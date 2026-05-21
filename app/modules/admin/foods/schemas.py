from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field


class AdminFoodCreate(BaseModel):
    """Payload tạo món ăn mới. Sau khi save, hệ thống tự sinh core_ingredient_keys và embedding."""
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    img_url: Optional[str] = None
    core_ingredients: List[str] = Field(default_factory=list, description="Nguyên liệu chính (không có định lượng)")
    raw_ingredients: List[str] = Field(default_factory=list, description="Nguyên liệu đầy đủ với định lượng")
    raw_instructions: str = Field(default="", description="Các bước hướng dẫn nấu")
    soft_tags: List[str] = Field(default_factory=list)
    taste_profile: List[str] = Field(default_factory=list)
    meal_context: List[str] = Field(default_factory=list)
    occasion_context: List[str] = Field(default_factory=list)


class AdminFoodUpdate(BaseModel):
    """Payload cập nhật món ăn (PATCH — chỉ gửi field cần thay đổi)."""
    name: Optional[str] = None
    description: Optional[str] = None
    img_url: Optional[str] = None
    core_ingredients: Optional[List[str]] = None
    raw_ingredients: Optional[List[str]] = None
    raw_instructions: Optional[str] = None
    soft_tags: Optional[List[str]] = None
    taste_profile: Optional[List[str]] = None
    meal_context: Optional[List[str]] = None
    occasion_context: Optional[List[str]] = None


class AdminFoodResult(BaseModel):
    """Chi tiết đầy đủ món ăn trong context admin (bao gồm core_ingredient_keys và trạng thái embedding)."""
    id: uuid.UUID
    name: str
    description: str
    img_url: Optional[str] = None
    core_ingredients: List[str]
    raw_ingredients: List[str]
    raw_instructions: str
    core_ingredient_keys: List[str]
    soft_tags: List[str]
    taste_profile: List[str]
    meal_context: List[str]
    occasion_context: List[str]
    has_embedding: bool = False  # True nếu vector embedding đã được sinh

    model_config = {"from_attributes": True}


class AdminFoodListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[AdminFoodResult]


class FoodImageUploadResponse(BaseModel):
    food_id: uuid.UUID
    img_url: str


class RebuildEmbeddingResponse(BaseModel):
    food_id: uuid.UUID
    success: bool
    message: str


class RebuildAllEmbeddingsResponse(BaseModel):
    total: int
    success: int
    failed: int
    failed_names: List[str]


# ---------------------------------------------------------------------------
# Admin — Tag / Medical Rule schemas
# ---------------------------------------------------------------------------


class FoodImportItem(BaseModel):
    """Schema một món ăn trong file JSON import."""
    name: str
    description: str
    img_url: Optional[str] = None
    core_ingredients: List[str] = Field(default_factory=list)
    raw_ingredients: List[str] = Field(default_factory=list)
    raw_instructions: str = ""
    soft_tags: List[str] = Field(default_factory=list)
    taste_profile: List[str] = Field(default_factory=list)
    meal_context: List[str] = Field(default_factory=list)
    occasion_context: List[str] = Field(default_factory=list)


class FoodImportPreviewResponse(BaseModel):
    """Kết quả dry-run import — chưa lưu vào DB."""
    total_in_file: int
    valid_count: int
    duplicate_names: List[str]  # Tên đã tồn tại trong DB
    invalid_items: List[Dict[str, Any]]  # Items lỗi validation
    preview_items: List[FoodImportItem]  # Items hợp lệ sẽ được import


class FoodImportApplyResponse(BaseModel):
    """Kết quả sau khi áp dụng import."""
    imported_count: int
    skipped_duplicates: int
    failed_count: int
    failed_names: List[str]


# ---------------------------------------------------------------------------
# Auth schemas
# ---------------------------------------------------------------------------
