"""Intent classifier cho chatbot.

Module này nhận câu hỏi hiện tại + ngữ cảnh hội thoại gần nhất, sau đó phân loại
ý định của user để dispatcher gọi đúng handler. Luồng xử lý ưu tiên rule nhanh
cho các case chắc chắn, gọi Gemini cho case cần hiểu ngữ cảnh, và fallback
rule-based khi LLM lỗi/timeout.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from google.genai import types

from app.modules.chat.engine.food_reference import extract_target_reference, normalize_text
from app.modules.search.intent import client, get_gemini_text_model, valid_health_tags

# Danh sách intent là contract giữa classifier và dispatcher.
# Khi thêm intent mới, cần cập nhật cả prompt/schema ở file này và route trong dispatcher.py.
INTENT_OPTIONS = [
    "new_search",
    "follow_up",
    "food_info",
    "food_safety_check",
    "location_search",
    "greeting",
    "off_topic",
]

# Các cụm này giúp rule fallback phân biệt câu "hỏi gợi ý món" dưới ràng buộc sức khỏe
# với câu "kiểm tra một món cụ thể có ăn được không".
RECOMMENDATION_SEARCH_CLUES = [
    "an gi",
    "mon gi",
    "nen an",
    "goi y",
    "tim mon",
    "muon an",
    "van muon an",
    "duoc an gi",
]

# Hiện chưa dùng trực tiếp trong rule chính, nhưng giữ lại như nhóm từ khóa tham chiếu
# cho các rule food_safety_check khi mở rộng classifier.
SPECIFIC_DISH_CHECK_CLUES = [
    "co sao khong",
    "an duoc khong",
    "an toan",
    "co hop khong",
    "kiem tra an toan",
]


def _response_schema() -> dict[str, Any]:
    """Schema ép Gemini trả JSON ổn định để dispatcher không phải đoán field."""
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
    """Prompt hệ thống mô tả intent, entity cần trích xuất và quy tắc dùng context."""
    return f"""
    Bạn là Hệ thống Phân loại Ý định (Intent Classifier) cốt lõi cho Trợ lý Ẩm thực & Sức khỏe AI của tập đoàn công nghệ.
    Nhiệm vụ của bạn là phân tích payload JSON đầu vào (bao gồm câu hỏi hiện tại và ngữ cảnh hội thoại trước đó) để trích xuất ý định (intent) và các thực thể (entities) theo đúng schema yêu cầu.

    # DANH SÁCH INTENT & QUY TẮC CHỌN (CHỌN 1 INTENT DUY NHẤT):
    1. `greeting`: Lời chào hỏi, tương tác xã giao cơ bản (VD: "chào bot", "bạn tên gì", "hello").
    2. `new_search`: Bắt đầu một luồng tìm kiếm món ăn mới hoặc thay đổi hẳn tiêu chí tìm kiếm.
       - Dấu hiệu: Hỏi món ăn dựa trên tình trạng sức khoẻ, thời gian, thời tiết (VD: "Sáng nay ăn gì?", "Bị tiểu đường thì nên ăn gì?", "Đang thèm đồ nước").
       - LƯU Ý QUAN TRỌNG: Nếu user đề cập bệnh lý/dị ứng kèm theo mong muốn được gợi ý (VD: "Mình bị dị ứng hải sản nhưng vẫn muốn ăn đồ nướng thì ăn gì?"), bắt buộc phải phân loại là `new_search`, KHÔNG PHẢI `food_safety_check`.
    3. `follow_up`: Thao tác trên danh sách món ăn trợ lý VỪA GỢI Ý ở lượt trước (`last_assistant_has_food_results` = true).
       - Dấu hiệu: Lọc, loại trừ, xếp hạng, đổi tiêu chí nhỏ dựa trên kết quả cũ (VD: "Loại mấy món nước ra đi", "Trong mấy món trên, ưu tiên món rẻ hơn", "Thêm đồ cay vào gợi ý vừa rồi").
    4. `food_info`: Hỏi thông tin chi tiết của một món ăn cụ thể.
       - Dấu hiệu: Hỏi về calo, thành phần, cách nấu, mô tả, nguồn gốc (VD: "Phở bò bao nhiêu calo?", "Cách nấu bún chả?", "Món số 1 làm từ nguyên liệu gì?").
    5. `food_safety_check`: Xác thực tính an toàn của MỘT MÓN CỤ THỂ đối với một tình trạng sức khỏe/bệnh lý.
       - Dấu hiệu: Câu hỏi có tính chất "Có được ăn không?", "Có an toàn không?", "Có sao không?" đối với một món đã chỉ định rõ (VD: "Bị loét dạ dày ăn xoài chua được không?", "Món top 2 người dị ứng đậu phộng ăn có sao không?").
    6. `location_search`: Nhu cầu tìm quán ăn, nhà hàng, địa điểm thực tế bán một món ăn.
       - Dấu hiệu: "Ở đâu", "quán nào", "địa chỉ", "gần đây" (VD: "Ăn bún bò ở đâu ngon?", "Tìm quán bún chả gần trường Bách Khoa").
    7. `off_topic`: Các câu hỏi ngoài luồng, không liên quan đến ẩm thực, sức khỏe dinh dưỡng hay tìm quán ăn (VD: "Viết giùm đoạn code Python", "Giá vàng hôm nay").

    # HƯỚNG DẪN TRÍCH XUẤT THỰC THỂ (EXTRACTED FIELDS):
    Dựa vào context được cung cấp trong payload, hãy trích xuất cẩn thận:
    - `food_name`: Tên món ăn cụ thể được nhắc đến. Nếu user dùng đại từ (món đó, món đầu tiên, top 2) hãy tham chiếu mảng `last_food_names` trong payload để điền tên món ăn thực tế vào đây.
    - `target_reference`: Nếu user dùng đại từ chỉ định ("top 1", "món 2", "món cuối"), hãy map thành dạng `top_1`, `top_2`, `last_item`.
    - `location_query`: Trích xuất chuỗi địa điểm, khu vực, tên đường nếu user có nhắc đến (VD: "Liên Chiểu", "Bách Khoa", "Đà Nẵng").
    - `dish_query`: Tên món ăn mà user muốn tìm địa điểm quán (thường đi kèm intent `location_search`).
    - `health_topic`: Trích xuất tình trạng bệnh lý, dị ứng, triệu chứng sức khỏe (VD: "tiểu đường", "dị ứng tôm", "đau dạ dày"). Tham chiếu chuẩn hoá theo danh sách sau nếu có thể: {valid_health_tags}.

    # LƯU Ý VỀ NGỮ CẢNH (CONTEXT MATCHING):
    - Hãy luôn xem xét `last_user_message` và `last_intent` để hiểu luồng hội thoại. Nếu câu hỏi hiện tại ngắn gọn (VD: "còn món nào khác không?"), hãy dựa vào context trước đó để xác định `new_search` hay `follow_up`.
    - Trả về JSON theo đúng schema yêu cầu, cung cấp chỉ số `confidence` (0.0 đến 1.0) thể hiện mức độ tự tin của bạn vào kết quả phân loại.
    """


def _classify_with_gemini(payload: dict[str, Any]) -> dict[str, Any]:
    """Gọi Gemini intent classifier với response schema dạng JSON."""
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
    """Trích xuất entity tối thiểu khi không dùng được Gemini."""
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


def _has_any_token(query_norm: str, tokens: list[str]) -> bool:
    """Kiểm tra query đã normalize có chứa một trong các token/cụm từ khóa."""
    return any(token in query_norm for token in tokens)


def _is_recommendation_under_health_constraint(query_norm: str, extracted: dict[str, Any]) -> bool:
    """Nhận diện câu hỏi gợi ý món trong bối cảnh bệnh lý/dị ứng."""
    has_health_signal = bool(extracted.get("health_topic")) or "di ung" in query_norm or "benh" in query_norm
    if not has_health_signal:
        return False
    return _has_any_token(query_norm, RECOMMENDATION_SEARCH_CLUES)


def _rule_based_short_circuit(query: str) -> dict[str, Any] | None:
    """
    Bắt nhanh các intent có độ chắc chắn cao trước khi gọi LLM.

    Mục tiêu là giảm latency cho greeting và tránh Gemini phân loại nhầm câu
    "bị bệnh/dị ứng nên ăn gì" thành food_safety_check.
    """
    query_norm = normalize_text(query)
    extracted = _fallback_extracted(query)

    pure_greetings = {
        "chao",
        "chao ban",
        "chao bot",
        "xin chao",
        "hello",
        "hi",
        "hey",
        "helo",
    }
    search_clues = [
        "an gi",
        "mon gi",
        "goi y",
        "tim mon",
        "toi nay",
        "an toi",
        "an trua",
        "an sang",
        "thanh dam",
        "giau dam",
        "protein",
        "calo",
        "quan",
        "dia chi",
        "co sao khong",
        "an toan",
    ]

    if query_norm in pure_greetings:
        return {
            "intent": "greeting",
            "confidence": 0.99,
            "extracted": extracted,
        }

    if (
        any(query_norm.startswith(token) for token in ["chao", "xin chao", "hello", "hi", "hey"])
        and len(query_norm.split()) <= 6
        and not any(clue in query_norm for clue in search_clues)
    ):
        return {
            "intent": "greeting",
            "confidence": 0.95,
            "extracted": extracted,
        }

    if _is_recommendation_under_health_constraint(query_norm, extracted):
        return {
            "intent": "new_search",
            "confidence": 0.97,
            "extracted": extracted,
        }

    return None


def _fallback_classify(
    *,
    current_query: str,
    last_assistant_has_food_results: bool,
) -> dict[str, Any]:
    """
    Classifier dự phòng khi Gemini lỗi/timeout hoặc trả payload không hợp lệ.

    Confidence cố định thấp để downstream/debug biết đây không phải kết quả LLM.
    """
    query_norm = normalize_text(current_query)
    extracted = _fallback_extracted(current_query)

    greeting_tokens = ["chao", "hello", "hi", "xin chao", "chao bot"]
    off_topic_tokens = ["node js", "nodejs", "javascript", "python", "crawl", "scrape", "viet code", "lap trinh", "api key"]
    location_tokens = ["quan", "dia chi", "gan day", "gan", "o dau", "ban mon", "tim quan"]
    safety_tokens = ["co sao khong", "an duoc khong", "an toan", "kiem tra an toan", "co hop khong"]
    food_info_tokens = ["thanh phan", "nguyen lieu", "calo", "kcal", "protein", "bao nhieu", "mo ta"]
    follow_up_tokens = ["loai", "bo", "khong thich", "trong may mon tren", "mays mon tren", "moi uu tien", "uu tien", "sap xep lai"]

    if any(token in query_norm for token in greeting_tokens):
        intent = "greeting"
    elif any(token in query_norm for token in off_topic_tokens):
        intent = "off_topic"
    elif any(token in query_norm for token in location_tokens):
        intent = "location_search"
    elif _is_recommendation_under_health_constraint(query_norm, extracted):
        intent = "new_search"
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
    """
    Public entrypoint cho dispatcher.

    Luồng:
    1. Rule short-circuit cho các case chắc chắn.
    2. Gọi Gemini kèm context hội thoại.
    3. Nếu lỗi/timeout/schema sai thì fallback rule-based.
    4. Normalize output để dispatcher luôn nhận cùng một shape.
    """
    shortcut = _rule_based_short_circuit(current_query)
    if shortcut is not None:
        return shortcut

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
