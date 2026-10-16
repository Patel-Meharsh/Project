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


def _ocr_quality_score(text: str) -> float:
    """Rank OCR candidates by readable invoice-like content, not raw text length."""
    if not text or not text.strip():
        return 0.0

    compact = re.sub(r"\s+", "", text)
    if not compact:
        return 0.0

    alnum = sum(char.isalnum() for char in compact)
    readable_ratio = alnum / max(1, len(compact))
    words = re.findall(r"[A-Za-z]{2,}", text)
    numbers = re.findall(r"\d+(?:[.,]\d+)?", text)
    invoice_terms = re.findall(
        r"\b(?:invoice|bill|date|qty|quantity|rate|amount|total|item|description|"
        r"hsn|gst|po|purchase|order|vendor|supplier|pcs|nos|kg|kgs|ltr|box|pkt)\b",
        text,
        re.IGNORECASE,
    )
    # Penalize OCR noise such as long runs of punctuation or replacement symbols.
    noise = len(re.findall(r"[^A-Za-z0-9\s.,:/()%'₹&+-]", text))
    score = (len(words) * 2.0) + (len(numbers) * 1.2) + (len(invoice_terms) * 2.5)
    score += readable_ratio * 8.0
    score -= noise * 1.5
    # Very short fragments are rarely enough to recover an invoice table.
    if len(compact) < 20:
        score *= 0.5
    return score


def _prepare_ocr_variants(image):
    """Return lightweight image variants that help Tesseract read scans and photos."""
    from PIL import Image, ImageEnhance, ImageOps, ImageFilter

    image = ImageOps.exif_transpose(image)
    if image.width * image.height > 25_000_000:
        raise HTTPException(413, "Image dimensions are too large to process.")

    gray = ImageOps.grayscale(image)
    gray = ImageOps.autocontrast(gray)
    # Small phone uploads and 150-DPI PDF renders often need more pixels for
    # character recognition. Keep the existing 25MP safety cap in place.
    longest = max(gray.size)
    if longest < 2600:
        scale = min(2.0, 2600 / max(1, longest))
        target = (int(gray.width * scale), int(gray.height * scale))
        if target[0] * target[1] <= 25_000_000:
            gray = gray.resize(target, Image.Resampling.LANCZOS)

    sharp = ImageEnhance.Sharpness(gray).enhance(1.6).filter(ImageFilter.SHARPEN)
    # A thresholded variant can improve faint photocopies; retain grayscale too,
    # because thresholding can erase thin fonts and decimal points.
    threshold = gray.point(lambda pixel: 255 if pixel > 175 else 0)
    return [gray, sharp, threshold]


def _run_ocr_candidates(image, modes: tuple[int, ...] = (6, 4, 11)) -> str:
    """Try multiple preprocessed images/layout modes and choose the most readable text."""
    import pytesseract

    candidates: list[str] = []
    for variant in _prepare_ocr_variants(image):
        for mode in modes:
            candidate = pytesseract.image_to_string(
                variant, config=f"--oem 3 --psm {mode}"
            ).strip()
            if candidate:
                candidates.append(candidate)

    if not candidates:
        return ""
    return max(candidates, key=_ocr_quality_score)


def _extract_item_rows(text: str, db: Session) -> list[dict[str, Any]]:
    """Extract invoice rows even when OCR breaks a table into uneven text lines."""
    from difflib import SequenceMatcher

    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]
    masters = db.query(models.ItemModel).all()
    found: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    unit_re = r"(?:BTL|BOTTLES?|PKT|PACKETS?|NOS?\.?|PCS?\.?|MTR|MET(?:RE|ER)|KGS?|GMS?|LTRS?|LIT(?:RE|ER)S?|ROLLS?|BOX(?:ES)?|SETS?|PAIRS?)"
    number_re = r"\d[\d,]*(?:\.\d{1,2})?"

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
                dt = set(re.findall(r"[a-z0-9]+", description.lower()))
                nt = set(re.findall(r"[a-z0-9]+", (item.name or "").lower()))
                overlap = len(dt & nt) / max(1, len(dt | nt))
                seq = SequenceMatcher(None, dn, nn).ratio()
                score = max(seq, overlap)
            if score >= 0.48:
                scored.append((score, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        if scored and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.08):
            return scored[0][1]
        return None

    for line in lines:
        if re.search(r"\b(?:cgst|sgst|igst|round\s*off|taxable value|amount chargeable|grand total|total|hsn/sac|description of goods)\b", line, re.I):
            continue

        # OCR may keep a row together, omit the serial number, or place a serial
        # number directly against the description. Do not require a serial number.
        body = re.sub(r"^\s*\d{1,3}\s*[.)]?\s*", "", line)
        qty_matches = list(re.finditer(rf"(?<![A-Za-z])({number_re})\s*({unit_re})\b", body, re.I))
        if not qty_matches:
            continue
        # Prefer a quantity-unit pair in the middle/right of a row. Ignore pack
        # sizes in names (e.g. "Lizol 2ltr") when a later pair exists.
        qm = next((m for m in reversed(qty_matches)
                   if len(_norm(body[:m.start()])) >= 3 and re.search(r"[A-Za-z]", body[:m.start()])), None)
        if not qm:
            continue

        prefix = body[:qm.start()].strip(" .:-")
        # Remove trailing HSN and GST columns from the description if OCR placed
        # those columns before quantity.
        prefix = re.sub(r"\s+\d{4,8}\s*$", "", prefix).strip()
        prefix = re.sub(r"\s+\d{1,2}\s*%?\s*$", "", prefix).strip()
        # If OCR combines columns in an unusual order, keep the leading textual
        # span only; numeric-only spans are not item descriptions.
        description_match = re.match(r"([A-Za-z][A-Za-z0-9 &()/.,'_-]{2,}?)\s*(?=\s+\d{4,8}\b|$)", prefix)
        description = (description_match.group(1) if description_match else prefix).strip(" .:-")
        description = re.sub(r"\s+", " ", description)
        if len(_norm(description)) < 3 or not re.search(r"[A-Za-z]", description):
            continue
        if re.search(r"\b(?:cgst|sgst|igst|total|round off|tax|gstin|invoice|dated)\b", description, re.I):
            continue

        qty = _number(qm.group(1))
        unit = qm.group(2).upper().rstrip(".")
        tail = body[qm.end():]
        trailing_numbers = re.findall(number_re, tail)
        rate = _number(trailing_numbers[0]) if trailing_numbers else None
        amount = _number(trailing_numbers[-1]) if len(trailing_numbers) >= 2 else None

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

    # Last-resort suggestions: match known item names anywhere in OCR text.
    # This still surfaces item choices when OCR separates table columns by line.
    if not found:
        normalized_text = _norm(text)
        for item in masters:
            code, name = (item.code or "").strip(), (item.name or "").strip()
            nn = _norm(name)
            if code and nn and len(nn) >= 4 and nn in normalized_text and code not in seen_codes:
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
                # Some digital PDFs expose plenty of header/footer text while
                # their item table is not extractable as usable rows. OCR those too.
                or not _extract_item_rows(page_text, db)
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
                            # Compare grayscale, sharpened, and thresholded scans using
                            # invoice-aware scoring rather than simply choosing the longest OCR.
                            ocr_text = _run_ocr_candidates(image, modes=(6, 4, 11))
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
            from PIL import Image
            image = Image.open(io.BytesIO(raw))
            # OCR helper handles orientation, contrast, resolution, and candidate scoring.
            text = _run_ocr_candidates(image, modes=(6, 4, 11))
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
