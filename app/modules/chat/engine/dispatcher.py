"""Intent dispatcher cho chat module.

Dispatcher chịu trách nhiệm đọc conversation context, gọi intent classifier và
route sang handler phù hợp. Service layer chỉ gọi dispatcher rồi lưu kết quả.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.chat.engine import context as chat_context
from app.modules.chat.engine.context import ConversationContextMessage
from app.modules.chat.engine.handlers import (
    handle_food_info,
    handle_food_safety_check,
    handle_follow_up,
    handle_location_search,
    handle_new_search,
)
from app.modules.chat.engine.food_reference import extract_target_reference
from app.modules.chat.engine.handlers.base import IntentHandlerResult
from app.modules.chat.engine.intent_classifier import classify_intent
from app.modules.chat.engine.response_factory import build_structured_result, food_names_from_results
from app.modules.chat.models import ChatMessage


def map_structured_kind_to_intent(kind: str | None) -> str | None:
    """Map structured_result.kind của assistant message về intent gần nhất."""
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


async def dispatch_intent_from_context(
    *,
    raw_query: str,
    user_id: uuid.UUID | None,
    user_structured_result: dict[str, Any] | None,
    recent_messages: list[ConversationContextMessage],
    skip_profile: bool,
    db: AsyncSession,
    thread_id: uuid.UUID | None,
) -> IntentHandlerResult:
    """Classify intent từ context rồi gọi handler tương ứng."""
    from app.modules.users.service import get_profile

    t0 = time.perf_counter()

    last_user_message = chat_context.get_last_message_by_role(recent_messages, "user")
    last_assistant_message = chat_context.get_last_message_by_role(recent_messages, "assistant")
    last_food_message = chat_context.get_last_assistant_with_food_results_from_messages(recent_messages)
    t_context = time.perf_counter()
    print(f"⏱️ [DISPATCH] Context prep: {(t_context - t0)*1000:.0f}ms")

    last_food_results = (last_food_message.food_results if last_food_message else None) or []
    last_intent = map_structured_kind_to_intent(
        (last_assistant_message.structured_result or {}).get("kind")
        if last_assistant_message
        else None
    )

    t_intent_start = time.perf_counter()
    intent_result = await classify_intent(
        current_query=raw_query,
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

    # DEBUG: bỏ comment dòng dưới để ép tất cả về new_search khi cần test
    intent = "new_search"

    profile = None
    if not skip_profile and user_id is not None:
        profile = await get_profile(user_id, db)

    history_context = chat_context.build_conversation_context_from_messages(recent_messages)
    query_with_context = (
        f"{history_context}\n\n[Câu hỏi hiện tại]\n{raw_query}"
        if history_context else raw_query
    )
    stored_lat, stored_lng = chat_context.extract_coordinates_from_structured_result(user_structured_result)

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

    result = await handle_new_search(
        raw_query=raw_query,
        query_with_context=query_with_context,
        db=db,
        profile=profile,
        thread_id=thread_id,
    )
    print(f"⏱️ [DISPATCH] handle_new_search: {(time.perf_counter() - t_handler_start)*1000:.0f}ms")
    return result


async def dispatch_user_intent(
    *,
    thread_id: uuid.UUID,
    user_id: uuid.UUID,
    user_msg: ChatMessage,
    skip_profile: bool,
    db: AsyncSession,
) -> IntentHandlerResult:
    """Load recent context của thread rồi dispatch intent cho user message."""
    recent_messages_db = await chat_context.load_recent_messages(
        thread_id=thread_id,
        exclude_msg_id=user_msg.id,
        db=db,
        limit=chat_context.CONTEXT_WINDOW,
    )
    recent_messages = [
        chat_context.snapshot_from_chat_message(msg)
        for msg in reversed(recent_messages_db)
    ]
    return await dispatch_intent_from_context(
        raw_query=user_msg.content,
        user_id=user_id,
        user_structured_result=user_msg.structured_result,
        recent_messages=recent_messages,
        skip_profile=skip_profile,
        db=db,
        thread_id=thread_id,
    )
