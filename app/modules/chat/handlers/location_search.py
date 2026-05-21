from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.chat.handlers.common import (
    IntentHandlerResult,
    build_structured_result,
    extract_target_reference,
    resolve_food_candidate,
)
from app.modules.places.service import search_food_places


async def handle_location_search(
    *,
    raw_query: str,
    db: AsyncSession,
    last_food_results: list[dict] | None,
    food_name: str | None,
    target_reference: str | None,
    dish_query: str | None,
    location_query: str | None,
    lat: float | None,
    lng: float | None,
) -> IntentHandlerResult:
    target_reference = target_reference or extract_target_reference(raw_query)
    resolved_food, referenced_item, resolved_name = await resolve_food_candidate(
        db,
        food_name=food_name or dish_query,
        target_reference=target_reference,
        last_food_results=last_food_results,
    )

    dish_name = dish_query or (resolved_food.name if resolved_food is not None else None) or resolved_name
    if not dish_name and last_food_results:
        dish_name = str(last_food_results[0].get("name") or "").strip() or None

    if not dish_name:
        content = (
            "Mình chưa xác định được món nào để tìm quán bán. Bạn có thể nhắc rõ tên món hoặc chọn lại một món trong "
            "danh sách vừa gợi ý để mình tìm địa điểm quanh bạn."
        )
        return IntentHandlerResult(
            intent="location_search",
            content=content,
            structured_result=build_structured_result(
                "location_search",
                {
                    "status": "missing_dish",
                    "location_text": location_query or "Đà Nẵng",
                },
            ),
        )

    location_text = (location_query or "Đà Nẵng").strip() or "Đà Nẵng"
    try:
        place_result = await search_food_places(
            dish=dish_name,
            location_text=location_text,
            limit=5,
            db=db,
            latitude=lat,
            longitude=lng,
        )
    except Exception as exc:
        content = (
            f"Mình chưa thể tìm quán bán {dish_name} lúc này vì dịch vụ địa điểm đang gặp trục trặc. "
            "Bạn có thể thử lại sau hoặc gửi khu vực rõ hơn để mình tìm lại."
        )
        return IntentHandlerResult(
            intent="location_search",
            content=content,
            structured_result=build_structured_result(
                "location_search",
                {
                    "status": "error",
                    "dish": dish_name,
                    "location_text": location_text,
                    "error": str(exc),
                },
            ),
        )

    if not place_result.results:
        content = (
            f"Mình đã thử tìm quán bán {dish_name} quanh {place_result.location_text}, nhưng hiện chưa thấy kết quả phù hợp. "
            "Bạn có thể nới rộng khu vực hoặc thử tên món gần hơn với cách gọi của quán."
        )
    else:
        top_lines = []
        for place in place_result.results[:3]:
            distance_text = f", cách khoảng {place.distance_meters}m" if place.distance_meters is not None else ""
            rating_text = f", rating {place.rating}" if place.rating is not None else ""
            top_lines.append(f"{place.name}{distance_text}{rating_text}")
        content = (
            f"Mình đã tìm được vài quán có vẻ hợp với {dish_name} quanh {place_result.location_text}. "
            f"Nổi bật nhất hiện tại là {', '.join(top_lines)}."
        )

    return IntentHandlerResult(
        intent="location_search",
        content=content,
        place_result=place_result,
        structured_result=build_structured_result(
            "location_search",
            {
                "status": "resolved",
                "dish": dish_name,
                "location_text": place_result.location_text,
                "results": place_result.model_dump(),
                "referenced_food_name": referenced_item.get("name") if referenced_item else None,
            },
        ),
    )
