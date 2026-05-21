from __future__ import annotations

import asyncio
import json
import math
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.places.models import PlaceSearchCache
from app.modules.places.schemas import (
    FoodPlaceResult,
    FoodPlaceSearchResponse,
    PlaceLocation,
)


GOOGLE_PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
GOOGLE_PLACES_DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
GOOGLE_PLACES_TEXT_SEARCH_FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.rating",
        "places.userRatingCount",
        "places.googleMapsUri",
        "places.nationalPhoneNumber",
        "places.businessStatus",
        "places.location",
    ]
)
GOOGLE_PLACES_DETAILS_FIELD_MASK = ",".join(
    [
        "id",
        "displayName",
        "formattedAddress",
        "rating",
        "userRatingCount",
        "googleMapsUri",
        "nationalPhoneNumber",
        "businessStatus",
        "location",
    ]
)
DEFAULT_LOCATION_TEXT = "Đà Nẵng"
DEFAULT_RADIUS_M = 3000


def normalize_dish_key(value: str) -> str:
    text = unicodedata.normalize("NFD", value.strip().lower())
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    text = text.replace("đ", "d")
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def bucket_coordinate(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 2)


def build_food_place_query(
    dish: str,
    location_text: str,
    *,
    has_coordinates: bool = False,
) -> str:
    dish = dish.strip()
    location_text = location_text.strip() or DEFAULT_LOCATION_TEXT
    if has_coordinates:
        return f"quán bán {dish}"
    return f"quán bán {dish} ở {location_text}"


def calculate_distance_meters(
    origin_lat: float | None,
    origin_lng: float | None,
    target_lat: float | None,
    target_lng: float | None,
) -> int | None:
    if None in {origin_lat, origin_lng, target_lat, target_lng}:
        return None

    earth_radius_m = 6_371_000
    lat1 = math.radians(origin_lat)
    lat2 = math.radians(target_lat)
    delta_lat = math.radians(target_lat - origin_lat)
    delta_lng = math.radians(target_lng - origin_lng)

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lng / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(earth_radius_m * c)


def _require_google_maps_key() -> None:
    if not settings.google_maps_api_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Thiếu GOOGLE_MAPS_API_KEY trong cấu hình backend.",
        )


def _read_google_response(request: Request) -> dict[str, Any]:
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Google Places API lỗi {exc.code}: {error_body}",
        ) from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Không gọi được Google Places API: {exc}",
        ) from exc


def _call_google_places_text_search(
    query: str,
    *,
    limit: int,
    latitude: float | None,
    longitude: float | None,
    radius_m: int,
    included_type: str | None = "restaurant",
) -> dict[str, Any]:
    _require_google_maps_key()
    payload: dict[str, Any] = {
        "textQuery": query,
        "languageCode": "vi",
        "regionCode": "VN",
        "pageSize": limit,
    }
    if included_type:
        payload["includedType"] = included_type
    if latitude is not None and longitude is not None:
        payload["locationBias"] = {
            "circle": {
                "center": {
                    "latitude": latitude,
                    "longitude": longitude,
                },
                "radius": radius_m,
            }
        }

    request = Request(
        GOOGLE_PLACES_TEXT_SEARCH_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": settings.google_maps_api_key,
            "X-Goog-FieldMask": GOOGLE_PLACES_TEXT_SEARCH_FIELD_MASK,
        },
        method="POST",
    )
    return _read_google_response(request)


def _call_google_places_text_search_with_fallback(
    query: str,
    *,
    limit: int,
    latitude: float | None,
    longitude: float | None,
    radius_m: int,
) -> dict[str, Any]:
    try:
        return _call_google_places_text_search(
            query,
            limit=limit,
            latitude=latitude,
            longitude=longitude,
            radius_m=radius_m,
            included_type="restaurant",
        )
    except HTTPException as exc:
        detail = str(exc.detail)
        should_retry_without_type = (
            exc.status_code == status.HTTP_502_BAD_GATEWAY
            and (
                "includedType" in detail
                or "INVALID_ARGUMENT" in detail
                or "not a supported type" in detail
            )
        )
        if not should_retry_without_type:
            raise
        return _call_google_places_text_search(
            query,
            limit=limit,
            latitude=latitude,
            longitude=longitude,
            radius_m=radius_m,
            included_type=None,
        )


