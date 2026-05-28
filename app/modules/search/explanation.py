"""Sinh giải thích và câu trả lời cuối cho food search.

Module này tạo reason deterministic cho từng món, xử lý no-result response và
gọi post-processing LLM với medical advice rules để viết câu trả lời cuối cho
chat/search.
"""

from __future__ import annotations

import asyncio
import json
import time

from google.genai import types

from app.modules.foods.models import Food
from app.modules.search.common import (
    FALLBACK_AI_RESPONSE_TEMPLATE,
    MEDICAL_ADVICE_ALIAS_MAP,
    POST_PROCESSING_TIMEOUT_SECONDS,
    PRIMARY_MEAL_ROLES,
    _normalize_search_text,
    client,
    get_gemini_text_model,
    split_food_category_tags,
)
from app.modules.search.schemas import FoodResult
from app.shared.paths import STANDARD_DATA_DIR


_ADVICE_RULES_PATH = STANDARD_DATA_DIR / "generated-rules" / "medical-advice-rules" / "medical_advice_rules.json"
with _ADVICE_RULES_PATH.open("r", encoding="utf-8") as _f:
    MEDICAL_ADVICE_RULES: dict = json.load(_f)


def _join_reason_items(items: list[str], limit: int = 2) -> str:
    """Ghép một vài tín hiệu quan trọng thành cụm ngắn cho food.reason."""
    cleaned = []
    for item in items or []:
        if item and item not in cleaned:
            cleaned.append(item)
    return ", ".join(cleaned[:limit])

def build_food_reason(
    food: Food,
    match_score: float,
    score_details: dict,
    ingredient_priority_match: bool,
    requested_ingredients: list[str],
) -> str:
    """
    Sinh lý do ngắn cho từng card món ăn bằng rule/template.

    Không gọi LLM ở đây để giữ tốc độ và đảm bảo lý do bám sát scoring thật.
    """
    requested_ingredients_text = _join_reason_items(requested_ingredients, limit=3)
    matched_user_tags = score_details.get("matched_user_prefer_tags", []) or []
    matched_medical_tags = score_details.get("matched_medical_prefer_tags", []) or []
    matched_avoid_tags = score_details.get("matched_avoid_tags", []) or []
    grouped_user_tags = split_food_category_tags(matched_user_tags)

    user_context_tags = (
        grouped_user_tags["meal_context"] +
        grouped_user_tags["occasion_context"]
    )
    user_soft_taste_tags = (
        grouped_user_tags["soft_tags"] +
        grouped_user_tags["taste_profile"]
    )

    signals: list[str] = []
    serving_role = score_details.get("serving_role")
    if score_details.get("main_meal_request") and serving_role in PRIMARY_MEAL_ROLES:
        signals.append("phù hợp làm bữa chính")
    if user_context_tags:
        signals.append(f"khớp ngữ cảnh {_join_reason_items(user_context_tags)}")
    if user_soft_taste_tags:
        signals.append(f"khớp sở thích {_join_reason_items(user_soft_taste_tags)}")
    if matched_medical_tags:
        signals.append(f"có tín hiệu tốt cho sức khỏe như {_join_reason_items(matched_medical_tags)}")

    if ingredient_priority_match and requested_ingredients_text:
        opening = f"Khớp nguyên liệu bạn muốn ({requested_ingredients_text})"
        if signals:
            opening += f" và {signals[0]}"
        opening += f", với điểm phù hợp {match_score:.1f}%."
    elif requested_ingredients_text:
        opening = (
            f"Được gợi ý như lựa chọn thay thế an toàn hơn khi món có "
            f"{requested_ingredients_text} không đủ nổi bật sau lọc sức khỏe/ngữ cảnh"
        )
        if signals:
            opening += f"; món này {signals[0]}"
        opening += f", điểm phù hợp {match_score:.1f}%."
    elif signals:
        opening = f"Được gợi ý vì {signals[0]}"
        if len(signals) > 1:
            opening += f" và {signals[1]}"
        opening += f", điểm phù hợp {match_score:.1f}%."
    else:
        opening = f"Được xếp hạng cao nhờ mức tương đồng với câu hỏi, điểm phù hợp {match_score:.1f}%."

    explicit_conflicts = score_details.get("explicit_preference_conflicts", []) or []
    if explicit_conflicts:
        conflict_text = "; ".join(
            f"bạn ưu tiên {conflict['requested_tag']} nhưng món này có {conflict['returned_conflict_tag']}"
            for conflict in explicit_conflicts[:2]
        )
        opening += (
            f" Lưu ý: {conflict_text}; hệ thống vẫn đưa vào vì sau lọc sức khỏe/ngữ cảnh, "
            "đây là lựa chọn thay thế có điểm phù hợp cao."
        )

    if matched_avoid_tags:
        caution_tags = _join_reason_items(matched_avoid_tags)
        return (
            f"{opening} Tuy nhiên món có tín hiệu cần lưu ý ({caution_tags}), "
            "nên xem là lựa chọn cần điều chỉnh theo khuyến nghị sức khỏe."
        )

    medical_caution_matches = score_details.get("medical_caution_matches", []) or []
    if medical_caution_matches:
        caution_labels = _join_reason_items(
            [match.get("label") for match in medical_caution_matches],
            limit=2,
        )
        return (
            f"{opening} Tuy nhiên món có thành phần cần dùng vừa phải "
            f"({caution_labels}), nên kiểm soát khẩu phần/nước chấm theo khuyến nghị sức khỏe."
        )

    return opening

