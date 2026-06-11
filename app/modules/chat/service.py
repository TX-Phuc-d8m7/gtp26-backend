"""Chat History service — quản lý threads và messages của chatbot."""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.chat import repository as chat_repo
from app.modules.chat.engine import context as chat_context
from app.modules.chat.engine import dispatcher as chat_dispatcher
from app.modules.chat.engine.context import ConversationContextMessage
from app.modules.chat.engine.response_factory import build_empty_search_response, build_structured_result
from app.modules.chat.models import ChatMessage, ChatThread

from app.modules.chat.schemas import (
    ChatMessageListResponse,
    ChatMessageResult,
    FoodRecommendationFeedbackRequest,
    FoodRecommendationFeedbackResult,
    GuestChatHistoryItem,
    GuestChatMessageResult,
    GuestChatSendMessageResponse,
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


def _food_recommendation_feedback_to_result(feedback) -> FoodRecommendationFeedbackResult:
    return FoodRecommendationFeedbackResult(
        id=feedback.id,
        user_id=feedback.user_id,
        thread_id=feedback.thread_id,
        assistant_message_id=feedback.assistant_message_id,
        food_id=feedback.food_id,
        verdict=feedback.verdict,
        rating=feedback.rating,
        reasons=feedback.reasons or [],
        comment=feedback.comment,
        tried=feedback.tried,
        created_at=feedback.created_at,
        updated_at=feedback.updated_at,
    )


def _message_to_result(
    msg: ChatMessage,
    food_recommendation_feedbacks: list[FoodRecommendationFeedbackResult] | None = None,
) -> ChatMessageResult:
    return ChatMessageResult(
        id=msg.id,
        thread_id=msg.thread_id,
        role=msg.role,
        content=msg.content,
        query_log_id=msg.query_log_id,
        food_results=msg.food_results,
        structured_result=msg.structured_result,
        feedback=msg.feedback,
        food_recommendation_feedbacks=food_recommendation_feedbacks or [],
        created_at=msg.created_at,
    )


def _guest_message_to_result(msg: ConversationContextMessage) -> GuestChatMessageResult:
    return GuestChatMessageResult(
        role=msg.role,
        content=msg.content,
        food_results=msg.food_results,
        structured_result=msg.structured_result,
    )


def _message_contains_food_result(msg: ChatMessage, food_id: uuid.UUID) -> bool:
    """Kiểm tra món được feedback có nằm trong danh sách gợi ý của message không."""
    food_id_text = str(food_id)
    for item in msg.food_results or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or "") == food_id_text:
            return True
    return False


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
    total, rows = await chat_repo.list_thread_summaries(
        db,
        user_id=user_id,
        limit=limit,
        offset=offset,
        q=q,
        pinned_first=pinned_first,
    )
    items = [
        _thread_to_result(row.thread, row.message_count, row.last_message_at)
        for row in rows
    ]
    return total, items


async def create_thread(
    user_id: uuid.UUID,
    data: ChatThreadCreate,
    db: AsyncSession,
) -> ChatThreadResult:
    """Tạo thread mới — title tuỳ chọn."""
    thread = await chat_repo.create_thread(
        db,
        user_id=user_id,
        title=data.title,
    )
    await db.commit()
    await db.refresh(thread)
    return _thread_to_result(thread)


