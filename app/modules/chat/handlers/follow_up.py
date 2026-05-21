from __future__ import annotations

from typing import Any

from app.modules.chat.handlers.common import (
    IntentHandlerResult,
    build_search_response_from_food_results,
    build_structured_result,
    normalize_text,
)


EXCLUDE_TAG_KEYWORDS = [
    ("Món nước", ["do nuoc", "mon nuoc"]),
    ("Gỏi / Nộm / Trộn", ["do goi", "mon goi", "goi"]),
    ("Sống/Chín tái", ["do song", "song tai", "chin tai"]),
    ("Chiên / Rán", ["do chien", "chien ran", "chien"]),
    ("Món khô", ["mon kho", "do kho"]),
]
PREFER_TAG_KEYWORDS = [
    ("Thanh đạm", ["thanh dam"]),
    ("Ấm bụng", ["am bung"]),
    ("Ăn tối", ["an toi", "toi nay"]),
    ("Giàu đạm", ["giau dam", "nhieu protein", "protein"]),
]
EXCLUDE_NAME_TOKENS = ["bun", "pho", "mi", "my", "lau", "goi", "salad"]
NEGATION_HINTS = ["khong", "bo", "loai", "tru", "ne", "so", "khong thich"]


def _should_exclude_phrase(query_norm: str, phrase_norm: str) -> bool:
    if phrase_norm not in query_norm:
        return False
    return any(hint in query_norm for hint in NEGATION_HINTS) or any(
        combo in query_norm for combo in [
            f"loai {phrase_norm}",
            f"bo {phrase_norm}",
            f"khong an {phrase_norm}",
            f"khong thich {phrase_norm}",
            f"so {phrase_norm}",
        ]
    )


def _apply_follow_up_filters(
    query: str,
    food_results: list[dict[str, Any]],
    target_food_name: str | None = None,
) -> tuple[list[dict[str, Any]], list[str], list[str], list[str]]:
    query_norm = normalize_text(query)
    excluded_tags: list[str] = []
    preferred_tags: list[str] = []
    excluded_name_tokens: list[str] = []

    for tag, phrases in EXCLUDE_TAG_KEYWORDS:
        if any(_should_exclude_phrase(query_norm, phrase) for phrase in phrases):
            excluded_tags.append(tag)

    for tag, phrases in PREFER_TAG_KEYWORDS:
        if any(phrase in query_norm for phrase in phrases):
            preferred_tags.append(tag)

    if target_food_name:
        excluded_name_tokens.append(normalize_text(target_food_name))

    if any(hint in query_norm for hint in NEGATION_HINTS):
        for token in EXCLUDE_NAME_TOKENS:
            if token in query_norm and token not in excluded_name_tokens:
                excluded_name_tokens.append(token)

    scored: list[tuple[float, dict[str, Any]]] = []
    for item in food_results:
        item_name_norm = normalize_text(str(item.get("name") or ""))
        all_tags = [
            *(item.get("soft_tags") or []),
            *(item.get("taste_profile") or []),
            *(item.get("meal_context") or []),
            *(item.get("occasion_context") or []),
        ]
        if any(token and token in item_name_norm for token in excluded_name_tokens):
            continue
        if any(tag in all_tags for tag in excluded_tags):
            continue

        score = float(item.get("matchScore") or 0.0)
        for tag in preferred_tags:
            if tag in all_tags:
                score += 6.0
        updated = dict(item)
        updated["matchScore"] = min(100.0, score)
        scored.append((score, updated))

    scored.sort(key=lambda value: value[0], reverse=True)
    return [item for _, item in scored], excluded_tags, preferred_tags, excluded_name_tokens


def _build_follow_up_content(
    *,
    filtered: list[dict[str, Any]],
    excluded_tags: list[str],
    preferred_tags: list[str],
    excluded_name_tokens: list[str],
) -> str:
    changes: list[str] = []
    if excluded_name_tokens:
        changes.append(f"đã loại các món khớp '{', '.join(excluded_name_tokens[:3])}'")
    if excluded_tags:
        changes.append(f"đã bỏ các món có đặc điểm {', '.join(excluded_tags[:3])}")
    if preferred_tags:
        changes.append(f"đồng thời ưu tiên các món thiên về {', '.join(preferred_tags[:3])}")

    if not filtered:
        prefix = "Mình đã áp dụng lại bộ lọc theo yêu cầu mới"
        if changes:
            prefix += f" ({'; '.join(changes)})"
        return (
            f"{prefix}, nhưng hiện không còn món nào trong danh sách trước đó phù hợp hẳn. "
            "Bạn có thể nới bớt một điều kiện để mình sắp xếp lại tiếp."
        )

    top_names = ", ".join(str(item.get("name") or "") for item in filtered[:3] if item.get("name"))
    prefix = "Đã rõ"
    if changes:
        prefix += f", mình { '; '.join(changes) }"
    return f"{prefix}. Sau khi lọc lại từ danh sách trước, các lựa chọn hợp lý nhất lúc này là {top_names}."


async def handle_follow_up(
    *,
    raw_query: str,
    last_food_results: list[dict[str, Any]],
    extracted_food_name: str | None = None,
) -> IntentHandlerResult:
    filtered, excluded_tags, preferred_tags, excluded_name_tokens = _apply_follow_up_filters(
        raw_query,
        last_food_results,
        target_food_name=extracted_food_name,
    )
    content = _build_follow_up_content(
        filtered=filtered,
        excluded_tags=excluded_tags,
        preferred_tags=preferred_tags,
        excluded_name_tokens=excluded_name_tokens,
    )
    search_result = build_search_response_from_food_results(
        query=raw_query,
        food_results=filtered,
        ai_response=content,
        retrieval_note="Danh sách được lọc lại từ kết quả gần nhất trong hội thoại.",
    )
    return IntentHandlerResult(
        intent="follow_up",
        content=content,
        search_result=search_result,
        food_results=filtered or None,
        structured_result=build_structured_result(
            "follow_up",
            {
                "query": raw_query,
                "food_results": filtered,
                "excluded_tags": excluded_tags,
                "preferred_tags": preferred_tags,
                "excluded_name_tokens": excluded_name_tokens,
            },
        ),
    )