def _call_google_place_details(place_id: str) -> dict[str, Any]:
    _require_google_maps_key()
    request = Request(
        GOOGLE_PLACES_DETAILS_URL.format(place_id=place_id),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": settings.google_maps_api_key,
            "X-Goog-FieldMask": GOOGLE_PLACES_DETAILS_FIELD_MASK,
        },
        method="GET",
    )
    return _read_google_response(request)


def _map_place(
    place: dict[str, Any],
    *,
    origin_lat: float | None = None,
    origin_lng: float | None = None,
) -> FoodPlaceResult:
    display_name = place.get("displayName") or {}
    location = place.get("location") or {}
    mapped_location = None
    distance_meters = None
    if location.get("latitude") is not None and location.get("longitude") is not None:
        mapped_location = PlaceLocation(
            latitude=location["latitude"],
            longitude=location["longitude"],
        )
        distance_meters = calculate_distance_meters(
            origin_lat,
            origin_lng,
            mapped_location.latitude,
            mapped_location.longitude,
        )

    return FoodPlaceResult(
        place_id=place.get("id", ""),
        name=display_name.get("text") or "",
        formatted_address=place.get("formattedAddress"),
        rating=place.get("rating"),
        user_rating_count=place.get("userRatingCount"),
        google_maps_uri=place.get("googleMapsUri"),
        phone_number=place.get("nationalPhoneNumber"),
        business_status=place.get("businessStatus"),
        location=mapped_location,
        distance_meters=distance_meters,
    )


def _sort_places_by_distance(results: list[FoodPlaceResult]) -> list[FoodPlaceResult]:
    return sorted(
        results,
        key=lambda place: (
            place.distance_meters is None,
            place.distance_meters if place.distance_meters is not None else 10**12,
            -(place.rating or 0),
        ),
    )


async def _load_cache(
    db: AsyncSession,
    *,
    dish_key: str,
    lat_bucket: float | None,
    lng_bucket: float | None,
    location_text: str,
    radius_m: int,
    limit: int,
) -> list[PlaceSearchCache]:
    now = datetime.now(timezone.utc)
    stmt = (
        select(PlaceSearchCache)
        .where(
            PlaceSearchCache.dish_key == dish_key,
            PlaceSearchCache.radius_m == radius_m,
            PlaceSearchCache.expires_at > now,
        )
        .order_by(PlaceSearchCache.rank)
        .limit(limit)
    )
    if lat_bucket is None or lng_bucket is None:
        stmt = stmt.where(
            PlaceSearchCache.lat_bucket.is_(None),
            PlaceSearchCache.lng_bucket.is_(None),
            PlaceSearchCache.location_text == location_text,
        )
    else:
        stmt = stmt.where(
            PlaceSearchCache.lat_bucket == lat_bucket,
            PlaceSearchCache.lng_bucket == lng_bucket,
        )

    try:
        result = await db.execute(stmt)
        return list(result.scalars().all())
    except SQLAlchemyError as exc:
        await db.rollback()
        print(f"⚠️ Places cache read skipped: {exc}")
        return []


