"""Admin User service — xem và quản lý tài khoản người dùng."""

from __future__ import annotations

import uuid
from typing import List, Optional, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.schemas import AdminUserUpdate, UserResult


def _to_result(user: User) -> UserResult:
    return UserResult(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
    )


async def list_users(
    db: AsyncSession,
    *,
    q: Optional[str] = None,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
    limit: int = 20,
    offset: int = 0,
) -> Tuple[int, List[UserResult]]:
    where = []
    if q:
        qs = q.strip()
        where.append(or_(User.email.ilike(f"%{qs}%"), User.full_name.ilike(f"%{qs}%")))
    if role:
        where.append(User.role == role)
    if is_active is not None:
        where.append(User.is_active == is_active)

    count_stmt = select(func.count()).select_from(User)
    data_stmt  = select(User).order_by(User.created_at.desc())

    if where:
        count_stmt = count_stmt.where(*where)
        data_stmt  = data_stmt.where(*where)

    total = (await db.execute(count_stmt)).scalar_one()
    users = (await db.execute(data_stmt.limit(limit).offset(offset))).scalars().all()
    return total, [_to_result(u) for u in users]


async def get_user(user_id: uuid.UUID, db: AsyncSession) -> Optional[UserResult]:
    user = await db.get(User, user_id)
    return _to_result(user) if user else None


async def update_user(
    user_id: uuid.UUID,
    data: AdminUserUpdate,
    db: AsyncSession,
) -> Optional[UserResult]:
    user = await db.get(User, user_id)
    if user is None:
        return None

    if data.role is not None:
        user.role = data.role
    if data.is_active is not None:
        user.is_active = data.is_active
    if data.full_name is not None:
        user.full_name = data.full_name

    await db.commit()
    await db.refresh(user)
    return _to_result(user)
