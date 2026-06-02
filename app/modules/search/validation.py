"""Final validation agent — LLM-based second-pass review của food results.

Nhận danh sách FoodResult đã xếp hạng cùng với health constraints, rồi:
1. Đánh giá từng món: PASS / WARN / REJECT
   - PASS:   Không vi phạm bất kỳ ràng buộc sức khỏe nào.
   - WARN:   Có thể ăn nhưng cần điều chỉnh (ăn nguội, bỏ gia vị, giảm phần nước).
   - REJECT: Vi phạm cứng — tag cấm, cooking method gây hại trực tiếp, hoặc
             nguyên liệu/mô tả rõ ràng chống chỉ định với bệnh lý.
2. Viết reason ngắn, tự nhiên cho từng món để hiển thị trên card món ăn.

Chỉ kích hoạt khi user có health conditions (symptoms non-empty).
Fallback về post_processing results nếu timeout hoặc LLM lỗi.
"""

from __future__ import annotations

import asyncio
import json
import time

from google.genai import types

from app.modules.search.common import (
    MEDICAL_ADVICE_ALIAS_MAP,
    POST_PROCESSING_TIMEOUT_SECONDS,
    client,
    get_gemini_text_model,
)
from app.modules.search.schemas import FoodResult
from app.shared.paths import STANDARD_DATA_DIR

# Dùng cùng timeout với post_processing để validation có đủ thời gian kiểm tra.
VALIDATION_TIMEOUT_SECONDS = POST_PROCESSING_TIMEOUT_SECONDS

# Số món tối thiểu cần giữ lại sau validation.
# Nếu số món PASS+WARN < MIN_VALID_RESULTS → revert về danh sách gốc.
MIN_VALID_RESULTS = 1

_VERDICT_PASS = "PASS"
_VERDICT_WARN = "WARN"
_VERDICT_REJECT = "REJECT"

_ADVICE_RULES_PATH = STANDARD_DATA_DIR / "generated-rules" / "medical-advice-rules" / "medical_advice_rules.json"
with _ADVICE_RULES_PATH.open("r", encoding="utf-8") as _f:
    MEDICAL_ADVICE_RULES: dict = json.load(_f)


def _get_medical_advice_rule(symptom: str) -> dict | None:
    """Lấy advice rule theo tên bệnh/alias nếu có."""
    return MEDICAL_ADVICE_RULES.get(symptom) or MEDICAL_ADVICE_RULES.get(
        MEDICAL_ADVICE_ALIAS_MAP.get(symptom, "")
    )


def _collect_food_soft_tag_warning_hints(
    symptoms: list[str],
    food: FoodResult,
) -> list[dict[str, str]]:
    """
    Tìm các cảnh báo y khoa khớp trực tiếp với nhóm tag mềm của món.

    Trong hệ thống này, soft tag được hiểu rộng gồm:
    - food.soft_tags
    - food.taste_profile
    - food.meal_context
    - food.occasion_context
    """
    food_soft_tags = set(
        list(food.soft_tags or [])
        + list(food.taste_profile or [])
        + list(food.meal_context or [])
        + list(food.occasion_context or [])
    )
    warning_hints: list[dict[str, str]] = []

    for symptom in symptoms:
        rule = _get_medical_advice_rule(symptom)
        if not rule:
            continue

        for cond in rule.get("conditional_warnings", []):
            if cond.get("trigger_type") != "soft_tag":
                continue

            trigger_value = cond.get("trigger_value")
            warning_text = cond.get("warning_text")
            if trigger_value in food_soft_tags and warning_text:
                warning_hints.append({
                    "symptom": symptom,
                    "matched_soft_tag": trigger_value,
                    "warning_text": warning_text,
                })

    return warning_hints[:2]


def _reason_with_required_warning(
    reason: str | None,
    warning_hints: list[dict[str, str]],
) -> str | None:
    """
    Đảm bảo reason cuối cùng chứa đúng warning_text từ medical advice rule.

    LLM vẫn được viết phần điểm mạnh/cảnh báo tự nhiên, nhưng warning theo rule
    được gắn deterministic để UI hiển thị nhất quán, không bị paraphrase mất ý.
    """
    clean_reason = (reason or "").strip()
    warning_text = (warning_hints[0].get("warning_text") if warning_hints else None) or ""
    warning_text = warning_text.strip()
    if not warning_text:
        return clean_reason or None

    if warning_text in clean_reason:
        return clean_reason

    if not clean_reason:
        return warning_text

    return f"{clean_reason} {warning_text}"


