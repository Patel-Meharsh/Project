"""Conservative document extraction for GRN drafts.

This module only extracts candidate text/fields. It never creates a GRN or changes inventory.
Scanned-image OCR requires the Tesseract binary to be installed on the server.
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.api.routes import _get_current_user

router = APIRouter()
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
}


def _first(patterns: list[str], text: str) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1).strip(" :#\t")
    return None


def _number(value: str | None) -> float | None:
    if not value:
        return None
    cleaned = value.replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _extract_item_rows(text: str, db: Session) -> list[dict[str, Any]]:
    """Extract goods rows from common Indian tax-invoice tables and map them to Item Master."""
    from difflib import SequenceMatcher

    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]
    masters = db.query(models.ItemModel).all()
    found: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    unit_re = r"(?:BTL|BOTTLES?|PKT|PACKETS?|NOS?\.?|PCS?\.?|MTR|MET(?:RE|ER)|KGS?|GMS?|LTRS?|LIT(?:RE|ER)S?|ROLLS?|BOX(?:ES)?|SETS?|PAIRS?|PCS?)"
    amount_re = r"\d[\d,]*(?:\.\d{1,2})?"

    def match_master(description: str):
        dn = _norm(description)
        if not dn:
            return None
        scored = []
        for item in masters:
            nn = _norm(item.name or "")
            if not item.code or not nn:
                continue
            if nn == dn or nn in dn or dn in nn:
                score = 1.0
            else:
                # Token overlap helps with abbreviations/OCR punctuation while
                # rejecting matches based on a single common word.
                dt = set(re.findall(r"[a-z0-9]+", description.lower()))
                nt = set(re.findall(r"[a-z0-9]+", (item.name or "").lower()))
                overlap = len(dt & nt) / max(1, len(dt | nt))
                seq = SequenceMatcher(None, dn, nn).ratio()
                score = max(seq, overlap)
            if score >= 0.55:
                scored.append((score, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        if scored and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.10):
            return scored[0][1]
        return None

    for line in lines:
        # Ignore headers, GST breakdowns, totals, and invoice footer text.
        if re.search(r"\b(?:cgst|sgst|igst|round\s*off|taxable value|amount chargeable|grand total|total|hsn/sac|description of goods|quantity\s+rate)\b", line, re.I):
            continue
        serial_match = re.match(r"^\s*(\d{1,3})\s+(.+?)\s*$", line)
        if not serial_match:
            continue
        serial = int(serial_match.group(1))
        if serial < 1 or serial > 250:
            continue
        body = serial_match.group(2)

        # Preferred table layout: description, optional HSN, optional GST%,
        # quantity+unit, rate, optional per-unit, optional discount, amount.
        full = re.search(
            rf"^(.*?)\s+(?:\d{{4,8}}\s+)?(?:\d{{1,2}}\s*%?\s+)?"
            rf"({amount_re})\s*({unit_re})\s+({amount_re})\s*(?:{unit_re}\s*)?(?:[\d.]+\s+)?({amount_re})\s*$",
            body, re.I,
        )
        description = ""
        qty = rate = amount = None
        unit = ""
        if full:
            description = full.group(1).strip(" .:-")
            qty = _number(full.group(2))
            unit = full.group(3).upper().rstrip(".")
            rate = _number(full.group(4))
            amount = _number(full.group(5))
        else:
            # OCR often loses column spacing or omits HSN/rate columns. Locate
            # a quantity followed by a recognized unit and preserve the leading
            # description; parse the last numeric columns only when plausible.
            quantity_candidates = list(re.finditer(
                rf"(?<![A-Za-z0-9])({amount_re})\s*({unit_re})\b", body, re.I
            ))
            if not quantity_candidates:
                continue
            # Quantity is normally in the right half of the row; ignore units
            # embedded in descriptions like "Lizol 2ltr".
            quantity_match = next(
                (m for m in reversed(quantity_candidates)
                 if len(_norm(body[:m.start()])) >= 3 and re.search(r"\s", body[:m.start()])),
                None,
            )
            if not quantity_match:
                continue
            description = body[:quantity_match.start()].strip(" .:-")
            qty = _number(quantity_match.group(1))
            unit = quantity_match.group(2).upper().rstrip(".")
            trailing = body[quantity_match.end():]
            numbers = re.findall(amount_re, trailing)
            if len(numbers) >= 2:
                rate = _number(numbers[0])
                amount = _number(numbers[-1])
            elif len(numbers) == 1:
                rate = _number(numbers[0])

        # Trim HSN/GST tokens left behind by OCR/layout differences.
        description = re.sub(r"\s+\d{4,8}\s*$", "", description).strip(" .:-")
        description = re.sub(r"\s+\d{1,2}\s*%\s*$", "", description).strip(" .:-")
        if not description or len(_norm(description)) < 3 or qty is None or qty <= 0 or qty > 1_000_000:
            continue
        # A serial number followed by a tax/summary phrase is not a goods row.
        if re.search(r"\b(?:cgst|sgst|igst|total|round off|tax)\b", description, re.I):
            continue

        matched = match_master(description)
        code = (matched.code or "") if matched else ""
        if code and code in seen_codes:
            continue
        found.append({
            "item_code": code,
            "item_name": matched.name if matched else description,
            "vendor_code": (matched.vendor_code or "") if matched else "",
            "vendor_name": "",
            "recd_qty": qty,
            "accepted_qty": None,
            "rate": rate if rate is not None else ((matched.rate or 0) if matched else 0),
            "unit": unit,
            "line_amount": amount,
            "match_status": "matched" if matched else "unmatched",
            "source": "receipt_text",
        })
        if code:
            seen_codes.add(code)

    # If OCR layout prevented quantity parsing, still surface confidently detected
    # item-master names as suggestions rather than returning an empty item list.
    if not found:
        normalized_lines = [_norm(line) for line in lines]
        for item in masters:
            code = (item.code or "").strip()
            name = (item.name or "").strip()
            name_norm = _norm(name)
            if not code or not name_norm or len(name_norm) < 4 or code in seen_codes:
                continue
            if any(name_norm in line for line in normalized_lines):
                found.append({
                    "item_code": code, "item_name": name,
                    "vendor_code": item.vendor_code or "", "vendor_name": "",
                    "recd_qty": None, "accepted_qty": None, "rate": item.rate or 0,
                    "match_status": "matched", "source": "receipt_text",
                })
                seen_codes.add(code)
    return found

def _extract_fields(text: str, db: Session) -> dict[str, Any]:
    invoice_no = _first([
        r"(?:invoice|bill)\s*(?:no\.?|number|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9/_.-]{2,})",
        r"tax\s*invoice\s*(?:no\.?|number|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9/_.-]{2,})",
    ], text)
    po_no = _first([
        r"(?:purchase order|\bP\.O\.?|\bPO)\s*(?:no|number|ref|#)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/_.-]{2,})",
    ], text)
    vendor_text = _first([
        r"(?:supplier|vendor)\s*(?:name)?\s*[:\-]\s*([^\n]{2,100})",
    ], text)
    date_raw = _first([
        r"(?:invoice\s*)?dated?\s*[:\-]?\s*(\d{1,2}[-/]\w{3}[-/]\d{2,4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})",
    ], text)
    invoice_date = None
    if date_raw:
        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y", "%d-%b-%Y", "%d-%b-%y", "%d/%b/%Y", "%d/%b/%y", "%Y-%m-%d", "%m/%d/%Y"):
            try:
                invoice_date = datetime.strptime(date_raw, fmt).date().isoformat()
                break
            except ValueError:
                pass

    vendors = db.query(models.VendorModel).all()
    vendor_match = None
    if vendor_text:
        norm = re.sub(r"[^a-z0-9]", "", vendor_text.lower())
        matches = [v for v in vendors if re.sub(r"[^a-z0-9]", "", (v.name or "").lower()) in norm
                   or norm in re.sub(r"[^a-z0-9]", "", (v.name or "").lower())]
        if len(matches) == 1:
            vendor_match = matches[0]
    # Many Indian tax invoices show the supplier name as a heading rather than
    # using a literal "Vendor:" or "Supplier:" label. Match known vendor names
    # anywhere in the document, but only accept a unique, meaningful match.
    if not vendor_match:
        normalized_text = _norm(text)
        named_matches = [
            v for v in vendors
            if len(_norm(v.name or "")) >= 5 and _norm(v.name or "") in normalized_text
        ]
        if len(named_matches) == 1:
            vendor_match = named_matches[0]

    po_match = db.query(models.PurchaseOrderModel).filter_by(po_no=po_no).first() if po_no else None
    items: list[dict[str, Any]] = []
    warnings: list[str] = []
    if not text.strip():
        warnings.append("No readable text was found. This may be a scanned document; OCR may be required.")
    if date_raw and not invoice_date:
        warnings.append("A date-like value was found, but its format could not be confirmed.")
    if vendor_text and not vendor_match:
        warnings.append("Supplier text was found but could not be matched confidently to one vendor master record.")
    if po_no and not po_match:
        warnings.append("PO reference was found but does not match a known purchase order.")
    if not invoice_no:
        warnings.append("Invoice number was not detected.")
    if not po_no:
        warnings.append("Purchase order number was not detected.")

    # First identify item-master rows visible in the receipt text. If that fails,
    # use every line from the exact matched PO as a fallback.
    items = _extract_item_rows(text, db)
    if not items and po_match:
        try:
            po_lines = __import__("json").loads(po_match.line_items or "[]")
        except (ValueError, TypeError):
            po_lines = []
        for line in po_lines:
            code = str(line.get("item_code") or "")
            item = db.query(models.ItemModel).filter_by(code=code).first() if code else None
            items.append({
                "item_code": code if item else "",
                "item_name": (item.name if item else line.get("description") or line.get("item_name") or ""),
                "vendor_code": po_match.vendor_code or "",
                "vendor_name": vendor_match.name if vendor_match else "",
                "recd_qty": None,
                "accepted_qty": None,
                "rate": _number(str(line.get("rate"))) if line.get("rate") is not None else None,
                "match_status": "matched" if item else "unmatched",
                "source": "purchase_order",
            })
        if not items and po_match.item_code:
            item = db.query(models.ItemModel).filter_by(code=po_match.item_code).first()
            items.append({
                "item_code": item.code if item else "",
                "item_name": item.name if item else "",
                "vendor_code": po_match.vendor_code or "",
                "vendor_name": vendor_match.name if vendor_match else "",
                "recd_qty": None, "accepted_qty": None,
                "rate": po_match.rate, "match_status": "matched" if item else "unmatched",
                "source": "purchase_order",
            })
        if items:
            warnings.append("Line items were suggested from the matched PO. Review every item and confirm actual received and accepted quantities.")
    if not items and re.search(r"\b(?:qty|quantity)\b", text, re.IGNORECASE):
        warnings.append("Quantity text was found, but no item-master names/codes could be matched confidently. Add or match line items manually.")
    elif items and any(row.get("source") == "receipt_text" for row in items):
        warnings.append("Line items were detected from receipt text. Verify item mapping, quantities, and rates before saving.")

    if any(row.get("match_status") == "unmatched" for row in items):
        warnings.append("One or more PO line items could not be matched to the item master.")
    return {
        "fields": {
            "invoice_no": invoice_no or "",
            "po_no": po_no or "",
            "grn_date": invoice_date or "",
            "vendor_code": vendor_match.code if vendor_match else (po_match.vendor_code if po_match else ""),
            "vendor_name": vendor_match.name if vendor_match else (vendor_text or ""),
            "store_location": (po_match.delivery_location if po_match else "") or "",
        },
        "line_items": items,
        "warnings": list(dict.fromkeys(warnings)),
        "extracted_text_preview": text[:4000],
        "requires_review": True,
    }


@router.post("/grns/extract-document")
async def extract_grn_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.UserModel = Depends(_get_current_user),
):
    """Parse a PDF/image into an editable draft suggestion; does not persist anything."""
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(415, "Upload a receipt in JPG, JPEG, PNG, or PDF format.")
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Document exceeds the 10 MB upload limit.")
    if not raw:
        raise HTTPException(400, "The uploaded document is empty.")

    text = ""
    if content_type == "application/pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw))
            if len(reader.pages) > 30:
                raise HTTPException(413, "PDFs are limited to 30 pages.")

            # Extract embedded text first; this is faster and usually more accurate for
            # digitally generated PDFs. Sparse text can indicate a scanned page with
            # only a heading or footer, so OCR those pages as well.
            page_texts = [(page.extract_text() or "").strip() for page in reader.pages]
            pages_needing_ocr = [
                index for index, page_text in enumerate(page_texts)
                if len(re.sub(r"\s+", "", page_text)) < 40
            ]

            # Render only pages that need OCR. PyMuPDF does not require Poppler.
            if pages_needing_ocr:
                try:
                    import pymupdf
                    from PIL import Image
                    import pytesseract

                    with pymupdf.open(stream=raw, filetype="pdf") as pdf_document:
                        for index in pages_needing_ocr:
                            page = pdf_document.load_page(index)
                            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
                            if pixmap.width * pixmap.height > 25_000_000:
                                raise HTTPException(413, "A rendered PDF page is too large to process.")
                            image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")
                            ocr_text = pytesseract.image_to_string(image).strip()
                            # Keep both sources on sparse/hybrid pages; don't discard
                            # embedded text if OCR finds only part of the page.
                            if ocr_text:
                                page_texts[index] = "\n".join(
                                    part for part in (page_texts[index], ocr_text) if part
                                )
                except HTTPException:
                    raise
                except ImportError:
                    raise HTTPException(
                        503,
                        "Scanned-PDF OCR is not configured. Install the PyMuPDF, Pillow, and pytesseract packages and the Tesseract OCR engine on the server.",
                    )
                except Exception:
                    raise HTTPException(
                        400,
                        "The scanned PDF could not be processed. Check that Tesseract OCR is installed and upload a clear PDF scan.",
                    )

            text = "\n".join(page_texts)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(400, "The PDF could not be read. Please upload a valid PDF.")
    else:
        try:
            from PIL import Image, ImageOps
            import pytesseract
            image = Image.open(io.BytesIO(raw))
            image = ImageOps.exif_transpose(image)  # Respect phone-camera orientation.
            if image.width * image.height > 25_000_000:
                raise HTTPException(413, "Image dimensions are too large to process.")
            # OCR engines work most predictably with a standard RGB image.
            image = image.convert("RGB")
            text = pytesseract.image_to_string(image)
        except HTTPException:
            raise
        except ImportError:
            raise HTTPException(503, "Image OCR is not configured on this server. Please use a text-based PDF or ask the administrator to install OCR support.")
        except Exception:
            raise HTTPException(400, "The image could not be processed. Try a clear PNG or JPG scan.")

    result = _extract_fields(text, db)
    result["filename"] = (file.filename or "document")[:160]
    result["document_type"] = "pdf" if content_type == "application/pdf" else "image"
    return result
