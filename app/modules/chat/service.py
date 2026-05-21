"""Chat History service — quản lý threads và messages của chatbot."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple

from sqlalchemy import delete, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.chat.handlers import (
    handle_food_info,
    handle_food_safety_check,
    handle_follow_up,
    handle_location_search,
    handle_new_search,
)
from app.modules.chat.handlers.common import (
    IntentHandlerResult,
    build_structured_result,
    build_empty_search_response,
    extract_target_reference,
    food_names_from_results,
)
from app.modules.chat.intent_classifier import classify_intent
from app.modules.chat.models import ChatMessage, ChatThread

# ---------------------------------------------------------------------------
# Cấu hình multi-turn context
# ---------------------------------------------------------------------------

# Số tin nhắn gần nhất đưa vào context (ví dụ: 6 = 3 lượt user + assistant)
CONTEXT_WINDOW = 6

# Giới hạn độ dài mỗi tin nhắn trong context để tránh prompt quá dài
# Assistant messages thường dài → cắt bớt
CONTEXT_USER_MSG_MAX_LEN = 300
CONTEXT_ASSISTANT_MSG_MAX_LEN = 200
from app.modules.chat.schemas import (
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
        structured_result=msg.structured_result,
        feedback=msg.feedback,
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
    lat: float | None,
    lng: float | None,
    db: AsyncSession,
) -> Optional[ChatSendMessageResponse]:
    """
    Luồng chính khi user gửi tin nhắn trong chatbot:
    1. Kiểm tra thread thuộc user.
    2. Lưu user message.
    3. Uỷ quyền cho dispatcher intent: classify → route handler → save assistant msg.
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
        structured_result=build_structured_result(
            "user_context",
            {
                "lat": lat,
                "lng": lng,
            },
        ) if lat is not None or lng is not None else None,
    )
    db.add(user_msg)
    await db.flush()

    # 3. Auto-title từ câu hỏi đầu tiên (trước khi search để không chặn flow)
    if not thread.title:
        thread.title = _auto_title(query)
        await db.flush()

    # 4. Search + lưu assistant message (logic dùng chung với regenerate & edit)
    return await _run_dispatch_and_save(thread_id, user_id, user_msg, skip_profile, db)


