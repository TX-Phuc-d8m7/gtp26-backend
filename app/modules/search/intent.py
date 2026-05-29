"""Phân tích intent/constraint ban đầu cho food search.

Module này quản lý supervisor LLM, schema response của supervisor và fallback
rule-based khi Gemini lỗi/timeout. Kết quả được `safety.resolve_food_conflicts`
dùng để merge với rule y tế và profile người dùng.
"""

from __future__ import annotations

import asyncio
import json
import time

from google.genai import types

from app.modules.search.common import (
    SUPERVISOR_TIMEOUT_SECONDS,
    USER_FOOD_BASE_PROMPT_LIST,
    _has_any_phrase,
    _normalize_search_text,
    canonicalize_health_tag,
    client,
    get_gemini_text_model,
    valid_health_tags,
    valid_soft_tags,
)


def _fallback_intent_from_query(user_input: str) -> dict:
    """Rule-based fallback rất nhỏ khi supervisor LLM không sẵn sàng."""
    query_text = _normalize_search_text(user_input)
    health_constraints: list[str] = []
    include_soft_tags: list[str] = []

    health_phrase_map = [
        (["dị ứng tôm", "di ung tom", "dị ứng tép", "di ung tep", "dị ứng cua", "di ung cua", "dị ứng ghẹ", "di ung ghe"], "Dị ứng động vật giáp xác"),
        (["dị ứng trứng", "di ung trung"], "Dị ứng trứng"),
        (["dị ứng sữa", "di ung sua", "dị ứng sữa bò", "di ung sua bo"], "Dị ứng sữa bò"),
        (["bất dung nạp lactose", "bat dung nap lactose", "không dung nạp lactose", "khong dung nap lactose"], "Bất dung nạp Lactose"),
        (["cao huyết áp", "cao huyet ap", "huyết áp cao", "huyet ap cao"], "Cao huyết áp"),
        (["tiểu đường", "tieu duong", "đái tháo đường", "dai thao duong"], "Tiểu đường"),
        (["gout", "gút"], "Gout"),
        (["đau dạ dày", "dau da day", "viêm loét dạ dày", "viem loet da day"], "Viêm loét dạ dày"),
    ]
    soft_tag_phrase_map = [
        (["ăn sáng", "an sang", "bữa sáng", "bua sang"], "Ăn sáng"),
        (["ăn trưa", "an trua", "bữa trưa", "bua trua", "cơm trưa", "com trua"], "Ăn trưa"),
        (["ăn tối", "an toi", "bữa tối", "bua toi", "cơm tối", "com toi"], "Ăn tối"),
        (["bữa chính", "bua chinh"], "Ăn no"),
        (["ăn vặt", "an vat"], "Ăn vặt"),
        (["tráng miệng", "trang mieng"], "Tráng miệng"),
        (["món nước", "mon nuoc", "đồ nước", "do nuoc"], "Món nước"),
        (["nóng hổi", "nong hoi", "nóng nóng", "nong nong", "ấm nóng", "am nong"], "Nóng hổi"),
    ]

    for phrases, tag in health_phrase_map:
        if _has_any_phrase(query_text, phrases) and tag not in health_constraints:
            health_constraints.append(tag)

    for phrases, tag in soft_tag_phrase_map:
        if _has_any_phrase(query_text, phrases) and tag not in include_soft_tags:
            include_soft_tags.append(tag)

    return {
        "health_constraints": health_constraints,
        "include_dishes": [],
        "exclude_dishes": [],
        "include_ingredients": [],
        "exclude_ingredients": [],
        "include_soft_tags": include_soft_tags,
        "exclude_soft_tags": [],
        "analysis_note": "Rule-based fallback vì supervisor LLM không khả dụng.",
    }

