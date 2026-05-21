from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field


class FoodListItem(BaseModel):
    """Card món ăn trong danh sách thư viện — không cần raw_instructions để nhẹ response."""
    id: uuid.UUID
    name: str
    description: str
    img_url: Optional[str] = None
    core_ingredients: List[str]
    soft_tags: List[str]
    taste_profile: List[str]
    meal_context: List[str]
    occasion_context: List[str]
    # Nhóm nguyên liệu chính hiển thị trên UI (ví dụ: "Hải sản", "Thịt bò")
    primary_category: Optional[str] = None

    model_config = {"from_attributes": True}


class FoodListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[FoodListItem]


class FoodCategoryItem(BaseModel):
    """Một nhóm món ăn theo nguyên liệu chính (từ group_keys trong ALIAS_RULES)."""
    key: str          # group key không có prefix "group:", ví dụ: "hai_san"
    label: str        # Nhãn hiển thị, ví dụ: "Hải sản"
    count: int        # Số món thuộc nhóm này trong DB


class FoodCategoriesResponse(BaseModel):
    """Danh sách category để hiển thị trên UI (category browser / sidebar filter)."""
    categories: List[FoodCategoryItem]


class FoodDetailResponse(BaseModel):
    """Chi tiết đầy đủ một món ăn, bao gồm nguyên liệu và hướng dẫn nấu."""
    id: uuid.UUID
    name: str
    description: str
    img_url: Optional[str] = None
    core_ingredients: List[str]
    raw_ingredients: List[str]
    raw_instructions: str
    soft_tags: List[str]
    taste_profile: List[str]
    meal_context: List[str]
    occasion_context: List[str]
    # Trạng thái yêu thích của user hiện tại (None nếu chưa đăng nhập)
    is_favorite: Optional[bool] = None
    user_rating: Optional[int] = None
    user_notes: Optional[str] = None

    model_config = {"from_attributes": True}


class FilterGroup(BaseModel):
    label: str
    key: str
    options: List[str]


class FilterOptionsResponse(BaseModel):
    """Tất cả giá trị khả dụng cho từng bộ lọc — dùng để render filter panel ở UI."""
    taste_profile: List[str]
    meal_context: List[str]
    occasion_context: List[str]
    dish_type: List[str]
    diet_style: List[str]
    nutrition: List[str]
    texture: List[str]


# ---------------------------------------------------------------------------
# Favorite Foods schemas
# ---------------------------------------------------------------------------


class FoodDetail(BaseModel):
    """Thông tin đầy đủ của một món ăn — dùng trong FavoriteFoodResult và các nơi cần embed food."""
    id: uuid.UUID
    name: str
    description: str
    img_url: Optional[str] = None
    core_ingredients: List[str]
    raw_ingredients: List[str]
    raw_instructions: str
    soft_tags: List[str]
    taste_profile: List[str]
    meal_context: List[str]
    occasion_context: List[str]

    model_config = {"from_attributes": True}
