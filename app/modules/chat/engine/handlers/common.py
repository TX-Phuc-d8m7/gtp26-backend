"""Compatibility exports cho chat handlers.

Logic dùng chung đã được tách sang `handlers.base`, `response_factory` và
`food_reference`. File này chỉ giữ re-export tạm thời để các import cũ không
bị vỡ trong giai đoạn refactor.
"""

from app.modules.chat.engine.food_reference import (
    extract_target_reference,
    find_food_result_by_reference,
    normalize_text,
    resolve_food_candidate,
    strip_accents,
)
from app.modules.chat.engine.handlers.base import IntentHandlerResult
from app.modules.chat.engine.response_factory import (
    build_empty_search_response,
    build_search_response_from_food_results,
    build_structured_result,
    coerce_food_result_items,
    food_names_from_results,
    serialize_food_results,
)

__all__ = [
    "IntentHandlerResult",
    "build_empty_search_response",
    "build_search_response_from_food_results",
    "build_structured_result",
    "coerce_food_result_items",
    "extract_target_reference",
    "find_food_result_by_reference",
    "food_names_from_results",
    "normalize_text",
    "resolve_food_candidate",
    "serialize_food_results",
    "strip_accents",
]
