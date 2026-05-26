from __future__ import annotations

import asyncio
import json
import math
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
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
SERPAPI_SEARCH_URL = "https://serpapi.com/search.json"
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
DEFAULT_SERPAPI_LANGUAGE = "vi"
DEFAULT_SERPAPI_COUNTRY = "vn"
GENERIC_DISH_TOKENS = {
    "am",
    "an",
    "ban",
    "bun",
    "cafe",
    "chao",
    "com",
    "cua",
    "ga",
    "ha",
    "hang",
    "heo",
    "kho",
    "lau",
    "mi",
    "mien",
    "mon",
    "nha",
    "nuoc",
    "pho",
    "pizza",
    "quan",
    "restaurant",
    "sup",
    "thit",
}


def normalize_dish_key(value: str) -> str:
    text = unicodedata.normalize("NFD", value.strip().lower())
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    text = text.replace("đ", "d")
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def normalize_ascii_text(value: str) -> str:
    text = unicodedata.normalize("NFD", value.strip())
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return text.replace("Đ", "D").replace("đ", "d")


def normalize_serpapi_location_text(location_text: str) -> str:
    normalized = normalize_ascii_text(location_text).strip()
    if not normalized:
        return "Da Nang, Vietnam"
    lowered = normalized.lower()
    if "vietnam" not in lowered and "viet nam" not in lowered:
        normalized = f"{normalized}, Vietnam"
    return normalized


def normalize_search_text(value: str) -> str:
    normalized = normalize_ascii_text(value).lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def tokenize_search_text(value: str) -> list[str]:
    return [token for token in normalize_search_text(value).split(" ") if token]


def extract_distinctive_dish_tokens(dish: str) -> list[str]:
    distinctive_tokens: list[str] = []
    seen: set[str] = set()
    for token in tokenize_search_text(dish):
        if len(token) <= 1 or token in GENERIC_DISH_TOKENS or token in seen:
            continue
        distinctive_tokens.append(token)
        seen.add(token)
    return distinctive_tokens


def is_place_payload_dict(place: Any) -> bool:
    return isinstance(place, dict)


def _build_place_searchable_text(place: dict[str, Any]) -> str:
    parts: list[str] = []
    for value in (
        place.get("title"),
        place.get("address"),
        place.get("type"),
        place.get("description"),
        place.get("hours"),
        place.get("displayName", {}).get("text") if isinstance(place.get("displayName"), dict) else None,
        place.get("formattedAddress"),
    ):
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    extensions = place.get("extensions")
    if isinstance(extensions, list):
        parts.extend(str(item).strip() for item in extensions if str(item).strip())
    return normalize_search_text(" ".join(parts))


def is_place_relevant_for_dish(place: dict[str, Any], dish: str) -> bool:
    searchable_text = _build_place_searchable_text(place)
    normalized_dish = normalize_search_text(dish)
    if not searchable_text:
        return False
    if normalized_dish and normalized_dish in searchable_text:
        return True

    distinctive_tokens = extract_distinctive_dish_tokens(dish)
    if not distinctive_tokens:
        return True

    matched_count = sum(1 for token in distinctive_tokens if token in searchable_text)
    if matched_count == len(distinctive_tokens):
        return True
    if len(distinctive_tokens) == 1:
        return matched_count == 1
    return matched_count / len(distinctive_tokens) >= 0.75


def compute_place_fallback_score(place: dict[str, Any], dish: str) -> float:
    searchable_text = _build_place_searchable_text(place)
    if not searchable_text:
        return 0.0

    normalized_dish = normalize_search_text(dish)
    if normalized_dish and normalized_dish in searchable_text:
        return 1.0

    dish_tokens = tokenize_search_text(dish)
    distinctive_tokens = extract_distinctive_dish_tokens(dish)
    if distinctive_tokens:
        matched_distinctive = sum(1 for token in distinctive_tokens if token in searchable_text)
        distinctive_score = matched_distinctive / len(distinctive_tokens)
    else:
        distinctive_score = 0.0

    if dish_tokens:
        matched_all = sum(1 for token in dish_tokens if token in searchable_text)
        token_score = matched_all / len(dish_tokens)
    else:
        token_score = 0.0

    if distinctive_tokens:
        return max(distinctive_score, token_score * 0.7)
    return token_score


def select_fallback_places(places: list[dict[str, Any]], dish: str, *, limit: int) -> list[dict[str, Any]]:
    scored_places: list[tuple[float, dict[str, Any]]] = []
    for place in places:
        score = compute_place_fallback_score(place, dish)
        if score <= 0:
            continue
        scored_places.append((score, place))

    scored_places.sort(
        key=lambda item: (
            -item[0],
            -(item[1].get("rating") or 0),
            item[1].get("reviews") or item[1].get("userRatingCount") or 0,
        )
    )
    return [place for score, place in scored_places[:limit]]


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
        return f"\"{dish}\" quán ăn"
    return f"\"{dish}\" quán ăn ở {location_text}"


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


