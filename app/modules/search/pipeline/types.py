"""Typed contracts for the semantic-first search pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExtractedIntent:
    health_constraints: list[str] = field(default_factory=list)
    include_dishes: list[str] = field(default_factory=list)
    exclude_dishes: list[str] = field(default_factory=list)
    preferred_ingredients: list[str] = field(default_factory=list)
    disliked_ingredients: list[str] = field(default_factory=list)
    preferred_ingredient_keys: list[str] = field(default_factory=list)
    disliked_ingredient_keys: list[str] = field(default_factory=list)
    preferred_tags: list[str] = field(default_factory=list)
    disliked_tags: list[str] = field(default_factory=list)
    meal_context: list[str] = field(default_factory=list)
    occasion_context: list[str] = field(default_factory=list)
    medical_prefer_tags: list[str] = field(default_factory=list)
    medical_prefer_ingredients: list[str] = field(default_factory=list)


@dataclass
class RetrievedFood:
    food: Any
    semantic_score: float
    retrieval_rank: int | None = None
    retrieval_mode: str = "semantic"


@dataclass
class CriticalSafetyRules:
    health_constraints: list[str] = field(default_factory=list)
    excluded_ingredient_keys: list[str] = field(default_factory=list)
    critical_exclude_tags: list[str] = field(default_factory=list)
    allergy_constraints: list[str] = field(default_factory=list)
    allergy_exclude_ingredients: list[str] = field(default_factory=list)


@dataclass
class SafetyDecision:
    reject: bool
    reason: str | None = None
    matched_values: list[str] = field(default_factory=list)


@dataclass
class RejectedFood:
    candidate: RetrievedFood
    decision: SafetyDecision


@dataclass
class ScoreBreakdown:
    semantic_score: float
    tag_bonus: float = 0.0
    context_bonus: float = 0.0
    preference_bonus: float = 0.0
    medical_bonus: float = 0.0
    dislike_penalty: float = 0.0
    dish_penalty: float = 0.0
    final_score: float = 0.0
    matched_signals: list[str] = field(default_factory=list)


@dataclass
class ScoredFood:
    food: Any
    semantic_score: float
    final_score: float
    score_breakdown: ScoreBreakdown
    reason_signals: list[str] = field(default_factory=list)
    retrieval_rank: int | None = None
    retrieval_mode: str = "semantic"
