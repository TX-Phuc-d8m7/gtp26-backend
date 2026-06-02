from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field


# ---------------------------------------------------------------------------
# Onboarding options (constants — trả về từ GET /users/me/onboarding-options)
# ---------------------------------------------------------------------------

HEALTH_CONDITION_OPTIONS: list[str] = [
    # Bệnh lý
    "Béo phì",
    "Cao huyết áp",
    "Gout",
    "Tim mạch",
    "Tiểu đường",
    "Viêm loét dạ dày",
    # Triệu chứng / Tình trạng
    "Bệnh lý hô hấp trên (Ho/Viêm họng/Cảm/Amidan)",
    "Đầy bụng / Khó tiêu",
    "Nhiệt miệng / Loét miệng",
]

ALLERGY_OPTIONS: list[str] = [
    "Dị ứng cá có vây",
    "Dị ứng động vật giáp xác",
    "Dị ứng động vật thân mềm",
    "Dị ứng đậu phộng",
    "Dị ứng sữa bò",
    "Dị ứng trứng",
]

PREFERRED_INGREDIENT_OPTIONS: list[str] = [
    "Bò",
    "Gà",
    "Heo",
    "Mực",
    "Nấm",
    "Rau",
    "Tôm",
    "Vịt",
]

TASTE_PROFILE_OPTIONS: list[str] = [
    "Béo ngậy",
    "Cay",
    "Chua",
    "Đắng",
    "Đậm đà",
    "Mặn",
    "Ngọt",
    "Thanh đạm",
]

DISH_TYPE_OPTIONS: list[str] = sorted([
    "Cháo",
    "Chiên / Rán",
    "Cuốn / Gói",
    "Gỏi / Nộm / Trộn",
    "Hầm / Ninh",
    "Hấp / Luộc",
    "Kho / Rim",
    "Lẩu",
    "Món khô",
    "Món nước",
    "Nước sền sệt",
    "Nướng",
    "Rang",
    "Súp",
    "Xào",
])


# ---------------------------------------------------------------------------
# User account schemas
# ---------------------------------------------------------------------------

class UserAccountUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = Field(default=None, max_length=120)


class UserDeactivateResponse(BaseModel):
    success: bool
    message: str


class UserResult(BaseModel):
    id: uuid.UUID
    email: str
    full_name: Optional[str] = None
    role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# User Health Profile schemas
# ---------------------------------------------------------------------------

class UserHealthProfileCreate(BaseModel):
    """Dùng cho PUT — thay thế toàn bộ profile."""
    health_conditions: List[str] = Field(
        default_factory=list,
        description="Bệnh lý / triệu chứng, chọn từ HEALTH_CONDITION_OPTIONS",
    )
    allergies: List[str] = Field(
        default_factory=list,
        description="Dị ứng thực phẩm, chọn từ ALLERGY_OPTIONS",
    )
    preferred_ingredients: List[str] = Field(
        default_factory=list,
        description="Nguyên liệu ưa thích, chọn từ PREFERRED_INGREDIENT_OPTIONS",
    )
    taste_profile: List[str] = Field(
        default_factory=list,
        description="Khẩu vị yêu thích, chọn từ TASTE_PROFILE_OPTIONS",
    )
    dish_preferences: List[str] = Field(
        default_factory=list,
        description="Cách nấu yêu thích, chọn từ DISH_TYPE_OPTIONS",
    )


class UserHealthProfileUpdate(BaseModel):
    """Dùng cho PATCH — chỉ cập nhật các field được gửi lên."""
    health_conditions: Optional[List[str]] = None
    allergies: Optional[List[str]] = None
    preferred_ingredients: Optional[List[str]] = None
    taste_profile: Optional[List[str]] = None
    dish_preferences: Optional[List[str]] = None


class UserHealthProfileResult(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    health_conditions: List[str]
    allergies: List[str]
    preferred_ingredients: List[str]
    taste_profile: List[str]
    dish_preferences: List[str]
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Onboarding options response schema
# ---------------------------------------------------------------------------

class OnboardingOptionsResponse(BaseModel):
    health_conditions: List[str]
    allergies: List[str]
    preferred_ingredients: List[str]
    taste_profile: List[str]
    dish_preferences: List[str]
