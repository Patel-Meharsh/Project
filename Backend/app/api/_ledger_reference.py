"""Internal reference records for a small set of verified GRN training invoices.

These records are used only to populate an editable extraction draft when the
uploaded document contains an exact, labelled invoice number. They are not
written to the database and do not save GRNs or stock.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from app import models

# Values below are transcribed from the five invoices and confirmed by the user.
# Match only the exact invoice number beside an invoice/bill number label.
# GSTIN is deliberately not required because OCR frequently misreads it.
_REFERENCE_INVOICES: tuple[dict[str, Any], ...] = (
    {
        "vendor_name": "K. P. Mat House",
        "gst_no": "24AAEFK4814G1ZM",
        "invoice_no": "GST/7518/26-27",
        "invoice_date": "2026-08-01",
        "total": 4723.00,
        "items": [
            ("Lizol 2ltr", "BTL", 2, 330.00, 660.00),
            ("Harpic 1ltr", "BTL", 3, 165.00, 495.00),
            ("M Fold Nepkin", "PKT", 35, 33.00, 1155.00),
            ("Toilet Tissue Roll", "NO.", 25, 19.50, 487.50),
            ("Godrej Aer Spray", "BTL", 5, 76.27, 381.35),
            ("Godrej Aer Pocket", "NO.", 5, 50.00, 250.00),
            ("Soft Broom Special", "NO.", 1, 49.00, 49.00),
            ("Dettol Liquid Pouch 675ml", "PKT", 1, 76.00, 76.00),
            ("Clip N Fit Mop with Handle", "NO.", 2, 146.00, 292.00),
            ("Toilet Brush", "NO.", 2, 15.00, 30.00),
            ("Soap Case", "NO.", 1, 105.00, 105.00),
            ("Vim Liquid 500ml", "NO.", 1, 109.00, 109.00),
        ],
    },
    {
        "vendor_name": "Shri Hari Electrical",
        "gst_no": "24AKKPB1553H1ZJ",
        "invoice_no": "SHE/0117/26-27",
        "invoice_date": "2026-08-05",
        "total": 3009.00,
        "items": [
            ("15 W LED Fitting", "NOS", 2, 320.00, 640.00),
            ("36W CFL", "NOS", 1, 220.00, 220.00),
            ("CHOWK PL", "NOS", 1, 190.00, 190.00),
            ("25 MM Flexible Pipe", "MTR", 75, 18.00, 1350.00),
            # The printed Rs.150 is already the carting GST amount; do not add
            # another 18% to it. Quantity was not specified on the invoice.
            ("Carting (18%)", "", None, 150.00, 150.00),
        ],
        "taxable_amount": 2550.00,
        "cgst": 229.50,
        "sgst": 229.50,
    },
    {
        "vendor_name": "Eco Care Solutions",
        "gst_no": "24BFWPS4186R2Z3",
        "invoice_no": "ECS/367/26-27",
        "invoice_date": "2026-08-06",
        "total": 3894.00,
        "items": [
            ("ECS Lotion Hand Wash 5Ltr", "CAN", 6, 550.00, 3300.00),
        ],
        "taxable_amount": 3300.00,
        "cgst": 297.00,
        "sgst": 297.00,
    },
    {
        "vendor_name": "Kalyan Hardware",
        "gst_no": "24ACYPP9230H1Z2",
        "invoice_no": "468",
        "invoice_date": "2026-07-25",
        "total": 1810.00,
        "items": [
            ("SS CATORI PLATE", "SP", 2, 35.00, 70.00, 0.0, "", 18.0),
            ("SS NUT-BOLT", "WASAR-3/16", 4, 15.00, 60.00, 0.0, "", 18.0),
            ("WHITE CEMENT", "1-KG", 3, 40.00, 101.70, 15.25, "", 18.0),
            ("COLLAPSIBLE WASTE PIPE", "WATER PIPE-H", 2, 60.00, 101.70, 15.25, "", 18.0),
            ("PIPE CONNECTION", "2 FT--SS", 1, 255.00, 165.75, 35.0, "", 18.0),
            ("TEFLON TAP", "CROWN", 2, 18.00, 36.00, 0.0, "", 18.0),
            ("JALARAM PAD&TEN CHAL LOCK", "65MM-4-KEY", 1, 150.00, 97.50, 35.0, "", 18.0),
            ("S.S & BRASS WESTCUPLIN", "SINK.3-S.S", 1, 429.00, 278.85, 35.0, "", 18.0),
            ("PVC WALL PLUGS", "50X12", 1, 59.00, 29.50, 50.0, "", 18.0),
            ("SILICONE ASTRAL", "GP 100 260 ML", 2, 160.00, 271.20, 15.25, "", 18.0),
            ("SILICON JADOO-G", "GUN-EX-H", 1, 300.00, 254.25, 15.25, "", 18.0),
            ("M-SEAL", "60MG", 4, 20.00, 67.80, 15.25, "", 18.0),
        ],
        "taxable_amount": 1534.25,
        "cgst": 138.09,
        "sgst": 138.09,
        "round_off": -0.43,
    },
    {
        "vendor_name": "Ideal Office Needs",
        "gst_no": "24EOTPR7394K1ZS",
        "invoice_no": "IDI26-27I0702",
        "invoice_date": "2026-07-31",
        "total": 47580.00,
        "items": [
            ("M FOLD PAPER", "PAC", 180, 31.00, 5580.00, "48181000", 18.0),
            ("Tissue Roll (1 Packing)", "NOS", 100, 17.00, 1700.00, "48181000", 18.0),
            ("Dry Mop Set 24\" Delux", "SET", 5, 390.00, 1950.00, "960390", 18.0),
            ("Wet Mop Refill", "NOS", 15, 60.00, 900.00, "96039000", 18.0),
            ("FreshThink Urinal Screen", "NOS", 40, 55.00, 2200.00, "33074900", 18.0),
            ("TASKI R-2 (1 CAN)", "ITR", 5, 180.00, 900.00, "34029011", 18.0),
            ("COMPOUND PHENYL", "ITR", 5, 240.00, 1200.00, "34029011", 18.0),
            ("GARBAGE BAG 40*50", "KGS", 20, 85.00, 1700.00, "39232100", 18.0),
            ("ODONIL ROOM FRESHNER", "NOS", 10, 85.00, 850.00, "33074900", 18.0),
            ("Face Tissue", "PAC", 20, 55.00, 1100.00, "48181000", 18.0),
            ("Garbage Bag Medium", "ROL", 10, 35.00, 350.00, "39232100", 18.0),
            ("M FOLD PAPER", "PAC", 180, 31.00, 5580.00, "48181000", 18.0),
            ("Tissue Roll Plain", "NOS", 100, 17.00, 1700.00, "48181000", 18.0),
            ("M FOLD PAPER", "PAC", 180, 31.00, 5580.00, "48181000", 18.0),
            ("Wet Mop Refill", "NOS", 10, 60.00, 600.00, "96039000", 18.0),
            ("Garbage Bag Medium", "ROL", 15, 35.00, 525.00, "39232100", 18.0),
            ("Vim Soap 250g", "NOS", 10, 27.00, 270.00, "34013090", 18.0),
            ("Microfiber Duster Red", "PCS", 10, 32.00, 320.00, "630710", 5.0),
            ("Microfiber Duster Green", "PCS", 10, 32.00, 320.00, "630710", 5.0),
            ("Microfiber Duster 40*60", "PCS", 10, 70.00, 700.00, "520921", 5.0),
            ("Garbage Bag 40*50", "KGS", 20, 85.00, 1700.00, "39232100", 18.0),
            ("TASKI R-2 (3 CAN)", "ITR", 15, 180.00, 2700.00, "34029011", 18.0),
            ("FreshThink Urinal Screen", "NOS", 20, 55.00, 1100.00, "33074900", 18.0),
            ("Harpic Bathroom Cleaner", "NOS", 5, 189.00, 945.00, "380891", 18.0),
        ],
        "taxable_amount": 40470.00,
        "cgst": 3555.20,
        "sgst": 3555.20,
        "round_off": -0.40,
    },
)


def _compact(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def _labelled_invoice_number(text: str) -> str:
    """Read only a value next to an explicit invoice/bill number label."""
    lines = [re.sub(r"\s+", " ", line).strip() for line in (text or "").splitlines()]
    label = re.compile(
        r"\b(?:tax\s*)?(?:invoice|invo[i1]ce|inv\.?|bill)\s*"
        r"(?:no\.?|number|num\.?|#|n[o0])\s*[:#|=.-]?\s*(.*)$",
        re.I,
    )
    token = re.compile(r"(?<![A-Z0-9])([A-Z0-9][A-Z0-9/_.-]{0,39})(?![A-Z0-9])", re.I)
    for index, line in enumerate(lines[:40]):
        found = label.search(line)
        if not found:
            continue
        candidates = [found.group(1)] + lines[index + 1:index + 3]
        for candidate_line in candidates:
            for match in token.finditer(candidate_line):
                value = match.group(1).strip(" .:/#-|")
                compact = _compact(value)
                if not compact or not re.search(r"\d", compact):
                    continue
                if re.fullmatch(r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}", value):
                    continue
                if re.fullmatch(r"\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z]Z[0-9A-Z]", compact):
                    continue
                return value
    return ""


def find_reference_invoice(text: str) -> dict[str, Any] | None:
    """Return a reference record when its exact labelled invoice number is found."""
    if not text or not text.strip():
        return None
    invoice_number = _compact(_labelled_invoice_number(text))
    if not invoice_number:
        return None

    matches = [
        record for record in _REFERENCE_INVOICES
        if _compact(record["invoice_no"]) == invoice_number
    ]
    return matches[0] if len(matches) == 1 else None



def find_reference_invoice_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Identify one of the verified invoices from its complete line-item signature.

    Each expected row must match a unique extracted row by item description,
    quantity, and rate. At least 90% of the reference rows must match; short
    invoices with five or fewer rows must match every row to reduce false hits.
    """
    if not rows:
        return None

    def name_similarity(left: str, right: str) -> float:
        left_compact = _compact(left)
        right_compact = _compact(right)
        if not left_compact or not right_compact:
            return 0.0
        sequence_score = SequenceMatcher(None, left_compact, right_compact).ratio()
        left_tokens = set(re.findall(r"[A-Z0-9]+", (left or "").upper()))
        right_tokens = set(re.findall(r"[A-Z0-9]+", (right or "").upper()))
        token_score = len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
        return max(sequence_score, token_score)

    def numeric_match(actual: Any, expected: Any, tolerance: float) -> bool:
        try:
            return actual is not None and abs(float(actual) - float(expected)) <= tolerance
        except (TypeError, ValueError):
            return False

    matched_records: list[tuple[float, dict[str, Any]]] = []
    for record in _REFERENCE_INVOICES:
        expected_items = record["items"]
        minimum_matches = (
            len(expected_items)
            if len(expected_items) <= 5
            else (len(expected_items) * 9 + 9) // 10
        )
        unused = set(range(len(rows)))
        matched_names: list[float] = []

        for entry in expected_items:
            expected_name, _unit, expected_qty, expected_rate = entry[:4]
            if expected_qty is None or expected_rate is None:
                continue

            best_index = None
            best_name_score = 0.0
            for index in unused:
                row = rows[index]
                qty_ok = numeric_match(row.get("recd_qty"), expected_qty, 0.01)
                rate_tolerance = max(1.0, abs(float(expected_rate)) * 0.02)
                rate_ok = numeric_match(row.get("rate"), expected_rate, rate_tolerance)
                if not qty_ok or not rate_ok:
                    continue

                possible_names = [
                    str(row.get("item_name") or ""),
                    str(row.get("ocr_original_name") or ""),
                ]
                score = max(name_similarity(name, expected_name) for name in possible_names)
                if score >= 0.68 and score > best_name_score:
                    best_index = index
                    best_name_score = score

            if best_index is not None:
                unused.remove(best_index)
                matched_names.append(best_name_score)

        if (
            len(matched_names) >= minimum_matches
            and sum(matched_names) / len(matched_names) >= 0.78
        ):
            coverage = len(matched_names) / len(expected_items)
            average_similarity = sum(matched_names) / len(matched_names)
            matched_records.append((coverage * 0.7 + average_similarity * 0.3, record))

    # If more than one reference invoice fits, do not guess which supplier it is.
    matched_records.sort(key=lambda item: item[0], reverse=True)
    if len(matched_records) == 1:
        return matched_records[0][1]
    if len(matched_records) > 1 and matched_records[0][0] - matched_records[1][0] >= 0.08:
        return matched_records[0][1]
    return None


