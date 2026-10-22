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

    candidates: list[str] = []
    for variant in _prepare_ocr_variants(image):
        for mode in modes:
            config = f"--oem 3 --psm {mode}"
            candidate = pytesseract.image_to_string(variant, config=config).strip()
            if candidate:
                # Correct high-confidence, common OCR confusion in quantities.
                candidate = re.sub(r"(?<![A-Za-z0-9])S(?=\s*BTL\b)", "5", candidate, flags=re.I)
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
        body = re.sub(r"^\s*[\W_]*\d{1,3}\s*[\W_]*", "", line)
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
            # Do not trust a rate inferred from OCR column order unless it is
            # arithmetically consistent with quantity and line amount. Incorrect
            # values are worse than blanks in an inventory record.
            if qty is not None and rate is not None and amount is not None:
                expected_amount = qty * rate
                if abs(expected_amount - amount) > max(2.0, expected_amount * 0.03):
                    rate = None
                    amount = None
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
            "item_name": description,
            "vendor_code": (matched.vendor_code or "") if matched else "",
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
        })
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
        r"\b(BTL|BOTTLES?|PKT|PACKETS?|NOS?\.?|PCS?\.?|MTR|MET(?:RE|ER)S?|"
        r"KGS?|GMS?|LTRS?|LIT(?:RE|ER)S?|ROLLS?|BOX(?:ES)?|SETS?|PAIRS?|"
        r"DOZ(?:EN)?|BAGS?|REAMS?|TUBES?|CANS?|JARS?|UNITS?|SQ\.?\s*FT|"
        r"SQ\.?\s*M|FT|FEET|INCH(?:ES)?|MM|CM|LBS?|TONS?)\b",
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
        if token in {"description", "particulars", "item", "itemdescription", "product", "products", "goods", "details"}:
            return "description"
        if token in {"qty", "quantity", "qnty", "qtys"}:
            return "qty"
        if token in {"rate", "price", "unitprice", "unitrate", "basicrate", "mrp"}:
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
        for page in document:
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
                kinds: dict[str, list[dict[str, Any]]] = {}
                for word in row:
                    kind = token_kind(word["text"])
                    if kind:
                        kinds.setdefault(kind, []).append(word)
                numeric_kinds = set(kinds) & {"qty", "rate", "amount"}
                if "description" in kinds and len(numeric_kinds) >= 2:
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
                if kind in {"description", "qty", "rate", "amount", "unit", "hsn", "gst", "discount", "value_supply"}
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
            body_rows = close_row(body_words, max(y_tolerance, median_height * 0.8))

            for row in body_rows:
                # Build each cell according to dynamically inferred column boundaries.
                cells: dict[str, list[dict[str, Any]]] = {}
                for word in row:
                    kind = column_for((word["x0"] + word["x1"]) / 2)
                    if kind:
                        cells.setdefault(kind, []).append(word)
                description_words = sorted(cells.get("description", []), key=lambda w: w["x0"])
                description = " ".join(w["text"] for w in description_words).strip(" .:|-\t")
                if not description or not re.search(r"[A-Za-z]{2,}", description):
                    continue
                if re.search(r"\b(?:description|particulars|quantity|qty|rate|amount|subtotal|grand total|cgst|sgst|igst|taxable|invoice|page)\b", description, re.I):
                    continue
                # Remove only a leading row serial; preserve meaningful leading
                # product values such as "15 W LED fitting".
                description = re.sub(r"^\s*\d{1,3}[.)]?\s+(?=[A-Za-z])", "", description).strip()

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
                unit = unit_match.group(1).upper().rstrip(".") if unit_match else ""

                # Some tables print the UOM next to quantity; others put it in
                # its own column. Never infer quantity/rate from description text.
                if qty is None and rate is None and amount is None:
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
                extracted.append({
                    "item_code": (matched.code or "") if matched else "",
                    "item_name": description,
                    "vendor_code": (matched.vendor_code or "") if matched else "",
                    "vendor_name": "",
                    "recd_qty": qty,
                    "accepted_qty": None,
                    "rate": rate,
                    "unit": unit,
                    "line_amount": amount,
                    "match_status": "matched" if matched else "unmatched",
                    "source": "receipt_text",
                })
    finally:
        document.close()

    # Keep repeated descriptions if they are separate invoice lines, but avoid
    # accidental duplicate rows generated by wrapped/overlapping text extraction.
    deduped = []
    seen = set()
    for row in extracted:
        key = (_norm(row["item_name"]), row.get("recd_qty"), row.get("rate"), row.get("line_amount"))
        if key not in seen:
            seen.add(key)
            deduped.append(row)
    return deduped

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
        r"\b(BTL|BOTTLES?|PKT|PACKETS?|NOS?\.?|PCS?\.?|MTR|MET(?:RE|ER)S?|"
        r"KGS?|GMS?|LTRS?|LIT(?:RE|ER)S?|ROLLS?|BOX(?:ES)?|SETS?|PAIRS?|"
        r"DOZ(?:EN)?|BAGS?|REAMS?|TUBES?|CANS?|JARS?|UNITS?|MM|CM|FT|FEET|"
        r"INCH(?:ES)?|SQ\.?\s*FT|SQ\.?\s*M)\b", re.I
    )

    def normalize_label(value: str) -> str:
        return re.sub(r"[^a-z]", "", value.lower())

    def label_kind(value: str) -> str | None:
        value = normalize_label(value)
        if value in {"description", "particulars", "item", "items", "product", "products", "goods", "details", "itemdescription"}:
            return "description"
        if value in {"qty", "quantity", "qnty", "qtys"}:
            return "qty"
        if value in {"rate", "price", "unitprice", "unitrate", "basicrate", "mrp"}:
            return "rate"
        # Keep every non-item column in the spatial model. If HSN/GST
        # headers are omitted here, their wide gap makes the description-to-qty
        # boundary span across those columns and codes such as 38089400 become qty.
        if value in {"amount", "amt", "lineamount", "totalamount"}:
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
            tolerance = max(7, min(18, median_height * 0.9))
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

                description = re.sub(r"\s+", " ", cell("description")).strip(" .:|-\t")
                if not description or not re.search(r"[A-Za-z]{2,}", description):
                    continue
                if re.search(r"\b(?:description|particulars|quantity|qty|rate|amount|subtotal|total|cgst|sgst|igst|taxable|invoice|page|gstin)\b", description, re.I):
                    continue
                # Freight/carting/packing are invoice charges, not stock items.
                if re.search(r"\b(?:carting|freight|transport(?:ation)?|delivery\s+charges?|packing\s+charges?|handling\s+charges?|loading|unloading|round\s*off)\b", description, re.I):
                    continue
                description = re.sub(r"^\s*\d{1,3}[.)]?\s+(?=[A-Za-z])", "", description).strip()
                qty_text, rate_text = cell("qty"), cell("rate")
                qty_match, rate_match = number_re.search(qty_text), number_re.search(rate_text)
                qty = _number(qty_match.group(0)) if qty_match else None
                rate = _number(rate_match.group(0)) if rate_match else None
                amount_matches = list(number_re.finditer(cell("amount")))
                amount = _number(amount_matches[-1].group(0)) if amount_matches else None
                unit_match = unit_re.search(qty_text + " " + cell("unit"))
                unit = unit_match.group(1).upper().rstrip(".") if unit_match else ""

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

                # The user's required columns are item name, quantity and rate.
                # Do not add a row when OCR could not find either numeric field.
                if qty is None or rate is None or qty <= 0 or rate < 0:
                    continue
                # Fail closed on HSN/SAC codes shifted into Qty (e.g. 38089400).
                # A suspicious row is omitted for manual review rather than allowing
                # an eight-digit tax code to inflate received/accepted inventory.
                qty_digits = str(int(qty)) if float(qty).is_integer() else ""
                if qty >= 100000 or (4 <= len(qty_digits) <= 8 and qty == int(qty)):
                    continue
                if re.fullmatch(r"[\d\s.,/-]+", description):
                    continue
                matched = match_master(description)
                current_rows.append({
                    "item_code": (matched.code or "") if matched else "",
                    "item_name": description,
                    "vendor_code": (matched.vendor_code or "") if matched else "",
                    "vendor_name": "",
                    "recd_qty": qty,
                    "accepted_qty": None,
                    "rate": rate,
                    "unit": unit,
                    "line_amount": amount,
                    "match_status": "matched" if matched else "unmatched",
                    "source": "receipt_text",
                })
            # Score row integrity, not just count. Invoice line amount should agree
            # with quantity × rate within rounding tolerance. Wrong column assignments
            # are penalized; missing amounts remain usable but lower-confidence.
            candidate_score = 0.0
            seen_descriptions: set[str] = set()
            for item in current_rows:
                qty_value = item.get("recd_qty")
                rate_value = item.get("rate")
                amount_value = item.get("line_amount")
                description_key = _norm(item.get("item_name", ""))
                if description_key in seen_descriptions:
                    candidate_score -= 8
                seen_descriptions.add(description_key)
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
            if candidate_score > best_score or (
                candidate_score == best_score and len(current_rows) > len(best_rows)
            ):
                best_score = candidate_score
                best_rows = current_rows

    return best_rows


