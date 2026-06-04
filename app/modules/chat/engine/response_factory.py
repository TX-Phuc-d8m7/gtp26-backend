"""Response builders dùng chung cho chat module."""

from __future__ import annotations

from typing import Any

from app.modules.search.schemas import AIInsight, FoodResult, SearchResponse


CHAT_SEARCH_DISCLAIMER = (
    "Hệ thống đã sàng lọc nguyên liệu theo điều kiện sức khỏe cá nhân nhưng "
    "không thay thế tư vấn từ bác sĩ/chuyên gia y tế. Vui lòng kiểm tra lại "
    "thành phần thực tế trước khi gọi món."
)


def serialize_food_results(search_result: SearchResponse | None) -> list[dict[str, Any]] | None:
    """Chuyển SearchResponse.results thành list dict để lưu vào chat message."""
    if not search_result or not search_result.results:
        return None
    return [
        {
            "id": str(item.id),
            "name": item.name,
            "description": item.description,
            "img_url": item.img_url,
            "core_ingredients": item.core_ingredients,
            "soft_tags": item.soft_tags,
            "taste_profile": item.taste_profile,
            "meal_context": item.meal_context,
            "occasion_context": item.occasion_context,
            "matchScore": item.matchScore,
            "reason": item.reason,
            "dining_context": item.dining_context,
        }
        for item in search_result.results
    ]


def build_structured_result(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    """Đóng gói structured_result theo shape thống nhất cho chat message."""
    return {
        "kind": kind,
        "data": data,
    }


def build_search_message_content(search_result: SearchResponse) -> str:
    """Tạo nội dung chat cho kết quả search, có ghép warning nếu safety layer trả về."""
    content = search_result.ai_response or (
        "Xin lỗi, mình chưa tìm được món phù hợp cho yêu cầu này."
        if not search_result.results
        else f"Mình đã tìm được {len(search_result.results)} gợi ý phù hợp cho bạn."
    )
    warning_text = (search_result.ai_insight.warning_message or "").strip()
    if not warning_text:
        return content
    if warning_text in content:
        return content
    return f"{warning_text}\n\n{content}"


def coerce_food_result_items(items: list[dict[str, Any]] | None) -> list[FoodResult]:
    """Ép list dict đã lưu trong chat message về FoodResult, bỏ qua item lỗi."""
    results: list[FoodResult] = []
    for item in items or []:
        try:
            results.append(FoodResult(**item))
        except Exception:
            continue
    return results


def food_names_from_results(items: list[dict[str, Any]] | None, limit: int = 5) -> list[str]:
    """Lấy danh sách tên món duy nhất từ food_results đã serialize."""
    names: list[str] = []
    for item in items or []:
        name = str(item.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
        if len(names) >= limit:
            break
    return names


def build_search_response_from_food_results(
    *,
    query: str,
    food_results: list[dict[str, Any]],
    ai_response: str,
    retrieval_note: str | None = None,
    ai_insight: dict[str, Any] | None = None,
) -> SearchResponse:
    """Tạo SearchResponse từ food_results đã lưu trong chat history."""
    if ai_insight:
        try:
            parsed_insight = AIInsight(**ai_insight)
        except Exception:
            parsed_insight = AIInsight(exclude=[], include=[], prefer=[])
    else:
        parsed_insight = AIInsight(exclude=[], include=[], prefer=[])
    return SearchResponse(
        query=query,
        ai_insight=parsed_insight,
        results=coerce_food_result_items(food_results),
        disclaimer=CHAT_SEARCH_DISCLAIMER,
        retrieval_note=retrieval_note,
        ai_response=ai_response,
    )


def build_empty_search_response(
    *,
    query: str,
    ai_response: str,
    retrieval_note: str | None = None,
) -> SearchResponse:
    """Tạo SearchResponse rỗng cho các intent không sinh danh sách món."""
    return SearchResponse(
        query=query,
        ai_insight=AIInsight(exclude=[], include=[], prefer=[]),
        results=[],
        disclaimer=CHAT_SEARCH_DISCLAIMER,
        retrieval_note=retrieval_note,
        ai_response=ai_response,
    )