async def _replace_cache(
    db: AsyncSession,
    *,
    dish_key: str,
    lat_bucket: float | None,
    lng_bucket: float | None,
    location_text: str,
    radius_m: int,
    query: str,
    results: list[FoodPlaceResult],
) -> None:
    if not results:
        return

    delete_stmt = delete(PlaceSearchCache).where(
        PlaceSearchCache.dish_key == dish_key,
        PlaceSearchCache.radius_m == radius_m,
    )
    if lat_bucket is None or lng_bucket is None:
        delete_stmt = delete_stmt.where(
            PlaceSearchCache.lat_bucket.is_(None),
            PlaceSearchCache.lng_bucket.is_(None),
            PlaceSearchCache.location_text == location_text,
        )
    else:
        delete_stmt = delete_stmt.where(
            PlaceSearchCache.lat_bucket == lat_bucket,
            PlaceSearchCache.lng_bucket == lng_bucket,
        )
    try:
        await db.execute(delete_stmt)

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=max(settings.places_cache_ttl_days, 1))
        for rank, place in enumerate(results, start=1):
            db.add(
                PlaceSearchCache(
                    dish_key=dish_key,
                    lat_bucket=lat_bucket,
                    lng_bucket=lng_bucket,
                    location_text=location_text,
                    radius_m=radius_m,
                    place_id=place.place_id,
                    rank=rank,
                    search_query=query,
                    fetched_at=now,
                    expires_at=expires_at,
                )
            )
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        print(f"⚠️ Places cache write skipped: {exc}")


async def _hydrate_cached_places(
    cached_rows: list[PlaceSearchCache],
    *,
    latitude: float | None,
    longitude: float | None,
) -> list[FoodPlaceResult]:
    results: list[FoodPlaceResult] = []
    for row in cached_rows:
        place = await asyncio.to_thread(_call_google_place_details, row.place_id)
        mapped = _map_place(place, origin_lat=latitude, origin_lng=longitude)
        if mapped.place_id and mapped.name:
            results.append(mapped)
    return _sort_places_by_distance(results)


async def search_food_places(
    *,
    dish: str,
    location_text: str,
    limit: int,
    db: AsyncSession,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_m: int = DEFAULT_RADIUS_M,
) -> FoodPlaceSearchResponse:
    normalized_location_text = (location_text or DEFAULT_LOCATION_TEXT).strip()
    has_coordinates = latitude is not None and longitude is not None
    query = build_food_place_query(
        dish,
        normalized_location_text,
        has_coordinates=has_coordinates,
    )
    dish_key = normalize_dish_key(dish)
    lat_bucket = bucket_coordinate(latitude) if has_coordinates else None
    lng_bucket = bucket_coordinate(longitude) if has_coordinates else None

    cached_rows = await _load_cache(
        db,
        dish_key=dish_key,
        lat_bucket=lat_bucket,
        lng_bucket=lng_bucket,
        location_text=normalized_location_text,
        radius_m=radius_m,
        limit=limit,
    )
    if cached_rows:
        cached_results = await _hydrate_cached_places(
            cached_rows,
            latitude=latitude,
            longitude=longitude,
        )
        return FoodPlaceSearchResponse(
            query=cached_rows[0].search_query,
            dish=dish,
            location_text=normalized_location_text,
            latitude=latitude,
            longitude=longitude,
            radius_m=radius_m,
            cache_hit=True,
            results=cached_results[:limit],
        )

    payload = await asyncio.to_thread(
        _call_google_places_text_search_with_fallback,
        query,
        limit=limit,
        latitude=latitude,
        longitude=longitude,
        radius_m=radius_m,
    )
    places = payload.get("places") or []
    results = [
        result
        for result in (
            _map_place(place, origin_lat=latitude, origin_lng=longitude)
            for place in places
        )
        if result.place_id and result.name
    ]
    sorted_results = _sort_places_by_distance(results)[:limit]
    await _replace_cache(
        db,
        dish_key=dish_key,
        lat_bucket=lat_bucket,
        lng_bucket=lng_bucket,
        location_text=normalized_location_text,
        radius_m=radius_m,
        query=query,
        results=sorted_results,
    )
    return FoodPlaceSearchResponse(
        query=query,
        dish=dish,
        location_text=normalized_location_text,
        latitude=latitude,
        longitude=longitude,
        radius_m=radius_m,
        cache_hit=False,
        results=sorted_results,
    )
