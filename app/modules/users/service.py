"""User Health Profile service: CRUD cho UserHealthProfile."""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import User, UserHealthProfile
from app.modules.users.schemas import (
    UserAccountUpdate,
    UserHealthProfileCreate,
    UserHealthProfileUpdate,
)


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------

async def update_account(
    user: User,
    data: UserAccountUpdate,
    db: AsyncSession,
) -> User:
    if data.email is not None:
        user.email = str(data.email)
    if data.full_name is not None:
        cleaned_name = data.full_name.strip()
        user.full_name = cleaned_name or None

    await db.commit()
    await db.refresh(user)
    return user


async def deactivate_account(user: User, db: AsyncSession) -> User:
    user.is_active = False
    await db.commit()
    await db.refresh(user)
    return user


async def get_profile(user_id: uuid.UUID, db: AsyncSession) -> Optional[UserHealthProfile]:
    """Lấy profile của user. Trả None nếu chưa tạo."""
    result = await db.execute(
        select(UserHealthProfile).where(UserHealthProfile.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def upsert_profile(
    user_id: uuid.UUID,
    data: UserHealthProfileCreate,
    db: AsyncSession,
) -> UserHealthProfile:
    """Tạo hoặc thay thế toàn bộ profile (PUT semantics)."""
    profile = await get_profile(user_id, db)

    if profile is None:
        profile = UserHealthProfile(user_id=user_id)
        db.add(profile)

    profile.health_conditions = data.health_conditions or []
    profile.allergies = data.allergies or []
    profile.preferred_ingredients = data.preferred_ingredients or []
    profile.taste_profile = data.taste_profile or []
    profile.dish_preferences = data.dish_preferences or []

    await db.commit()
    await db.refresh(profile)
    return profile


async def patch_profile(
    user_id: uuid.UUID,
    data: UserHealthProfileUpdate,
    db: AsyncSession,
) -> Optional[UserHealthProfile]:
    """Cập nhật một phần profile (PATCH semantics). Trả None nếu chưa tồn tại."""
    profile = await get_profile(user_id, db)
    if profile is None:
        return None

    if data.health_conditions is not None:
        profile.health_conditions = data.health_conditions
    if data.allergies is not None:
        profile.allergies = data.allergies
    if data.preferred_ingredients is not None:
        profile.preferred_ingredients = data.preferred_ingredients
    if data.taste_profile is not None:
        profile.taste_profile = data.taste_profile
    if data.dish_preferences is not None:
        profile.dish_preferences = data.dish_preferences

    await db.commit()
    await db.refresh(profile)
    return profile


async def delete_profile(user_id: uuid.UUID, db: AsyncSession) -> bool:
    """Xóa profile. Trả True nếu xóa thành công, False nếu không tồn tại."""
    profile = await get_profile(user_id, db)
    if profile is None:
        return False
    await db.delete(profile)
    await db.commit()
    return True
