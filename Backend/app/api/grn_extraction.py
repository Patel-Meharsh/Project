"""Conservative document extraction for GRN drafts.

This module only extracts candidate text/fields. It never creates a GRN or changes inventory.
Scanned-image OCR requires the Tesseract binary to be installed on the server.
"""
from __future__ import annotations

import io
import os
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


def _clean_item_description(value: str, expected_serial: int | None = None) -> str:
    """Remove explicit or sequence-confirmed row serials without damaging product numbers."""
    description = re.sub(r"\s+", " ", (value or "")).strip(" .:| -\t")
    # Remove only a clearly marked serial (1., 01), 2 -). Do not strip a bare
    # leading number followed by whitespace: "15 W LED fitting" is a product.
    previous = None
    while description != previous:
        previous = description
        description = re.sub(
            r"^\s*(?:(?:sr|s)\.?\s*(?:no|number)\.?\s*)?\d{1,3}\s*[.)-]\s*(?=[A-Za-z])",
            "",
            description,
            count=1,
            flags=re.I,
        ).strip()
    # Some invoices print a bare serial (e.g. "1 Lizol") without punctuation
    # and omit the serial-column header. Strip it only when it matches the row's
    # expected sequence, and not when the remainder starts with a product unit
    # ("15 W LED", "2 Ltr White Phenyl", "3 Pin Plug").
    if expected_serial is not None:
        match = re.match(r"^\s*(\d{1,3})\s+(?=[A-Za-z])", description)
        if match and int(match.group(1)) == expected_serial:
            remainder = description[match.end():]
            if not re.match(
                r"^(?:W|WATT|L|LTR|LITRE|LITER|ML|MM|CM|MTR|KG|GM|GMS|PCS|PC|NOS|INCH|FT|PIN)\b",
                remainder,
                re.I,
            ):
                description = remainder.strip()
    return description.strip(" .:| -\t")


def _pdf_pages_needing_image_fallback(
    page_count: int,
    coordinate_rows: list[dict[str, Any]],
    max_pages: int = 30,
    expected_row_counts: dict[int, int] | None = None,
) -> list[int]:
    """Return pages where coordinate extraction is absent, uncertain, or likely incomplete."""
    rows_by_page: dict[int, list[dict[str, Any]]] = {}
    for row in coordinate_rows:
        page_index = row.get("_source_page_index")
        if page_index is not None:
            rows_by_page.setdefault(page_index, []).append(row)
    pages = []
    expected_row_counts = expected_row_counts or {}
    for index in range(min(page_count, max_pages)):
        page_rows = rows_by_page.get(index, [])
        # A partial coordinate parse can produce some rows and still miss others.
        # If any row is incomplete/inconsistent, run the OCR alternative for that page.
        # A separate text parser can also reveal likely omissions even when all
        # coordinate rows look complete (e.g. one missed row in a long invoice).
        text_row_count = expected_row_counts.get(index, 0)
        likely_missing_rows = text_row_count > len(page_rows)
        if (
            not page_rows
            or any(row.get("needs_review") for row in page_rows)
            or likely_missing_rows
        ):
            pages.append(index)
    return pages


