"""Shared helpers for the semantic-first search pipeline."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable


def get_field(food: Any, field_name: str, default: Any = None) -> Any:
    if isinstance(food, dict):
        return food.get(field_name, default)
    return getattr(food, field_name, default)


def coerce_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values or []:
        normalized = str(value or "").strip()
        if normalized and normalized.lower() not in seen:
            seen.add(normalized.lower())
            result.append(normalized)
    return result


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    text = text.replace("đ", "d").replace("Đ", "D").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalized_overlap(left: Iterable[str], right: Iterable[str]) -> list[str]:
    """Diacritic/case-insensitive overlap, giữ thứ tự và casing của `left`."""
    right_keys = {normalize_text(item) for item in (right or [])}
    matched: list[str] = []
    seen: set[str] = set()
    for value in left or []:
        key = normalize_text(value)
        if key and key in right_keys and key not in seen:
            seen.add(key)
            matched.append(str(value))
    return matched


def phrase_matches(needles: Iterable[str], haystack: str) -> list[str]:
    normalized_haystack = f" {normalize_text(haystack)} "
    matched: list[str] = []
    for needle in needles or []:
        normalized_needle = normalize_text(needle)
        if normalized_needle and f" {normalized_needle} " in normalized_haystack:
            matched.append(str(needle))
    return matched


def has_diacritics(value: str) -> bool:
    """True nếu chuỗi chứa dấu tiếng Việt (combining marks hoặc đ/Đ)."""
    text = str(value or "")
    if "đ" in text or "Đ" in text:
        return True
    decomposed = unicodedata.normalize("NFD", text)
    return any(unicodedata.category(char) == "Mn" for char in decomposed)


def soft_normalize_text(value: str) -> str:
    """Lowercase + gọn khoảng trắng/ký tự lạ nhưng GIỮ dấu tiếng Việt."""
    text = str(value or "").lower()
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    text = text.replace("_", " ")
    return re.sub(r"\s+", " ", text).strip()


def dish_phrase_matches(needles: Iterable[str], haystack: str) -> list[str]:
    """Word-boundary match cho tên món, tránh false positive do bỏ dấu.

    Needle CÓ dấu ("phở") → so khớp giữ dấu, không match "phô mai".
    Needle KHÔNG dấu ("pho bo") → so khớp bỏ dấu như phrase_matches.
    """
    soft_haystack = f" {soft_normalize_text(haystack)} "
    hard_haystack = f" {normalize_text(haystack)} "
    matched: list[str] = []
    for needle in needles or []:
        if has_diacritics(needle):
            normalized_needle = soft_normalize_text(needle)
            if normalized_needle and f" {normalized_needle} " in soft_haystack:
                matched.append(str(needle))
        else:
            normalized_needle = normalize_text(needle)
            if normalized_needle and f" {normalized_needle} " in hard_haystack:
                matched.append(str(needle))
    return matched
