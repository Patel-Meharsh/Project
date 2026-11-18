"""Reusable, local-only document processing primitives.

The package contains deterministic Python helpers shared by GRN and future
document workflows. It does not call cloud services or AI APIs.
"""
from .layout import group_words_into_rows, rows_to_text
from .matching import normalize_alphanumeric, rank_candidates
from .validation import line_item_warnings, score_line_item_rows

__all__ = [
    "group_words_into_rows",
    "rows_to_text",
    "normalize_alphanumeric",
    "rank_candidates",
    "line_item_warnings",
    "score_line_item_rows",
]
