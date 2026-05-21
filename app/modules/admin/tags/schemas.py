from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field


class AdminTagCreate(BaseModel):
    name: str = Field(min_length=1, description="Tên tag (ví dụ: Cao huyết áp, Dị ứng tôm cua)")
    tag_type: str = Field(description="Loại tag: 'health' | 'allergy' | 'diet' | 'soft'")
    exclude_soft_tag: List[str] = Field(default_factory=list, description="Tags món ăn cần tránh khi có bệnh này")
    prefer_soft_tag: List[str] = Field(default_factory=list, description="Tags món ăn nên ưu tiên")
    exclude_ingredient: List[str] = Field(default_factory=list, description="Nguyên liệu cần loại trừ")
    prefer_ingredient: List[str] = Field(default_factory=list, description="Nguyên liệu nên ưu tiên")


class AdminTagUpdate(BaseModel):
    name: Optional[str] = None
    tag_type: Optional[str] = None
    exclude_soft_tag: Optional[List[str]] = None
    prefer_soft_tag: Optional[List[str]] = None
    exclude_ingredient: Optional[List[str]] = None
    prefer_ingredient: Optional[List[str]] = None


class AdminTagResult(BaseModel):
    id: uuid.UUID
    name: str
    tag_type: str
    exclude_soft_tag: List[str]
    prefer_soft_tag: List[str]
    exclude_ingredient: List[str]
    prefer_ingredient: List[str]

    model_config = {"from_attributes": True}


class AdminTagListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[AdminTagResult]


# ---------------------------------------------------------------------------
# Admin — User Management schemas
# ---------------------------------------------------------------------------
