from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Iterable, TypeVar

T = TypeVar("T")


def normalize_name(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", (value or "").casefold())
    return re.sub(r"\s+", " ", cleaned).strip()


def _token_set(value: str) -> set[str]:
    normalized = normalize_name(value)
    return {token for token in normalized.split(" ") if token}


def _score_name(candidate: str, target: str) -> float:
    candidate_normalized = normalize_name(candidate)
    target_normalized = normalize_name(target)

    if not candidate_normalized or not target_normalized:
        return 0.0

    if candidate_normalized == target_normalized:
        return 1.0

    candidate_tokens = _token_set(candidate)
    target_tokens = _token_set(target)
    if candidate_tokens and target_tokens:
        if candidate_tokens.issubset(target_tokens) or target_tokens.issubset(candidate_tokens):
            return 0.97

        overlap = len(candidate_tokens & target_tokens) / max(len(candidate_tokens), len(target_tokens))
    else:
        overlap = 0.0

    ratio = SequenceMatcher(None, candidate_normalized, target_normalized).ratio()
    return max(ratio, overlap)


def find_best_name_match(target: str, options: Iterable[T], extractor, minimum_score: float = 0.8):
    best_item = None
    best_score = 0.0
    for item in options:
        score = _score_name(extractor(item), target)
        if score > best_score:
            best_item = item
            best_score = score

    if best_item is None or best_score < minimum_score:
        return None, 0.0

    return best_item, best_score


def find_best_book_match(target: str, options: Iterable[T], extractor, isbn: str | None = None):
    normalized_isbn = normalize_name(isbn or "")
    if normalized_isbn:
        for item in options:
            candidate_isbn = normalize_name(str(extractor(item, "isbn") or ""))
            if candidate_isbn == normalized_isbn:
                return item, 1.0

    return find_best_name_match(target, options, lambda item: extractor(item, "title"), minimum_score=0.75)