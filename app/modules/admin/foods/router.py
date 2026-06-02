"""Admin Food router — CRUD, image upload, rebuild keys/embedding, import."""

from __future__ import annotations

import json
import uuid
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.users.models import User
from app.modules.admin.alias_overrides.schemas import RebuildFoodKeysResponse
from app.modules.admin.foods.schemas import (
    AdminFoodCreate,
    AdminFoodListResponse,
    AdminFoodResult,
    AdminFoodUpdate,
    FoodImageUploadResponse,
    FoodImportApplyResponse,
    FoodImportPreviewResponse,
    RebuildAllEmbeddingsResponse,
    RebuildEmbeddingResponse,
)
from app.modules.admin.foods.service import (
    create_food,
    delete_food,
    get_food_admin,
    import_foods_apply,
    import_foods_preview,
    list_foods_admin,
    rebuild_embedding_for_food,
    rebuild_keys_for_food,
    update_food,
    upload_image_for_food,
)
from app.modules.auth.service import get_current_admin_user
from app.integrations.vertex_ai import rebuild_all_embeddings
from app.integrations.google_storage import ALLOWED_CONTENT_TYPES, MAX_FILE_SIZE_BYTES

router = APIRouter(prefix="/admin/foods", tags=["Admin — Foods"])

# ⚠️ Route tĩnh phải đặt trước /{food_id}


# ---------------------------------------------------------------------------
# List & Detail
# ---------------------------------------------------------------------------

