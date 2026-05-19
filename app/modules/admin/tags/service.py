"""Admin Tag service — CRUD cho bảng tags (medical rules)."""

from __future__ import annotations

import uuid
from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tag
from app.schemas import AdminTagCreate, AdminTagResult, AdminTagUpdate


def _to_result(tag: Tag) -> AdminTagResult:
    return AdminTagResult(
        id=tag.id,
        name=tag.name,
        tag_type=tag.tag_type,
        exclude_soft_tag=tag.exclude_soft_tag or [],
        prefer_soft_tag=tag.prefer_soft_tag or [],
        exclude_ingredient=tag.exclude_ingredient or [],
        prefer_ingredient=tag.prefer_ingredient or [],
    )


async def list_tags(
    db: AsyncSession,
    *,
    q: Optional[str] = None,
    tag_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[int, List[AdminTagResult]]:
    where = []
    if q:
        where.append(Tag.name.ilike(f"%{q.strip()}%"))
    if tag_type:
        where.append(Tag.tag_type == tag_type)

    count_stmt = select(func.count()).select_from(Tag)
    data_stmt  = select(Tag).order_by(Tag.tag_type.asc(), Tag.name.asc())

    if where:
        count_stmt = count_stmt.where(*where)
        data_stmt  = data_stmt.where(*where)

    total = (await db.execute(count_stmt)).scalar_one()
    tags  = (await db.execute(data_stmt.limit(limit).offset(offset))).scalars().all()
    return total, [_to_result(t) for t in tags]


async def get_tag(tag_id: uuid.UUID, db: AsyncSession) -> Optional[AdminTagResult]:
    tag = await db.get(Tag, tag_id)
    return _to_result(tag) if tag else None


async def create_tag(data: AdminTagCreate, db: AsyncSession) -> AdminTagResult:
    tag = Tag(
        name=data.name,
        tag_type=data.tag_type,
        exclude_soft_tag=data.exclude_soft_tag,
        prefer_soft_tag=data.prefer_soft_tag,
        exclude_ingredient=data.exclude_ingredient,
        prefer_ingredient=data.prefer_ingredient,
    )
    db.add(tag)
    await db.commit()
    await db.refresh(tag)
    return _to_result(tag)


async def update_tag(
    tag_id: uuid.UUID,
    data: AdminTagUpdate,
    db: AsyncSession,
) -> Optional[AdminTagResult]:
    tag = await db.get(Tag, tag_id)
    if tag is None:
        return None

    if data.name is not None:
        tag.name = data.name
    if data.tag_type is not None:
        tag.tag_type = data.tag_type
    if data.exclude_soft_tag is not None:
        tag.exclude_soft_tag = data.exclude_soft_tag
    if data.prefer_soft_tag is not None:
        tag.prefer_soft_tag = data.prefer_soft_tag
    if data.exclude_ingredient is not None:
        tag.exclude_ingredient = data.exclude_ingredient
    if data.prefer_ingredient is not None:
        tag.prefer_ingredient = data.prefer_ingredient

    await db.commit()
    await db.refresh(tag)
    return _to_result(tag)


async def delete_tag(tag_id: uuid.UUID, db: AsyncSession) -> bool:
    tag = await db.get(Tag, tag_id)
    if tag is None:
        return False
    await db.delete(tag)
    await db.commit()
    return True