async def run_supervisor_with_timeout(user_input: str) -> tuple[dict, dict]:
    """Chạy supervisor với timeout và fallback sang rule-based intent khi LLM lỗi."""
    started_at = time.perf_counter()
    runtime = {"status": "ok", "latency_ms": 0, "error_message": None}
    try:
        extracted_data = await asyncio.wait_for(
            asyncio.to_thread(supervisor_agent, user_input),
            timeout=SUPERVISOR_TIMEOUT_SECONDS,
        )
        runtime["latency_ms"] = round((time.perf_counter() - started_at) * 1000)
        if isinstance(extracted_data, dict) and extracted_data.get("error"):
            runtime["status"] = "fallback"
            runtime["error_message"] = str(extracted_data.get("error"))[:300]
            return _fallback_intent_from_query(user_input), runtime
        return extracted_data, runtime
    except asyncio.TimeoutError:
        runtime["latency_ms"] = round((time.perf_counter() - started_at) * 1000)
        runtime["status"] = "fallback"
        runtime["error_message"] = f"supervisor timeout after {SUPERVISOR_TIMEOUT_SECONDS}s"
        print(f"[SUPERVISOR] Timeout sau {SUPERVISOR_TIMEOUT_SECONDS}s, dùng fallback_intent.")
        return _fallback_intent_from_query(user_input), runtime
    except Exception as exc:
        runtime["latency_ms"] = round((time.perf_counter() - started_at) * 1000)
        runtime["status"] = "fallback"
        runtime["error_message"] = str(exc)[:300]
        print(f"[SUPERVISOR] Lỗi wrapper: {exc}, dùng fallback_intent.")
        return _fallback_intent_from_query(user_input), runtime

