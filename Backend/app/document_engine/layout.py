"""Coordinate-based layout helpers for OCR and PDF word extraction."""
from __future__ import annotations

from typing import Any, Iterable


def group_words_into_rows(
    words: Iterable[dict[str, Any]],
    page_height: int,
    tolerance_ratio: float = 0.006,
    minimum_tolerance: int = 10,
) -> list[list[dict[str, Any]]]:
    """Group OCR words by vertical position, preserving left-to-right order.

    Each word must provide text, x and y. Coordinates can be centers or top
    positions, as long as one convention is used for the full input collection.
    """
    ordered = sorted(
        (word for word in words if str(word.get("text") or "").strip()),
        key=lambda word: (float(word.get("y", 0)), float(word.get("x", 0))),
    )
    tolerance = max(minimum_tolerance, int(max(1, page_height) * tolerance_ratio))
    rows: list[list[dict[str, Any]]] = []
    for word in ordered:
        target = None
        for row in reversed(rows[-4:]):
            center_y = sum(float(item.get("y", 0)) for item in row) / len(row)
            if abs(float(word.get("y", 0)) - center_y) <= tolerance:
                target = row
                break
        if target is None:
            rows.append([word])
        else:
            target.append(word)

    for row in rows:
        row.sort(key=lambda word: float(word.get("x", 0)))
    return rows


def rows_to_text(rows: Iterable[Iterable[dict[str, Any]]]) -> str:
    """Convert coordinate-grouped words into line-preserving text."""
    return "\n".join(
        " ".join(str(word.get("text") or "").strip() for word in row).strip()
        for row in rows
    ).strip()
