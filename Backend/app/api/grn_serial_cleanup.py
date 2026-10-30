"""Pure helpers for removing invoice serial numbers from item descriptions.

No database, OCR or FastAPI imports, so these helpers can be unit-tested on their own
and reused by the text, image and PDF extraction paths.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Callable, Iterable


# A leading number followed by one of these is a product size/spec, not a row serial.
_UNIT_START = re.compile(
    r"^(?:W|WATT|WATTS|V|VOLT|VOLTS|L|LTR|LITRE|LITER|ML|MM|CM|MTR|KG|GM|GMS|"
    r"PCS|PC|NOS|INCH|FT|PIN)\b",
    re.I,
)


def _squash(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip(" .:| -\t")


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _serial_number(serial_text: str | None) -> int | None:
    match = re.search(r"\d{1,3}", serial_text or "")
    return int(match.group(0)) if match else None


def strip_leading_serial(
    description: str,
    expected_serial: int | None = None,
    serial_text: str | None = None,
) -> str:
    """Remove a separate leading serial only when confirmed by invoice sequence."""
    text = _squash(description)
    known = _serial_number(serial_text)
    if known is None:
        known = expected_serial
    if known is None:
        return text
    match = re.match(r"^(\d{1,3})\s+(?=[A-Za-z0-9])", text)
    if not match or int(match.group(1)) != known:
        return text
    remainder = text[match.end():]
    if _UNIT_START.match(remainder) or not re.search(r"[A-Za-z]", remainder):
        return text
    return remainder.strip(" .:| -\t")


def glued_serial_variant(description: str, expected_serial: int | None) -> str | None:
    """Return a candidate without an OCR-glued serial, e.g. '236W CFL' -> '36W CFL'."""
    if expected_serial is None:
        return None
    text = _squash(description)
    serial = str(expected_serial)
    match = re.match(rf"^{re.escape(serial)}(?=(?:\d{{1,3}}\s*[A-Za-z]))(\d{{1,3}}\s*[A-Za-z].*)$", text)
    if not match:
        return None
    candidate = match.group(1).strip()
    return candidate if len(_norm(candidate)) >= 3 else None


def resolve_description(
    description: str,
    expected_serial: int | None = None,
    serial_text: str | None = None,
    score_fn: Callable[[str], float] | None = None,
    margin: float = 0.05,
) -> tuple[str, str | None]:
    """Clean a description and return (description, optional review warning)."""
    cleaned = strip_leading_serial(description, expected_serial, serial_text)
    known = _serial_number(serial_text)
    if known is None:
        known = expected_serial
    variant = glued_serial_variant(cleaned, known)
    if not variant:
        return cleaned, None
    if score_fn is not None and score_fn(variant) >= score_fn(cleaned) + margin:
        return variant, None
    return cleaned, f"item name may start with the serial number ({known}); check '{variant}'"


def suggest_master_items(
    description: str,
    masters: Iterable[Any],
    limit: int = 3,
    min_score: float = 0.5,
) -> list[dict[str, Any]]:
    """Return the strongest Item Master candidates for a possibly misread name."""
    target = _norm(description)
    if not target:
        return []
    target_tokens = set(re.findall(r"[a-z0-9]+", description.lower()))
    scored: list[dict[str, Any]] = []
    for item in masters:
        name = (getattr(item, "name", "") or "").strip()
        code = (getattr(item, "code", "") or "").strip()
        if not name or not code:
            continue
        name_norm = _norm(name)
        ratio = SequenceMatcher(None, target, name_norm).ratio()
        name_tokens = set(re.findall(r"[a-z0-9]+", name.lower()))
        overlap = len(target_tokens & name_tokens) / max(1, len(target_tokens | name_tokens))
        score = max(ratio, overlap)
        if score >= min_score:
            scored.append({"code": code, "name": name, "score": round(score, 3)})
    scored.sort(key=lambda entry: entry["score"], reverse=True)
    return scored[:limit]
