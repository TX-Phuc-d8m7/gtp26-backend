"""Intent mapping from the existing supervisor/rule payload to pipeline types."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .types import ExtractedIntent


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values or []:
        normalized = str(value or "").strip()
        if normalized and normalized.lower() not in seen:
            seen.add(normalized.lower())
            result.append(normalized)
    return result


def _generate_keys(
    values: list[str],
    *,
    key_generator: Callable[..., list[str]] | None = None,
    extra_rules: list[dict[str, Any]] | None = None,
) -> list[str]:
    if not values or key_generator is None:
        return []
    return _dedupe(key_generator(values, extra_rules=extra_rules))


def intent_from_conflict_payload(
    payload: dict[str, Any],
    *,
    category_splitter: Callable[[list[str]], dict[str, list[str]]] | None = None,
    key_generator: Callable[..., list[str]] | None = None,
    extra_rules: list[dict[str, Any]] | None = None,
) -> ExtractedIntent:
    """Build the new scoring intent while preserving legacy extraction output."""
    user_include_tags = _dedupe(payload.get("user_include_tags", []))
    user_exclude_tags = _dedupe(payload.get("user_exclude_tags", []))
    grouped_include = (
        category_splitter(user_include_tags)
        if category_splitter
        else {"soft_tags": user_include_tags, "meal_context": [], "occasion_context": []}
    )
    grouped_exclude = (
        category_splitter(user_exclude_tags)
        if category_splitter
        else {"soft_tags": user_exclude_tags, "meal_context": [], "occasion_context": []}
    )

    preferred_ingredients = _dedupe(payload.get("final_include_ings", []))
    disliked_ingredients = _dedupe(payload.get("user_dislike_ings", []))
    medical_prefer_ingredients = _dedupe(payload.get("medical_prefer_ings", []))

    return ExtractedIntent(
        health_constraints=_dedupe(payload.get("symptoms", [])),
        include_dishes=_dedupe(payload.get("user_include_dishes", [])),
        exclude_dishes=_dedupe(payload.get("user_exclude_dishes", [])),
        preferred_ingredients=preferred_ingredients,
        disliked_ingredients=disliked_ingredients,
        preferred_ingredient_keys=_generate_keys(
            preferred_ingredients + medical_prefer_ingredients,
            key_generator=key_generator,
            extra_rules=extra_rules,
        ),
        disliked_ingredient_keys=_generate_keys(
            disliked_ingredients,
            key_generator=key_generator,
            extra_rules=extra_rules,
        ),
        preferred_tags=_dedupe(
            grouped_include.get("soft_tags", [])
            + grouped_include.get("taste_profile", [])
        ),
        disliked_tags=_dedupe(
            grouped_exclude.get("soft_tags", [])
            + grouped_exclude.get("taste_profile", [])
            + grouped_exclude.get("meal_context", [])
            + grouped_exclude.get("occasion_context", [])
        ),
        meal_context=_dedupe(grouped_include.get("meal_context", [])),
        occasion_context=_dedupe(grouped_include.get("occasion_context", [])),
        medical_prefer_tags=_dedupe(payload.get("medical_prefer_tags", [])),
        medical_prefer_ingredients=medical_prefer_ingredients,
    )