def _format_top_food_names_for_fallback(top_foods: list[FoodResult]) -> str:
    """Ghép 1-2 tên món đầu tiên thành cụm ngắn để chèn vào câu trả lời fallback."""
    names = [food.name for food in (top_foods or [])[:2] if food.name]
    if not names:
        return "các món trong danh sách gợi ý"
    if len(names) == 1:
        return names[0]
    return f"{names[0]} và {names[1]}"

def build_fallback_ai_response_with_notes(
    top_foods: list[FoodResult],
    symptoms: list[str],
    retrieval_notes: list[str] | None = None,
) -> str:
    """Sinh phản hồi dự phòng thân thiện khi post-processing không hoạt động ổn định."""
    health_sentence = (
        "Mình đã ưu tiên lọc theo yêu cầu sức khỏe hiện nhận diện được."
        if symptoms
        else "Nếu bạn có dị ứng hoặc bệnh lý, hãy kiểm tra kỹ nguyên liệu của món trước khi dùng."
    )
    retrieval_note_sentence = " ".join(retrieval_notes or [])
    return FALLBACK_AI_RESPONSE_TEMPLATE.format(
        top_food_names=_format_top_food_names_for_fallback(top_foods),
        retrieval_note_sentence=retrieval_note_sentence,
        health_sentence=health_sentence,
    )

def _parse_post_processing_result(
    raw: dict,
) -> tuple[str, dict[str, str]]:
    """Parse kết quả JSON từ post_processing_agent thành (ai_response, food_reasons_map).

    food_reasons_map: dict keyed by lowercase tên món → LLM reason.
    Dùng lowercase để so sánh không phân biệt chữ hoa/thường khi apply về FoodResult.
    """
    ai_response = (raw.get("ai_response") or "").strip()
    food_reasons_map: dict[str, str] = {}
    for item in raw.get("food_reasons") or []:
        name = (item.get("name") or "").strip()
        reason = (item.get("reason") or "").strip()
        if name and reason:
            food_reasons_map[name.lower()] = reason
    return ai_response, food_reasons_map


