from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field


class IngredientAliasOverrideCreate(BaseModel):
    alias: str
    canonical_key: str
    group_keys: List[str] = Field(default_factory=list)
    enabled: bool = True
    notes: str = ""


class IngredientAliasOverrideUpdate(BaseModel):
    alias: Optional[str] = None
    canonical_key: Optional[str] = None
    group_keys: Optional[List[str]] = None
    enabled: Optional[bool] = None
    notes: Optional[str] = None


class IngredientAliasOverrideResult(BaseModel):
    id: uuid.UUID
    alias: str
    alias_key: str
    canonical_key: str
    group_keys: List[str] = Field(default_factory=list)
    enabled: bool
    notes: str = ""

    model_config = {"from_attributes": True}


class RebuildFoodKeysResponse(BaseModel):
    foods_count: int
    updated_count: int


# ---------------------------------------------------------------------------
# Food Library schemas
# ---------------------------------------------------------------------------
