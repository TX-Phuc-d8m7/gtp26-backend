from __future__ import annotations

import uuid

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from app.db.session import Base


class RefreshToken(Base):
    """Lưu refresh token (đã hash) để hỗ trợ stateful refresh + revoke khi logout."""

    __tablename__ = "refresh_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    # Lưu SHA-256 hash của token, không lưu raw token
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PasswordResetToken(Base):
    """Token dùng một lần để reset mật khẩu (thông thường gửi qua email)."""

    __tablename__ = "password_reset_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, nullable=False, unique=True, index=True)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    # role: "user" | "admin"
    role = Column(String, nullable=False, default="user")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class UserHealthProfile(Base):
    __tablename__ = "user_health_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Mỗi user chỉ có 1 profile — unique constraint
    user_id = Column(UUID(as_uuid=True), nullable=False, unique=True, index=True)

    # Bệnh lý / triệu chứng (chọn từ HEALTH_CONDITION_OPTIONS)
    # VD: ["Cao huyết áp", "Gout"]
    health_conditions = Column(ARRAY(Text), nullable=False, default=[])
    # Dị ứng thực phẩm (chọn từ ALLERGY_OPTIONS)
    # VD: ["Dị ứng động vật giáp xác", "Dị ứng trứng"]
    allergies = Column(ARRAY(Text), nullable=False, default=[])
    # Nguyên liệu ưa thích (chọn từ PREFERRED_INGREDIENT_OPTIONS)
    # VD: ["Gà", "Tôm", "Nấm"]
    preferred_ingredients = Column(ARRAY(Text), nullable=False, default=[])
    # Khẩu vị yêu thích (chọn từ TASTE_PROFILE_OPTIONS — map tới TASTE_PROFILE_TAGS)
    # VD: ["Cay", "Đậm đà"]
    taste_profile = Column(ARRAY(Text), nullable=False, default=[])
    # Cách nấu yêu thích (chọn từ DISH_TYPE_OPTIONS — map tới valid_soft_tags)
    # VD: ["Nướng", "Hấp / Luộc"]
    dish_preferences = Column(ARRAY(Text), nullable=False, default=[])

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
