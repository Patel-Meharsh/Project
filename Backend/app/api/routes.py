from contextlib import closing
from operator import inv

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Header as FHeader, Body, Request
from fastapi.responses import StreamingResponse, FileResponse, Response
import os
import uuid
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app import models
from app.config import settings
from app.auth import hash_password, verify_password, create_token, decode_token, needs_rehash
import io
import pandas as pd
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from typing import Optional
import datetime
import calendar
import json as _json
from datetime import date
from collections import defaultdict

router = APIRouter()

ROLE_HIERARCHY = {"super_admin": 4, "admin": 3, "analyst": 2, "observer": 1}


def _clean(data: dict, model_class) -> dict:
    """Strip keys that don't exist as columns on the model to avoid SQLAlchemy errors."""
    cols = {col.name for col in model_class.__table__.columns}
    return {k: v for k, v in data.items() if k in cols}


def _parse_dates(data: dict, fields: list):
    """Convert ISO date strings in `data` for the given field names in-place."""
    for f in fields:
        v = data.get(f)
        if v and isinstance(v, str):
            data[f] = datetime.date.fromisoformat(v)
        elif f in data and not v:
            data[f] = None


def _require_role(current_user, min_role: str):
    """Raise 403 if user doesn't meet the minimum role level."""
    if ROLE_HIERARCHY.get(current_user.role, 0) < ROLE_HIERARCHY.get(min_role, 0):
        raise HTTPException(403, f"{min_role.replace('_', ' ').title()}s only")


def _log(db: Session, event_type: str, entity: str, entity_id: str,
         location_code=None, item_code=None, vendor_code=None,
         qty=None, rate=None, before=None, after=None, meta=None,
         actor_id=None, actor_role=None):
    """Append one immutable event row. Never raises — silently skips on error."""
    try:
        row = models.EventLogModel(
            ts            = datetime.datetime.utcnow().isoformat(),
            event_type    = event_type,
            entity        = entity,
            entity_id     = str(entity_id),
            actor_id      = actor_id,
            actor_role    = actor_role,
            location_code = location_code,
            item_code     = item_code,
            vendor_code   = vendor_code,
            qty           = qty,
            rate          = rate,
            value         = round(float(qty or 0) * float(rate or 0), 4) if qty and rate else None,
            before_state  = _json.dumps(before)  if before is not None else None,
            after_state   = _json.dumps(after)   if after  is not None else None,
            meta          = _json.dumps(meta)     if meta   is not None else None,
        )
        db.add(row)
        db.flush()   # write in same transaction — no extra commit
    except Exception:
        pass          # logging must never break the main operation


def _is_active_user(value) -> bool:
    """Treat common legacy PostgreSQL string representations of active as active."""
    return str(value).strip().lower() in {"true", "1", "yes", "active"}


def _session_cookie_name() -> str:
    return "__Host-gg_session" if settings.ENVIRONMENT == "production" else "gg_session"


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        _session_cookie_name(),
        token,
        httponly=True,
        secure=settings.ENVIRONMENT == "production",
        samesite="lax",
        max_age=60 * 60 * 24 * 7,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(_session_cookie_name(), path="/")


def _get_current_user(request: Request, authorization: str = FHeader(default=""), db: Session = Depends(get_db)):
    # Cookie names differ between development and production. Read both explicitly;
    # FastAPI Cookie parameters otherwise look for a cookie named after the parameter.
    session_cookie = request.cookies.get("__Host-gg_session") or request.cookies.get("gg_session") or ""
    token = authorization.removeprefix("Bearer ").strip() or session_cookie.strip()
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.query(models.UserModel).filter(models.UserModel.id == payload.get("sub")).first()
    if not user or not _is_active_user(user.is_active):
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


def _inv_snapshot(inv) -> dict:
    """Serialisable snapshot of an InventoryModel row."""
    if not inv: return {}
    return {
        "item_code":     inv.item_code,
        "location_code": inv.location_code,
        "opening_stock": inv.opening_stock,
        "stock_in":      inv.stock_in,
        "stock_out":     inv.stock_out,
        "closing":       inv.opening_stock + inv.stock_in - inv.stock_out,
        "rate":          inv.rate,
    }

def _resolve_store(db: Session, location_code: str) -> str:
    """Resolve a SITE location to its parent STORE.
    SITE locations (CH-XX) never hold inventory — stock always lives at the STORE (STORE-CH).
    Returns the effective store location_code to use for inventory rows."""
    loc = (db.query(models.LocationModel)
             .filter_by(code=location_code)
             .first())
    if loc and loc.loc_type == "SITE" and loc.parent_store:
        return loc.parent_store
    return location_code


def _get_or_create_inv(db: Session, item_code: str, location_code: str,
                       vendor_code: str = "", rate: float = 0):
    """Return existing inventory row or create one with zeroes.
    Always operates on the STORE location — SITE locations are redirected
    to their parent_store so inventory is never created at a consumption site."""
    stock_location = _resolve_store(db, location_code)
    inv = (db.query(models.InventoryModel)
             .filter_by(item_code=item_code, location_code=stock_location)
             .first())
    if not inv:
        inv = models.InventoryModel(
            item_code=item_code, location_code=stock_location,
            vendor_code=vendor_code, rate=rate,
            opening_stock=0, stock_in=0, stock_out=0,
        )
        db.add(inv); db.flush()
    return inv

def _reverse_grn_stock(db: Session, grn, current_user=None):
    """Reverse all inventory changes made by a GRN before deleting it.
    Mirrors create_grn logic: decrements stock_in for each line item,
    reverses linked PO received_qty, and logs the deletion."""
    store_location = grn.store_location or ""
    if not store_location:
        return

    # Parse line items (same logic as create_grn)
    try:
        line_items = _json.loads(grn.line_items) if grn.line_items else []
    except Exception:
        line_items = []
    if not line_items and grn.item_code:
        line_items = [{"item_code": grn.item_code, "vendor_code": grn.vendor_code or "",
                       "accepted_qty": grn.accepted_qty or 0, "rate": grn.rate or 0}]

    stock_loc = _resolve_store(db, store_location)
    po_total_reversed = 0.0

    for li in line_items:
        item_code = li.get("item_code", "")
        accepted = float(li.get("accepted_qty") or 0)
        if not (accepted > 0 and item_code):
            continue
        inv = (db.query(models.InventoryModel)
                 .filter_by(item_code=item_code, location_code=stock_loc)
                 .first())
        if inv:
            snap = _inv_snapshot(inv)
            inv.stock_in = max(0, inv.stock_in - accepted)
            db.flush()
            _log(db, "grn.deleted", "grn", grn.grn_no,
                 location_code=stock_loc, item_code=item_code,
                 vendor_code=li.get("vendor_code", ""),
                 qty=-accepted, rate=float(li.get("rate") or 0),
                 before=snap, after=_inv_snapshot(inv),
                 meta={"grn_no": grn.grn_no, "reason": "grn_deleted"},
                 actor_id=current_user.id if current_user else None,
                 actor_role=current_user.role if current_user else None)
        po_total_reversed += accepted

    # Reverse linked PO received_qty
    if grn.po_no and po_total_reversed > 0:
        po = db.query(models.PurchaseOrderModel).filter_by(po_no=grn.po_no).first()
        if po:
            po.received_qty = max(0, (po.received_qty or 0) - po_total_reversed)
            po.balance_qty = max(0, (po.qty_ordered or 0) - po.received_qty)
            if po.received_qty == 0:
                po.status = "Sent to Vendor"
            elif po.balance_qty > 0:
                po.status = "Partial Received"
            db.flush()


def _reverse_issuance_stock(db: Session, iss, current_user=None):
    """Reverse inventory changes made by an issuance before deleting it.
    Decrements stock_out, reverses monthly budget actuals."""
    qty = float(iss.qty or 0)
    item_code = iss.item_code or ""
    location_code = iss.location_code or ""
    rate = float(iss.rate or 0)

    if not (qty > 0 and item_code and location_code):
        return

    stock_location = _resolve_store(db, location_code)
    inv = (db.query(models.InventoryModel)
             .filter_by(item_code=item_code, location_code=stock_location)
             .first())
    if inv:
        snap = _inv_snapshot(inv)
        inv.stock_out = max(0, inv.stock_out - qty)
        db.flush()
        _log(db, "issuance.deleted", "issuance", iss.issue_id,
             location_code=location_code, item_code=item_code,
             qty=-qty, rate=rate, before=snap, after=_inv_snapshot(inv),
             meta={"reason": "issuance_deleted", "department": iss.department},
             actor_id=current_user.id if current_user else None,
             actor_role=current_user.role if current_user else None)

    # Reverse monthly budget actuals
    month = iss.month
    if month:
        budget = (db.query(models.MonthlyBudgetModel)
                    .filter_by(item_code=item_code, location_code=location_code, month=month)
                    .first())
        if budget:
            budget.actual_qty = max(0, (budget.actual_qty or 0) - qty)
            budget.actual_value = max(0, (budget.actual_value or 0) - qty * rate)
            db.flush()


@router.post("/admin/run-fix")
def run_fix(current_user: models.UserModel = Depends(_get_current_user)):
    if ROLE_HIERARCHY.get(current_user.role, 0) < 4:
        raise HTTPException(403, "Super admins only")
    return {"status": "skipped", "message": "Run 'python fix_grn_values.py' manually on the server for safety."}

