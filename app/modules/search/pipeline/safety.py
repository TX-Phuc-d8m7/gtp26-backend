"""Critical safety guardrails for the semantic-first search pipeline."""

from __future__ import annotations

from typing import Any, Iterable

from app.modules.search.safety import detect_allergy_text_matches

from .types import CriticalSafetyRules, RejectedFood, RetrievedFood, SafetyDecision


def _get_field(food: Any, field_name: str, default: Any = None) -> Any:
    if isinstance(food, dict):
        return food.get(field_name, default)
    return getattr(food, field_name, default)


def _coerce_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _ordered_overlap(left: Iterable[str], right: Iterable[str]) -> list[str]:
    right_values = {str(item) for item in (right or [])}
    return [str(item) for item in (left or []) if str(item) in right_values]


def get_food_scoring_tags(food: Any) -> list[str]:
    """Return all non-medical tags that can participate in scoring or safety."""
    tags: list[str] = []
    for field_name in (
        "soft_tags",
        "taste_profile",
        "meal_context",
        "occasion_context",
    ):
        tags.extend(_coerce_list(_get_field(food, field_name, [])))
    return tags


def evaluate_critical_safety(
    food: Any,
    rules: CriticalSafetyRules,
) -> SafetyDecision:
    """Reject a food only for critical health or allergy constraints."""
    ingredient_matches = _ordered_overlap(
        _coerce_list(_get_field(food, "core_ingredient_keys", [])),
        rules.excluded_ingredient_keys,
    )
    if ingredient_matches:
        return SafetyDecision(
            reject=True,
            reason="critical_ingredient_key_overlap",
            matched_values=ingredient_matches,
        )

    tag_matches = _ordered_overlap(
        get_food_scoring_tags(food),
        rules.critical_exclude_tags,
    )
    if tag_matches:
        return SafetyDecision(
            reject=True,
            reason="critical_tag_overlap",
            matched_values=tag_matches,
        )

    allergy_matches = detect_allergy_text_matches(
        food,
        rules.allergy_constraints,
        rules.allergy_exclude_ingredients,
    )
    if allergy_matches:
        matched_values = [
            f"{match.get('allergy')}: {match.get('phrase')}"
            for match in allergy_matches
            if match.get("allergy") or match.get("phrase")
        ]
        return SafetyDecision(
            reject=True,
            reason="allergy_text_match",
            matched_values=matched_values,
        )

    return SafetyDecision(reject=False)


def apply_critical_safety_filter(
    candidates: list[RetrievedFood],
    rules: CriticalSafetyRules,
) -> tuple[list[RetrievedFood], list[RejectedFood]]:
    """Split retrieved candidates into medically safe and rejected pools."""
    safe_candidates: list[RetrievedFood] = []
    rejected_candidates: list[RejectedFood] = []

    for candidate in candidates:
        decision = evaluate_critical_safety(candidate.food, rules)
        if decision.reject:
            rejected_candidates.append(RejectedFood(candidate=candidate, decision=decision))
        else:
            safe_candidates.append(candidate)

    return safe_candidates, rejected_candidates
