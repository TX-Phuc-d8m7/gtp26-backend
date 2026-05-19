"""Admin Tag router — CRUD cho bảng tags (medical/diet rules)."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models import User
from app.schemas import (
    AdminTagCreate,
    AdminTagListResponse,
    AdminTagResult,
    AdminTagUpdate,
)
from app.modules.admin.tags.service import (
    create_tag,
    delete_tag,
    get_tag,
    list_tags,
    update_tag,
)
from app.modules.auth.service import get_current_admin_user

router = APIRouter(prefix="/admin/tags", tags=["Admin — Tags"])


# ---------------------------------------------------------------------------
# List & Detail
# ---------------------------------------------------------------------------

@router.get("", response_model=AdminTagListResponse, summary="Danh sách tags")
async def admin_list_tags(
    q: Optional[str] = Query(default=None, description="Tìm theo tên tag"),
    tag_type: Optional[str] = Query(default=None, description="Lọc theo loại tag (disease / diet / lifestyle / ...)"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    total, items = await list_tags(db, q=q, tag_type=tag_type, limit=limit, offset=offset)
    return AdminTagListResponse(total=total, limit=limit, offset=offset, items=items)


@router.get("/{tag_id}", response_model=AdminTagResult, summary="Chi tiết tag")
async def admin_get_tag(
    tag_id: uuid.UUID,
    _: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await get_tag(tag_id, db)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy tag.")
    return result


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=AdminTagResult,
    status_code=status.HTTP_201_CREATED,
    summary="Tạo tag mới",
)
async def admin_create_tag(
    payload: AdminTagCreate,
    _: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Tạo tag mới (medical rule / diet rule).

    - `name`: tên tag, phải khớp với giá trị dùng trong `soft_tags` của món ăn.
    - `tag_type`: phân loại (`disease`, `diet`, `lifestyle`, ...).
    - `exclude_soft_tag`: các soft_tag bị loại trừ khi user có tag này.
    - `prefer_soft_tag`: các soft_tag được ưu tiên khi user có tag này.
    - `exclude_ingredient`: nguyên liệu bị loại trừ.
    - `prefer_ingredient`: nguyên liệu được ưu tiên.
    """
    return await create_tag(payload, db)


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

@router.patch("/{tag_id}", response_model=AdminTagResult, summary="Cập nhật tag")
async def admin_update_tag(
    tag_id: uuid.UUID,
    payload: AdminTagUpdate,
    _: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Cập nhật thông tin tag (chỉ gửi field cần thay đổi)."""
    result = await update_tag(tag_id, payload, db)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy tag.")
    return result


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Xóa tag")
async def admin_delete_tag(
    tag_id: uuid.UUID,
    _: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Xóa vĩnh viễn tag. `404` nếu không tìm thấy."""
    deleted = await delete_tag(tag_id, db)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy tag.")
