from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.chat.handlers.common import (
    IntentHandlerResult,
    build_structured_result,
    normalize_text,
    resolve_food_candidate,
)


def _is_nutrition_estimate_question(query: str) -> bool:
    query_norm = normalize_text(query)
    return any(token in query_norm for token in ["calo", "kcal", "protein", "carb", "fat", "macro"])


async def handle_food_info(
    *,
    raw_query: str,
    db: AsyncSession,
    last_food_results: list[dict] | None,
    food_name: str | None,
    target_reference: str | None,
) -> IntentHandlerResult:
    food, referenced_item, resolved_name = await resolve_food_candidate(
        db,
        food_name=food_name,
        target_reference=target_reference,
        last_food_results=last_food_results,
    )

    if food is None:
        missing_name = resolved_name or food_name or "món này"
        content = (
            f"Mình chưa tìm thấy dữ liệu chi tiết cho {missing_name} trong thư viện món ăn hiện tại. "
            "Nếu bạn gửi tên món rõ hơn hoặc chọn một món trong danh sách vừa gợi ý, mình sẽ trả lời sát hơn."
        )
        return IntentHandlerResult(
            intent="food_info",
            content=content,
            structured_result=build_structured_result(
                "food_info",
                {
                    "status": "not_found",
                    "food_name": missing_name,
                },
            ),
        )

    if _is_nutrition_estimate_question(raw_query):
        content = (
            f"Mình có thể mô tả thành phần và tính chất của {food.name}, nhưng hiện chưa có số dinh dưỡng chuẩn "
            "như kcal hay gram protein cho món này trong cơ sở dữ liệu. Nếu bạn cần mức calo chính xác, nên kiểm tra "
            "định lượng thực tế từ quán hoặc công thức cụ thể."
        )
    else:
        ingredients = ", ".join((food.core_ingredients or [])[:6])
        soft_tags = ", ".join((food.soft_tags or [])[:5])
        meal_context = ", ".join((food.meal_context or [])[:3])
        content = (
            f"{food.name} là món có hương vị và ngữ cảnh khá rõ trong dữ liệu của mình. "
            f"Mô tả hiện có: {food.description} "
            f"Nguyên liệu nổi bật gồm {ingredients or 'chưa có chi tiết đầy đủ'}. "
            f"Các tính chất chính là {soft_tags or 'chưa gắn tag rõ ràng'}"
            f"{f', thường phù hợp cho {meal_context}' if meal_context else ''}."
        )

    return IntentHandlerResult(
        intent="food_info",
        content=content,
        structured_result=build_structured_result(
            "food_info",
            {
                "status": "resolved",
                "food_id": str(food.id),
                "food_name": food.name,
                "referenced_food_name": referenced_item.get("name") if referenced_item else None,
            },
        ),
    )

