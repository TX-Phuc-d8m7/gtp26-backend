"""Helper resolve món ăn được nhắc tới trong hội thoại chat."""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.foods.models import Food


def strip_accents(text: str) -> str:
    """Bỏ dấu tiếng Việt để match query ngắn trong chat."""
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
    """Normalize text về lowercase không dấu để so khớp tham chiếu món."""
    normalized = strip_accents(text or "").lower()
    normalized = re.sub(r"[^a-z0-9\s/_-]", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def extract_target_reference(query: str) -> str | None:
    """Rút tham chiếu kiểu top 1/món đầu/món này từ query."""
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
    """Tìm item trong food_results theo tham chiếu top_n."""
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
    """Resolve món từ tên trực tiếp hoặc tham chiếu trong kết quả gần nhất."""
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
