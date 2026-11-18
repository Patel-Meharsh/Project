"""Reusable local OCR pipeline for image-based business documents.

This module uses Tesseract and optional locally cached PaddleOCR models only.
It does not call hosted AI services or download models at runtime.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

from fastapi import HTTPException
from app.document_engine.matching import normalize_alphanumeric

logger = logging.getLogger(__name__)


def _number(value: str | None) -> float | None:
    if not value:
        return None
    cleaned = value.replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


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
    """Create aligned grayscale, denoised, Otsu and adaptive OCR image variants."""
    from PIL import Image, ImageEnhance, ImageOps, ImageFilter

    image = ImageOps.exif_transpose(image)
    if image.width * image.height > 25_000_000:
        raise HTTPException(413, "Image dimensions are too large to process.")

    gray_image = ImageOps.autocontrast(ImageOps.grayscale(image))
    # Upscale small phone images / low-DPI scans before OCR. Respect the
    # existing pixel safety cap, including after resizing.
    longest = max(gray_image.size)
    if longest < 2600:
        scale = min(2.0, 2600 / max(1, longest))
        target = (int(gray_image.width * scale), int(gray_image.height * scale))
        if target[0] * target[1] <= 25_000_000:
            gray_image = gray_image.resize(target, Image.Resampling.LANCZOS)

    try:
        import cv2
        import numpy as np

        gray = np.asarray(gray_image, dtype=np.uint8)

        # Remove only narrow, consistently dark scan borders. Do not trim the
        # invoice's printed table/grid lines or crop meaningful page content.
        height, width = gray.shape[:2]
        max_crop_x, max_crop_y = int(width * 0.025), int(height * 0.025)
        left, right, top, bottom = 0, width, 0, height

        def is_dark_edge(values):
            return float(np.mean(values)) < 72 and float(np.mean(values < 100)) > 0.60

        while left < max_crop_x and right - left > width * 0.90 and is_dark_edge(gray[top:bottom, left]):
            left += 1
        while right > width - max_crop_x and right - left > width * 0.90 and is_dark_edge(gray[top:bottom, right - 1]):
            right -= 1
        while top < max_crop_y and bottom - top > height * 0.90 and is_dark_edge(gray[top, left:right]):
            top += 1
        while bottom > height - max_crop_y and bottom - top > height * 0.90 and is_dark_edge(gray[bottom - 1, left:right]):
            bottom -= 1
        if left or top or right < width or bottom < height:
            gray = gray[top:bottom, left:right]

        # Estimate skew from long horizontal rules/lines, not the whole page
        # rectangle. This avoids mistaking a portrait page for a -90° rotation.
        inverse = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
        horizontal_kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT, (max(30, gray.shape[1] // 12), 1)
        )
        horizontal_lines = cv2.morphologyEx(inverse, cv2.MORPH_OPEN, horizontal_kernel)
        points = cv2.findNonZero(horizontal_lines)
        if points is not None and len(points) >= 20:
            angle = cv2.minAreaRect(points)[-1]
            angle = -(90 + angle) if angle < -45 else -angle
            if 0.35 <= abs(angle) <= 7.0:
                center = (gray.shape[1] / 2, gray.shape[0] / 2)
                matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
                gray = cv2.warpAffine(
                    gray, matrix, (gray.shape[1], gray.shape[0]),
                    flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE,
                )

        # Light median denoising removes isolated speckles without heavily
        # blurring decimal points and thin invoice characters.
        denoised = cv2.medianBlur(gray, 3)
        gaussian = cv2.GaussianBlur(denoised, (3, 3), 0)
        otsu = cv2.threshold(
            gaussian, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )[1]
        adaptive = cv2.adaptiveThreshold(
            denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 31, 11,
        )

        # Keep all variants geometrically aligned: the table parser uses their
        # OCR word coordinates to infer the same invoice columns.
        return [
            Image.fromarray(gray),
            Image.fromarray(denoised),
            Image.fromarray(otsu),
            Image.fromarray(adaptive),
        ]
    except ImportError:
        # Pillow fallback keeps extraction available when OpenCV is absent.
        sharp = ImageEnhance.Sharpness(gray_image).enhance(1.6).filter(ImageFilter.SHARPEN)
        threshold = gray_image.point(lambda pixel: 255 if pixel > 175 else 0)
        return [gray_image, sharp, threshold]


_paddle_ocr_engine = None


def _paddleocr_candidate(image) -> dict[str, Any]:
    """Return PaddleOCR text, mean confidence and position-ordered word rows."""
    global _paddle_ocr_engine
    try:
        import numpy as np
        from paddleocr import PaddleOCR

        if _paddle_ocr_engine is None:
            det_dir = os.getenv("GRN_PADDLEOCR_DET_MODEL_DIR")
            rec_dir = os.getenv("GRN_PADDLEOCR_REC_MODEL_DIR")
            cls_dir = os.getenv("GRN_PADDLEOCR_CLS_MODEL_DIR")
            model_dirs = (det_dir, rec_dir, cls_dir)
            models_ready = all(
                path
                and os.path.isfile(os.path.join(path, "inference.pdmodel"))
                and os.path.isfile(os.path.join(path, "inference.pdiparams"))
                for path in model_dirs
            )
            if not models_ready:
                logger.info(
                    "PaddleOCR skipped: configure local GRN_PADDLEOCR_DET_MODEL_DIR, "
                    "GRN_PADDLEOCR_REC_MODEL_DIR and GRN_PADDLEOCR_CLS_MODEL_DIR "
                    "to use cached models without network downloads."
                )
                return {"text": "", "confidence": 0.0, "word_count": 0, "engine": "paddleocr"}
            _paddle_ocr_engine = PaddleOCR(
                det_model_dir=det_dir,
                rec_model_dir=rec_dir,
                cls_model_dir=cls_dir,
                use_angle_cls=True,
                lang="en",
                show_log=False,
            )
        result = _paddle_ocr_engine.ocr(np.asarray(image.convert("RGB")), cls=True) or []
        words = []
        confidences = []
        for page_result in result:
            for entry in page_result or []:
                try:
                    box, recognition = entry
                    label, confidence = recognition
                    confidence = float(confidence)
                    if label and confidence >= 0.25:
                        xs = [point[0] for point in box]
                        ys = [point[1] for point in box]
                        words.append({
                            "text": str(label).strip(),
                            "x": sum(xs) / len(xs),
                            "y": sum(ys) / len(ys),
                            "confidence": confidence * 100,
                        })
                        confidences.append(confidence * 100)
                except (TypeError, ValueError, IndexError):
                    continue
        rows = group_words_into_rows(words, image.height, tolerance_ratio=0.012)
        text = rows_to_text(rows)
        return {
            "text": text,
            "confidence": sum(confidences) / len(confidences) if confidences else 0.0,
            "word_count": len(words),
            "engine": "paddleocr",
        }
    except ImportError:
        logger.info("PaddleOCR is not installed; continuing with Tesseract only.")
        return {"text": "", "confidence": 0.0, "word_count": 0, "engine": "paddleocr"}
    except Exception:
        logger.exception("PaddleOCR candidate failed; continuing with Tesseract.")
        return {"text": "", "confidence": 0.0, "word_count": 0, "engine": "paddleocr"}


def _tesseract_box_candidate(image, mode: int = 6) -> dict[str, Any]:
    """Reconstruct Tesseract words in visual order and retain TSV confidence."""
    try:
        import pytesseract
        from pytesseract import Output

        data = pytesseract.image_to_data(
            image, config=f"--oem 3 --psm {mode}", output_type=Output.DICT
        )
        words = []
        confidences = []
        for index, raw_word in enumerate(data.get("text", [])):
            word = (raw_word or "").strip()
            try:
                confidence = float(data["conf"][index])
            except (ValueError, TypeError, KeyError, IndexError):
                confidence = -1
            if word and confidence >= 15:
                words.append({
                    "text": word,
                    "x": int(data["left"][index]),
                    "y": int(data["top"][index]) + int(data["height"][index]) // 2,
                })
                confidences.append(confidence)
        rows = group_words_into_rows(words, image.height, tolerance_ratio=0.006)
        text = rows_to_text(rows)
        return {
            "text": text,
            "confidence": sum(confidences) / len(confidences) if confidences else 0.0,
            "word_count": len(words),
            "engine": "tesseract",
        }
    except Exception:
        return {"text": "", "confidence": 0.0, "word_count": 0, "engine": "tesseract"}


def _ocr_candidate_score(candidate: dict[str, Any]) -> float:
    """Combine invoice-text quality with the OCR engine's own word confidence."""
    text_value = str(candidate.get("text") or "")
    confidence = max(0.0, min(100.0, float(candidate.get("confidence") or 0.0)))
    return _ocr_quality_score(text_value) + confidence * 0.15