def _choose_pdf_page_rows(
    existing: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Choose the OCR alternative only when it improves row quality."""
    if candidates and (not existing or _line_item_quality(candidates) > _line_item_quality(existing)):
        return candidates
    return existing


def _line_item_quality(rows: list[dict[str, Any]]) -> float:
    """Score candidate rows for completeness and arithmetic consistency."""
    score = float(len(rows) * 10)
    for row in rows:
        qty, rate, amount = row.get("recd_qty"), row.get("rate"), row.get("line_amount")
        if qty is None:
            score -= 3
        if rate is None:
            score -= 3
        if amount is not None and qty is not None and rate is not None:
            if abs(qty * rate - amount) <= max(2.0, abs(amount) * 0.03):
                score += 4
            else:
                score -= 5
        if len(_norm(row.get("item_name", ""))) < 4:
            score -= 4
    return score


def _append_pdf_description_continuation(
    rows: list[dict[str, Any]],
    description: str,
    page_index: int,
) -> bool:
    """Append a description-only PDF line to the previous item on the same page."""
    continuation = re.sub(r"\s+", " ", (description or "")).strip(" .:|-\t")
    if not continuation or len(_norm(continuation)) < 3 or len(continuation) > 80:
        return False
    if re.search(
        r"\b(?:invoice|description|quantity|qty|rate|amount|subtotal|total|grand|"
        r"cgst|sgst|igst|taxable|hsn|gstin|round off|continued to page|terms|bank details)\b",
        continuation,
        re.I,
    ):
        return False
    if not rows or rows[-1].get("_source_page_index") != page_index:
        return False
    previous = rows[-1]
    previous_name = str(previous.get("item_name") or "").strip()
    normalized_previous = _norm(previous_name)
    normalized_continuation = _norm(continuation)
    if not previous_name or normalized_continuation in normalized_previous:
        return False
    previous["item_name"] = f"{previous_name} {continuation}".strip()
    return True


def _invoice_number_from_nearby_label(text: str) -> str | None:
    """Recover invoice IDs when the label and value are separated in extracted/OCR text."""
    lines = [re.sub(r"\s+", " ", line).strip(" :#|\t") for line in (text or "").splitlines()]
    label = re.compile(
        r"\b(?:tax\s*)?(?:invoice|invo[i1]ce|inv\.?|bill)\s*"
        r"(?:no\.?|number|num\.?|#|n[o0])(?=\s|[:#|=.-]|$)",
        re.I,
    )
    token_re = re.compile(r"(?<![A-Za-z0-9])([A-Z0-9][A-Z0-9/_.-]{1,39})(?![A-Za-z0-9])", re.I)
    date_re = re.compile(
        r"^(?:\d{1,4}[./-]){1,2}\d{1,4}$|^\d{1,2}[-/ ](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[-/ ,]+\d{2,4}$",
        re.I,
    )
    for index, line in enumerate(lines[:35]):
        match = label.search(line)
        if not match:
            continue
        # The value may be on the same line, or one/two visual text lines later.
        for candidate_index in range(index, min(len(lines), index + 4)):
            candidate_line = lines[candidate_index]
            search_from = match.end() if candidate_index == index else 0
            for token_match in token_re.finditer(candidate_line[search_from:]):
                candidate = token_match.group(1).strip(" .:/#-|")
                normalized = re.sub(r"[^A-Z0-9]", "", candidate.upper())
                if len(normalized) < 2 or not re.search(r"\d", normalized):
                    continue
                if date_re.fullmatch(candidate):
                    continue
                if re.fullmatch(r"\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z]Z[0-9A-Z]", normalized, re.I):
                    continue
                if re.search(
                    r"original|recipient|duplicate|triplicate|dated|gstin|supplier|vendor|"
                    r"delivery|consignee|reference|purchase|order|payment|amount|taxinvoice",
                    candidate,
                    re.I,
                ):
                    continue
                return re.sub(r"\s+", "", candidate)
    return None


def _mark_row_for_review(row: dict[str, Any]) -> dict[str, Any]:
    """Keep extracted invoice evidence and mark incomplete/inconsistent rows for review."""
    warnings = [
        part.strip()
        for part in str(row.get("extraction_warning") or "").split(";")
        if part.strip()
    ]
    qty = row.get("recd_qty")
    rate = row.get("rate")
    amount = row.get("line_amount")

    # A common column-alignment failure is an HSN/SAC code (for example 9405)
    # being read as quantity. Keep ordinary large quantities when their arithmetic
    # supports them; when a 4-8 digit integer makes the printed line amount wildly
    # implausible, withhold it from the draft and force OCR/manual review instead
    # of pre-filling an obviously unsafe accepted quantity.
    if (
        qty is not None
        and float(qty).is_integer()
        and 1000 <= qty < 100_000_000
        and rate is not None
        and amount is not None
        and abs(qty * rate - amount) > max(10.0, abs(amount) * 0.20)
        and qty * max(abs(rate), 1.0) > max(abs(amount), 1.0) * 20
    ):
        warnings.append(
            f"quantity candidate {qty:g} may be an HSN/SAC code; quantity was withheld for review"
        )
        row["recd_qty"] = None
        qty = None

    if qty is None and "quantity was not confidently read" not in warnings:
        warnings.append("quantity was not confidently read")
    if rate is None and "rate was not confidently read" not in warnings:
        warnings.append("rate was not confidently read")
    if qty is not None and rate is not None and amount is not None:
        expected = qty * rate
        if abs(expected - amount) > max(0.05, abs(amount) * 0.015):
            arithmetic_warning = "quantity × rate differs from the printed line amount"
            if arithmetic_warning not in warnings:
                warnings.append(arithmetic_warning)

    if warnings:
        row["needs_review"] = True
        row["extraction_warning"] = "; ".join(warnings)
    else:
        row["needs_review"] = False
        row["extraction_warning"] = ""
    return row


def _ocr_quality_score(text: str) -> float:
    """Prefer readable OCR that preserves invoice line rows, not just header text."""
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
    # A good invoice OCR candidate should retain one product row per line, with
    # a description, quantity/UOM and numeric rate/amount. This deliberately
    # outweighs a candidate that reads the header beautifully but loses the table.
    unit = r"(?:BTL|PKT|NOS?\.?|PCS?\.?|KGS?|GMS?|LTRS?|ROLLS?|BOX(?:ES)?|SETS?|PAIRS?)"
    noise = len(re.findall(r"[^A-Za-z0-9\s.,:/()%'₹&+-]", text))
    score = (len(words) * 2.0) + (len(numbers) * 1.2) + (len(invoice_terms) * 2.5)
    score += readable_ratio * 8.0
    score -= noise * 1.5
    # Balance table-heavy OCR against header-heavy OCR so the selected text
    # retains supplier/date/GSTIN details as well as item rows.
    header_terms = re.findall(
        r"\b(?:dated|invoice\s*date|bill\s*date|supplier|vendor|gstin|gst\s*in|"
        r"invoice\s*(?:no|number)|purchase\s*order|p\.?\s*o\.?)\b",
        text, re.IGNORECASE,
    )
    score += len(header_terms) * 5.0
    if re.search(r"\b\d{1,2}[-/ ](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[-/ ,]+\d{2,4}\b", text, re.I):
        score += 8.0
    if re.search(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z]Z[0-9A-Z]\b", text, re.I):
        score += 10.0
    row_like = 0
    lines = text.splitlines()
    for index, line in enumerate(lines):
        # Tesseract often confuses 5 with S in quantity/UOM tokens ("SBTL").
        normalized_line = re.sub(r"(?<![A-Za-z0-9])S(?=\s*BTL\b)", "5", line, flags=re.I)
        if re.search(r"[A-Za-z]{2,}", normalized_line) and re.search(rf"\d[\d,.]*\s*{unit}\b", normalized_line, re.I):
            values = [_number(value) for value in re.findall(r"\d[\d,.]*", normalized_line)]
            if len(values) >= 3:
                row_like += 1
                # Reward rows whose quantity x rate agrees with line amount.
                # This helps choose between OCR variants, e.g. 1 PKT vs 4 PKT.
                pairs = list(re.finditer(rf"(?<![A-Za-z])(\d[\d,.]*)\s*{unit}\b", normalized_line, re.I))
                arithmetic_matches = 0
                for pair in pairs:
                    qty_value = _number(pair.group(1))
                    after_values = [_number(value) for value in re.findall(r"\d[\d,.]*", normalized_line[pair.end():])]
                    if qty_value is not None and len(after_values) >= 2:
                        rate_value, amount_value = after_values[0], after_values[-1]
                        if rate_value is not None and amount_value is not None:
                            delta = abs(qty_value * rate_value - amount_value)
                            if delta <= max(2.0, amount_value * 0.03):
                                arithmetic_matches += 1
                score += 12 if arithmetic_matches else -10
    score += row_like * 35.0
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
    variants = [gray, sharp, threshold]

    # OpenCV adaptive thresholding helps with uneven lighting and shaded paper.
    try:
        import cv2
        import numpy as np

        adaptive = cv2.adaptiveThreshold(
            np.asarray(gray), 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 31, 11,
        )
        variants.append(Image.fromarray(adaptive))
    except ImportError:
        pass
    return variants


_paddle_ocr_engine = None


def _paddleocr_candidate(image) -> str:
    """Use PaddleOCR as an optional local OCR candidate; no cloud services."""
    global _paddle_ocr_engine
    try:
        import numpy as np
        from paddleocr import PaddleOCR

        if _paddle_ocr_engine is None:
            _paddle_ocr_engine = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
        result = _paddle_ocr_engine.ocr(np.asarray(image.convert("RGB")), cls=True) or []
        words = []
        for page_result in result:
            for entry in page_result or []:
                try:
                    box, recognition = entry
                    label, confidence = recognition
                    if label and float(confidence) >= 0.25:
                        xs = [point[0] for point in box]
                        ys = [point[1] for point in box]
                        words.append({"text": str(label).strip(), "x": sum(xs) / len(xs), "y": sum(ys) / len(ys)})
                except (TypeError, ValueError, IndexError):
                    continue
        words.sort(key=lambda word: (word["y"], word["x"]))
        rows = []
        tolerance = max(10, int(image.height * 0.012))
        for word in words:
            target = None
            for row in reversed(rows[-4:]):
                centre = sum(item["y"] for item in row) / len(row)
                if abs(word["y"] - centre) <= tolerance:
                    target = row
                    break
            if target is None:
                rows.append([word])
            else:
                target.append(word)
        return "\n".join(
            " ".join(item["text"] for item in sorted(row, key=lambda item: item["x"]))
            for row in rows
        ).strip()
    except ImportError:
        # PaddleOCR is optional because its model runtime is large.
        return ""
    except Exception:
        # A PaddleOCR/model-version issue must not break the Tesseract path.
        return ""


def _run_ocr_candidates(image, modes: tuple[int, ...] = (6, 4, 11)) -> str:
    """Compare Tesseract and optional PaddleOCR candidates after local preprocessing."""
    import pytesseract

    variants = _prepare_ocr_variants(image)
    plain_candidates: list[dict[str, Any]] = []
    for variant_index, variant in enumerate(variants):
        for mode in modes:
            config = f"--oem 3 --psm {mode}"
            candidate = pytesseract.image_to_string(variant, config=config).strip()
            if candidate:
                # Correct high-confidence, common OCR confusion in quantities.
                candidate = re.sub(r"(?<![A-Za-z0-9])S(?=\s*BTL\b)", "5", candidate, flags=re.I)
                plain_candidates.append({
                    "text": candidate,
                    "variant": variant,
                    "variant_index": variant_index,
                    "mode": mode,
                    "score": _ocr_quality_score(candidate),
                })

    # Keep every inexpensive plain-text candidate, but run the more expensive TSV
    # word-box pass only for the best candidate from each page-segmentation mode.
    # Two strong box reconstructions usually preserve table alignment without
    # tripling OCR work across every threshold/contrast variant.
    candidates = [record["text"] for record in plain_candidates]
    best_by_mode: dict[int, dict[str, Any]] = {}
    for record in plain_candidates:
        mode = record["mode"]
        if mode not in best_by_mode or record["score"] > best_by_mode[mode]["score"]:
            best_by_mode[mode] = record
    selected_box_candidates = sorted(
        best_by_mode.values(), key=lambda record: record["score"], reverse=True
    )[:2]

    for record in selected_box_candidates:
        try:
            from pytesseract import Output
            data = pytesseract.image_to_data(
                record["variant"],
                config=f"--oem 3 --psm {record['mode']}",
                output_type=Output.DICT,
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
                    if distance <= max(10, int(record["variant"].height * 0.006)) and (
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

    paddle_text = _paddleocr_candidate(image)
    if paddle_text:
        candidates.append(paddle_text)

    if not candidates:
        return ""
    best_text = max(candidates, key=_ocr_quality_score)
    # Apply the same quantity correction to both plain OCR and reconstructed TSV text.
    return re.sub(r"(?<![A-Za-z0-9])S(?=\s*BTL\b)", "5", best_text, flags=re.I)


def _extract_item_rows(text: str, db: Session) -> list[dict[str, Any]]:
    """Extract invoice rows even when OCR breaks a table into uneven text lines."""
    from difflib import SequenceMatcher

    raw_lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]
    masters = db.query(models.ItemModel).all()
    unit_re = r"(?:BOTTLES?|BTL|PACKETS?|PKT|PIECES?|PCS?\.?|NOS?\.?|MILLIMETERS?|MILLIMETRES?|MM|CENTIMETERS?|CENTIMETRES?|CM|METERS?|METRES?|MTRS?|MTR|KILOGRAMS?|KGS?|KG|GRAMS?|GMS?|MILLILITERS?|MILLILITRES?|ML|LIT(?:RE|ER)S?|LTRS?|LTR|ROLLS?|BOX(?:ES)?|SETS?|PAIRS?|WATTS?|VOLTS?|W|V|M|G)"
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
        body = re.sub(r"^\s*[\W_]*\d{1,3}\s*[.)-]\s*", "", line)
        qty_matches = list(re.finditer(rf"(?<![A-Za-z])({number_re})\s*({unit_re})\b", body, re.I))
        qty = rate = amount = None
        unit = ""

        if qty_matches:
            # Do not choose the rightmost number+unit pair blindly. Invoice rows
            # commonly contain both the billed quantity ("2 BTL") and the rate's
            # unit ("330.00 BTL"). The latter was being mistaken for quantity.
            # Prefer a pair followed by rate + rate-UOM + line amount, and prefer
            # pairs preceded by HSN/GST columns over product pack sizes ("2 Ltr").
            ranked_pairs = []
            for candidate in qty_matches:
                prefix_candidate = body[:candidate.start()]
                suffix_candidate = body[candidate.end():]
                suffix_numbers = re.findall(number_re, suffix_candidate)
                has_hsn_or_gst = bool(
                    re.search(r"\b\d{4,8}\b", prefix_candidate)
                    or re.search(r"\d\s*%", prefix_candidate)
                )
                # Start with structural evidence, then strongly prefer a quantity
                # whose following rate and line amount satisfy qty × rate ≈ amount.
                # This prevents pack sizes and numbers embedded in descriptions
                # from winning just because they have more numbers after them.
                score = min(len(suffix_numbers), 3) * 10 + (8 if has_hsn_or_gst else 0)
                parsed_suffix = [_number(value) for value in suffix_numbers]
                qty_value = _number(candidate.group(1))
                if qty_value is not None and len(parsed_suffix) >= 2:
                    rate_value = parsed_suffix[0]
                    amount_value = parsed_suffix[-1]
                    if rate_value is not None and amount_value is not None:
                        expected = qty_value * rate_value
                        if abs(expected - amount_value) <= max(2.0, abs(amount_value) * 0.03):
                            score += 45
                        else:
                            score -= 8
                # A long HSN/SAC number immediately after a pair means that pair
                # was probably a pack size inside the description, not billed qty.
                if suffix_numbers and len(suffix_numbers[0].replace(",", "").split(".")[0]) in range(4, 9):
                    score -= 20
                # Quantity candidates embedded in a product description are less
                # likely than candidates whose prefix already contains a product name.
                if len(_norm(prefix_candidate)) >= 3 and re.search(r"[A-Za-z]", prefix_candidate):
                    ranked_pairs.append((score, candidate))
            if not ranked_pairs:
                continue
            # Sort by confidence score; Python's stable sort preserves left-to-right
            # order when candidates have equally strong evidence.
            ranked_pairs.sort(key=lambda pair: pair[0], reverse=True)
            qm = ranked_pairs[0][1]
            prefix = body[:qm.start()].strip(" .:-")
            # HSN/SAC and GST are separate invoice columns that OCR often
            # appends to the description. Remove these tokens anywhere in the
            # prefix, not only at the very end (the old order missed HSN when
            # the GST percentage appeared after it).
            prefix = re.sub(r"(?<!\d)\d{4,8}(?!\d)", " ", prefix)
            prefix = re.sub(r"(?<!\d)\d{1,2}\s*%", " ", prefix)
            prefix = re.sub(r"\b(?:HSN/?SAC|SAC|HSN)\b", " ", prefix, flags=re.I)
            prefix = re.sub(r"\s+", " ", prefix).strip(" .:-|")
            description = prefix
            qty = _number(qm.group(1))
            unit = qm.group(2).upper().rstrip(".")
            trailing_numbers = re.findall(number_re, body[qm.end():])
            rate = _number(trailing_numbers[0]) if trailing_numbers else None
            amount = _number(trailing_numbers[-1]) if len(trailing_numbers) >= 2 else None
            # Preserve the values read from the invoice even if the arithmetic
            # disagrees. The row-level review marker below warns the user rather
            # than silently erasing OCR evidence that may be correct for tax/discount
            # or rounding reasons. Never auto-correct the rate from arithmetic alone.
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
            # Keep the source amount even when quantity × rate disagrees. The
            # review marker below records the inconsistency without destroying data.

        description = _clean_item_description(description)
        if len(_norm(description)) < 3 or not re.search(r"[A-Za-z]", description):
            continue
        if re.search(r"\b(?:cgst|sgst|igst|total|round off|tax|gstin|invoice|dated)\b", description, re.I):
            continue

        matched = match_master(description)
        code = (matched.code or "") if matched else ""
        # Do not deduplicate invoice rows by item code: a supplier may list the
        # same catalog item on multiple lines with different quantities, variants,
        # delivery batches, or rates. Preserve every detected row for GRN review.
        found.append(_mark_row_for_review({
            "item_code": code,
            "item_name": ((matched.name or description) if matched else description),
            "vendor_code": "",
            "vendor_name": "",
            "recd_qty": qty,
            "accepted_qty": None,
            # Never substitute the catalog's default rate for a missing invoice
            # rate; the catalog price may differ from the supplier's billed rate.
            "rate": rate,
            "unit": unit,
            "line_amount": amount,
            "match_status": "matched" if matched else "unmatched",
            "source": "receipt_text",
        }))
        if code:
            seen_codes.add(code)

    # Do not append item-master records merely because their names appear anywhere
    # on the page. Header/footer text (for example a software licence in the
    # company footer) is not an invoice line item. Only rows with parsed
    # quantity/rate evidence are returned by this parser.
    return found


def _extract_pdf_table_line_items(raw: bytes, db: Session) -> list[dict[str, Any]]:
    """Extract digital-PDF invoice rows using dynamically detected table headers.

    Column positions are inferred from each document's own header words. No
    supplier-specific x coordinates or fixed invoice layout are assumed.
    """
    try:
        import pymupdf
    except ImportError:
        return []

    from difflib import SequenceMatcher

    try:
        document = pymupdf.open(stream=raw, filetype="pdf")
    except Exception:
        return []

    masters = db.query(models.ItemModel).all()
    extracted: list[dict[str, Any]] = []
    number_re = re.compile(r"(?<![A-Za-z])[-+]?\d[\d,]*(?:\.\d{1,4})?")
    unit_re = re.compile(
        r"\b(BTL|BOTTLES?|PKT|PACKETS?|NOS?\.?|PCS?\.?|MILLIMETERS?|MILLIMETRES?|MM|CENTIMETERS?|CENTIMETRES?|CM|METERS?|METRES?|MTRS?|MTR|"
        r"KILOGRAMS?|KGS?|KG|GRAMS?|GMS?|MILLILITERS?|MILLILITRES?|ML|LIT(?:RE|ER)S?|LTRS?|LTR|L|ROLLS?|BOX(?:ES)?|SETS?|PAIRS?|"
        r"DOZ(?:EN)?|BAGS?|REAMS?|TUBES?|CANS?|JARS?|UNITS?|SQ\.?\s*FT|"
        r"SQ\.?\s*M|FT|FEET|INCH(?:ES)?|IN|MM|CM|LBS?|TONS?)\b",
        re.I,
    )

    def match_master(description: str):
        normalized = _norm(description)
        if len(normalized) < 3:
            return None
        candidates = []
        desc_tokens = set(re.findall(r"[a-z0-9]+", description.lower()))
        for item in masters:
            name, code = (item.name or "").strip(), (item.code or "").strip()
            normalized_name = _norm(name)
            if not name or not code:
                continue
            name_tokens = set(re.findall(r"[a-z0-9]+", name.lower()))
            overlap = len(desc_tokens & name_tokens) / max(1, len(desc_tokens | name_tokens))
            score = max(
                SequenceMatcher(None, normalized, normalized_name).ratio(),
                overlap,
                1.0 if normalized_name in normalized or normalized in normalized_name else 0.0,
            )
            if score >= 0.72:
                candidates.append((score, item))
        candidates.sort(key=lambda pair: pair[0], reverse=True)
        if candidates and (
            len(candidates) == 1 or candidates[0][0] - candidates[1][0] >= 0.16
        ):
            return candidates[0][1]
        return None

    def token_kind(value: str) -> str | None:
        token = re.sub(r"[^a-z]", "", value.lower())
        # Header aliases are normalized so punctuation, slashes and spacing do
        # not matter (e.g. "Description of Product / Service").
        # Explicit serial-number columns must stay separate from the item
        # description column; otherwise their values get prefixed to item names.
        if token in {
            "sr", "sl", "srno", "sno", "serialno", "serialnumber", "slno", "slnumber",
            "srnumber", "serial", "srlno",
        }:
            return "serial"
        if token in {
            "description", "particulars", "item", "items", "itemdescription",
            "descriptionofgoods", "descriptionofgoodsandservices",
            "descriptionofproductservice", "descriptionofproducts",
            "nameofitem", "itemname", "goodsname", "nameofgoods",
            "nameofproducts", "productname", "productservice", "materialdescription",
            "productdescription", "product", "products", "goods", "details",
        }:
            return "description"
        if token in {
            "qty", "quantity", "qnty", "qtys", "billedqty", "billqty",
            "quantitynos", "quantityno", "receivedqty", "orderedqty",
        }:
            return "qty"
        if token in {
            "rate", "price", "unitprice", "unitrate", "basicrate", "mrp",
            "rateperunit", "unitcost", "priceperunit",
        }:
            return "rate"
        # "Value of Supply" is a separate tax-inclusive column on many Indian
        # invoices. Treating its first word ("Value") as the line-amount header
        # averages two unrelated column positions and shifts HSN/GST numbers
        # into quantity/rate cells. Only explicit amount labels identify amount.
        if token in {"amount", "amt", "totalamount", "netamount", "lineamount"}:
            return "amount"
        if token in {"unit", "uom", "units"}:
            return "unit"
        # These columns must retain their own spatial zones so their values are
        # never assigned to the nearest quantity/rate/amount column.
        if token in {"hsn", "hsnsac", "sac"}:
            return "hsn"
        if token in {"gst", "gstpercent", "tax"}:
            return "gst"
        if token in {"discount", "disc", "d"}:
            return "discount"
        if token in {"value", "supply"}:
            return "value_supply"
        return None

    def close_row(words: list[dict[str, Any]], tolerance: float) -> list[list[dict[str, Any]]]:
        """Cluster words into visual rows using relative text height."""
        rows: list[list[dict[str, Any]]] = []
        for word in sorted(words, key=lambda item: (item["y"], item["x0"])):
            candidates = [
                (abs(sum(w["y"] for w in row) / len(row) - word["y"]), row)
                for row in rows[-5:]
            ]
            candidates = [pair for pair in candidates if pair[0] <= tolerance]
            if candidates:
                _, best = min(candidates, key=lambda pair: pair[0])
                best.append(word)
            else:
                rows.append([word])
        for row in rows:
            row.sort(key=lambda item: item["x0"])
        return rows

    try:
        for page_index, page in enumerate(document):
            raw_words = page.get_text("words")
            if not raw_words:
                continue
            words = [
                {
                    "text": str(w[4]).strip(),
                    "x0": float(w[0]),
                    "x1": float(w[2]),
                    "y": (float(w[1]) + float(w[3])) / 2,
                    "height": max(1.0, float(w[3]) - float(w[1])),
                }
                for w in raw_words if str(w[4]).strip()
            ]
            median_height = sorted(w["height"] for w in words)[len(words) // 2]
            y_tolerance = max(2.5, min(6.0, median_height * 0.65))
            visual_rows = close_row(words, y_tolerance)

            # Detect a header from a group of common label synonyms. Require a
            # description-like label and at least two numeric-column labels so
            # ordinary prose or a totals section is not mistaken for the table.
            header = None
            header_row_index = -1
            for row_index, row in enumerate(visual_rows):
                row_center = sum(word["y"] for word in row) / max(1, len(row))
                # Invoice headers are often stacked over 2-3 lines (e.g. Description
                # at y=248, Qty/Rate at y=251, and HSN/SAC at y=254). Aggregate only
                # this compact header band instead of requiring all labels on one line.
                header_band = []
                for nearby_index in range(max(0, row_index - 1), min(len(visual_rows), row_index + 5)):
                    nearby = visual_rows[nearby_index]
                    nearby_center = sum(word["y"] for word in nearby) / max(1, len(nearby))
                    header_band_tolerance = max(8.0, min(14.0, median_height * 0.9))
                    if abs(nearby_center - row_center) <= header_band_tolerance:
                        header_band.append(nearby)
                kinds: dict[str, list[dict[str, Any]]] = {}
                for header_words in header_band:
                    for word in header_words:
                        kind = token_kind(word["text"])
                        if kind:
                            kinds.setdefault(kind, []).append(word)
                numeric_kinds = set(kinds) & {"qty", "rate", "amount"}
                if "description" in kinds and len(numeric_kinds) >= 2:
                    # For multi-word headers, anchor description at the first
                    # recognized word instead of averaging "Description" and "Goods".
                    if len(kinds["description"]) > 1:
                        kinds["description"] = [min(kinds["description"], key=lambda w: w["x0"])]
                    # "GST Rate" is not the item unit-rate column.
                    if "gst" in kinds and "qty" in kinds and "rate" in kinds:
                        qty_x = sum((w["x0"] + w["x1"]) / 2 for w in kinds["qty"]) / len(kinds["qty"])
                        real_rates = [w for w in kinds["rate"] if (w["x0"] + w["x1"]) / 2 > qty_x]
                        if real_rates:
                            kinds["rate"] = real_rates
                    header = {kind: sum((w["x0"] + w["x1"]) / 2 for w in group) / len(group)
                              for kind, group in kinds.items()}
                    header_row_index = row_index
                    break
            if header is None:
                # Some invoices use a short "Item" heading and omit a separate
                # description heading. Accept it only when the row also contains
                # quantity, rate/price and amount/value labels.
                for row_index, row in enumerate(visual_rows):
                    labels = {}
                    for word in row:
                        kind = token_kind(word["text"])
                        if kind:
                            labels.setdefault(kind, []).append(word)
                    if "description" in labels and {"qty", "amount"}.issubset(labels) and "rate" in labels:
                        if len(labels["description"]) > 1:
                            labels["description"] = [min(labels["description"], key=lambda w: w["x0"])]
                        if "gst" in labels and "qty" in labels:
                            qty_x = sum((w["x0"] + w["x1"]) / 2 for w in labels["qty"]) / len(labels["qty"])
                            real_rates = [w for w in labels["rate"] if (w["x0"] + w["x1"]) / 2 > qty_x]
                            if real_rates:
                                labels["rate"] = real_rates
                        header = {kind: sum((w["x0"] + w["x1"]) / 2 for w in group) / len(group)
                                  for kind, group in labels.items()}
                        header_row_index = row_index
                        break
            if header is None:
                continue

            desc_x = header.get("description")
            if desc_x is None:
                continue
            # Use header centers to infer column boundaries for this invoice.
            # If a label is absent, its value stays blank rather than borrowing a
            # number from a neighboring column.
            column_centers = sorted(
                (x, kind) for kind, x in header.items()
                if kind in {"description", "serial", "qty", "rate", "amount", "unit", "hsn", "gst", "discount", "value_supply"}
            )
            boundaries = [
                (column_centers[i][0] + column_centers[i + 1][0]) / 2
                for i in range(len(column_centers) - 1)
            ]

            def column_for(x: float) -> str | None:
                if not column_centers:
                    return None
                idx = 0
                while idx < len(boundaries) and x >= boundaries[idx]:
                    idx += 1
                return column_centers[idx][1]

            # Limit extraction to the goods table, stopping at totals/tax summary.
            body_words = []
            for row in visual_rows[header_row_index + 1:]:
                row_text = " ".join(w["text"] for w in row)
                if re.search(r"\b(?:grand\s+total|invoice\s+total|total\s+amount|amount\s+in\s+words|taxable\s+value|cgst|sgst|igst|round\s*off|terms\s+and\s+conditions|bank\s+details)\b", row_text, re.I):
                    break
                if re.search(r"\btotal\b", row_text, re.I) and not re.search(r"\b(?:sub\s*total|total\s+qty)\b", row_text, re.I):
                    break
                body_words.extend(row)

            if not body_words:
                continue
            # visual_rows already grouped words using the page's baseline tolerance.
            # Reuse that same narrow tolerance here; widening it by glyph-box height can
            # merge neighboring invoice items whose descriptions start slightly lower.
            body_rows = close_row(body_words, y_tolerance)

            for row_number, row in enumerate(body_rows, start=1):
                # Build each cell according to dynamically inferred column boundaries.
                cells: dict[str, list[dict[str, Any]]] = {}
                for word in row:
                    kind = column_for((word["x0"] + word["x1"]) / 2)
                    if kind:
                        cells.setdefault(kind, []).append(word)
                # Preserve reading order when a product name wraps onto a lower baseline.
                description_words = sorted(cells.get("description", []), key=lambda w: (w["y"], w["x0"]))
                # Wrapped description-only baselines do not represent new
                # goods rows. Use the next extracted item ordinal rather than
                # the visual-row index so a serial such as "2 Tissue Roll" is
                # removed even when the previous item's name wraps over a line.
                description = _clean_item_description(
                    " ".join(w["text"] for w in description_words),
                    len(extracted) + 1,
                )
                if not description or not re.search(r"[A-Za-z]{2,}", description):
                    continue
                if re.search(r"\b(?:description|particulars|quantity|qty|rate|amount|subtotal|grand total|cgst|sgst|igst|taxable|invoice|page)\b", description, re.I):
                    continue
                # Remove only a leading row serial; preserve meaningful leading
                # product values such as "15 W LED fitting".
                description = _clean_item_description(description)

                def cell_text(kind: str) -> str:
                    return " ".join(w["text"] for w in sorted(cells.get(kind, []), key=lambda w: w["x0"]))

                qty_text = cell_text("qty")
                rate_text = cell_text("rate")
                amount_text = cell_text("amount")
                unit_text = cell_text("unit")
                qty_match = number_re.search(qty_text)
                rate_match = number_re.search(rate_text)
                amount_matches = list(number_re.finditer(amount_text))
                qty = _number(qty_match.group(0)) if qty_match else None
                rate = _number(rate_match.group(0)) if rate_match else None
                amount = _number(amount_matches[-1].group(0)) if amount_matches else None
                unit_match = unit_re.search((qty_text + " " + unit_text).strip())
                # Prefer a recognized abbreviation, but preserve a short textual
                # value from an explicitly detected Unit/UOM column (e.g. RFT,
                # RMT, EA) even when it is not in the common abbreviation list.
                unit = unit_match.group(1).upper().rstrip(".") if unit_match else ""
                if not unit and unit_text:
                    candidate_unit = re.sub(r"[^A-Za-z./ -]", "", unit_text).strip(" .-/").upper()
                    if candidate_unit and len(candidate_unit) <= 12 and len(candidate_unit.split()) <= 2:
                        unit = candidate_unit

                # Some tables print the UOM next to quantity; others put it in
                # its own column. Never infer quantity/rate from description text.
                if qty is None and rate is None and amount is None:
                    # Product descriptions such as "M Fold Paper professional",
                    # "Tissue Roll Plain", or colour/pack-size notes often wrap to a
                    # second visual line with no numeric cells. Keep them attached
                    # to the preceding item instead of silently dropping them.
                    if _append_pdf_description_continuation(extracted, description, page_index):
                        previous = extracted[-1]
                        updated_match = match_master(previous["item_name"])
                        previous["item_code"] = (updated_match.code or "") if updated_match else ""
                        previous["match_status"] = "matched" if updated_match else "unmatched"
                    continue
                if qty is not None and rate is not None and amount is not None:
                    expected = qty * rate
                    # Tax-inclusive or rounded lines can differ slightly; only
                    # clear values on a substantial mismatch, don't rewrite them.
                    if abs(expected - amount) > max(3.0, abs(amount) * 0.08):
                        # Preserve the source values for human review, and mark
                        # uncertainty in the warning rather than silently blanking.
                        pass
                matched = match_master(description)
                extracted.append(_mark_row_for_review({
                    "item_code": (matched.code or "") if matched else "",
                    "item_name": ((matched.name or description) if matched else description),
                    "vendor_code": "",
                    "vendor_name": "",
                    "recd_qty": qty,
                    "accepted_qty": None,
                    "rate": rate,
                    "unit": unit,
                    "line_amount": amount,
                    "match_status": "matched" if matched else "unmatched",
                    "source": "receipt_text",
                    "_source_page_index": page_index,
                }))
    finally:
        document.close()

    # Keep every row in document order. Identical item/quantity/rate combinations
    # can legitimately appear more than once on an invoice; global value-based
    # deduplication silently removed those real lines.
    return extracted

def _extract_image_table_line_items(image, db: Session) -> list[dict[str, Any]]:
    """Read invoice line items from image OCR boxes, using the invoice's own columns.

    Only rows below a detected item/description + quantity + rate header are
    considered. Text elsewhere on the page cannot become a line item.
    """
    try:
        import pytesseract
        from pytesseract import Output
    except ImportError:
        return []

    from difflib import SequenceMatcher

    masters = db.query(models.ItemModel).all()
    number_re = re.compile(r"(?<![A-Za-z])\d[\d,]*(?:\.\d{1,4})?")
    unit_re = re.compile(
        r"\b(BTL|BOTTLES?|PKT|PACKETS?|NOS?\.?|PCS?\.?|MILLIMETERS?|MILLIMETRES?|MM|CENTIMETERS?|CENTIMETRES?|CM|METERS?|METRES?|MTRS?|MTR|"
        r"KILOGRAMS?|KGS?|KG|GRAMS?|GMS?|MILLILITERS?|MILLILITRES?|ML|LIT(?:RE|ER)S?|LTRS?|LTR|L|ROLLS?|BOX(?:ES)?|SETS?|PAIRS?|"
        r"DOZ(?:EN)?|BAGS?|REAMS?|TUBES?|CANS?|JARS?|UNITS?|MM|CM|FT|FEET|"
        r"INCH(?:ES)?|SQ\.?\s*FT|SQ\.?\s*M)\b", re.I
    )

    def normalize_label(value: str) -> str:
        return re.sub(r"[^a-z]", "", value.lower())

    def label_kind(value: str) -> str | None:
        value = normalize_label(value)
        if value in {
            "sr", "sl", "srno", "sno", "serialno", "serialnumber", "slno", "slnumber",
            "srnumber", "serial", "srlno",
        }:
            return "ignore_serial"
        if value in {
            "description", "particulars", "item", "items", "product", "products",
            "goods", "details", "itemdescription", "descriptionofgoods",
            "descriptionofgoodsandservices", "descriptionofproductservice",
            "descriptionofproducts", "nameofitem", "itemname", "goodsname",
            "nameofgoods", "nameofproducts", "productname", "productservice",
            "materialdescription", "productdescription",
        }:
            return "description"
        if value in {
            "qty", "quantity", "qnty", "qtys", "billedqty", "billqty",
            "quantitynos", "quantityno", "receivedqty", "orderedqty",
        }:
            return "qty"
        if value in {
            "rate", "price", "unitprice", "unitrate", "basicrate", "mrp",
            "rateperunit", "unitcost", "priceperunit",
        }:
            return "rate"
        # Keep every non-item column in the spatial model. If HSN/GST
        # headers are omitted here, their wide gap makes the description-to-qty
        # boundary span across those columns and codes such as 38089400 become qty.
        if value in {"amount", "amt", "lineamount", "totalamount", "netamount", "linetotal", "taxableamount", "extendedamount"}:
            return "amount"
        if value in {"unit", "uom", "units"}:
            return "unit"
        # Keep each non-item column as its own boundary. Collapsing HSN,
        # GST and Discount into one shared "ignore" center shifts that center
        # toward Quantity and can route HSN codes (e.g. 38089400) into Qty.
        if value in {"hsn", "sac", "hsnsac"}:
            return "ignore_hsn"
        if value in {"gst", "tax", "gstrate", "gstpercent", "gstpercentage"}:
            return "ignore_gst"
        if value in {"discount", "disc", "d"}:
            return "ignore_discount"
        if value in {"value", "supply"}:
            return "ignore_value_supply"
        if value in {"per"}:
            return "ignore_rate_unit"
        return None

    def match_master(description: str):
        normalized = _norm(description)
        tokens = set(re.findall(r"[a-z0-9]+", description.lower()))
        ranked = []
        for item in masters:
            name, code = (item.name or "").strip(), (item.code or "").strip()
            if not name or not code:
                continue
            norm_name = _norm(name)
            name_tokens = set(re.findall(r"[a-z0-9]+", name.lower()))
            overlap = len(tokens & name_tokens) / max(1, len(tokens | name_tokens))
            ratio = SequenceMatcher(None, normalized, norm_name).ratio()
            score = max(ratio, overlap, 1.0 if norm_name and norm_name in normalized else 0.0)
            if score >= 0.58:
                ranked.append((score, item))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        if ranked and (len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= 0.10):
            return ranked[0][1]
        return None

    best_rows: list[dict[str, Any]] = []
    best_score = float("-inf")
    all_candidate_rows: list[dict[str, Any]] = []
    # Evaluate multiple segmentation modes and image variants. Selecting the
    # candidate with the largest raw row count alone is unsafe: a noisy pass can
    # create extra rows by splitting descriptions from their numeric columns.
    for variant in _prepare_ocr_variants(image)[:3]:
        for psm in (4, 6, 11):
            try:
                data = pytesseract.image_to_data(
                    variant, config=f"--oem 3 --psm {psm}", output_type=Output.DICT
                )
            except Exception:
                continue
            words = []
            for i, raw_text in enumerate(data.get("text", [])):
                token = (raw_text or "").strip()
                try:
                    confidence = float(data["conf"][i])
                except (ValueError, TypeError, IndexError):
                    confidence = -1
                if not token or confidence < 20:
                    continue
                x, y = int(data["left"][i]), int(data["top"][i])
                width, height = int(data["width"][i]), int(data["height"][i])
                words.append({
                    "text": token, "x0": x, "x1": x + width,
                    "y": y + height / 2, "height": max(1, height),
                    "block": data.get("block_num", [0] * len(data["text"]))[i],
                    "par": data.get("par_num", [0] * len(data["text"]))[i],
                    "line": data.get("line_num", [0] * len(data["text"]))[i],
                })
            if not words:
                continue
            median_height = sorted(w["height"] for w in words)[len(words) // 2]
            # Invoice columns often use different font sizes: description,
            # quantity and rate baselines can differ by 15-25 px even on the
            # same printed row. Use a wider but capped tolerance so they stay
            # associated, while adjacent item rows remain separate.
            tolerance = max(12, min(28, median_height * 1.5))
            visual_rows: list[list[dict[str, Any]]] = []
            for word in sorted(words, key=lambda w: (w["y"], w["x0"])):
                possible = [(abs(sum(item["y"] for item in row) / len(row) - word["y"]), row)
                            for row in visual_rows[-5:]]
                possible = [entry for entry in possible if entry[0] <= tolerance]
                if possible:
                    min(possible, key=lambda entry: entry[0])[1].append(word)
                else:
                    visual_rows.append([word])
            for row in visual_rows:
                row.sort(key=lambda w: w["x0"])

            header_index = None
            header_centers: dict[str, float] = {}
            for idx, row in enumerate(visual_rows):
                labels: dict[str, list[dict[str, Any]]] = {}
                for word in row:
                    kind = label_kind(word["text"])
                    if kind:
                        labels.setdefault(kind, []).append(word)
                # Multi-word descriptions such as "Description of Goods" can
                # otherwise contribute both "Description" and "Goods" to the
                # same column center. Anchor the description column to its
                # left-most recognized header word.
                if len(labels.get("description", [])) > 1:
                    labels["description"] = [
                        min(labels["description"], key=lambda w: w["x0"])
                    ]
                if "description" in labels and "qty" in labels and "rate" in labels:
                    # In Indian tax invoices, "GST Rate" is a separate tax column.
                    # Its word "Rate" must not be averaged with the actual item-rate
                    # header, or the inferred Qty/Rate boundaries drift into HSN/GST.
                    if "ignore_gst" in labels:
                        qty_center = sum((w["x0"] + w["x1"]) / 2 for w in labels["qty"]) / len(labels["qty"])
                        real_rate_words = [
                            w for w in labels["rate"]
                            if (w["x0"] + w["x1"]) / 2 > qty_center
                        ]
                        if real_rate_words:
                            labels["rate"] = real_rate_words
                    header_index = idx
                    header_centers = {
                        kind: sum((w["x0"] + w["x1"]) / 2 for w in group) / len(group)
                        for kind, group in labels.items()
                    }
                    break
            if header_index is None:
                continue

            ordered_columns = sorted(
                (x, name) for name, x in header_centers.items()
                if name in {"description", "qty", "rate", "amount", "unit"}
                or name.startswith("ignore_")
            )
            if not any(name == "description" for _, name in ordered_columns):
                continue
            boundaries = [(ordered_columns[i][0] + ordered_columns[i + 1][0]) / 2
                          for i in range(len(ordered_columns) - 1)]

            def which_column(x: float) -> str | None:
                index = 0
                while index < len(boundaries) and x >= boundaries[index]:
                    index += 1
                return ordered_columns[index][1] if ordered_columns else None

            current_rows: list[dict[str, Any]] = []
            for row in visual_rows[header_index + 1:]:
                row_text = " ".join(w["text"] for w in row)
                if re.search(r"\b(?:grand\s+total|sub\s*total|total\s+amount|amount\s+in\s+words|taxable\s+value|cgst|sgst|igst|round\s*off|terms\s+and\s+conditions|bank\s+details)\b", row_text, re.I):
                    break
                cells: dict[str, list[dict[str, Any]]] = {}
                for word in row:
                    kind = which_column((word["x0"] + word["x1"]) / 2)
                    if kind:
                        cells.setdefault(kind, []).append(word)

                def cell(kind: str) -> str:
                    return " ".join(w["text"] for w in sorted(cells.get(kind, []), key=lambda w: w["x0"]))

                description = _clean_item_description(cell("description"))
                if not description or not re.search(r"[A-Za-z]{2,}", description):
                    continue
                if re.search(r"\b(?:description|particulars|quantity|qty|rate|amount|subtotal|total|cgst|sgst|igst|taxable|invoice|page|gstin)\b", description, re.I):
                    continue
                # Freight/carting/packing are invoice charges, not stock items.
                if re.search(r"\b(?:carting|freight|transport(?:ation)?|delivery\s+charges?|packing\s+charges?|handling\s+charges?|loading|unloading|round\s*off)\b", description, re.I):
                    continue
                description = _clean_item_description(description)
                # Reject tiny OCR fragments (e.g. "sis") as item descriptions.
                # They are commonly misread remnants of a longer product name and
                # must not become a selectable GRN item or trigger a weak catalog match.
                meaningful_tokens = re.findall(r"[A-Za-z]{2,}", description)
                if not meaningful_tokens or sum(len(token) for token in meaningful_tokens) < 4:
                    continue
                qty_text, rate_text = cell("qty"), cell("rate")
                qty_match, rate_match = number_re.search(qty_text), number_re.search(rate_text)
                qty = _number(qty_match.group(0)) if qty_match else None
                rate = _number(rate_match.group(0)) if rate_match else None
                amount_matches = list(number_re.finditer(cell("amount")))
                amount = _number(amount_matches[-1].group(0)) if amount_matches else None
                unit_text = cell("unit")
                unit_match = unit_re.search(qty_text + " " + unit_text)
                unit = unit_match.group(1).upper().rstrip(".") if unit_match else ""
                if not unit and unit_text:
                    candidate_unit = re.sub(r"[^A-Za-z./ -]", "", unit_text).strip(" .-/").upper()
                    if candidate_unit and len(candidate_unit) <= 12 and len(candidate_unit.split()) <= 2:
                        unit = candidate_unit

                # OCR frequently drops a faint decimal point (e.g. 76.00 -> 7600).
                # Only repair a rate when the independently detected line amount
                # supports it arithmetically; never scale a value on its own.
                if qty is not None and qty > 0 and rate is not None and amount is not None:
                    implied_rate = amount / qty
                    if abs(rate - implied_rate) > max(2.0, abs(implied_rate) * 0.03):
                        scaled_candidates = [rate / factor for factor in (10, 100, 1000)]
                        supported = [
                            value for value in scaled_candidates
                            if abs(value - implied_rate) <= max(0.03, abs(implied_rate) * 0.015)
                        ]
                        if len(supported) == 1:
                            rate = round(supported[0], 4)

                # Preserve credible item rows when one numeric cell was missed by OCR.
                # Blank values remain editable in the GRN form and must be reviewed;
                # dropping the whole row silently loses invoice goods.
                if qty is None and rate is None and amount is None:
                    continue
                if (qty is not None and qty <= 0) or (rate is not None and rate < 0):
                    continue
                # Fail closed on HSN/SAC codes shifted into Qty (e.g. 38089400).
                # A suspicious row is omitted for manual review rather than allowing
                # an eight-digit tax code to inflate received/accepted inventory.
                qty_digits = str(int(qty)) if qty is not None and float(qty).is_integer() else ""
                if qty is not None and (
                    qty >= 100000 or (4 <= len(qty_digits) <= 8 and qty == int(qty))
                ):
                    continue
                if re.fullmatch(r"[\d\s.,/-]+", description):
                    continue
                matched = match_master(description)
                current_rows.append(_mark_row_for_review({
                    "item_code": (matched.code or "") if matched else "",
                    "item_name": ((matched.name or description) if matched else description),
                    "vendor_code": "",
                    "vendor_name": "",
                    "recd_qty": qty,
                    "accepted_qty": None,
                    "rate": rate,
                    "unit": unit,
                    "line_amount": amount,
                    "match_status": "matched" if matched else "unmatched",
                    "source": "receipt_text",
                }))
            # Score row integrity, not just count. Invoice line amount should agree
            # with quantity × rate within rounding tolerance. Wrong column assignments
            # are penalized; missing amounts remain usable but lower-confidence.
            candidate_score = 0.0
            for item in current_rows:
                qty_value = item.get("recd_qty")
                rate_value = item.get("rate")
                amount_value = item.get("line_amount")
                # Repeated descriptions are valid invoice rows (e.g. same item
                # supplied from different batches/lines), so do not penalize them.
                candidate_score += 8
                if amount_value is not None and qty_value is not None and rate_value is not None:
                    expected = qty_value * rate_value
                    if abs(expected - amount_value) <= max(2.0, abs(amount_value) * 0.03):
                        candidate_score += 12
                    else:
                        candidate_score -= 10
                else:
                    candidate_score -= 1
                if qty_value is not None and (qty_value > 10000 or (float(qty_value).is_integer() and 1000 <= qty_value < 100000)):
                    candidate_score -= 20
                if not item.get("unit"):
                    candidate_score -= 0.5
            # Prefer a candidate with more valid rows only after evaluating integrity.
            # Keep rows even when qty × rate conflicts with the printed amount.
            # Discounts, tax-inclusive rates, rounding, or OCR errors can explain
            # differences; preserve the evidence and flag it for manual review.
            validated_rows = [_mark_row_for_review(item) for item in current_rows]

            if candidate_score > best_score or (
                candidate_score == best_score and len(validated_rows) > len(best_rows)
            ):
                best_score = candidate_score
                best_rows = validated_rows
            all_candidate_rows.extend(validated_rows)

    # Return one internally consistent OCR pass only. Merging numeric signatures
    # across preprocessing variants can combine unrelated rows (e.g. a qty/rate
    # pair from one pass with a misread description from another) and introduce
    # duplicate products. The selected pass is scored using row arithmetic above.
    return best_rows


def _parse_invoice_date(text: str):
    """Parse common invoice date formats, prioritizing explicitly labelled dates."""
    import calendar

    months = "|".join(
        [calendar.month_name[i] for i in range(1, 13)] +
        [calendar.month_abbr[i] for i in range(1, 13)]
    )
    token = (
        rf"(?:\d{{1,2}}(?:st|nd|rd|th)?[./\- ]\d{{1,2}}[./\- ]\d{{2,4}}"
        rf"|\d{{1,2}}(?:st|nd|rd|th)?[\-/ ](?:{months})[\-/ ,]+\d{{2,4}}"
        rf"|\d{{4}}[./\- ]\d{{1,2}}[./\- ]\d{{1,2}})"
    )
    date_label = r"(?:invoice\s+date|bill\s+date|date\s+of\s+invoice|dated|date)"
    # Invoice layouts commonly print the label and value on separate lines:
    #     Dated
    #     5-Aug-26
    # OCR may also insert spaces around hyphens or turn them into en/em dashes.
    # Normalize those OCR variants before applying the date patterns.
    normalized_text = text.replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-")
    normalized_text = re.sub(r"(?<=\d)\s*-\s*(?=[A-Za-z])", "-", normalized_text)
    normalized_text = re.sub(r"(?<=[A-Za-z])\s*-\s*(?=\d)", "-", normalized_text)

    label = re.compile(
        rf"\b{date_label}\b\s*[:#\-]?\s*({token})",
        re.I,
    )
    candidates = [m.group(1) for m in label.finditer(normalized_text)]
    if not candidates:
        # Allow a label on its own line, or short OCR punctuation/spacing,
        # before the date on the next line.
        next_line = re.compile(
            rf"\b{date_label}\b[^\S\n]*[:#\-]?[^\n]{{0,24}}\n\s*({token})",
            re.I,
        )
        candidates = [m.group(1) for m in next_line.finditer(normalized_text)]
    if not candidates:
        candidates = re.findall(token, text, re.I)

    formats = (
        "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y", "%d.%m.%y",
        "%d-%b-%Y", "%d-%b-%y", "%d/%b/%Y", "%d/%b/%y", "%d %b %Y", "%d %b %y",
        "%d-%B-%Y", "%d-%B-%y", "%d %B %Y", "%d %B %y",
        "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%m/%d/%Y",
    )
    for raw in candidates:
        value = re.sub(r"(?i)(\d)(st|nd|rd|th)\b", r"\1", raw.strip())
        value = re.sub(r"\s+", " ", value.replace(",", " ")).strip()
        for fmt in formats:
            try:
                parsed = datetime.strptime(value, fmt).date()
                if 1990 <= parsed.year <= datetime.now().year + 2:
                    return parsed.isoformat()
            except ValueError:
                continue
    return None


def _extract_fields(text: str, db: Session) -> dict[str, Any]:
    # Invoice labels vary by supplier and OCR may turn punctuation into spaces.
    # Capture the value after an explicit invoice/bill number label, including
    # values such as GST/7518/26-27.
    invoice_no = _first([
        # Standard invoice labels and IDs such as GST/7518/26-27.
        r"(?:(?:tax\s+)?invoice|inv\.?|bill)\s*(?:no\.?|number|num\.?|#)\s*[:\-#]?\s*([A-Z0-9][A-Z0-9/_.-]{2,})",
        r"(?:(?:tax\s+)?invoice|inv\.?|bill)\s*(?:no\.?|number|num\.?|#)\s*[:\-#]?\s*([A-Z0-9][A-Z0-9\s/_.-]{2,}?)(?=\s+(?:dated?|date|ref(?:erence)?\.?|gstin|party)\b|$)",
        # OCR may put the invoice ID on the line immediately after its label.
        r"(?im)^\s*(?:invoice|inv\.?|bill)\s*(?:no\.?|number|num\.?|#)\s*[:\-#]?\s*\n?\s*([A-Z]{2,}[A-Z0-9]*(?:\s*/\s*[A-Z0-9.-]+){1,})\b",
    ], text)
    if invoice_no and (
        re.search(
            r"\b(?:date|dated|gstin|original|recipient|duplicate|triplicate|delivery|reference|purchase|order)\b",
            invoice_no,
            re.I,
        )
        or _parse_invoice_date(invoice_no)
    ):
        # Some layouts place "Date" immediately after "Invoice No."; do not treat
        # that neighboring field label/date as the invoice identifier.
        invoice_no = None
    if invoice_no:
        invoice_no = re.sub(r"\s*/\s*", "/", invoice_no).replace(" ", "")
    else:
        # Recover IDs where the label and value are separated by layout/OCR line breaks.
        invoice_no = _invoice_number_from_nearby_label(text)
    # Do not interpret generic prose containing "purchase order" as a PO number.
    po_no = _first([
        r"(?:purchase\s*order|P\.?\s*O\.?)\s*(?:no\.?|number|ref(?:erence)?\.?|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9/_.-]{2,})",
    ], text)
    def clean_vendor_candidate(value: str | None) -> str:
        candidate = re.sub(r"\s+", " ", value or "").strip(" :|,-")
        # Reject contact-only lines rather than turning OCR-corrupted
        # phone/email text into a plausible-looking supplier name.
        if re.search(r"\d{8,}", re.sub(r"\D", "", candidate)):
            return ""
        if re.match(r"(?i)^\s*[([]?\s*(?:n|m|ph|mob|tel)\s*[)\].:-]", candidate):
            return ""
        if re.search(r"(?i)e[- ]?m(?:ail|att|a1l)\b", candidate):
            return ""
        # Contact details are often printed on the same line as the supplier.
        # Keep the business-name portion and never treat an email/phone as a name.
        candidate = re.split(
            r"(?i)\b(?:phone|mobile|mob|tel|email|e-mail|website|web|www|gstin|gst\s*in)\b|@|https?://",
            candidate,
            maxsplit=1,
        )[0].strip(" :|,-")
        candidate = re.sub(r"\b\+?\d[\d ()-]{7,}\b", " ", candidate)
        candidate = re.sub(r"\s+", " ", candidate).strip(" :|,-")
        if not candidate or "@" in candidate or re.search(r"\d{8,}", re.sub(r"\D", "", candidate)):
            return ""
        # A candidate must contain a real alphabetic business-name token.
        words = re.findall(r"[A-Za-z][A-Za-z&.'-]*", candidate)
        if not words or sum(map(len, words)) < 4:
            return ""
        return candidate[:90]

    vendor_text = clean_vendor_candidate(_first([
        r"(?:supplier|vendor)\s*(?:name)?\s*[:\-]\s*([^\n]{2,120})",
    ], text))
    if not vendor_text:
        # Many small-business invoices print the trading name as a standalone
        # heading, while phone/email/GSTIN/address details occupy nearby lines.
        # Score only plausible company-name lines; do not pick the first line
        # containing letters (which can be an email address or contact label).
        ignored_header = re.compile(
            r"invoice|tax invoice|bill no|invoice no|gstin|gst\s*in|state code|date|dated|"
            r"phone|mobile|\bmob\b|tel|email|e-mail|www|https?://|page|amount|"
            r"buyer|consignee|ship to|bill to|address|contact|original|duplicate|"
            r"udyam|pan no|state name|dispatch",
            re.I,
        )
        candidates = []
        for index, header_line in enumerate(text.splitlines()[:20]):
            raw_candidate = re.sub(r"\s+", " ", header_line).strip(" :|-")
            candidate = clean_vendor_candidate(raw_candidate)
            if not candidate or ignored_header.search(raw_candidate):
                continue
            if re.search(r"@|https?://|\d{8,}", raw_candidate):
                continue
            if re.search(r"(?i)e[- ]?m(?:ail|att|a1l)\b", raw_candidate):
                continue
            words = re.findall(r"[A-Za-z][A-Za-z&.'-]*", candidate)
            if len(words) < 2 and not re.search(r"\b(?:traders|trading|hardware|enterprise|enterprises|industries|stores|store|agency|agencies|sales|services|suppliers|supplier|corporation|co)\b", candidate, re.I):
                continue
            score = min(len(words), 4) * 2
            if re.search(r"\b(?:hardware|traders|trading|enterprise|enterprises|industries|stores|agency|sales|services|corporation)\b", candidate, re.I):
                score += 3
            if raw_candidate.isupper():
                score += 1
            # Earlier header lines are more likely to be the supplier masthead.
            score += max(0, 5 - index) * 0.2
            candidates.append((score, index, candidate))
        if candidates:
            candidates.sort(key=lambda entry: (entry[0], -entry[1]), reverse=True)
            vendor_text = candidates[0][2]
    # Accept common invoice date labels, including "Dated" on Indian invoices.
    date_pattern = (
        r"(\d{1,2}(?:st|nd|rd|th)?[./-]\d{1,2}[./-]\d{2,4}"
        r"|\d{1,2}(?:st|nd|rd|th)?[-/ ]\w{3,9}[-/ ,]+\d{2,4}"
        r"|\d{4}[./-]\d{1,2}[./-]\d{1,2})"
    )
    date_raw = _first([
        rf"\b(?:invoice\s+date|bill\s+date|date\s+of\s+invoice|dated|date)\b\s*[:\-]?\s*{date_pattern}",
        rf"\b(?:invoice\s+date|bill\s+date|date\s+of\s+invoice|dated|date)\b[^\n]{{0,12}}\n\s*{date_pattern}",
        r"\b(\d{1,2}[./-]\d{1,2}[./-]\d{4})\b",
    ], text)
    invoice_date = _parse_invoice_date(text)

    vendors = db.query(models.VendorModel).all()
    vendor_match = None
    normalized_text = _norm(text)

    # GSTIN is the strongest supplier identifier when present. Normalize OCR
    # punctuation/spacing and inspect both labelled GSTIN/UIN values and
    # standalone GSTIN-shaped tokens before falling back to supplier-name matching.
    def normalize_gstin(value: str | None) -> str:
        return re.sub(r"[^A-Z0-9]", "", (value or "").upper())

    gstin_pattern = r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]"
    labelled_gstins = re.findall(
        rf"(?i)\b(?:GSTIN(?:/UIN)?|GST\s*IN|UIN)\b\s*[:#\-]?\s*({gstin_pattern})",
        text,
    )
    all_gstins = re.findall(gstin_pattern, text, re.I)
    ocr_gstins = {normalize_gstin(value) for value in labelled_gstins + all_gstins}
    master_gstins: dict[str, list[Any]] = {}
    for vendor in vendors:
        gstin = normalize_gstin(vendor.gst_no)
        if gstin:
            master_gstins.setdefault(gstin, []).append(vendor)

    # Assign automatically only if exactly one vendor record matches. Duplicate
    # GSTINs in the directory remain ambiguous and use the safe name fallback.
    gst_matches = [
        vendor
        for gstin in ocr_gstins
        for vendor in master_gstins.get(gstin, [])
    ]
    if len(gst_matches) == 1:
        vendor_match = gst_matches[0]

    # Try the explicit supplier field first.
    if not vendor_match and vendor_text:
        norm = _norm(vendor_text)
        matches = [
            vendor for vendor in vendors
            if len(_norm(vendor.name or "")) >= 5
            and (_norm(vendor.name or "") in norm or norm in _norm(vendor.name or ""))
        ]
        if len(matches) == 1:
            vendor_match = matches[0]

    # Compare header lines to vendor-directory names to tolerate minor OCR errors.
    if not vendor_match:
        from difflib import SequenceMatcher

        lines = [re.sub(r"\s+", " ", line).strip(" :|\t") for line in text.splitlines()]
        candidates = [
            line for line in lines[:25]
            if 4 <= len(line) <= 100
            and re.search(r"[A-Za-z]{3,}", line)
            and not re.search(
                r"invoice|tax invoice|bill no|invoice no|gstin|state code|date|dated|"
                r"phone|mobile|email|www|page|amount|buyer|consignee|ship to|bill to|"
                r"purchase order|description|quantity|rate|total", line, re.I,
            )
        ]
        if vendor_text:
            candidates.insert(0, vendor_text)

        ranked = []
        for vendor in vendors:
            name = (vendor.name or "").strip()
            normalized_name = _norm(name)
            if len(normalized_name) < 5:
                continue
            tokens = {t for t in re.findall(r"[a-z0-9]+", name.lower()) if len(t) > 2}
            best = 0.0
            for candidate in candidates:
                score = SequenceMatcher(None, normalized_name, _norm(candidate)).ratio()
                candidate_tokens = {t for t in re.findall(r"[a-z0-9]+", candidate.lower()) if len(t) > 2}
                if tokens:
                    score = max(score, (len(tokens & candidate_tokens) / len(tokens)) * 0.92)
                best = max(best, score)
            if best >= 0.78:
                ranked.append((best, vendor))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        if ranked and (len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= 0.08):
            vendor_match = ranked[0][1]

    # Last fallback: exact normalized vendor name anywhere in OCR text.
    if not vendor_match:
        named_matches = [
            vendor for vendor in vendors
            if len(_norm(vendor.name or "")) >= 5 and _norm(vendor.name or "") in normalized_text
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
            "gst_no": next(iter(ocr_gstins)) if len(ocr_gstins) == 1 else "",
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
    # Browsers/proxies sometimes send application/octet-stream for PDFs.
    # Detect the real format from both the filename and the file signature.
    supplied_type = (file.content_type or "").lower().split(";")[0].strip()
    filename = (file.filename or "").lower()
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Document exceeds the 10 MB upload limit.")
    if not raw:
        raise HTTPException(400, "The uploaded document is empty.")

    is_pdf = raw.startswith(b"%PDF-") or filename.endswith(".pdf") or supplied_type == "application/pdf"
    if is_pdf:
        content_type = "application/pdf"
    elif supplied_type in {"image/jpeg", "image/png"}:
        content_type = supplied_type
    elif filename.endswith((".jpg", ".jpeg")) or raw.startswith(b"\xff\xd8\xff"):
        content_type = "image/jpeg"
    elif filename.endswith(".png") or raw.startswith(b"\x89PNG\r\n\x1a\n"):
        content_type = "image/png"
    else:
        raise HTTPException(415, "Upload a receipt in JPG, JPEG, PNG, or PDF format.")

    text = ""
    # Keep alternative header text separately from the candidate chosen for item parsing.
    # A candidate that reads table rows well can still miss supplier/date header text.
    supplemental_field_text = ""
    if content_type == "application/pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw))
            if len(reader.pages) > 30:
                raise HTTPException(413, "PDFs are limited to 30 pages.")
            if not reader.pages:
                raise HTTPException(400, "The PDF contains no readable pages.")

            # Read embedded text first; scanned pages commonly return empty text.
            page_texts = [(page.extract_text() or "").strip() for page in reader.pages]
            supplemental_page_texts = list(page_texts)
            table_text_by_page: list[str] = ["" for _ in page_texts]

            # Extract table cells as row-shaped text where possible.
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
                supplemental_field_text = "\n".join(
                    part for part in (
                        "\n".join(supplemental_page_texts),
                        "\n".join(value for value in table_text_by_page if value),
                    ) if part
                ).strip()
            except Exception:
                # Table extraction is optional; OCR/text extraction must still run.
                pass

            # Crucial fallback: a page is OCR'd if it has little embedded text OR
            # embedded/table text produces no actual receipt-text line rows.
            # Do not use the item-master fallback here; it can make a bad PDF look parsed.
            try:
                import pymupdf
                from PIL import Image
                with pymupdf.open(stream=raw, filetype="pdf") as pdf_document:
                    for index in range(len(page_texts)):
                        embedded = page_texts[index]
                        table_text = table_text_by_page[index]
                        digital_candidate = "\n".join(part for part in (embedded, table_text) if part).strip()
                        parsed_rows = [
                            row for row in _extract_item_rows(digital_candidate, db)
                            if row.get("source") == "receipt_text"
                        ] if digital_candidate else []
                        needs_ocr = (
                            len(re.sub(r"\s+", "", embedded)) < 80
                            or len(parsed_rows) == 0
                        )
                        if not needs_ocr:
                            continue

                        page = pdf_document.load_page(index)
                        # Render at 300 DPI-equivalent for small invoice print.
                        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(3, 3), alpha=False)
                        if pixmap.width * pixmap.height > 25_000_000:
                            # Keep the page within the image safety cap.
                            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
                        if pixmap.width * pixmap.height > 25_000_000:
                            raise HTTPException(413, "A rendered PDF page is too large to process.")
                        image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")
                        ocr_text = _run_ocr_candidates(image, modes=(6, 4, 11))
                        if ocr_text:
                            # Preserve OCR text for shared field extraction even when embedded
                            # text wins item-row selection (or vice versa).
                            supplemental_field_text = "\n".join(
                                part for part in (supplemental_field_text, ocr_text) if part
                            ).strip()
                            ocr_rows = [
                                row for row in _extract_item_rows(ocr_text, db)
                                if row.get("source") == "receipt_text"
                            ]
                            # Prefer OCR when it recovers more invoice rows or a
                            # higher-quality text candidate; avoid blindly appending
                            # duplicate headers and rows to embedded PDF text.
                            if len(ocr_rows) > len(parsed_rows) or not parsed_rows:
                                page_texts[index] = ocr_text
                                table_text_by_page[index] = ""
                            elif not embedded.strip():
                                page_texts[index] = ocr_text
            except HTTPException:
                raise
            except ImportError as exc:
                raise HTTPException(
                    503,
                    "PDF processing needs PyMuPDF, Pillow, pytesseract, and the Tesseract OCR engine installed on the backend.",
                ) from exc
            except Exception as exc:
                raise HTTPException(
                    400,
                    "The PDF could not be processed. Ensure it is a valid PDF and Tesseract OCR is installed for scanned pages.",
                ) from exc

            text = "\n".join(
                "\n".join(part for part in (page_texts[index], table_text_by_page[index]) if part)
                for index in range(len(page_texts))
            ).strip()
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

    # Use the selected text for item parsing, but let the common field extractor
    # inspect every available text source. This prevents choosing a table-focused
    # candidate from accidentally discarding a better-read supplier/date header.
    # Shared keyword parser receives the same combined text regardless of PDF/image input.
    from app.api.grn_keyword_parser import extract_header_fields
    combined_header_text = "\n".join(part for part in (text, supplemental_field_text) if part)
    keyword_fields = extract_header_fields(combined_header_text, db)
    result = _extract_fields(text, db)
    fields = result.get("fields", {})

    # If the invoice cannot be matched to a vendor master record, use the
    # uploaded document's filename (without .pdf/.jpg/.jpeg/.png) as a safer
    # vendor-name suggestion than an uncertain OCR line from the address block.
    # Ignore generic filenames such as "invoice", "scan", or "document".
    filename_stem = os.path.splitext(os.path.basename(file.filename or ""))[0]
    filename_vendor_name = re.sub(r"[._-]+", " ", filename_stem)
    filename_vendor_name = re.sub(r"\s+", " ", filename_vendor_name).strip(" _-")
    generic_filename = re.fullmatch(
        r"(?i)(?:invoice|tax invoice|bill|receipt|document|scan|image|photo|img|"
        r"whatsapp image|untitled|download|file|\d{1,8})",
        filename_vendor_name,
    )
    if (
        not fields.get("vendor_code")
        and len(filename_vendor_name) >= 4
        and not generic_filename
        and not re.fullmatch(r"[\W\d_]+", filename_vendor_name)
    ):
        fields["vendor_name"] = filename_vendor_name
    for key in ("invoice_no", "po_no", "grn_date"):
        if keyword_fields.get(key) and (key != "invoice_no" or not fields.get(key)):
            # Keep a validated, explicitly labelled invoice ID from the primary
            # extractor; use the shared keyword parser only when it was not found.
            fields[key] = keyword_fields[key]
    if keyword_fields.get("vendor_code"):
        fields["vendor_code"] = keyword_fields["vendor_code"]
        fields["vendor_name"] = keyword_fields.get("vendor_name") or fields.get("vendor_name", "")
    elif keyword_fields.get("vendor_name") and not fields.get("vendor_name"):
        fields["vendor_name"] = keyword_fields["vendor_name"]
    if supplemental_field_text:
        supplemental_result = _extract_fields(
            "\n".join(part for part in (text, supplemental_field_text) if part), db
        )
        # Keep keyword-parser values already applied above. Resetting this dict to
        # result["fields"] here discarded successful invoice/PO/vendor matches.
        supplemental_fields = supplemental_result.get("fields", {})
        # Only replace missing header fields; never overwrite a populated field
        # with a blank or an unmatched supplier candidate.
        if not fields.get("grn_date") and supplemental_fields.get("grn_date"):
            fields["grn_date"] = supplemental_fields["grn_date"]
        if not fields.get("vendor_code") and supplemental_fields.get("vendor_code"):
            fields["vendor_code"] = supplemental_fields["vendor_code"]
            fields["vendor_name"] = supplemental_fields.get("vendor_name", fields.get("vendor_name", ""))
        if not fields.get("invoice_no") and supplemental_fields.get("invoice_no"):
            fields["invoice_no"] = supplemental_fields["invoice_no"]
        if not fields.get("po_no") and supplemental_fields.get("po_no"):
            fields["po_no"] = supplemental_fields["po_no"]
        result["fields"] = fields
        result["warnings"] = list(dict.fromkeys(
            result.get("warnings", []) + supplemental_result.get("warnings", [])
        ))

    # Photos/scans need the same column-aware strategy as digital PDFs. If the
    # OCR bounding boxes identify a table, use only those rows rather than
    # unrelated text matches elsewhere on the page.
    if content_type != "application/pdf":
        try:
            from PIL import Image
            with Image.open(io.BytesIO(raw)) as source_image:
                image_items = _extract_image_table_line_items(source_image.convert("RGB"), db)
            if image_items:
                # Compare independent parsers rather than always trusting a
                # coordinate pass that may split one description across rows.
                # Keep the candidate with more complete invoice rows, with
                # arithmetic consistency as the tie-breaker.
                text_items = [
                    row for row in _extract_item_rows(text, db)
                    if row.get("source") == "receipt_text"
                ]
                def row_quality(rows):
                    score = len(rows) * 10
                    for row in rows:
                        qty = row.get("recd_qty")
                        rate = row.get("rate")
                        amount = row.get("line_amount")
                        if qty is not None and rate is not None and amount is not None:
                            if abs(qty * rate - amount) <= max(0.05, abs(amount) * 0.015):
                                score += 5
                            else:
                                score -= 8
                        if not row.get("item_name") or len(_norm(row.get("item_name", ""))) < 4:
                            score -= 4
                    return score
                chosen_items = text_items if text_items and row_quality(text_items) > row_quality(image_items) else image_items
                result["line_items"] = chosen_items
                result["warnings"] = [
                    warning for warning in result.get("warnings", [])
                    if "Line items were detected from receipt text" not in warning
                    and "One or more PO line items could not be matched" not in warning
                    and "Line items were read from image-table" not in warning
                ]
                result["warnings"].append(
                    "Line items were extracted using the highest-scoring OCR parser. Verify item names, quantities, and rates before saving."
                )
                if any(row.get("match_status") == "unmatched" for row in chosen_items):
                    result["warnings"].append(
                        "One or more invoice descriptions could not be matched confidently to the item master."
                    )
        except Exception:
            # Existing local OCR text extraction remains the fallback if
            # bounding-box table detection cannot confidently find the headers.
            pass

    # For PDFs with embedded text, use the table's actual word coordinates when
    # available. This avoids treating header fragments (e.g. "SHE/") as products
    # and keeps description, quantity, rate, and amount from separate columns
    # attached to the same invoice row. Scanned PDFs still use the OCR parser.
    if content_type == "application/pdf":
        coordinate_items = _extract_pdf_table_line_items(raw, db)
        # A PDF can mix digital-text pages with scanned pages. Previously, finding
        # even one digital table row disabled OCR for the entire document, silently
        # losing scanned pages. OCR only pages with no coordinate-extracted rows;
        # this also avoids spending OCR time on pages already handled successfully.
        try:
            import pymupdf
            from PIL import Image
            with pymupdf.open(stream=raw, filetype="pdf") as pdf_document:
                # Count independent text-parser candidates per page as a second
                # signal for missing rows. This is only a trigger for OCR; it never
                # adds text-parser rows directly or overrides coordinate evidence.
                expected_row_counts: dict[int, int] = {}
                for index, page in enumerate(pdf_document):
                    page_text = page.get_text("text") or ""
                    text_candidates = [
                        row for row in _extract_item_rows(page_text, db)
                        if row.get("source") == "receipt_text"
                    ] if page_text.strip() else []
                    expected_row_counts[index] = len(text_candidates)

                pages_to_ocr = _pdf_pages_needing_image_fallback(
                    len(pdf_document),
                    coordinate_items,
                    expected_row_counts=expected_row_counts,
                )
                for page_index in pages_to_ocr:
                    page = pdf_document.load_page(page_index)
                    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2.5, 2.5), alpha=False)
                    if pixmap.width * pixmap.height > 25_000_000:
                        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
                    if pixmap.width * pixmap.height > 25_000_000:
                        continue
                    page_image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")
                    candidates = _extract_image_table_line_items(page_image, db)
                    for row in candidates:
                        row["_source_page_index"] = page_index
                    existing = [
                        row for row in coordinate_items
                        if row.get("_source_page_index") == page_index
                    ]
                    # Prefer the OCR candidate only when it is measurably better;
                    # otherwise retain the coordinate parser's source values.
                    chosen_page_rows = _choose_pdf_page_rows(existing, candidates)
                    if chosen_page_rows is not existing:
                        coordinate_items = [
                            row for row in coordinate_items
                            if row.get("_source_page_index") != page_index
                        ]
                        coordinate_items.extend(chosen_page_rows)
            coordinate_items.sort(key=lambda row: row.get("_source_page_index", 0))
        except Exception:
            # Text extraction still returns its available rows if OCR is unavailable.
            pass
        if coordinate_items:
            # Internal page markers are only used to merge mixed PDF page types.
            for row in coordinate_items:
                row.pop("_source_page_index", None)
            result["line_items"] = coordinate_items
            result["warnings"] = [
                warning for warning in result.get("warnings", [])
                if "Line items were detected from receipt text" not in warning
                and "One or more PO line items could not be matched" not in warning
            ]
            result["warnings"].append(
                "Line items were read from PDF table positions. Verify item mapping, quantities, and rates before saving."
            )
            if any(row.get("match_status") == "unmatched" for row in coordinate_items):
                result["warnings"].append(
                    "One or more invoice descriptions could not be matched confidently to the item master."
                )

    review_rows = [row for row in result.get("line_items", []) if row.get("needs_review")]
    if review_rows:
        result["warnings"] = list(dict.fromkeys(
            result.get("warnings", []) + [
                f"{len(review_rows)} extracted line(s) need manual review because one or more values are incomplete or inconsistent."
            ]
        ))

    result["filename"] = (file.filename or "document")[:160]
    result["document_type"] = "pdf" if content_type == "application/pdf" else "image"
    return result
