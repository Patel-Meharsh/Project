"""Reusable, local-only document processing primitives.

The package contains deterministic Python helpers shared by GRN and future
document workflows. It does not call cloud services or AI APIs.
"""
from .layout import group_words_into_rows, rows_to_text
from .matching import normalize_alphanumeric, rank_candidates
from .validation import line_item_warnings, score_line_item_rows
from .ocr import prepare_ocr_variants, run_ocr_candidates
from .pdf import extract_pdf_text_sources
from .table import choose_rate_amount, extract_table_body_lines, normalize_ocr_numeric_text

__all__ = [
    "group_words_into_rows",
    "rows_to_text",
    "normalize_alphanumeric",
    "rank_candidates",
    "line_item_warnings",
    "score_line_item_rows",
    "prepare_ocr_variants",
    "run_ocr_candidates",
    "extract_pdf_text_sources",
    "choose_rate_amount",
    "extract_table_body_lines",
    "normalize_ocr_numeric_text",
]
