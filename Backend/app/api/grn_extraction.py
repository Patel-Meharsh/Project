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
    """Match item master names/codes found in receipt text; quantities remain suggestions."""
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in db.query(models.ItemModel).all():
        code = (item.code or "").strip()
        name = (item.name or "").strip()
        for line in lines:
            norm_line = _norm(line)
            code_found = bool(code and re.search(r"(?<![A-Za-z0-9])" + re.escape(code) + r"(?![A-Za-z0-9])", line, re.I))
            name_norm = _norm(name)
            name_found = bool(name_norm and len(name_norm) >= 4 and name_norm in norm_line)
            if not (code_found or name_found) or not code or code in seen:
                continue
            # Avoid claiming a quantity unless the row has a numeric value.
            numbers = re.findall(r"(?<![A-Za-z])\d+(?:,\d{3})*(?:\.\d+)?", line)
            numbers = [float(n.replace(",", "")) for n in numbers]
            qty = numbers[-2] if len(numbers) >= 2 else (numbers[-1] if numbers else None)
            rate = numbers[-1] if len(numbers) >= 3 else (item.rate or 0)
            found.append({
                "item_code": code, "item_name": name,
                "vendor_code": item.vendor_code or "", "vendor_name": "",
                "recd_qty": qty, "accepted_qty": None, "rate": rate,
                "match_status": "matched", "source": "receipt_text",
            })
            seen.add(code)
            break
    return found


def _extract_fields(text: str, db: Session) -> dict[str, Any]:
    invoice_no = _first([
        r"(?:invoice|tax invoice|bill)\s*(?:no|number|#)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/_.-]{2,})",
    ], text)
    po_no = _first([
        r"(?:purchase order|\bP\.O\.?|\bPO)\s*(?:no|number|ref|#)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/_.-]{2,})",
    ], text)
    vendor_text = _first([
        r"(?:supplier|vendor)\s*(?:name)?\s*[:\-]\s*([^\n]{2,100})",
    ], text)
    date_raw = _first([
        r"(?:invoice\s*)?date\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})",
    ], text)
    invoice_date = None
    if date_raw:
        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y", "%Y-%m-%d", "%m/%d/%Y"):
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
                if len(re.sub(r"\\s+", "", page_text)) < 40
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
                                page_texts[index] = "\\n".join(
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
