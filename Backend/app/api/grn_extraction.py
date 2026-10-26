"""Keyword-driven GRN document extraction.

Extracts editable suggestions only; it never creates a GRN or changes stock.
Digital PDF text is preferred; scanned PDFs and images use Tesseract OCR.
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.api.routes import _get_current_user

router = APIRouter()
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 30
MAX_PIXELS = 25_000_000

# Keep synonyms here so document-specific tuning doesn't create parser branches.
KEYWORDS = {
    "invoice_no": [r"tax\s*invoice\s*(?:no\.?|number|#)", r"invoice\s*(?:no\.?|number|#)", r"\binv\.?\s*(?:no\.?|number|#)", r"bill\s*(?:no\.?|number|#)"],
    "po_no": [r"purchase\s*order\s*(?:no\.?|number|#)", r"\bP\.?O\.?\s*(?:no\.?|number|#)", r"\bPO\s*[:#-]"],
    "date": [r"invoice\s*date", r"bill\s*date", r"\bdated\b", r"\bdate\b"],
    "gstin": [r"\bGSTIN\s*/?\s*UIN\b", r"\bGSTIN\b", r"\bGST\s*No\.?\b"],
    "description": [r"description(?:\s+of\s+goods)?", r"item(?:\s+description|\s+name)?", r"particulars", r"product\s+name", r"material\s+description"],
    "qty": [r"quantity", r"\bqty\b", r"received\s*qty"],
    "uom": [r"unit\s*of\s*measure", r"\buom\b", r"\bunit\b"],
    "rate": [r"unit\s*price", r"\brate\b", r"price\s*/\s*unit", r"basic\s*rate"],
    "amount": [r"line\s*amount", r"taxable\s*value", r"\bamount\b", r"total\s*price", r"\bvalue\b"],
}
NUM_RE = re.compile(r"(?:₹|Rs\.?\s*)?\(?-?\d[\d,]*(?:\.\d+)?\)?", re.I)
TOTAL_RE = re.compile(r"\b(?:sub\s*total|grand\s*total|invoice\s*total|total\s*amount|cgst|sgst|igst|round\s*off|amount\s*in\s*words|bank\s*details)\b", re.I)


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _number(value: Any) -> float | None:
    if value is None:
        return None
    raw = str(value).strip()
    try:
        number = float(re.sub(r"(?i)rs\.?|inr|₹|,|\s", "", raw).strip("()"))
        return -number if raw.startswith("(") else number
    except (TypeError, ValueError):
        return None


def _field(text: str, key: str) -> str | None:
    for alias in KEYWORDS[key]:
        # Stop at a line or table-cell boundary, rather than swallowing the next field.
        for match in re.finditer(alias + r"\s*[:#-]?\s*([^\n|]{1,100})", text, re.I):
            value = match.group(1).strip(" :#-\t")
            value = re.split(r"\s{2,}|\s+(?:GSTIN|PAN|Phone|Mobile|Email)\b", value, maxsplit=1, flags=re.I)[0].strip()
            if value and not re.fullmatch(alias, value, re.I):
                return value[:100]
    return None


def _parse_date(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"\b(?:invoice\s*)?date\b\s*[:#-]?", "", value, flags=re.I).strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%y", "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(value[:30].strip(), fmt).date().isoformat()
        except ValueError:
            pass
    match = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", value)
    if match:
        day, month, year = map(int, match.groups())
        year += 2000 if year < 100 else 0
        try:
            return datetime(year, month, day).date().isoformat()
        except ValueError:
            pass
    return ""


def _ocr(image) -> str:
    try:
        import pytesseract
        from PIL import ImageEnhance, ImageFilter, ImageOps
    except ImportError as exc:
        raise HTTPException(503, "OCR needs Pillow, pytesseract, and the Tesseract OCR engine installed on the backend.") from exc
    image = ImageOps.exif_transpose(image).convert("RGB")
    if image.width * image.height > MAX_PIXELS:
        scale = (MAX_PIXELS / (image.width * image.height)) ** 0.5
        image = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))))
    image = ImageOps.grayscale(image)
    image = ImageEnhance.Contrast(image).enhance(1.6).filter(ImageFilter.SHARPEN)
    candidates = []
    for psm in (6, 4, 11):
        try:
            candidate = pytesseract.image_to_string(image, config=f"--oem 3 --psm {psm}").strip()
            terms = len(re.findall(r"\b(?:invoice|quantity|qty|rate|amount|total|GSTIN|HSN|description|PO)\b", candidate, re.I))
            score = sum(c.isalnum() for c in candidate) + 12 * terms
            candidates.append((score, candidate))
        except Exception:
            continue
    result = max(candidates, default=(0, ""))[1]
    if not result:
        raise HTTPException(422, "OCR could not read this document. Upload a clearer scan or image.")
    return result


def _read_document(raw: bytes, content_type: str) -> tuple[str, str]:
    if content_type != "application/pdf":
        try:
            from PIL import Image, ImageOps
            return _ocr(ImageOps.exif_transpose(Image.open(io.BytesIO(raw)))), "image-ocr"
        except HTTPException:
            raise
        except ImportError as exc:
            raise HTTPException(503, "Image extraction needs Pillow, pytesseract, and Tesseract OCR.") from exc
        except Exception as exc:
            raise HTTPException(400, "The image could not be processed. Try a clear JPG or PNG.") from exc
    try:
        import pymupdf
        from PIL import Image
        page_texts = []
        with pymupdf.open(stream=raw, filetype="pdf") as pdf:
            if len(pdf) > MAX_PDF_PAGES:
                raise HTTPException(413, "PDFs are limited to 30 pages.")
            if not len(pdf):
                raise HTTPException(400, "The PDF contains no pages.")
            for page in pdf:
                text = (page.get_text("text", sort=True) or "").strip()
                # OCR pages with no meaningful digital text; don't OCR all digital pages needlessly.
                if len(re.sub(r"\s+", "", text)) < 50:
                    pix = page.get_pixmap(matrix=pymupdf.Matrix(2.5, 2.5), alpha=False)
                    if pix.width * pix.height > MAX_PIXELS:
                        pix = page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
                    if pix.width * pix.height > MAX_PIXELS:
                        raise HTTPException(413, "A rendered PDF page is too large to process.")
                    text = _ocr(Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB"))
                page_texts.append(text)
        text = "\n\n".join(p for p in page_texts if p).strip()
        if not text:
            raise HTTPException(422, "No readable text was found in this PDF.")
        return text, "pdf-text-or-ocr"
    except HTTPException:
        raise
    except ImportError as exc:
        raise HTTPException(503, "PDF extraction needs PyMuPDF and Pillow; scanned pages also need pytesseract and Tesseract.") from exc
    except Exception as exc:
        raise HTTPException(400, "The PDF could not be processed. Please upload a valid PDF.") from exc


def _match_vendor(db: Session, text: str):
    vendors = db.query(models.VendorModel).all()
    gstin = _norm(_field(text, "gstin") or "")
    if gstin:
        exact = [v for v in vendors if _norm(getattr(v, "gst_no", "") or "") == gstin]
        if len(exact) == 1:
            return exact[0]
    lines = [re.sub(r"\s+", " ", line).strip(" :|\t") for line in text.splitlines()[:35]]
    candidates = [line for line in lines if 4 <= len(line) <= 100 and re.search(r"[A-Za-z]{3,}", line) and not re.search(r"invoice|GSTIN|date|phone|mobile|email|amount|buyer|consignee|description|quantity|rate|total|purchase order", line, re.I)]
    ranked = []
    for vendor in vendors:
        name = (getattr(vendor, "name", "") or "").strip()
        normalized = _norm(name)
        if len(normalized) < 5:
            continue
        score = max((SequenceMatcher(None, normalized, _norm(line)).ratio() for line in candidates), default=0)
        if normalized in _norm(text):
            score = max(score, 0.99)
        if score >= 0.84:
            ranked.append((score, vendor))
    ranked.sort(key=lambda x: x[0], reverse=True)
    if ranked and (len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= 0.08):
        return ranked[0][1]
    return None


def _match_item(db: Session, description: str):
    target = _norm(description)
    if len(target) < 3:
        return None
    items = db.query(models.ItemModel).all()
    exact = [i for i in items if target in {_norm(i.name), _norm(i.code)}]
    if len(exact) == 1:
        return exact[0]
    contained = [i for i in items if len(_norm(i.name)) >= 4 and (_norm(i.name) in target or target in _norm(i.name))]
    if len(contained) == 1:
        return contained[0]
    ranked = sorted(((SequenceMatcher(None, _norm(i.name), target).ratio(), i) for i in items), key=lambda pair: pair[0], reverse=True)
    if ranked and ranked[0][0] >= 0.90 and (len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= 0.08):
        return ranked[0][1]
    return None


def _extract_rows(text: str, db: Session, vendor) -> list[dict[str, Any]]:
    lines = [re.sub(r"[\t\u00a0]+", " ", line).strip() for line in text.splitlines()]
    header_idx = None
    for idx, line in enumerate(lines):
        desc = any(re.search(p, line, re.I) for p in KEYWORDS["description"])
        qty = any(re.search(p, line, re.I) for p in KEYWORDS["qty"])
        rate = any(re.search(p, line, re.I) for p in KEYWORDS["rate"])
        if desc and (qty or rate):
            header_idx = idx
            break
    output = []
    for line in lines[(header_idx + 1) if header_idx is not None else 0:]:
        if not line:
            continue
        if TOTAL_RE.search(line):
            break
        if len(line) > 260 or re.search(r"\b(?:invoice\s*(?:no|date)|GSTIN|purchase\s*order)\b", line, re.I):
            continue
        # Preserve column cells from PDFs/tables; OCR usually separates columns by multiple spaces.
        parts = [p.strip() for p in re.split(r"\s*\|\s*|\s{2,}", line) if p.strip()]
        if len(parts) < 3:
            nums = list(NUM_RE.finditer(line))
            if len(nums) < 2:
                continue
            description = line[:nums[0].start()].strip(" .:-")
            if not re.search(r"[A-Za-z]{2,}", description):
                continue
            parts = [description] + [m.group(0) for m in nums]
        description = parts[0].strip(" .:-")
        if len(_norm(description)) < 3 or not re.search(r"[A-Za-z]{2,}", description):
            continue
        if TOTAL_RE.search(description) or re.search(r"\b(?:description|quantity|qty|rate|amount|HSN|SAC|GSTIN)\b", description, re.I):
            continue
        numbers = [n for n in (_number(p) for p in parts[1:]) if n is not None]
        if len(numbers) < 2:
            continue
        # Typical invoice numeric tail: quantity, rate, amount. Keep missing qty unknown.
        qty = numbers[-3] if len(numbers) >= 3 else None
        rate = numbers[-2]
        amount = numbers[-1]
        if qty is not None and not (0 < qty <= 1_000_000):
            qty = None
        if not (0 <= rate <= 100_000_000):
            rate = None
        if not (0 <= amount <= 1_000_000_000):
            amount = None
        item = _match_item(db, description)
        output.append({
            "item_code": getattr(item, "code", "") if item else "",
            "item_name": getattr(item, "name", description) if item else description,
            "vendor_code": getattr(vendor, "code", "") if vendor else "",
            "vendor_name": getattr(vendor, "name", "") if vendor else "",
            "recd_qty": qty,
            "accepted_qty": qty,
            "rate": rate,
            "line_amount": amount,
            "match_status": "matched" if item else "unmatched",
            "source": "keyword_table",
        })
    unique, seen = [], set()
    for row in output:
        key = (_norm(row["item_name"]), row["recd_qty"], row["rate"], row["line_amount"])
        if key not in seen:
            seen.add(key)
            unique.append(row)
    return unique


@router.post("/grns/extract-document")
async def extract_grn_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.UserModel = Depends(_get_current_user),
):
    """Return editable field and line-item suggestions; nothing is saved automatically."""
    supplied_type = (file.content_type or "").lower().split(";")[0].strip()
    filename = (file.filename or "").lower()
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Document exceeds the 10 MB upload limit.")
    if not raw:
        raise HTTPException(400, "The uploaded document is empty.")
    if raw.startswith(b"%PDF-") or filename.endswith(".pdf") or supplied_type == "application/pdf":
        content_type = "application/pdf"
    elif raw.startswith(b"\xff\xd8\xff") or filename.endswith((".jpg", ".jpeg")) or supplied_type == "image/jpeg":
        content_type = "image/jpeg"
    elif raw.startswith(b"\x89PNG\r\n\x1a\n") or filename.endswith(".png") or supplied_type == "image/png":
        content_type = "image/png"
    else:
        raise HTTPException(415, "Upload a receipt in JPG, JPEG, PNG, or PDF format.")

    text, method = _read_document(raw, content_type)
    invoice_no = _field(text, "invoice_no") or ""
    po_raw = _field(text, "po_no") or ""
    date_raw = _field(text, "date")
    invoice_date = _parse_date(date_raw)
    vendor = _match_vendor(db, text)

    po_match = None
    if po_raw:
        po_norm = _norm(po_raw)
        matches = [po for po in db.query(models.PurchaseOrderModel).all() if _norm(getattr(po, "po_no", "") or "") == po_norm]
        if len(matches) == 1:
            po_match = matches[0]
    if not vendor and po_match:
        vendor = db.query(models.VendorModel).filter_by(code=po_match.vendor_code).first()

    rows = _extract_rows(text, db, vendor)
    warnings = []
    if not invoice_no:
        warnings.append("Invoice number was not confidently detected.")
    if not po_match:
        warnings.append("Purchase order number was not matched to a known PO. Verify it before saving.")
    if date_raw and not invoice_date:
        warnings.append("A date-like value was found, but its format could not be confirmed.")
    if not vendor:
        warnings.append("Supplier could not be matched confidently to the vendor directory.")
    if not rows:
        warnings.append("No confident invoice line items were extracted. Add or correct item rows manually.")
    if any(row["match_status"] == "unmatched" for row in rows):
        warnings.append("One or more descriptions could not be matched confidently to the item master.")
    if rows:
        warnings.append("Review every extracted item, quantity, rate, and amount before saving.")

    return {
        "fields": {
            "invoice_no": invoice_no,
            "po_no": getattr(po_match, "po_no", "") if po_match else po_raw,
            "grn_date": invoice_date,
            "vendor_code": getattr(vendor, "code", "") if vendor else "",
            "vendor_name": getattr(vendor, "name", "") if vendor else "",
            "store_location": getattr(po_match, "delivery_location", "") if po_match else "",
        },
        "line_items": rows,
        "warnings": list(dict.fromkeys(warnings)),
        "extracted_text_preview": text[:4000],
        "filename": (file.filename or "document")[:160],
        "document_type": "pdf" if content_type == "application/pdf" else "image",
        "extraction_method": method,
        "requires_review": True,
    }
