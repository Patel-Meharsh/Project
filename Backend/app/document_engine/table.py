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
    r"amount\s+chargeable|total|cgst|sgst|igst|round\s*off|bank\s+details|"
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
            # Exclude the header itself. If quantity/rate headings are on
            # the following OCR line, exclude that continuation too.
            start = index + 1
            if not (_QTY_WORDS.search(lines[index]) and _RATE_WORDS.search(lines[index])):
                if index + 1 < len(lines) and (
                    _QTY_WORDS.search(lines[index + 1]) or _RATE_WORDS.search(lines[index + 1])
                ):
                    start = index + 2
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


def merge_invoice_continuation_lines(
    lines: Iterable[str], unit_pattern: str
) -> list[str]:
    """Attach wrapped descriptions to the correct adjacent invoice row.

    A description-only line between two numbered rows belongs to the previous
    row (for example, a product variant such as "Mogra" or "Lemon"). A
    description-only line immediately before its numeric row is joined forward.
    """
    source = [re.sub(r"\s+", " ", str(line)).strip() for line in lines if str(line).strip()]
    merged: list[str] = []

    def has_quantity_unit(line: str) -> bool:
        pattern = re.compile(
            rf"(?<![A-Za-z])\d[\d,]*(?:\.\d{{1,2}})?\s*{unit_pattern}\b",
            re.I,
        )
        # A product specification such as "15 W LED" is not a billed
        # quantity. Require the candidate unit to be followed by rate/amount
        # evidence, and inspect rightmost matches first to prefer the Qty column.
        for match in reversed(list(pattern.finditer(line))):
            trailing_numbers = re.findall(
                r"\d[\d,]*(?:\.\d{1,2})?", line[match.end():]
            )
            if len(trailing_numbers) >= 2:
                return True
        return False

    def starts_numbered_item(line: str) -> bool:
        return bool(re.match(r"^\s*[\W_]*\d{1,3}\s*[.)-]?\s+[A-Za-z]", line))

    for index, line in enumerate(source):
        current_has_values = has_quantity_unit(line)
        previous_has_values = has_quantity_unit(merged[-1]) if merged else False
        next_index = index + 1
        while (
            next_index < len(source)
            and next_index - index <= 3
            and not re.search(r"[A-Za-z]{2,}", source[next_index])
        ):
            next_index += 1
        next_is_new_item = (
            next_index < len(source) and starts_numbered_item(source[next_index])
        )

        if merged and previous_has_values and not current_has_values and next_is_new_item:
            merged[-1] = f"{merged[-1]} {line}".strip()
            continue

        if merged and current_has_values and not previous_has_values:
            previous = merged[-1]
            if (
                re.search(r"[A-Za-z]", previous)
                and not re.search(
                    r"\b(?:invoice|gstin|cgst|sgst|igst|total|round off|"
                    r"description|quantity|amount|dated|vendor|supplier|party|tax invoice)\b",
                    previous, re.I,
                )
            ):
                merged[-1] = f"{previous} {line}".strip()
                continue

        merged.append(line)

    return merged


def normalize_ocr_numeric_text(value: str) -> str:
    """Repair common OCR substitutions only inside digit-bounded numeric tokens."""
    value = str(value or "")
    value = re.sub(r"(?<=[\d.])[sS](?=\d)", "5", value)
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
