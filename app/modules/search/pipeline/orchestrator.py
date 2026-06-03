"""Semantic-first food search orchestrator."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from app.core.config import settings

from ._utils import coerce_list as _coerce_list, dedupe as _dedupe, get_field as _get_field
from .explanation import build_generation_guardrails, build_reason
from .intent import intent_from_conflict_payload
from .retrieval import (
    RETRIEVAL_EXPANSION_FACTOR,
    build_semantic_query_text,
    lexical_retrieve_foods,
    needs_retrieval_expansion,
    semantic_retrieve_foods,
)
from .safety import apply_critical_safety_filter, select_critical_exclude_tags
from .scoring import rank_candidates
from .types import CriticalSafetyRules, ExtractedIntent, RejectedFood, RetrievedFood, ScoredFood

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.modules.search.schemas import AIInsight, FoodResult, SearchResponse
    from app.modules.users.models import UserHealthProfile


SEMANTIC_PIPELINE_VERSION = "semantic_first_v1"
SEARCH_DISCLAIMER = (
    "Hệ thống đã sàng lọc nguyên liệu theo điều kiện sức khỏe cá nhân nhưng không "
    "thay thế tư vấn từ bác sĩ/chuyên gia y tế. Vui lòng kiểm tra lại thành phần "
    "thực tế trước khi gọi món."
)
EMBEDDING_FALLBACK_RETRIEVAL_NOTE = (
    "Kết quả đang được gợi ý theo tìm kiếm từ khóa do dịch vụ phân tích tạm thời gián đoạn."
)


def _setting_int(name: str, default: int) -> int:
    value = getattr(settings, name, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _setting_float(name: str, default: float) -> float:
    value = getattr(settings, name, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _json_safe(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return value


def _food_result_from_scored(scored: ScoredFood) -> FoodResult:
    from app.modules.search.schemas import FoodResult

    food = scored.food
    return FoodResult(
        id=_get_field(food, "id"),
        name=str(_get_field(food, "name", "")),
        description=str(_get_field(food, "description", "")),
        img_url=_get_field(food, "img_url"),
        core_ingredients=_coerce_list(_get_field(food, "core_ingredients", [])),
        soft_tags=_coerce_list(_get_field(food, "soft_tags", [])),
        taste_profile=_coerce_list(_get_field(food, "taste_profile", [])),
        meal_context=_coerce_list(_get_field(food, "meal_context", [])),
        occasion_context=_coerce_list(_get_field(food, "occasion_context", [])),
        matchScore=round(scored.final_score * 100, 2),
        reason=build_reason(scored),
        dining_context=_get_field(food, "dining_context"),
    )


def _candidate_trace(candidate: RetrievedFood) -> dict[str, Any]:
    food = candidate.food
    return {
        "food_id": _json_safe(_get_field(food, "id")),
        "food_name": _get_field(food, "name"),
        "semantic_score": candidate.semantic_score,
        "retrieval_rank": candidate.retrieval_rank,
        "retrieval_mode": candidate.retrieval_mode,
    }


def _rejected_trace(rejected: RejectedFood) -> dict[str, Any]:
    return {
        **_candidate_trace(rejected.candidate),
        "reason": rejected.decision.reason,
        "matched_values": rejected.decision.matched_values,
    }


def _scored_trace(scored: ScoredFood) -> dict[str, Any]:
    return {
        "food_id": _json_safe(_get_field(scored.food, "id")),
        "food_name": _get_field(scored.food, "name"),
        "semantic_score": scored.semantic_score,
        "final_score": scored.final_score,
        "retrieval_rank": scored.retrieval_rank,
        "retrieval_mode": scored.retrieval_mode,
        "reason_signals": scored.reason_signals,
        "score_breakdown": scored.score_breakdown.__dict__,
    }


def _build_ai_insight(
    payload: dict[str, Any],
    critical_exclude_ings: list[str],
) -> AIInsight:
    from app.modules.search.schemas import AIInsight

    return AIInsight(
        exclude=_dedupe(payload.get("medical_exclude_tags", []) + critical_exclude_ings),
        include=_dedupe(payload.get("symptoms", [])),
        prefer=_dedupe(
            payload.get("medical_prefer_tags", [])
            + payload.get("final_include_ings", [])
            + payload.get("medical_prefer_ings", [])
        ),
        warning_message=payload.get("warning_message"),
    )


def _build_safety_rules(
    payload: dict[str, Any],
    critical_exclude_ingredient_keys: list[str],
) -> CriticalSafetyRules:
    return CriticalSafetyRules(
        health_constraints=_dedupe(payload.get("symptoms", [])),
        excluded_ingredient_keys=critical_exclude_ingredient_keys,
        critical_exclude_tags=select_critical_exclude_tags(payload.get("symptoms", [])),
        allergy_constraints=_dedupe(payload.get("allergy_constraints", [])),
        allergy_exclude_ingredients=_dedupe(payload.get("allergy_exclude_ings", [])),
        exclude_dishes=_dedupe(payload.get("user_exclude_dishes", [])),
    )


def _build_empty_response(
    query: str,
    payload: dict[str, Any] | None = None,
    *,
    retrieval_note: str | None = None,
) -> SearchResponse:
    from app.modules.search.schemas import AIInsight, SearchResponse

    ai_insight = _build_ai_insight(payload or {}, []) if payload else AIInsight(exclude=[], include=[], prefer=[])
    return SearchResponse(
        query=query,
        ai_insight=ai_insight,
        results=[],
        disclaimer=SEARCH_DISCLAIMER,
        retrieval_note=retrieval_note,
        ai_response=(
            "Mình chưa tìm được món đủ phù hợp sau khi áp dụng điều kiện an toàn. "
            "Bạn có thể thử nới bớt sở thích không bắt buộc hoặc mô tả món mong muốn cụ thể hơn."
        ),
    )


async def _generate_response_text(
    query: str,
    payload: dict[str, Any],
    results: list[FoodResult],
    retrieval_notes: list[str],
) -> tuple[str, dict]:
    from app.modules.search import service as legacy_search

    ai_response_text, _food_reasons_map, runtime = await legacy_search.run_post_processing_with_timeout(
        query,
        payload.get("symptoms", []),
        results,
        retrieval_notes,
    )
    return ai_response_text, runtime


async def _retrieve_candidates(
    db: "AsyncSession",
    query: str,
    intent: ExtractedIntent,
    semantic_query_text: str,
    retrieval_notes: list[str],
    llm_runtime: dict[str, Any],
) -> tuple[list[RetrievedFood], str, list[float] | None]:
    """Retrieve candidates and return (candidates, retrieval_mode, query_vector).

    query_vector is returned for semantic mode so the caller can perform
    expansion retrieval if the safety filter starves the result pool.
    For lexical_fallback, query_vector is None (whole table already scanned).
    """
    from app.modules.search import service as legacy_search

    top_k = _setting_int("semantic_retrieval_top_k", 100)
    query_vector, embedding_runtime = await legacy_search.run_embedding_with_timeout(semantic_query_text)
    llm_runtime["embedding_status"] = embedding_runtime.get("status", "ok")
    llm_runtime.setdefault("stage_latency_ms", {})["embedding"] = embedding_runtime.get("latency_ms", 0)
    if embedding_runtime.get("error_message"):
        llm_runtime["embedding_error"] = embedding_runtime["error_message"]

    if query_vector is not None:
        candidates = await semantic_retrieve_foods(
            db,
            list(query_vector),
            top_k=top_k,
        )
        if candidates:
            llm_runtime["retrieval_mode"] = "semantic"
            return candidates, "semantic", list(query_vector)
        llm_runtime["retrieval_empty_reason"] = "no_embedded_foods"
    else:
        retrieval_notes.append(EMBEDDING_FALLBACK_RETRIEVAL_NOTE)
        llm_runtime["user_visible_retrieval_note_applied"] = True

    llm_runtime["retrieval_mode"] = "lexical_fallback"
    llm_runtime.setdefault("fallbacks_used", []).append("embedding")
    candidates = await lexical_retrieve_foods(
        db,
        query,
        intent,
        top_k=top_k,
    )
    return candidates, "lexical_fallback", None


async def semantic_first_search_food(
    query: str,
    db: "AsyncSession",
    profile: "UserHealthProfile | None" = None,
    thread_id: uuid.UUID | None = None,
    top_k: int = 5,
    debug: bool = False,
) -> SearchResponse:
    """Run the 4-stage Semantic Retrieval -> Safety -> Rerank -> Explanation flow."""
    from app.modules.search import service as legacy_search
    from app.modules.ingredients.service import (
        generate_filter_keys,
        load_enabled_alias_override_rules,
    )
    from app.modules.query_logs.service import create_query_log

    llm_runtime = legacy_search._new_llm_runtime_state()
    llm_runtime["pipeline_version"] = SEMANTIC_PIPELINE_VERSION
    retrieval_notes: list[str] = []

    payload = await legacy_search.resolve_food_conflicts(query, db, profile=profile)
    if not payload:
        return _build_empty_response(query)

    payload_runtime = payload.get("llm_runtime") or {}
    llm_runtime["supervisor_status"] = payload_runtime.get("supervisor_status", "ok")
    llm_runtime.setdefault("stage_latency_ms", {}).update(
        payload_runtime.get("stage_latency_ms", {})
    )
    if payload_runtime.get("supervisor_error"):
        llm_runtime["supervisor_error"] = payload_runtime["supervisor_error"]
    if payload_runtime.get("fallback_extracted_constraints"):
        llm_runtime["fallback_extracted_constraints"] = payload_runtime["fallback_extracted_constraints"]
    if llm_runtime["supervisor_status"] == "fallback":
        llm_runtime.setdefault("fallbacks_used", []).append("supervisor")
        llm_runtime["user_visible_warning_applied"] = True

    alias_override_rules = await load_enabled_alias_override_rules(db)
    intent = intent_from_conflict_payload(
        payload,
        category_splitter=legacy_search.split_food_category_tags,
        key_generator=generate_filter_keys,
        extra_rules=alias_override_rules,
    )
    semantic_query_text = build_semantic_query_text(query, intent)

    candidates, retrieval_mode, query_vector = await _retrieve_candidates(
        db,
        query,
        intent,
        semantic_query_text,
        retrieval_notes,
        llm_runtime,
    )

    critical_exclude_ings = _dedupe(
        payload.get("allergy_exclude_ings", [])
        + payload.get("disease_exclude_ings", [])
    )
    critical_exclude_ingredient_keys = generate_filter_keys(
        critical_exclude_ings,
        extra_rules=alias_override_rules,
    )
    safety_rules = _build_safety_rules(payload, critical_exclude_ingredient_keys)

    return_limit = max(1, min(top_k, _setting_int("search_return_limit", 5)))
    safe_candidates, rejected_candidates = apply_critical_safety_filter(
        candidates,
        safety_rules,
    )

    if (
        query_vector is not None
        and needs_retrieval_expansion(len(safe_candidates), return_limit, retrieval_mode)
    ):
        expanded_top_k = (
            _setting_int("semantic_retrieval_top_k", 100) * RETRIEVAL_EXPANSION_FACTOR
        )
        wider_candidates = await semantic_retrieve_foods(db, query_vector, top_k=expanded_top_k)
        llm_runtime["retrieval_expansion_attempted"] = True
        llm_runtime["retrieval_expanded_top_k"] = expanded_top_k
        if len(wider_candidates) > len(candidates):
            candidates = wider_candidates
            safe_candidates, rejected_candidates = apply_critical_safety_filter(
                candidates,
                safety_rules,
            )
            llm_runtime.setdefault("fallbacks_used", []).append("retrieval_expanded")

    ranked = rank_candidates(
        safe_candidates,
        intent,
        limit=return_limit,
        min_score=_setting_float("semantic_min_score", 0.0),
    )
    results = [_food_result_from_scored(scored) for scored in ranked]

    ai_insight = _build_ai_insight(payload, critical_exclude_ings)
    query_log_id = None
    ai_response_text = None
    post_processing_runtime: dict[str, Any] = {"status": "skipped", "latency_ms": 0}

    if results:
        ai_response_text, post_processing_runtime = await _generate_response_text(
            query,
            payload,
            results,
            retrieval_notes,
        )
        llm_runtime["post_processing_status"] = post_processing_runtime.get("status", "ok")
        llm_runtime.setdefault("stage_latency_ms", {})["post_processing"] = (
            post_processing_runtime.get("latency_ms", 0)
        )
        if post_processing_runtime.get("error_message"):
            llm_runtime["post_processing_error"] = post_processing_runtime["error_message"]
        if post_processing_runtime.get("status") == "fallback":
            llm_runtime.setdefault("fallbacks_used", []).append("post_processing")
    else:
        ai_response_text = _build_empty_response(query, payload).ai_response

    excluded_summary = {
        "pipeline_version": SEMANTIC_PIPELINE_VERSION,
        "semantic_query_text": semantic_query_text,
        "retrieval": {
            "mode": retrieval_mode,
            "top_k": _setting_int("semantic_retrieval_top_k", 100),
            "expanded_top_k": llm_runtime.get("retrieval_expanded_top_k"),
            "candidate_count": len(candidates),
            "sample": [_candidate_trace(candidate) for candidate in candidates[:10]],
        },
        "critical_safety": {
            "health_constraints": safety_rules.health_constraints,
            "excluded_ingredient_keys": critical_exclude_ingredient_keys,
            "critical_exclude_tags": safety_rules.critical_exclude_tags,
            "allergy_constraints": safety_rules.allergy_constraints,
            "exclude_dishes": safety_rules.exclude_dishes,
            "rejected_count": len(rejected_candidates),
            "rejected_sample": [_rejected_trace(item) for item in rejected_candidates[:20]],
            "safe_count": len(safe_candidates),
        },
        "soft_scoring": {
            "medical_avoid_tags": intent.medical_avoid_tags,
            "scored_count": len(safe_candidates),
            "returned_count": len(results),
            "top_results": [_scored_trace(item) for item in ranked],
        },
        "explanation": {
            "generation_guardrails": build_generation_guardrails(),
            "can_reorder": False,
        },
        "llm_runtime": llm_runtime,
    }

    try:
        query_log = await create_query_log(
            db,
            query=query,
            ai_insight=ai_insight,
            final_exclude_ings=critical_exclude_ings,
            exclude_ingredient_keys=critical_exclude_ingredient_keys,
            user_include_tags=payload.get("user_include_tags", []),
            user_exclude_tags=payload.get("user_exclude_tags", []),
            candidate_count=len(candidates),
            filtered_count=len(safe_candidates),
            scored_count=len(safe_candidates),
            returned_count=len(results),
            excluded_summary=_json_safe(excluded_summary),
            retrieval_notes=retrieval_notes,
            top_results=results,
            warning_message=payload.get("warning_message"),
            thread_id=thread_id,
        )
        query_log_id = query_log.id
    except Exception as exc:
        print(f"[SEMANTIC QUERY LOG] Không thể lưu query log: {exc}")
        await db.rollback()

    from app.modules.search.schemas import SearchResponse

    return SearchResponse(
        query=query,
        ai_insight=ai_insight,
        results=results,
        disclaimer=SEARCH_DISCLAIMER,
        query_log_id=query_log_id,
        retrieval_note=retrieval_notes[0] if retrieval_notes else None,
        retrieval_trace=_json_safe(excluded_summary) if debug else None,
        ai_response=ai_response_text or None,
    )
