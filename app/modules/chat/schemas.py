from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field


from app.modules.places.schemas import FoodPlaceSearchResponse
from app.modules.search.schemas import SearchResponse


class ChatThreadCreate(BaseModel):
    """Tạo thread mới — title tuỳ chọn, nếu bỏ trống sẽ auto-gen từ tin nhắn đầu."""
    title: Optional[str] = None


class ChatThreadUpdate(BaseModel):
    """Cập nhật tiêu đề hoặc trạng thái ghim."""
    title: Optional[str] = None
    is_pinned: Optional[bool] = None


class ChatThreadResult(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    title: Optional[str] = None
    is_pinned: bool
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
    # Thống kê tổng hợp — tính khi query
    message_count: int = 0
    last_message_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ChatThreadListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[ChatThreadResult]


class ChatMessageResult(BaseModel):
    id: uuid.UUID
    thread_id: uuid.UUID
    role: str  # "user" | "assistant"
    content: str
    query_log_id: Optional[uuid.UUID] = None
    food_results: Optional[List[Dict[str, Any]]] = None
    structured_result: Optional[Dict[str, Any]] = None
    feedback: Optional[str] = None  # "like" | "dislike" | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatMessageListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[ChatMessageResult]


class MessageFeedbackRequest(BaseModel):
    """👍 / 👎 — gửi null để xoá feedback đã đặt."""
    feedback: Optional[Literal["like", "dislike"]] = Field(
        default=None,
        description="'like' hoặc 'dislike'. Gửi null để xoá feedback.",
    )


class MessageEditRequest(BaseModel):
    """Chỉnh sửa câu hỏi cũ và gửi lại."""
    query: str = Field(min_length=1, description="Nội dung câu hỏi sau khi chỉnh sửa")
    skip_profile: bool = Field(
        default=False,
        description="Bỏ qua hồ sơ sức khỏe cho lần tìm kiếm này",
    )
    lat: Optional[float] = Field(default=None, description="Vĩ độ GPS của người dùng")
    lng: Optional[float] = Field(default=None, description="Kinh độ GPS của người dùng")


class ChatSendMessageRequest(BaseModel):
    """Payload gửi tin nhắn mới — backend tự gọi search và lưu cả 2 chiều."""
    query: str = Field(min_length=1, description="Câu hỏi / yêu cầu của người dùng")
    skip_profile: bool = Field(
        default=False,
        description="Bỏ qua hồ sơ sức khỏe đã lưu cho lần tìm kiếm này",
    )
    lat: Optional[float] = Field(default=None, description="Vĩ độ GPS của người dùng")
    lng: Optional[float] = Field(default=None, description="Kinh độ GPS của người dùng")


class GuestChatHistoryItem(BaseModel):
    """Một mẩu lịch sử hội thoại do client guest tự giữ và gửi lên."""
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, description="Nội dung tin nhắn")
    food_results: Optional[List[Dict[str, Any]]] = None
    structured_result: Optional[Dict[str, Any]] = None


class GuestChatMessageResult(BaseModel):
    """Message trả về cho guest chat — không có persistence id/thread id."""
    role: str
    content: str
    food_results: Optional[List[Dict[str, Any]]] = None
    structured_result: Optional[Dict[str, Any]] = None


class GuestChatSendMessageRequest(BaseModel):
    """Payload public guest chat — dùng chung intent dispatcher nhưng không lưu thread."""
    query: str = Field(min_length=1, description="Câu hỏi / yêu cầu của người dùng")
    skip_profile: bool = Field(
        default=False,
        description="Bỏ qua hồ sơ sức khỏe nếu request đang kèm access token hợp lệ",
    )
    lat: Optional[float] = Field(default=None, description="Vĩ độ GPS của người dùng")
    lng: Optional[float] = Field(default=None, description="Kinh độ GPS của người dùng")
    history: List[GuestChatHistoryItem] = Field(
        default_factory=list,
        description="Lịch sử hội thoại gần nhất do client guest gửi kèm (cũ nhất trước).",
    )


class ChatSendMessageResponse(BaseModel):
    """Response sau khi gửi tin nhắn: trả cả 2 message + kết quả theo intent."""
    user_message: ChatMessageResult
    assistant_message: ChatMessageResult
    intent: Optional[str] = None
    search_result: Optional[SearchResponse] = None
    place_result: Optional[FoodPlaceSearchResponse] = None


class GuestChatSendMessageResponse(BaseModel):
    """Response cho guest chat — không phụ thuộc thread/message persistence."""
    user_message: GuestChatMessageResult
    assistant_message: GuestChatMessageResult
    intent: Optional[str] = None
    search_result: Optional[SearchResponse] = None
    place_result: Optional[FoodPlaceSearchResponse] = None


# ---------------------------------------------------------------------------
# Admin — Food schemas
# ---------------------------------------------------------------------------
