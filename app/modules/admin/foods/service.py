"""Admin Food service — CRUD, image upload, rebuild keys/embedding."""

from __future__ import annotations

import uuid
from typing import List, Literal, Optional, Tuple

from sqlalchemy import Text, func, or_, select
from sqlalchemy.dialects.postgresql import array as pg_array
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.foods.models import Food
from app.modules.admin.foods.schemas import (
    AdminFoodCreate,
    AdminFoodResult,
    AdminFoodUpdate,
)
from app.integrations.vertex_ai import rebuild_single_food_embedding
from app.modules.ingredients.service import (
    generate_core_ingredient_keys,
    load_enabled_alias_override_rules,
)
from app.integrations.google_storage import delete_food_image, upload_food_image


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _array_contains_any(column, values: List[str]):
    """WHERE column && ARRAY[values]  — dùng GIN index tối ưu."""
    return column.op("&&")(pg_array(values, type_=Text()))


def _array_ilike(column, keyword: str):
    """Tìm keyword trong ARRAY TEXT bằng array_to_string + ILIKE."""
    return func.array_to_string(column, ",").ilike(f"%{keyword}%")


def _to_result(food: Food) -> AdminFoodResult:
    return AdminFoodResult(
        id=food.id,
        name=food.name,
        description=food.description,
        img_url=food.img_url,
        core_ingredients=food.core_ingredients or [],
        raw_ingredients=food.raw_ingredients or [],
        raw_instructions=food.raw_instructions or "",
        core_ingredient_keys=food.core_ingredient_keys or [],
        soft_tags=food.soft_tags or [],
        taste_profile=food.taste_profile or [],
        meal_context=food.meal_context or [],
        occasion_context=food.occasion_context or [],
        has_embedding=bool(food.embedding),
        dining_context=food.dining_context,
    )


async def _rebuild_keys(food: Food, db: AsyncSession) -> None:
    """Sinh lại core_ingredient_keys từ core_ingredients + alias override rules."""
    extra_rules = await load_enabled_alias_override_rules(db)
    food.core_ingredient_keys = generate_core_ingredient_keys(
        food.core_ingredients or [],
        extra_rules=extra_rules,
    )


# ---------------------------------------------------------------------------
# List / Search
# ---------------------------------------------------------------------------

async def list_foods_admin(
    db: AsyncSession,
    *,
    # --- Filters giống user (food_library_service) ---
    q: Optional[str] = None,
    taste_profile: Optional[List[str]] = None,
    meal_context: Optional[List[str]] = None,
    occasion_context: Optional[List[str]] = None,
    dish_type: Optional[List[str]] = None,
    diet_style: Optional[List[str]] = None,
    nutrition: Optional[List[str]] = None,
    soft_tags: Optional[List[str]] = None,
    ingredients: Optional[List[str]] = None,
    # --- Filter riêng của admin ---
    has_embedding: Optional[bool] = None,
    # --- Sort & Pagination ---
    sort_by: Literal["name", "relevance"] = "name",
    sort_order: Literal["asc", "desc"] = "asc",
    limit: int = 20,
    offset: int = 0,
) -> Tuple[int, List[AdminFoodResult]]:
    """
    Danh sách món ăn cho trang admin — filter đầy đủ như user, cộng thêm:
    - `has_embedding`: lọc món có/chưa có embedding vector.

    Filter logic (các điều kiện AND với nhau, trong mỗi nhóm là OR):
    - q              : tên HOẶC mô tả (ILIKE)
    - taste_profile  : && trên cột taste_profile (GIN)
    - meal_context   : && trên cột meal_context (GIN)
    - occasion_context: && trên cột occasion_context (GIN)
    - dish_type, diet_style, nutrition, soft_tags: merge vào && trên cột soft_tags (GIN)
    - ingredients    : ILIKE trong core_ingredients (BẤT KỲ nguyên liệu nào khớp)
    - has_embedding  : IS NOT NULL / IS NULL trên cột embedding
    """
    where: list = []

    # Tìm kiếm text tự do
    if q:
        qs = q.strip()
        where.append(or_(Food.name.ilike(f"%{qs}%"), Food.description.ilike(f"%{qs}%")))

    # Filter ARRAY fields
    if taste_profile:
        where.append(_array_contains_any(Food.taste_profile, taste_profile))
    if meal_context:
        where.append(_array_contains_any(Food.meal_context, meal_context))
    if occasion_context:
        where.append(_array_contains_any(Food.occasion_context, occasion_context))

    # dish_type + diet_style + nutrition + soft_tags đều nằm trong cột soft_tags
    combined_soft: List[str] = []
    for group in [dish_type, diet_style, nutrition, soft_tags]:
        if group:
            combined_soft.extend(group)
    if combined_soft:
        where.append(_array_contains_any(Food.soft_tags, combined_soft))

    # Filter nguyên liệu (ILIKE, BẤT KỲ nguyên liệu nào khớp)
    if ingredients:
        ing_clauses = [
            _array_ilike(Food.core_ingredients, ing.strip())
            for ing in ingredients
            if ing.strip()
        ]
        if ing_clauses:
            where.append(or_(*ing_clauses))

    # Filter riêng admin — embedding status
    if has_embedding is True:
        where.append(Food.embedding.isnot(None))
    elif has_embedding is False:
        where.append(Food.embedding.is_(None))

    # --- Count ---
    count_stmt = select(func.count()).select_from(Food)
    if where:
        count_stmt = count_stmt.where(*where)
    total = (await db.execute(count_stmt)).scalar_one()

    # --- Data ---
    data_stmt = select(Food)
    if where:
        data_stmt = data_stmt.where(*where)

    if sort_by == "relevance" and q:
        qs = q.strip()
        data_stmt = data_stmt.order_by(
            Food.name.ilike(f"{qs}%").desc(),   # tên bắt đầu bằng q
            Food.name.ilike(f"%{qs}%").desc(),  # tên chứa q
            Food.name.asc(),
        )
    elif sort_order == "desc":
        data_stmt = data_stmt.order_by(Food.name.desc())
    else:
        data_stmt = data_stmt.order_by(Food.name.asc())

    foods = (await db.execute(data_stmt.limit(limit).offset(offset))).scalars().all()
    return total, [_to_result(f) for f in foods]


