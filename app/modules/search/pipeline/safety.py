"""Critical safety guardrails for the semantic-first search pipeline."""

from __future__ import annotations

from typing import Any, Iterable

from app.modules.search.safety import detect_allergy_text_matches

from ._utils import (
    coerce_list as _coerce_list,
    dedupe,
    dish_phrase_matches as _dish_phrase_matches,
    get_field as _get_field,
    normalize_text,
    normalized_overlap as _normalized_overlap,
)
from .types import CriticalSafetyRules, RejectedFood, RetrievedFood, SafetyDecision

# Hard filter theo tag chỉ dành cho chống chỉ định TUYỆT ĐỐI về sinh học.
# Mirror quyết định legacy (app/modules/search/service.py:377-385):
# exclude_soft_tag của đa số bệnh trộn tag nguy hiểm cao với tag "nên tránh"
# (Nướng, Xào, Đậm đà...) — hard filter toàn bộ gây over-filtering.
# Tag "nên tránh" được xử lý bằng penalty trong scoring (medical_avoid_tags).
# Lưu ý ranh giới an toàn: với các bệnh chuyển hóa (Tiểu đường, Cao huyết áp...)
# chống chỉ định tuyệt đối nằm ở INGREDIENT KEYS (vẫn hard-filter ở orchestrator);
# tag mức món ăn chỉ mang tính khuyến nghị tuân thủ chế độ ăn.
CRITICAL_TAG_WHITELIST: dict[str, list[str]] = {
    "Gout": ["Hải sản"],
    "Gút": ["Hải sản"],  # alias tiếng Việt phòng hồ sơ nhập tay không qua enum UI
}
_CRITICAL_TAG_WHITELIST_NORMALIZED: dict[str, list[str]] = {
    normalize_text(condition): tags
    for condition, tags in CRITICAL_TAG_WHITELIST.items()
}


def select_critical_exclude_tags(health_constraints: list[str]) -> list[str]:
    """Chỉ trả về tag thuộc whitelist chống chỉ định tuyệt đối theo bệnh.

    Lookup không phân biệt hoa thường/dấu (hồ sơ user là free text).
    """
    critical: list[str] = []
    for condition in health_constraints or []:
        critical.extend(
            _CRITICAL_TAG_WHITELIST_NORMALIZED.get(normalize_text(condition), [])
        )
    return dedupe(critical)


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

    tag_matches = _normalized_overlap(
        get_food_scoring_tags(food),
        rules.critical_exclude_tags,
    )
    if tag_matches:
        return SafetyDecision(
            reject=True,
            reason="critical_tag_overlap",
            matched_values=tag_matches,
        )

    dish_matches = _dish_phrase_matches(
        rules.exclude_dishes,
        str(_get_field(food, "name", "")),
    )
    if dish_matches:
        return SafetyDecision(
            reject=True,
            reason="excluded_dish_name",
            matched_values=dish_matches,
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