def _get_per_food_medical_warnings(
    food_soft_tags: list[str],
    food_ingredients: list[str],
    symptoms: list[str],
) -> list[str]:
    """Trả về cảnh báo y tế liên quan đến soft_tags/ingredients của một món cụ thể."""
    warnings: list[str] = []
    for symptom in symptoms:
        rule = MEDICAL_ADVICE_RULES.get(symptom) or MEDICAL_ADVICE_RULES.get(
            MEDICAL_ADVICE_ALIAS_MAP.get(symptom, "")
        )
        if not rule:
            continue
        for cond in rule.get("conditional_warnings", []):
            trigger_type = cond["trigger_type"]
            trigger_value = cond["trigger_value"]
            matched = (
                (trigger_type == "soft_tag" and trigger_value in food_soft_tags)
                or (trigger_type == "ingredient" and trigger_value in food_ingredients)
            )
            if matched and cond["warning_text"] not in warnings:
                warnings.append(cond["warning_text"])
    return warnings


async def run_post_processing_with_timeout(
    user_query: str,
    symptoms: list[str],
    top_foods: list[FoodResult],
    retrieval_notes: list[str] | None = None,
) -> tuple[str, dict[str, str], dict]:
    """Chạy post-processing với timeout và fallback sang template nếu LLM trả rỗng/lỗi.

    Returns:
        (ai_response_text, food_reasons_map, runtime)
        food_reasons_map: dict[lowercase_name → llm_reason]; rỗng nếu LLM lỗi/timeout.
    """
    started_at = time.perf_counter()
    runtime = {"status": "ok", "latency_ms": 0, "error_message": None}
    _empty_reasons: dict[str, str] = {}
    try:
        raw = await asyncio.wait_for(
            asyncio.to_thread(
                post_processing_agent,
                user_query,
                symptoms,
                top_foods,
                retrieval_notes,
            ),
            timeout=POST_PROCESSING_TIMEOUT_SECONDS,
        )
        runtime["latency_ms"] = round((time.perf_counter() - started_at) * 1000)
        if not raw:
            runtime["status"] = "fallback"
            runtime["error_message"] = "post_processing returned empty response"
            return build_fallback_ai_response_with_notes(top_foods, symptoms, retrieval_notes), _empty_reasons, runtime
        ai_response, food_reasons_map = _parse_post_processing_result(raw)
        if not ai_response:
            runtime["status"] = "fallback"
            runtime["error_message"] = "post_processing ai_response is empty"
            return build_fallback_ai_response_with_notes(top_foods, symptoms, retrieval_notes), _empty_reasons, runtime
        return ai_response, food_reasons_map, runtime
    except asyncio.TimeoutError:
        runtime["latency_ms"] = round((time.perf_counter() - started_at) * 1000)
        runtime["status"] = "fallback"
        runtime["error_message"] = f"post_processing timeout after {POST_PROCESSING_TIMEOUT_SECONDS}s"
        print(f"[POST-PROCESSING] Timeout sau {POST_PROCESSING_TIMEOUT_SECONDS}s, dùng template fallback.")
        return build_fallback_ai_response_with_notes(top_foods, symptoms, retrieval_notes), _empty_reasons, runtime
    except Exception as exc:
        runtime["latency_ms"] = round((time.perf_counter() - started_at) * 1000)
        runtime["status"] = "fallback"
        runtime["error_message"] = str(exc)[:300]
        print(f"[POST-PROCESSING] Lỗi wrapper: {exc}, dùng template fallback.")
        return build_fallback_ai_response_with_notes(top_foods, symptoms, retrieval_notes), _empty_reasons, runtime

