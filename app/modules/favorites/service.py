"""Favorite Foods service: thêm, xóa, list, rating, filter/sort, recommendations, shopping list."""

from __future__ import annotations

import uuid
from typing import List, Literal, Optional, Tuple

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FavoriteFood, Food
from app.schemas import (
    FavoriteFoodResult,
    FavoriteFoodUpdate,
    FavoriteRecommendationResult,
    FoodDetail,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _build_food_detail(food: Food) -> FoodDetail:
    """Chuyển Food ORM object → FoodDetail schema (đầy đủ thông tin)."""
    return FoodDetail(
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
    )


def _build_result(fav: FavoriteFood, food: Food) -> FavoriteFoodResult:
    return FavoriteFoodResult(
        id=fav.id,
        food_id=fav.food_id,
        notes=fav.notes,
        rating=fav.rating,
        created_at=fav.created_at,
        food=_build_food_detail(food),
    )


# ---------------------------------------------------------------------------
# List với filter / sort
# ---------------------------------------------------------------------------

async def list_favorites(
    user_id: uuid.UUID,
    db: AsyncSession,
    *,
    limit: int = 20,
    offset: int = 0,
    q: Optional[str] = None,
    meal_context: Optional[str] = None,
    taste_profile: Optional[str] = None,
    rated_only: bool = False,
    sort_by: Literal["created_at", "name", "rating"] = "created_at",
    sort_order: Literal["asc", "desc"] = "desc",
) -> Tuple[int, List[FavoriteFoodResult]]:
    """
    Danh sách món yêu thích với filter và sort.

    - q: tìm theo tên món (không phân biệt hoa thường)
    - meal_context: lọc theo bữa ăn (e.g. "Ăn sáng")
    - taste_profile: lọc theo khẩu vị (e.g. "Thanh đạm")
    - rated_only: chỉ hiện những món đã được đánh giá
    - sort_by: created_at | name | rating
    - sort_order: asc | desc
    """
    base_where = [FavoriteFood.user_id == user_id]

    # Filter: từ khoá tên món
    if q:
        base_where.append(Food.name.ilike(f"%{q}%"))

    # Filter: bữa ăn (meal_context là ARRAY — kiểm tra có chứa giá trị không)
    if meal_context:
        base_where.append(Food.meal_context.any(meal_context))

    # Filter: khẩu vị
    if taste_profile:
        base_where.append(Food.taste_profile.any(taste_profile))

    # Filter: chỉ món đã đánh giá
    if rated_only:
        base_where.append(FavoriteFood.rating.is_not(None))

    # --- Sort ---
    if sort_by == "name":
        order_col = Food.name.asc() if sort_order == "asc" else Food.name.desc()
    elif sort_by == "rating":
        # Món chưa đánh giá (NULL) xếp cuối
        order_col = (
            FavoriteFood.rating.asc().nulls_last()
            if sort_order == "asc"
            else FavoriteFood.rating.desc().nulls_last()
        )
    else:  # created_at (default)
        order_col = (
            FavoriteFood.created_at.asc()
            if sort_order == "asc"
            else FavoriteFood.created_at.desc()
        )

    # Count
    count_stmt = (
        select(func.count())
        .select_from(FavoriteFood)
        .join(Food, Food.id == FavoriteFood.food_id)
        .where(*base_where)
    )
    total = (await db.execute(count_stmt)).scalar_one()

    # Data
    stmt = (
        select(FavoriteFood, Food)
        .join(Food, Food.id == FavoriteFood.food_id)
        .where(*base_where)
        .order_by(order_col)
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).all()

    items = [_build_result(fav, food) for fav, food in rows]
    return total, items


# ---------------------------------------------------------------------------
# Add / Update / Remove / Check
# ---------------------------------------------------------------------------

async def add_favorite(
    user_id: uuid.UUID,
    food_id: uuid.UUID,
    notes: str,
    rating: Optional[int],
    db: AsyncSession,
) -> FavoriteFoodResult:
    """Thêm món vào yêu thích. Raise ValueError nếu món không tồn tại hoặc đã lưu rồi."""
    food = await db.get(Food, food_id)
    if food is None:
        raise ValueError(f"Món ăn với id={food_id} không tồn tại.")

    existing = (await db.execute(
        select(FavoriteFood).where(
            FavoriteFood.user_id == user_id,
            FavoriteFood.food_id == food_id,
        )
    )).scalar_one_or_none()

    if existing is not None:
        raise ValueError("Món ăn này đã có trong danh sách yêu thích.")

    fav = FavoriteFood(
        user_id=user_id,
        food_id=food_id,
        notes=notes or "",
        rating=rating,
    )
    db.add(fav)
    await db.commit()
    await db.refresh(fav)
    return _build_result(fav, food)


async def update_favorite(
    user_id: uuid.UUID,
    food_id: uuid.UUID,
    data: FavoriteFoodUpdate,
    db: AsyncSession,
) -> Optional[FavoriteFoodResult]:
    """Cập nhật notes và/hoặc rating. Trả None nếu không tìm thấy."""
    result = await db.execute(
        select(FavoriteFood, Food)
        .join(Food, Food.id == FavoriteFood.food_id)
        .where(
            FavoriteFood.user_id == user_id,
            FavoriteFood.food_id == food_id,
        )
    )
    row = result.one_or_none()
    if row is None:
        return None

    fav, food = row
    if data.notes is not None:
        fav.notes = data.notes
    if data.rating is not None:
        fav.rating = data.rating

    await db.commit()
    await db.refresh(fav)
    return _build_result(fav, food)


async def remove_favorite(
    user_id: uuid.UUID,
    food_id: uuid.UUID,
    db: AsyncSession,
) -> bool:
    """Xóa món khỏi yêu thích. Trả True nếu xóa thành công."""
    fav = (await db.execute(
        select(FavoriteFood).where(
            FavoriteFood.user_id == user_id,
            FavoriteFood.food_id == food_id,
        )
    )).scalar_one_or_none()

    if fav is None:
        return False
    await db.delete(fav)
    await db.commit()
    return True


async def is_favorite(
    user_id: uuid.UUID,
    food_id: uuid.UUID,
    db: AsyncSession,
) -> bool:
    """Kiểm tra trạng thái yêu thích."""
    return (await db.execute(
        select(FavoriteFood).where(
            FavoriteFood.user_id == user_id,
            FavoriteFood.food_id == food_id,
        )
    )).scalar_one_or_none() is not None


# ---------------------------------------------------------------------------
# Recommendations từ favorites (embedding-based)
# ---------------------------------------------------------------------------

async def get_favorites_recommendations(
    user_id: uuid.UUID,
    db: AsyncSession,
    limit: int = 5,
) -> List[FavoriteRecommendationResult]:
    """
    Gợi ý món tương tự dựa trên embedding trung bình của các món yêu thích.

    Thuật toán:
    1. Lấy embedding của tất cả món đã yêu thích (ưu tiên món được đánh giá cao).
    2. Tính centroid (weighted average theo rating nếu có, uniform nếu không).
    3. Tìm top-N món trong DB gần centroid nhất theo cosine distance.
    4. Loại trừ các món đã có trong favorites.

    Trả danh sách rỗng nếu user chưa có favorites hoặc favorites không có embedding.
    """
    # Bước 1: Lấy food_id + embedding + rating của tất cả favorites
    stmt = (
        select(FavoriteFood.food_id, FavoriteFood.rating, Food.embedding)
        .join(Food, Food.id == FavoriteFood.food_id)
        .where(
            FavoriteFood.user_id == user_id,
            Food.embedding.is_not(None),
        )
    )
    rows = (await db.execute(stmt)).all()

    if not rows:
        return []

    favorite_food_ids = [r.food_id for r in rows]

    # Bước 2: Tính weighted centroid
    # Rating 1-5 → weight 1-5; chưa đánh giá → weight 1 (không thiên vị)
    embeddings = []
    weights = []
    for r in rows:
        emb = r.embedding
        if emb is None:
            continue
        arr = np.array(emb, dtype=np.float32)
        embeddings.append(arr)
        weights.append(float(r.rating) if r.rating else 1.0)

    if not embeddings:
        return []

    weights_arr = np.array(weights, dtype=np.float32)
    weights_arr /= weights_arr.sum()  # normalize
    centroid = np.average(np.stack(embeddings), axis=0, weights=weights_arr)

    # Bước 3: Tìm món gần nhất với centroid, loại trừ favorites đã có
    # cosine_distance trả về 0 (giống nhau) → 2 (đối nghịch)
    rec_stmt = (
        select(Food)
        .where(
            Food.embedding.is_not(None),
            Food.id.not_in(favorite_food_ids),
        )
        .order_by(Food.embedding.cosine_distance(centroid.tolist()))
        .limit(limit)
    )
    rec_foods = (await db.execute(rec_stmt)).scalars().all()

    # Bước 4: Tính similarity score (1 - cosine_distance/2) → [0, 1]
    results = []
    for food in rec_foods:
        food_emb = np.array(food.embedding, dtype=np.float32)
        # Cosine similarity = dot(a,b) / (|a| * |b|)
        norm_c = np.linalg.norm(centroid)
        norm_f = np.linalg.norm(food_emb)
        if norm_c > 0 and norm_f > 0:
            sim = float(np.dot(centroid, food_emb) / (norm_c * norm_f))
        else:
            sim = 0.0
        sim = round(max(0.0, min(1.0, sim)), 4)

        results.append(FavoriteRecommendationResult(
            id=food.id,
            name=food.name,
            description=food.description,
            img_url=food.img_url,
            soft_tags=food.soft_tags or [],
            taste_profile=food.taste_profile or [],
            meal_context=food.meal_context or [],
            similarity_score=sim,
        ))

    return results


# ---------------------------------------------------------------------------
# Shopping list từ favorites
# ---------------------------------------------------------------------------

async def get_favorites_shopping_list(
    user_id: uuid.UUID,
    db: AsyncSession,
    food_ids: Optional[List[uuid.UUID]] = None,
) -> Tuple[int, List[str]]:
    """
    Gom tất cả raw_ingredients từ món yêu thích được chọn, deduplicate, trả về danh sách mua sắm.

    - food_ids: chọn subset (None = lấy toàn bộ favorites)
    - Trả (food_count, sorted_ingredients)
    """
    # Lấy danh sách food thuộc favorites của user
    where_clauses = [FavoriteFood.user_id == user_id]
    if food_ids:
        where_clauses.append(FavoriteFood.food_id.in_(food_ids))

    stmt = (
        select(Food.raw_ingredients)
        .join(FavoriteFood, FavoriteFood.food_id == Food.id)
        .where(*where_clauses)
    )
    rows = (await db.execute(stmt)).all()

    if not rows:
        return 0, []

    # Gom và deduplicate (case-insensitive, giữ casing gốc của lần đầu xuất hiện)
    seen: dict[str, str] = {}  # lower → original
    for (raw_ings,) in rows:
        for ing in (raw_ings or []):
            ing = ing.strip()
            if not ing:
                continue
            key = ing.lower()
            if key not in seen:
                seen[key] = ing

    ingredients = sorted(seen.values(), key=lambda x: x.lower())
    return len(rows), ingredients
