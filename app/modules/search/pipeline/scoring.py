"""Soft scoring and deterministic reranking for semantic-first search."""

from __future__ import annotations

from typing import Any

from ._utils import (
    coerce_list as _coerce_list,
    get_field as _get_field,
    normalized_overlap as _overlap,
    phrase_matches as _phrase_matches,
)
from .safety import get_food_scoring_tags
from .types import ExtractedIntent, RetrievedFood, ScoreBreakdown, ScoredFood

MEAL_CONTEXT_BONUS = 0.02
OCCASION_CONTEXT_BONUS = 0.02
PREFERRED_TAG_BONUS = 0.02
PREFERRED_INGREDIENT_BONUS = 0.04
MEDICAL_PREFER_BONUS = 0.02
INCLUDE_DISH_BONUS = 0.05

DISLIKED_INGREDIENT_PENALTY = 0.15
DISLIKED_TAG_PENALTY = 0.10
MEDICAL_AVOID_PENALTY = 0.12  # mạnh hơn disliked_tag (0.10): lý do y khoa > sở thích

MAX_TOTAL_BONUS = 0.12
MAX_PENALTY = 0.30


def _combined_food_text(food: Any) -> str:
    parts = [
        _get_field(food, "name", ""),
        _get_field(food, "description", ""),
        " ".join(_coerce_list(_get_field(food, "core_ingredients", []))),
        " ".join(_coerce_list(_get_field(food, "raw_ingredients", []))),
    ]
    return " ".join(str(part or "") for part in parts)


def _clamp_score(value: float) -> float:
    return max(0.0, min(1.0, value))


def score_candidate(candidate: RetrievedFood, intent: ExtractedIntent) -> ScoredFood:
    """Apply small contextual bonuses and medium preference penalties."""
    food = candidate.food
    semantic_score = _clamp_score(float(candidate.semantic_score or 0.0))
    breakdown = ScoreBreakdown(semantic_score=semantic_score)
    signals: list[str] = []

    meal_matches = _overlap(_coerce_list(_get_field(food, "meal_context", [])), intent.meal_context)
    if meal_matches:
        breakdown.context_bonus += min(0.04, len(meal_matches) * MEAL_CONTEXT_BONUS)
        signals.append("meal_context_match")

    occasion_matches = _overlap(
        _coerce_list(_get_field(food, "occasion_context", [])),
        intent.occasion_context,
    )
    if occasion_matches:
        breakdown.context_bonus += min(0.04, len(occasion_matches) * OCCASION_CONTEXT_BONUS)
        signals.append("occasion_context_match")

    food_tags = get_food_scoring_tags(food)
    preferred_tag_matches = _overlap(food_tags, intent.preferred_tags)
    if preferred_tag_matches:
        breakdown.tag_bonus += min(0.06, len(preferred_tag_matches) * PREFERRED_TAG_BONUS)
        signals.append("preferred_tag_match")

    medical_tag_matches = _overlap(food_tags, intent.medical_prefer_tags)
    if medical_tag_matches:
        breakdown.medical_bonus += min(0.06, len(medical_tag_matches) * MEDICAL_PREFER_BONUS)
        signals.append("medical_prefer_tag_match")

    ingredient_key_matches = _overlap(
        _coerce_list(_get_field(food, "core_ingredient_keys", [])),
        intent.preferred_ingredient_keys,
    )
    if ingredient_key_matches:
        breakdown.preference_bonus += min(0.08, len(ingredient_key_matches) * PREFERRED_INGREDIENT_BONUS)
        signals.append("preferred_ingredient_match")

    dish_name = str(_get_field(food, "name", ""))
    include_dish_matches = _phrase_matches(intent.include_dishes, dish_name)
    if include_dish_matches:
        breakdown.preference_bonus += INCLUDE_DISH_BONUS
        signals.append("include_dish_match")

    disliked_ingredient_matches = _overlap(
        _coerce_list(_get_field(food, "core_ingredient_keys", [])),
        intent.disliked_ingredient_keys,
    )
    if disliked_ingredient_matches:
        breakdown.dislike_penalty += min(0.24, len(disliked_ingredient_matches) * DISLIKED_INGREDIENT_PENALTY)
        signals.append("disliked_ingredient_penalty")

    disliked_tag_matches = _overlap(food_tags, intent.disliked_tags)
    if disliked_tag_matches:
        breakdown.dislike_penalty += min(0.20, len(disliked_tag_matches) * DISLIKED_TAG_PENALTY)
        signals.append("disliked_tag_penalty")

    medical_avoid_matches = _overlap(food_tags, intent.medical_avoid_tags)
    if medical_avoid_matches:
        breakdown.medical_penalty += min(0.24, len(medical_avoid_matches) * MEDICAL_AVOID_PENALTY)
        signals.append("medical_avoid_tag_penalty")

    combined_text = _combined_food_text(food)
    disliked_ingredient_text_matches = _phrase_matches(intent.disliked_ingredients, combined_text)
    if disliked_ingredient_text_matches and not disliked_ingredient_matches:
        breakdown.dislike_penalty += DISLIKED_INGREDIENT_PENALTY
        signals.append("disliked_ingredient_text_penalty")

    bonus = min(
        MAX_TOTAL_BONUS,
        breakdown.tag_bonus
        + breakdown.context_bonus
        + breakdown.preference_bonus
        + breakdown.medical_bonus,
    )
    penalty = min(
        MAX_PENALTY,
        breakdown.dislike_penalty + breakdown.medical_penalty,
    )
    breakdown.final_score = _clamp_score(semantic_score + bonus - penalty)
    breakdown.matched_signals = signals

    return ScoredFood(
        food=food,
        semantic_score=semantic_score,
        final_score=breakdown.final_score,
        score_breakdown=breakdown,
        reason_signals=signals,
        retrieval_rank=candidate.retrieval_rank,
        retrieval_mode=candidate.retrieval_mode,
    )


def rank_candidates(
    candidates: list[RetrievedFood],
    intent: ExtractedIntent,
    *,
    limit: int = 5,
    min_score: float = 0.0,
) -> list[ScoredFood]:
    scored = [
        score_candidate(candidate, intent)
        for candidate in candidates
    ]
    filtered = [
        item for item in scored
        if item.final_score >= min_score
    ]
    filtered.sort(
        key=lambda item: (
            item.final_score,
            item.semantic_score,
            -(item.retrieval_rank if item.retrieval_rank is not None else 10_000),
        ),
        reverse=True,
    )
    return filtered[:limit]