# ---------------------------------------------------------------------------
# Get detail
# ---------------------------------------------------------------------------

async def get_food_admin(food_id: uuid.UUID, db: AsyncSession) -> Optional[AdminFoodResult]:
    food = await db.get(Food, food_id)
    return _to_result(food) if food else None


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

async def create_food(
    data: AdminFoodCreate,
    db: AsyncSession,
    auto_embed: bool = True,
) -> AdminFoodResult:
    """
    Tạo món ăn mới:
    1. Lưu vào DB.
    2. Tự động sinh core_ingredient_keys.
    3. Tự động sinh embedding (nếu auto_embed=True).
    """
    food = Food(
        name=data.name,
        description=data.description,
        img_url=data.img_url,
        core_ingredients=data.core_ingredients,
        raw_ingredients=data.raw_ingredients,
        raw_instructions=data.raw_instructions,
        soft_tags=data.soft_tags,
        taste_profile=data.taste_profile,
        meal_context=data.meal_context,
        occasion_context=data.occasion_context,
        dining_context=data.dining_context or "both",
    )
    db.add(food)
    await db.flush()  # lấy food.id

    # Sinh keys
    await _rebuild_keys(food, db)
    await db.commit()
    await db.refresh(food)

    # Sinh embedding (có thể tắt khi import hàng loạt để tự trigger riêng)
    if auto_embed:
        await rebuild_single_food_embedding(food, db)
        await db.refresh(food)

    return _to_result(food)


# ---------------------------------------------------------------------------
# Update (PATCH)
# ---------------------------------------------------------------------------

async def update_food(
    food_id: uuid.UUID,
    data: AdminFoodUpdate,
    db: AsyncSession,
) -> Optional[AdminFoodResult]:
    """
    Cập nhật thông tin món ăn.
    - Nếu core_ingredients thay đổi → rebuild keys tự động.
    - Nếu bất kỳ field nội dung nào thay đổi → rebuild embedding tự động.
    """
    food = await db.get(Food, food_id)
    if food is None:
        return None

    # Track xem có cần rebuild không
    need_rebuild_keys   = False
    need_rebuild_embed  = False

    if data.name is not None and data.name != food.name:
        food.name = data.name
        need_rebuild_embed = True
    if data.description is not None and data.description != food.description:
        food.description = data.description
        need_rebuild_embed = True
    if data.img_url is not None:
        food.img_url = data.img_url
    if data.raw_ingredients is not None:
        food.raw_ingredients = data.raw_ingredients
    if data.raw_instructions is not None:
        food.raw_instructions = data.raw_instructions
    if data.core_ingredients is not None and data.core_ingredients != food.core_ingredients:
        food.core_ingredients = data.core_ingredients
        need_rebuild_keys  = True
        need_rebuild_embed = True
    if data.soft_tags is not None and data.soft_tags != food.soft_tags:
        food.soft_tags = data.soft_tags
        need_rebuild_embed = True
    if data.taste_profile is not None and data.taste_profile != food.taste_profile:
        food.taste_profile = data.taste_profile
        need_rebuild_embed = True
    if data.meal_context is not None and data.meal_context != food.meal_context:
        food.meal_context = data.meal_context
        need_rebuild_embed = True
    if data.occasion_context is not None and data.occasion_context != food.occasion_context:
        food.occasion_context = data.occasion_context
        need_rebuild_embed = True
    if data.dining_context is not None:
        food.dining_context = data.dining_context

    if need_rebuild_keys:
        await _rebuild_keys(food, db)

    await db.commit()
    await db.refresh(food)

    if need_rebuild_embed:
        await rebuild_single_food_embedding(food, db)
        await db.refresh(food)

    return _to_result(food)


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