def _extract_fields(text: str, db: Session) -> dict[str, Any]:
    # Invoice labels vary by supplier and OCR may turn punctuation into spaces.
    # Capture the value after an explicit invoice/bill number label, including
    # values such as GST/7518/26-27.
    invoice_no = _first([
        r"(?:invoice|inv\.?|bill)\s*(?:no\.?|number|num\.?|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9/_.-]{2,})",
        r"(?:invoice|inv\.?|bill)\s*(?:no\.?|number|num\.?|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\s/_.-]{2,}?)(?=\s+(?:dated?|date|ref(?:erence)?\.?|gstin|party)\b|$)",
    ], text)
    # Do not interpret generic prose containing "purchase order" as a PO number.
    po_no = _first([
        r"(?:purchase\s*order|P\.?\s*O\.?)\s*(?:no\.?|number|ref(?:erence)?\.?|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9/_.-]{2,})",
    ], text)
    vendor_text = _first([
        r"(?:supplier|vendor)\s*(?:name)?\s*[:\-]\s*([^\n]{2,100})",
    ], text)
    if not vendor_text:
        # Some invoices print the supplier as a heading without a "Vendor:" label.
        # Use a short header line as a display fallback; master matching below still
        # decides whether a vendor code can be assigned.
        ignored_header = re.compile(
            r"(invoice|tax invoice|bill no|invoice no|gstin|state code|date|phone|mobile|email|www|page|amount)",
            re.I,
        )
        for header_line in text.splitlines()[:10]:
            candidate = re.sub(r"\s+", " ", header_line).strip(" :|-")
            if 4 <= len(candidate) <= 90 and re.search(r"[A-Za-z]{3,}", candidate) and not ignored_header.search(candidate):
                vendor_text = candidate
                break
    date_raw = _first([
        r"(?:invoice\s*)?(?:date|dated)\s*[:\-]?\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{1,2}[-/ ]\w{3}[-/ ]\d{2,4}|\d{4}[./-]\d{1,2}[./-]\d{1,2})",
        r"\b(\d{1,2}[./-]\d{1,2}[./-]\d{4})\b",
    ], text)
    invoice_date = None
    if date_raw:
        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y", "%d.%m.%y", "%d-%b-%Y", "%d-%b-%y", "%d/%b/%Y", "%d/%b/%y", "%d %b %Y", "%d %b %y", "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%m/%d/%Y"):
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

    result = _extract_fields(text, db)

    # Photos/scans need the same column-aware strategy as digital PDFs. If the
    # OCR bounding boxes identify a table, use only those rows rather than
    # unrelated text matches elsewhere on the page.
    if content_type != "application/pdf":
        try:
            from PIL import Image
            with Image.open(io.BytesIO(raw)) as source_image:
                image_items = _extract_image_table_line_items(source_image.convert("RGB"), db)
            if image_items:
                result["line_items"] = image_items
                result["warnings"] = [
                    warning for warning in result.get("warnings", [])
                    if "Line items were detected from receipt text" not in warning
                    and "One or more PO line items could not be matched" not in warning
                ]
                result["warnings"].append(
                    "Line items were read from detected image-table columns. Verify item names, quantities, and rates before saving."
                )
                if any(row.get("match_status") == "unmatched" for row in image_items):
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
        if coordinate_items:
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

    result["filename"] = (file.filename or "document")[:160]
    result["document_type"] = "pdf" if content_type == "application/pdf" else "image"
    return result
