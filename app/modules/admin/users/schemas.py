from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field


from app.modules.users.schemas import UserResult


class AdminUserUpdate(BaseModel):
    role: Optional[Literal["user", "admin"]] = Field(default=None, description="Cập nhật role")
    is_active: Optional[bool] = Field(default=None, description="Khoá / mở khoá tài khoản")
    full_name: Optional[str] = None


class AdminUserListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List["UserResult"]


# ---------------------------------------------------------------------------
# Admin — Import schemas
# ---------------------------------------------------------------------------
