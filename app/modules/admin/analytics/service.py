from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, time, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.analytics.schemas import (
    AdminAIFeedbackItem,
    AdminDashboardStatsResponse,
    AdminFeedbackSummary,
    AdminTopItem,
)
from app.modules.chat.models import ChatMessage, ChatThread
from app.modules.foods.models import Food, Tag
from app.modules.query_logs.models import QueryLog
from app.modules.users.models import User, UserHealthProfile


def _today_start_utc() -> datetime:
    return datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)


def _extract_ai_insight_labels(ai_insight: dict[str, Any] | None) -> list[str]:
    if not isinstance(ai_insight, dict):
        return []
    labels: list[str] = []
    for key in ("include", "exclude", "prefer"):
        values = ai_insight.get(key)
        if isinstance(values, list):
            labels.extend(str(value) for value in values if value)
    return labels


def _extract_top_food_names(top_results: list[Any] | None) -> list[str]:
    if not isinstance(top_results, list):
        return []
    names: list[str] = []
    for item in top_results:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if name:
            names.append(str(name))
    return names


def _to_top_items(counter: Counter[str], *, limit: int) -> list[AdminTopItem]:
    return [
        AdminTopItem(name=name, count=count)
        for name, count in counter.most_common(limit)
    ]


async def get_dashboard_stats(db: AsyncSession, *, top_limit: int = 10) -> AdminDashboardStatsResponse:
    total_users = await db.scalar(select(func.count()).select_from(User)) or 0
    active_users = (
        await db.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True)))
        or 0
    )
    total_foods = await db.scalar(select(func.count()).select_from(Food)) or 0
    total_queries = await db.scalar(select(func.count()).select_from(QueryLog)) or 0
    queries_today = (
        await db.scalar(
            select(func.count())
            .select_from(QueryLog)
            .where(QueryLog.created_at >= _today_start_utc())
        )
        or 0
    )
    total_chat_threads = await db.scalar(select(func.count()).select_from(ChatThread)) or 0
    total_chat_messages = await db.scalar(select(func.count()).select_from(ChatMessage)) or 0
    likes = (
        await db.scalar(
            select(func.count())
            .select_from(ChatMessage)
            .where(ChatMessage.feedback == "like")
        )
        or 0
    )
    dislikes = (
        await db.scalar(
            select(func.count())
            .select_from(ChatMessage)
            .where(ChatMessage.feedback == "dislike")
        )
        or 0
    )

    health_counter: Counter[str] = Counter()
    profile_rows = await db.execute(
        select(UserHealthProfile.health_conditions, UserHealthProfile.allergies)
    )
    for health_conditions, allergies in profile_rows.all():
        health_counter.update(value for value in (health_conditions or []) if value)
        health_counter.update(value for value in (allergies or []) if value)

    medical_tag_rows = await db.execute(
        select(Tag.name).where(Tag.tag_type.in_(["DISEASE", "ALLERGY", "SYMPTON", "STATUS"]))
    )
    medical_tag_names = {name for (name,) in medical_tag_rows.all()}

    query_rows = await db.execute(select(QueryLog.ai_insight, QueryLog.top_results))
    recommended_counter: Counter[str] = Counter()
    for ai_insight, top_results in query_rows.all():
        health_counter.update(
            label
            for label in _extract_ai_insight_labels(ai_insight)
            if label in medical_tag_names
        )
        recommended_counter.update(_extract_top_food_names(top_results))

    return AdminDashboardStatsResponse(
        total_users=total_users,
        active_users=active_users,
        total_foods=total_foods,
        total_queries=total_queries,
        queries_today=queries_today,
        total_chat_threads=total_chat_threads,
        total_chat_messages=total_chat_messages,
        feedback=AdminFeedbackSummary(
            total=likes + dislikes,
            likes=likes,
            dislikes=dislikes,
        ),
        top_health_conditions=_to_top_items(health_counter, limit=top_limit),
        top_recommended_foods=_to_top_items(recommended_counter, limit=top_limit),
    )


async def list_ai_feedback(
    db: AsyncSession,
    *,
    feedback: str | None,
    limit: int,
    offset: int,
) -> tuple[int, list[AdminAIFeedbackItem]]:
    base_filters = [ChatMessage.role == "assistant", ChatMessage.feedback.is_not(None)]
    if feedback:
        base_filters.append(ChatMessage.feedback == feedback)

    total = (
        await db.scalar(
            select(func.count())
            .select_from(ChatMessage)
            .where(*base_filters)
        )
        or 0
    )

    stmt = (
        select(ChatMessage, ChatThread, User, QueryLog)
        .join(ChatThread, ChatThread.id == ChatMessage.thread_id)
        .join(User, User.id == ChatThread.user_id, isouter=True)
        .join(QueryLog, QueryLog.id == ChatMessage.query_log_id, isouter=True)
        .where(*base_filters)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = await db.execute(stmt)
    items: list[AdminAIFeedbackItem] = []
    for message, thread, user, query_log in rows.all():
        items.append(
            AdminAIFeedbackItem(
                message_id=message.id,
                thread_id=message.thread_id,
                query_log_id=message.query_log_id,
                feedback=message.feedback,
                assistant_content=message.content,
                food_results=message.food_results or [],
                created_at=message.created_at,
                user_id=user.id if user else None,
                user_email=user.email if user else None,
                thread_title=thread.title if thread else None,
                query=query_log.query if query_log else None,
            )
        )
    return total, items
