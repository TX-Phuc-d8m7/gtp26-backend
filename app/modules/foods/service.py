"""Food Library service: browse, filter, search, detail — không qua LLM."""

from __future__ import annotations

import uuid
from typing import List, Literal, Optional, Tuple

from sqlalchemy import Text, cast, func, or_, select, text
from sqlalchemy.dialects.postgresql import ARRAY as PgARRAY
from sqlalchemy.dialects.postgresql import array as pg_array
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.favorites.models import FavoriteFood
from app.modules.foods.models import Food
from app.modules.foods.schemas import (
    FilterOptionsResponse,
    FoodCategoryItem,
    FoodCategoriesResponse,
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
# Category (group_keys) — nguồn: ALIAS_RULES trong scripts/generate_ingredient_key_preview.py
#
# Chỉ expose các group có ý nghĩa nguyên liệu rõ ràng với người dùng cuối.
# Ẩn các group nội bộ dùng để lọc y tế (gia_vi_man_natri_cao, cay_kich_ung,
# ruou_bia, purine_vua, ...) — những group này không phù hợp để browse UI.
# ---------------------------------------------------------------------------

# Nhãn hiển thị cho từng group key (prefix "group:" đã lược bỏ làm key dict).
GROUP_KEY_DISPLAY_LABELS: dict[str, str] = {
    "group:ca_co_vay":              "Cá có vảy",
    "group:giap_xac":               "Tôm · Cua · Ghẹ",
    "group:than_mem":               "Mực · Bạch tuộc · Thân mềm",
    "group:hai_san":                "Hải sản",
    "group:thit_bo":                "Thịt bò",
    "group:thit_heo":               "Thịt heo",
    "group:thit_ga":                "Thịt gà",
    "group:thit_vit":               "Thịt vịt",
    "group:noitang":                "Nội tạng",
    "group:thit_che_bien_san":      "Thịt chế biến sẵn",
    "group:trung":                  "Trứng",
    "group:tinh_bot":               "Tinh bột · Ngũ cốc",
    "group:sua_va_che_pham_tu_sua": "Sữa · Phô mai · Bơ",
    "group:dau_nanh":               "Đậu nành & chế phẩm",
    "group:dau_phong":              "Đậu phộng",
    "group:hat_cay":                "Hạt cây",
    "group:me_vung":                "Mè · Vừng",
    "group:nam":                    "Nấm",
    "group:mang":                   "Măng",
    "group:gia_do":                 "Giá đỗ",
    "group:mam_len_men":            "Mắm · Nước chấm lên men",
}

# Thứ tự ưu tiên xác định primary_category: key nào xuất hiện đầu tiên trong
# danh sách này (và tồn tại trong core_ingredient_keys của món) sẽ được chọn.
# Sắp xếp từ cụ thể → tổng quát trong cùng nhóm (cá có vảy trước hải sản chung).
CATEGORY_PRIORITY: list[str] = [
    "group:ca_co_vay",
    "group:giap_xac",
    "group:than_mem",
    "group:hai_san",            # catch-all hải sản hỗn hợp
    "group:thit_bo",
    "group:thit_heo",
    "group:thit_ga",
    "group:thit_vit",
    "group:noitang",
    "group:thit_che_bien_san",
    "group:trung",
    "group:tinh_bot",
    "group:sua_va_che_pham_tu_sua",
    "group:dau_nanh",
    "group:dau_phong",
    "group:hat_cay",
    "group:me_vung",
    "group:nam",
    "group:mang",
    "group:gia_do",
    "group:mam_len_men",
]

_CATEGORY_PRIORITY_SET = set(CATEGORY_PRIORITY)


def get_primary_category(core_ingredient_keys: list[str] | None) -> str | None:
    """
    Trả về nhãn category chính của món dựa trên core_ingredient_keys.

    Ví dụ: ["base:ca_nuc", "canon:ca_nuc", "group:ca_co_vay", "group:hai_san"]
    → "Cá có vảy"  (group:ca_co_vay khớp trước group:hai_san trong CATEGORY_PRIORITY)
    """
    if not core_ingredient_keys:
        return None
    keys_set = set(core_ingredient_keys)
    for key in CATEGORY_PRIORITY:
        if key in keys_set:
            return GROUP_KEY_DISPLAY_LABELS[key]
    return None


async def get_food_categories(db: AsyncSession) -> FoodCategoriesResponse:
    """
    Đếm số món trong mỗi category dựa trên core_ingredient_keys.

    Dùng unnest() trong FROM clause (lateral join PostgreSQL) để mở rộng mảng
    thành hàng, rồi GROUP BY — tránh lỗi HAVING với set-returning functions.
    Chỉ trả về các category trong GROUP_KEY_DISPLAY_LABELS (ẩn group y tế nội bộ).
    """
    # Lấy số lượng theo từng group key trong DB
    result = await db.execute(text("""
        SELECT k, count(*)::int AS cnt
        FROM foods, unnest(core_ingredient_keys) AS k
        WHERE k LIKE 'group:%'
        GROUP BY k
    """))
    counts: dict[str, int] = {row.k: row.cnt for row in result.all()}

    # Duyệt theo CATEGORY_PRIORITY để giữ thứ tự hiển thị, lọc bỏ group nội bộ
    items: list[FoodCategoryItem] = []
    for key in CATEGORY_PRIORITY:
        label = GROUP_KEY_DISPLAY_LABELS.get(key)
        if label is None:
            continue
        cnt = counts.get(key, 0)
        if cnt == 0:
            continue  # Ẩn category chưa có dữ liệu
        items.append(FoodCategoryItem(
            key=key.removeprefix("group:"),
            label=label,
            count=cnt,
        ))

    return FoodCategoriesResponse(categories=items)


# ---------------------------------------------------------------------------
# Helper: filter ARRAY column chứa ít nhất 1 trong danh sách values (OR)
# ---------------------------------------------------------------------------

def _array_contains_any(column, values: List[str]):
    """
    WHERE column && ARRAY[values]::text[]
    Dùng toán tử overlap (&&) thay vì nhiều ANY() riêng lẻ.
    GIN index được tối ưu đặc biệt cho toán tử này — 1 index lookup duy nhất.

    cast(..., PgARRAY(Text())) bắt buộc để tránh lỗi:
      "operator does not exist: text[] && character varying[]"
    PostgreSQL không tự coerce VARCHAR[] → TEXT[] khi dùng toán tử &&.
    """
    return column.op("&&")(cast(pg_array(values), PgARRAY(Text())))


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
    category: Optional[str] = None,
    taste_profile: Optional[List[str]] = None,
    meal_context: Optional[List[str]] = None,
    occasion_context: Optional[List[str]] = None,
    dish_type: Optional[List[str]] = None,
    diet_style: Optional[List[str]] = None,
    nutrition: Optional[List[str]] = None,
    texture: Optional[List[str]] = None,
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

    # dish_type, diet_style, nutrition, texture, soft_tags đều lưu trong soft_tags
    combined_soft = []
    for group in [dish_type, diet_style, nutrition, texture, soft_tags]:
        if group:
            combined_soft.extend(group)
    if combined_soft:
        where_clauses.append(_array_contains_any(Food.soft_tags, combined_soft))

    # Lọc theo category (group_key) — dùng overlap operator &&
    # Frontend truyền suffix không có "group:" (ví dụ: "hai_san"), backend thêm prefix.
    if category:
        group_key = f"group:{category.strip()}" if not category.startswith("group:") else category.strip()
        if group_key in GROUP_KEY_DISPLAY_LABELS:
            where_clauses.append(
                _array_contains_any(Food.core_ingredient_keys, [group_key])
            )

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
            primary_category=get_primary_category(f.core_ingredient_keys),
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