def _active_places_provider() -> str:
    if settings.serpapi_api_key:
        return "serpapi"
    if settings.google_maps_api_key:
        return "google_places"
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Thiếu cấu hình địa điểm. Hãy set SERPAPI_API_KEY hoặc GOOGLE_MAPS_API_KEY.",
    )


def _read_json_response(request: Request, *, provider_name: str) -> dict[str, Any]:
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"{provider_name} lỗi {exc.code}: {error_body}",
        ) from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Không gọi được {provider_name}: {exc}",
        ) from exc

    if isinstance(payload, dict) and payload.get("error"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"{provider_name} trả lỗi: {payload['error']}",
        )
    return payload


def _require_google_maps_key() -> None:
    if not settings.google_maps_api_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Thiếu GOOGLE_MAPS_API_KEY trong cấu hình backend.",
        )


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
    return _read_json_response(request, provider_name="Google Places API")


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
    return _read_json_response(request, provider_name="Google Places API")


def _build_serpapi_params(
    query: str,
    *,
    location_text: str,
    latitude: float | None,
    longitude: float | None,
    radius_m: int,
) -> dict[str, Any]:
    base_params: dict[str, Any] = {
        "api_key": settings.serpapi_api_key,
        "engine": "google",
        "hl": DEFAULT_SERPAPI_LANGUAGE,
        "google_domain": "google.com",
        "q": query,
        "gl": DEFAULT_SERPAPI_COUNTRY,
        "no_cache": "false",
        "output": "json",
    }
    base_params["location"] = normalize_serpapi_location_text(location_text)

    if latitude is not None and longitude is not None:
        base_params["q"] = f"{query} gần đây"

    return base_params


def _call_serpapi_local_search(
    query: str,
    *,
    location_text: str,
    latitude: float | None,
    longitude: float | None,
    radius_m: int,
) -> dict[str, Any]:
    if not settings.serpapi_api_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Thiếu SERPAPI_API_KEY trong cấu hình backend.",
        )

    params = _build_serpapi_params(
        query,
        location_text=location_text,
        latitude=latitude,
        longitude=longitude,
        radius_m=radius_m,
    )
    request = Request(
        f"{SERPAPI_SEARCH_URL}?{urlencode(params)}",
        headers={"Accept": "application/json"},
        method="GET",
    )
    return _read_json_response(request, provider_name="SerpApi")


