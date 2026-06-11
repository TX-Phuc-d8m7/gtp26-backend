"""Admin User router — xem và quản lý tài khoản người dùng."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.users.models import User
from app.modules.admin.users.schemas import AdminUserListResponse, AdminUserUpdate
from app.modules.users.schemas import UserResult
from app.modules.admin.users.service import get_user, list_users, update_user
from app.modules.auth.service import get_current_admin_user

router = APIRouter(prefix="/admin/users", tags=["Admin — Users"])


# ---------------------------------------------------------------------------
# List & Detail
# ---------------------------------------------------------------------------

@router.get("", response_model=AdminUserListResponse, summary="Danh sách người dùng")
async def admin_list_users(
    q: Optional[str] = Query(default=None, description="Tìm theo email hoặc tên"),
    role: Optional[str] = Query(default=None, description="Lọc theo role (user / admin)"),
    is_active: Optional[bool] = Query(default=None, description="Lọc theo trạng thái hoạt động"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    total, items = await list_users(db, q=q, role=role, is_active=is_active, limit=limit, offset=offset)
    return AdminUserListResponse(total=total, limit=limit, offset=offset, items=items)


@router.get("/{user_id}", response_model=UserResult, summary="Chi tiết người dùng")
async def admin_get_user(
    user_id: uuid.UUID,
    _: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await get_user(user_id, db)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy người dùng.")
    return result


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

@router.patch("/{user_id}", response_model=UserResult, summary="Cập nhật tài khoản")
async def admin_update_user(
    user_id: uuid.UUID,
    payload: AdminUserUpdate,
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Cập nhật thông tin tài khoản:
    - `role`: thăng/hạ quyền (`user` ↔ `admin`).
    - `is_active`: khoá/mở tài khoản.
    - `full_name`: đổi tên hiển thị.

    ⚠️ Admin không thể tự hạ quyền hoặc tự khóa chính mình để tránh lock-out.
    """
    if str(user_id) == str(current_admin.id) and payload.role is not None and payload.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin không thể tự hạ quyền chính mình.",
        )
    if str(user_id) == str(current_admin.id) and payload.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin không thể tự khóa tài khoản của chính mình.",
        )

    result = await update_user(user_id, payload, db)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy người dùng.")
    return result


@router.post("/{user_id}/lock", response_model=UserResult, summary="Khóa tài khoản người dùng")
async def admin_lock_user(
    user_id: uuid.UUID,
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Khóa tài khoản bằng cách đặt `is_active=false`."""
    if str(user_id) == str(current_admin.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin không thể tự khóa tài khoản của chính mình.",
        )

    result = await update_user(user_id, AdminUserUpdate(is_active=False), db)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy người dùng.")
    return result


@router.post("/{user_id}/unlock", response_model=UserResult, summary="Mở khóa tài khoản người dùng")
async def admin_unlock_user(
    user_id: uuid.UUID,
    _: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Mở khóa tài khoản bằng cách đặt `is_active=true`."""
    result = await update_user(user_id, AdminUserUpdate(is_active=True), db)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy người dùng.")
    return result
