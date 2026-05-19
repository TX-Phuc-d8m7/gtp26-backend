"""User Health Profile service: CRUD và tích hợp vào search query."""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserHealthProfile
from app.schemas import UserHealthProfileCreate, UserHealthProfileUpdate


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------

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
    """
    Tạo hoặc thay thế toàn bộ profile (PUT semantics).
    Nếu đã có profile thì ghi đè tất cả field.
    """
    profile = await get_profile(user_id, db)

    if profile is None:
        profile = UserHealthProfile(user_id=user_id)
        db.add(profile)

    profile.health_conditions = data.health_conditions or []
    profile.allergies = data.allergies or []
    profile.diet_preferences = data.diet_preferences or []
    profile.nutrition_goals = data.nutrition_goals or []
    profile.disliked_ingredients = data.disliked_ingredients or []
    profile.preferred_ingredients = data.preferred_ingredients or []
    profile.notes = data.notes or ""

    await db.commit()
    await db.refresh(profile)
    return profile


async def patch_profile(
    user_id: uuid.UUID,
    data: UserHealthProfileUpdate,
    db: AsyncSession,
) -> Optional[UserHealthProfile]:
    """
    Cập nhật một phần profile (PATCH semantics).
    Trả None nếu profile chưa tồn tại.
    """
    profile = await get_profile(user_id, db)
    if profile is None:
        return None

    if data.health_conditions is not None:
        profile.health_conditions = data.health_conditions
    if data.allergies is not None:
        profile.allergies = data.allergies
    if data.diet_preferences is not None:
        profile.diet_preferences = data.diet_preferences
    if data.nutrition_goals is not None:
        profile.nutrition_goals = data.nutrition_goals
    if data.disliked_ingredients is not None:
        profile.disliked_ingredients = data.disliked_ingredients
    if data.preferred_ingredients is not None:
        profile.preferred_ingredients = data.preferred_ingredients
    if data.notes is not None:
        profile.notes = data.notes

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


# ---------------------------------------------------------------------------
# Search integration: chuyển profile → context string cho LLM
# ---------------------------------------------------------------------------

def build_profile_query_context(profile: UserHealthProfile) -> str:
    """
    Chuyển health profile thành đoạn văn bản ngắn để gắn vào đầu search query.

    LLM supervisor_agent sẽ đọc đoạn này và trích xuất constraint tự động —
    không cần thay đổi bất kỳ logic nào trong food_service.py.

    Ví dụ output:
        "Thông tin sức khỏe của tôi: tôi bị Cao huyết áp, Tiểu đường.
         Tôi bị dị ứng Dị ứng tôm cua.
         Tôi không muốn ăn: nội tạng, mỡ động vật.
         Tôi thích ăn: ức gà, rau xanh.
         Chế độ ăn: Ít muối, Eat Clean.
         Ghi chú thêm: Không ăn cay."
    """
    parts: list[str] = []

    if profile.health_conditions:
        joined = ", ".join(profile.health_conditions)
        parts.append(f"tôi bị {joined}")

    if profile.allergies:
        joined = ", ".join(profile.allergies)
        parts.append(f"tôi bị dị ứng: {joined}")

    if profile.diet_preferences:
        joined = ", ".join(profile.diet_preferences)
        parts.append(f"chế độ ăn của tôi: {joined}")

    if profile.nutrition_goals:
        joined = ", ".join(profile.nutrition_goals)
        parts.append(f"mục tiêu dinh dưỡng: {joined}")

    if profile.disliked_ingredients:
        joined = ", ".join(profile.disliked_ingredients)
        parts.append(f"tôi không muốn ăn: {joined}")

    if profile.preferred_ingredients:
        joined = ", ".join(profile.preferred_ingredients)
        parts.append(f"tôi thích ăn: {joined}")

    if profile.notes and profile.notes.strip():
        parts.append(f"lưu ý thêm: {profile.notes.strip()}")

    if not parts:
        return ""

    context = "Thông tin sức khỏe của tôi: " + "; ".join(parts) + ". "
    return context


def augment_query_with_profile(query: str, profile: Optional[UserHealthProfile]) -> str:
    """
    Gắn profile context vào đầu query nếu profile tồn tại và có nội dung.
    Query gốc được giữ nguyên ở cuối.
    """
    if profile is None:
        return query

    context = build_profile_query_context(profile)
    if not context:
        return query

    return context + query
