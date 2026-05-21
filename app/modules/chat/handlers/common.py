from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.foods.models import Food
from app.modules.search.schemas import AIInsight, FoodResult, SearchResponse


@dataclass
class IntentHandlerResult:
    intent: str
    content: str
    query_log_id: uuid.UUID | None = None
    search_result: SearchResponse | None = None
    place_result: Any | None = None
    food_results: list[dict[str, Any]] | None = None
    structured_result: dict[str, Any] | None = None


def strip_accents(text: str) -> str:
    accents = {
        "àáạảãâầấậẩẫăằắặẳẵ": "a",
        "èéẹẻẽêềếệểễ": "e",
        "ìíịỉĩ": "i",
        "òóọỏõôồốộổỗơờớợởỡ": "o",
        "ùúụủũưừứựửữ": "u",
        "ỳýỵỷỹ": "y",
        "đ": "d",
    }
    result = text or ""
    for source, target in accents.items():
        for ch in source:
            result = result.replace(ch, target).replace(ch.upper(), target.upper())
    return result


def normalize_text(text: str) -> str:
    normalized = strip_accents(text or "").lower()
    normalized = re.sub(r"[^a-z0-9\s/_-]", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def serialize_food_results(search_result: SearchResponse | None) -> list[dict[str, Any]] | None:
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
        }
        for item in search_result.results
    ]


def build_structured_result(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": kind,
        "data": data,
    }


def coerce_food_result_items(items: list[dict[str, Any]] | None) -> list[FoodResult]:
    results: list[FoodResult] = []
    for item in items or []:
        try:
            results.append(FoodResult(**item))
        except Exception:
            continue
    return results


def food_names_from_results(items: list[dict[str, Any]] | None, limit: int = 5) -> list[str]:
    names: list[str] = []
    for item in items or []:
        name = str(item.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
        if len(names) >= limit:
            break
    return names


def extract_target_reference(query: str) -> str | None:
    query_norm = normalize_text(query)
    patterns = [
        (r"\btop\s*([1-5])\b", "top_{n}"),
        (r"\bm(o|ó)n\s*so\s*([1-5])\b", "top_{n}"),
        (r"\bm(o|ó)n\s*thu\s*([1-5])\b", "top_{n}"),
    ]
    for pattern, template in patterns:
        match = re.search(pattern, query_norm)
        if not match:
            continue
        number = match.groups()[-1]
        return template.format(n=number)

    if any(token in query_norm for token in ["mon dau", "mon top dau", "mon nay", "mon do", "quan do"]):
        return "top_1"
    return None


def find_food_result_by_reference(
    food_results: list[dict[str, Any]] | None,
    target_reference: str | None,
) -> dict[str, Any] | None:
    if not food_results:
        return None
    if not target_reference:
        return None
    reference = (target_reference or "").strip().lower()
    if reference.startswith("top_"):
        try:
            index = int(reference.split("_", 1)[1]) - 1
        except (IndexError, ValueError):
            return None
        if 0 <= index < len(food_results):
            return food_results[index]
    return None


async def resolve_food_candidate(
    db: AsyncSession,
    *,
    food_name: str | None = None,
    target_reference: str | None = None,
    last_food_results: list[dict[str, Any]] | None = None,
) -> tuple[Food | None, dict[str, Any] | None, str | None]:
    referenced = find_food_result_by_reference(last_food_results, target_reference)
    if referenced:
        food_id = referenced.get("id")
        try:
            if food_id:
                food = await db.get(Food, uuid.UUID(str(food_id)))
                if food is not None:
                    return food, referenced, food.name
        except (ValueError, TypeError):
            pass

    candidate_name = (food_name or referenced.get("name") if referenced else food_name or "").strip()
    if not candidate_name:
        return None, referenced, None

    stmt_exact = (
        select(Food)
        .where(func.lower(Food.name) == candidate_name.lower())
        .limit(1)
    )
    exact = (await db.execute(stmt_exact)).scalar_one_or_none()
    if exact is not None:
        return exact, referenced, exact.name

    stmt_partial = (
        select(Food)
        .where(Food.name.ilike(f"%{candidate_name}%"))
        .order_by(func.length(Food.name).asc())
        .limit(1)
    )
    partial = (await db.execute(stmt_partial)).scalar_one_or_none()
    if partial is not None:
        return partial, referenced, partial.name

    if last_food_results:
        candidate_norm = normalize_text(candidate_name)
        for item in last_food_results:
            item_name = str(item.get("name") or "")
            if candidate_norm and candidate_norm in normalize_text(item_name):
                try:
                    food = await db.get(Food, uuid.UUID(str(item.get("id"))))
                except (ValueError, TypeError):
                    food = None
                return food, item, item_name

    return None, referenced, candidate_name or None


def build_search_response_from_food_results(
    *,
    query: str,
    food_results: list[dict[str, Any]],
    ai_response: str,
    retrieval_note: str | None = None,
) -> SearchResponse:
    return SearchResponse(
        query=query,
        ai_insight=AIInsight(exclude=[], include=[], prefer=[]),
        results=coerce_food_result_items(food_results),
        disclaimer=(
            "Hệ thống đã sàng lọc nguyên liệu theo điều kiện sức khỏe cá nhân nhưng "
            "không thay thế tư vấn từ bác sĩ/chuyên gia y tế. Vui lòng kiểm tra lại "
            "thành phần thực tế trước khi gọi món."
        ),
        retrieval_note=retrieval_note,
        ai_response=ai_response,
    )


def build_empty_search_response(
    *,
    query: str,
    ai_response: str,
    retrieval_note: str | None = None,
) -> SearchResponse:
    return SearchResponse(
        query=query,
        ai_insight=AIInsight(exclude=[], include=[], prefer=[]),
        results=[],
        disclaimer=(
            "Hệ thống đã sàng lọc nguyên liệu theo điều kiện sức khỏe cá nhân nhưng "
            "không thay thế tư vấn từ bác sĩ/chuyên gia y tế. Vui lòng kiểm tra lại "
            "thành phần thực tế trước khi gọi món."
        ),
        retrieval_note=retrieval_note,
        ai_response=ai_response,
    )
