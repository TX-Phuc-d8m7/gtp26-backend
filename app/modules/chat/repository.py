"""Repository layer cho chat module.

File này chỉ chứa các thao tác DB thuần cho thread/message. Service layer chịu
trách nhiệm điều phối use-case, commit/refresh và mapping sang response schema.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.chat.models import ChatMessage, ChatThread, FoodRecommendationFeedback


@dataclass(frozen=True)
class ThreadSummary:
    thread: ChatThread
    message_count: int = 0
    last_message_at: datetime | None = None


async def list_thread_summaries(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    limit: int,
    offset: int,
    q: str | None = None,
    pinned_first: bool = True,
) -> tuple[int, list[ThreadSummary]]:
    """Lấy danh sách thread kèm số tin nhắn và thời điểm tin cuối."""
    base_where = [
        ChatThread.user_id == user_id,
        ChatThread.is_deleted.is_(False),
    ]
    if q:
        base_where.append(ChatThread.title.ilike(f"%{q.strip()}%"))

    count_stmt = select(func.count()).select_from(ChatThread).where(*base_where)
    total = (await db.execute(count_stmt)).scalar_one()

    msg_stats = (
        select(
            ChatMessage.thread_id,
            func.count(ChatMessage.id).label("msg_count"),
            func.max(ChatMessage.created_at).label("last_msg_at"),
        )
        .group_by(ChatMessage.thread_id)
        .subquery()
    )

    data_stmt = (
        select(
            ChatThread,
            func.coalesce(msg_stats.c.msg_count, 0).label("message_count"),
            msg_stats.c.last_msg_at.label("last_message_at"),
        )
        .outerjoin(msg_stats, ChatThread.id == msg_stats.c.thread_id)
        .where(*base_where)
    )

    if pinned_first:
        data_stmt = data_stmt.order_by(
            ChatThread.is_pinned.desc(),
            ChatThread.updated_at.desc(),
        )
    else:
        data_stmt = data_stmt.order_by(ChatThread.updated_at.desc())

    rows = (await db.execute(data_stmt.limit(limit).offset(offset))).all()
    return total, [
        ThreadSummary(
            thread=row.ChatThread,
            message_count=row.message_count,
            last_message_at=row.last_message_at,
        )
        for row in rows
    ]


async def create_thread(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    title: str | None,
) -> ChatThread:
    """Tạo thread mới nhưng chưa commit."""
    thread = ChatThread(user_id=user_id, title=title)
    db.add(thread)
    await db.flush()
    return thread


async def get_thread_summary(
    db: AsyncSession,
    *,
    thread_id: uuid.UUID,
    user_id: uuid.UUID,
) -> ThreadSummary | None:
    """Lấy metadata thread kèm thống kê message."""
    msg_stats = (
        select(
            ChatMessage.thread_id,
            func.count(ChatMessage.id).label("msg_count"),
            func.max(ChatMessage.created_at).label("last_msg_at"),
        )
        .where(ChatMessage.thread_id == thread_id)
        .group_by(ChatMessage.thread_id)
        .subquery()
    )

    stmt = (
        select(
            ChatThread,
            func.coalesce(msg_stats.c.msg_count, 0).label("message_count"),
            msg_stats.c.last_msg_at.label("last_message_at"),
        )
        .outerjoin(msg_stats, ChatThread.id == msg_stats.c.thread_id)
        .where(
            ChatThread.id == thread_id,
            ChatThread.user_id == user_id,
            ChatThread.is_deleted.is_(False),
        )
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        return None
    return ThreadSummary(
        thread=row.ChatThread,
        message_count=row.message_count,
        last_message_at=row.last_message_at,
    )


async def get_thread_for_user(
    db: AsyncSession,
    *,
    thread_id: uuid.UUID,
    user_id: uuid.UUID,
) -> ChatThread | None:
    """Lấy thread đang hoạt động thuộc user."""
    return (await db.execute(
        select(ChatThread).where(
            ChatThread.id == thread_id,
            ChatThread.user_id == user_id,
            ChatThread.is_deleted.is_(False),
        )
    )).scalar_one_or_none()


def apply_thread_updates(
    thread: ChatThread,
    *,
    title: str | None = None,
    is_pinned: bool | None = None,
) -> None:
    """Cập nhật metadata thread trên model đã load."""
    if title is not None:
        thread.title = title
    if is_pinned is not None:
        thread.is_pinned = is_pinned
    thread.updated_at = func.now()


def soft_delete_thread(thread: ChatThread) -> None:
    """Đánh dấu thread là đã xóa."""
    thread.is_deleted = True


async def list_messages(
    db: AsyncSession,
    *,
    thread_id: uuid.UUID,
    limit: int,
    offset: int,
) -> tuple[int, list[ChatMessage]]:
    """Lấy messages trong thread theo thứ tự timeline."""
    count_stmt = select(func.count()).select_from(ChatMessage).where(
        ChatMessage.thread_id == thread_id
    )
    total = (await db.execute(count_stmt)).scalar_one()

    data_stmt = (
        select(ChatMessage)
        .where(ChatMessage.thread_id == thread_id)
        .order_by(ChatMessage.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    messages = (await db.execute(data_stmt)).scalars().all()
    return total, list(messages)


async def create_message(
    db: AsyncSession,
    *,
    thread_id: uuid.UUID,
    role: str,
    content: str,
    query_log_id: uuid.UUID | None = None,
    food_results: list[dict[str, Any]] | None = None,
    structured_result: dict[str, Any] | None = None,
) -> ChatMessage:
    """Tạo chat message nhưng chưa commit."""
    message = ChatMessage(
        thread_id=thread_id,
        role=role,
        content=content,
        query_log_id=query_log_id,
        food_results=food_results,
        structured_result=structured_result,
    )
    db.add(message)
    await db.flush()
    return message


async def load_recent_messages(
    db: AsyncSession,
    *,
    thread_id: uuid.UUID,
    exclude_msg_id: uuid.UUID,
    limit: int,
) -> list[ChatMessage]:
    """Lấy các message gần nhất, loại trừ message hiện tại."""
    return list((await db.execute(
        select(ChatMessage)
        .where(
            ChatMessage.thread_id == thread_id,
            ChatMessage.id != exclude_msg_id,
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )).scalars().all())


async def get_last_assistant_with_food_results(
    db: AsyncSession,
    *,
    thread_id: uuid.UUID,
    exclude_msg_id: uuid.UUID,
) -> ChatMessage | None:
    """Lấy assistant message gần nhất có food_results."""
    return (await db.execute(
        select(ChatMessage)
        .where(
            ChatMessage.thread_id == thread_id,
            ChatMessage.id != exclude_msg_id,
            ChatMessage.role == "assistant",
            ChatMessage.food_results.is_not(None),
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()


async def get_assistant_message(
    db: AsyncSession,
    *,
    thread_id: uuid.UUID,
    message_id: uuid.UUID,
) -> ChatMessage | None:
    """Lấy assistant message theo id trong thread."""
    return (await db.execute(
        select(ChatMessage).where(
            ChatMessage.id == message_id,
            ChatMessage.thread_id == thread_id,
            ChatMessage.role == "assistant",
        )
    )).scalar_one_or_none()


async def get_user_message(
    db: AsyncSession,
    *,
    thread_id: uuid.UUID,
    message_id: uuid.UUID,
) -> ChatMessage | None:
    """Lấy user message theo id trong thread."""
    return (await db.execute(
        select(ChatMessage).where(
            ChatMessage.id == message_id,
            ChatMessage.thread_id == thread_id,
            ChatMessage.role == "user",
        )
    )).scalar_one_or_none()


async def get_previous_user_message(
    db: AsyncSession,
    *,
    thread_id: uuid.UUID,
    before_created_at: datetime,
) -> ChatMessage | None:
    """Lấy user message liền trước một thời điểm trong thread."""
    return (await db.execute(
        select(ChatMessage)
        .where(
            ChatMessage.thread_id == thread_id,
            ChatMessage.role == "user",
            ChatMessage.created_at < before_created_at,
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()


async def delete_message(db: AsyncSession, message: ChatMessage) -> None:
    """Xóa một message đã load."""
    await db.delete(message)
    await db.flush()


async def delete_messages_after(
    db: AsyncSession,
    *,
    thread_id: uuid.UUID,
    created_at: datetime,
) -> None:
    """Xóa tất cả message sau một mốc thời gian trong thread."""
    await db.execute(
        delete(ChatMessage).where(
            ChatMessage.thread_id == thread_id,
            ChatMessage.created_at > created_at,
        )
    )
    await db.flush()


def update_message_content_and_context(
    message: ChatMessage,
    *,
    content: str,
    structured_result: dict[str, Any] | None = None,
    update_structured_result: bool = False,
) -> None:
    """Cập nhật nội dung và tùy chọn structured_result cho message đã load."""
    message.content = content
    if update_structured_result:
        message.structured_result = structured_result


def set_message_feedback(message: ChatMessage, feedback: str | None) -> None:
    """Cập nhật feedback trên assistant message đã load."""
    message.feedback = feedback


async def list_food_recommendation_feedbacks(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    message_ids: list[uuid.UUID],
) -> list[FoodRecommendationFeedback]:
    """Lấy food-level feedback của user cho một nhóm assistant message."""
    if not message_ids:
        return []

    return list((await db.execute(
        select(FoodRecommendationFeedback)
        .where(
            FoodRecommendationFeedback.user_id == user_id,
            FoodRecommendationFeedback.assistant_message_id.in_(message_ids),
        )
    )).scalars().all())


async def get_food_recommendation_feedback(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    assistant_message_id: uuid.UUID,
    food_id: uuid.UUID,
) -> FoodRecommendationFeedback | None:
    """Lấy feedback duy nhất của user cho một món trong một assistant message."""
    return (await db.execute(
        select(FoodRecommendationFeedback).where(
            FoodRecommendationFeedback.user_id == user_id,
            FoodRecommendationFeedback.assistant_message_id == assistant_message_id,
            FoodRecommendationFeedback.food_id == food_id,
        )
    )).scalar_one_or_none()


async def create_food_recommendation_feedback(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    thread_id: uuid.UUID,
    assistant_message_id: uuid.UUID,
    food_id: uuid.UUID,
    verdict: str,
    rating: int | None,
    reasons: list[str],
    comment: str | None,
    tried: bool,
) -> FoodRecommendationFeedback:
    """Tạo food-level feedback nhưng chưa commit."""
    feedback = FoodRecommendationFeedback(
        user_id=user_id,
        thread_id=thread_id,
        assistant_message_id=assistant_message_id,
        food_id=food_id,
        verdict=verdict,
        rating=rating,
        reasons=reasons,
        comment=comment,
        tried=tried,
    )
    db.add(feedback)
    await db.flush()
    return feedback


def apply_food_recommendation_feedback_updates(
    feedback: FoodRecommendationFeedback,
    *,
    verdict: str,
    rating: int | None,
    reasons: list[str],
    comment: str | None,
    tried: bool,
) -> None:
    """Cập nhật food-level feedback trên model đã load."""
    feedback.verdict = verdict
    feedback.rating = rating
    feedback.reasons = reasons
    feedback.comment = comment
    feedback.tried = tried
    feedback.updated_at = func.now()


async def touch_thread_updated_at(db: AsyncSession, *, thread_id: uuid.UUID) -> None:
    """Cập nhật updated_at của thread."""
    await db.execute(
        update(ChatThread)
        .where(ChatThread.id == thread_id)
        .values(updated_at=func.now())
    )
