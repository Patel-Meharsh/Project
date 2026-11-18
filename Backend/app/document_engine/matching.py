"""Deterministic text normalization and fuzzy candidate ranking."""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Callable, Iterable


def normalize_alphanumeric(value: str | None) -> str:
    """Normalize OCR text for comparisons without changing its displayed value."""
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _tokens(value: str | None) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (value or "").lower()))


def similarity_score(query: str, candidate: str) -> float:
    """Combine character similarity, token overlap and substring evidence."""
    left = normalize_alphanumeric(query)
    right = normalize_alphanumeric(candidate)
    if not left or not right:
        return 0.0
    if left == right or left in right or right in left:
        return 1.0
    left_tokens = _tokens(query)
    right_tokens = _tokens(candidate)
    union = left_tokens | right_tokens
    token_score = len(left_tokens & right_tokens) / max(1, len(union))
    sequence_score = SequenceMatcher(None, left, right).ratio()
    return max(sequence_score, token_score)


def rank_candidates(
    query: str,
    candidates: Iterable[Any],
    name_getter: Callable[[Any], str | None],
    minimum_score: float = 0.0,
) -> list[dict[str, Any]]:
    """Return candidates sorted by deterministic similarity score."""
    ranked = []
    for candidate in candidates:
        name = name_getter(candidate) or ""
        score = similarity_score(query, name)
        if score >= minimum_score:
            ranked.append({"score": score, "candidate": candidate})
    ranked.sort(key=lambda entry: entry["score"], reverse=True)
    return ranked