async def _load_recent_messages(
    thread_id: uuid.UUID,
    exclude_msg_id: uuid.UUID,
    db: AsyncSession,
    limit: int = CONTEXT_WINDOW,
) -> list[ChatMessage]:
    return (await db.execute(
        select(ChatMessage)
        .where(
            ChatMessage.thread_id == thread_id,
            ChatMessage.id != exclude_msg_id,
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )).scalars().all()


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
    msgs = await _load_recent_messages(
        thread_id=thread_id,
        exclude_msg_id=exclude_msg_id,
        db=db,
        limit=limit,
    )

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


def _extract_coordinates_from_structured_result(structured_result: dict[str, Any] | None) -> tuple[float | None, float | None]:
    if not structured_result:
        return None, None
    if structured_result.get("kind") != "user_context":
        return None, None
    data = structured_result.get("data") or {}
    lat = data.get("lat")
    lng = data.get("lng")
    return lat, lng


async def _get_last_assistant_with_food_results(
    thread_id: uuid.UUID,
    exclude_msg_id: uuid.UUID,
    db: AsyncSession,
) -> ChatMessage | None:
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


def _map_structured_kind_to_intent(kind: str | None) -> str | None:
    if kind == "food_search":
        return "new_search"
    if kind in {
        "follow_up",
        "food_info",
        "food_safety_check",
        "location_search",
        "greeting",
        "off_topic",
    }:
        return kind
    return None


async def _dispatch_user_intent(
    *,
    thread_id: uuid.UUID,
    user_id: uuid.UUID,
    user_msg: ChatMessage,
    skip_profile: bool,
    db: AsyncSession,
) -> IntentHandlerResult:
    from app.modules.users.service import get_profile

    t0 = time.perf_counter()

    # --- DB lookups (song song với nhau) ---
    recent_messages = await _load_recent_messages(
        thread_id=thread_id,
        exclude_msg_id=user_msg.id,
        db=db,
        limit=CONTEXT_WINDOW,
    )
    last_user_message = next((msg for msg in recent_messages if msg.role == "user"), None)
    last_assistant_message = next((msg for msg in recent_messages if msg.role == "assistant"), None)
    last_food_message = await _get_last_assistant_with_food_results(
        thread_id=thread_id,
        exclude_msg_id=user_msg.id,
        db=db,
    )
    t_db = time.perf_counter()
    print(f"⏱️ [DISPATCH] DB lookups: {(t_db - t0)*1000:.0f}ms")

    last_food_results = (last_food_message.food_results if last_food_message else None) or []
    last_intent = _map_structured_kind_to_intent(
        (last_assistant_message.structured_result or {}).get("kind") if last_assistant_message else None
    )

    # --- LLM #1: Intent Classifier ---
    t_intent_start = time.perf_counter()
    intent_result = await classify_intent(
        current_query=user_msg.content,
        last_user_message=last_user_message.content if last_user_message else "",
        last_assistant_message=last_assistant_message.content if last_assistant_message else "",
        last_assistant_has_food_results=bool(last_food_results),
        last_food_names=food_names_from_results(last_food_results, limit=5),
        last_intent=last_intent,
    )
    t_intent_end = time.perf_counter()
    extracted = intent_result.get("extracted") or {}
    intent = intent_result.get("intent") or "new_search"
    print(f"⏱️ [DISPATCH] classify_intent: {(t_intent_end - t_intent_start)*1000:.0f}ms → intent={intent}")

    profile = None
    if not skip_profile:
        profile = await get_profile(user_id, db)

    history_context = await _build_conversation_context(thread_id, user_msg.id, db)
    raw_query = user_msg.content
    query_with_context = (
        f"{history_context}\n\n[Câu hỏi hiện tại]\n{raw_query}"
        if history_context else raw_query
    )
    stored_lat, stored_lng = _extract_coordinates_from_structured_result(user_msg.structured_result)

    # --- Route theo intent ---
    t_handler_start = time.perf_counter()

    if intent == "follow_up" and last_food_results:
        result = await handle_follow_up(
            raw_query=raw_query,
            last_food_results=last_food_results,
            extracted_food_name=extracted.get("food_name"),
        )
        print(f"⏱️ [DISPATCH] handle_follow_up: {(time.perf_counter() - t_handler_start)*1000:.0f}ms")
        return result

    if intent == "food_info":
        result = await handle_food_info(
            raw_query=raw_query,
            db=db,
            last_food_results=last_food_results,
            food_name=extracted.get("food_name"),
            target_reference=extracted.get("target_reference") or extract_target_reference(raw_query),
        )
        print(f"⏱️ [DISPATCH] handle_food_info: {(time.perf_counter() - t_handler_start)*1000:.0f}ms")
        return result

    if intent == "food_safety_check":
        result = await handle_food_safety_check(
            raw_query=raw_query,
            db=db,
            profile=profile,
            last_food_results=last_food_results,
            food_name=extracted.get("food_name"),
            target_reference=extracted.get("target_reference") or extract_target_reference(raw_query),
            health_topic=extracted.get("health_topic"),
        )
        print(f"⏱️ [DISPATCH] handle_food_safety_check: {(time.perf_counter() - t_handler_start)*1000:.0f}ms")
        return result

    if intent == "location_search":
        result = await handle_location_search(
            raw_query=raw_query,
            db=db,
            last_food_results=last_food_results,
            food_name=extracted.get("food_name"),
            target_reference=extracted.get("target_reference") or extract_target_reference(raw_query),
            dish_query=extracted.get("dish_query"),
            location_query=extracted.get("location_query"),
            lat=stored_lat,
            lng=stored_lng,
        )
        print(f"⏱️ [DISPATCH] handle_location_search: {(time.perf_counter() - t_handler_start)*1000:.0f}ms")
        return result

    if intent == "greeting":
        print(f"⏱️ [DISPATCH] greeting (no LLM): {(time.perf_counter() - t_handler_start)*1000:.0f}ms")
        return IntentHandlerResult(
            intent="greeting",
            content=(
                "Chào bạn, mình sẵn sàng lên món và lọc theo khẩu vị hoặc hồ sơ sức khỏe cho bạn. "
                "Bạn đang muốn ăn món nước, món khô hay có tiêu chí cụ thể nào cho bữa này không?"
            ),
            structured_result=build_structured_result("greeting", {"status": "handled"}),
        )

    if intent == "off_topic":
        print(f"⏱️ [DISPATCH] off_topic (no LLM): {(time.perf_counter() - t_handler_start)*1000:.0f}ms")
        return IntentHandlerResult(
            intent="off_topic",
            content=(
                "Mình hiện tập trung vào tư vấn món ăn, kiểm tra an toàn thực phẩm và tìm quán phù hợp trong hệ thống này. "
                "Nếu bạn muốn, mình có thể giúp quay lại việc chọn món hoặc tìm địa điểm ăn uống."
            ),
            structured_result=build_structured_result("off_topic", {"status": "handled"}),
        )

    # --- Default: new_search (LLM pipeline nặng nhất) ---
    result = await handle_new_search(
        raw_query=raw_query,
        query_with_context=query_with_context,
        db=db,
        profile=profile,
        thread_id=thread_id,
    )
    print(f"⏱️ [DISPATCH] handle_new_search: {(time.perf_counter() - t_handler_start)*1000:.0f}ms")
    return result


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


async def _run_dispatch_and_save(
    thread_id: uuid.UUID,
    user_id: uuid.UUID,
    user_msg: ChatMessage,
    skip_profile: bool,
    db: AsyncSession,
) -> "ChatSendMessageResponse":
    """
    Dùng chung cho send_message, regenerate_message, edit_and_resend:
    - Phân loại intent từ context gần nhất
    - Dispatch sang handler tương ứng
    - Lưu assistant message với payload có cấu trúc
    - Cập nhật updated_at của thread
    - Trả ChatSendMessageResponse
    """
    t_total_start = time.perf_counter()
    print(f"\n{'='*60}")
    print(f"⏱️ [TIMING] send_message bắt đầu | query={user_msg.content[:60]!r}")

    handler_result = await _dispatch_user_intent(
        thread_id=thread_id,
        user_id=user_id,
        user_msg=user_msg,
        skip_profile=skip_profile,
        db=db,
    )
    t_dispatch_done = time.perf_counter()
    print(f"⏱️ [TIMING] _dispatch_user_intent DONE: {(t_dispatch_done - t_total_start)*1000:.0f}ms")

    if handler_result.search_result is None:
        handler_result.search_result = build_empty_search_response(
            query=user_msg.content,
            ai_response=handler_result.content,
            retrieval_note=(
                "Intent này không sinh danh sách món mới; search_result rỗng được giữ lại để tương thích frontend."
            ),
        )

    # Tạo assistant message
    assistant_msg = ChatMessage(
        thread_id=thread_id,
        role="assistant",
        content=handler_result.content,
        query_log_id=handler_result.query_log_id,
        food_results=handler_result.food_results,
        structured_result=handler_result.structured_result,
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
    t_total_end = time.perf_counter()
    print(f"⏱️ [TIMING] DB save: {(t_total_end - t_dispatch_done)*1000:.0f}ms")
    print(f"⏱️ [TIMING] *** TOTAL end-to-end: {(t_total_end - t_total_start)*1000:.0f}ms ***")
    print(f"{'='*60}\n")

    return ChatSendMessageResponse(
        user_message=_message_to_result(user_msg),
        assistant_message=_message_to_result(assistant_msg),
        intent=handler_result.intent,
        search_result=handler_result.search_result,
        place_result=handler_result.place_result,
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

    return await _run_dispatch_and_save(thread_id, user_id, user_msg, skip_profile, db)


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
    if data.lat is not None or data.lng is not None:
        user_msg.structured_result = build_structured_result(
            "user_context",
            {
                "lat": data.lat,
                "lng": data.lng,
            },
        )
    await db.flush()

    return await _run_dispatch_and_save(thread_id, user_id, user_msg, data.skip_profile, db)
