"""Conversation context helpers cho chat module.

Module này gom các thao tác tạo snapshot hội thoại, load recent messages và
format history context cho intent classifier/search. Không chứa logic dispatch
intent hay ghi response.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.chat import repository as chat_repo
from app.modules.chat.models import ChatMessage
from app.modules.chat.schemas import GuestChatHistoryItem


# Số tin nhắn gần nhất đưa vào context (ví dụ: 6 = 3 lượt user + assistant)
CONTEXT_WINDOW = 6

# Giới hạn độ dài mỗi tin nhắn trong context để tránh prompt quá dài.
CONTEXT_USER_MSG_MAX_LEN = 300
CONTEXT_ASSISTANT_MSG_MAX_LEN = 200


@dataclass
class ConversationContextMessage:
    role: str
    content: str
    food_results: list[dict[str, Any]] | None = None
    structured_result: dict[str, Any] | None = None


def snapshot_from_chat_message(msg: ChatMessage) -> ConversationContextMessage:
    """Chuyển DB message thành snapshot nhẹ để dùng cho context."""
    return ConversationContextMessage(
        role=msg.role,
        content=msg.content,
        food_results=msg.food_results,
        structured_result=msg.structured_result,
    )


def snapshot_from_guest_history_item(item: GuestChatHistoryItem) -> ConversationContextMessage:
    """Chuyển guest history item thành snapshot nhẹ để dùng chung dispatcher."""
    return ConversationContextMessage(
        role=item.role,
        content=item.content,
        food_results=item.food_results,
        structured_result=item.structured_result,
    )


async def load_recent_messages(
    thread_id: uuid.UUID,
    exclude_msg_id: uuid.UUID,
    db: AsyncSession,
    limit: int = CONTEXT_WINDOW,
) -> list[ChatMessage]:
    """Load các message gần nhất trong thread, không bao gồm message hiện tại."""
    return await chat_repo.load_recent_messages(
        db,
        thread_id=thread_id,
        exclude_msg_id=exclude_msg_id,
        limit=limit,
    )


async def build_conversation_context(
    thread_id: uuid.UUID,
    exclude_msg_id: uuid.UUID,
    db: AsyncSession,
    limit: int = CONTEXT_WINDOW,
) -> str:
    """
    Lấy lịch sử gần nhất trong thread và format thành text context cho LLM.

    Trả chuỗi rỗng nếu thread chưa có lịch sử trước message hiện tại.
    """
    msgs = await load_recent_messages(
        thread_id=thread_id,
        exclude_msg_id=exclude_msg_id,
        db=db,
        limit=limit,
    )
    snapshots = [snapshot_from_chat_message(msg) for msg in reversed(msgs)]
    return build_conversation_context_from_messages(snapshots)


def build_conversation_context_from_messages(
    messages: list[ConversationContextMessage],
) -> str:
    """Format danh sách snapshot thành block `[Lịch sử hội thoại]`."""
    if not messages:
        return ""

    lines = ["[Lịch sử hội thoại]"]
    for msg in messages:
        if msg.role == "user":
            label = "Người dùng"
            max_len = CONTEXT_USER_MSG_MAX_LEN
        else:
            label = "Trợ lý"
            max_len = CONTEXT_ASSISTANT_MSG_MAX_LEN

        content = msg.content.strip()
        if len(content) > max_len:
            content = content[:max_len] + "..."
        lines.append(f"{label}: {content}")

    return "\n".join(lines)


def extract_coordinates_from_structured_result(
    structured_result: dict[str, Any] | None,
) -> tuple[float | None, float | None]:
    """Lấy lat/lng từ structured_result dạng user_context."""
    if not structured_result:
        return None, None
    if structured_result.get("kind") != "user_context":
        return None, None
    data = structured_result.get("data") or {}
    lat = data.get("lat")
    lng = data.get("lng")
    return lat, lng


async def get_last_assistant_with_food_results(
    thread_id: uuid.UUID,
    exclude_msg_id: uuid.UUID,
    db: AsyncSession,
) -> ChatMessage | None:
    """Lấy assistant message gần nhất có food_results."""
    return await chat_repo.get_last_assistant_with_food_results(
        db,
        thread_id=thread_id,
        exclude_msg_id=exclude_msg_id,
    )


def get_last_message_by_role(
    messages: list[ConversationContextMessage],
    role: str,
) -> ConversationContextMessage | None:
    """Tìm message gần nhất theo role trong danh sách snapshot."""
    for msg in reversed(messages):
        if msg.role == role:
            return msg
    return None


def get_last_assistant_with_food_results_from_messages(
    messages: list[ConversationContextMessage],
) -> ConversationContextMessage | None:
    """Tìm assistant snapshot gần nhất có food_results."""
    for msg in reversed(messages):
        if msg.role == "assistant" and msg.food_results:
            return msg
    return None
