"""Search API router."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models import User
from app.schemas import SearchResponse
from app.modules.auth.service import get_current_user_optional
from app.modules.search.service import search_food
from app.modules.users.service import augment_query_with_profile, get_profile

router = APIRouter(prefix="/foods", tags=["Food Search"])


@router.get("/search", response_model=SearchResponse, response_model_exclude_none=True)
async def search_endpoint(
    q: str = Query(None),
    thread_id: Optional[uuid.UUID] = Query(default=None),
    skip_profile: bool = Query(
        default=False,
        description="Bỏ qua hồ sơ sức khỏe đã lưu cho lần tìm kiếm này (mặc định: luôn dùng profile nếu đã đăng nhập)",
    ),
    debug: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    if not q:
        raise HTTPException(status_code=400, detail="Vui lòng nhập câu hỏi tìm kiếm.")

    effective_query = q
    if current_user is not None and not skip_profile:
        profile = await get_profile(current_user.id, db)
        effective_query = augment_query_with_profile(q, profile)

    return await search_food(effective_query, db, thread_id=thread_id, debug=debug)

