from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class PlaceLocation(BaseModel):
    latitude: float
    longitude: float


class FoodPlaceResult(BaseModel):
    place_id: str
    name: str
    formatted_address: Optional[str] = None
    rating: Optional[float] = None
    user_rating_count: Optional[int] = None
    google_maps_uri: Optional[str] = None
    website_uri: Optional[str] = None
    phone_number: Optional[str] = None
    business_status: Optional[str] = None
    price_level: Optional[str] = None
    location: Optional[PlaceLocation] = None
    distance_meters: Optional[int] = None


class FoodPlaceSearchResponse(BaseModel):
    query: str
    dish: str
    location_text: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    radius_m: Optional[int] = None
    cache_hit: bool = False
    results: List[FoodPlaceResult] = Field(default_factory=list)
    strict_results: List[FoodPlaceResult] = Field(default_factory=list)
    fallback_results: List[FoodPlaceResult] = Field(default_factory=list)
    used_fallback_results: bool = False
    result_label: str = "Khớp đúng món"
    provider: str = "places_search"