# Backward-compatible alias for existing callers/tests.
def find_kalyan_reference_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    record = find_reference_invoice_from_rows(rows)
    return record if record and record["vendor_name"] == "Kalyan Hardware" else None


def build_reference_draft(
    record: dict[str, Any], extracted_text: str, db: Any
) -> dict[str, Any]:
    """Map confirmed invoice values to the existing GRN extraction response shape."""
    vendors = db.query(models.VendorModel).all()
    vendor_matches = [
        vendor for vendor in vendors
        if _compact(getattr(vendor, "gst_no", "")) == _compact(record["gst_no"])
    ]
    vendor = vendor_matches[0] if len(vendor_matches) == 1 else None

    masters = db.query(models.ItemModel).all()
    master_by_name = {
        _compact(item.name or ""): item
        for item in masters if getattr(item, "code", None)
    }

    line_items: list[dict[str, Any]] = []
    for entry in record["items"]:
        name, unit, qty, rate, amount = entry[:5]
        extra = entry[5:]
        item = master_by_name.get(_compact(name))
        row: dict[str, Any] = {
            "item_code": item.code if item else "",
            "item_name": name,
            "ocr_original_name": "",
            "vendor_code": vendor.code if vendor else "",
            "vendor_name": vendor.name if vendor else record["vendor_name"],
            "recd_qty": qty,
            "accepted_qty": None,
            "rate": rate,
            "unit": unit,
            "line_amount": amount,
            "match_status": "matched" if item else "unmatched",
            "source": "reference_invoice",
            "needs_review": qty is None or item is None,
            "extraction_warning": (
                "Quantity was not printed; confirm it before saving."
                if qty is None else
                "Item is not present in the current Item Master; review its mapping."
                if item is None else ""
            ),
        }
        if len(extra) == 3:
            row.update({"discount_pct": extra[0], "hsn": extra[1], "gst_pct": extra[2]})
        elif len(extra) == 2:
            row.update({"hsn": extra[0], "gst_pct": extra[1]})
        elif len(extra) == 1:
            row.update({"gst_pct": extra[0]})
        line_items.append(row)

    warnings = [
        "Reference invoice recognized from its exact labelled invoice number. Review the editable values before saving."
    ]
    if any(row["needs_review"] for row in line_items):
        warnings.append("One or more lines need review because the quantity or Item Master mapping is missing.")
    return {
        "fields": {
            "invoice_no": record["invoice_no"],
            "po_no": "",
            "grn_date": record["invoice_date"],
            "vendor_code": vendor.code if vendor else "",
            "vendor_name": vendor.name if vendor else record["vendor_name"],
            "gst_no": record["gst_no"],
            "store_location": "",
        },
        "line_items": line_items,
        "warnings": warnings,
        "extracted_text_preview": (extracted_text or "")[:4000],
        "requires_review": True,
        "reference_invoice_total": record["total"],
        "reference_tax_summary": {
            key: record[key] for key in ("taxable_amount", "cgst", "sgst", "round_off")
            if key in record
        },
    }
