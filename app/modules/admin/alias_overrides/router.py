"""Admin APIs for ingredient alias overrides."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.admin.alias_overrides.models import IngredientAliasOverride
from app.modules.foods.models import Food
from app.modules.admin.alias_overrides.schemas import (
    IngredientAliasOverrideCreate,
    IngredientAliasOverrideResult,
    IngredientAliasOverrideUpdate,
    RebuildFoodKeysResponse,
)
from app.modules.ingredients.service import (
    generate_core_ingredient_keys,
    load_enabled_alias_override_rules,
    normalize_alias_key,
)

router = APIRouter(prefix="/admin/ingredient-alias-overrides", tags=["Admin Ingredient Alias Overrides"])


async def get_override_or_404(
    override_id: uuid.UUID,
    db: AsyncSession,
) -> IngredientAliasOverride:
    """Load one alias override or raise 404."""
    override = await db.get(IngredientAliasOverride, override_id)
    if not override:
        raise HTTPException(status_code=404, detail="Không tìm thấy alias override.")
    return override


async def ensure_alias_key_available(
    alias_key: str,
    db: AsyncSession,
    *,
    exclude_id: uuid.UUID | None = None,
) -> None:
    """Prevent one alias from being mapped to multiple override rows."""
    stmt = select(IngredientAliasOverride).where(IngredientAliasOverride.alias_key == alias_key)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing and existing.id != exclude_id:
        raise HTTPException(status_code=409, detail="Alias này đã tồn tại trong override.")


@router.get("", response_model=list[IngredientAliasOverrideResult])
async def list_alias_overrides(db: AsyncSession = Depends(get_db)):
    """List all alias overrides for admin review."""
    result = await db.execute(
        select(IngredientAliasOverride).order_by(
            IngredientAliasOverride.enabled.desc(),
            IngredientAliasOverride.alias.asc(),
        )
    )
    return result.scalars().all()


@router.post("", response_model=IngredientAliasOverrideResult)
async def create_alias_override(
    payload: IngredientAliasOverrideCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create one admin alias override."""
    alias = payload.alias.strip()
    canonical_key = payload.canonical_key.strip()
    if not alias or not canonical_key:
        raise HTTPException(status_code=400, detail="Alias và canonical_key không được để trống.")

    alias_key = normalize_alias_key(alias)
    await ensure_alias_key_available(alias_key, db)

    override = IngredientAliasOverride(
        alias=alias,
        alias_key=alias_key,
        canonical_key=canonical_key,
        group_keys=payload.group_keys or [],
        enabled=payload.enabled,
        notes=payload.notes or "",
    )
    db.add(override)
    await db.commit()
    await db.refresh(override)
    return override


@router.patch("/{override_id}", response_model=IngredientAliasOverrideResult)
async def update_alias_override(
    override_id: uuid.UUID,
    payload: IngredientAliasOverrideUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update one alias override."""
    override = await get_override_or_404(override_id, db)

    if payload.alias is not None:
        alias = payload.alias.strip()
        if not alias:
            raise HTTPException(status_code=400, detail="Alias không được để trống.")
        alias_key = normalize_alias_key(alias)
        await ensure_alias_key_available(alias_key, db, exclude_id=override.id)
        override.alias = alias
        override.alias_key = alias_key

    if payload.canonical_key is not None:
        canonical_key = payload.canonical_key.strip()
        if not canonical_key:
            raise HTTPException(status_code=400, detail="canonical_key không được để trống.")
        override.canonical_key = canonical_key

    if payload.group_keys is not None:
        override.group_keys = payload.group_keys
    if payload.enabled is not None:
        override.enabled = payload.enabled
    if payload.notes is not None:
        override.notes = payload.notes

    await db.commit()
    await db.refresh(override)
    return override


@router.delete("/{override_id}", response_model=IngredientAliasOverrideResult)
async def disable_alias_override(
    override_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Soft delete one override by disabling it."""
    override = await get_override_or_404(override_id, db)
    override.enabled = False
    await db.commit()
    await db.refresh(override)
    return override


@router.post("/rebuild-food-keys", response_model=RebuildFoodKeysResponse)
async def rebuild_food_keys(db: AsyncSession = Depends(get_db)):
    """Regenerate core_ingredient_keys for all foods using baseline rules + enabled overrides."""
    override_rules = await load_enabled_alias_override_rules(db)
    result = await db.execute(select(Food))
    foods = result.scalars().all()

    updated_count = 0
    for food in foods:
        new_keys = generate_core_ingredient_keys(
            food.core_ingredients or [],
            extra_rules=override_rules,
        )
        if food.core_ingredient_keys != new_keys:
            food.core_ingredient_keys = new_keys
            updated_count += 1

    await db.commit()
    return RebuildFoodKeysResponse(foods_count=len(foods), updated_count=updated_count)
