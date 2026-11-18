"""Digital-PDF text and table extraction for reusable document workflows."""
from __future__ import annotations

import io
import re
from typing import Any

from fastapi import HTTPException


def extract_pdf_text_sources(raw: bytes, max_pages: int = 30) -> dict[str, Any]:
    """Extract embedded page text and optional table rows from a PDF.

    Scanned pages intentionally return empty embedded text; the caller decides
    whether image rendering and OCR are needed for each page.
    """
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw))
        if len(reader.pages) > max_pages:
            raise HTTPException(413, f"PDFs are limited to {max_pages} pages.")
        if not reader.pages:
            raise HTTPException(400, "The PDF contains no readable pages.")
        page_texts = [(page.extract_text() or "").strip() for page in reader.pages]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, "The PDF could not be read. Please upload a valid PDF.") from exc

    table_text_by_page = ["" for _ in page_texts]
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            for index, page in enumerate(pdf.pages[:len(page_texts)]):
                rows = []
                for table in (page.extract_tables() or []):
                    for row in table:
                        cells = [
                            re.sub(r"\\s+", " ", (cell or "")).strip()
                            for cell in row
                        ]
                        if any(cells):
                            rows.append(" | ".join(cells))
                if rows:
                    table_text_by_page[index] = "\\n".join(rows)
    except Exception:
        # Embedded text remains useful even if optional table detection fails.
        pass

    supplemental_field_text = "\\n".join(
        part for part in (
            "\\n".join(page_texts),
            "\\n".join(value for value in table_text_by_page if value),
        ) if part
    ).strip()

    return {
        "page_texts": page_texts,
        "table_text_by_page": table_text_by_page,
        "supplemental_field_text": supplemental_field_text,
    }
