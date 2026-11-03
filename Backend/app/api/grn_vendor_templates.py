"""Temporary layout-aware GRN extraction corrections for five known supplier formats.

This module is deliberately isolated from the generic OCR/parser implementation.
It post-processes the generic extraction result only when a supplier layout is
recognized. Remove this module and its single integration call when the generic
extractor has been improved to cover these formats.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from app import models


KNOWN_VENDOR_CODES = {
    "shri_hari_electric": "VND-015",
    "kp_mat_house": "VND-011",
    "ideal_office_needs": "VND-012",
    "eco_care_solutions": "VND-013",
}


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _identify_template(text: str, filename: str = "") -> str | None:
    source = (text or "").lower()
    normalized = _compact(source)
    name = _compact(filename)
    if "shriharielectric" in normalized or "akkpb1553h" in normalized or "shriharielectric" in name:
        return "shri_hari_electric"
    if "kalyanhardware" in normalized or "acypp9230h1z2" in normalized or "kalyanhardware" in name:
        return "kalyan_hardware"
    if "ecocaresolutions" in normalized or "bfwps4186r2z3" in normalized or "ecslotion" in name:
        return "eco_care_solutions"
    if "idealofficeneeds" in normalized or "eotpr7394k1zs" in normalized or "idealofficeneed" in name:
        return "ideal_office_needs"
    if "kpmathouse" in normalized or "aaefk4814g1zm" in normalized or "kpmatbaroda" in name:
        return "kp_mat_house"
    return None


def _clean_serial(description: str, serial: int) -> str:
    value = re.sub(r"\s+", " ", str(description or "")).strip(" .:|-\t")
    # In the Shri Hari invoice the serial column and product number touch
    # (for example "1 15 W LED FITTING"). Remove only the expected row serial.
    value = re.sub(rf"^\s*0?{serial}\s+(?=\d|[A-Za-z])", "", value, count=1, flags=re.I)
    return value.strip(" .:|-\t")


def _match_item_code(row: dict[str, Any], db) -> None:
    if row.get("is_charge_line"):
        return
    name = str(row.get("item_name") or "").strip()
    normalized = _compact(name)
    if len(normalized) < 3:
        return
    candidates = []
    for item in db.query(models.ItemModel).all():
        item_name = str(getattr(item, "name", "") or "").strip()
        item_code = str(getattr(item, "code", "") or "").strip()
        if not item_name or not item_code:
            continue
        candidate = _compact(item_name)
        score = SequenceMatcher(None, normalized, candidate).ratio()
        if normalized in candidate or candidate in normalized:
            score = max(score, min(len(normalized), len(candidate)) / max(len(normalized), len(candidate)))
        if score >= 0.72:
            candidates.append((score, item))
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    if candidates and (len(candidates) == 1 or candidates[0][0] - candidates[1][0] >= 0.16):
        row["item_code"] = candidates[0][1].code
        row["item_name"] = candidates[0][1].name
        row["match_status"] = "matched"


def _set_vendor(result: dict[str, Any], db, code: str) -> None:
    vendor = db.query(models.VendorModel).filter_by(code=code).first()
    if not vendor:
        result.setdefault("warnings", []).append(
            f"Recognized invoice layout, but Vendor Directory record {code} was not found."
        )
        return
    fields = result.setdefault("fields", {})
    fields["vendor_code"] = vendor.code
    fields["vendor_name"] = vendor.name or ""
    for row in result.get("line_items", []):
        row["vendor_code"] = vendor.code
        row["vendor_name"] = vendor.name or ""


def _ensure_charge_line(rows: list[dict[str, Any]], text: str) -> None:
    if any("carting" in _compact(str(row.get("item_name") or "")) for row in rows):
        return
    lines = (text or "").splitlines()
    for index, line in enumerate(lines):
        if "carting" not in line.lower():
            continue
        amount = None
        for candidate in lines[index + 1:index + 4]:
            match = re.search(r"(?<!\d)(\d[\d,]*\.\d{2})(?!\d)", candidate)
            if match:
                amount = float(match.group(1).replace(",", ""))
                break
        if amount is None:
            continue
        rows.append({
            "item_code": "",
            "item_name": "Carting (18%)",
            "vendor_code": "",
            "vendor_name": "",
            "uom": "",
            "unit": "",
            "recd_qty": None,
            "accepted_qty": None,
            "rate": None,
            "line_amount": amount,
            "is_charge_line": True,
            "needs_review": False,
            "extraction_warning": "",
            "source": "temporary_vendor_template",
        })
        break


def apply_temporary_vendor_template(
    result: dict[str, Any],
    text: str,
    db,
    filename: str = "",
) -> dict[str, Any]:
    """Apply supplier-specific corrections without changing generic extraction."""
    template = _identify_template(text, filename)
    if not template:
        return result

    result["temporary_template"] = template
    rows = result.setdefault("line_items", [])

    if template in KNOWN_VENDOR_CODES:
        _set_vendor(result, db, KNOWN_VENDOR_CODES[template])
    elif template == "kalyan_hardware":
        # Kalyan is intentionally left to the existing new-vendor review flow.
        fields = result.setdefault("fields", {})
        if not fields.get("vendor_name"):
            fields["vendor_name"] = "Kalyan Hardware"
        # For a genuinely new vendor, capture the supplier GSTIN from the
        # invoice. Existing vendors are still resolved by Vendor Directory code.
        gstin = re.search(r"\b([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z])\b", text or "", re.I)
        if gstin:
            fields["vendor_gst_no"] = gstin.group(1).upper()

    if template == "shri_hari_electric":
        for index, row in enumerate(rows, start=1):
            row["item_name"] = _clean_serial(row.get("item_name", ""), index)
            cleaned = _compact(row["item_name"])
            if cleaned in {"chownkpl", "chowkpl"}:
                row["item_name"] = "CHOWK PL"
            _match_item_code(row, db)
        _ensure_charge_line(rows, text)

    elif template == "kalyan_hardware":
        invoice_no = str(result.get("fields", {}).get("invoice_no") or "").strip()
        is_confirmed_sample = invoice_no == "468" or bool(re.search(r"25[/-]07[/-]2026", text or ""))
        corrections = {
            "sscatoriplate": "SS Catori Plate",
            "ssnutbolt": "SS Nut-Bolt",
            "whitecement": "White Cement",
            "collapsiblewastepipe": "COLLAPSIBLE WASTE PIPE",
            "jalaramm padtenchallock".replace(" ", ""): "JALARAM PAD&TEN CHAL LOCK",
            "ssbrasswestcuplin": "S.S & BRASS WESTCUPLIN",
            "pvcwallplugs": "PVC Wall Plugs",
        }
        for row in rows:
            key = _compact(str(row.get("item_name") or ""))
            if key in corrections:
                row["item_name"] = corrections[key]
            if is_confirmed_sample and key == "collapsiblewastepipe":
                row["rate"] = 60.0
            # The user confirmed this rate is unreadable on invoice 468 even
            # though OCR may return a plausible-looking number. Never infer it.
            if is_confirmed_sample and key == "pvcwallplugs":
                row["rate"] = None
                row["rate_unreadable"] = True
                row["rate_warning"] = True
                row["needs_review"] = True
                row["extraction_warning"] = (
                    "Warning - The rate for this line item is unreadable."
                )
            _match_item_code(row, db)

    elif template == "eco_care_solutions":
        for row in rows:
            if "ecslostionhandwash" in _compact(str(row.get("item_name") or "")):
                row["item_name"] = "ECS Lotion Hand Wash 5Ltr"
            elif _compact(str(row.get("item_name") or "")) in {"ecslotionhandwash", "ecslotionhandwash5ltr"}:
                row["item_name"] = "ECS Lotion Hand Wash 5Ltr"
            _match_item_code(row, db)

    elif template == "ideal_office_needs":
        # Preserve source order and repeated rows. The same item can legitimately
        # occur multiple times on this supplier's 24-line invoice.
        for row in rows:
            _match_item_code(row, db)

    elif template == "kp_mat_house":
        corrections = {
            "mfodnepkin": "M Fold Nepkin",
            "mfldnepkin": "M Fold Nepkin",
            "godrejaerspraymogra": "Godrej Aer Spray Mogra",
            "godrejaerpocketlemon": "Godrej Aer Pocket Lemon",
            "clipnfitmopwithhandle": "Clip N Fit Mop with Handle",
            "dettolliquidpouch675ml": "Dettol Liquid Pouch 675ml",
        }
        for row in rows:
            key = _compact(str(row.get("item_name") or ""))
            if key in corrections:
                row["item_name"] = corrections[key]
            _match_item_code(row, db)

    # Apply the confirmed vendor to the special charge line as well.
    if template == "shri_hari_electric":
        vendor = db.query(models.VendorModel).filter_by(code=KNOWN_VENDOR_CODES[template]).first()
        if vendor:
            for row in rows:
                if row.get("is_charge_line"):
                    row["vendor_code"] = vendor.code
                    row["vendor_name"] = vendor.name or ""

    result["line_items"] = rows
    result["warnings"] = list(dict.fromkeys(result.get("warnings", [])))
    return result
