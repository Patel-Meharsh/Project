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
            config = f"--oem 3 --psm {mode}"
            candidate = pytesseract.image_to_string(variant, config=config).strip()
            if candidate:
                candidates.append(candidate)

            # Reconstruct rows from word bounding boxes as a second candidate.
            # This often preserves table columns better than image_to_string,
            # which can read quantity/rate/amount in separate or misleading lines.
            try:
                from pytesseract import Output
                data = pytesseract.image_to_data(
                    variant, config=config, output_type=Output.DICT
                )
                words = []
                for index, raw_word in enumerate(data.get("text", [])):
                    word = (raw_word or "").strip()
                    try:
                        confidence = float(data["conf"][index])
                    except (ValueError, TypeError, KeyError):
                        confidence = -1
                    if word and confidence >= 15:
                        words.append({
                            "text": word,
                            "x": int(data["left"][index]),
                            "y": int(data["top"][index]) + int(data["height"][index]) // 2,
                        })
                # Cluster words by vertical centre, then order each row left-to-right.
                words.sort(key=lambda word: (word["y"], word["x"]))
                rows = []
                for word in words:
                    best_row = None
                    best_distance = None
                    for row in rows[-4:]:
                        centre = sum(item["y"] for item in row) / len(row)
                        distance = abs(word["y"] - centre)
                        if distance <= max(10, int(variant.height * 0.006)) and (
                            best_distance is None or distance < best_distance
                        ):
                            best_row, best_distance = row, distance
                    if best_row is None:
                        rows.append([word])
                    else:
                        best_row.append(word)
                reconstructed = "\n".join(
                    " ".join(item["text"] for item in sorted(row, key=lambda item: item["x"]))
                    for row in rows
                ).strip()
                if reconstructed:
                    candidates.append(reconstructed)
            except Exception:
                # Plain OCR remains available if TSV/bounding-box reconstruction fails.
                pass

    if not candidates:
        return ""
    return max(candidates, key=_ocr_quality_score)


