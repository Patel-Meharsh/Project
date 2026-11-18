"""Deterministic validation and quality scoring for extracted line items."""
from __future__ import annotations

from typing import Any, Iterable
import re


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
    """Score row completeness, arithmetic consistency and invoice-table plausibility."""
    materialized = list(rows)
    score = float(len(materialized) * 10)
    footer_terms = re.compile(
        r"\b(?:bank|account|ifsc|branch|pan|gstin|licen[cs]e|declaration|"
        r"authori[sz]ed|signatory|subtotal|grand\s+total|amount\s+chargeable)\b",
        re.I,
    )
    for row in materialized:
        description = str(row.get("item_name") or "").strip()
        quantity = row.get("recd_qty")
        rate = row.get("rate")
        amount = row.get("line_amount")
        normalized = "".join(ch for ch in description.lower() if ch.isalnum())
        words = re.findall(r"[A-Za-z]{2,}", description)
        digits = sum(ch.isdigit() for ch in description)

        if len(normalized) < 4:
            score -= 8
        if len(description) > 90:
            score -= 8
        if footer_terms.search(description):
            score -= 30
        if digits > max(4, len(description) * 0.35):
            score -= 8
        if len(words) < 1:
            score -= 5

        if quantity is None:
            score -= 3
        elif quantity <= 0:
            score -= 8
        if rate is None:
            score -= 3
        elif rate < 0:
            score -= 8
        if amount is not None and amount < 0:
            score -= 8

        if amount is not None and quantity is not None and rate is not None:
            if abs(quantity * rate - amount) <= max(2.0, abs(amount) * 0.03):
                score += 4
            else:
                score -= 5
    return score
