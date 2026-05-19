"""Food Library service: browse, filter, search, detail — không qua LLM."""

from __future__ import annotations

import uuid
from typing import List, Literal, Optional, Tuple

from sqlalchemy import Text, func, or_, select
from sqlalchemy.dialects.postgresql import array as pg_array
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FavoriteFood, Food
from app.schemas import (
    FilterOptionsResponse,
    FoodDetailResponse,
    FoodListItem,
)

# ---------------------------------------------------------------------------
# Hằng số filter options — đồng bộ với food_service.py
# ---------------------------------------------------------------------------

TASTE_PROFILE_OPTIONS = sorted([
    "Đậm đà", "Thanh đạm", "Chua", "Cay", "Mặn", "Ngọt", "Đắng", "Béo ngậy",
])

MEAL_CONTEXT_OPTIONS = ["Ăn sáng", "Ăn trưa", "Ăn chiều / xế", "Ăn tối", "Ăn khuya"]

OCCASION_CONTEXT_OPTIONS = sorted([
    "Ăn no", "Ăn vặt", "Mồi nhậu", "Tráng miệng",
    "Giải rượu", "Giải cảm", "Ấm bụng",
])

DISH_TYPE_OPTIONS = sorted([
    "Lẩu", "Nướng", "Hấp / Luộc", "Chiên / Rán", "Xào", "Rang",
    "Hầm / Ninh", "Kho/Rim", "Gỏi / Nộm / Trộn", "Cuốn / Gói",
    "Súp", "Cháo", "Món nước", "Món khô", "Nước sền sệt",
])

DIET_STYLE_OPTIONS = sorted([
    "Món chay", "Healthy / Eat Clean", "Ẩm thực đường phố",
    "Món Việt truyền thống", "Món Á", "Món Âu", "Thức ăn nhanh",
    "Đặc sản Đà Nẵng",
])

NUTRITION_OPTIONS = sorted([
    "Giàu chất xơ", "Giàu đạm", "Giàu vitamin", "Giàu tinh bột",
    "Từ sữa / Phô mai", "Thực phẩm chế biến sẵn", "Bánh ngọt",
    "Nội tạng", "Hải sản", "Dễ tiêu", "Khó tiêu / Nặng bụng",
    "Nhiều dầu mỡ / Calo cao",
])

TEXTURE_OPTIONS = sorted([
    "Nóng hổi", "Thanh mát/Giải nhiệt", "Món lạnh",
    "Giòn / Giòn rụm", "Dai / Sần sật", "Mềm", "Sống/Chín tái",
])

# ---------------------------------------------------------------------------
# Helper: filter ARRAY column chứa ít nhất 1 trong danh sách values (OR)
# ---------------------------------------------------------------------------

def _array_contains_any(column, values: List[str]):
    """
    WHERE column && ARRAY[values]
    Dùng toán tử overlap (&&) thay vì nhiều ANY() riêng lẻ.
    GIN index được tối ưu đặc biệt cho toán tử này — 1 index lookup duy nhất.
    """
    return column.op("&&")(pg_array(values, type_=Text()))


def _array_ilike(column, keyword: str):
    """
    Tìm kiếm keyword (không phân biệt hoa thường) trong ARRAY TEXT bằng cách
    join mảng thành chuỗi rồi ILIKE. Đủ chính xác cho MVP.
    """
    return func.array_to_string(column, ",").ilike(f"%{keyword}%")


# ---------------------------------------------------------------------------
# List với filter đầy đủ
# ---------------------------------------------------------------------------