def post_processing_agent(
    user_query: str,
    user_symptoms: list[str],
    top5_foods: list,  # List[FoodResult] - Pydantic objects
    retrieval_notes: list[str] | None = None,
) -> dict:
    """
    Dynamic Rule Injection Agent:
    1. Thu thập tất cả soft_tags + core_ingredients của Top 5 món
    2. Đối chiếu với medical_advice_rules.json theo từng bệnh lý của user
    3. Tổng hợp các cảnh báo phù hợp -> Bơm vào prompt -> Gọi LLM
    Trả về dict gồm:
      - ai_response: đoạn tổng quan ngắn; reason từng món được build deterministic ở service layer.
    """

    # --- Bước 1: Thu thập tags & ingredients từ Top 5 ---
    all_tags: set[str] = set()
    all_ingredients: set[str] = set()
    foods_summary = []

    for food in top5_foods:
        food_all_tags = (
            list(food.soft_tags)
            + list(food.taste_profile)
            + list(food.meal_context)
            + list(food.occasion_context)
        )
        all_tags.update(food_all_tags)
        all_ingredients.update(food.core_ingredients)
        per_food_warnings = _get_per_food_medical_warnings(
            food_soft_tags=food_all_tags,
            food_ingredients=list(food.core_ingredients),
            symptoms=user_symptoms,
        )
        foods_summary.append({
            "name": food.name,
            "reason": food.reason,
            "core_ingredients": food.core_ingredients,
            "tags": food.soft_tags,
            "taste_profile": food.taste_profile,
            "meal_context": food.meal_context,
            "occasion_context": food.occasion_context,
            "medical_warnings_for_this_food": per_food_warnings,
        })

    print(f"\n[POST-PROCESSING] All tags from top5: {all_tags}")

    # --- Bước 2 & 3: Đối chiếu luật & Tổng hợp cảnh báo ---
    collected_warnings: list[str] = []
    general_advices: list[str] = []

    for symptom in user_symptoms:
        rule = MEDICAL_ADVICE_RULES.get(symptom) or MEDICAL_ADVICE_RULES.get(MEDICAL_ADVICE_ALIAS_MAP.get(symptom, ""))
        if not rule:
            print(f"  [POST-PROCESSING] Không có luật cho bệnh: {symptom}")
            continue

        general_advices.append(f"({symptom}) {rule['general_advice']}")

        # Lifestyle tips: khuyến cáo lối sống luôn inject, không phụ thuộc vào món ăn
        for tip in rule.get("lifestyle_tips", []):
            general_advices.append(tip)

        # Kiểm tra điều kiện trigger cảnh báo
        for cond in rule.get("conditional_warnings", []):
            trigger_type = cond["trigger_type"]
            trigger_val  = cond["trigger_value"]

            matched = False
            if trigger_type == "soft_tag" and trigger_val in all_tags:
                matched = True
            elif trigger_type == "ingredient" and trigger_val in all_ingredients:
                matched = True

            if matched:
                collected_warnings.append(cond["warning_text"])
                print(f"  ✅ Trigger khớp [{symptom}]: '{trigger_val}' -> Bơm cảnh báo")

    # --- Bước 4: Tổng hợp medical_warnings ---
    advice_lines = general_advices + collected_warnings
    medical_warnings = "\n".join(
        [f"- {w}" for w in advice_lines]
    ) if advice_lines else "(Không có cảnh báo đặc biệt nào cho các món được gợi ý.)"

    foods_text = json.dumps(foods_summary, ensure_ascii=False, indent=2)
    symptoms_text = ", ".join(user_symptoms) if user_symptoms else "Không có bệnh lý đặc biệt"
    retrieval_notes_text = "\n".join(
        [f"- {note}" for note in (retrieval_notes or [])]
    ) if retrieval_notes else "(Không có ghi chú truy xuất đặc biệt.)"

    # --- Bước 5: Bơm luật vào Prompt (Dynamic Rule Injection) ---
    system_prompt = f"""\
Bạn là chuyên gia tư vấn dinh dưỡng và ẩm thực tận tâm tại Đà Nẵng.
Nhiệm vụ: Dựa vào dữ liệu có sẵn, trả về JSON gồm 2 phần: tổng quan ngắn và lý do riêng cho từng món.

[Tình trạng sức khỏe của người dùng]
{symptoms_text}

[Top món ăn đã qua lọc và xếp hạng]
{foods_text}

[Ghi chú truy xuất từ hệ thống]
{retrieval_notes_text}

[Hướng dẫn sức khỏe bắt buộc]
{medical_warnings}

[QUY TẮC AN TOÀN KHI VIẾT]
- Chỉ được nhắc tên món có trong danh sách. Không tự thêm món mới hoặc bịa món ngoài danh sách.
- Không được gọi một món là "rất phù hợp", "rất an toàn" nếu món đó có tag/nguyên liệu cần lưu ý.
- Mọi lời khuyên điều chỉnh cách ăn phải dựa trên [Hướng dẫn sức khỏe bắt buộc].
- Nếu [Ghi chú truy xuất từ hệ thống] có xung đột sở thích, bắt buộc giải thích ngắn trong ai_response.

[QUY TẮC CHO TRƯỜNG "ai_response" — tổng quan ngắn]
- Độ dài: 65-110 chữ, giọng gần gũi, KHÔNG dùng bullet point.
- Nội dung nên có 3 ý tự nhiên trong cùng một đoạn:
  1) Nhắc ngắn tình trạng/yêu cầu chính của user và tiêu chí ăn uống nên ưu tiên.
  2) Nhắc đủ các món trong danh sách top kết quả, có thể gom nhóm món tương tự để câu văn tự nhiên.
  3) Nếu danh sách có món cần điều chỉnh khi ăn, nêu cách ăn cụ thể thay vì loại bỏ tuyệt đối.
- Không nhắc điểm số, thứ hạng phần trăm hoặc match_score trong câu trả lời cho người dùng.
- Nếu user có Cao huyết áp và danh sách có món nước/nước sền sệt/súp/cháo, hãy nhắc thực tế: ăn phần cái, chan/húp ít nước dùng hoặc dặn giảm muối.
- Nếu user có bệnh dạ dày/GERD và danh sách có món chua/cay/đậm đà, hãy nhắc giảm nước chấm/gia vị kích ứng.
- Nếu top món có cả lựa chọn khô/healthy và món nước, hãy trình bày kiểu: "ưu tiên A/B; nếu thèm món nước như C/D thì lưu ý ...".
- Không chỉ nhắc duy nhất món #1 hoặc 1-2 món đầu; top 5 đều là kết quả trả về nên cần được đề cập trong ai_response, trừ khi danh sách có ít hơn 5 món.

[QUY TẮC CHO TRƯỜNG "food_reasons" — lý do từng món]
- Viết lý do tự nhiên (25-55 chữ) cho TỪNG món trong danh sách top, dùng tiếng Việt.
- Giải thích tại sao món phù hợp với câu hỏi của người dùng — không chỉ liệt kê tên tag kỹ thuật.
- Nếu "medical_warnings_for_this_food" của món đó không rỗng: lồng cảnh báo vào lý do một cách tự nhiên, không tách rời.
  VD: "Bún bò đậm đà, giàu đạm — phù hợp bữa trưa; nên ăn phần cái, hạn chế húp nước dùng nếu đang kiêng muối."
- Nếu "medical_warnings_for_this_food" rỗng: chỉ nêu tại sao món phù hợp, không thêm cảnh báo không có căn cứ.
- Không nhắc điểm số, matchScore, tên tag kỹ thuật (ví dụ: "soft_tag", "meal_context").
- Tên món trong food_reasons phải khớp chính xác với tên món trong danh sách top.

"""

    response_schema = {
        "type": "OBJECT",
        "properties": {
            "ai_response": {"type": "STRING"},
            "food_reasons": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "name":   {"type": "STRING"},
                        "reason": {"type": "STRING"},
                    },
                    "required": ["name", "reason"],
                },
            },
        },
        "required": ["ai_response", "food_reasons"],
    }

    # --- Bước 6: Gọi LLM ---
    try:
        response = client.models.generate_content(
            model=get_gemini_text_model(),
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.2,
                response_mime_type="application/json",
                response_schema=response_schema,
            ),
            contents=f"Câu hỏi gốc của người dùng: {user_query}"
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"[POST-PROCESSING] Lỗi LLM: {e}")
        return {}

