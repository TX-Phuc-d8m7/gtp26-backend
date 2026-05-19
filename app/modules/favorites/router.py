"""Favorite Foods router."""

from __future__ import annotations

import uuid
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models import User
from app.schemas import (
    FavoriteFoodCreate,
    FavoriteFoodResult,
    FavoriteFoodUpdate,
    FavoriteListResponse,
    FavoriteRecommendationResult,
    ShoppingListResponse,
)
from app.modules.auth.service import get_current_user
from app.modules.favorites.service import (
    add_favorite,
    get_favorites_recommendations,
    get_favorites_shopping_list,
    is_favorite,
    list_favorites,
    remove_favorite,
    update_favorite,
)

router = APIRouter(prefix="/users/me/favorites", tags=["Favorite Foods"])

# ⚠️  QUAN TRỌNG: Các route tĩnh (/recommendations, /shopping-list)
# phải được định nghĩa TRƯỚC route có path param (/{food_id})
# để FastAPI không nhầm "recommendations" thành food_id.


# ---------------------------------------------------------------------------
# List (filter / sort / search)
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=FavoriteListResponse,
    summary="Danh sách món yêu thích (có filter và sort)",
)
async def get_my_favorites(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    q: Optional[str] = Query(default=None, description="Tìm theo tên món"),
    meal_context: Optional[str] = Query(default=None, description="Lọc theo bữa ăn, ví dụ: 'Ăn sáng'"),
    taste_profile: Optional[str] = Query(default=None, description="Lọc theo khẩu vị, ví dụ: 'Thanh đạm'"),
    rated_only: bool = Query(default=False, description="Chỉ hiện những món đã được đánh giá"),
    sort_by: Literal["created_at", "name", "rating"] = Query(default="created_at"),
    sort_order: Literal["asc", "desc"] = Query(default="desc"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Lấy danh sách món yêu thích với đầy đủ thông tin món ăn.

    **Filter:**
    - `q`: tìm theo tên món
    - `meal_context`: lọc theo bữa ăn (Ăn sáng / Ăn trưa / Ăn tối / ...)
    - `taste_profile`: lọc theo khẩu vị (Thanh đạm / Đậm đà / Chua / ...)
    - `rated_only`: chỉ hiện những món đã đánh giá sao

    **Sort:**
    - `sort_by`: `created_at` | `name` | `rating`
    - `sort_order`: `asc` | `desc`
    """
    total, items = await list_favorites(
        current_user.id, db,
        limit=limit, offset=offset,
        q=q,
        meal_context=meal_context,
        taste_profile=taste_profile,
        rated_only=rated_only,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return FavoriteListResponse(total=total, limit=limit, offset=offset, items=items)


# ---------------------------------------------------------------------------
# Add
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=FavoriteFoodResult,
    status_code=status.HTTP_201_CREATED,
    summary="Thêm món vào danh sách yêu thích",
)
async def add_to_favorites(
    payload: FavoriteFoodCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Lưu món ăn vào danh sách yêu thích, có thể đánh giá sao ngay khi thêm.

    ```json
    {
      "food_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "notes": "Ăn trưa hợp, vị vừa miệng",
      "rating": 5
    }
    ```

    - `404`: food_id không tồn tại
    - `409`: món đã có trong danh sách yêu thích
    """
    try:
        result = await add_favorite(
            user_id=current_user.id,
            food_id=payload.food_id,
            notes=payload.notes,
            rating=payload.rating,
            db=db,
        )
    except ValueError as e:
        msg = str(e)
        if "không tồn tại" in msg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
        if "đã có" in msg:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    return result


# ---------------------------------------------------------------------------
# Recommendations — PHẢI đặt TRƯỚC /{food_id}
# ---------------------------------------------------------------------------

@router.get(
    "/recommendations",
    response_model=List[FavoriteRecommendationResult],
    summary="Gợi ý món tương tự dựa trên danh sách yêu thích",
)
async def get_recommendations(
    limit: int = Query(default=5, ge=1, le=20),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Gợi ý `limit` món chưa có trong danh sách yêu thích, dựa trên embedding similarity.

    **Thuật toán:**
    1. Tính centroid embedding của các món yêu thích (weighted theo rating — món 5 sao có trọng số cao hơn).
    2. Tìm các món có cosine similarity cao nhất với centroid.
    3. Loại trừ những món đã có trong favorites.

    Trả `[]` nếu user chưa có favorites hoặc chưa có embedding nào.
    """
    return await get_favorites_recommendations(current_user.id, db, limit=limit)


# ---------------------------------------------------------------------------
# Shopping list — PHẢI đặt TRƯỚC /{food_id}
# ---------------------------------------------------------------------------

@router.get(
    "/shopping-list",
    response_model=ShoppingListResponse,
    summary="Tạo danh sách mua sắm từ nguyên liệu của các món yêu thích",
)
async def get_shopping_list(
    food_ids: Optional[str] = Query(
        default=None,
        description="Danh sách food_id cách nhau bởi dấu phẩy. Để trống = lấy toàn bộ favorites.",
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Gom tất cả `raw_ingredients` từ các món yêu thích được chọn, deduplicate và trả về
    danh sách mua sắm đã sắp xếp theo alphabet.

    **Cách dùng:**
    - Không truyền `food_ids` → lấy toàn bộ favorites
    - Truyền `food_ids=uuid1,uuid2,uuid3` → chỉ lấy những món được chọn

    **Ví dụ response:**
    ```json
    {
      "food_count": 3,
      "ingredient_count": 24,
      "ingredients": ["bánh phở tươi 400g", "bò viên", "cà chua 2 quả", ...]
    }
    ```
    """
    # Parse food_ids từ query string
    parsed_ids: Optional[List[uuid.UUID]] = None
    if food_ids:
        try:
            parsed_ids = [uuid.UUID(fid.strip()) for fid in food_ids.split(",") if fid.strip()]
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="food_ids không hợp lệ. Phải là danh sách UUID cách nhau bởi dấu phẩy.",
            )

    food_count, ingredients = await get_favorites_shopping_list(
        current_user.id, db, food_ids=parsed_ids
    )
    return ShoppingListResponse(
        food_count=food_count,
        ingredient_count=len(ingredients),
        ingredients=ingredients,
    )


# ---------------------------------------------------------------------------
# Update (PATCH notes / rating)
# ---------------------------------------------------------------------------

@router.patch(
    "/{food_id}",
    response_model=FavoriteFoodResult,
    summary="Cập nhật ghi chú hoặc đánh giá sao",
)
async def update_favorite_item(
    food_id: uuid.UUID,
    payload: FavoriteFoodUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Cập nhật `notes` và/hoặc `rating` cho một món đã lưu.

    Chỉ gửi field cần thay đổi, các field khác giữ nguyên.

    ```json
    { "rating": 4, "notes": "Vị ngon hơn hôm trước" }
    ```

    - `404`: món không có trong danh sách yêu thích
    """
    result = await update_favorite(current_user.id, food_id, payload, db)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Món ăn này không có trong danh sách yêu thích.",
        )
    return result


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@router.delete(
    "/{food_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Xóa món khỏi danh sách yêu thích",
)
async def remove_from_favorites(
    food_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Xóa món khỏi danh sách yêu thích. `404` nếu không tìm thấy."""
    deleted = await remove_favorite(current_user.id, food_id, db)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Món ăn này không có trong danh sách yêu thích.",
        )


# ---------------------------------------------------------------------------
# Check trạng thái tim ♥
# ---------------------------------------------------------------------------

@router.get(
    "/{food_id}/check",
    summary="Kiểm tra trạng thái yêu thích",
)
async def check_favorite(
    food_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trả `{"is_favorite": true/false}` — tiện cho frontend hiển thị nút tim ♥."""
    result = await is_favorite(current_user.id, food_id, db)
    return {"is_favorite": result, "food_id": food_id}
