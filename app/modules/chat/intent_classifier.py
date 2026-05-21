from __future__ import annotations

import asyncio
import json
from typing import Any

from google.genai import types

from app.modules.chat.handlers.common import extract_target_reference, normalize_text
from app.modules.search.service import client, get_gemini_text_model, valid_health_tags

INTENT_OPTIONS = [
    "new_search",
    "follow_up",
    "food_info",
    "food_safety_check",
    "location_search",
    "greeting",
    "off_topic",
]


def _response_schema() -> dict[str, Any]:
    return {
        "type": "OBJECT",
        "properties": {
            "intent": {
                "type": "STRING",
                "enum": INTENT_OPTIONS,
            },
            "confidence": {"type": "NUMBER"},
            "extracted": {
                "type": "OBJECT",
                "properties": {
                    "food_name": {"type": "STRING"},
                    "target_reference": {"type": "STRING"},
                    "location_query": {"type": "STRING"},
                    "dish_query": {"type": "STRING"},
                    "health_topic": {"type": "STRING"},
                },
            },
        },
        "required": ["intent", "confidence", "extracted"],
    }


def _build_system_instruction() -> str:
    return f"""
    Bạn là bộ phân loại intent cho chatbot ẩm thực.
    Hãy chọn duy nhất một intent phù hợp nhất:
    {", ".join(INTENT_OPTIONS)}

    Quy tắc:
    - `greeting`: chỉ chào hỏi, mở lời, chưa có nhu cầu xử lý cụ thể.
    - `new_search`: user đang muốn tìm món mới hoặc đổi yêu cầu tìm món.
    - `follow_up`: user đang lọc/xếp lại từ danh sách món vừa có, thường nói "mấy món trên", "loại ra", "bỏ món nước", "ưu tiên thanh đạm hơn".
    - `food_info`: user hỏi thông tin về 1 món cụ thể như thành phần, mô tả, hợp ăn lúc nào.
    - `food_safety_check`: user hỏi ăn món đó có sao không, có an toàn không, có hợp dị ứng/bệnh lý không.
    - `location_search`: user muốn tìm quán/địa điểm bán món.
    - `off_topic`: nội dung ngoài miền ẩm thực/tư vấn món/quán.

    Các field extracted:
    - `food_name`: tên món cụ thể nếu có.
    - `target_reference`: nếu user nói "top 1", "món đầu", "món đó" thì map thành `top_1`, `top_2`, ...
    - `location_query`: khu vực user nhắc tới nếu có.
    - `dish_query`: món cần tìm quán bán nếu có.
    - `health_topic`: chỉ điền nếu user nói rõ một bệnh lý/dị ứng cụ thể liên quan kiểm tra an toàn.

    Danh sách health tag hợp lệ tham chiếu khi cần:
    {valid_health_tags}
    """


def _classify_with_gemini(payload: dict[str, Any]) -> dict[str, Any]:
    response = client.models.generate_content(
        model=get_gemini_text_model(),
        config=types.GenerateContentConfig(
            system_instruction=_build_system_instruction(),
            temperature=0.1,
            response_mime_type="application/json",
            response_schema=_response_schema(),
        ),
        contents=json.dumps(payload, ensure_ascii=False),
    )
    return json.loads(response.text)


def _fallback_extracted(query: str) -> dict[str, Any]:
    query_norm = normalize_text(query)
    health_topic = None
    for tag in valid_health_tags:
        if normalize_text(tag) in query_norm:
            health_topic = tag
            break
    location_query = None
    if "lien chieu" in query_norm:
        location_query = "Liên Chiểu"
    elif "bach khoa" in query_norm:
        location_query = "gần Đại học Bách Khoa, quận Liên Chiểu"
    elif "da nang" in query_norm:
        location_query = "Đà Nẵng"

    return {
        "food_name": None,
        "target_reference": extract_target_reference(query),
        "location_query": location_query,
        "dish_query": None,
        "health_topic": health_topic,
    }


def _fallback_classify(
    *,
    current_query: str,
    last_assistant_has_food_results: bool,
) -> dict[str, Any]:
    query_norm = normalize_text(current_query)
    extracted = _fallback_extracted(current_query)

    greeting_tokens = ["chao", "hello", "hi", "xin chao", "chao bot"]
    off_topic_tokens = ["node js", "nodejs", "javascript", "python", "crawl", "scrape", "viet code", "lap trinh", "api key"]
    location_tokens = ["quan", "dia chi", "gan day", "gan", "o dau", "ban mon", "tim quan"]
    safety_tokens = ["co sao khong", "an duoc khong", "an toan", "di ung", "kiem tra an toan", "co hop khong"]
    food_info_tokens = ["thanh phan", "nguyen lieu", "calo", "kcal", "protein", "bao nhieu", "mo ta"]
    follow_up_tokens = ["loai", "bo", "khong thich", "trong may mon tren", "mays mon tren", "moi uu tien", "uu tien", "sap xep lai"]

    if any(token in query_norm for token in greeting_tokens):
        intent = "greeting"
    elif any(token in query_norm for token in off_topic_tokens):
        intent = "off_topic"
    elif any(token in query_norm for token in location_tokens):
        intent = "location_search"
    elif any(token in query_norm for token in safety_tokens):
        intent = "food_safety_check"
    elif any(token in query_norm for token in food_info_tokens):
        intent = "food_info"
    elif last_assistant_has_food_results and any(token in query_norm for token in follow_up_tokens):
        intent = "follow_up"
    else:
        intent = "new_search"

    return {
        "intent": intent,
        "confidence": 0.35,
        "extracted": extracted,
    }


async def classify_intent(
    *,
    current_query: str,
    last_user_message: str | None,
    last_assistant_message: str | None,
    last_assistant_has_food_results: bool,
    last_food_names: list[str],
    last_intent: str | None,
) -> dict[str, Any]:
    payload = {
        "current_query": current_query,
        "last_user_message": last_user_message or "",
        "last_assistant_message": last_assistant_message or "",
        "last_assistant_has_food_results": bool(last_assistant_has_food_results),
        "last_food_names": last_food_names[:5],
        "last_intent": last_intent,
    }

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_classify_with_gemini, payload),
            timeout=8,
        )
    except Exception:
        return _fallback_classify(
            current_query=current_query,
            last_assistant_has_food_results=last_assistant_has_food_results,
        )

    if not isinstance(result, dict):
        return _fallback_classify(
            current_query=current_query,
            last_assistant_has_food_results=last_assistant_has_food_results,
        )

    intent = result.get("intent")
    extracted = result.get("extracted") or {}
    if intent not in INTENT_OPTIONS:
        return _fallback_classify(
            current_query=current_query,
            last_assistant_has_food_results=last_assistant_has_food_results,
        )

    normalized = {
        "intent": intent,
        "confidence": float(result.get("confidence") or 0.0),
        "extracted": {
            "food_name": extracted.get("food_name") or None,
            "target_reference": extracted.get("target_reference") or extract_target_reference(current_query),
            "location_query": extracted.get("location_query") or None,
            "dish_query": extracted.get("dish_query") or None,
            "health_topic": extracted.get("health_topic") or None,
        },
    }
    return normalized
