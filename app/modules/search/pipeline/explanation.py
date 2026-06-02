"""Explanation helpers that preserve deterministic reranking output."""

from __future__ import annotations

from typing import Iterable

from .types import ScoredFood


def build_generation_guardrails() -> str:
    return (
        "You are a generator, not a validator. "
        "Do not add foods. Do not remove foods. Do not reorder foods. "
        "Explain only the foods and order provided by the ranking stage."
    )


def build_reason(scored_food: ScoredFood) -> str:
    score = round(scored_food.final_score * 100, 1)
    signals = set(scored_food.reason_signals)

    if "disliked_ingredient_penalty" in signals or "disliked_ingredient_text_penalty" in signals:
        return f"Khớp ngữ nghĩa tốt ({score}%) nhưng có nguyên liệu bạn không thích nên bị hạ điểm."
    if "meal_context_match" in signals or "occasion_context_match" in signals:
        return f"Khớp nhu cầu món ăn và đúng ngữ cảnh bữa ăn ({score}%)."
    if "preferred_ingredient_match" in signals:
        return f"Khớp nguyên liệu bạn muốn và giữ điểm ngữ nghĩa cao ({score}%)."
    if "medical_prefer_tag_match" in signals:
        return f"Có đặc tính được ưu tiên theo hồ sơ sức khỏe và khớp truy vấn ({score}%)."
    return f"Khớp ngữ nghĩa với yêu cầu của bạn ({score}%)."


def build_ordered_foods_summary(scored_foods: Iterable[ScoredFood]) -> list[dict]:
    foods_summary: list[dict] = []
    for rank, item in enumerate(scored_foods, 1):
        food = item.food
        foods_summary.append({
            "rank": rank,
            "name": getattr(food, "name", ""),
            "score": round(item.final_score * 100, 1),
            "reason_signals": item.reason_signals,
        })
    return foods_summary