# ─── DASHBOARD ────────────────────────────────────────────────────────────────
@router.get("/dashboard/kpis")
def dashboard_kpis(db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    pending_prs  = db.query(models.PurchaseRequisitionModel).filter(models.PurchaseRequisitionModel.status.in_(["Draft","Submitted"])).count()
    open_pos     = db.query(models.PurchaseOrderModel).filter(models.PurchaseOrderModel.status.in_(["Sent to Vendor","Partial Received","Acknowledged"])).count()
    pending_grns = db.query(models.GRNModel).filter(models.GRNModel.status == "Pending Inspection").count()
    active_vendors = db.query(models.VendorModel).filter(models.VendorModel.status == "Active").count()
    total_items  = db.query(models.ItemModel).filter(models.ItemModel.status == "Active").count()
    hk_total     = db.query(models.HKMasterModel).count()
    inv = db.query(models.InventoryModel).all()
    items = db.query(models.ItemModel).all()
    item_map = {i.code: i for i in items}
    item_rate_map = {i.code: (i.rate or 0) for i in items}
    stock_value = sum(
        max((r.opening_stock + r.stock_in - r.stock_out), 0)
        * (r.rate if (r.rate and r.rate > 0) else item_rate_map.get(r.item_code, 0))
        for r in inv
    )
    # below_rol: aggregate closing per item across all locations, compare best closing to ROL
    item_best_closing: dict = defaultdict(float)
    for r in inv:
        closing = r.opening_stock + r.stock_in - r.stock_out
        item_best_closing[r.item_code] = max(item_best_closing[r.item_code], closing)
    below_rol = sum(
        1 for code, best in item_best_closing.items()
        if (item_map.get(code) and best <= item_map[code].rol)
    )
    ytd_po = db.query(func.sum(models.PurchaseOrderModel.qty_ordered * models.PurchaseOrderModel.rate)).scalar() or 0
    iss = db.query(models.IssuanceLogModel).all()
    monthly = {m: 0 for m in range(1, 13)}
    for i in iss:
        k = i.month; monthly[k] = monthly.get(k, 0) + (i.qty * i.rate)
    # Reorder alerts — aggregate best closing per item across all locations
    reorder_items = []
    for code, best in item_best_closing.items():
        item = item_map.get(code)
        if item and best <= item.rol:
            reorder_items.append({"code": code, "name": item.name, "category": item.category, "closing": best, "rol": item.rol, "shortfall": item.rol - best, "location": "all"})
    return {
        "pending_prs": pending_prs, "open_pos": open_pos,
        "pending_grns": pending_grns, "active_vendors": active_vendors,
        "total_items": total_items, "hk_total": hk_total,
        "stock_value": round(stock_value, 2), "below_rol": below_rol,
        "ytd_po_value": round(float(ytd_po), 2),
        "monthly_spend": [{"month": k, "value": round(v,2)} for k,v in sorted(monthly.items())],
        "reorder_alerts": reorder_items,
    }

@router.get("/dashboard/spend-by-category")
def spend_by_category(db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    iss = db.query(models.IssuanceLogModel).all()
    items = {i.code: i for i in db.query(models.ItemModel).all()}
    cat_map = {}
    for i in iss:
        item = items.get(i.item_code)
        cat = (item.category if item and item.category else "Other")
        value = (i.qty or 0) * (i.rate or 0)
        cat_map[cat] = cat_map.get(cat, 0) + value
    return [{"category": k, "value": round(v,2)} for k,v in sorted(cat_map.items(), key=lambda x: -x[1])]

@router.get("/dashboard/spend-by-location")
def spend_by_location(
    db: Session = Depends(get_db),
    current_user: models.UserModel = Depends(_get_current_user)):
    rows, _ = _compute_budget(db)

    # Aggregate per location
    loc_totals = {}
    for r in rows:
        for loc_code, data in r["locations"].items():
            loc_totals.setdefault(loc_code, 0)
            loc_totals[loc_code] += data["value"]

    # Fetch location metadata
    locs = {l.code: l for l in db.query(models.LocationModel).all()}

    result = []
    for loc_code, total in loc_totals.items():
        loc = locs.get(loc_code)

        result.append({
            "location": loc_code,
            "name": loc.name if loc else loc_code,
            "headcount": loc.headcount if loc else 0,
            "area": loc.area_sqft if loc else 0,
            "monthly_budget": round(total, 0)
        })

    return sorted(result, key=lambda x: -x["monthly_budget"])

# ─── LOCATIONS ────────────────────────────────────────────────────────────────
@router.get("/locations")
def get_locations(db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    locs = db.query(models.LocationModel).all()
    result = []
    for loc in locs:
        try:
            services = db.query(models.ThirdPartyServiceModel).filter(
                models.ThirdPartyServiceModel.location_code == loc.code,
                models.ThirdPartyServiceModel.status == "Active"
            ).all()
            svc_list = [{"id":s.id,"service_type":s.service_type,"vendor_name":s.vendor_name,"monthly_cost":s.monthly_cost,"status":s.status,"scope":s.scope} for s in services]
        except Exception:
            svc_list = []
        d = {c.name: getattr(loc, c.name) for c in loc.__table__.columns}
        d["third_party_services"] = svc_list
        result.append(d)
    return result

@router.get("/locations/{code}")
def get_location(code: str, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    loc = db.query(models.LocationModel).filter(models.LocationModel.code == code).first()
    if not loc: raise HTTPException(404)
    services = db.query(models.ThirdPartyServiceModel).filter(models.ThirdPartyServiceModel.location_code == code).all()
    d = {c.name: getattr(loc,c.name) for c in loc.__table__.columns}
    d["third_party_services"] = [{"id":s.id,"service_type":s.service_type,"vendor_name":s.vendor_name,"monthly_cost":s.monthly_cost,"contract_start":str(s.contract_start),"contract_end":str(s.contract_end),"scope":s.scope,"status":s.status,"vendor_contact":s.vendor_contact} for s in services]
    return d

@router.put("/locations/{code}")
def update_location(code: str, data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    loc = db.query(models.LocationModel).filter(models.LocationModel.code == code).first()
    if not loc: raise HTTPException(404)
    for k, v in data.items():
        if hasattr(loc, k): setattr(loc, k, v)
    db.commit(); db.refresh(loc); return loc

@router.post("/locations")
def create_location(data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    loc = models.LocationModel(**{k:v for k,v in data.items() if hasattr(models.LocationModel, k)})
    db.add(loc); db.commit(); db.refresh(loc); return loc

@router.post("/locations/{code}/services")
def add_service(code: str, data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    _parse_dates(data, ["contract_start", "contract_end"])
    svc = models.ThirdPartyServiceModel(location_code=code, **{k:v for k,v in data.items() if hasattr(models.ThirdPartyServiceModel,k) and k!='id'})
    db.add(svc); db.commit(); db.refresh(svc); return svc

@router.put("/locations/{code}/services/{svc_id}")
def update_service(code: str, svc_id: int, data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    svc = db.query(models.ThirdPartyServiceModel).filter(models.ThirdPartyServiceModel.id == svc_id).first()
    if not svc: raise HTTPException(404)
    for k, v in data.items():
        if hasattr(svc, k): setattr(svc, k, v)
    db.commit(); db.refresh(svc); return svc

# ─── VENDORS ──────────────────────────────────────────────────────────────────
@router.get("/vendors")
def get_vendors(db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    return db.query(models.VendorModel).all()

@router.post("/vendors")
def create_vendor(data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    v = models.VendorModel(**data); db.add(v); db.commit(); db.refresh(v); return v

@router.put("/vendors/{code}")
def update_vendor(code: str, data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    v = db.query(models.VendorModel).filter(models.VendorModel.code == code).first()
    if not v: raise HTTPException(404)
    for k, val in data.items():
        if hasattr(v, k): setattr(v, k, val)
    db.commit(); db.refresh(v); return v

# ─── HK MASTER ────────────────────────────────────────────────────────────────
@router.get("/hk-master")
def get_hk_master(category: Optional[str] = None, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    q = db.query(models.HKMasterModel)
    if category: q = q.filter(models.HKMasterModel.category == category)
    return q.all()

@router.post("/hk-master")
def create_hk_item(data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    item = models.HKMasterModel(**{k: v for k, v in data.items() if hasattr(models.HKMasterModel, k)})
    db.add(item); db.commit(); db.refresh(item); return item

@router.get("/hk-master/categories")
def get_hk_categories(db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    rows = db.query(models.HKMasterModel.category).distinct().all(); return [r[0] for r in rows]

@router.put("/hk-master/{code}")
def update_hk_item(code: str, data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    item = db.query(models.HKMasterModel).filter(models.HKMasterModel.code == code).first()
    if not item: raise HTTPException(404)
    for k, v in data.items():
        if hasattr(item, k): setattr(item, k, v)
    db.commit(); db.refresh(item); return item

# ─── ITEMS ────────────────────────────────────────────────────────────────────
def _resolve_master_group(data: dict, db: Session):
    """Resolve master_group_id from either master_group_id or master_group string."""
    mg_id = data.get("master_group_id")
    mg_name = data.get("master_group", "")
    if mg_id:
        return  # Already has FK
    if mg_name:
        grp = db.query(models.MasterGroupModel).filter_by(name=mg_name).first()
        if grp:
            data["master_group_id"] = grp.id

@router.get("/items")
def get_items(category: Optional[str] = None, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    q = db.query(models.ItemModel)
    if category: q = q.filter(models.ItemModel.category == category)
    items = q.all()
    # Build master_group name lookup
    mg_map = {g.id: g.name for g in db.query(models.MasterGroupModel).all()}
    result = []
    for i in items:
        d = {c.name: getattr(i, c.name) for c in i.__table__.columns}
        # Always include resolved group name
        d["master_group_name"] = mg_map.get(i.master_group_id, i.master_group or "")
        result.append(d)
    return result

@router.post("/items")
def create_item(data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    _resolve_master_group(data, db)
    item = models.ItemModel(**_clean(data, models.ItemModel))
    db.add(item); db.commit(); db.refresh(item); return item

@router.put("/items/{code}")
def update_item(code: str, data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    item = db.query(models.ItemModel).filter(models.ItemModel.code == code).first()
    if not item: raise HTTPException(404)
    _resolve_master_group(data, db)
    for k, v in data.items():
        if hasattr(item, k): setattr(item, k, v)
    db.commit(); db.refresh(item); return item

# ─── INVENTORY ────────────────────────────────────────────────────────────────
@router.get("/inventory")
def get_inventory(location: Optional[str] = None, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    q = db.query(models.InventoryModel)
    if location: q = q.filter(models.InventoryModel.location_code == location)
    rows = q.all()
    items    = {i.code: i for i in db.query(models.ItemModel).all()}
    loc_map  = {l.code: l for l in db.query(models.LocationModel).all()}
    result = []
    for r in rows:
        loc = loc_map.get(r.location_code)
        # Only expose STORE-level rows — SITE rows should not exist after cleanup
        # but guard here to ensure they never surface in the stock register.
        if loc and loc.loc_type == "SITE":
            continue
        item = items.get(r.item_code)
        closing = r.opening_stock + r.stock_in - r.stock_out
        rol = item.rol if item else 0
        if closing < 0:
            st = "Negative Stock"
        elif item and closing <= rol:
            st = "Below ROL"
        else:
            st = "OK"
        effective_rate = r.rate if (r.rate and r.rate > 0) else (item.rate if item else 0)
        result.append({"id":r.id,"item_code":r.item_code,"item_name":item.name if item else r.item_code,"category":item.category if item else "","uom":item.uom if item else "","location_code":r.location_code,"vendor_code":r.vendor_code,"rate":effective_rate,"opening_stock":r.opening_stock,"stock_in":r.stock_in,"stock_out":r.stock_out,"closing_stock":closing,"rol":rol,"max_stock":item.max_stock if item else 0,"stock_value":round(max(closing,0)*effective_rate,2),"status":st,"last_grn_no":r.last_grn_no or ""})
    return result


@router.get("/inventory/{item_code}/stock-history")
def stock_history(item_code: str, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    """Return stock movement history for an item from the event log."""
    events = (db.query(models.EventLogModel)
                .filter(models.EventLogModel.item_code == item_code,
                        models.EventLogModel.event_type.in_(["grn.created", "grn.deleted", "grn.updated",
                                                              "issuance.created", "issuance.deleted",
                                                              "return.created"]))
                .order_by(models.EventLogModel.ts.desc())
                .limit(100)
                .all())
    return [{c.name: getattr(e, c.name) for c in models.EventLogModel.__table__.columns} for e in events]


@router.get("/inventory/consumption")
def get_consumption(db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    """Consumption view: issuances aggregated per (item_code, location_code) for SITE locations."""
    issuances = db.query(models.IssuanceLogModel).all()
    items     = {i.code: i for i in db.query(models.ItemModel).all()}
    agg: dict = {}   # (item_code, location_code) → row dict
    for iss in issuances:
        key = (iss.item_code, iss.location_code)
        item = items.get(iss.item_code)
        rate = iss.rate or (item.rate if item else 0)
        if key not in agg:
            agg[key] = {
                "item_code": iss.item_code,
                "item_name": item.name if item else iss.item_code,
                "category":  item.category if item else "",
                "uom":       item.uom if item else "",
                "location_code": iss.location_code,
                "consumed_qty": 0.0,
                "consumed_value": 0.0,
            }
        agg[key]["consumed_qty"]   += float(iss.qty or 0)
        agg[key]["consumed_value"] += float(iss.qty or 0) * float(rate)
    result = sorted(agg.values(), key=lambda x: (x["item_code"], x["location_code"]))
    for r in result:
        r["consumed_value"] = round(r["consumed_value"], 2)
    return result

@router.post("/inventory")
def create_inventory_row(data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    existing = db.query(models.InventoryModel).filter_by(
        item_code=data.get("item_code"),
        location_code=data.get("location_code", "STORE-CH")
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Inventory row already exists for this item + location")
    row = models.InventoryModel(**_clean(data, models.InventoryModel))
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id}

@router.put("/inventory/{inv_id}")
def update_inventory_row(inv_id: int, data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    row = db.query(models.InventoryModel).filter(models.InventoryModel.id == inv_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Inventory row not found")
    cleaned = _clean(data, models.InventoryModel)
    for field in ("opening_stock", "stock_in", "stock_out", "rate"):
        if field in cleaned and float(cleaned[field] or 0) < 0:
            raise HTTPException(400, f"{field} cannot be negative.")
    for k, v in cleaned.items():
        setattr(row, k, v)
    db.commit(); db.refresh(row)
    return {"id": row.id}

@router.patch("/inventory/{inv_id}/reset")
def reset_inventory_row(inv_id: int, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    """Reset stock_in and stock_out to zero. Row, item, location, opening_stock are untouched."""
    row = db.query(models.InventoryModel).filter(models.InventoryModel.id == inv_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Row not found")
    row.stock_in = 0
    row.stock_out = 0
    db.commit(); db.refresh(row)
    return {"id": row.id, "reset": True}

# ─── PURCHASE REQUISITIONS ────────────────────────────────────────────────────
@router.get("/purchase-requisitions")
def get_prs(status: Optional[str] = None, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    q = db.query(models.PurchaseRequisitionModel)
    if status: q = q.filter(models.PurchaseRequisitionModel.status == status)
    prs = q.order_by(models.PurchaseRequisitionModel.pr_date.desc()).all()
    items = {i.code: i for i in db.query(models.ItemModel).all()}
    result = []
    for pr in prs:
        item = items.get(pr.item_code)
        try:
            li_parsed = _json.loads(pr.line_items) if getattr(pr, 'line_items', None) else []
        except Exception:
            li_parsed = []
        result.append({"pr_no":pr.pr_no,"pr_date":str(pr.pr_date) if pr.pr_date else None,"item_code":pr.item_code,"req_qty":pr.req_qty,"location_code":pr.location_code,"department":pr.department,"requested_by":pr.requested_by,"priority":pr.priority,"required_date":str(pr.required_date) if pr.required_date else None,"justification":pr.justification,"status":pr.status,"approved_by":pr.approved_by,"approval_date":str(pr.approval_date) if pr.approval_date else None,"po_ref":pr.po_ref,"item_name":item.name if item else pr.item_code,"category":item.category if item else "","uom":item.uom if item else "","rate":item.rate if item else 0,"est_value":(pr.req_qty or 0)*(item.rate if item else 0),"line_items":li_parsed})
    return result

@router.post("/purchase-requisitions")
def create_pr(data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "analyst")
    line_items = data.pop("line_items", None) or []
    if any(float(li.get("qty") or 0) <= 0 for li in line_items):
        raise HTTPException(400, "All PR quantities must be greater than zero.")
    if data.get("req_qty") is not None and float(data.get("req_qty") or 0) < 0:
        raise HTTPException(400, "Request quantity cannot be negative.")
    # Backward compat: populate top-level item_code/req_qty from first line item
    if line_items:
        first = line_items[0]
        if not data.get("item_code"): data["item_code"] = first.get("item_code", "")
        data["req_qty"] = sum(float(li.get("qty") or 0) for li in line_items)
        data["line_items"] = _json.dumps(line_items)
    _parse_dates(data, ["pr_date", "required_date", "approval_date"])
    pr = models.PurchaseRequisitionModel(**_clean(data, models.PurchaseRequisitionModel))
    db.add(pr); db.commit(); db.refresh(pr); return pr

@router.put("/purchase-requisitions/{pr_no}")
def update_pr(pr_no: str, data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "analyst")
    pr = db.query(models.PurchaseRequisitionModel).filter(models.PurchaseRequisitionModel.pr_no == pr_no).first()
    if not pr: raise HTTPException(404)
    # Only admin+ can approve or reject (case-insensitive check)
    new_status = data.get("status", "")
    if new_status and new_status.strip().lower() in ("approved", "rejected"):
        _require_role(current_user, "admin")
    # Serialize line_items if provided as a list
    if "line_items" in data and isinstance(data["line_items"], list):
        li = data["line_items"]
        data["line_items"] = _json.dumps(li)
        # Update backward-compat fields from line items
        if li:
            data.setdefault("item_code", li[0].get("item_code", ""))
            data["req_qty"] = sum(float(x.get("qty") or 0) for x in li)
    _parse_dates(data, ["pr_date", "required_date", "approval_date"])
    for k, v in data.items():
        if hasattr(pr, k) and k != "_sa_instance_state": setattr(pr, k, v)
    db.commit(); db.refresh(pr); return pr

# ─── PURCHASE ORDERS ──────────────────────────────────────────────────────────
@router.get("/purchase-orders")
def get_pos(status: Optional[str] = None, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    q = db.query(models.PurchaseOrderModel)
    if status: q = q.filter(models.PurchaseOrderModel.status == status)
    pos = q.order_by(models.PurchaseOrderModel.po_date.desc()).all()
    vendors = {v.code: v for v in db.query(models.VendorModel).all()}
    items = {i.code: i for i in db.query(models.ItemModel).all()}
    result = []
    for po in pos:
        vendor = vendors.get(po.vendor_code); item = items.get(po.item_code)
        amount = (po.qty_ordered or 0) * (po.rate or 0)
        gst_amt = amount * (po.gst_pct or 0) / 100
        li_parsed = []
        try:
            li_parsed = _json.loads(po.line_items) if po.line_items else []
        except Exception:
            li_parsed = []
        if li_parsed:
            amount = sum(float(li.get("qty") or 0) * float(li.get("rate") or 0) for li in li_parsed)
            gst_amt = sum(float(li.get("qty") or 0) * float(li.get("rate") or 0) * float(li.get("gst_pct") or po.gst_pct or 0) / 100 for li in li_parsed)
        total = amount + gst_amt
        result.append({
            "po_no":po.po_no, "po_date":str(po.po_date) if po.po_date else None,
            "pr_ref":po.pr_ref, "vendor_code":po.vendor_code, "item_code":po.item_code,
            "uom":po.uom, "qty_ordered":po.qty_ordered, "rate":po.rate, "gst_pct":po.gst_pct,
            "delivery_date":str(po.delivery_date) if po.delivery_date else None,
            "delivery_location":po.delivery_location, "terms":po.terms,
            "subject": getattr(po, 'subject', '') or "",
            "contact_person": getattr(po, 'contact_person', '') or "",
            "status":po.status, "po_type": getattr(po, 'po_type', '') or "Routine",
            "received_qty":po.received_qty, "balance_qty":po.balance_qty,
            "vendor_name":vendor.name if vendor else po.vendor_code,
            "item_name":item.name if item else po.item_code,
            "amount":round(amount,2), "gst_amt":round(gst_amt,2), "total":round(total,2),
            "line_items":li_parsed,
        })
    return result

@router.post("/purchase-orders")
def create_po(data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "analyst")
    line_items = data.pop("line_items", None) or []
    if any(float(li.get("qty") or 0) <= 0 for li in line_items):
        raise HTTPException(400, "All PO quantities must be greater than zero.")
    if data.get("qty_ordered") is not None and float(data.get("qty_ordered") or 0) < 0:
        raise HTTPException(400, "Ordered quantity cannot be negative.")
    if line_items:
        first = line_items[0]
        if not data.get("item_code"): data["item_code"] = first.get("item_code", "")
        data["qty_ordered"] = sum(float(li.get("qty") or 0) for li in line_items)
        data["rate"] = float(first.get("rate") or 0)
        data["line_items"] = _json.dumps(line_items)
    _parse_dates(data, ["po_date", "delivery_date"])
    po = models.PurchaseOrderModel(**_clean(data, models.PurchaseOrderModel))
    db.add(po); db.commit(); db.refresh(po); return po

@router.put("/purchase-orders/{po_no}")
def update_po(po_no: str, data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "analyst")
    po = db.query(models.PurchaseOrderModel).filter(models.PurchaseOrderModel.po_no == po_no).first()
    if not po: raise HTTPException(404)
    if "status" in data:
        _require_role(current_user, "admin")
    for k, v in data.items():
        if hasattr(po, k) and k not in ("_sa_instance_state", "po_no"):
            setattr(po, k, v)
    db.commit(); db.refresh(po); return po

@router.post("/purchase-orders/from-pr/{pr_no}")
def create_po_from_pr(pr_no: str, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    """Convert an approved PR into a new PO. Auto-fills item, qty, location from PR."""
    _require_role(current_user, "admin")
    pr = db.query(models.PurchaseRequisitionModel).filter_by(pr_no=pr_no).first()
    if not pr:
        raise HTTPException(404, "PR not found")
    if pr.status == "Converted to PO":
        raise HTTPException(400, f"PR {pr_no} has already been converted to PO {pr.po_ref or '?'}")
    if pr.status != "Approved":
        raise HTTPException(400, "Only approved PRs can be converted to PO")

    # Parse PR line items (if multi-item) or build from single item
    try:
        pr_line_items = _json.loads(pr.line_items) if pr.line_items else []
    except Exception:
        pr_line_items = []
    items_map = {i.code: i for i in db.query(models.ItemModel).all()}

    if not pr_line_items and pr.item_code:
        item = items_map.get(pr.item_code)
        pr_line_items = [{"item_code": pr.item_code, "item_name": item.name if item else pr.item_code,
                          "qty": pr.req_qty, "uom": item.uom if item else "", "rate": item.rate if item else 0}]

    # Build PO line items from PR line items
    po_line_items = []
    vendor_code = ""
    for li in pr_line_items:
        item = items_map.get(li.get("item_code", ""))
        if item and item.vendor_code and not vendor_code:
            vendor_code = item.vendor_code
        po_line_items.append({
            "item_code": li.get("item_code", ""),
            "description": li.get("item_name", "") or (item.name if item else ""),
            "qty": float(li.get("qty") or 0),
            "uom": li.get("uom", "") or (item.uom if item else ""),
            "rate": float(li.get("rate") or (item.rate if item else 0)),
            "gst_pct": float(item.gst_pct if item else 18),
        })

    if not po_line_items:
        raise HTTPException(400, "PR has no valid line items to convert")

    first_item = items_map.get(pr.item_code)
    total_qty = sum(float(li.get("qty") or 0) for li in po_line_items)

    # Generate PO number
    po_rows = db.query(models.PurchaseOrderModel.po_no).all()
    nums = []
    for (val,) in po_rows:
        try: nums.append(int(str(val).replace("PO-", "").split("-")[-1]))
        except: pass
    next_n = (max(nums) + 1) if nums else 1
    po_no = f"PO-{str(next_n).zfill(3)}"

    po = models.PurchaseOrderModel(
        po_no=po_no,
        po_date=datetime.date.today(),
        pr_ref=pr.pr_no,
        vendor_code=vendor_code,
        item_code=pr.item_code,
        uom=first_item.uom if first_item else "",
        qty_ordered=total_qty,
        rate=float(po_line_items[0]["rate"]) if po_line_items else 0,
        gst_pct=float(po_line_items[0].get("gst_pct", 18)) if po_line_items else 18,
        delivery_location=pr.location_code or "STORE-CH",
        status="Draft",
        po_type="Routine",
        balance_qty=total_qty,
        line_items=_json.dumps(po_line_items) if po_line_items else None,
    )
    db.add(po); db.flush()

    # Update PR to reflect conversion
    pr.status = "Converted to PO"
    pr.po_ref = po_no
    db.commit()
    db.refresh(po)
    return {"po_no": po.po_no, "message": f"PO created from {pr_no}"}

@router.get("/purchase-orders/{po_no}/grn-prefill")
def grn_prefill_from_po(po_no: str, db: Session = Depends(get_db),
                         current_user: models.UserModel = Depends(_get_current_user)):
    """Return PO header + line items enriched with per-line remaining_qty for GRN
    inwarding. Remaining is computed by subtracting accepted_qty from prior GRNs
    against the same PO + item_code, so partial GRNs default to what's actually left."""
    po = db.query(models.PurchaseOrderModel).filter_by(po_no=po_no).first()
    if not po:
        raise HTTPException(404, "PO not found")

    try:
        po_lines = _json.loads(po.line_items) if po.line_items else []
    except Exception:
        po_lines = []
    if not po_lines and po.item_code:
        po_lines = [{
            "item_code": po.item_code, "description": "",
            "qty": float(po.qty_ordered or 0), "uom": po.uom or "",
            "rate": float(po.rate or 0), "gst_pct": float(po.gst_pct or 0),
        }]

    received_per_item: dict = {}
    for g in db.query(models.GRNModel).filter_by(po_no=po_no).all():
        try:
            g_lines = _json.loads(g.line_items) if g.line_items else []
        except Exception:
            g_lines = []
        if not g_lines and g.item_code:
            g_lines = [{"item_code": g.item_code, "accepted_qty": g.accepted_qty or 0}]
        for gli in g_lines:
            ic = gli.get("item_code", "")
            if ic:
                received_per_item[ic] = received_per_item.get(ic, 0.0) + float(gli.get("accepted_qty") or 0)

    vendor = db.query(models.VendorModel).filter_by(code=po.vendor_code).first() if po.vendor_code else None
    items_map = {i.code: i for i in db.query(models.ItemModel).all()}

    enriched = []
    for li in po_lines:
        ic = li.get("item_code", "")
        if not ic:
            continue
        ordered = float(li.get("qty") or 0)
        already = received_per_item.get(ic, 0.0)
        remaining = max(0.0, ordered - already)
        if remaining <= 0:
            continue
        item = items_map.get(ic)
        enriched.append({
            "item_code": ic,
            "item_name": (item.name if item else li.get("description", "") or ic),
            "qty_ordered": ordered,
            "qty_received_prior": already,
            "remaining_qty": remaining,
            "uom": li.get("uom", "") or (item.uom if item else ""),
            "rate": float(li.get("rate") or (item.rate if item else 0)),
        })

    return {
        "po_no": po.po_no,
        "vendor_code": po.vendor_code or "",
        "vendor_name": vendor.name if vendor else (po.vendor_code or ""),
        "delivery_location": po.delivery_location or "",
        "line_items": enriched,
    }

@router.get("/purchase-orders/{po_no}/pdf")
def generate_po_pdf(po_no: str, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    """Generate PO PDF matching the NINtec AMC Work Order reference format exactly."""
    import base64, os as _os

    po = db.query(models.PurchaseOrderModel).filter_by(po_no=po_no).first()
    if not po: raise HTTPException(404, "PO not found")
    vendor = db.query(models.VendorModel).filter_by(code=po.vendor_code).first()
    items_map = {i.code: i for i in db.query(models.ItemModel).all()}

    # ── Build line items ─────────────────────────────────────────────────────
    try:
        line_items = _json.loads(po.line_items) if po.line_items else []
    except Exception:
        line_items = []
    if not line_items and po.item_code:
        item = items_map.get(po.item_code)
        line_items = [{"item_code": po.item_code, "description": item.name if item else po.item_code,
                       "qty": po.qty_ordered or 0, "uom": po.uom or (item.uom if item else ""),
                       "rate": po.rate or 0, "gst_pct": po.gst_pct or 18}]

    subtotal = sum(float(li.get("qty") or 0) * float(li.get("rate") or 0) for li in line_items)
    total_gst = sum(float(li.get("qty") or 0) * float(li.get("rate") or 0) * float(li.get("gst_pct") or 0) / 100 for li in line_items)
    grand_total = subtotal + total_gst

    # ── Load logo as base64 ──────────────────────────────────────────────────
    logo_b64 = ""
    _base = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    for lp in [_os.path.join(_base, "static", "logo_extracted.jpeg"),
               _os.path.join(_base, "static", "logo.png"),
               _os.path.join(_os.getcwd(), "app", "static", "logo_extracted.jpeg")]:
        if _os.path.exists(lp):
            with open(lp, "rb") as lf:
                ext = "jpeg" if lp.endswith(".jpeg") or lp.endswith(".jpg") else "png"
                logo_b64 = f"data:image/{ext};base64," + base64.b64encode(lf.read()).decode()
            break

    # ── Vendor details ───────────────────────────────────────────────────────
    v_name = vendor.name if vendor else po.vendor_code
    v_address = getattr(vendor, 'address', '') or "" if vendor else ""
    v_city = vendor.city if vendor else ""
    v_phone = vendor.phone if vendor else ""
    v_email = vendor.email if vendor else ""
    v_contact = po.contact_person or (vendor.contact_person if vendor else "")
    v_contact_phone = vendor.phone if vendor else ""
    v_gst = vendor.gst_no if vendor else ""
    po_subject = po.subject or "Purchase Order"
    po_date_str = po.po_date.strftime("%d %B %Y") if po.po_date else "-"
    delivery_loc = po.delivery_location or "STORE-CH"
    payment_terms = po.terms or "As per agreement"
    po_type_label = po.po_type or "Routine"

    # ── Build item rows ──────────────────────────────────────────────────────
    item_rows_html = ""
    for idx, li in enumerate(line_items, 1):
        q = float(li.get("qty") or 0)
        r = float(li.get("rate") or 0)
        desc = li.get("description", "") or li.get("item_name", "") or li.get("item_code", "")
        amt = q * r
        item_rows_html += f"""<tr>
            <td style="text-align:center;">{idx}</td>
            <td style="text-align:left;">{desc}</td>
            <td style="text-align:center;">{q:g}</td>
            <td style="text-align:center;">{li.get('uom','Nos')}</td>
            <td style="text-align:right;">{r:,.2f}</td>
            <td style="text-align:right;">{amt:,.2f}</td>
        </tr>"""

    # ── Ref number ───────────────────────────────────────────────────────────
    fy_start = po.po_date.year if po.po_date and po.po_date.month >= 4 else (po.po_date.year - 1 if po.po_date else 2025)
    ref_no = f"PO/{po_type_label[:3].upper()}/CH/{po.po_no.replace('PO-','')}/{fy_start}-{fy_start+1}"

    # ── FULL HTML ────────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
@page {{ size: A4; margin: 18mm 20mm 18mm 20mm; }}
body {{ font-family: Arial, Helvetica, sans-serif; font-size: 11pt; color: #000; margin:0; padding:0; }}
.page {{ page-break-after: always; padding: 0; }}
.page:last-child {{ page-break-after: auto; }}

/* ── Header (repeated on every page) ── */
.hdr {{ padding-bottom: 8px; border-bottom: 1.5px solid #000; margin-bottom: 18px; }}
.hdr-row {{ display: table; width: 100%; }}
.hdr-left {{ display: table-cell; vertical-align: top; }}
.hdr-right {{ display: table-cell; vertical-align: top; text-align: right; width: 90px; }}
.hdr-company {{ font-size: 16pt; font-weight: bold; }}
.hdr-sub {{ font-size: 8pt; color: #333; margin-top: 3px; line-height: 1.5; }}
.hdr-logo {{ width: 80px; height: auto; }}

/* ── Footer ── */
.ftr {{ border-top: 1px solid #000; margin-top: 24px; padding-top: 5px; text-align: right; font-size: 7.5pt; color: #444; }}

/* ── Body elements ── */
.date {{ font-weight: bold; margin-bottom: 14px; }}
.to-block {{ margin-bottom: 14px; line-height: 1.6; }}
.ref {{ font-weight: bold; margin-bottom: 10px; }}
.attn {{ font-weight: bold; margin-bottom: 14px; }}
.subject {{ text-align: center; font-weight: bold; text-decoration: underline; margin-bottom: 14px; font-size: 11pt; }}
.intro {{ margin-bottom: 14px; line-height: 1.6; font-size: 10pt; }}

/* ── Table ── */
table.items {{ width: 100%; border-collapse: collapse; margin-bottom: 18px; font-size: 10pt; }}
table.items thead tr {{ background: #1e3a5f; color: #fff; }}
table.items thead th {{ padding: 8px 6px; border: 1px solid #1e3a5f; text-align: center; font-weight: bold; font-size: 9pt; }}
table.items tbody td {{ padding: 7px 6px; border: 1px solid #ccc; }}
table.items tbody tr:nth-child(even) {{ background: #f5f5f5; }}
.total-row td {{ font-weight: bold; background: #eef2f7 !important; }}

/* ── Terms ── */
.terms-title {{ font-weight: bold; text-decoration: underline; margin-bottom: 8px; font-size: 10pt; }}
.terms-list {{ list-style: none; padding: 0; line-height: 1.8; font-size: 10pt; }}
.terms-list li {{ padding-left: 28px; position: relative; margin-bottom: 5px; }}
.terms-list li .n {{ position: absolute; left: 0; font-weight: normal; }}

.signatory {{ margin-top: 36px; line-height: 1.8; font-size: 10pt; }}
.signatory .cg {{ font-style: italic; font-size: 8.5pt; color: #555; }}

.gen-terms ol {{ padding-left: 20px; font-size: 10pt; line-height: 1.7; }}
.gen-terms li {{ margin-bottom: 8px; }}
.gen-terms ol ol {{ margin-top: 4px; }}
</style></head><body>

<!-- ═══════════════════ PAGE 1 ═══════════════════ -->
<div class="page">
  <div class="hdr">
    <div class="hdr-row">
      <div class="hdr-left">
        <div class="hdr-company">Gateway Group</div>
        <div class="hdr-sub">
          B-11, Corporate House, Bodakdev, S.G. Highway, Ahmedabad &ndash; 380054, Gujarat<br>
          Tel: +91 79 40393909 | Email: admin@thegatewaygroup.com | www.thegatewaygroup.com
        </div>
      </div>
      {'<div class="hdr-right"><img src="' + logo_b64 + '" class="hdr-logo"></div>' if logo_b64 else ''}
    </div>
  </div>

  <div class="date">Date: {po_date_str}</div>

  <div class="to-block">
    To,<br>
    <strong>{v_name}</strong><br>
    {(v_address.replace(chr(10), '<br>') + '<br>') if v_address else ((v_city + '<br>') if v_city else '')}
    {('Tel: ' + v_phone) if v_phone else ''}
  </div>

  <div class="ref">Ref. {ref_no}</div>

  {f'<div class="attn">Kind Attn: {v_contact}{(" - " + v_contact_phone) if v_contact_phone else ""}</div>' if v_contact else ''}

  <div class="subject">Subject: {po_subject}</div>

  <div class="intro">
    With reference to your quotation and our discussions, we are pleased to place our Purchase Order as per the details below.
  </div>

  <table class="items">
    <thead><tr>
      <th style="width:35px;">Sr.no</th>
      <th style="text-align:left;">Description</th>
      <th style="width:40px;">Qty</th>
      <th style="width:45px;">UOM</th>
      <th style="width:80px;">Rate (&#8377;)</th>
      <th style="width:90px;">Amount (&#8377;)</th>
    </tr></thead>
    <tbody>
      {item_rows_html}
      <tr class="total-row">
        <td colspan="5" style="text-align:right;">Total Amount (excl. GST)</td>
        <td style="text-align:right;">&#8377;{subtotal:,.2f}</td>
      </tr>
      <tr class="total-row">
        <td colspan="5" style="text-align:right;">GST</td>
        <td style="text-align:right;">&#8377;{total_gst:,.2f}</td>
      </tr>
      <tr class="total-row">
        <td colspan="5" style="text-align:right; font-size:11pt;">Grand Total</td>
        <td style="text-align:right; font-size:11pt;">&#8377;{grand_total:,.2f}/-</td>
      </tr>
    </tbody>
  </table>

  <div class="terms-title">Commercial Terms &amp; Conditions:</div>
  <ul class="terms-list">
    <li><span class="n">I.</span>Payment Term: {payment_terms} after delivery of Item.</li>
    <li><span class="n">II.</span>Above mentioned rates are exclusive of all applicable taxes.</li>
    <li><span class="n">III.</span>All disputes shall be subject to Ahmedabad Jurisdiction.</li>
    {f'<li><span class="n">IV.</span>GST No: {v_gst}</li>' if v_gst else ''}
    <li><span class="n">{'V' if v_gst else 'IV'}.</span>Gateway Group reserves the right to modify or cancel this PO with written notice.</li>
  </ul>

  <div class="ftr">
    <strong>Gateway Group</strong><br>
    B-11, Corporate House, Bodakdev, S.G. Highway, Ahmedabad &ndash; 380054 | admin@thegatewaygroup.com
  </div>
</div>

<!-- ═══════════════════ PAGE 2: GENERAL T&C ═══════════════════ -->
<div class="page">
  <div class="hdr">
    <div class="hdr-row">
      <div class="hdr-left">
        <div class="hdr-company">Gateway Group</div>
        <div class="hdr-sub">
          B-11, Corporate House, Bodakdev, S.G. Highway, Ahmedabad &ndash; 380054, Gujarat<br>
          Tel: +91 79 40393909 | Email: admin@thegatewaygroup.com | www.thegatewaygroup.com
        </div>
      </div>
      {'<div class="hdr-right"><img src="' + logo_b64 + '" class="hdr-logo"></div>' if logo_b64 else ''}
    </div>
  </div>

  <div class="gen-terms">
    <div style="font-weight:bold; margin-bottom:10px;">General Terms &amp; Condition:</div>
    <ol type="i">
      <li><strong>Goods &amp; Service Location:</strong><br>
        {delivery_loc}</li>
      <li>The GOODS &amp; SERVICES will be subject to final inspection and acceptance or rejection as specified in the PURCHASE ORDER.</li>
      <li>In the case of GOODS &amp; SERVICES delivered by VENDOR not conforming with the PURCHASE ORDER whether by reason of not being of the quality or in the quantity or measurement stipulated or being unfit for the purpose for which they are required, Gateway Group shall have the right to reject such GOODS &amp; SERVICES within a reasonable time of their delivery and inspection and to purchase elsewhere and to claim for any additional expense incurred and risks besides OPPORTUNITY COST Loss in our planned business without any prejudice to any other right which Gateway Group may have against SUPPLIER. The making of any prior payments by Gateway Group shall not prejudice PURCHASER&rsquo;s right of rejection.</li>
      <li>Time is of the essence for the PURCHASE ORDER. The time stipulated for delivery of GOODS &amp; SERVICES shall be strictly adhered to. Failure to deliver on the date specified or subsequently agreed shall entitle PURCHASER (without prejudice to any other rights it may have)
        <ol type="a" style="margin-top:6px;">
          <li>to cancel order without any penalty to PURCHASER; or</li>
          <li>Refuse to accept any subsequent delivery of the GOODS &amp; SERVICES which the VENDOR attempts to make; or</li>
          <li>Recover from the SUPPLIER any expenditure reasonably incurred by Gateway Group in obtaining the GOODS &amp; SERVICES in substitution from another vendor; or</li>
          <li>Claim damages for any additional costs incurred by Gateway Group which are in any way attributable to the SUPPLIER&rsquo;s failure to deliver the GOODS &amp; SERVICES on the due date.</li>
        </ol>
      </li>
      <li>Gateway Group reserves the right at any time to make changes in the PURCHASE ORDER or any part thereof.</li>
      <li>No change to or modification of the items, specifications, terms, conditions and prices appearing in the PURCHASE ORDER shall be binding upon Gateway Group unless expressly agreed in writing by Gateway Group.</li>
      <li>However, In the event of any breach of any of the terms and conditions of the PURCHASE ORDER including failure to deliver by the due date, then Gateway Group without prejudice to any other rights, may extend or terminate the PURCHASE ORDER.</li>
    </ol>
  </div>

  <div class="signatory">
    Thanking you,<br>
    <strong>For Gateway Group</strong><br>
    SD/-<br>
    <strong>Authorized Signatory</strong><br>
    <span class="cg">This is a computer generated document so No Signature is required.</span>
  </div>

  <div class="ftr">
    <strong>Gateway Group</strong><br>
    B-11, Corporate House, Bodakdev, S.G. Highway, Ahmedabad &ndash; 380054 | admin@thegatewaygroup.com
  </div>
</div>

</body></html>"""

    # ── Render to PDF ────────────────────────────────────────────────────────
    try:
        from xhtml2pdf import pisa
        buf = io.BytesIO()
        result = pisa.CreatePDF(io.StringIO(html), dest=buf)
        if result.err:
            raise Exception("xhtml2pdf error")
        buf.seek(0)
        return StreamingResponse(buf, media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={po.po_no}.pdf"})
    except Exception:
        pass

    # Fallback: fpdf2
    from fpdf import FPDF
    fpdf = FPDF(); fpdf.set_auto_page_break(True, 20); fpdf.add_page()
    fpdf.set_font("Helvetica", "B", 14); fpdf.cell(0, 8, "Gateway Group", new_x="LMARGIN", new_y="NEXT")
    fpdf.set_font("Helvetica", "", 8); fpdf.cell(0, 4, "B-11, Corporate House, Ahmedabad 380054", new_x="LMARGIN", new_y="NEXT")
    fpdf.line(10, fpdf.get_y()+2, 200, fpdf.get_y()+2); fpdf.ln(8)
    fpdf.set_font("Helvetica", "B", 10); fpdf.cell(0, 5, f"Date: {po_date_str}", new_x="LMARGIN", new_y="NEXT")
    fpdf.cell(0, 5, f"To, {v_name}", new_x="LMARGIN", new_y="NEXT"); fpdf.ln(3)
    fpdf.cell(0, 5, f"Ref. {ref_no}", new_x="LMARGIN", new_y="NEXT"); fpdf.ln(3)
    fpdf.cell(0, 5, f"Subject: {po_subject}", new_x="LMARGIN", new_y="NEXT"); fpdf.ln(5)
    cw = [12, 78, 18, 18, 30, 30]
    for i, h in enumerate(["Sr", "Description", "Qty", "UOM", "Rate", "Amount"]):
        fpdf.set_font("Helvetica","B",8); fpdf.cell(cw[i],7,h,1,0,"C")
    fpdf.ln()
    fpdf.set_font("Helvetica","",8)
    for idx, li in enumerate(line_items, 1):
        q=float(li.get("qty") or 0); r=float(li.get("rate") or 0); a=q*r
        d=(li.get("description","") or li.get("item_name",""))[:45]
        for i,v in enumerate([str(idx),d,f"{q:g}",li.get("uom",""),f"{r:,.0f}",f"{a:,.0f}"]):
            fpdf.cell(cw[i],6,v,1,0,"R" if i>=2 else "L")
        fpdf.ln()
    fpdf.set_font("Helvetica","B",9)
    fpdf.cell(sum(cw[:-1]),7,"Grand Total (Incl GST)",1,0,"R")
    fpdf.cell(cw[-1],7,f"{grand_total:,.0f}/-",1,0,"R"); fpdf.ln(10)
    fpdf.set_font("Helvetica","",8)
    fpdf.cell(0,5,"Thanking you, For Gateway Group | Authorized Signatory", new_x="LMARGIN", new_y="NEXT")
    return StreamingResponse(io.BytesIO(fpdf.output()), media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={po.po_no}.pdf"})

# ─── GRNs ─────────────────────────────────────────────────────────────────────
def _next_grn_no(db) -> str:
    rows = db.query(models.GRNModel.grn_no).all()
    nums = []
    for (val,) in rows:
        try: nums.append(int(str(val).replace("GRN-", "").split("-")[-1]))
        except Exception: pass
    return f"GRN-{str((max(nums) + 1) if nums else 1).zfill(3)}"

def _grn_item_summary(line_items: list) -> str:
    """Build a compact summary string for multi-line GRNs, e.g. 'HK-018 (435), HK-002 (10) +1 more'."""
    if not line_items:
        return ""
    parts = [
        f"{li.get('item_code','')} ({int(float(li.get('accepted_qty') or 0))})"
        for li in line_items[:2]
    ]
    s = ", ".join(parts)
    if len(line_items) > 2:
        s += f" +{len(line_items) - 2} more"
    return s


@router.get("/grns")
def get_grns(db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    grns = db.query(models.GRNModel).order_by(models.GRNModel.grn_date.desc()).all()
    vendors = {v.code: v for v in db.query(models.VendorModel).all()}
    items = {i.code: i for i in db.query(models.ItemModel).all()}
    result = []
    for g in grns:
        v = vendors.get(g.vendor_code); i = items.get(g.item_code)
        line_items = _json.loads(g.line_items) if g.line_items else []
        effective_rate = g.rate if (g.rate and g.rate > 0) else (i.rate if i else 0)
        # item_summary: multi-line compact text; item_name: first/only item full name
        item_summary = _grn_item_summary(line_items) if len(line_items) > 1 else (i.name if i else g.item_code)
        result.append({
            "grn_no": g.grn_no, "grn_date": str(g.grn_date) if g.grn_date else None,
            "invoice_no": g.invoice_no, "po_no": g.po_no,
            "vendor_code": g.vendor_code, "item_code": g.item_code,
            "recd_qty": g.recd_qty, "accepted_qty": g.accepted_qty, "rejected_qty": g.rejected_qty,
            "uom": g.uom, "rate": effective_rate,
            "received_by": g.received_by, "inspected_by": g.inspected_by,
            "store_location": g.store_location, "batch_lot": g.batch_lot,
            "status": g.status, "remarks": g.remarks,
            "line_items": line_items,
            "vendor_name": v.name if v else g.vendor_code,
            "item_name": i.name if i else g.item_code,
            "item_summary": item_summary,
            "line_count": len(line_items),
            "value": round(sum(float(li.get("accepted_qty") or 0) * float(li.get("rate") or effective_rate)
            for li in line_items) if line_items else (g.accepted_qty or 0) * effective_rate,2),
        })
    return result

@router.post("/grns")
def create_grn(data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "analyst")
    # Extract line items before cleaning
    line_items = data.pop("line_items", []) or []
    for li in line_items:
        recd = float(li.get("recd_qty") or 0)
        accepted = float(li.get("accepted_qty") or 0)
        if recd <= 0 or accepted < 0 or accepted > recd:
            raise HTTPException(400, "GRN quantities must be positive and accepted quantity cannot exceed received quantity.")
        if float(li.get("rejected_qty") or 0) < 0:
            raise HTTPException(400, "Rejected quantity cannot be negative.")
    if not line_items:
        recd = float(data.get("recd_qty") or 0)
        accepted = float(data.get("accepted_qty") or 0)
        if recd <= 0 or accepted < 0 or accepted > recd:
            raise HTTPException(400, "GRN quantities must be positive and accepted quantity cannot exceed received quantity.")

    # Auto-generate GRN number server-side if not provided
    if not data.get("grn_no"):
        data["grn_no"] = _next_grn_no(db)

    # Populate top-level item/qty fields from line items for backward compat
    if line_items:
        first = line_items[0]
        if not data.get("item_code"):   data["item_code"]   = first.get("item_code", "")
        if not data.get("vendor_code"): data["vendor_code"] = first.get("vendor_code", "")
        data["recd_qty"]     = sum(float(li.get("recd_qty") or 0) for li in line_items)
        data["accepted_qty"] = sum(float(li.get("accepted_qty") or 0) for li in line_items)
        data["rejected_qty"] = data["recd_qty"] - data["accepted_qty"]

    # ── Back-fill missing rates from Item Master (before persisting) ──────────
    _item_cache: dict = {}
    def _item_rate(code: str) -> float:
        if code not in _item_cache:
            rec = db.query(models.ItemModel).filter_by(code=code).first()
            _item_cache[code] = float(rec.rate) if rec and rec.rate else 0.0
        return _item_cache[code]

    for li in (line_items or []):
        if not (float(li.get("rate") or 0) > 0):
            li["rate"] = _item_rate(li.get("item_code", ""))

    if not (float(data.get("rate") or 0) > 0):
        top_code = data.get("item_code", "")
        data["rate"] = _item_rate(top_code) if top_code else 0.0

    data["line_items"] = _json.dumps(line_items) if line_items else None
    total_value = sum(
        float(li.get("accepted_qty") or 0) * float(li.get("rate") or 0)
        for li in line_items)
    data["total_value"] = total_value

    _parse_dates(data, ["grn_date"])

    grn = models.GRNModel(**_clean(data, models.GRNModel))
    db.add(grn); db.flush()

    store_location = data.get("store_location", "")
    po_no          = data.get("po_no")
    po_total_accepted = 0.0

    # ── Inventory update — loop over each line item ───────────────────────────
    items_to_update = line_items if line_items else [
        {"item_code": data.get("item_code", ""), "vendor_code": data.get("vendor_code", ""),
         "accepted_qty": data.get("accepted_qty", 0), "recd_qty": data.get("recd_qty", 0), "rate": data.get("rate", 0)}
    ]
    for li in items_to_update:
        item_code   = li.get("item_code", "")
        vendor_code = li.get("vendor_code", "")
        _aq = li.get("accepted_qty")
        accepted    = float(_aq if _aq is not None else (li.get("recd_qty") or 0))
        rate        = float(li.get("rate") or data.get("rate") or 0)
        if not (accepted > 0 and item_code and store_location):
            continue
        inv  = _get_or_create_inv(db, item_code, store_location, vendor_code, rate)
        snap = _inv_snapshot(inv)
        inv.stock_in += accepted
        inv.last_grn_no = grn.grn_no
        if rate > 0: inv.rate = rate
        if not inv.vendor_code and vendor_code: inv.vendor_code = vendor_code
        db.flush()
        _log(db, "grn.created", "grn", grn.grn_no,
             location_code=store_location, item_code=item_code, vendor_code=vendor_code,
             qty=accepted, rate=rate, before=snap, after=_inv_snapshot(inv),
             meta={"grn_no": grn.grn_no, "po_no": po_no, "invoice_no": data.get("invoice_no")})
        po_total_accepted += accepted

    # ── Mark linked PO as received ────────────────────────────────────────────
    if po_no and po_total_accepted > 0:
        po = db.query(models.PurchaseOrderModel).filter_by(po_no=po_no).first()
        if po:
            po.received_qty = (po.received_qty or 0) + po_total_accepted
            po.balance_qty  = max(0, (po.qty_ordered or 0) - po.received_qty)
            if po.balance_qty == 0: po.status = "Fully Received"
            elif po.received_qty > 0: po.status = "Partial Received"
            db.flush()
            _log(db, "po.received", "po", po.po_no,
                 item_code=data.get("item_code"), vendor_code=data.get("vendor_code"),
                 qty=po_total_accepted, rate=data.get("rate"),
                 meta={"grn_no": grn.grn_no, "received_qty": po.received_qty, "balance_qty": po.balance_qty})

    db.commit(); db.refresh(grn); return {"grn_no": grn.grn_no}

@router.put("/grns/{grn_no}")
def update_grn(grn_no: str, data: dict, db: Session = Depends(get_db),
               current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "analyst")
    grn = db.query(models.GRNModel).filter_by(grn_no=grn_no).first()
    if not grn:
        raise HTTPException(status_code=404, detail="GRN not found")

    # ── Pull new line_items out before mutating data ───────────────────────────
    new_line_items = data.pop("line_items", None)  # list or None
    if new_line_items is not None:
        for li in new_line_items:
            recd = float(li.get("recd_qty") or 0)
            accepted = float(li.get("accepted_qty") or 0)
            if recd <= 0 or accepted < 0 or accepted > recd:
                raise HTTPException(400, "GRN quantities must be positive and accepted quantity cannot exceed received quantity.")
    elif "accepted_qty" in data or "recd_qty" in data:
        recd = float(data.get("recd_qty") or 0)
        accepted = float(data.get("accepted_qty") or 0)
        if recd <= 0 or accepted < 0 or accepted > recd:
            raise HTTPException(400, "GRN quantities must be positive and accepted quantity cannot exceed received quantity.")

    old_store_location = grn.store_location or ""
    new_store_location = (data.get("store_location") or old_store_location).strip()

    # ── Build OLD accepted-qty map from what was originally posted ────────────
    try:
        old_lis = _json.loads(grn.line_items) if grn.line_items else []
    except Exception:
        old_lis = []
    if not old_lis and grn.item_code:
        # legacy single-item GRN (no line_items JSON)
        old_lis = [{"item_code": grn.item_code, "vendor_code": grn.vendor_code or "",
                    "accepted_qty": grn.accepted_qty or 0, "rate": grn.rate or 0}]

    old_accepted: dict = defaultdict(float)   # item_code → qty
    for li in old_lis:
        old_accepted[li.get("item_code", "")] += float(li.get("accepted_qty") or 0)

    # ── Build NEW accepted-qty map from incoming payload ──────────────────────
    new_lis = new_line_items if new_line_items is not None else old_lis
    new_accepted: dict = defaultdict(float)
    new_rates:    dict = {}
    new_vendors:  dict = {}
    for li in new_lis:
        code = li.get("item_code", "")
        new_accepted[code] += float(li.get("accepted_qty") or 0)
        new_rates[code]    = float(li.get("rate") or 0)
        new_vendors[code]  = li.get("vendor_code", "")

    # ── Apply inventory deltas ────────────────────────────────────────────────
    location_changed = new_store_location and (new_store_location != old_store_location)

    if location_changed:
        # Reverse every item from the old location
        for code, old_qty in old_accepted.items():
            if not code or not old_store_location:
                continue
            inv = db.query(models.InventoryModel).filter_by(
                item_code=code, location_code=old_store_location).first()
            if inv and old_qty > 0:
                snap = _inv_snapshot(inv)
                inv.stock_in = max(0, inv.stock_in - old_qty)
                db.flush()
                _log(db, "grn.updated", "grn", grn_no,
                     location_code=old_store_location, item_code=code,
                     qty=-old_qty, before=snap, after=_inv_snapshot(inv),
                     meta={"grn_no": grn_no, "reason": "location_change_reversal"})

        # Credit every item at the new location
        for code, new_qty in new_accepted.items():
            if not code or not new_store_location or not (new_qty > 0):
                continue
            rate   = new_rates.get(code, 0)
            vendor = new_vendors.get(code, "")
            inv    = _get_or_create_inv(db, code, new_store_location, vendor, rate)
            snap   = _inv_snapshot(inv)
            inv.stock_in += new_qty
            if rate > 0: inv.rate = rate
            closing = inv.opening_stock + inv.stock_in - inv.stock_out
            inv.value = closing * (inv.rate or 0)
            db.flush()
            _log(db, "grn.updated", "grn", grn_no,
                 location_code=new_store_location, item_code=code, vendor_code=vendor,
                 qty=new_qty, rate=rate, before=snap, after=_inv_snapshot(inv),
                 meta={"grn_no": grn_no, "reason": "location_change_credit"})
    else:
        # Same location — apply per-item delta (new_accepted − old_accepted)
        all_codes = set(old_accepted) | set(new_accepted)
        for code in all_codes:
            if not code or not new_store_location:
                continue
            delta  = new_accepted.get(code, 0.0) - old_accepted.get(code, 0.0)
            if delta == 0:
                continue
            rate   = new_rates.get(code, 0)
            vendor = new_vendors.get(code, "")
            inv    = _get_or_create_inv(db, code, new_store_location, vendor, rate)
            snap   = _inv_snapshot(inv)
            inv.stock_in = max(0, inv.stock_in + delta)
            if rate > 0: inv.rate = rate

            closing = inv.opening_stock + inv.stock_in - inv.stock_out
            inv.value = closing * (inv.rate or 0)

            db.flush()
            _log(db, "grn.updated", "grn", grn_no,
                 location_code=new_store_location, item_code=code, vendor_code=vendor,
                 qty=delta, rate=rate, before=snap, after=_inv_snapshot(inv),
                 meta={"grn_no": grn_no, "delta": delta})

    # ── Persist updated GRN fields ─────────────────────────────────────────────
    if new_line_items is not None:
        data["line_items"] = _json.dumps(new_line_items) if new_line_items else None
    #recompute totals from line items
        total_recd = sum(float(li.get("recd_qty") or 0) for li in new_line_items)
        total_accepted = sum(float(li.get("accepted_qty") or 0) for li in new_line_items)

        data["recd_qty"] = total_recd
        data["accepted_qty"] = total_accepted
        data["rejected_qty"] = total_recd - total_accepted

        total_value = sum(
        float(li.get("accepted_qty") or 0) * float(li.get("rate") or 0)
        for li in new_line_items)

        data["total_value"] = total_value

    _parse_dates(data, ["grn_date"])
    for k, v in _clean(data, models.GRNModel).items():
        setattr(grn, k, v)
    db.commit(); db.refresh(grn)
    return {"grn_no": grn.grn_no}

# ─── ISSUANCE ─────────────────────────────────────────────────────────────────
@router.get("/issuances")
def get_issuances(db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    return db.query(models.IssuanceLogModel).order_by(models.IssuanceLogModel.date.desc()).all()

@router.post("/issuances")
def create_issuance(data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "analyst")
    _parse_dates(data, ["date"])
    qty = float(data.get("qty") or 0)
    if qty <= 0:
        raise HTTPException(400, "Issuance quantity must be greater than zero.")
    iss = models.IssuanceLogModel(**_clean(data, models.IssuanceLogModel))
    db.add(iss); db.flush()

    # ── Auto-decrement inventory stock_out ────────────────────────────────────
    item_code     = data.get("item_code", "")
    location_code = data.get("location_code", "")
    rate          = float(data.get("rate") or 0)

    if qty > 0 and item_code and location_code:
        if not rate > 0:
            im = db.query(models.ItemModel).filter_by(code=item_code).first()
            if im and im.rate: rate = float(im.rate)

        # Resolve SITE → STORE: stock always deducted from the parent store,
        # but location_code (the consumption site) is preserved in all logs/budgets.
        stock_location = _resolve_store(db, location_code)

        inv = _get_or_create_inv(db, item_code, stock_location, rate=rate)
        available = inv.opening_stock + inv.stock_in - inv.stock_out
        if available - qty < 0:
            raise HTTPException(400, f"Insufficient stock: {item_code} at {stock_location} has {available:.1f} units available, cannot issue {qty:.1f}")
        snap = _inv_snapshot(inv)
        inv.stock_out += qty
        db.flush()
        _log(db, "issuance.created", "issuance", iss.issue_id,
             location_code=location_code, item_code=item_code,
             qty=qty, rate=rate, before=snap, after=_inv_snapshot(inv),
             meta={"department": data.get("department"), "issued_to": data.get("issued_to"),
                   "stock_location": stock_location,
                   "month": data.get("month"), "quarter": data.get("quarter")})

        # Update monthly_budget actual figures (tracked per consumption site)
        month = data.get("month")
        if month:
            budget = (db.query(models.MonthlyBudgetModel)
                        .filter_by(item_code=item_code, location_code=location_code, month=month)
                        .first())
            if budget:
                budget.actual_qty   = (budget.actual_qty   or 0) + qty
                budget.actual_value = (budget.actual_value or 0) + qty * rate
                db.flush()

    db.commit(); db.refresh(iss); return iss

# ─── RETURNS ──────────────────────────────────────────────────────────────────
@router.get("/returns")
def get_returns(db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    return db.query(models.ReturnLogModel).order_by(models.ReturnLogModel.return_date.desc()).all()

@router.post("/returns")
def create_return(data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "analyst")
    _parse_dates(data, ["return_date"])
    ret = models.ReturnLogModel(**_clean(data, models.ReturnLogModel))
    db.add(ret); db.flush()

    # ── If vendor return: reverse stock_in that the GRN added ────────────────
    qty_returned  = float(data.get("qty_returned") or 0)
    if qty_returned <= 0:
        raise HTTPException(400, "Return quantity must be greater than zero.")
    item_code     = data.get("item_code", "")
    grn_ref       = data.get("grn_ref", "")

    if qty_returned > 0 and item_code and grn_ref:
        grn = db.query(models.GRNModel).filter_by(grn_no=grn_ref).first()
        if grn and grn.store_location:
            inv = db.query(models.InventoryModel).filter_by(
                item_code=item_code, location_code=grn.store_location).first()
            if inv:
                snap = _inv_snapshot(inv)
                inv.stock_in = max(0, inv.stock_in - qty_returned)
                db.flush()
                _log(db, "return.created", "return", ret.return_id,
                     location_code=grn.store_location, item_code=item_code,
                     vendor_code=data.get("vendor_code"),
                     qty=qty_returned, before=snap, after=_inv_snapshot(inv),
                     meta={"grn_ref": grn_ref, "reason": data.get("reason")})

    db.commit(); db.refresh(ret); return ret

# ─── CONSUMPTION NORMS ────────────────────────────────────────────────────────
@router.get("/consumption-norms")
def get_norms(db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    norms = db.query(models.ConsumptionNormModel).all()
    items = {i.code: i for i in db.query(models.ItemModel).all()}
    result = []
    for n in norms:
        item = items.get(n.item_code)
        result.append({**n.__dict__, "current_rate": item.rate if item else n.rate, "item_status": item.status if item else "Not Active"})
    return result

@router.put("/consumption-norms/{id}")
def update_norm(id: int, data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    norm = db.query(models.ConsumptionNormModel).filter(models.ConsumptionNormModel.id == id).first()
    if not norm: raise HTTPException(404)
    for k, v in data.items():
        if hasattr(norm, k): setattr(norm, k, v)
    db.commit(); db.refresh(norm); return norm

# ─── BUDGET ENGINE ────────────────────────────────────────────────────────────
def _compute_budget(db: Session):
    """Core budget calculation: Norms × Location Factors = Monthly Budget per item per location"""
    norms = db.query(models.ConsumptionNormModel).all()
    locations = db.query(models.LocationModel).all()
    items = {i.code: i for i in db.query(models.ItemModel).all()}

    result = []
    total_monthly = 0
    for norm in norms:
        item = items.get(norm.item_code)
        rate = (item.rate if item else norm.rate) or 0
        if rate == 0: continue

        row = {"item_code": norm.item_code, "item_name": norm.item_name, "category": norm.category,
               "basis": norm.basis, "norm_value": norm.norm_value, "norm_unit": norm.norm_unit,
               "rate": rate, "remarks": norm.remarks, "locations": {}, "total_qty": 0, "total_value": 0}

        for loc in locations:
            # Determine the factor based on basis
            if norm.basis == "Per 1000 SqFt":
                factor = (loc.area_sqft or 0) / 1000
            elif norm.basis == "Per Person":
                factor = loc.headcount or 0
            elif norm.basis == "Per Washroom":
                factor = loc.num_washrooms or 0
            elif norm.basis == "Per Urinal":
                factor = loc.num_urinals or 0
            elif norm.basis == "Per WC":
                factor = loc.num_wcs or 0
            elif norm.basis == "Per Pantry":
                factor = loc.num_pantries or 0
            else:
                factor = 1

            if not norm.norm_value:
                continue
            safe_factor = factor or 0
            safe_norm = norm.norm_value or 0

            qty = round(safe_factor * safe_norm, 2)
            value = round((qty or 0) * (rate or 0), 2)
            row["locations"][loc.code] = {"qty": qty, "value": value}
            row["total_qty"] = round(row["total_qty"] + qty, 2)
            row["total_value"] = round(row["total_value"] + value, 2)

        result.append(row)
        total_monthly += row["total_value"]

    return result, round(total_monthly, 2)

@router.get("/budget/calculated")
def get_budget_calculated(db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    rows, total = _compute_budget(db)
    return {"items": rows, "total_monthly": total, "total_quarterly": round(total*3,2), "total_yearly": round(total*12,2)}

@router.post("/budget/calculate")
def recalculate_budget(db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "analyst")
    rows, total = _compute_budget(db)
    return {"message": "Budget recalculated", "total_monthly": total, "items_count": len(rows)}

@router.get("/budget/vs-actual")
def budget_vs_actual(month: int = 1, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    rows, _ = _compute_budget(db)
    iss = db.query(models.IssuanceLogModel).filter(models.IssuanceLogModel.month == month).all()
    actual_qty = {}; actual_val = {}
    for i in iss:
        key = (i.item_code, i.location_code)

        actual_qty[key] = actual_qty.get(key, 0) + i.qty
        actual_val[key] = actual_val.get(key, 0) + (i.qty * i.rate)

    result = []
    for row in rows:
        total_a_qty = 0
        total_a_val = 0

        for loc_code in row["locations"]:
            key = (row["item_code"], loc_code)
            total_a_qty += actual_qty.get(key, 0)
            total_a_val += actual_val.get(key, 0)

        a_qty = total_a_qty
        a_val = total_a_val
        b_val = row["total_value"]
        variance = b_val - a_val
        result.append({
            "item_code": row["item_code"], "item_name": row["item_name"], "category": row["category"],
            "uom": row["norm_unit"], "budget_qty": row["total_qty"], "budget_value": b_val,
            "actual_qty": round(a_qty,2), "actual_value": round(a_val,2),
            "variance_qty": round(row["total_qty"] - a_qty, 2),
            "variance_value": round(variance, 2),
            "variance_pct": round((variance/b_val*100) if b_val else 0, 1),
            "utilization_pct": round((a_val/b_val*100) if b_val else 0, 1),
            "status": "Over Budget" if variance < 0 else "Under Budget" if variance > 0 else "On Budget"
        })
    budget_total = sum(r["budget_value"] for r in result)
    actual_total = sum(r["actual_value"] for r in result)
    return {"month": month, "items": result, "budget_total": round(budget_total,2), "actual_total": round(actual_total,2), "variance_total": round(budget_total-actual_total,2), "utilization_pct": round(actual_total/budget_total*100 if budget_total else 0, 1)}

@router.get("/budget/forecast")
def budget_forecast(inflation: float = 6, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _, monthly = _compute_budget(db)
    yearly = monthly * 12
    inf = inflation / 100
    periods = [
        {"period": "Current Month", "value": round(monthly, 2), "type": "current"},
        {"period": "Current Quarter", "value": round(monthly*3, 2), "type": "current"},
        {"period": "Current Year",   "value": round(yearly, 2),    "type": "current"},
        {"period": f"Next Year (+{inflation}% inflation)", "value": round(yearly*(1+inf), 2), "type": "forecast"},
        {"period": "3-Year Total",   "value": round(yearly*(1 + (1+inf) + (1+inf)**2), 2), "type": "forecast"},
    ]
    # Category-wise forecast
    rows, _ = _compute_budget(db)
    cat_curr = {}
    for r in rows:
        cat_curr[r["category"]] = cat_curr.get(r["category"], 0) + r["total_value"]*12
    cat_forecast = [{"category":k,"current_year":round(v,2),"next_year":round(v*(1+inf),2),"increase":round(v*inf,2)} for k,v in cat_curr.items()]
    return {"inflation_pct": inflation, "periods": periods, "category_forecast": cat_forecast, "monthly": monthly, "yearly": yearly}

@router.get("/budget/category-summary")
def budget_cat_summary(db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    rows, total = _compute_budget(db)
    cats = {}
    for r in rows:
        c = r["category"]
        cats.setdefault(c, 0)
        cats[c] += r["total_value"]
    return [{"category":k,"monthly":round(v,2),"quarterly":round(v*3,2),"yearly":round(v*12,2),"pct":round(v/total*100 if total else 0,1)} for k,v in sorted(cats.items(), key=lambda x:-x[1])]

@router.get("/budget/location-summary")
def budget_loc_summary(db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    rows, _ = _compute_budget(db)
    locs = {l.code: l for l in db.query(models.LocationModel).all()}
    loc_vals = {}
    for r in rows:
        for loc_code, data in r["locations"].items():
            loc_vals.setdefault(loc_code, 0)
            loc_vals[loc_code] += data["value"]
    return [{"location":k,"name":locs.get(k).name if locs.get(k) else k,"area":locs.get(k).area_sqft if locs.get(k) else 0,"headcount":locs.get(k).headcount if locs.get(k) else 0,"monthly":round(v,2),"quarterly":round(v*3,2),"yearly":round(v*12,2)} for k,v in sorted(loc_vals.items(), key=lambda x:-x[1])]


# ─── CATEGORIES ──────────────────────────────────────────────────────────────
@router.get("/categories")
def get_categories(group: Optional[str] = None, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    q = db.query(models.CategoryModel)
    if group:
        q = q.filter(models.CategoryModel.master_group == group)
    cats = q.order_by(models.CategoryModel.name).all()
    return [{"id": c.id, "name": c.name, "parent_id": c.parent_id,
             "master_group": getattr(c, 'master_group', '') or "",
             "description": c.description, "status": c.status} for c in cats]

@router.post("/categories")
def create_category(data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    name = (data.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Category name required")
    existing = db.query(models.CategoryModel).filter_by(name=name).first()
    if existing:
        raise HTTPException(400, f"Category '{name}' already exists")
    data["name"] = name
    cat = models.CategoryModel(**_clean(data, models.CategoryModel))
    db.add(cat); db.commit(); db.refresh(cat)
    return {"id": cat.id, "name": cat.name, "parent_id": cat.parent_id, "master_group": cat.master_group or ""}

@router.put("/categories/{cat_id}")
def update_category(cat_id: int, data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    cat = db.query(models.CategoryModel).filter_by(id=cat_id).first()
    if not cat: raise HTTPException(404)
    for k, v in data.items():
        if hasattr(cat, k) and k != "id": setattr(cat, k, v)
    db.commit(); db.refresh(cat)
    return {"id": cat.id, "name": cat.name, "parent_id": cat.parent_id, "master_group": cat.master_group or ""}

@router.patch("/categories/{cat_id}")
def patch_category(cat_id: int, data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    """Assign/update master_group on an existing category."""
    _require_role(current_user, "admin")
    cat = db.query(models.CategoryModel).filter_by(id=cat_id).first()
    if not cat: raise HTTPException(404)
    if "master_group" in data: cat.master_group = data["master_group"]
    if "name" in data: cat.name = data["name"]
    db.commit(); db.refresh(cat)
    return {"id": cat.id, "name": cat.name, "master_group": cat.master_group or ""}

@router.delete("/categories/{cat_id}")
def delete_category(cat_id: int, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    # Check if any items use this category name
    cat = db.query(models.CategoryModel).filter_by(id=cat_id).first()
    if not cat: raise HTTPException(404)
    items_using = db.query(models.ItemModel).filter(models.ItemModel.category == cat.name).count()
    if items_using > 0:
        raise HTTPException(400, f"Cannot delete: {items_using} items use category '{cat.name}'")
    # Check for sub-categories
    children = db.query(models.CategoryModel).filter_by(parent_id=cat_id).count()
    if children > 0:
        raise HTTPException(400, f"Cannot delete: {children} sub-categories exist under '{cat.name}'")
    db.delete(cat); db.commit()
    return {"deleted": cat_id}

@router.post("/categories/seed")
def seed_categories(db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    """Auto-populate categories from existing distinct values in items table."""
    _require_role(current_user, "admin")
    existing = {c.name for c in db.query(models.CategoryModel).all()}
    item_cats = db.query(models.ItemModel.category).distinct().all()
    hk_cats = db.query(models.HKMasterModel.category).distinct().all()
    all_cats = {r[0] for r in item_cats + hk_cats if r[0]}
    created = 0
    for name in sorted(all_cats - existing):
        db.add(models.CategoryModel(name=name))
        created += 1
    db.commit()
    return {"seeded": created, "total": len(all_cats)}


# ─── MASTER GROUPS ───────────────────────────────────────────────────────────
@router.get("/master-groups")
def get_master_groups(db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    groups = db.query(models.MasterGroupModel).order_by(models.MasterGroupModel.name).all()
    # Include item count per group
    item_counts = {}
    for (gid, cnt) in db.query(models.ItemModel.master_group_id, func.count(models.ItemModel.code)).group_by(models.ItemModel.master_group_id).all():
        if gid: item_counts[gid] = cnt
    return [{"id": g.id, "name": g.name, "description": g.description or "", "status": g.status,
             "created_at": g.created_at, "updated_at": g.updated_at,
             "item_count": item_counts.get(g.id, 0)} for g in groups]

@router.post("/master-groups")
def create_master_group(data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    name = (data.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Name is required")
    existing = db.query(models.MasterGroupModel).filter_by(name=name).first()
    if existing:
        raise HTTPException(400, f"Master group '{name}' already exists")
    data["name"] = name
    data["created_at"] = datetime.datetime.utcnow().isoformat()
    grp = models.MasterGroupModel(**_clean(data, models.MasterGroupModel))
    db.add(grp); db.commit(); db.refresh(grp)
    return {"id": grp.id, "name": grp.name}

@router.put("/master-groups/{grp_id}")
def update_master_group(grp_id: int, data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    grp = db.query(models.MasterGroupModel).filter_by(id=grp_id).first()
    if not grp: raise HTTPException(404)
    # Check for duplicate name if name is being changed
    new_name = data.get("name")
    if new_name and new_name != grp.name:
        dup = db.query(models.MasterGroupModel).filter_by(name=new_name).first()
        if dup: raise HTTPException(400, f"Name '{new_name}' already exists")
    data["updated_at"] = datetime.datetime.utcnow().isoformat()
    for k, v in data.items():
        if hasattr(grp, k) and k != "id": setattr(grp, k, v)
    # If name changed, also update the legacy string field on linked items
    if new_name and new_name != grp.name:
        db.query(models.ItemModel).filter_by(master_group_id=grp_id).update({"master_group": new_name})
    db.commit(); db.refresh(grp)
    return {"id": grp.id, "name": grp.name}

@router.delete("/master-groups/{grp_id}")
def delete_master_group(grp_id: int, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    grp = db.query(models.MasterGroupModel).filter_by(id=grp_id).first()
    if not grp: raise HTTPException(404)
    items_using = db.query(models.ItemModel).filter(models.ItemModel.master_group_id == grp_id).count()
    if items_using > 0:
        raise HTTPException(400, f"Cannot delete: {items_using} item(s) linked to '{grp.name}'. Reassign them first.")
    db.delete(grp); db.commit()
    return {"deleted": grp_id}

@router.post("/master-groups/seed")
def seed_master_groups(db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    """Auto-populate master groups from existing distinct values + defaults."""
    _require_role(current_user, "admin")
    defaults = {"HK Benchmark", "Electrical", "Stationery", "Welcome Kits", "IT Consumables",
                "Maintenance", "Pantry", "PPE & Safety", "Pest Control", "Others"}
    existing = {g.name for g in db.query(models.MasterGroupModel).all()}
    # Also pull from existing items
    item_groups = {r[0] for r in db.query(models.ItemModel.master_group).distinct().all() if r[0]}
    all_groups = defaults | item_groups
    created = 0
    for name in sorted(all_groups - existing):
        db.add(models.MasterGroupModel(name=name))
        created += 1
    db.commit()
    return {"seeded": created, "total": len(all_groups)}


@router.post("/master-groups/seed-from-excel")
def seed_from_excel_api(db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    """Seed master groups + items from the stockitems.xlsx file bundled with the app.
    Idempotent — safe to call multiple times. Super admin only."""
    _require_role(current_user, "super_admin")
    import os

    GROUP_PREFIXES = {
        "Diwali Gifts": "DG", "Welcome Kit": "WK", "Stationery": "ST",
        "Electrical Refurbished": "EL", "Electrical": "EL",
    }
    OVERRIDES = {"Electrical Stock (Refurbished Items)": "Electrical Refurbished"}

    def _clean_name(raw):
        name = raw.strip()
        if name in OVERRIDES: return OVERRIDES[name]
        for s in ["Stock", "stock"]:
            if name.endswith(s): name = name[:name.rfind(s)].strip()
        if "(" in name: name = name[:name.index("(")].strip()
        return name

    def _prefix(gn):
        for k, p in GROUP_PREFIXES.items():
            if k.lower() in gn.lower(): return p
        words = gn.split()
        return (words[0][0] + words[1][0]).upper() if len(words) >= 2 else gn[:2].upper()

    # Try multiple possible locations for the Excel file
    _base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # app/
    _candidates = [
        os.path.join(_base, "stockitems.xlsx"),                          # app/stockitems.xlsx
        os.path.join(os.path.dirname(_base), "stockitems.xlsx"),         # backend/stockitems.xlsx
        os.path.join(os.getcwd(), "stockitems.xlsx"),                    # cwd/stockitems.xlsx
        os.path.join(os.getcwd(), "app", "stockitems.xlsx"),             # cwd/app/stockitems.xlsx
    ]
    xlsx = None
    for c in _candidates:
        if os.path.exists(c):
            xlsx = c; break
    if not xlsx:
        raise HTTPException(404, f"stockitems.xlsx not found. Searched: {_candidates}")

    df = pd.read_excel(xlsx, header=None)
    header_row = 1
    groups = {}
    for col in range(df.shape[1]):
        val = df.iloc[header_row, col]
        if pd.notna(val) and isinstance(val, str) and val not in ("All Items", "Total"):
            gname = _clean_name(val)
            items = []
            for row in range(header_row + 1, df.shape[0]):
                cell = df.iloc[row, col]
                qty_cell = df.iloc[row, col + 1] if col + 1 < df.shape[1] else None
                if pd.isna(cell) or not str(cell).strip() or str(cell).strip().lower() == "total":
                    continue
                qty = int(float(qty_cell)) if pd.notna(qty_cell) else 0
                items.append({"name": str(cell).strip(), "qty": qty})
            if items:
                groups[gname] = items

    groups_created, items_created, items_existing = 0, 0, 0

    for gname, item_list in groups.items():
        prefix = _prefix(gname)
        mg = db.query(models.MasterGroupModel).filter_by(name=gname).first()
        if not mg:
            mg = models.MasterGroupModel(name=gname, description=f"From Excel import", status="Active",
                                          created_at=datetime.datetime.utcnow().isoformat())
            db.add(mg); db.flush()
            groups_created += 1

        # Get next code number
        existing_codes = db.query(models.ItemModel.code).filter(models.ItemModel.code.like(f"{prefix}-%")).all()
        nums = []
        for (c,) in existing_codes:
            try: nums.append(int(c.replace(f"{prefix}-", "")))
            except: pass
        next_n = (max(nums) + 1) if nums else 1

        existing_names = {i.name.strip().lower() for i in db.query(models.ItemModel).filter_by(master_group_id=mg.id).all() if i.name}

        for it in item_list:
            if it["name"].strip().lower() in existing_names:
                items_existing += 1; continue
            code = f"{prefix}-{str(next_n).zfill(3)}"
            next_n += 1
            db.add(models.ItemModel(
                code=code, name=it["name"], category=gname, sub_category="",
                uom="Nos", brand_tier="Standard", vendor_code="", rate=0, gst_pct=18,
                rol=0, max_stock=0, lead_days=5, status="Active",
                master_group=gname, master_group_id=mg.id,
            ))
            items_created += 1
            existing_names.add(it["name"].strip().lower())

    db.commit()
    return {
        "status": "ok",
        "groups_detected": len(groups),
        "groups_created": groups_created,
        "items_created": items_created,
        "items_existing": items_existing,
        "groups": {k: len(v) for k, v in groups.items()},
    }


def _read_excel(file_bytes: bytes) -> pd.DataFrame:
    try:
        df = pd.read_excel(io.BytesIO(file_bytes), engine='openpyxl')
    except Exception:
        df = pd.read_csv(io.BytesIO(file_bytes))
    df.columns = [str(c).strip().lower().replace(' ','_').replace('-','_') for c in df.columns]
    return df

def _apply_mapping(df: pd.DataFrame, mapping_json: str) -> pd.DataFrame:
    """Rename df columns according to user mapping {system_field: user_column}."""
    if not mapping_json:
        return df
    try:
        mapping = _json.loads(mapping_json)  # {system_field: user_col | ""}
    except Exception:
        return df
    rename = {v: k for k, v in mapping.items() if v and v in df.columns}
    df = df.rename(columns=rename)
    # Add any mapped-to-empty fields as NaN columns
    for sys_field, user_col in mapping.items():
        if not user_col and sys_field not in df.columns:
            df[sys_field] = None
    return df

def _result(imported, skipped, errors):
    return {"imported": imported, "skipped": skipped, "errors": errors[:50]}

def _safe(v):
    """Convert NaN/NaT to None."""
    try:
        return None if pd.isna(v) else v
    except Exception:
        return v

# ── TEMPLATE DOWNLOAD ─────────────────────────────────────────────────────────
@router.get("/import/template/{entity}")
def download_template(entity: str, current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    templates = {
        "hk_master": ["code","name","category","sub_category","uom","eco_brand","eco_price","std_brand","std_price","prem_brand","prem_price","recommended","rate","gst_pct","rol","max_stock","lead_days","status"],
        "items":     ["code","name","category","sub_category","uom","brand_tier","vendor_code","rate","gst_pct","rol","max_stock","lead_days","status"],
        "vendors":   ["code","name","category","contact_person","phone","email","city","gst_no","pan","payment_terms","rating","status"],
        "locations": ["code","name","city","type","contact_person","phone","status","area_sqft","headcount","num_washrooms","num_urinals","num_wcs","num_wash_basins","num_pantries","num_meeting_rooms","num_ac_units","num_fans"],
        "norms":     ["item_code","item_name","category","basis","norm_value","norm_unit","rate","frequency","remarks"],
        "issuances": ["issue_id","date","month","quarter","item_code","qty","uom","rate","location_code","department","issued_to","issued_by","remarks"],
        "returns":   ["return_id","return_date","grn_ref","item_code","item_name","qty_returned","uom","vendor_code","reason","status","credit_note","remarks"],
    }
    if entity not in templates:
        raise HTTPException(404, f"No template for '{entity}'")
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = entity
    headers = templates[entity]
    header_fill = PatternFill("solid", fgColor="0D0F1A")
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = Font(bold=True, color="FFFFFF", name="Calibri")
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions[cell.column_letter].width = max(14, len(h) + 4)
    samples = {
        "hk_master": ["HK-001","Floor Cleaner","Cleaning Chemicals","Floor Care","Liter","Local Brand",200,"Lizol",320,"Taski R2",500,"Standard",310,18,20,100,5,"Active"],
        "items":     ["HK-001","Floor Cleaner Regular 5L","Cleaning Chemicals","Floor Care","Liter","Standard","VND-003",310,18,20,100,5,"Active"],
        "vendors":   ["VND-001","ABC Supplies","Cleaning Chemicals","Ramesh Kumar","9876543210","ramesh@abc.com","Ahmedabad","24AABCU9603R1ZM","AABCU9603R","Net 30",4.5,"Active"],
        "locations": ["MS","Gandhinagar Site","Gandhinagar","Office","Site Manager","079-2630001","Active",3000,50,4,4,8,8,2,3,8,12],
        "norms":     ["HK-001","Floor Cleaner","Cleaning Chemicals","Per 1000 SqFt",0.5,"Liter",310,"Monthly","500ml per 1000 sqft weekly"],
        "issuances": ["ISS-001","2024-01-10",1,1,"HK-001",10,"Liter",310,"MS","Housekeeping","HK Staff","Store Keeper","Monthly stock"],
        "returns":   ["RET-001","2024-01-15","GRN-2024-002","EL-019","LED Bulb 9W",2,"Piece","VND-008","Damaged in transit","Pending","","Cracked glass"],
    }
    if entity in samples:
        for col, val in enumerate(samples[entity], 1):
            ws.cell(row=2, column=col, value=val)
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    return StreamingResponse(buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=template_{entity}.xlsx"})

# ── PREVIEW ───────────────────────────────────────────────────────────────────
@router.post("/import/preview")
async def preview_import(file: UploadFile = File(...), entity: str = Form(...), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    raw = await file.read()
    try:
        df = _read_excel(raw)
    except Exception as e:
        return {"error": str(e)}
    return {
        "columns":   list(df.columns),
        "row_count": len(df),
        "preview":   df.head(5).fillna("").astype(str).to_dict("records"),
    }

# ── SHARED IMPORT CORE ────────────────────────────────────────────────────────
async def _do_import(file, mapping_json, overwrite_str, db, model_class, pk_field, required_fields, date_fields=None):
    raw  = await file.read()
    df   = _read_excel(raw)
    df   = _apply_mapping(df, mapping_json)
    overwrite = overwrite_str in ("1", "true", "True", True)
    date_fields = date_fields or []
    imported, skipped, errors = 0, 0, []

    for i, row in df.iterrows():
        d = row.to_dict()
        # Check required fields
        missing = [f for f in required_fields if not d.get(f) or (isinstance(d.get(f), float) and pd.isna(d[f]))]
        if missing:
            skipped += 1
            errors.append(f"Row {i+2}: missing required field(s): {', '.join(missing)}")
            continue
        try:
            pk_val = str(d[pk_field])
            exists = db.query(model_class).filter(getattr(model_class, pk_field) == pk_val).first()
            if exists and not overwrite:
                skipped += 1
                continue
            fields = {k: _safe(v) for k,v in d.items() if hasattr(model_class, k)}
            for df_field in date_fields:
                if fields.get(df_field):
                    try: fields[df_field] = pd.to_datetime(fields[df_field]).date()
                    except Exception: fields[df_field] = None
            if exists:
                for k, v in fields.items(): setattr(exists, k, v)
            else:
                db.add(model_class(**fields))
            db.commit(); imported += 1
        except Exception as e:
            db.rollback(); skipped += 1
            errors.append(f"Row {i+2} ({d.get(pk_field,'?')}): {str(e)[:100]}")
    return _result(imported, skipped, errors)

# ── IMPORT ENDPOINTS ──────────────────────────────────────────────────────────
@router.post("/import/hk_master")
async def import_hk_master(file: UploadFile = File(...), mapping: str = Form(""), overwrite: str = Form("0"), db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    return await _do_import(file, mapping, overwrite, db, models.HKMasterModel, "code", ["code","name"])

@router.post("/import/items")
async def import_items(file: UploadFile = File(...), mapping: str = Form(""), overwrite: str = Form("0"), db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    return await _do_import(file, mapping, overwrite, db, models.ItemModel, "code", ["code","name"])

@router.post("/import/vendors")
async def import_vendors(file: UploadFile = File(...), mapping: str = Form(""), overwrite: str = Form("0"), db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    return await _do_import(file, mapping, overwrite, db, models.VendorModel, "code", ["code","name"])

@router.post("/import/locations")
async def import_locations(file: UploadFile = File(...), mapping: str = Form(""), overwrite: str = Form("0"), db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    return await _do_import(file, mapping, overwrite, db, models.LocationModel, "code", ["code","name"])

@router.post("/import/norms")
async def import_norms(file: UploadFile = File(...), mapping: str = Form(""), overwrite: str = Form("0"), db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    return await _do_import(file, mapping, overwrite, db, models.ConsumptionNormModel, "item_code", ["item_code"])

@router.post("/import/issuances")
async def import_issuances(file: UploadFile = File(...), mapping: str = Form(""), overwrite: str = Form("0"), db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    return await _do_import(file, mapping, overwrite, db, models.IssuanceLogModel, "issue_id", ["issue_id","item_code"], date_fields=["date"])

@router.post("/import/returns")
async def import_returns(file: UploadFile = File(...), mapping: str = Form(""), overwrite: str = Form("0"), db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    return await _do_import(file, mapping, overwrite, db, models.ReturnLogModel, "return_id", ["return_id"], date_fields=["return_date"])



# ─── AUTO CODE GENERATION ─────────────────────────────────────────────────────
@router.get("/next-code/{entity}")
def next_code(entity: str, prefix: Optional[str] = None, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    """Auto-generate next code. For items, pass ?prefix=DG to get DG-001 instead of HK-001."""
    prefixes = {
        "item": ("items", models.ItemModel, "code", "HK-"),
        "vendor": ("vendors", models.VendorModel, "code", "VND-"),
        "issuance": ("issuances", models.IssuanceLogModel, "issue_id", "ISS-"),
        "return": ("returns", models.ReturnLogModel, "return_id", "RET-"),
        "pr": ("prs", models.PurchaseRequisitionModel, "pr_no", "PR-"),
        "po": ("pos", models.PurchaseOrderModel, "po_no", "PO-"),
        "grn": ("grns", models.GRNModel, "grn_no", "GRN-"),
    }
    if entity not in prefixes:
        raise HTTPException(400, f"Unknown entity: {entity}")
    _, model_cls, pk_attr, default_prefix = prefixes[entity]
    pfx = (prefix.strip().rstrip("-") + "-") if prefix else default_prefix
    rows = db.query(getattr(model_cls, pk_attr)).filter(
        getattr(model_cls, pk_attr).like(f"{pfx}%")
    ).all()
    nums = []
    for (val,) in rows:
        try:
            n = int(str(val).replace(pfx, "").split("-")[-1])
            nums.append(n)
        except Exception:
            pass
    next_n = (max(nums) + 1) if nums else 1
    return {"code": f"{pfx}{str(next_n).zfill(3)}"}

# ─── VENDOR PROFILE ───────────────────────────────────────────────────────────
@router.get("/vendors/{code}/profile")
def vendor_profile(code: str, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    vendor = db.query(models.VendorModel).filter(models.VendorModel.code == code).first()
    if not vendor: raise HTTPException(404)
    pos = db.query(models.PurchaseOrderModel).filter(models.PurchaseOrderModel.vendor_code == code).all()
    grns = db.query(models.GRNModel).filter(models.GRNModel.vendor_code == code).all()
    total_ordered = sum((p.qty_ordered or 0) * (p.rate or 0) for p in pos)
    total_received = sum((g.accepted_qty or 0) * (g.rate or 0) for g in grns)
    on_time = sum(1 for g in grns if g.status == "Stored")
    items_map = {i.code: i for i in db.query(models.ItemModel).all()}
    categories_supplied = list(set(items_map[p.item_code].category for p in pos if p.item_code and p.item_code in items_map and items_map[p.item_code].category))
    recent_pos = sorted(pos, key=lambda p: str(p.po_date or ""), reverse=True)[:5]
    # Reliability score: % of POs that reached Fully Received
    completed = sum(1 for p in pos if p.status in ("Fully Received", "Closed"))
    reliability = round((completed / len(pos) * 100) if pos else 0, 1)
    return {
        "vendor": {k: v for k, v in vendor.__dict__.items() if not k.startswith("_")},
        "stats": {
            "total_pos": len(pos),
            "total_ordered_value": round(total_ordered, 2),
            "total_received_value": round(total_received, 2),
            "reliability_score": reliability,
            "on_time_deliveries": on_time,
        },
        "recent_orders": [
            {k: v for k, v in p.__dict__.items() if not k.startswith("_")}
            for p in recent_pos
        ],
        "categories": categories_supplied,
    }

@router.get("/vendors/{code}/services")
def get_vendor_services(code: str, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    svcs = db.query(models.ThirdPartyServiceModel).filter(
        models.ThirdPartyServiceModel.vendor_code == code
    ).all()
    return [{k: v for k, v in s.__dict__.items() if k != "_sa_instance_state"} for s in svcs]


# ─── VENDOR RATE CARDS ────────────────────────────────────────────────────────
# Pricing sheets / quotations uploaded per-vendor. Stored on disk under
# <UPLOAD_DIR>/vendors/<vendor_code>/rate-cards/<id><ext>; DB row holds metadata.
_UPLOAD_ROOT = os.environ.get("UPLOAD_DIR") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "uploads")
)
_MAX_RATE_CARD_BYTES = 50 * 1024 * 1024   # 50 MB

# ext → mime. Keep the set tight; anything else is rejected.
_RATE_CARD_TYPES = {
    ".pdf":  "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
}


def _rate_card_dir(vendor_code: str) -> str:
    p = os.path.join(_UPLOAD_ROOT, "vendors", vendor_code, "rate-cards")
    os.makedirs(p, exist_ok=True)
    return p


def _rate_card_to_dict(r) -> dict:
    return {
        "id":          r.id,
        "vendor_code": r.vendor_code,
        "file_name":   r.file_name,
        "file_size":   r.file_size,
        "mime_type":   r.mime_type,
        "uploaded_at": r.uploaded_at,
        "uploaded_by": r.uploaded_by,
    }


@router.post("/vendors/{code}/rate-cards")
async def upload_vendor_rate_card(
    code: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.UserModel = Depends(_get_current_user),
):
    _require_role(current_user, "admin")

    vendor = db.query(models.VendorModel).filter(models.VendorModel.code == code).first()
    if not vendor:
        raise HTTPException(404, "Vendor not found")

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _RATE_CARD_TYPES:
        raise HTTPException(400, "Allowed types: PDF, DOCX, XLSX, JPG, PNG")

    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty file")
    if len(content) > _MAX_RATE_CARD_BYTES:
        raise HTTPException(400, f"File exceeds {_MAX_RATE_CARD_BYTES // (1024*1024)}MB limit")

    rc_id = uuid.uuid4().hex
    stored_name = f"{rc_id}{ext}"
    dest_path = os.path.join(_rate_card_dir(code), stored_name)
    with open(dest_path, "wb") as f:
        f.write(content)

    row = models.VendorRateCardModel(
        id          = rc_id,
        vendor_code = code,
        file_name   = file.filename or stored_name,
        stored_name = stored_name,
        file_size   = len(content),
        mime_type   = _RATE_CARD_TYPES[ext],
        uploaded_at = datetime.datetime.utcnow().isoformat(),
        uploaded_by = current_user.email,
    )
    db.add(row)
    _log(db, "vendor.rate_card_uploaded", "vendor", code,
         vendor_code=code, actor_id=current_user.id, actor_role=current_user.role,
         meta={"rate_card_id": rc_id, "file_name": row.file_name, "file_size": row.file_size})
    db.commit()
    db.refresh(row)
    return _rate_card_to_dict(row)


@router.get("/vendors/{code}/rate-cards")
def list_vendor_rate_cards(code: str, db: Session = Depends(get_db),
                           current_user: models.UserModel = Depends(_get_current_user)):
    rows = (db.query(models.VendorRateCardModel)
              .filter(models.VendorRateCardModel.vendor_code == code)
              .order_by(models.VendorRateCardModel.uploaded_at.desc())
              .all())
    return [_rate_card_to_dict(r) for r in rows]


@router.get("/vendors/{code}/rate-cards/{rate_card_id}")
def get_vendor_rate_card(code: str, rate_card_id: str, db: Session = Depends(get_db),
                         current_user: models.UserModel = Depends(_get_current_user)):
    row = (db.query(models.VendorRateCardModel)
             .filter_by(id=rate_card_id, vendor_code=code).first())
    if not row:
        raise HTTPException(404, "Rate card not found")
    path = os.path.join(_rate_card_dir(code), row.stored_name)
    if not os.path.exists(path):
        raise HTTPException(404, "File missing on disk")
    safe_name = (row.file_name or f"rate-card{os.path.splitext(row.stored_name)[1]}").replace('"', '')
    return FileResponse(
        path,
        media_type=row.mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{safe_name}"'},
    )


@router.delete("/vendors/{code}/rate-cards/{rate_card_id}")
def delete_vendor_rate_card(code: str, rate_card_id: str, db: Session = Depends(get_db),
                            current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    row = (db.query(models.VendorRateCardModel)
             .filter_by(id=rate_card_id, vendor_code=code).first())
    if not row:
        raise HTTPException(404, "Rate card not found")
    path = os.path.join(_rate_card_dir(code), row.stored_name)
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass   # row delete still proceeds; orphan file is acceptable
    meta = {"rate_card_id": rate_card_id, "file_name": row.file_name}
    db.delete(row)
    _log(db, "vendor.rate_card_deleted", "vendor", code,
         vendor_code=code, actor_id=current_user.id, actor_role=current_user.role, meta=meta)
    db.commit()
    return {"deleted": rate_card_id}

# ─── MONTHLY BUDGET FORECAST ──────────────────────────────────────────────────
@router.get("/budget/monthly-forecast")
def monthly_budget_forecast(inflation: float = 6, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    """Return month-by-month actual spend + forecasted budget for next 12 months."""
    issuances = db.query(models.IssuanceLogModel).all()
    # Group actual spend by month
    monthly_actual = {m: 0.0 for m in range(1, 13)}
    for iss in issuances:
        m = iss.month or (iss.date.month if iss.date else None)
        if m and 1 <= m <= 12:
            monthly_actual[m] += (iss.qty or 0) * (iss.rate or 0)
    # Average actual monthly spend as base
    avg = sum(monthly_actual.values()) / 12
    inf_factor = 1 + inflation / 100
    # Build 12-month plan: actual where available, forecast where not
    today = date.today()
    current_month = today.month
    months_out = []
    for i, m in enumerate(range(1, 13)):
        label = calendar.month_abbr[m]
        actual = round(monthly_actual[m], 2)
        # Forecasted = avg * seasonal weight (crude), scaled up by inflation vs avg
        seasonal = actual / avg if avg > 0 else 1.0
        forecast = round(avg * inf_factor * (seasonal if seasonal > 0.1 else 1.0), 2)
        months_out.append({
            "month": m,
            "label": label,
            "actual": actual,
            "forecast": forecast,
            "is_past": m < current_month,
            "is_current": m == current_month,
        })
    yearly_actual  = round(sum(monthly_actual.values()), 2)
    yearly_forecast = round(sum(r["forecast"] for r in months_out), 2)
    return {
        "months": months_out,
        "yearly_actual": yearly_actual,
        "yearly_forecast": yearly_forecast,
        "avg_monthly": round(avg, 2),
        "inflation_pct": inflation,
    }

# ─── DELETE ROUTES (admin+ only) ─────────────────────────────────────────────
@router.delete("/hk-master/bulk")
def delete_hk_bulk(data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    codes = data.get("ids", [])
    db.query(models.HKMasterModel).filter(models.HKMasterModel.code.in_(codes)).delete(synchronize_session=False); db.commit(); return {"deleted": len(codes)}

@router.delete("/hk-master/{code}")
def delete_hk_item(code: str, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    db.query(models.HKMasterModel).filter(models.HKMasterModel.code == code).delete(); db.commit(); return {"deleted": code}

@router.delete("/items/bulk")
def delete_items_bulk(data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    codes = data.get("ids", [])
    db.query(models.ItemModel).filter(models.ItemModel.code.in_(codes)).delete(synchronize_session=False); db.commit(); return {"deleted": len(codes)}

@router.delete("/items/{code}")
def delete_item(code: str, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    db.query(models.ItemModel).filter(models.ItemModel.code == code).delete(); db.commit(); return {"deleted": code}

@router.delete("/vendors/bulk")
def delete_vendors_bulk(data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    codes = data.get("ids", [])
    db.query(models.VendorModel).filter(models.VendorModel.code.in_(codes)).delete(synchronize_session=False); db.commit(); return {"deleted": len(codes)}

@router.delete("/vendors/{code}")
def delete_vendor(code: str, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    db.query(models.VendorModel).filter(models.VendorModel.code == code).delete(); db.commit(); return {"deleted": code}

@router.delete("/locations/bulk")
def delete_locations_bulk(data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    codes = data.get("ids", [])
    db.query(models.LocationModel).filter(models.LocationModel.code.in_(codes)).delete(synchronize_session=False); db.commit(); return {"deleted": len(codes)}

@router.delete("/locations/{code}")
def delete_location(code: str, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    db.query(models.LocationModel).filter(models.LocationModel.code == code).delete(); db.commit(); return {"deleted": code}

@router.delete("/issuances/bulk")
def delete_issuances_bulk(
    data: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    ids = data.get("ids", [])
    rows = db.query(models.IssuanceLogModel).filter(models.IssuanceLogModel.issue_id.in_(ids)).all()
    for iss in rows:
        _reverse_issuance_stock(db, iss, current_user)
        db.delete(iss)
    db.commit()
    return {"deleted": len(rows)}

@router.delete("/issuances/{issue_id}")
def delete_issuance(issue_id: str, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    iss = db.query(models.IssuanceLogModel).filter_by(issue_id=issue_id).first()
    if not iss:
        raise HTTPException(404, "Issuance not found")
    _reverse_issuance_stock(db, iss, current_user)
    db.delete(iss)
    db.commit()
    return {"deleted": issue_id}

@router.delete("/returns/bulk")
def delete_returns_bulk(data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    ids = data.get("ids", [])
    db.query(models.ReturnLogModel).filter(models.ReturnLogModel.return_id.in_(ids)).delete(synchronize_session=False); db.commit(); return {"deleted": len(ids)}

@router.delete("/returns/{return_id}")
def delete_return(return_id: str, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    db.query(models.ReturnLogModel).filter(models.ReturnLogModel.return_id == return_id).delete(); db.commit(); return {"deleted": return_id}

@router.delete("/purchase-requisitions/bulk")
def delete_prs_bulk(data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    ids = data.get("ids", [])
    db.query(models.PurchaseRequisitionModel).filter(models.PurchaseRequisitionModel.pr_no.in_(ids)).delete(synchronize_session=False); db.commit(); return {"deleted": len(ids)}

@router.delete("/purchase-requisitions/{pr_no}")
def delete_pr(pr_no: str, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    db.query(models.PurchaseRequisitionModel).filter(models.PurchaseRequisitionModel.pr_no == pr_no).delete(); db.commit(); return {"deleted": pr_no}

@router.delete("/purchase-orders/bulk")
def delete_pos_bulk(data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    ids = data.get("ids", [])
    db.query(models.PurchaseOrderModel).filter(models.PurchaseOrderModel.po_no.in_(ids)).delete(synchronize_session=False); db.commit(); return {"deleted": len(ids)}

@router.delete("/purchase-orders/{po_no}")
def delete_po(po_no: str, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    db.query(models.PurchaseOrderModel).filter(models.PurchaseOrderModel.po_no == po_no).delete(); db.commit(); return {"deleted": po_no}

@router.delete("/grns/bulk")
def delete_grns_bulk(data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    ids = data.get("ids", [])
    grns = db.query(models.GRNModel).filter(models.GRNModel.grn_no.in_(ids)).all()
    for grn in grns:
        _reverse_grn_stock(db, grn, current_user)
        db.delete(grn)
    db.commit()
    return {"deleted": len(grns)}

@router.delete("/grns/{grn_no}")
def delete_grn(grn_no: str, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    grn = db.query(models.GRNModel).filter_by(grn_no=grn_no).first()
    if not grn:
        raise HTTPException(404, "GRN not found")
    _reverse_grn_stock(db, grn, current_user)
    db.delete(grn)
    db.commit()
    return {"deleted": grn_no}

@router.delete("/consumption-norms/bulk")
def delete_norms_bulk(data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    ids = data.get("ids", [])
    db.query(models.ConsumptionNormModel).filter(models.ConsumptionNormModel.id.in_(ids)).delete(synchronize_session=False); db.commit(); return {"deleted": len(ids)}

@router.delete("/consumption-norms/{id}")
def delete_norm(id: int, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    db.query(models.ConsumptionNormModel).filter(models.ConsumptionNormModel.id == id).delete(); db.commit(); return {"deleted": id}


# ═══════════════════════════════════════════════════════════════════════════════
# AUTH ROUTES
# ═══════════════════════════════════════════════════════════════════════════════
import datetime as _dt


# ─── EVENT LOG & ANALYTICS DATA API ──────────────────────────────────────────
# These endpoints feed the future ML/intelligence layer.
# All data is append-only in event_log; never delete rows.

@router.get("/events")
def get_events(
    current_user: models.UserModel = Depends(_get_current_user),
    event_type: Optional[str] = None,
    entity: Optional[str] = None,
    item_code: Optional[str] = None,
    location_code: Optional[str] = None,
    from_ts: Optional[str] = None,
    to_ts: Optional[str] = None,
    limit: int = 500,
    db: Session = Depends(get_db)
):
    """Query the event log. Supports filtering for ML feature extraction."""
    q = db.query(models.EventLogModel)
    if event_type:    q = q.filter(models.EventLogModel.event_type == event_type)
    if entity:        q = q.filter(models.EventLogModel.entity == entity)
    if item_code:     q = q.filter(models.EventLogModel.item_code == item_code)
    if location_code: q = q.filter(models.EventLogModel.location_code == location_code)
    if from_ts:       q = q.filter(models.EventLogModel.ts >= from_ts)
    if to_ts:         q = q.filter(models.EventLogModel.ts <= to_ts)
    rows = q.order_by(models.EventLogModel.ts.desc()).limit(limit).all()
    return [
        {c.name: getattr(r, c.name) for c in models.EventLogModel.__table__.columns}
        for r in rows
    ]

@router.get("/analytics/snapshot")
def analytics_snapshot(db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    """Full denormalised snapshot for ML training / BI tools.
    Returns all entities joined with their latest context.
    Safe to call repeatedly — read-only."""
    items     = {i.code: i for i in db.query(models.ItemModel).all()}
    vendors   = {v.code: v for v in db.query(models.VendorModel).all()}
    locations = {l.code: l for l in db.query(models.LocationModel).all()}

    inventory = []
    for inv in db.query(models.InventoryModel).all():
        item = items.get(inv.item_code)
        loc  = locations.get(inv.location_code)
        closing = inv.opening_stock + inv.stock_in - inv.stock_out
        eff_rate = inv.rate if (inv.rate and inv.rate > 0) else (item.rate if item else 0)
        inventory.append({
            "item_code": inv.item_code, "item_name": item.name if item else "",
            "category": item.category if item else "",
            "location_code": inv.location_code, "location_name": loc.name if loc else "",
            "vendor_code": inv.vendor_code,
            "rate": eff_rate, "opening": inv.opening_stock,
            "stock_in": inv.stock_in, "stock_out": inv.stock_out,
            "closing": closing, "stock_value": round(max(closing, 0) * eff_rate, 2),
            "rol": item.rol if item else 0, "max_stock": item.max_stock if item else 0,
            "below_rol": closing <= (item.rol if item else 0),
        })

    issuances = []
    for iss in db.query(models.IssuanceLogModel).all():
        item = items.get(iss.item_code)
        loc  = locations.get(iss.location_code)
        issuances.append({
            "issue_id": iss.issue_id, "date": str(iss.date), "month": iss.month, "quarter": iss.quarter,
            "item_code": iss.item_code, "item_name": item.name if item else "",
            "category": item.category if item else "",
            "qty": iss.qty, "uom": iss.uom, "rate": iss.rate,
            "value": round((iss.qty or 0) * (iss.rate or 0), 2),
            "location_code": iss.location_code, "location_name": loc.name if loc else "",
            "department": iss.department,
        })

    prs = []
    for pr in db.query(models.PurchaseRequisitionModel).all():
        item = items.get(pr.item_code)
        prs.append({
            "pr_no": pr.pr_no, "pr_date": str(pr.pr_date), "item_code": pr.item_code,
            "item_name": item.name if item else "", "category": item.category if item else "",
            "req_qty": pr.req_qty, "location_code": pr.location_code,
            "department": pr.department, "priority": pr.priority,
            "status": pr.status, "approved_by": pr.approved_by,
        })

    grns = []
    for g in db.query(models.GRNModel).all():
        item   = items.get(g.item_code)
        vendor = vendors.get(g.vendor_code)
        grns.append({
            "grn_no": g.grn_no, "grn_date": str(g.grn_date), "po_no": g.po_no,
            "item_code": g.item_code, "item_name": item.name if item else "",
            "vendor_code": g.vendor_code, "vendor_name": vendor.name if vendor else "",
            "accepted_qty": g.accepted_qty, "rate": g.rate,
            "value": round((g.accepted_qty or 0) * (g.rate or 0), 2),
            "store_location": g.store_location, "status": g.status,
        })

    event_count = db.query(func.count(models.EventLogModel.id)).scalar()

    return {
        "generated_at": datetime.datetime.utcnow().isoformat(),
        "event_log_rows": event_count,
        "inventory": inventory,
        "issuances": issuances,
        "purchase_requisitions": prs,
        "grns": grns,
        "vendors": [
            {"code": v.code, "name": v.name, "category": v.category,
             "rating": v.rating, "city": v.city, "status": v.status}
            for v in db.query(models.VendorModel).all()
        ],
        "items": [
            {"code": i.code, "name": i.name, "category": i.category,
             "uom": i.uom, "rate": i.rate, "rol": i.rol, "max_stock": i.max_stock}
            for i in db.query(models.ItemModel).all()
        ],
    }

@router.get("/analytics/item-velocity")
def item_velocity(db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    """Consumption rate per item per location per month — core ML feature."""
    rows = db.query(
        models.IssuanceLogModel.item_code,
        models.IssuanceLogModel.location_code,
        models.IssuanceLogModel.month,
        func.sum(models.IssuanceLogModel.qty).label("total_qty"),
        func.sum(models.IssuanceLogModel.qty * models.IssuanceLogModel.rate).label("total_value"),
        func.count(models.IssuanceLogModel.issue_id).label("txn_count"),
    ).group_by(
        models.IssuanceLogModel.item_code,
        models.IssuanceLogModel.location_code,
        models.IssuanceLogModel.month,
    ).all()
    items = {i.code: i.name for i in db.query(models.ItemModel).all()}
    return [
        {"item_code": r.item_code, "item_name": items.get(r.item_code, ""),
         "location_code": r.location_code, "month": r.month,
         "total_qty": r.total_qty, "total_value": round(r.total_value or 0, 2),
         "txn_count": r.txn_count}
        for r in rows
    ]


AVATAR_COLORS = ["#f0a500","#3b82f6","#10b981","#8b5cf6","#ef4444","#06b6d4","#f97316","#ec4899"]

# Login throttling: temporary in-process protection for local/single-worker deployments.
# Production deployments with multiple replicas should move these counters to a shared
# store (for example Redis) or enforce equivalent limits at the API gateway.
_LOGIN_WINDOW_SECONDS = 15 * 60
_LOGIN_EMAIL_MAX_FAILURES = 5
_LOGIN_IP_MAX_FAILURES = 20
_login_failures = {}

def _login_key_state(key):
    now = datetime.datetime.now(datetime.timezone.utc).timestamp()
    state = _login_failures.get(key)
    if not state or state["window_start"] + _LOGIN_WINDOW_SECONDS <= now:
        state = {"count": 0, "window_start": now, "blocked_until": 0}
        _login_failures[key] = state
    return state, now

def _check_login_rate_limit(email: str, client_ip: str):
    keys = [f"email:{email}" if email else None, f"ip:{client_ip}" if client_ip else None]
    retry_after = 0
    for key in keys:
        if not key:
            continue
        state, now = _login_key_state(key)
        if state["blocked_until"] > now:
            retry_after = max(retry_after, int(state["blocked_until"] - now) + 1)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )

def _record_login_failure(email: str, client_ip: str):
    now = datetime.datetime.now(datetime.timezone.utc).timestamp()
    for key, limit in [
        (f"email:{email}" if email else None, _LOGIN_EMAIL_MAX_FAILURES),
        (f"ip:{client_ip}" if client_ip else None, _LOGIN_IP_MAX_FAILURES),
    ]:
        if not key:
            continue
        state, _ = _login_key_state(key)
        state["count"] += 1
        if state["count"] >= limit:
            state["blocked_until"] = now + _LOGIN_WINDOW_SECONDS

def _clear_login_rate_limit(email: str, client_ip: str):
    for key in (f"email:{email}" if email else None, f"ip:{client_ip}" if client_ip else None):
        if key:
            _login_failures.pop(key, None)

def _validate_password(password: str):
    if not isinstance(password, str) or len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    if len(password) > 128:
        raise HTTPException(400, "Password must be 128 characters or fewer.")
    if not any("A" <= ch <= "Z" for ch in password):
        raise HTTPException(400, "Password must contain at least one uppercase letter.")
    if not any(ch in "!@#$%^&*(),.?\":{}|<>" for ch in password):
        raise HTTPException(400, "Password must contain at least one special character.")


@router.post("/auth/signup")
def signup(data: dict, response: Response, db: Session = Depends(get_db)):
    email = (data.get("email") or "").strip().lower()
    if not email or not data.get("password") or not data.get("full_name"):
        raise HTTPException(400, "email, password and full_name are required")
    _validate_password(data.get("password"))
    if db.query(models.UserModel).filter(models.UserModel.email == email).first():
        raise HTTPException(400, "Email already registered")
    # First user becomes super_admin automatically
    count = db.query(models.UserModel).count()
    role  = "super_admin" if count == 0 else "observer"  # never trust user-supplied role
    color = AVATAR_COLORS[count % len(AVATAR_COLORS)]
    user  = models.UserModel(
        email        = email,
        full_name    = data["full_name"],
        password_hash= hash_password(data["password"]),
        role         = role,
        department   = data.get("department", ""),
        phone        = data.get("phone", ""),
        avatar_color = color,
        is_active    = "true",
        created_at   = _dt.datetime.utcnow().isoformat(),
    )
    db.add(user); db.commit(); db.refresh(user)
    token = create_token({"sub": user.id, "role": user.role, "email": user.email})
    _set_session_cookie(response, token)
    return {"user": _user_dict(user)}

@router.post("/auth/login")
def login(request: Request, data: dict, response: Response, db: Session = Depends(get_db)):
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    client_ip = request.client.host if request.client else "unknown"
    _check_login_rate_limit(email, client_ip)

    user = db.query(models.UserModel).filter(models.UserModel.email == email).first()
    valid = bool(user) and verify_password(password, user.password_hash)
    if not valid or not _is_active_user(user.is_active):
        _record_login_failure(email, client_ip)
        raise HTTPException(401, "Invalid email or password")

    _clear_login_rate_limit(email, client_ip)
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login = _dt.datetime.now(_dt.timezone.utc).isoformat()
    db.commit()
    token = create_token({"sub": user.id, "role": user.role, "email": user.email})
    _set_session_cookie(response, token)
    return {"user": _user_dict(user)}

@router.post("/auth/logout")
def logout(response: Response):
    _clear_session_cookie(response)
    return {"status": "ok"}

@router.get("/auth/me")
def get_me(current_user: models.UserModel = Depends(_get_current_user)):
    return _user_dict(current_user)

@router.put("/auth/profile")
def update_profile(data: dict, current_user: models.UserModel = Depends(_get_current_user), db: Session = Depends(get_db)):
    allowed = ["full_name", "department", "phone", "avatar_color"]
    for k in allowed:
        if k in data:
            setattr(current_user, k, data[k])
    if data.get("new_password"):
        _validate_password(data.get("new_password"))
        if not verify_password(data.get("current_password",""), current_user.password_hash):
            raise HTTPException(400, "Current password is incorrect")
        current_user.password_hash = hash_password(data["new_password"])
    db.commit(); db.refresh(current_user)
    return _user_dict(current_user)

@router.get("/auth/users")
def list_users(current_user: models.UserModel = Depends(_get_current_user), db: Session = Depends(get_db)):
    _require_role(current_user, "admin")
    return [_user_dict(u) for u in db.query(models.UserModel).order_by(models.UserModel.id).all()]

@router.put("/auth/users/{user_id}")
def update_user(user_id: int, data: dict, current_user: models.UserModel = Depends(_get_current_user), db: Session = Depends(get_db)):
    _require_role(current_user, "admin")
    user = db.query(models.UserModel).filter(models.UserModel.id == user_id).first()
    if not user: raise HTTPException(404)
    if user.id == current_user.id:
        raise HTTPException(400, "You cannot deactivate or change your own role.")
    if user.role == "super_admin" and current_user.role != "super_admin":
        raise HTTPException(403, "Only super admins can manage super admin accounts.")
    # Super admin can change roles; admin can only deactivate/reactivate
    if "role" in data and current_user.role == "super_admin":
        if data["role"] not in ROLE_HIERARCHY:
            raise HTTPException(400, "Invalid role")
        user.role = data["role"]
    if "is_active" in data:
        if data["is_active"] not in ("true", "false"):
            raise HTTPException(400, "is_active must be true or false")
        user.is_active = data["is_active"]
    db.commit(); db.refresh(user)
    return _user_dict(user)


@router.post("/auth/users")
def create_user(data: dict, current_user: models.UserModel = Depends(_get_current_user), db: Session = Depends(get_db)):
    """Super admin creates a user account with any role."""
    if current_user.role != "super_admin":
        raise HTTPException(403, "Super admins only")
    email = (data.get("email") or "").strip().lower()
    if not email or not data.get("password") or not data.get("full_name"):
        raise HTTPException(400, "email, password and full_name are required")
    _validate_password(data.get("password"))
    if db.query(models.UserModel).filter(models.UserModel.email == email).first():
        raise HTTPException(400, "Email already registered")
    role = data.get("role", "observer")
    if role not in ROLE_HIERARCHY:
        raise HTTPException(400, "Invalid role")
    count = db.query(models.UserModel).count()
    color = AVATAR_COLORS[count % len(AVATAR_COLORS)]
    user  = models.UserModel(
        email         = email,
        full_name     = data["full_name"],
        password_hash = hash_password(data["password"]),
        role          = role,
        department    = data.get("department", ""),
        phone         = data.get("phone", ""),
        avatar_color  = color,
        is_active     = "true",
        created_at    = _dt.datetime.utcnow().isoformat(),
    )
    db.add(user); db.commit(); db.refresh(user)
    return _user_dict(user)

def _user_dict(u):
    return {
        "id": u.id, "email": u.email, "full_name": u.full_name,
        "role": u.role, "department": u.department, "phone": u.phone,
        "avatar_color": u.avatar_color, "is_active": u.is_active,
        "created_at": u.created_at, "last_login": u.last_login,
        "initials": "".join(p[0].upper() for p in (u.full_name or "U").split()[:2])
    }


@router.post("/auth/users/{user_id}/reset-password")
def reset_user_password(user_id: int, data: dict, current_user: models.UserModel = Depends(_get_current_user), db: Session = Depends(get_db)):
    """Super admin resets any user's password to a temporary one."""
    if current_user.role != "super_admin":
        raise HTTPException(403, "Super admins only")
    new_password = (data.get("new_password") or "").strip()
    _validate_password(new_password)
    user = db.query(models.UserModel).filter(models.UserModel.id == user_id).first()
    if not user: raise HTTPException(404, "User not found")
    if user.id == current_user.id:
        raise HTTPException(400, "Use the Profile page to change your own password")
    user.password_hash = hash_password(new_password)
    db.commit()
    return {"status": "ok", "message": f"Password reset for {user.email}"}


# ─── DATA RESET (super admin only) ───────────────────────────────────────────
@router.post("/admin/reset-data")
def reset_data(data: dict, db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "super_admin")
    if data.get("confirm") != "RESET":
        raise HTTPException(400, 'Safety gate: send { "confirm": "RESET" } to proceed')

    keep_masters = data.get("keep_masters", False)
    cleared = []
    for Model, label in [
        (models.EventLogModel,            "event_log"),
        (models.MonthlyBudgetModel,       "monthly_budget"),
        (models.IssuanceLogModel,         "issuance_log"),
        (models.ReturnLogModel,           "returns_log"),
        (models.GRNModel,                 "grns"),
        (models.PurchaseOrderModel,       "purchase_orders"),
        (models.PurchaseRequisitionModel, "purchase_requisitions"),
        (models.InventoryModel,           "inventory"),
    ]:
        count = db.query(Model).count()
        db.query(Model).delete(synchronize_session=False)
        cleared.append({"table": label, "deleted": count})

    if not keep_masters:
        for Model, label in [
            (models.ThirdPartyServiceModel, "third_party_services"),
            (models.HKMasterModel,          "hk_master"),
            (models.ItemModel,              "items"),
            (models.VendorModel,            "vendors"),
            (models.LocationModel,          "locations"),
        ]:
            count = db.query(Model).count()
            db.query(Model).delete(synchronize_session=False)
            cleared.append({"table": label, "deleted": count})

    db.commit()
    total_deleted = sum(r["deleted"] for r in cleared)
    return {
        "status": "ok",
        "message": f"Reset complete. {total_deleted} rows deleted. User accounts preserved.",
        "keep_masters": keep_masters,
        "tables_cleared": cleared,
        "performed_by": current_user.email,
        "performed_at": datetime.datetime.utcnow().isoformat(),
    }

@router.get("/admin/data-summary")
def data_summary(db: Session = Depends(get_db), current_user: models.UserModel = Depends(_get_current_user)):
    _require_role(current_user, "admin")
    return {
        "locations":             db.query(models.LocationModel).count(),
        "vendors":               db.query(models.VendorModel).count(),
        "hk_master":             db.query(models.HKMasterModel).count(),
        "items":                 db.query(models.ItemModel).count(),
        "inventory":             db.query(models.InventoryModel).count(),
        "consumption_norms":     db.query(models.ConsumptionNormModel).count(),
        "purchase_requisitions": db.query(models.PurchaseRequisitionModel).count(),
        "purchase_orders":       db.query(models.PurchaseOrderModel).count(),
        "grns":                  db.query(models.GRNModel).count(),
        "issuances":             db.query(models.IssuanceLogModel).count(),
        "returns":               db.query(models.ReturnLogModel).count(),
        "monthly_budget":        db.query(models.MonthlyBudgetModel).count(),
        "event_log":             db.query(models.EventLogModel).count(),
        "users":                 db.query(models.UserModel).count(),
    }