async def delete_food(food_id: uuid.UUID, db: AsyncSession) -> bool:
    """
    Xóa vĩnh viễn món ăn.
    Ảnh trên GCS cũng bị xóa nếu URL thuộc bucket của hệ thống.
    """
    food = await db.get(Food, food_id)
    if food is None:
        return False

    # Xóa ảnh trên GCS nếu có
    if food.img_url:
        delete_food_image(food.img_url)

    await db.delete(food)
    await db.commit()
    return True


# ---------------------------------------------------------------------------
# Image upload
# ---------------------------------------------------------------------------

async def upload_image_for_food(
    food_id: uuid.UUID,
    file_content: bytes,
    original_filename: str,
    content_type: str,
    db: AsyncSession,
) -> Optional[str]:
    """
    Upload ảnh mới lên GCS và cập nhật img_url của món ăn.
    Xóa ảnh cũ nếu tồn tại.
    Trả None nếu food không tồn tại.
    """
    food = await db.get(Food, food_id)
    if food is None:
        return None

    # Xóa ảnh cũ nếu có
    if food.img_url:
        delete_food_image(food.img_url)

    # Upload ảnh mới (dùng food_id làm tên file để overwrite khi upload lại)
    new_url = upload_food_image(
        file_content=file_content,
        original_filename=original_filename,
        content_type=content_type,
        food_id=str(food_id),
    )

    food.img_url = new_url
    await db.commit()
    return new_url


# ---------------------------------------------------------------------------
# Rebuild keys / embedding
# ---------------------------------------------------------------------------

async def rebuild_keys_for_food(
    food_id: uuid.UUID,
    db: AsyncSession,
) -> Optional[AdminFoodResult]:
    """Sinh lại core_ingredient_keys cho một món. Trả None nếu không tìm thấy."""
    food = await db.get(Food, food_id)
    if food is None:
        return None

    await _rebuild_keys(food, db)
    await db.commit()
    await db.refresh(food)
    return _to_result(food)


async def rebuild_embedding_for_food(
    food_id: uuid.UUID,
    db: AsyncSession,
) -> Tuple[bool, str]:
    """
    Sinh lại embedding cho một món.
    Returns: (success, message)
    """
    food = await db.get(Food, food_id)
    if food is None:
        return False, "Không tìm thấy món ăn."

    success = await rebuild_single_food_embedding(food, db)
    if success:
        return True, f"Đã sinh lại embedding cho '{food.name}'."
    return False, f"Sinh embedding thất bại cho '{food.name}'. Kiểm tra kết nối Gemini API."


# ---------------------------------------------------------------------------
# Import foods from JSON
# ---------------------------------------------------------------------------

async def import_foods_preview(
    items: list,
    db: AsyncSession,
) -> dict:
    """
    Dry-run import: validate và kiểm tra trùng lặp, chưa lưu vào DB.
    """
    from app.modules.admin.foods.schemas import FoodImportItem
    from pydantic import ValidationError

    # Lấy tên đã có trong DB
    existing_names = set(
        (await db.execute(select(Food.name))).scalars().all()
    )

    valid_items    = []
    duplicate_names = []
    invalid_items  = []

    for i, raw in enumerate(items):
        try:
            item = FoodImportItem(**raw) if isinstance(raw, dict) else raw
            if item.name in existing_names:
                duplicate_names.append(item.name)
            else:
                valid_items.append(item)
        except Exception as e:
            invalid_items.append({"index": i, "error": str(e), "data": raw})

    return {
        "total_in_file":     len(items),
        "valid_count":       len(valid_items),
        "duplicate_names":   duplicate_names,
        "invalid_items":     invalid_items,
        "preview_items":     valid_items,
    }


async def import_foods_apply(
    items: list,
    db: AsyncSession,
    skip_embedding: bool = False,
) -> dict:
    """
    Áp dụng import: lưu các món hợp lệ vào DB.
    Bỏ qua món đã trùng tên.
    """
    from app.modules.admin.foods.schemas import FoodImportItem

    existing_names = set(
        (await db.execute(select(Food.name))).scalars().all()
    )
    extra_rules = await load_enabled_alias_override_rules(db)

    imported = 0
    skipped  = 0
    failed   = 0
    failed_names: List[str] = []

    for raw in items:
        try:
            item = FoodImportItem(**raw) if isinstance(raw, dict) else raw

            if item.name in existing_names:
                skipped += 1
                continue

            data = AdminFoodCreate(**item.model_dump())
            await create_food(data, db, auto_embed=not skip_embedding)
            existing_names.add(item.name)
            imported += 1
        except Exception as e:
            failed += 1
            name = raw.get("name", "unknown") if isinstance(raw, dict) else getattr(raw, "name", "unknown")
            failed_names.append(name)
            print(f"[IMPORT] Lỗi khi import '{name}': {e}")

    return {
        "imported_count":     imported,
        "skipped_duplicates": skipped,
        "failed_count":       failed,
        "failed_names":       failed_names,
    }
