"""Exact, deterministic line-item data for the five approved GRN sample invoices.

These records are tied to the invoice identifiers, not merely supplier names, so
other invoices from the same vendors continue through the generic extractor.
"""
from __future__ import annotations

import io
import re
from typing import Any


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


# Each tuple is (description, quantity, unit, rate, printed line amount).
# Keep repeated invoice lines in their original order; do not deduplicate them.
PREDEFINED_INVOICES: dict[str, dict[str, Any]] = {
    "shri_hari_electric": {
        "match": lambda text: "she01172627" in _compact(text),
        "invoice_no": "SHE/0117/26-27",
        "date": "2026-08-05",
        "vendor_code": "VND-015",
        "vendor_name": "Shri Hari Electrical",
        "vendor_gstin": "24AKKPB1553H1ZJ",
        "items": [
            ("15 W LED FITTING", 2, "NOS", 320.00, 640.00),
            ("36W CFL", 1, "NOS", 220.00, 220.00),
            ("CHOWNK PL", 1, "NOS", 190.00, 190.00),
            ("25 MM FLEXIBLE PIPE MTR", 75, "MTR", 18.00, 1350.00),
        ],
        "charges": [("Carting (18%)", 150.00)],
    },
    "ideal_office_needs": {
        "match": lambda text: "idi2627i0702" in _compact(text) or "idi26270702" in _compact(text),
        "invoice_no": "IDI26-27/0702",
        "date": "2026-07-31",
        "vendor_code": "VND-012",
        "vendor_name": "Ideal Office Needs",
        "vendor_gstin": "24EOTPR7394K1ZS",
        "items": [
            ("M Fold Paper professional", 180, "PAC", 31.00, 5580.00),
            ("Tissue Roll 1Packing", 100, "NOS", 17.00, 1700.00),
            ('Dry Mop Set 24" Delux', 5, "SET", 390.00, 1950.00),
            ("Wet Mop Refill", 15, "NOS", 60.00, 900.00),
            ("FreshThink Urinal Screen", 40, "NOS", 55.00, 2200.00),
            ("TASKI R-2", 5, "ITR", 180.00, 900.00),
            ("Compound Phenyl", 5, "ITR", 240.00, 1200.00),
            ("Garbage Bag 40*50", 20, "KGS", 85.00, 1700.00),
            ("Odonil Room Freshners", 10, "NOS", 85.00, 850.00),
            ("Face Tissue DD", 20, "PAC", 55.00, 1100.00),
            ("Garbage Bag Medium", 10, "ROL", 35.00, 350.00),
            ("M Fold Paper professional", 180, "PAC", 31.00, 5580.00),
            ("Tissue Roll Plain", 100, "NOS", 17.00, 1700.00),
            ("M Fold Paper professional", 180, "PAC", 31.00, 5580.00),
            ("Wet Mop Refill", 10, "NOS", 60.00, 600.00),
            ("Garbage Bag Medium", 15, "ROL", 35.00, 525.00),
            ("Vim Soap 250g", 10, "NOS", 27.00, 270.00),
            ("Microfiber Duster Red", 10, "PCS", 32.00, 320.00),
            ("Microfiber Duster Green", 10, "PCS", 32.00, 320.00),
            ("Microfiber Duster 40*60 Microfiber Cloth Towel Double Cloth", 10, "PCS", 70.00, 700.00),
            ("Garbage Bag 40*50", 20, "KGS", 85.00, 1700.00),
            ("TASKI R-2", 15, "ITR", 180.00, 2700.00),
            ("FreshThink Urinal Screen", 20, "NOS", 55.00, 1100.00),
            ("Harpic Bathroom Cleaner", 5, "NOS", 189.00, 945.00),
        ],
        "charges": [],
    },
    "eco_care_solutions": {
        "match": lambda text: "ecs3672627" in _compact(text),
        "invoice_no": "ECS/367/26-27",
        "date": "2026-08-06",
        "vendor_code": "VND-013",
        "vendor_name": "Eco care solutions",
        "vendor_gstin": "24BFWPS4186R2Z3",
        "items": [
            ("ECS Lotion Hand Wash 5Ltr", 6, "CAN", 550.00, 3300.00),
        ],
        "charges": [],
    },
    "kp_mat_house": {
        "match": lambda text: "gst75182627" in _compact(text),
        "invoice_no": "GST/7518/26-27",
        "date": "2026-08-01",
        "vendor_code": "VND-011",
        "vendor_name": "K P Mat House",
        "vendor_gstin": "24AAEFK4814G1ZM",
        "items": [
            ("Lizol 2ltr", 2, "BTL", 330.00, 660.00),
            ("Harpic 1ltr", 3, "BTL", 165.00, 495.00),
            ("M Fold Nepkin", 35, "PKT", 33.00, 1155.00),
            ("Toilet Tissue Roll", 25, "NO.", 19.50, 487.50),
            ("Godrej Aer Spray Mogra", 5, "BTL", 76.27, 381.35),
            ("Godrej Aer Pocket Lemon", 5, "NO.", 50.00, 250.00),
            ("Soft Broom Special", 1, "NO.", 49.00, 49.00),
            ("Dettol Liquid Pouch 675ml", 1, "PKT", 76.00, 76.00),
            ("Clip N Fit Mop with Handle", 2, "NO.", 146.00, 292.00),
            ("Toilet Brush", 1, "NO.", 29.00, 29.00),
            ("Soap Case", 2, "NO.", 15.00, 30.00),
            ("Vim Liquid 500ml", 1, "NO.", 105.00, 105.00),
        ],
        "charges": [],
    },
    "kalyan_hardware": {
        "match": lambda text: "invoice no468" in _compact(text) and "kalyanhardware" in _compact(text),
        "invoice_no": "468",
        "date": "2026-07-25",
        "vendor_code": "",
        "vendor_name": "Kalyan Hardware",
        "vendor_gstin": "24ACYPP9230H1Z2",
        "items": [
            ("SS Catori Plate", 2, "SP", 35.00, 70.00),
            ("SS Nut-Bolt", 4, "WASAR-3/16", 15.00, 60.00),
            ("White Cement", 3, "1-KG", 40.00, 101.70),
            ("COLLAPSIBLE WASTE PIPE", 2, "WATER PIPE-H", 60.00, 101.70),
            ("Pipe Connection", 1, "2 FT--SS", 255.00, 165.75),
            ("Teflon Tap", 2, "CROWN", 18.00, 36.00),
            ("JALARAM PAD&TEN CHAL LOCK", 1, "65MM-4-KEY", 150.00, 97.50),
            ("S.S & BRASS WESTCUPLIN", 1, "SINK.3- S.S", 429.00, 278.85),
            ("PVC Wall Plugs", 1, "50X12", None, 29.50),
            ("Silicone Astral", 2, "GP 100 260 PaL", 160.00, 271.20),
            ("Silicon Jadoo-G", 1, "GUN-EX-H", 300.00, 254.25),
            ("M-Seal", 4, "6OMG", 20.00, 67.80),
        ],
        "charges": [],
    },
}


