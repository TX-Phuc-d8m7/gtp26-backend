"""Truy xuất ngữ nghĩa và lexical fallback cho search.

Module này gọi Gemini embedding cho query và cung cấp tín hiệu lexical khi
embedding lỗi/timeout. `service.search_food` dùng kết quả ở đây để chấm điểm
candidate foods, nhưng không đặt logic orchestration trong file này.
"""

from __future__ import annotations

import asyncio
import time

import numpy as np
from google.genai import types

from app.modules.foods.models import Food
from app.modules.search.common import (
    EMBEDDING_TIMEOUT_SECONDS,
    FALLBACK_STOPWORDS,
    _normalize_search_text,
    _phrase_in_text,
    client,
    get_food_scoring_tags,
    matched_canonical_tags,
    split_food_category_tags,
)


async def run_embedding_with_timeout(expanded_query: str) -> tuple[list[float] | None, dict]:
    """Sinh embedding cho query và fallback sang lexical mode nếu embedding lỗi/timeout."""
    started_at = time.perf_counter()
    runtime = {"status": "ok", "latency_ms": 0, "error_message": None}

    def get_embedding():
        return client.models.embed_content(
            model='gemini-embedding-001',
            contents=expanded_query,
            config=types.EmbedContentConfig(
                output_dimensionality=3072,
                task_type="RETRIEVAL_QUERY"
            )
        )

    try:
        embedding_response = await asyncio.wait_for(
            asyncio.to_thread(get_embedding),
            timeout=EMBEDDING_TIMEOUT_SECONDS,
        )
        runtime["latency_ms"] = round((time.perf_counter() - started_at) * 1000)
        return embedding_response.embeddings[0].values, runtime
    except asyncio.TimeoutError:
        runtime["latency_ms"] = round((time.perf_counter() - started_at) * 1000)
        runtime["status"] = "fallback"
        runtime["error_message"] = f"embedding timeout after {EMBEDDING_TIMEOUT_SECONDS}s"
        print(f"[EMBEDDING] Timeout sau {EMBEDDING_TIMEOUT_SECONDS}s, dùng lexical fallback.")
        return None, runtime
    except Exception as exc:
        runtime["latency_ms"] = round((time.perf_counter() - started_at) * 1000)
        runtime["status"] = "fallback"
        runtime["error_message"] = str(exc)[:300]
        print(f"[EMBEDDING] Lỗi: {exc}, dùng lexical fallback.")
        return None, runtime

def _dedupe_normalized_phrases(values: list[str]) -> list[str]:
    """Chuẩn hóa và loại trùng các phrase để dùng cho lexical fallback scoring."""
    seen = set()
    phrases = []
    for value in values or []:
        normalized = _normalize_search_text(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            phrases.append(normalized)
    return phrases

def build_fallback_query_signals(
    query: str,
    user_include_dishes: list[str],
    final_include_ings: list[str],
    user_include_tags: list[str],
    medical_prefer_tags: list[str],
) -> dict:
    """Tạo bộ tín hiệu truy vấn dạng keyword/tag để chấm điểm khi embedding không khả dụng."""
    grouped_tags = split_food_category_tags(list(set((user_include_tags or []) + (medical_prefer_tags or []))))
    soft_tag_phrases = (
        grouped_tags["soft_tags"] +
        grouped_tags["taste_profile"] +
        grouped_tags["occasion_context"]
    )
    meal_context_phrases = grouped_tags["meal_context"]
    normalized_query = _normalize_search_text(query)
    residual_terms = []
    for term in normalized_query.split():
        if len(term) >= 3 and term not in FALLBACK_STOPWORDS and term not in residual_terms:
            residual_terms.append(term)

    return {
        "name_phrases": _dedupe_normalized_phrases(user_include_dishes),
        "ingredient_phrases": _dedupe_normalized_phrases(final_include_ings),
        "soft_tag_phrases": _dedupe_normalized_phrases(soft_tag_phrases),
        "meal_context_phrases": _dedupe_normalized_phrases(meal_context_phrases),
        "residual_terms": residual_terms,
    }

def _phrase_match_ratio(phrases: list[str], text_value: str) -> tuple[float, list[str]]:
    """Tính tỷ lệ phrase truy vấn khớp trong một chuỗi text cùng danh sách phrase đã match."""
    if not phrases:
        return 0.0, []
    normalized_text = _normalize_search_text(text_value)
    matched = [phrase for phrase in phrases if _phrase_in_text(normalized_text, phrase)]
    return len(matched) / max(1, len(phrases)), matched

def _normalized_tag_match_ratio(phrases: list[str], values: list[str]) -> tuple[float, list[str]]:
    """Tính tỷ lệ khớp giữa phrase/tag truy vấn và tập tag của món sau khi chuẩn hóa."""
    if not phrases:
        return 0.0, []
    value_keys = {_normalize_search_text(value) for value in (values or [])}
    matched = [phrase for phrase in phrases if phrase in value_keys]
    return len(matched) / max(1, len(phrases)), matched

def calculate_lexical_fallback_score(food: Food, query_signals: dict) -> tuple[float, dict]:
    """Chấm điểm thay thế cho semantic search bằng tín hiệu keyword/tag có trọng số."""
    name_score, matched_name_phrases = _phrase_match_ratio(
        query_signals["name_phrases"],
        food.name or "",
    )
    ingredient_score, matched_ingredient_phrases = _phrase_match_ratio(
        query_signals["ingredient_phrases"],
        " ".join(food.core_ingredients or []),
    )
    soft_tag_score, matched_soft_tags = _normalized_tag_match_ratio(
        query_signals["soft_tag_phrases"],
        get_food_scoring_tags(food),
    )
    meal_context_score, matched_meal_contexts = _normalized_tag_match_ratio(
        query_signals["meal_context_phrases"],
        food.meal_context or [],
    )
    residual_text = " ".join([
        food.name or "",
        " ".join(food.core_ingredients or []),
        " ".join(get_food_scoring_tags(food)),
    ])
    residual_score, matched_residual_terms = _phrase_match_ratio(
        query_signals["residual_terms"],
        residual_text,
    )
    score = min(
        1.0,
        name_score * 0.30 +
        ingredient_score * 0.30 +
        meal_context_score * 0.20 +
        soft_tag_score * 0.15 +
        residual_score * 0.05,
    )
    return score, {
        "name_score": name_score,
        "ingredient_score": ingredient_score,
        "meal_context_score": meal_context_score,
        "soft_tag_score": soft_tag_score,
        "residual_score": residual_score,
        "matched_name_phrases": matched_name_phrases,
        "matched_ingredient_phrases": matched_ingredient_phrases,
        "matched_meal_contexts": matched_meal_contexts,
        "matched_soft_tags_lexical": matched_soft_tags,
        "matched_residual_terms": matched_residual_terms,
    }