def _map_google_place(
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


def _map_serpapi_place(
    place: dict[str, Any],
    *,
    origin_lat: float | None = None,
    origin_lng: float | None = None,
) -> FoodPlaceResult:
    gps_coordinates = place.get("gps_coordinates") or {}
    mapped_location = None
    distance_meters = None
    latitude = gps_coordinates.get("latitude")
    longitude = gps_coordinates.get("longitude")
    if latitude is not None and longitude is not None:
        mapped_location = PlaceLocation(latitude=latitude, longitude=longitude)
        distance_meters = calculate_distance_meters(
            origin_lat,
            origin_lng,
            mapped_location.latitude,
            mapped_location.longitude,
        )

    links = place.get("links") or {}
    google_maps_uri = (
        links.get("directions")
        or links.get("order")
        or place.get("place_id_search")
    )
    business_status = place.get("hours") or place.get("open_state")

    return FoodPlaceResult(
        place_id=str(
            place.get("place_id")
            or place.get("data_id")
            or place.get("data_cid")
            or ""
        ),
        name=place.get("title") or "",
        formatted_address=place.get("address"),
        rating=place.get("rating"),
        user_rating_count=place.get("reviews"),
        google_maps_uri=google_maps_uri,
        website_uri=links.get("website"),
        phone_number=place.get("phone"),
        business_status=business_status,
        price_level=place.get("price"),
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


def _build_response_result_sets(
    *,
    strict_results: list[FoodPlaceResult],
    fallback_results: list[FoodPlaceResult],
    limit: int,
) -> tuple[list[FoodPlaceResult], list[FoodPlaceResult], list[FoodPlaceResult], bool, str]:
    strict_sorted = _sort_places_by_distance(strict_results)[:limit]
    fallback_sorted = _sort_places_by_distance(fallback_results)[:limit]
    used_fallback = not strict_sorted and bool(fallback_sorted)
    primary_results = strict_sorted if strict_sorted else fallback_sorted
    result_label = "Quán gần liên quan nhất" if used_fallback else "Khớp đúng món"
    return primary_results, strict_sorted, fallback_sorted, used_fallback, result_label


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
        mapped = _map_google_place(place, origin_lat=latitude, origin_lng=longitude)
        if mapped.place_id and mapped.name:
            results.append(mapped)
    return _sort_places_by_distance(results)


async def _search_with_google_places(
    *,
    query: str,
    dish: str,
    location_text: str,
    limit: int,
    db: AsyncSession,
    latitude: float | None,
    longitude: float | None,
    radius_m: int,
) -> FoodPlaceSearchResponse:
    has_coordinates = latitude is not None and longitude is not None
    dish_key = normalize_dish_key(dish)
    lat_bucket = bucket_coordinate(latitude) if has_coordinates else None
    lng_bucket = bucket_coordinate(longitude) if has_coordinates else None

    cached_rows = await _load_cache(
        db,
        dish_key=dish_key,
        lat_bucket=lat_bucket,
        lng_bucket=lng_bucket,
        location_text=location_text,
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
            location_text=location_text,
            latitude=latitude,
            longitude=longitude,
            radius_m=radius_m,
            cache_hit=True,
            results=cached_results[:limit],
            strict_results=cached_results[:limit],
            fallback_results=[],
            used_fallback_results=False,
            result_label="Khớp đúng món",
            provider="google_places_text_search",
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
    filtered_places = [
        place
        for place in places
        if is_place_payload_dict(place) and is_place_relevant_for_dish(place, dish)
    ]
    strict_results = [
        result
        for result in (
            _map_google_place(place, origin_lat=latitude, origin_lng=longitude)
            for place in filtered_places
        )
        if result.place_id and result.name
    ]
    fallback_source_places = [
        place for place in places if is_place_payload_dict(place)
    ]
    fallback_places = select_fallback_places(
        fallback_source_places,
        dish,
        limit=limit,
    )
    fallback_results = [
        result
        for result in (
            _map_google_place(place, origin_lat=latitude, origin_lng=longitude)
            for place in fallback_places
        )
        if result.place_id and result.name
    ]
    primary_results, strict_sorted, fallback_sorted, used_fallback, result_label = _build_response_result_sets(
        strict_results=strict_results,
        fallback_results=fallback_results,
        limit=limit,
    )
    await _replace_cache(
        db,
        dish_key=dish_key,
        lat_bucket=lat_bucket,
        lng_bucket=lng_bucket,
        location_text=location_text,
        radius_m=radius_m,
        query=query,
        results=primary_results,
    )
    return FoodPlaceSearchResponse(
        query=query,
        dish=dish,
        location_text=location_text,
        latitude=latitude,
        longitude=longitude,
        radius_m=radius_m,
        cache_hit=False,
        results=primary_results,
        strict_results=strict_sorted,
        fallback_results=fallback_sorted,
        used_fallback_results=used_fallback,
        result_label=result_label,
        provider="google_places_text_search",
    )


async def _search_with_serpapi(
    *,
    query: str,
    dish: str,
    location_text: str,
    limit: int,
    latitude: float | None,
    longitude: float | None,
    radius_m: int,
) -> FoodPlaceSearchResponse:
    payload = await asyncio.to_thread(
        _call_serpapi_local_search,
        query,
        location_text=location_text,
        latitude=latitude,
        longitude=longitude,
        radius_m=radius_m,
    )
    places = payload.get("local_results") or []
    filtered_places = [
        place
        for place in places
        if is_place_payload_dict(place) and is_place_relevant_for_dish(place, dish)
    ]
    strict_results = [
        result
        for result in (
            _map_serpapi_place(place, origin_lat=latitude, origin_lng=longitude)
            for place in filtered_places
        )
        if result.place_id and result.name
    ]
    fallback_source_places = [
        place for place in places if is_place_payload_dict(place)
    ]
    fallback_places = select_fallback_places(
        fallback_source_places,
        dish,
        limit=limit,
    )
    fallback_results = [
        result
        for result in (
            _map_serpapi_place(place, origin_lat=latitude, origin_lng=longitude)
            for place in fallback_places
        )
        if result.place_id and result.name
    ]
    primary_results, strict_sorted, fallback_sorted, used_fallback, result_label = _build_response_result_sets(
        strict_results=strict_results,
        fallback_results=fallback_results,
        limit=limit,
    )
    return FoodPlaceSearchResponse(
        query=query,
        dish=dish,
        location_text=location_text,
        latitude=latitude,
        longitude=longitude,
        radius_m=radius_m,
        cache_hit=False,
        results=primary_results,
        strict_results=strict_sorted,
        fallback_results=fallback_sorted,
        used_fallback_results=used_fallback,
        result_label=result_label,
        provider="serpapi_google_search",
    )


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
    normalized_location_text = (location_text or DEFAULT_LOCATION_TEXT).strip() or DEFAULT_LOCATION_TEXT
    query = build_food_place_query(
        dish,
        normalized_location_text,
        has_coordinates=latitude is not None and longitude is not None,
    )
    provider = _active_places_provider()

    if provider == "serpapi":
        try:
            return await _search_with_serpapi(
                query=query,
                dish=dish,
                location_text=normalized_location_text,
                limit=limit,
                latitude=latitude,
                longitude=longitude,
                radius_m=radius_m,
            )
        except HTTPException as exc:
            if not settings.google_maps_api_key:
                raise
            print(f"⚠️ SerpApi places search failed, fallback to Google Places: {exc.detail}")

    return await _search_with_google_places(
        query=query,
        dish=dish,
        location_text=normalized_location_text,
        limit=limit,
        db=db,
        latitude=latitude,
        longitude=longitude,
        radius_m=radius_m,
    )
