"""Food Library router: browse, filter, search, detail — không qua LLM."""

from __future__ import annotations

import uuid
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models import User
from app.schemas import (
    FilterOptionsResponse,
    FoodDetailResponse,
    FoodListResponse,
)
from app.modules.auth.service import get_current_user_optional
from app.modules.foods.service import (
    get_filter_options,
    get_food_detail,
    list_foods,
)

router = APIRouter(prefix="/foods", tags=["Food Library"])

# ⚠️ Route tĩnh (/filter-options) phải đặt TRƯỚC route có path param (/{food_id})


# ---------------------------------------------------------------------------
# Filter options — dùng để build UI filter panel
# ---------------------------------------------------------------------------

@router.get(
    "/filter-options",
    response_model=FilterOptionsResponse,
    summary="Lấy danh sách giá trị hợp lệ cho từng bộ lọc",
)
async def get_food_filter_options():
    """
    Trả về tất cả giá trị có thể chọn cho từng bộ lọc trong UI thư viện món ăn.

    Frontend dùng endpoint này để render các checkbox / dropdown filter mà không cần
    hardcode giá trị ở client.

    ```json
    {
      "taste_profile": ["Béo ngậy", "Cay", "Chua", ...],
      "meal_context":  ["Ăn chiều / xế", "Ăn khuya", "Ăn sáng", ...],
      "occasion_context": [...],
      "dish_type": [...],
      "diet_style": [...],
      "nutrition": [...],
      "texture": [...]
    }
    ```
    """
    return get_filter_options()


# ---------------------------------------------------------------------------
# List / Search / Filter
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=FoodListResponse,
    summary="Duyệt thư viện món ăn với filter đầy đủ",
)
async def browse_foods(
    # Tìm kiếm text
    q: Optional[str] = Query(default=None, description="Tìm theo tên hoặc mô tả món"),

    # Filter theo từng nhóm tag (multi-select, lặp param hoặc dùng dấu phẩy)
    taste_profile: Optional[List[str]] = Query(
        default=None,
        description="Khẩu vị: Đậm đà, Thanh đạm, Chua, Cay, Mặn, Ngọt, Đắng, Béo ngậy",
    ),
    meal_context: Optional[List[str]] = Query(
        default=None,
        description="Bữa ăn: Ăn sáng, Ăn trưa, Ăn chiều / xế, Ăn tối, Ăn khuya",
    ),
    occasion_context: Optional[List[str]] = Query(
        default=None,
        description="Dịp ăn: Ăn no, Ăn vặt, Mồi nhậu, Tráng miệng, Giải rượu, Giải cảm, Ấm bụng",
    ),
    dish_type: Optional[List[str]] = Query(
        default=None,
        description="Kiểu chế biến: Lẩu, Nướng, Hấp / Luộc, Chiên / Rán, Xào, Cháo, ...",
    ),
    diet_style: Optional[List[str]] = Query(
        default=None,
        description="Phong cách ăn: Món chay, Healthy / Eat Clean, Món Việt truyền thống, ...",
    ),
    nutrition: Optional[List[str]] = Query(
        default=None,
        description="Dinh dưỡng: Giàu đạm, Giàu chất xơ, Hải sản, Nội tạng, ...",
    ),
    soft_tags: Optional[List[str]] = Query(
        default=None,
        description="Soft tag bất kỳ không thuộc các nhóm trên",
    ),

    # Filter theo nguyên liệu
    ingredients: Optional[List[str]] = Query(
        default=None,
        description="Lọc theo nguyên liệu (ILIKE), ví dụ: ingredients=bò&ingredients=cà chua",
    ),

    # Sort & Pagination
    sort_by: Literal["name", "relevance"] = Query(
        default="name",
        description="name: alphabet | relevance: ưu tiên kết quả khớp q nhất (chỉ có hiệu lực khi có q)",
    ),
    sort_order: Literal["asc", "desc"] = Query(default="asc"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),

    db: AsyncSession = Depends(get_db),
):
    """
    Duyệt thư viện món ăn với nhiều bộ lọc — **pure SQL, không gọi LLM**, response nhanh.

    ### Cách dùng filter multi-select
    Lặp lại query param:
    ```
    GET /foods?meal_context=Ăn sáng&meal_context=Ăn trưa&taste_profile=Thanh đạm
    ```
    Logic: `(meal_context=Ăn sáng OR Ăn trưa) AND taste_profile=Thanh đạm`

    ### Tìm theo nguyên liệu
    ```
    GET /foods?ingredients=bò&ingredients=cà chua
    ```
    Trả về các món có chứa "bò" HOẶC "cà chua" trong core_ingredients.

    ### Sort
    - `sort_by=relevance` chỉ có hiệu lực khi có `q` — ưu tiên tên khớp trước.
    - Khi không có `q`, tự động fallback về sort theo `name`.
    """
    total, items = await list_foods(
        db,
        q=q,
        taste_profile=taste_profile,
        meal_context=meal_context,
        occasion_context=occasion_context,
        dish_type=dish_type,
        diet_style=diet_style,
        nutrition=nutrition,
        soft_tags=soft_tags,
        ingredients=ingredients,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        offset=offset,
    )
    return FoodListResponse(total=total, limit=limit, offset=offset, items=items)


# ---------------------------------------------------------------------------
# Detail — PHẢI đặt SAU /filter-options
# ---------------------------------------------------------------------------

@router.get(
    "/{food_id}",
    response_model=FoodDetailResponse,
    summary="Chi tiết một món ăn",
)
async def get_food(
    food_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Trả đầy đủ thông tin món ăn:
    - Tên, mô tả, ảnh
    - `core_ingredients`: nguyên liệu chính
    - `raw_ingredients`: danh sách nguyên liệu đầy đủ với định lượng
    - `raw_instructions`: các bước hướng dẫn nấu
    - `soft_tags`, `taste_profile`, `meal_context`, `occasion_context`

    Nếu đã đăng nhập (Bearer token), response bổ sung:
    - `is_favorite`: món có trong danh sách yêu thích không
    - `user_rating`: số sao user đã đánh giá (null nếu chưa)
    - `user_notes`: ghi chú user đã lưu (null nếu chưa)
    """
    user_id = current_user.id if current_user else None
    detail = await get_food_detail(food_id, db, user_id=user_id)

    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy món ăn với id={food_id}.",
        )
    return detail