def _build_validation_prompt(
    symptoms: list[str],
    forbidden_tags: list[str],
    forbidden_ingredients: list[str],
    foods: list[FoodResult],
) -> str:
    """Xây dựng system prompt cho validation agent."""
    symptoms_text = ", ".join(symptoms) if symptoms else "Không có bệnh lý"
    forbidden_tags_text = (
        ", ".join(f'"{t}"' for t in forbidden_tags)
        if forbidden_tags
        else "(không có)"
    )
    forbidden_ings_text = (
        ", ".join(f'"{i}"' for i in forbidden_ingredients[:20])
        if forbidden_ingredients
        else "(không có)"
    )

    foods_summary = []
    for food in foods:
        medical_warning_hints = _collect_food_soft_tag_warning_hints(symptoms, food)
        foods_summary.append({
            "name": food.name,
            "soft_tags": food.soft_tags,
            "taste_profile": food.taste_profile,
            "core_ingredients": food.core_ingredients,
            "description_excerpt": (food.description or "")[:200],
            "current_reason": food.reason,
            "medical_warning_hints": medical_warning_hints,
        })
    foods_text = json.dumps(foods_summary, ensure_ascii=False, indent=2)

    return f"""\
 Bạn là một chuyên gia dinh dưỡng lâm sàng. Nhiệm vụ của bạn là kiểm tra danh sách món ăn và đánh giá từng món theo ràng buộc sức khỏe.

[TÌNH TRẠNG SỨC KHỎE NGƯỜI DÙNG]
{symptoms_text}

[TAG TUYỆT ĐỐI PHẢI TRÁNH]
{forbidden_tags_text}

[NGUYÊN LIỆU CẦN TRÁNH]
{forbidden_ings_text}

[DANH SÁCH MÓN CẦN KIỂM TRA]
{foods_text}

[QUY TẮC ĐÁNH GIÁ VERDICT]
REJECT — khi MỘT TRONG CÁC điều sau đúng:
  1. soft_tags của món chứa tag trong danh sách TAG TUYỆT ĐỐI PHẢI TRÁNH.
  2. Mô tả hoặc nguyên liệu TRỰC TIẾP gây hại (VD: Nhiệt miệng + "chiên vàng", Ho + "sụn giòn/đá lạnh").
  3. Bản chất món không thể điều chỉnh an toàn (VD: Lẩu luôn phải ăn sôi).

WARN — khi:
  - Món có thể ăn NẾU điều chỉnh cụ thể (ăn nguội, dặn quán bỏ tiêu/ớt, giảm nước dùng).

PASS — khi:
  - Không vi phạm, hoàn toàn lành tính với bệnh lý.

[QUY TẮC OUTPUT]
- Chỉ trả JSON decisions.
- Không viết câu trả lời tư vấn tự nhiên, không viết ai_response, không viết validated_response.
- Mỗi decision BẮT BUỘC có reason 20-35 chữ, giọng tự nhiên, súc tích.
- Không nhắc điểm số, matchScore, semantic score hoặc tên tag kỹ thuật.
- Cấu trúc reason: [điểm mạnh chính của món] + [cảnh báo hoặc lưu ý sức khỏe nếu có].
- Nếu không có cảnh báo: chỉ nêu điểm mạnh phù hợp với tình trạng sức khỏe/sở thích.
- Nếu có cảnh báo: nêu bối cảnh thực tế ngắn gọn và hành động cụ thể, VD: "nước dùng nhiều purin — nên chan ít".
- Nếu món có `medical_warning_hints`, reason BẮT BUỘC phải nhắc ít nhất một warning phù hợp trong đó bằng lời tự nhiên.
- Không lặp lại y hệt cùng một cảnh báo cho nhiều món; hãy điều chỉnh cảnh báo theo đặc điểm riêng của từng món.
- Được dùng lại ý từ reason hiện có của món nếu ý đó đúng, cụ thể và không mang tính kỹ thuật.
- Với PASS: reason nêu vì sao món phù hợp với tình trạng sức khỏe, dựa vào nguyên liệu/cách chế biến/dạng món.
- Với WARN: reason nêu lợi điểm chính và cách điều chỉnh cụ thể khi ăn.
- Với REJECT: reason nêu ngắn gọn tác nhân làm món không phù hợp.
- Không bịa món ngoài danh sách.
"""

def _parse_validation_result(
    raw: dict,
    original_foods: list[FoodResult],
    symptoms: list[str],
) -> tuple[list[FoodResult], list[dict]]:
    """
    Parse kết quả JSON từ validation agent.

    Returns:
        (approved_foods, rejected_foods_info)
        approved_foods:     danh sách FoodResult đã loại REJECT
        rejected_foods_info: list[{"name": str, "reason": str}]
    """
    decisions: list[dict] = raw.get("decisions") or []

    verdict_map: dict[str, str] = {}
    reason_map: dict[str, str] = {}

    for d in decisions:
        name = (d.get("name") or "").strip()
        verdict = (d.get("verdict") or _VERDICT_PASS).upper()
        reason = (d.get("reason") or "").strip()
        if name:
            verdict_map[name] = verdict
            if reason:
                reason_map[name] = reason

    approved_foods: list[FoodResult] = []
    rejected_foods_info: list[dict] = []

    for food in original_foods:
        verdict = verdict_map.get(food.name, _VERDICT_PASS)
        warning_hints = _collect_food_soft_tag_warning_hints(symptoms, food)
        reason = _reason_with_required_warning(reason_map.get(food.name), warning_hints)
        if verdict == _VERDICT_REJECT:
            rejected_foods_info.append({
                "name": food.name,
                "reason": reason or "vi phạm ràng buộc sức khỏe",
            })
            print(f"  🚫 [VALIDATION] REJECT: {food.name} — {reason or ''}")
        else:
            approved_foods.append(food.model_copy(update={"reason": reason}) if reason else food)
            if verdict == _VERDICT_WARN:
                print(f"  ⚠️ [VALIDATION] WARN: {food.name}")
            else:
                print(f"  ✅ [VALIDATION] PASS: {food.name}")

    return approved_foods, rejected_foods_info