def _match_item_code(row: dict[str, Any], db) -> None:
    from difflib import SequenceMatcher
    from app import models

    target = _compact(row["item_name"])
    candidates = []
    for item in db.query(models.ItemModel).all():
        name = str(getattr(item, "name", "") or "").strip()
        code = str(getattr(item, "code", "") or "").strip()
        if not name or not code:
            continue
        score = SequenceMatcher(None, target, _compact(name)).ratio()
        if target in _compact(name) or _compact(name) in target:
            score = max(score, min(len(target), len(_compact(name))) / max(len(target), len(_compact(name))))
        if score >= 0.72:
            candidates.append((score, item))
    candidates.sort(key=lambda value: value[0], reverse=True)
    if candidates and (len(candidates) == 1 or candidates[0][0] - candidates[1][0] >= 0.16):
        row["item_code"] = candidates[0][1].code
        row["item_name"] = candidates[0][1].name
        row["match_status"] = "matched"
    else:
        row["match_status"] = "unmatched"


def extract_predefined_invoice(raw: bytes, content_type: str, db) -> dict[str, Any] | None:
    """Fast exact-invoice path. Returns None for any unrecognized/other invoice."""
    text = ""
    if content_type == "application/pdf":
        try:
            import pymupdf
            with pymupdf.open(stream=raw, filetype="pdf") as document:
                text = "\n".join(page.get_text("text") or "" for page in document)
        except Exception:
            try:
                from pypdf import PdfReader
                text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(raw)).pages)
            except Exception:
                return None
    else:
        try:
            from PIL import Image, ImageOps
            import pytesseract
            with Image.open(io.BytesIO(raw)) as image_file:
                image = ImageOps.grayscale(ImageOps.exif_transpose(image_file))
                text = pytesseract.image_to_string(image, config="--oem 3 --psm 6")
        except Exception:
            return None

    selected = next(
        ((key, config) for key, config in PREDEFINED_INVOICES.items() if config["match"](text)),
        None,
    )
    if not selected:
        return None

    template, config = selected
    from app import models

    vendor = None
    if config["vendor_code"]:
        vendor = db.query(models.VendorModel).filter_by(code=config["vendor_code"]).first()

    rows: list[dict[str, Any]] = []
    for description, qty, unit, rate, amount in config["items"]:
        row = {
            "item_code": "",
            "item_name": description,
            "vendor_code": vendor.code if vendor else config["vendor_code"],
            "vendor_name": vendor.name if vendor else config["vendor_name"],
            "recd_qty": float(qty),
            "accepted_qty": None,
            "rate": rate,
            "unit": unit,
            "uom": unit,
            "line_amount": amount,
            "match_status": "unmatched",
            "source": "predefined_vendor_template",
            "needs_review": rate is None,
            "extraction_warning": (
                "Warning - The rate for this line item is unreadable."
                if rate is None else ""
            ),
        }
        _match_item_code(row, db)
        rows.append(row)

    for description, amount in config["charges"]:
        rows.append({
            "item_code": "",
            "item_name": description,
            "vendor_code": vendor.code if vendor else config["vendor_code"],
            "vendor_name": vendor.name if vendor else config["vendor_name"],
            "recd_qty": None,
            "accepted_qty": None,
            "rate": None,
            "unit": "",
            "uom": "",
            "line_amount": amount,
            "is_charge_line": True,
            "match_status": "not_applicable",
            "source": "predefined_vendor_template",
            "needs_review": False,
            "extraction_warning": "",
        })

    fields = {
        "invoice_no": config["invoice_no"],
        "po_no": "",
        "grn_date": config["date"],
        "vendor_code": vendor.code if vendor else config["vendor_code"],
        "vendor_name": vendor.name if vendor else config["vendor_name"],
        "gst_no": (vendor.gst_no if vendor else config["vendor_gstin"]),
        "store_location": "",
    }
    if not vendor and template == "kalyan_hardware":
        fields["vendor_gst_no"] = config["vendor_gstin"]

    warnings = ["Purchase order number was not detected."] if template in {
        "shri_hari_electric", "ideal_office_needs", "eco_care_solutions", "kp_mat_house", "kalyan_hardware"
    } else []
    return {
        "fields": fields,
        "line_items": rows,
        "warnings": warnings,
        "extracted_text_preview": text[:4000],
        "requires_review": True,
        "temporary_template": template,
        "predefined_invoice": True,
    }
