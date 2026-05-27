from __future__ import annotations

import uuid

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from app.db.session import Base


class FavoriteFood(Base):
    __tablename__ = "favorite_foods"
    __table_args__ = (
        # Mỗi user chỉ lưu 1 lần cho mỗi món
        UniqueConstraint("user_id", "food_id", name="uq_favorite_user_food"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    food_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    notes = Column(Text, nullable=False, default="")
    # Đánh giá 1-5 sao (nullable = chưa đánh giá)
    rating = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
