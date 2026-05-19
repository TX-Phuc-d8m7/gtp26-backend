"""Utilities for persisting food search explainability logs."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import QueryLog
from app.schemas import AIInsight, FoodResult


def _serialize_food_result(food: FoodResult) -> dict[str, Any]:
    """Create a compact JSON snapshot for query logs without large raw fields or embeddings."""
    return {
        "id": str(food.id),
        "name": food.name,
        "matchScore": food.matchScore,
        "reason": food.reason,
        "soft_tags": food.soft_tags,
        "taste_profile": food.taste_profile,
        "meal_context": food.meal_context,
        "occasion_context": food.occasion_context,
    }


async def create_query_log(
    db: AsyncSession,
    *,
    query: str,
    ai_insight: AIInsight,
    final_exclude_ings: list[str],
    exclude_ingredient_keys: list[str],
    user_include_tags: list[str],
    user_exclude_tags: list[str],
    candidate_count: int,
    filtered_count: int,
    scored_count: int,
    returned_count: int,
    excluded_summary: dict[str, Any],
    retrieval_notes: list[str],
    top_results: list[FoodResult],
    warning_message: str | None,
    user_id: uuid.UUID | None = None,
    thread_id: uuid.UUID | None = None,
) -> QueryLog:
    """Persist one search trace for admin/debug explainability."""
    log = QueryLog(
        user_id=user_id,
        thread_id=thread_id,
        query=query,
        ai_insight=ai_insight.model_dump(),
        final_exclude_ings=final_exclude_ings,
        exclude_ingredient_keys=exclude_ingredient_keys,
        user_include_tags=user_include_tags,
        user_exclude_tags=user_exclude_tags,
        candidate_count=candidate_count,
        filtered_count=filtered_count,
        scored_count=scored_count,
        returned_count=returned_count,
        excluded_summary=excluded_summary,
        retrieval_notes=retrieval_notes,
        top_results=[_serialize_food_result(food) for food in top_results],
        warning_message=warning_message,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return log
