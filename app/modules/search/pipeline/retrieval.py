"""Wide semantic retrieval for the semantic-first food search pipeline."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._utils import (
    coerce_list as _coerce_list,
    dedupe as _dedupe,
    get_field as _get_field,
    normalize_text as _normalize_text,
)
from .types import ExtractedIntent, RetrievedFood

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


RETRIEVAL_EXPANSION_FACTOR = 5


def needs_retrieval_expansion(
    safe_count: int,
    return_limit: int,
    retrieval_mode: str,
) -> bool:
    """Mở rộng pool khi safety filter loại gần hết candidates semantic.

    Chỉ áp dụng cho semantic: lexical fallback đã quét toàn bộ bảng nên
    không còn gì để mở rộng.
    """
    return retrieval_mode == "semantic" and safe_count < return_limit


def build_semantic_query_text(query: str, intent: ExtractedIntent) -> str:
    """Mirror food embedding text without adding hard negative filters."""
    parts = [f"Mô tả: {query}"]

    if intent.include_dishes:
        parts.append(f"Món ăn: {', '.join(intent.include_dishes)}")

    preferred_ingredients = _dedupe(
        intent.preferred_ingredients + intent.medical_prefer_ingredients
    )
    if preferred_ingredients:
        parts.append(f"Nguyên liệu chính: {', '.join(preferred_ingredients)}")

    preferred_tags = _dedupe(intent.preferred_tags + intent.medical_prefer_tags)
    if preferred_tags:
        parts.append(f"Tính chất: {', '.join(preferred_tags)}")

    if intent.meal_context:
        parts.append(f"Bữa ăn phù hợp: {', '.join(intent.meal_context)}")

    if intent.occasion_context:
        parts.append(f"Ngữ cảnh sử dụng: {', '.join(intent.occasion_context)}")

    return ". ".join(parts)


def _cosine_distance_to_similarity(distance: Any) -> float:
    try:
        value = float(distance)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, 1.0 - (value / 2.0)))


async def semantic_retrieve_foods(
    db: "AsyncSession",
    query_vector: list[float],
    *,
    top_k: int,
    food_model: Any | None = None,
) -> list[RetrievedFood]:
    """Retrieve a wide unfiltered candidate pool by vector distance only."""
    if food_model is None:
        from app.models import Food as food_model
    from sqlalchemy import select
    from sqlalchemy.orm import defer

    distance_expr = food_model.embedding.cosine_distance(query_vector)
    stmt = (
        select(food_model, distance_expr.label("distance"))
        .options(defer(food_model.embedding))
        .where(food_model.embedding.is_not(None))
        .order_by(distance_expr)
        .limit(top_k)
    )
    rows = (await db.execute(stmt)).all()

    return [
        RetrievedFood(
            food=row[0],
            semantic_score=_cosine_distance_to_similarity(row.distance),
            retrieval_rank=index,
            retrieval_mode="semantic",
        )
        for index, row in enumerate(rows, 1)
    ]


def lexical_score_food(food: Any, query: str, intent: ExtractedIntent) -> float:
    """Small no-filter fallback when query embeddings are unavailable."""
    query_terms = {
        term for term in _normalize_text(query).split()
        if len(term) >= 3
    }
    food_text = " ".join([
        str(_get_field(food, "name", "")),
        str(_get_field(food, "description", "")),
        " ".join(_coerce_list(_get_field(food, "core_ingredients", []))),
        " ".join(_coerce_list(_get_field(food, "soft_tags", []))),
        " ".join(_coerce_list(_get_field(food, "taste_profile", []))),
        " ".join(_coerce_list(_get_field(food, "meal_context", []))),
        " ".join(_coerce_list(_get_field(food, "occasion_context", []))),
    ])
    normalized_food_text = _normalize_text(food_text)

    term_score = 0.0
    if query_terms:
        matched_terms = [term for term in query_terms if term in normalized_food_text]
        term_score = len(matched_terms) / max(1, len(query_terms))

    dish_score = 0.0
    name = _normalize_text(str(_get_field(food, "name", "")))
    if intent.include_dishes:
        dish_score = max(
            (1.0 if _normalize_text(dish) in name else 0.0)
            for dish in intent.include_dishes
        )

    context_values = {
        _normalize_text(value)
        for value in (
            _coerce_list(_get_field(food, "meal_context", []))
            + _coerce_list(_get_field(food, "occasion_context", []))
        )
    }
    context_targets = {
        _normalize_text(value)
        for value in (intent.meal_context + intent.occasion_context)
    }
    context_score = 0.2 if context_values.intersection(context_targets) else 0.0

    return max(0.0, min(1.0, term_score * 0.55 + dish_score * 0.25 + context_score))


async def lexical_retrieve_foods(
    db: "AsyncSession",
    query: str,
    intent: ExtractedIntent,
    *,
    top_k: int,
    food_model: Any | None = None,
) -> list[RetrievedFood]:
    """Fallback retrieval that still avoids DB filters and keeps recall wide."""
    if food_model is None:
        from app.models import Food as food_model
    from sqlalchemy import select
    from sqlalchemy.orm import defer

    rows = (
        (await db.execute(select(food_model).options(defer(food_model.embedding))))
        .scalars()
        .all()
    )
    scored_rows = [
        (food, lexical_score_food(food, query, intent))
        for food in rows
    ]
    scored_rows.sort(key=lambda item: item[1], reverse=True)
    return [
        RetrievedFood(
            food=food,
            semantic_score=score,
            retrieval_rank=index,
            retrieval_mode="lexical_fallback",
        )
        for index, (food, score) in enumerate(scored_rows[:top_k], 1)
    ]
