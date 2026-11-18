"""Deterministic validation and quality scoring for extracted line items."""
from __future__ import annotations

from typing import Any, Iterable


def line_item_warnings(
    quantity: float | None,
    rate: float | None,
    amount: float | None,
    tolerance_ratio: float = 0.015,
) -> list[str]:
    """Return review warnings without rewriting or discarding invoice values."""
    warnings = []
    if quantity is None:
        warnings.append("quantity was not confidently read")
    if rate is None:
        warnings.append("rate was not confidently read")
    if quantity is not None and rate is not None and amount is not None:
        expected = quantity * rate
        if abs(expected - amount) > max(0.05, abs(amount) * tolerance_ratio):
            warnings.append("quantity × rate differs from the printed line amount")
    return warnings


def score_line_item_rows(rows: Iterable[dict[str, Any]]) -> float:
    """Score row completeness and arithmetic consistency for parser selection."""
    materialized = list(rows)
    score = float(len(materialized) * 10)
    for row in materialized:
        quantity = row.get("recd_qty")
        rate = row.get("rate")
        amount = row.get("line_amount")
        if quantity is None:
            score -= 3
        if rate is None:
            score -= 3
        if amount is not None and quantity is not None and rate is not None:
            if abs(quantity * rate - amount) <= max(2.0, abs(amount) * 0.03):
                score += 4
            else:
                score -= 5
        if len("".join(ch for ch in str(row.get("item_name") or "").lower() if ch.isalnum())) < 4:
            score -= 4
    return score
