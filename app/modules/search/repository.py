"""Repository layer cho search module.

File này chỉ chứa truy vấn DB thuần phục vụ search. Không đặt logic filter,
rerank, scoring hoặc business rule ở đây để service layer dễ maintain hơn.
"""

from __future__ import annotations

from sqlalchemy import not_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.foods.models import Food, Tag


async def list_tags_by_names(db: AsyncSession, names: list[str]) -> list[Tag]:
    """Lấy các rule tag bệnh lý/dị ứng theo tên tag đã chuẩn hóa."""
    if not names:
        return []
    result = await db.execute(select(Tag).where(Tag.name.in_(names)))
    return list(result.scalars().all())


async def list_foods_with_ingredient_key_overlap(
    db: AsyncSession,
    ingredient_keys: list[str],
) -> list[Food]:
    """Lấy các món có ingredient key giao với danh sách key cần loại."""
    if not ingredient_keys:
        return []
    result = await db.execute(
        select(Food).where(Food.core_ingredient_keys.overlap(ingredient_keys))
    )
    return list(result.scalars().all())


async def list_foods_matching_name(db: AsyncSession, name_fragment: str) -> list[Food]:
    """Lấy các món có tên chứa cụm tên món được yêu cầu."""
    if not name_fragment:
        return []
    result = await db.execute(select(Food).where(Food.name.ilike(f"%{name_fragment}%")))
    return list(result.scalars().all())


async def list_candidate_foods(
    db: AsyncSession,
    *,
    exclude_ingredient_keys: list[str],
    exclude_dishes: list[str],
) -> list[Food]:
    """Lấy danh sách món ứng viên sau lớp lọc cứng ở SQL."""
    stmt = select(Food)

    if exclude_ingredient_keys:
        stmt = stmt.where(not_(Food.core_ingredient_keys.overlap(exclude_ingredient_keys)))

    for dish in exclude_dishes:
        if dish:
            stmt = stmt.where(not_(Food.name.ilike(f"%{dish}%")))

    result = await db.execute(stmt)
    return list(result.scalars().all())