def final_validation_agent(
    user_query: str,
    symptoms: list[str],
    forbidden_tags: list[str],
    forbidden_ingredients: list[str],
    top_foods: list[FoodResult],
) -> dict:
    """
    Gọi LLM để validate từng món trong top_foods với health constraints.

    Returns dict:
    {
      "decisions": [{"name": str, "verdict": "PASS|WARN|REJECT", "reason": str}]
    }
    """
    system_prompt = _build_validation_prompt(
        symptoms=symptoms,
        forbidden_tags=forbidden_tags,
        forbidden_ingredients=forbidden_ingredients,
        foods=top_foods,
    )

    response_schema = {
        "type": "OBJECT",
        "properties": {
            "decisions": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "name": {"type": "STRING"},
                        "verdict": {
                            "type": "STRING",
                            "enum": [_VERDICT_PASS, _VERDICT_WARN, _VERDICT_REJECT],
                        },
                        "reason": {"type": "STRING"},
                    },
                    "required": ["name", "verdict", "reason"],
                },
            },
        },
        "required": ["decisions"],
    }

    try:
        response = client.models.generate_content(
            model=get_gemini_text_model(),
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.1,
                response_mime_type="application/json",
                response_schema=response_schema,
            ),
            contents=f"Câu hỏi của người dùng: {user_query}",
        )
        return json.loads(response.text)
    except Exception as exc:
        print(f"[VALIDATION] Lỗi LLM: {exc}")
        return {}


async def run_final_validation_with_timeout(
    user_query: str,
    symptoms: list[str],
    forbidden_tags: list[str],
    forbidden_ingredients: list[str],
    top_foods: list[FoodResult],
) -> tuple[list[FoodResult], list[dict], dict]:
    """
    Chạy final_validation_agent với timeout. Fallback giữ nguyên danh sách gốc nếu lỗi.

    Returns:
        (approved_foods, rejected_foods_info, runtime)
        - Nếu approved_foods < MIN_VALID_RESULTS → revert về top_foods gốc, response rỗng.
        - Nếu timeout/lỗi               → trả top_foods gốc, response rỗng.
    """
    started_at = time.perf_counter()
    runtime: dict = {"status": "ok", "latency_ms": 0, "error_message": None}

    def _fallback(reason: str) -> tuple[list[FoodResult], list[dict], dict]:
        runtime["latency_ms"] = round((time.perf_counter() - started_at) * 1000)
        runtime["status"] = "fallback"
        runtime["error_message"] = reason
        print(f"[VALIDATION] Fallback — {reason}")
        return top_foods, [], runtime

    try:
        raw = await asyncio.wait_for(
            asyncio.to_thread(
                final_validation_agent,
                user_query,
                symptoms,
                forbidden_tags,
                forbidden_ingredients,
                top_foods,
            ),
            timeout=VALIDATION_TIMEOUT_SECONDS,
        )
        runtime["latency_ms"] = round((time.perf_counter() - started_at) * 1000)

        if not raw:
            return _fallback("validation returned empty response")

        approved_foods, rejected_foods_info = _parse_validation_result(
            raw,
            top_foods,
            symptoms,
        )

        if len(approved_foods) < MIN_VALID_RESULTS:
            print(
                f"[VALIDATION] Chỉ còn {len(approved_foods)} món sau validation "
                f"(< {MIN_VALID_RESULTS}) — revert về danh sách gốc."
            )
            return _fallback(
                f"only {len(approved_foods)} approved food(s) — below minimum threshold, reverting"
            )

        rejected_count = len(rejected_foods_info)
        approved_count = len(approved_foods)
        print(
            f"✅ [VALIDATION] Hoàn thành: {approved_count} PASS/WARN, "
            f"{rejected_count} REJECT trong {runtime['latency_ms']}ms"
        )
        return approved_foods, rejected_foods_info, runtime

    except asyncio.TimeoutError:
        return _fallback(f"validation timeout after {VALIDATION_TIMEOUT_SECONDS}s")
    except Exception as exc:
        return _fallback(str(exc)[:300])