def supervisor_agent(user_input: str):
    """Sử dụng LLM (Gemini) để phân tích ý định của người dùng ra định dạng JSON tĩnh."""

    system_instruction = f"""
    Bạn là chuyên gia phân tích ý định người dùng trong ẩm thực.
    Nhiệm vụ: Trích xuất thông tin sức khỏe và sở thích ăn uống.

    [DANH SÁCH TAG SỨC KHỎE HỢP LỆ]
    {valid_health_tags}

    [DANH SÁCH TÍNH CHẤT (SOFT TAGS) HỢP LỆ]
    {valid_soft_tags}

    [DANH SÁCH NHÓM MÓN NỀN CÓ THỂ ĐƯA VÀO include_dishes/exclude_dishes]
    {USER_FOOD_BASE_PROMPT_LIST}

    [QUY TẮC PHÂN LOẠI]
    1. health_constraints: Chỉ chọn từ danh sách trên. Map các từ đồng nghĩa (VD: đau dạ dày -> Viêm loét dạ dày).
       QUAN TRỌNG — Phân biệt dị ứng hải sản (KHÔNG được tự mở rộng sang nhóm không được đề cập):
       - "Dị ứng động vật giáp xác": CHỈ map khi user đề cập tôm / tép / cua / ghẹ / tôm hùm / bề bề / tôm càng.
         Ví dụ: "dị ứng tôm cua ghẹ" -> ["Dị ứng động vật giáp xác"] — KHÔNG thêm "Dị ứng động vật thân mềm".
       - "Dị ứng động vật thân mềm": CHỈ map khi user đề cập mực / bạch tuộc / ốc / sò / nghêu / hến / hàu / vẹm.
         Ví dụ: "dị ứng mực ốc" -> ["Dị ứng động vật thân mềm"] — KHÔNG thêm "Dị ứng động vật giáp xác".
       - Chỉ thêm CẢ HAI khi user nói "dị ứng hải sản" hoặc liệt kê cụ thể từ cả hai nhóm.
       - TUYỆT ĐỐI không tự suy luận "dị ứng giáp xác thường đi kèm thân mềm" — chỉ map đúng những gì user nói rõ.
    2. include_dishes: Tên món ăn cụ thể hoặc nhóm món nền người dùng muốn.
       - Nếu user nói tên món cụ thể, GIỮ NGUYÊN tên món cụ thể và ưu tiên tên đó.
       - Ví dụ: "bún bò" -> "bún bò"; "bún riêu" -> "bún riêu"; "cơm gà" -> "cơm gà"; "mì quảng chay" -> "mì quảng chay".
       - Chỉ dùng nhóm món nền trong danh sách trên khi user thật sự nói nhu cầu dạng rộng như "muốn ăn bún", "tìm món cơm", "ăn phở", "thèm lẩu".
    3. exclude_dishes: Tên món ăn hoàn chỉnh hoặc nhóm món nền người dùng KHÔNG muốn ăn.
       - Nếu user phủ định/né/tránh tên món cụ thể, GIỮ NGUYÊN tên món cụ thể trong exclude_dishes.
       - Nếu user phủ định/né/tránh nhóm món nền, đưa nhóm nền đó vào exclude_dishes.
       - Ví dụ: "không ăn bún bò" -> "bún bò"; "không ăn bún" -> "bún"; "né phở", "ngoại trừ bánh mì", "không muốn cơm" -> exclude_dishes tương ứng.
       - Nếu cùng một món/nhóm món vừa xuất hiện ở ý muốn và ý không muốn, ưu tiên ý không muốn.
    4. exclude_ingredients: Danh sách các nguyên liệu người dùng KHÔNG MUỐN.
    5. include_ingredients: Danh sách các nguyên liệu người dùng CẢM THẤY THÍCH.
       - Không đưa các nhóm món nền như bún/cơm/phở/mì vào include_ingredients hoặc exclude_ingredients; hãy dùng include_dishes/exclude_dishes.
    6. include_soft_tags (SỞ THÍCH CHỦ ĐỘNG): CHỈ TRÍCH XUẤT khi user ĐÍCH THÂN phát ngôn yêu cầu một tính chất, hương vị, hoặc bữa ăn. 
       - NGUYÊN TẮC THÉP: LLM chỉ là "Máy ghi âm", tuyệt đối KHÔNG ĐƯỢC SUY DIỄN nhu cầu dựa trên bệnh lý.
       - Thời điểm/bữa ăn: "sáng mai" -> "Ăn sáng"; "tối nay" -> "Ăn tối"; "khuya" -> "Ăn khuya".
       - Ngữ cảnh: "no bụng" -> "Ăn no"; "ăn vặt" -> "Ăn vặt"; "nhậu" -> "Mồi nhậu".
       - Tính chất: "món nước" -> "Món nước"; "nóng hổi" -> "Nóng hổi"; "thanh mát" -> "Thanh mát / Giải nhiệt".

    7. exclude_soft_tags (PHỦ ĐỊNH CHỦ ĐỘNG): CHỈ ĐIỀN khi user đích thân dùng các từ ngữ phủ định rõ ràng (không/ít/tránh/sợ/đừng) đối với một tính chất món ăn.
       - Mặc định PHẢI TRẢ [] nếu user không nói các từ khóa phủ định sở thích.
       - Ví dụ hợp lệ: "tôi không ăn cay" -> ["Cay"]; "đừng làm đồ béo" -> ["Béo ngậy"].
       
    8. QUY TẮC CÁCH LY Y KHOA (RẤT QUAN TRỌNG): 
       - `health_constraints` là nơi DUY NHẤT để ghi nhận bệnh lý/triệu chứng. Backend sẽ tự động dùng rule SQL/Python để chặn món ăn. 
       - LLM BỊ NGHIÊM CẤM tự ý dịch bệnh lý thành các tags khẩu vị (`include_soft_tags`, `exclude_soft_tags`).
       - [VÍ DỤ ĐÚNG 1]: "Tôi bị viêm loét dạ dày, muốn ăn sáng ấm bụng" 
        -> health_constraints=["Viêm loét dạ dày"], include_soft_tags=["Ăn sáng", "Ấm bụng"], exclude_soft_tags=[]
       - [VÍ DỤ ĐÚNG 2 - TRƯỜNG HỢP CẦN CHÚ Ý]: "Tôi đang bị nhiệt miệng đau lắm, ăn gì cho mau khỏi?"
        -> health_constraints=["Nhiệt miệng"]
        -> include_soft_tags=[] (VÌ USER KHÔNG YÊU CẦU MÓN NƯỚC HAY ĐỒ MÁT)
        -> exclude_soft_tags=[] (VÌ USER KHÔNG BẢO "ĐỪNG ĂN CAY/NÓNG")
    """

    response_schema = {
        "type": "OBJECT",
        "properties": {
            "health_constraints": {
                "type": "ARRAY",
                "items": {"type": "STRING", "enum": valid_health_tags}
            },
            "include_dishes": {"type": "ARRAY", "items": {"type": "STRING"}},
            "exclude_dishes": {"type": "ARRAY", "items": {"type": "STRING"}},
            "include_ingredients": {"type": "ARRAY", "items": {"type": "STRING"}},
            "exclude_ingredients": {"type": "ARRAY", "items": {"type": "STRING"}},
            "include_soft_tags": {
                "type": "ARRAY",
                "items": {"type": "STRING", "enum": valid_soft_tags}
            },
            "exclude_soft_tags": {
                "type": "ARRAY",
                "items": {"type": "STRING", "enum": valid_soft_tags}
            },
            "analysis_note": {"type": "STRING"}
        },
        "required": [
            "health_constraints", "include_dishes", "exclude_dishes", 
            "include_ingredients", "exclude_ingredients", 
            "include_soft_tags", "exclude_soft_tags"
        ]
    }

    try:
        response = client.models.generate_content(
            model=get_gemini_text_model(),
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.2,
                response_mime_type="application/json",
                response_schema=response_schema
            ),
            contents=user_input
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"Lỗi Gemini: {e}")
        return {"error": str(e)}