async def get_thread(
    thread_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> Optional[ChatThreadResult]:
    """Lấy metadata thread. None nếu không tồn tại hoặc không thuộc user."""
    row = await chat_repo.get_thread_summary(
        db,
        thread_id=thread_id,
        user_id=user_id,
    )
    if row is None:
        return None
    return _thread_to_result(row.thread, row.message_count, row.last_message_at)


async def update_thread(
    thread_id: uuid.UUID,
    user_id: uuid.UUID,
    data: ChatThreadUpdate,
    db: AsyncSession,
) -> Optional[ChatThreadResult]:
    """Cập nhật title hoặc is_pinned. None nếu không tìm thấy."""
    thread = await chat_repo.get_thread_for_user(
        db,
        thread_id=thread_id,
        user_id=user_id,
    )

    if thread is None:
        return None

    chat_repo.apply_thread_updates(
        thread,
        title=data.title,
        is_pinned=data.is_pinned,
    )
    await db.commit()
    await db.refresh(thread)
    return _thread_to_result(thread)


async def delete_thread(
    thread_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> bool:
    """Soft delete thread. Trả False nếu không tìm thấy."""
    thread = await chat_repo.get_thread_for_user(
        db,
        thread_id=thread_id,
        user_id=user_id,
    )

    if thread is None:
        return False

    chat_repo.soft_delete_thread(thread)
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
    thread = await chat_repo.get_thread_for_user(
        db,
        thread_id=thread_id,
        user_id=user_id,
    )

    if thread is None:
        return None

    total, messages = await chat_repo.list_messages(
        db,
        thread_id=thread_id,
        limit=limit,
        offset=offset,
    )
    assistant_message_ids = [m.id for m in messages if m.role == "assistant"]
    feedback_rows = await chat_repo.list_food_recommendation_feedbacks(
        db,
        user_id=user_id,
        message_ids=assistant_message_ids,
    )
    feedbacks_by_message: dict[uuid.UUID, list[FoodRecommendationFeedbackResult]] = {}
    for feedback in feedback_rows:
        feedbacks_by_message.setdefault(feedback.assistant_message_id, []).append(
            _food_recommendation_feedback_to_result(feedback)
        )

    return total, [
        _message_to_result(m, feedbacks_by_message.get(m.id))
        for m in messages
    ]


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
    user_msg = await chat_repo.create_message(
        db,
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

    # 3. Auto-title từ câu hỏi đầu tiên (trước khi search để không chặn flow)
    if not thread.title:
        chat_repo.apply_thread_updates(thread, title=_auto_title(query))
        await db.flush()

    # 4. Search + lưu assistant message (logic dùng chung với regenerate & edit)
    result = await _run_dispatch_and_save(thread_id, user_id, user_msg, skip_profile, db)
    return result.model_copy(update={"thread_title": thread.title})


async def send_guest_message(
    *,
    query: str,
    skip_profile: bool,
    lat: float | None,
    lng: float | None,
    history: list[GuestChatHistoryItem],
    current_user_id: uuid.UUID | None,
    db: AsyncSession,
) -> GuestChatSendMessageResponse:
    """
    Public guest chat endpoint:
    - Không lưu thread/message vào DB
    - Dùng chung intent dispatcher với chat đã đăng nhập
    - Có thể tận dụng profile nếu request kèm token hợp lệ và skip_profile=false
    """
    user_structured_result = build_structured_result(
        "user_context",
        {
            "lat": lat,
            "lng": lng,
        },
    ) if lat is not None or lng is not None else None

    recent_messages = [
        chat_context.snapshot_from_guest_history_item(item)
        for item in history[-chat_context.CONTEXT_WINDOW:]
    ]
    user_message = ConversationContextMessage(
        role="user",
        content=query.strip(),
        structured_result=user_structured_result,
    )

    handler_result = await chat_dispatcher.dispatch_intent_from_context(
        raw_query=user_message.content,
        user_id=current_user_id,
        user_structured_result=user_message.structured_result,
        recent_messages=recent_messages,
        skip_profile=skip_profile,
        db=db,
        thread_id=None,
    )

    if handler_result.search_result is None:
        handler_result.search_result = build_empty_search_response(
            query=user_message.content,
            ai_response=handler_result.content,
            retrieval_note=(
                "Intent này không sinh danh sách món mới; search_result rỗng được giữ lại để tương thích frontend."
            ),
        )

    assistant_message = ConversationContextMessage(
        role="assistant",
        content=handler_result.content,
        food_results=handler_result.food_results,
        structured_result=handler_result.structured_result,
    )
    return GuestChatSendMessageResponse(
        user_message=_guest_message_to_result(user_message),
        assistant_message=_guest_message_to_result(assistant_message),
        intent=handler_result.intent,
        search_result=handler_result.search_result,
        place_result=handler_result.place_result,
    )

def _build_fallback_content(search_result) -> str:
    """Tạo nội dung fallback khi không có ai_response (lỗi LLM)."""
    if not search_result.results:
        return "Xin lỗi, tôi không tìm thấy món ăn phù hợp với yêu cầu của bạn."
    names = ", ".join(r.name for r in search_result.results[:3])
    return f"Dựa trên yêu cầu của bạn, tôi gợi ý: {names}."

async def _get_thread_for_user(
    thread_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> Optional[ChatThread]:
    """Lấy thread nếu thuộc user và chưa bị xoá. Dùng chung cho nhiều hàm."""
    return await chat_repo.get_thread_for_user(
        db,
        thread_id=thread_id,
        user_id=user_id,
    )


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

    handler_result = await chat_dispatcher.dispatch_user_intent(
        thread_id=thread_id,
        user_id=user_id,
        user_msg=user_msg,
        skip_profile=skip_profile,
        db=db,
    )
    t_dispatch_done = time.perf_counter()
    print(f"⏱️ [TIMING] dispatch_user_intent DONE: {(t_dispatch_done - t_total_start)*1000:.0f}ms")

    if handler_result.search_result is None:
        handler_result.search_result = build_empty_search_response(
            query=user_msg.content,
            ai_response=handler_result.content,
            retrieval_note=(
                "Intent này không sinh danh sách món mới; search_result rỗng được giữ lại để tương thích frontend."
            ),
        )

    # Tạo assistant message
    assistant_msg = await chat_repo.create_message(
        db,
        thread_id=thread_id,
        role="assistant",
        content=handler_result.content,
        query_log_id=handler_result.query_log_id,
        food_results=handler_result.food_results,
        structured_result=handler_result.structured_result,
    )

    # Cập nhật thread updated_at
    await chat_repo.touch_thread_updated_at(db, thread_id=thread_id)

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
    thread = await _get_thread_for_user(thread_id, user_id, db)
    if thread is None:
        return None

    # Tìm assistant message
    asst_msg = await chat_repo.get_assistant_message(
        db,
        thread_id=thread_id,
        message_id=message_id,
    )
    if asst_msg is None:
        return None

    # Tìm user message liền trước (theo thứ tự thời gian)
    user_msg = await chat_repo.get_previous_user_message(
        db,
        thread_id=thread_id,
        before_created_at=asst_msg.created_at,
    )
    if user_msg is None:
        return None

    # Xoá assistant message cũ để không lẫn vào context
    await chat_repo.delete_message(db, asst_msg)

    result = await _run_dispatch_and_save(thread_id, user_id, user_msg, skip_profile, db)
    return result.model_copy(update={"thread_title": thread.title})


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

    msg = await chat_repo.get_assistant_message(
        db,
        thread_id=thread_id,
        message_id=message_id,
    )

    if msg is None:
        return None

    chat_repo.set_message_feedback(msg, feedback)
    await db.commit()
    await db.refresh(msg)
    return _message_to_result(msg)


# ---------------------------------------------------------------------------
# Food Recommendation Feedback — đánh giá từng món gợi ý
# ---------------------------------------------------------------------------

async def set_food_recommendation_feedback(
    thread_id: uuid.UUID,
    message_id: uuid.UUID,
    user_id: uuid.UUID,
    data: FoodRecommendationFeedbackRequest,
    db: AsyncSession,
) -> Optional[FoodRecommendationFeedbackResult]:
    """
    Tạo hoặc cập nhật feedback của user cho một món trong assistant message.
    Trả None nếu thread/message không thuộc user. Raise ValueError nếu food_id
    không nằm trong food_results của assistant message.
    """
    if not await _get_thread_for_user(thread_id, user_id, db):
        return None

    msg = await chat_repo.get_assistant_message(
        db,
        thread_id=thread_id,
        message_id=message_id,
    )
    if msg is None:
        return None

    if not _message_contains_food_result(msg, data.food_id):
        raise ValueError("FOOD_NOT_IN_ASSISTANT_MESSAGE")

    normalized_reasons = [
        reason.strip()
        for reason in data.reasons
        if reason.strip()
    ]
    normalized_comment = data.comment.strip() if data.comment and data.comment.strip() else None

    feedback = await chat_repo.get_food_recommendation_feedback(
        db,
        user_id=user_id,
        assistant_message_id=message_id,
        food_id=data.food_id,
    )
    if feedback is None:
        feedback = await chat_repo.create_food_recommendation_feedback(
            db,
            user_id=user_id,
            thread_id=thread_id,
            assistant_message_id=message_id,
            food_id=data.food_id,
            verdict=data.verdict,
            rating=data.rating,
            reasons=normalized_reasons,
            comment=normalized_comment,
            tried=data.tried,
        )
    else:
        chat_repo.apply_food_recommendation_feedback_updates(
            feedback,
            verdict=data.verdict,
            rating=data.rating,
            reasons=normalized_reasons,
            comment=normalized_comment,
            tried=data.tried,
        )

    await db.commit()
    await db.refresh(feedback)
    return _food_recommendation_feedback_to_result(feedback)


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
    thread = await _get_thread_for_user(thread_id, user_id, db)
    if thread is None:
        return None

    # Tìm user message cần edit
    user_msg = await chat_repo.get_user_message(
        db,
        thread_id=thread_id,
        message_id=message_id,
    )

    if user_msg is None:
        return None

    # Xoá tất cả messages sau user message (assistant cũ + các lượt tiếp theo)
    await chat_repo.delete_messages_after(
        db,
        thread_id=thread_id,
        created_at=user_msg.created_at,
    )

    # Cập nhật nội dung user message
    structured_result = None
    update_structured_result = data.lat is not None or data.lng is not None
    if update_structured_result:
        structured_result = build_structured_result(
            "user_context",
            {
                "lat": data.lat,
                "lng": data.lng,
            },
        )
    chat_repo.update_message_content_and_context(
        user_msg,
        content=data.query.strip(),
        structured_result=structured_result,
        update_structured_result=update_structured_result,
    )
    await db.flush()

    result = await _run_dispatch_and_save(thread_id, user_id, user_msg, data.skip_profile, db)
    return result.model_copy(update={"thread_title": thread.title})