async def list_foods(
    db: AsyncSession,
    *,
    q: Optional[str] = None,
    taste_profile: Optional[List[str]] = None,
    meal_context: Optional[List[str]] = None,
    occasion_context: Optional[List[str]] = None,
    dish_type: Optional[List[str]] = None,
    diet_style: Optional[List[str]] = None,
    nutrition: Optional[List[str]] = None,
    soft_tags: Optional[List[str]] = None,
    ingredients: Optional[List[str]] = None,
    sort_by: Literal["name", "relevance"] = "name",
    sort_order: Literal["asc", "desc"] = "asc",
    limit: int = 20,
    offset: int = 0,
) -> Tuple[int, List[FoodListItem]]:
    """
    Duyệt danh sách món ăn với filter đầy đủ — pure SQL, không LLM.

    Filter logic (tất cả điều kiện là AND với nhau, trong mỗi điều kiện là OR):
    - q           : tìm tên HOẶC mô tả (ILIKE)
    - taste_profile, meal_context, occasion_context, dish_type, diet_style,
      nutrition, soft_tags: multi-select, chứa BẤT KỲ giá trị nào được chọn
    - ingredients : tìm trong core_ingredients (ILIKE), BẤT KỲ nguyên liệu nào khớp

    Sort:
    - name        : alphabet
    - relevance   : tên bắt đầu bằng q trước → tên chứa q → còn lại (chỉ khi có q)
    """
    where_clauses = []

    # Tìm kiếm text tự do (tên + mô tả)
    if q:
        qs = q.strip()
        where_clauses.append(
            or_(
                Food.name.ilike(f"%{qs}%"),
                Food.description.ilike(f"%{qs}%"),
            )
        )

    # Filter ARRAY fields — OR logic trong từng nhóm
    if taste_profile:
        where_clauses.append(_array_contains_any(Food.taste_profile, taste_profile))
    if meal_context:
        where_clauses.append(_array_contains_any(Food.meal_context, meal_context))
    if occasion_context:
        where_clauses.append(_array_contains_any(Food.occasion_context, occasion_context))

    # dish_type, diet_style, nutrition, soft_tags đều lưu trong soft_tags
    combined_soft = []
    for group in [dish_type, diet_style, nutrition, soft_tags]:
        if group:
            combined_soft.extend(group)
    if combined_soft:
        where_clauses.append(_array_contains_any(Food.soft_tags, combined_soft))

    # Tìm theo nguyên liệu (ILIKE trong mảng core_ingredients)
    if ingredients:
        ing_clauses = [
            _array_ilike(Food.core_ingredients, ing.strip())
            for ing in ingredients
            if ing.strip()
        ]
        if ing_clauses:
            where_clauses.append(or_(*ing_clauses))

    # --- Count ---
    count_stmt = select(func.count()).select_from(Food)
    if where_clauses:
        count_stmt = count_stmt.where(*where_clauses)
    total = (await db.execute(count_stmt)).scalar_one()

    # --- Data ---
    data_stmt = select(Food)
    if where_clauses:
        data_stmt = data_stmt.where(*where_clauses)

    if sort_by == "relevance" and q:
        qs = q.strip()
        data_stmt = data_stmt.order_by(
            Food.name.ilike(f"{qs}%").desc(),   # bắt đầu bằng q
            Food.name.ilike(f"%{qs}%").desc(),  # tên chứa q
            Food.name.asc(),
        )
    elif sort_order == "desc":
        data_stmt = data_stmt.order_by(Food.name.desc())
    else:
        data_stmt = data_stmt.order_by(Food.name.asc())

    data_stmt = data_stmt.limit(limit).offset(offset)
    foods = (await db.execute(data_stmt)).scalars().all()

    return total, [
        FoodListItem(
            id=f.id,
            name=f.name,
            description=f.description,
            img_url=f.img_url,
            core_ingredients=f.core_ingredients or [],
            soft_tags=f.soft_tags or [],
            taste_profile=f.taste_profile or [],
            meal_context=f.meal_context or [],
            occasion_context=f.occasion_context or [],
        )
        for f in foods
    ]


# ---------------------------------------------------------------------------
# Detail một món ăn
# ---------------------------------------------------------------------------

async def get_food_detail(
    food_id: uuid.UUID,
    db: AsyncSession,
    user_id: Optional[uuid.UUID] = None,
) -> Optional[FoodDetailResponse]:
    """
    Trả đầy đủ thông tin món ăn (nguyên liệu + hướng dẫn nấu).
    Nếu user đã đăng nhập → bổ sung is_favorite / user_rating / user_notes.
    """
    food = await db.get(Food, food_id)
    if food is None:
        return None

    is_fav: Optional[bool] = None
    user_rating: Optional[int] = None
    user_notes: Optional[str] = None

    if user_id is not None:
        fav = (await db.execute(
            select(FavoriteFood).where(
                FavoriteFood.user_id == user_id,
                FavoriteFood.food_id == food_id,
            )
        )).scalar_one_or_none()
        is_fav = fav is not None
        if fav:
            user_rating = fav.rating
            user_notes = fav.notes

    return FoodDetailResponse(
        id=food.id,
        name=food.name,
        description=food.description,
        img_url=food.img_url,
        core_ingredients=food.core_ingredients or [],
        raw_ingredients=food.raw_ingredients or [],
        raw_instructions=food.raw_instructions or "",
        soft_tags=food.soft_tags or [],
        taste_profile=food.taste_profile or [],
        meal_context=food.meal_context or [],
        occasion_context=food.occasion_context or [],
        is_favorite=is_fav,
        user_rating=user_rating,
        user_notes=user_notes,
    )


# ---------------------------------------------------------------------------
# Filter options
# ---------------------------------------------------------------------------

def get_filter_options() -> FilterOptionsResponse:
    """Trả tất cả giá trị khả dụng cho từng bộ lọc — dùng để render UI filter panel."""
    return FilterOptionsResponse(
        taste_profile=TASTE_PROFILE_OPTIONS,
        meal_context=MEAL_CONTEXT_OPTIONS,
        occasion_context=OCCASION_CONTEXT_OPTIONS,
        dish_type=DISH_TYPE_OPTIONS,
        diet_style=DIET_STYLE_OPTIONS,
        nutrition=NUTRITION_OPTIONS,
        texture=TEXTURE_OPTIONS,
    )
