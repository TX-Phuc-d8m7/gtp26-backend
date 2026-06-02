"""Admin analytics router."""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.admin.analytics.schemas import (
    AdminAIFeedbackListResponse,
    AdminDashboardStatsResponse,
    AdminFoodRecommendationFeedbackListResponse,
)
from app.modules.admin.analytics.service import (
    get_dashboard_stats,
    list_ai_feedback,
    list_food_recommendation_feedback,
)
from app.modules.auth.service import get_current_admin_user
from app.modules.users.models import User


router = APIRouter(prefix="/admin/analytics", tags=["Admin — Analytics"])


@router.get(
    "/dashboard-stats",
    response_model=AdminDashboardStatsResponse,
    summary="Thống kê tổng quan dashboard admin",
)
async def admin_dashboard_stats(
    top_limit: int = Query(default=10, ge=1, le=50),
    _: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    return await get_dashboard_stats(db, top_limit=top_limit)


@router.get(
    "/ai-feedback",
    response_model=AdminAIFeedbackListResponse,
    summary="Danh sách feedback AI tập trung",
)
async def admin_ai_feedback(
    feedback: Optional[Literal["like", "dislike"]] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    total, items = await list_ai_feedback(
        db,
        feedback=feedback,
        limit=limit,
        offset=offset,
    )
    return AdminAIFeedbackListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=items,
    )


@router.get(
    "/food-feedback",
    response_model=AdminFoodRecommendationFeedbackListResponse,
    summary="Danh sách feedback từng món gợi ý",
)
async def admin_food_recommendation_feedback(
    verdict: Optional[Literal["like", "neutral", "dislike"]] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_food_recommendation_feedback(
        db,
        verdict=verdict,
        limit=limit,
        offset=offset,
    )