def _build_no_result_retrieval_note(
    symptoms: list[str],
    safety_e_tags: list[str],
    final_e_ings: list[str],
    candidate_count: int,
    context_before_count: int,
    context_after_count: int,
    scored_count: int,
) -> str:
    """Tạo ghi chú kỹ thuật ngắn về lý do kết quả rỗng, dùng trong retrieval_notes."""
    reasons = []
    if candidate_count == 0:
        reasons.append("Không có món nào vượt qua bộ lọc nguyên liệu cứng")
    elif context_after_count == 0 and context_before_count > 0:
        reasons.append(
            f"Sau lọc nguyên liệu còn {context_before_count} món nhưng "
            "bị loại toàn bộ bởi bộ lọc ngữ cảnh bữa ăn"
        )
    elif scored_count == 0 and context_after_count > 0:
        reasons.append(
            f"{context_after_count} món còn lại thiếu embedding, "
            "không thể xếp hạng ngữ nghĩa"
        )
    else:
        reasons.append("Không có món nào đạt điểm sau tất cả bộ lọc")

    if safety_e_tags:
        reasons.append(f"Tính chất bị loại: {', '.join(safety_e_tags[:5])}")
    if final_e_ings:
        reasons.append(f"Nguyên liệu cấm: {', '.join(final_e_ings[:5])}")

    return "Kết quả rỗng — " + "; ".join(reasons) + "."

