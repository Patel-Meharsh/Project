"""Table-region and numeric cleanup helpers for noisy invoice OCR."""
from __future__ import annotations

import re
from typing import Iterable


_HEADER_WORDS = re.compile(
    r"\b(?:d?escription\s+of\s+goods|d?escription|particulars|item\s+description|"
    r"product\s+description|goods\s+details)\b", re.I
)
_QTY_WORDS = re.compile(r"\b(?:qty|quantity|qnty|billed\s+qty)\b", re.I)
_RATE_WORDS = re.compile(r"\b(?:rate|unit\s+price|price\s+per\s+unit)\b", re.I)
_FOOTER = re.compile(
    r"\b(?:sub\s*total|grand\s*total|total\s+amount|amount\s+in\s+words|"
    r"amount\s+chargeable|cgst|sgst|igst|round\s*off|bank\s+details|"
    r"company'?s?\s+pan|declaration|drug\s+licen[cs]e|authori[sz]ed\s+signatory|"
    r"terms\s+and\s+conditions)\b", re.I
)


def extract_table_body_lines(text: str) -> list[str]:
    """Keep only text plausibly inside an invoice's line-item table.

    A recognized table header is preferred. For less structured receipts without
    a header, retain the text until a clear totals/footer marker. Numeric-only
    footer rows are rejected so account/licence numbers cannot become products.
    """
    lines = [re.sub(r"\s+", " ", line).strip() for line in (text or "").splitlines()]
    lines = [line for line in lines if line]
    start = 0
    header_found = False

    # Headers are often split by OCR into adjacent visual lines.
    for index in range(len(lines)):
        window = " ".join(lines[index:index + 2])
        if _HEADER_WORDS.search(window) and _QTY_WORDS.search(window) and _RATE_WORDS.search(window):
            start = index + (1 if index + 1 < len(lines) and not (
                _QTY_WORDS.search(lines[index]) and _RATE_WORDS.search(lines[index])
            ) else 0)
            header_found = True
            break

    body: list[str] = []
    for line in lines[start:]:
        if _FOOTER.search(line):
            break
        # Once table rows have started, a number-only line is usually a subtotal,
        # tax amount, page number or footer reference rather than an inventory row.
        if body and not re.search(r"[A-Za-z]{2,}", line) and re.search(r"\d", line):
            break
        body.append(line)

    # If a table header was not detected, return the conservative pre-footer
    # region for common cash receipts that have no formal column headings.
    return body


def normalize_ocr_numeric_text(value: str) -> str:
    """Repair common OCR substitutions only inside digit-bounded numeric tokens."""
    value = str(value or "")
    value = re.sub(r"(?<=\d)[sS](?=\d)", "5", value)
    value = re.sub(r"(?<=\d)[oO](?=\d)", "0", value)
    # OCR often reads a decimal point as a colon or comma in prices.
    value = re.sub(r"(?<=\d)[:,](?=\d{2}(?:\D|$))", ".", value)
    return value


def choose_rate_amount(
    numeric_values: Iterable[float | None], quantity: float | None
) -> tuple[float | None, float | None]:
    """Choose a plausible rate/amount pair, preferring arithmetic agreement.

    Values are kept as OCR evidence; arithmetic is used only to choose between
    multiple candidate rate tokens, never to fabricate a missing amount.
    """
    values = [value for value in numeric_values if value is not None]
    if not values:
        return None, None
    if len(values) == 1:
        return values[0], None
    amount = values[-1]
    rate_candidates = values[:-1]
    if quantity is not None:
        matching = [
            rate for rate in rate_candidates
            if abs(quantity * rate - amount) <= max(0.05, abs(amount) * 0.015)
        ]
        if matching:
            return matching[-1], amount
    return rate_candidates[0], amount