def _run_ocr_candidates(image, modes: tuple[int, ...] = (6, 11), include_paddle: bool = True, paddle_text_out: dict[str, str] | None = None) -> str:
    """Run a fast OCR pass first, escalating only when the result is weak."""
    import pytesseract

    variants = _prepare_ocr_variants(image)
    fast_variant = variants[0]
    candidates: list[dict[str, Any]] = []

    def add_tesseract_candidate(variant, mode: int, variant_index: int = 0):
        try:
            candidate_text = pytesseract.image_to_string(
                variant, config=f"--oem 3 --psm {mode}"
            ).strip()
        except Exception:
            return
        if candidate_text:
            candidate_text = re.sub(
                r"(?<![A-Za-z0-9])S(?=\s*BTL\b)", "5", candidate_text, flags=re.I
            )
            candidates.append({
                "text": candidate_text,
                "confidence": 0.0,
                "engine": "tesseract",
                "variant": variant_index,
                "mode": mode,
                "score": _ocr_quality_score(candidate_text),
            })

    # One inexpensive first pass is enough for most clean scans.
    add_tesseract_candidate(fast_variant, 6)
    if paddle_text_out is not None:
        paddle_text_out["text"] = ""

    # Only try PaddleOCR when all three local model directories are configured.
    # This avoids importing/initializing a large OCR runtime when it cannot run.
    paddle_candidate = (
        _paddleocr_candidate(fast_variant)
        if include_paddle and all(os.getenv(key) for key in (
            "GRN_PADDLEOCR_DET_MODEL_DIR",
            "GRN_PADDLEOCR_REC_MODEL_DIR",
            "GRN_PADDLEOCR_CLS_MODEL_DIR",
        ))
        else {"text": "", "confidence": 0.0, "engine": "paddleocr"}
    )
    if paddle_text_out is not None:
        paddle_text_out["text"] = paddle_candidate.get("text", "")
    if paddle_candidate.get("text"):
        candidates.append(paddle_candidate)

    best_score = max(
        (_ocr_candidate_score(item) for item in candidates), default=0.0
    )

    # Escalate only weak pages. Limit retries to two useful variants and two
    # layouts rather than running every filter/layout combination.
    if best_score < 70:
        retry_variants = [variants[1], variants[2]] if len(variants) > 2 else variants[1:]
        for variant_index, variant in enumerate(retry_variants, start=1):
            for mode in modes[:2]:
                add_tesseract_candidate(variant, mode, variant_index)
        # TSV reconstruction is expensive; use it once, only for a weak page.
        if candidates:
            box_candidate = _tesseract_box_candidate(variants[2] if len(variants) > 2 else fast_variant, 6)
            if box_candidate.get("text"):
                candidates.append(box_candidate)

    if not candidates:
        return ""

    paddle_text = next(
        (item["text"] for item in candidates if item.get("engine") == "paddleocr"),
        "",
    )
    for candidate in candidates:
        candidate["score"] = _ocr_candidate_score(candidate)
        if paddle_text and candidate.get("engine") == "tesseract":
            from difflib import SequenceMatcher
            similarity = SequenceMatcher(
                None, normalize_alphanumeric(candidate["text"]), normalize_alphanumeric(paddle_text)
            ).ratio()
            candidate["score"] += similarity * 8.0

    best = max(candidates, key=lambda item: item.get("score", 0.0))
    best_text = str(best.get("text") or "")
    return re.sub(r"(?<![A-Za-z0-9])S(?=\s*BTL\b)", "5", best_text, flags=re.I)



def prepare_ocr_variants(image):
    """Public document-engine entry point for deterministic image preprocessing."""
    return _prepare_ocr_variants(image)


def run_ocr_candidates(
    image,
    modes: tuple[int, ...] = (6, 11),
    include_paddle: bool = True,
    paddle_text_out: dict[str, str] | None = None,
) -> str:
    """Public document-engine entry point for local OCR candidate selection."""
    return _run_ocr_candidates(
        image,
        modes=modes,
        include_paddle=include_paddle,
        paddle_text_out=paddle_text_out,
    )
