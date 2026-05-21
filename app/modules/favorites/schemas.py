from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field


from app.modules.foods.schemas import FoodDetail


class FavoriteFoodCreate(BaseModel):
    food_id: uuid.UUID = Field(description="ID của món ăn muốn lưu yêu thích")
    notes: str = Field(default="", description="Ghi chú tuỳ chọn, ví dụ: 'Ăn trưa hợp'")
    rating: Optional[int] = Field(default=None, ge=1, le=5, description="Đánh giá 1–5 sao (để trống nếu chưa muốn đánh giá)")


class FavoriteFoodUpdate(BaseModel):
    notes: Optional[str] = Field(default=None, description="Cập nhật ghi chú")
    rating: Optional[int] = Field(default=None, ge=1, le=5, description="Cập nhật đánh giá 1–5 sao")


class FavoriteFoodResult(BaseModel):
    id: uuid.UUID
    food_id: uuid.UUID
    notes: str
    rating: Optional[int] = None
    created_at: datetime
    food: FoodDetail

    model_config = {"from_attributes": True}


class FavoriteListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[FavoriteFoodResult]


class ShoppingListResponse(BaseModel):
    food_count: int
    ingredient_count: int
    ingredients: List[str]


class FavoriteRecommendationResult(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    img_url: Optional[str] = None
    soft_tags: List[str]
    taste_profile: List[str]
    meal_context: List[str]
    similarity_score: float = Field(description="Độ tương đồng embedding với nhóm yêu thích (0–1)")


# ---------------------------------------------------------------------------
# Chat History schemas
# ---------------------------------------------------------------------------