def _extract_item_rows(text: str, db: Session) -> list[dict[str, Any]]:
    """Extract invoice rows even when OCR breaks a table into uneven text lines."""
    from difflib import SequenceMatcher

    raw_lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]
    masters = db.query(models.ItemModel).all()
    unit_re = r"(?:BTL|BOTTLES?|PKT|PACKETS?|NOS?\.?|PCS?\.?|MTR|MET(?:RE|ER)|KGS?|GMS?|LTRS?|LIT(?:RE|ER)S?|ROLLS?|BOX(?:ES)?|SETS?|PAIRS?)"
    number_re = r"\d[\d,]*(?:\.\d{1,2})?"

    # OCR frequently places a product description on one line and its HSN,
    # quantity, rate, and amount on the next. Rejoin likely continuation lines
    # before parsing, while leaving headings and totals untouched.
    lines: list[str] = []
    for raw_line in raw_lines:
        has_qty_unit = re.search(rf"(?<![A-Za-z]){number_re}\s*{unit_re}\b", raw_line, re.I)
        if lines and has_qty_unit and not re.search(rf"{number_re}\s*{unit_re}\b", lines[-1], re.I):
            previous = lines[-1]
            if (re.search(r"[A-Za-z]", previous)
                    and not re.search(r"\b(?:invoice|gstin|cgst|sgst|igst|total|round off|description|quantity|amount)\b", previous, re.I)
                    and not re.search(r"\b(?:dated|vendor|supplier|party|tax invoice)\b", previous, re.I)):
                lines[-1] = previous + " " + raw_line
                continue
        lines.append(raw_line)
    found: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
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
        qty = rate = amount = None
        unit = ""

        if qty_matches:
            # Prefer a quantity-unit pair near the right side of the description.
            # Product pack sizes such as "2 LTR" can appear before the actual quantity.
            qm = next((m for m in reversed(qty_matches)
                       if len(_norm(body[:m.start()])) >= 3 and re.search(r"[A-Za-z]", body[:m.start()])), None)
            if not qm:
                continue
            prefix = body[:qm.start()].strip(" .:-")
            prefix = re.sub(r"\s+\d{4,8}\s*$", "", prefix).strip()
            prefix = re.sub(r"\s+\d{1,2}\s*%?\s*$", "", prefix).strip()
            description = prefix
            qty = _number(qm.group(1))
            unit = qm.group(2).upper().rstrip(".")
            trailing_numbers = re.findall(number_re, body[qm.end():])
            rate = _number(trailing_numbers[0]) if trailing_numbers else None
            amount = _number(trailing_numbers[-1]) if len(trailing_numbers) >= 2 else None
        else:
            # Many invoices omit UOM from the printed row. The previous parser
            # discarded those rows entirely. Try description + quantity + rate +
            # amount, while excluding a likely HSN/SAC code before the quantity.
            numeric_tokens = list(re.finditer(number_re, body))
            if len(numeric_tokens) < 3:
                continue
            first_number = numeric_tokens[0]
            description = body[:first_number.start()].strip(" .:-")
            row_numbers = [m.group(0) for m in numeric_tokens]
            first_value = row_numbers[0].replace(",", "")
            # HSN/SAC codes commonly contain 4-8 digits and precede quantity.
            if len(first_value.split(".")[0]) in range(4, 9) and len(row_numbers) >= 4:
                row_numbers = row_numbers[1:]
            if not re.search(r"[A-Za-z]", description) or len(_norm(description)) < 3:
                continue
            # Ignore explicitly printed percentage values such as GST columns.
            if re.search(r"\d\s*%", body):
                row_numbers = [
                    value for value in row_numbers
                    if not re.search(re.escape(value) + r"\s*%", body)
                ]
            if len(row_numbers) < 3:
                continue
            qty = _number(row_numbers[0])
            rate = _number(row_numbers[1])
            amount = _number(row_numbers[-1])
            if qty is None or rate is None or amount is None or qty <= 0 or rate < 0 or amount < 0:
                continue
            # Validate the inferred amount against quantity × rate. If the
            # arithmetic is inconsistent, leave amount blank for manual review.
            expected_amount = qty * rate
            if expected_amount > 0 and abs(expected_amount - amount) > max(2.0, expected_amount * 0.08):
                amount = None

        description = re.sub(r"\s+", " ", description).strip(" .:-")
        if len(_norm(description)) < 3 or not re.search(r"[A-Za-z]", description):
            continue
        if re.search(r"\b(?:cgst|sgst|igst|total|round off|tax|gstin|invoice|dated)\b", description, re.I):
            continue

        matched = match_master(description)
        code = (matched.code or "") if matched else ""
        # Do not deduplicate invoice rows by item code: a supplier may list the
        # same catalog item on multiple lines with different quantities, variants,
        # delivery batches, or rates. Preserve every detected row for GRN review.
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

            # First pass: embedded text (fast, accurate for digital PDFs).
            page_texts = [(page.extract_text() or "").strip() for page in reader.pages]
            if not page_texts:
                raise HTTPException(400, "The PDF contains no readable pages.")

            # Second pass: extract table rows from PDFs where text extraction has
            # lost column boundaries. pdfplumber is used for tables only to avoid
            # duplicating all body text from pypdf.
            table_text_by_page: list[str] = ["" for _ in page_texts]
            try:
                import pdfplumber
                with pdfplumber.open(io.BytesIO(raw)) as pdf:
                    for index, page in enumerate(pdf.pages[:len(page_texts)]):
                        rows = []
                        for table in (page.extract_tables() or []):
                            for row in table:
                                cells = [re.sub(r"\s+", " ", (cell or "")).strip() for cell in row]
                                if any(cells):
                                    rows.append(" | ".join(cells))
                        if rows:
                            table_text_by_page[index] = "\n".join(rows)
            except ImportError:
                # Table extraction is an enhancement; embedded text and OCR still work.
                pass
            except Exception:
                # A malformed table layout should not prevent the PDF from being read.
                pass

            # OCR pages with sparse text or a table that still cannot be parsed
            # into plausible item rows. Render via PyMuPDF (no Poppler dependency).
            pages_needing_ocr = []
            for index, page_text in enumerate(page_texts):
                combined_page = "\n".join(part for part in (page_text, table_text_by_page[index]) if part)
                if (
                    len(re.sub(r"\s+", "", page_text)) < 40
                    or not _extract_item_rows(combined_page, db)
                ):
                    pages_needing_ocr.append(index)

            if pages_needing_ocr:
                try:
                    import pymupdf
                    from PIL import Image
                    with pymupdf.open(stream=raw, filetype="pdf") as pdf_document:
                        for index in pages_needing_ocr:
                            page = pdf_document.load_page(index)
                            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
                            if pixmap.width * pixmap.height > 25_000_000:
                                raise HTTPException(413, "A rendered PDF page is too large to process.")
                            image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")
                            ocr_text = _run_ocr_candidates(image, modes=(6, 4, 11))
                            if ocr_text:
                                page_texts[index] = "\n".join(
                                    part for part in (page_texts[index], ocr_text) if part
                                )
                except HTTPException:
                    raise
                except ImportError:
                    raise HTTPException(
                        503,
                        "Scanned-PDF OCR is not configured. Install PyMuPDF, Pillow, pytesseract, and the Tesseract OCR engine on the server.",
                    )
                except Exception as exc:
                    raise HTTPException(
                        400,
                        "The scanned PDF could not be processed. Check that Tesseract OCR is installed and upload a clear PDF scan.",
                    ) from exc

            # Keep digital text, extracted table rows, and OCR candidates together.
            # The parser then sees both ordinary invoice text and row-shaped table data.
            text = "\n".join(
                "\n".join(part for part in (page_texts[index], table_text_by_page[index]) if part)
                for index in range(len(page_texts))
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(400, "The PDF could not be read. Please upload a valid PDF.") from exc
    else:
        try:
            from PIL import Image
            image = Image.open(io.BytesIO(raw))
            # Handles phone rotation, contrast, upscaling, and several layout modes.
            text = _run_ocr_candidates(image, modes=(6, 4, 11))
        except HTTPException:
            raise
        except ImportError:
            raise HTTPException(
                503,
                "Image OCR is not configured. Install Pillow, pytesseract, and the Tesseract OCR engine on the server.",
            )
        except Exception as exc:
            raise HTTPException(400, "The image could not be processed. Try a clear PNG or JPG scan.") from exc

    result = _extract_fields(text, db)
    result["filename"] = (file.filename or "document")[:160]
    result["document_type"] = "pdf" if content_type == "application/pdf" else "image"
    return result
