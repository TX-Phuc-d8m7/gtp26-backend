"""Chat History service — quản lý threads và messages của chatbot."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import delete, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatMessage, ChatThread

# ---------------------------------------------------------------------------
# Cấu hình multi-turn context
# ---------------------------------------------------------------------------

# Số tin nhắn gần nhất đưa vào context (ví dụ: 6 = 3 lượt user + assistant)
CONTEXT_WINDOW = 6

# Giới hạn độ dài mỗi tin nhắn trong context để tránh prompt quá dài
# Assistant messages thường dài → cắt bớt
CONTEXT_USER_MSG_MAX_LEN = 300
CONTEXT_ASSISTANT_MSG_MAX_LEN = 200
from app.schemas import (
    ChatMessageListResponse,
    ChatMessageResult,
    ChatSendMessageResponse,
    ChatThreadCreate,
    ChatThreadListResponse,
    ChatThreadResult,
    ChatThreadUpdate,
    MessageEditRequest,
    MessageFeedbackRequest,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TITLE_MAX_LEN = 60


def _auto_title(query: str) -> str:
    """Tạo tiêu đề tự động từ câu hỏi đầu tiên (giới hạn 60 ký tự)."""
    text = query.strip()
    if len(text) <= _TITLE_MAX_LEN:
        return text
    return text[:_TITLE_MAX_LEN - 1] + "…"


def _thread_to_result(thread: ChatThread, message_count: int = 0, last_message_at: Optional[datetime] = None) -> ChatThreadResult:
    return ChatThreadResult(
        id=thread.id,
        user_id=thread.user_id,
        title=thread.title,
        is_pinned=thread.is_pinned,
        is_deleted=thread.is_deleted,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
        message_count=message_count,
        last_message_at=last_message_at,
    )


def _message_to_result(msg: ChatMessage) -> ChatMessageResult:
    return ChatMessageResult(
        id=msg.id,
        thread_id=msg.thread_id,
        role=msg.role,
        content=msg.content,
        query_log_id=msg.query_log_id,
        food_results=msg.food_results,
        created_at=msg.created_at,
    )


# ---------------------------------------------------------------------------
# Thread CRUD
# ---------------------------------------------------------------------------

async def list_threads(
    user_id: uuid.UUID,
    db: AsyncSession,
    *,
    limit: int = 20,
    offset: int = 0,
    q: Optional[str] = None,
    pinned_first: bool = True,
) -> Tuple[int, List[ChatThreadResult]]:
    """
    Lấy danh sách threads của user (không bao gồm đã xoá).
    Mặc định sắp xếp: ghim trên cùng → mới nhất trước.
    """
    base_where = [
        ChatThread.user_id == user_id,
        ChatThread.is_deleted.is_(False),
    ]
    if q:
        base_where.append(ChatThread.title.ilike(f"%{q.strip()}%"))

    # Đếm tổng
    count_stmt = select(func.count()).select_from(ChatThread).where(*base_where)
    total = (await db.execute(count_stmt)).scalar_one()

    # Thống kê messages cho mỗi thread (số tin + thời điểm tin cuối)
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

    data_stmt = data_stmt.limit(limit).offset(offset)
    rows = (await db.execute(data_stmt)).all()

    items = [
        _thread_to_result(row.ChatThread, row.message_count, row.last_message_at)
        for row in rows
    ]
    return total, items


async def create_thread(
    user_id: uuid.UUID,
    data: ChatThreadCreate,
    db: AsyncSession,
) -> ChatThreadResult:
    """Tạo thread mới — title tuỳ chọn."""
    thread = ChatThread(
        user_id=user_id,
        title=data.title,
    )
    db.add(thread)
    await db.commit()
    await db.refresh(thread)
    return _thread_to_result(thread)


async def get_thread(
    thread_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> Optional[ChatThreadResult]:
    """Lấy metadata thread. None nếu không tồn tại hoặc không thuộc user."""
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
    return _thread_to_result(row.ChatThread, row.message_count, row.last_message_at)


async def update_thread(
    thread_id: uuid.UUID,
    user_id: uuid.UUID,
    data: ChatThreadUpdate,
    db: AsyncSession,
) -> Optional[ChatThreadResult]:
    """Cập nhật title hoặc is_pinned. None nếu không tìm thấy."""
    thread = (await db.execute(
        select(ChatThread).where(
            ChatThread.id == thread_id,
            ChatThread.user_id == user_id,
            ChatThread.is_deleted.is_(False),
        )
    )).scalar_one_or_none()

    if thread is None:
        return None

    if data.title is not None:
        thread.title = data.title
    if data.is_pinned is not None:
        thread.is_pinned = data.is_pinned

    # Cập nhật thủ công updated_at vì SQLAlchemy onupdate không trigger khi set attr
    thread.updated_at = func.now()
    await db.commit()
    await db.refresh(thread)
    return _thread_to_result(thread)


async def delete_thread(
    thread_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> bool:
    """Soft delete thread. Trả False nếu không tìm thấy."""
    thread = (await db.execute(
        select(ChatThread).where(
            ChatThread.id == thread_id,
            ChatThread.user_id == user_id,
            ChatThread.is_deleted.is_(False),
        )
    )).scalar_one_or_none()

    if thread is None:
        return False

    thread.is_deleted = True
    await db.commit()
    return True


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

async def list_messages(
    thread_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
) -> Optional[Tuple[int, List[ChatMessageResult]]]:
    """
    Lấy danh sách messages trong thread (thứ tự cũ nhất trước — như timeline chat).
    Trả None nếu thread không thuộc user.
    """
    # Kiểm tra quyền
    thread = (await db.execute(
        select(ChatThread).where(
            ChatThread.id == thread_id,
            ChatThread.user_id == user_id,
            ChatThread.is_deleted.is_(False),
        )
    )).scalar_one_or_none()

    if thread is None:
        return None

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

    return total, [_message_to_result(m) for m in messages]


# ---------------------------------------------------------------------------
# Send message (= search + save both sides)
# ---------------------------------------------------------------------------

async def send_message(
    thread_id: uuid.UUID,
    user_id: uuid.UUID,
    query: str,
    skip_profile: bool,
    db: AsyncSession,
) -> Optional[ChatSendMessageResponse]:
    """
    Luồng chính khi user gửi tin nhắn trong chatbot:
    1. Kiểm tra thread thuộc user.
    2. Lưu user message.
    3. Uỷ quyền cho _run_search_and_save: build context → augment profile → search → save assistant msg.
    4. Auto-gen title từ câu hỏi đầu tiên nếu thread chưa có title.

    Trả None nếu thread không tồn tại hoặc không thuộc user.
    """
    # 1. Kiểm tra thread
    thread = await _get_thread_for_user(thread_id, user_id, db)
    if thread is None:
        return None

    # 2. Lưu user message
    user_msg = ChatMessage(
        thread_id=thread_id,
        role="user",
        content=query.strip(),
    )
    db.add(user_msg)
    await db.flush()

    # 3. Auto-title từ câu hỏi đầu tiên (trước khi search để không chặn flow)
    if not thread.title:
        thread.title = _auto_title(query)
        await db.flush()

    # 4. Search + lưu assistant message (logic dùng chung với regenerate & edit)
    return await _run_search_and_save(thread_id, user_id, user_msg, skip_profile, db)


async def _build_conversation_context(
    thread_id: uuid.UUID,
    exclude_msg_id: uuid.UUID,
    db: AsyncSession,
    limit: int = CONTEXT_WINDOW,
) -> str:
    """
    Lấy `limit` tin nhắn gần nhất trong thread (không tính tin nhắn hiện tại),
    format thành chuỗi ngữ cảnh hội thoại để LLM supervisor hiểu được context.

    Ví dụ output:
        [Lịch sử hội thoại]
        Người dùng: Tôi bị cao huyết áp, gợi ý món ăn sáng
        Trợ lý: Với tình trạng cao huyết áp, tôi gợi ý cháo yến mạch…
        Người dùng: Món nào không cần nấu?
        Trợ lý: Bạn có thể chọn bánh mì nguyên cám…

    Trả chuỗi rỗng nếu thread chưa có lịch sử (tin nhắn đầu tiên).
    """
    msgs = (await db.execute(
        select(ChatMessage)
        .where(
            ChatMessage.thread_id == thread_id,
            ChatMessage.id != exclude_msg_id,
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )).scalars().all()

    if not msgs:
        return ""

    # Đảo lại để hiển thị cũ → mới
    msgs = list(reversed(msgs))

    lines = ["[Lịch sử hội thoại]"]
    for msg in msgs:
        if msg.role == "user":
            label = "Người dùng"
            max_len = CONTEXT_USER_MSG_MAX_LEN
        else:
            label = "Trợ lý"
            max_len = CONTEXT_ASSISTANT_MSG_MAX_LEN

        content = msg.content.strip()
        if len(content) > max_len:
            content = content[:max_len] + "…"
        lines.append(f"{label}: {content}")

    return "\n".join(lines)


def _build_fallback_content(search_result) -> str:
    """Tạo nội dung fallback khi không có ai_response (lỗi LLM)."""
    if not search_result.results:
        return "Xin lỗi, tôi không tìm thấy món ăn phù hợp với yêu cầu của bạn."
    names = ", ".join(r.name for r in search_result.results[:3])
    return f"Dựa trên yêu cầu của bạn, tôi gợi ý: {names}."


def _serialize_food_results(search_result) -> Optional[list]:
    """Serialize danh sách FoodResult thành list dict để lưu JSONB."""
    if not search_result.results:
        return None
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "description": r.description,
            "img_url": r.img_url,
            "core_ingredients": r.core_ingredients,
            "soft_tags": r.soft_tags,
            "taste_profile": r.taste_profile,
            "meal_context": r.meal_context,
            "occasion_context": r.occasion_context,
            "matchScore": r.matchScore,
            "reason": r.reason,
        }
        for r in search_result.results
    ]


async def _get_thread_for_user(
    thread_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> Optional[ChatThread]:
    """Lấy thread nếu thuộc user và chưa bị xoá. Dùng chung cho nhiều hàm."""
    return (await db.execute(
        select(ChatThread).where(
            ChatThread.id == thread_id,
            ChatThread.user_id == user_id,
            ChatThread.is_deleted.is_(False),
        )
    )).scalar_one_or_none()


async def _run_search_and_save(
    thread_id: uuid.UUID,
    user_id: uuid.UUID,
    user_msg: ChatMessage,
    skip_profile: bool,
    db: AsyncSession,
) -> "ChatSendMessageResponse":
    """
    Dùng chung cho send_message, regenerate_message, edit_and_resend:
    - Build conversation context từ lịch sử thread (không tính user_msg hiện tại)
    - Augment với health profile
    - Gọi search_food
    - Tạo và lưu assistant message
    - Cập nhật updated_at của thread
    - Trả ChatSendMessageResponse
    """
    from app.modules.search.service import search_food
    from app.modules.users.service import augment_query_with_profile, get_profile

    # Build context từ lịch sử
    history_context = await _build_conversation_context(thread_id, user_msg.id, db)
    raw_query = user_msg.content
    query_with_context = (
        f"{history_context}\n\n[Câu hỏi hiện tại]\n{raw_query}"
        if history_context else raw_query
    )

    # Augment health profile
    effective_query = query_with_context
    if not skip_profile:
        profile = await get_profile(user_id, db)
        effective_query = augment_query_with_profile(query_with_context, profile)

    # Gọi AI search
    search_result = await search_food(effective_query, db, thread_id=thread_id)

    # Tạo assistant message
    assistant_msg = ChatMessage(
        thread_id=thread_id,
        role="assistant",
        content=search_result.ai_response or _build_fallback_content(search_result),
        query_log_id=search_result.query_log_id,
        food_results=_serialize_food_results(search_result),
    )
    db.add(assistant_msg)

    # Cập nhật thread updated_at
    await db.execute(
        update(ChatThread)
        .where(ChatThread.id == thread_id)
        .values(updated_at=func.now())
    )

    await db.commit()
    await db.refresh(user_msg)
    await db.refresh(assistant_msg)

    return ChatSendMessageResponse(
        user_message=_message_to_result(user_msg),
        assistant_message=_message_to_result(assistant_msg),
        search_result=search_result,
    )


# ---------------------------------------------------------------------------
# Regenerate — thử lại câu trả lời AI
# ---------------------------------------------------------------------------

async def regenerate_message(
    thread_id: uuid.UUID,
    message_id: uuid.UUID,
    user_id: uuid.UUID,
    skip_profile: bool,
    db: AsyncSession,
) -> Optional[ChatSendMessageResponse]:
    """
    Xoá assistant message cũ và tạo lại response từ cùng user message.

    `message_id` là ID của assistant message cần regenerate.
    Trả None nếu thread/message không tồn tại hoặc không thuộc user.
    """
    # Kiểm tra thread
    if not await _get_thread_for_user(thread_id, user_id, db):
        return None

    # Tìm assistant message
    asst_msg = (await db.execute(
        select(ChatMessage).where(
            ChatMessage.id == message_id,
            ChatMessage.thread_id == thread_id,
            ChatMessage.role == "assistant",
        )
    )).scalar_one_or_none()
    if asst_msg is None:
        return None

    # Tìm user message liền trước (theo thứ tự thời gian)
    user_msg = (await db.execute(
        select(ChatMessage).where(
            ChatMessage.thread_id == thread_id,
            ChatMessage.role == "user",
            ChatMessage.created_at < asst_msg.created_at,
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if user_msg is None:
        return None

    # Xoá assistant message cũ để không lẫn vào context
    await db.delete(asst_msg)
    await db.flush()

    return await _run_search_and_save(thread_id, user_id, user_msg, skip_profile, db)


# ---------------------------------------------------------------------------
# Message Feedback — 👍 / 👎
# ---------------------------------------------------------------------------

async def set_message_feedback(
    thread_id: uuid.UUID,
    message_id: uuid.UUID,
    user_id: uuid.UUID,
    feedback: Optional[str],
    db: AsyncSession,
) -> Optional[ChatMessageResult]:
    """
    Đặt hoặc xoá feedback (like/dislike) cho một assistant message.
    Chỉ áp dụng cho messages thuộc thread của user.
    Trả None nếu không tìm thấy.
    """
    if not await _get_thread_for_user(thread_id, user_id, db):
        return None

    msg = (await db.execute(
        select(ChatMessage).where(
            ChatMessage.id == message_id,
            ChatMessage.thread_id == thread_id,
            ChatMessage.role == "assistant",
        )
    )).scalar_one_or_none()

    if msg is None:
        return None

    msg.feedback = feedback  # None = xoá feedback
    await db.commit()
    await db.refresh(msg)
    return _message_to_result(msg)


# ---------------------------------------------------------------------------
# Edit & Resend — chỉnh sửa câu hỏi cũ và chạy lại
# ---------------------------------------------------------------------------

async def edit_and_resend(
    thread_id: uuid.UUID,
    message_id: uuid.UUID,
    user_id: uuid.UUID,
    data: MessageEditRequest,
    db: AsyncSession,
) -> Optional[ChatSendMessageResponse]:
    """
    Chỉnh sửa nội dung một user message và chạy lại toàn bộ từ điểm đó:
    1. Xoá tất cả messages sau user message (kể cả assistant response cũ và các lượt tiếp).
    2. Cập nhật nội dung user message.
    3. Re-run search với câu hỏi mới + context trước đó.
    4. Lưu assistant message mới.

    `message_id` là ID của user message cần edit.
    Trả None nếu không tìm thấy.
    """
    if not await _get_thread_for_user(thread_id, user_id, db):
        return None

    # Tìm user message cần edit
    user_msg = (await db.execute(
        select(ChatMessage).where(
            ChatMessage.id == message_id,
            ChatMessage.thread_id == thread_id,
            ChatMessage.role == "user",
        )
    )).scalar_one_or_none()

    if user_msg is None:
        return None

    # Xoá tất cả messages sau user message (assistant cũ + các lượt tiếp theo)
    await db.execute(
        delete(ChatMessage).where(
            ChatMessage.thread_id == thread_id,
            ChatMessage.created_at > user_msg.created_at,
        )
    )

    # Cập nhật nội dung user message
    user_msg.content = data.query.strip()
    await db.flush()

    return await _run_search_and_save(thread_id, user_id, user_msg, data.skip_profile, db)