@router.get("", response_model=AdminFoodListResponse, summary="Danh sách món ăn")
async def admin_list_foods(
    # Tìm kiếm text
    q: Optional[str] = Query(default=None, description="Tìm theo tên hoặc mô tả món"),

    # Filter ARRAY fields — giống user
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

    # Filter nguyên liệu
    ingredients: Optional[List[str]] = Query(
        default=None,
        description="Lọc theo nguyên liệu (ILIKE), ví dụ: ingredients=bò&ingredients=cà chua",
    ),

    # Filter riêng admin
    has_embedding: Optional[bool] = Query(default=None, description="Lọc theo trạng thái embedding"),

    # Sort & Pagination
    sort_by: Literal["name", "relevance"] = Query(
        default="name",
        description="name: alphabet | relevance: ưu tiên kết quả khớp q nhất (chỉ có hiệu lực khi có q)",
    ),
    sort_order: Literal["asc", "desc"] = Query(default="asc"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),

    _: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Danh sách món ăn cho admin — filter đầy đủ như user, cộng thêm `has_embedding`.

    ### Logic filter
    Các điều kiện **AND** với nhau. Trong từng nhóm tag là **OR**:
    ```
    GET /admin/foods?meal_context=Ăn sáng&meal_context=Ăn trưa&taste_profile=Cay&has_embedding=false
    ```
    → Lấy món (Ăn sáng **OR** Ăn trưa) **AND** Cay **AND** chưa có embedding.
    """
    total, items = await list_foods_admin(
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
        has_embedding=has_embedding,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        offset=offset,
    )
    return AdminFoodListResponse(total=total, limit=limit, offset=offset, items=items)


@router.get("/{food_id}", response_model=AdminFoodResult, summary="Chi tiết món ăn")
async def admin_get_food(
    food_id: uuid.UUID,
    _: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await get_food_admin(food_id, db)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy món ăn.")
    return result


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=AdminFoodResult,
    status_code=status.HTTP_201_CREATED,
    summary="Tạo món ăn mới",
)
async def admin_create_food(
    payload: AdminFoodCreate,
    auto_embed: bool = Query(default=True, description="Tự động sinh embedding sau khi tạo"),
    _: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Tạo món ăn mới. Sau khi lưu:
    - `core_ingredient_keys` được sinh tự động từ `core_ingredients`.
    - Embedding được sinh tự động (có thể tắt bằng `auto_embed=false` khi import hàng loạt).
    """
    return await create_food(payload, db, auto_embed=auto_embed)


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

@router.patch("/{food_id}", response_model=AdminFoodResult, summary="Cập nhật thông tin món ăn")
async def admin_update_food(
    food_id: uuid.UUID,
    payload: AdminFoodUpdate,
    _: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Cập nhật thông tin món ăn (chỉ gửi field cần thay đổi).

    Tự động rebuild:
    - `core_ingredient_keys` nếu `core_ingredients` thay đổi.
    - `embedding` nếu bất kỳ field nội dung nào thay đổi.
    """
    result = await update_food(food_id, payload, db)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy món ăn.")
    return result


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@router.delete("/{food_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Xóa món ăn")
async def admin_delete_food(
    food_id: uuid.UUID,
    _: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Xóa vĩnh viễn món ăn và ảnh liên quan trên GCS. `404` nếu không tìm thấy."""
    deleted = await delete_food(food_id, db)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy món ăn.")


# ---------------------------------------------------------------------------
# Image upload
# ---------------------------------------------------------------------------

@router.post(
    "/{food_id}/image",
    response_model=FoodImageUploadResponse,
    summary="Upload ảnh món ăn lên Google Cloud Storage",
)
async def admin_upload_food_image(
    food_id: uuid.UUID,
    file: UploadFile = File(..., description="File ảnh (JPEG/PNG/WebP, tối đa 5MB)"),
    _: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload ảnh mới cho món ăn lên GCS.
    - Ảnh cũ (nếu có) sẽ bị xóa tự động.
    - Trả về `img_url` công khai của ảnh mới.
    """
    # Validate content type
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Định dạng không hỗ trợ: {file.content_type}. Chỉ chấp nhận JPEG, PNG, WebP.",
        )

    content = await file.read()

    # Validate kích thước
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File quá lớn ({len(content)/1024/1024:.1f}MB). Tối đa 5MB.",
        )

    img_url = await upload_image_for_food(
        food_id=food_id,
        file_content=content,
        original_filename=file.filename or "",
        content_type=file.content_type,
        db=db,
    )
    if img_url is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy món ăn.")

    return FoodImageUploadResponse(food_id=food_id, img_url=img_url)


# ---------------------------------------------------------------------------
# Rebuild keys / embedding cho một món
# ---------------------------------------------------------------------------

@router.post(
    "/{food_id}/rebuild-keys",
    response_model=AdminFoodResult,
    summary="Sinh lại core_ingredient_keys",
)
async def admin_rebuild_food_keys(
    food_id: uuid.UUID,
    _: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Sinh lại `core_ingredient_keys` từ `core_ingredients` + alias rules hiện tại."""
    result = await rebuild_keys_for_food(food_id, db)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy món ăn.")
    return result


@router.post(
    "/{food_id}/embedding",
    response_model=RebuildEmbeddingResponse,
    summary="Sinh lại embedding vector",
)
async def admin_rebuild_food_embedding(
    food_id: uuid.UUID,
    _: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Gọi Gemini Embedding API và lưu lại vector 3072 chiều cho món ăn."""
    success, message = await rebuild_embedding_for_food(food_id, db)
    if not success and "Không tìm thấy" in message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
    return RebuildEmbeddingResponse(food_id=food_id, success=success, message=message)


# ---------------------------------------------------------------------------
# Rebuild ALL embeddings (batch)
# ---------------------------------------------------------------------------

@router.post(
    "/batch/rebuild-embeddings",
    response_model=RebuildAllEmbeddingsResponse,
    summary="Sinh lại embedding cho TẤT CẢ món ăn (batch)",
)
async def admin_rebuild_all_embeddings(
    _: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    ⚠️ Tốn thời gian nếu có nhiều món. Mỗi món gọi 1 lần Gemini API.
    Nên chạy khi cần re-index toàn bộ hoặc sau khi thay đổi model embedding.
    """
    result = await rebuild_all_embeddings(db)
    return RebuildAllEmbeddingsResponse(**result)


# ---------------------------------------------------------------------------
# Import từ JSON
# ---------------------------------------------------------------------------

@router.post(
    "/import/preview",
    response_model=FoodImportPreviewResponse,
    summary="Xem trước dữ liệu import (dry-run, chưa lưu vào DB)",
)
async def admin_import_preview(
    file: UploadFile = File(..., description="File JSON — mảng các món ăn"),
    _: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload file JSON để xem trước kết quả import:
    - Kiểm tra validation từng item.
    - Phát hiện tên món trùng với DB hiện tại.
    - **Chưa lưu vào DB** — chỉ trả preview.

    Format JSON:
    ```json
    [
      {
        "name": "Phở bò",
        "description": "...",
        "core_ingredients": ["thịt bò", "bánh phở"],
        ...
      }
    ]
    ```
    """
    content = await file.read()
    try:
        items = json.loads(content)
        if not isinstance(items, list):
            raise ValueError("File JSON phải là một mảng (array) các món ăn.")
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    result = await import_foods_preview(items, db)
    return FoodImportPreviewResponse(**result)


@router.post(
    "/import/apply",
    response_model=FoodImportApplyResponse,
    summary="Áp dụng import JSON vào DB",
)
async def admin_import_apply(
    file: UploadFile = File(..., description="File JSON — mảng các món ăn"),
    skip_embedding: bool = Query(
        default=False,
        description="Bỏ qua sinh embedding lúc import (tốc độ nhanh hơn, cần chạy batch rebuild sau)",
    ),
    _: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Import món ăn từ JSON vào DB.
    - Bỏ qua tên đã tồn tại.
    - `skip_embedding=true` để import nhanh, sau đó chạy `/batch/rebuild-embeddings`.
    """
    content = await file.read()
    try:
        items = json.loads(content)
        if not isinstance(items, list):
            raise ValueError("File JSON phải là một mảng (array).")
    except (json.JSONDecodeError, ValueError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    result = await import_foods_apply(items, db, skip_embedding=skip_embedding)
    return FoodImportApplyResponse(**result)