def _build_no_result_ai_response(
    symptoms: list[str],
    safety_e_tags: list[str],
    final_e_ings: list[str],
    candidate_count: int,
    context_before_count: int,
    context_after_count: int,
    scored_count: int,
) -> str:
    """
    Tạo phản hồi tự nhiên (tiếng Việt) giải thích tại sao không gợi ý được món nào.
    Dùng thay thế cho post_processing_agent khi kết quả rỗng, tránh LLM hallucinate.
    """
    parts: list[str] = []

    # Ngữ cảnh sức khỏe
    if symptoms:
        cond_text = ", ".join(symptoms)
        parts.append(
            f"Mình đã ghi nhận tình trạng sức khỏe của bạn ({cond_text}) "
            "và áp dụng đầy đủ bộ lọc an toàn tương ứng."
        )

    # Giải thích theo giai đoạn bị rỗng
    if candidate_count == 0:
        parts.append(
            "Rất tiếc, sau khi loại trừ các nguyên liệu không phù hợp, "
            "không còn món nào trong cơ sở dữ liệu vượt qua bộ lọc thành phần."
        )
    elif context_after_count == 0 and context_before_count > 0:
        parts.append(
            f"Sau bộ lọc nguyên liệu, còn {context_before_count} món an toàn, "
            "nhưng không có món nào phù hợp với bữa ăn hoặc ngữ cảnh bạn yêu cầu. "
            "Bạn có thể thử bỏ yêu cầu về bữa ăn cụ thể để mở rộng kết quả."
        )
    elif scored_count == 0 and context_after_count > 0:
        parts.append(
            f"Còn {context_after_count} món an toàn nhưng hiện chưa có dữ liệu "
            "phân tích ngữ nghĩa, không thể xếp hạng và gợi ý chính xác lúc này. "
            "Vui lòng thử lại sau hoặc liên hệ hỗ trợ."
        )
    else:
        parts.append(
            "Rất tiếc, sau khi áp dụng tất cả bộ lọc sức khỏe và ngữ cảnh, "
            "hệ thống không tìm được món ăn phù hợp với yêu cầu hiện tại của bạn."
        )

    # Chi tiết bộ lọc
    if safety_e_tags:
        tags_text = ", ".join(safety_e_tags[:6])
        parts.append(
            f"Các tính chất sau đã bị loại để đảm bảo an toàn: {tags_text}."
        )
    if final_e_ings:
        ings_text = ", ".join(final_e_ings[:5])
        parts.append(f"Nguyên liệu cần tránh đã được lọc: {ings_text}.")

    # Hướng dẫn tiếp theo
    parts.append(
        "Bạn có thể thử lại với yêu cầu đơn giản hơn (ví dụ: bỏ bớt điều kiện về "
        "bữa ăn, loại nguyên liệu, hoặc địa điểm), hoặc cho mình biết thêm sở thích "
        "để tìm kiếm tốt hơn. Mọi gợi ý không thay thế tư vấn của bác sĩ hoặc "
        "chuyên gia dinh dưỡng."
    )

    return " ".join(parts)
