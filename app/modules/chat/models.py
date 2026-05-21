from __future__ import annotations

import uuid

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from app.db.session import Base


class ChatThread(Base):
    __tablename__ = "chat_threads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    # Tiêu đề thread — auto-gen từ tin nhắn đầu tiên nếu user không đặt
    title = Column(Text, nullable=True)
    is_pinned = Column(Boolean, nullable=False, default=False)
    # Soft delete — không xóa khỏi DB, chỉ ẩn khỏi list
    is_deleted = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    # "user" | "assistant"
    role = Column(String, nullable=False)
    # Nội dung tin nhắn: câu hỏi user hoặc lời tư vấn AI
    content = Column(Text, nullable=False)
    # Liên kết tới QueryLog để tra cứu chi tiết kết quả tìm kiếm
    query_log_id = Column(UUID(as_uuid=True), nullable=True)
    # Danh sách món gợi ý (serialized FoodResult) — chỉ có ở assistant messages
    food_results = Column(JSONB, nullable=True)
    # Payload có cấu trúc cho multi-intent chat (food/place/safety/info/...)
    structured_result = Column(JSONB, nullable=True)
    # Phản hồi của user với tin nhắn AI: "like" | "dislike" | None
    feedback = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
