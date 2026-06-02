"""Restaurant/place lookup API."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.places.schemas import FoodPlaceSearchResponse
from app.modules.places.service import search_food_places


router = APIRouter(prefix="/places", tags=["Food Places"])


@router.get("/search", response_model=FoodPlaceSearchResponse)
async def search_places_endpoint(
    dish: str = Query(..., min_length=1, description="Tên món hoặc nhóm món cần tìm quán bán."),
    location: str = Query(default="Đà Nẵng", min_length=1, description="Khu vực cần tìm quán."),
    lat: Optional[float] = Query(default=None, ge=-90, le=90, description="Vĩ độ hiện tại của người dùng."),
    lng: Optional[float] = Query(default=None, ge=-180, le=180, description="Kinh độ hiện tại của người dùng."),
    radius_m: int = Query(default=3000, ge=100, le=50000, description="Bán kính ưu tiên tìm kiếm quanh vị trí user."),
    limit: int = Query(default=5, ge=1, le=10, description="Số địa điểm tối đa trả về."),
    db: AsyncSession = Depends(get_db),
):
    return await search_food_places(
        dish=dish,
        location_text=location,
        limit=limit,
        db=db,
        latitude=lat,
        longitude=lng,
        radius_m=radius_m,
    )
