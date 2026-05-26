"""Retrieval trace helpers cho search pipeline.

Module này tạo trace item cho các bước filter, rerank và returned để lưu vào
query log hoặc in debug. File này chỉ đóng gói dữ liệu quan sát, không quyết
định business logic.
"""

from __future__ import annotations

from app.modules.foods.models import Food
from app.modules.search.common import MEDICAL_CAUTION_INGREDIENT_KEY_RULES, TRACE_LIMIT
from app.modules.search.schemas import FoodResult


def init_retrieval_trace() -> dict:
    """Khởi tạo cấu trúc trace để ghi lại các bước lọc, rerank và kết quả trả về."""
    return {
        "hard_filtered_out": [],
        "allergy_text_filtered_out": [],
        "context_filtered_out": [],
        "dish_name_filtered_out": [],
        "ingredient_include_filtered_out": [],
        "embedding_skipped": [],
        "score_breakdown": [],
        "returned": [],
    }

def append_trace_item(
    trace: dict,
    bucket: str,
    item: dict,
    limit: int = TRACE_LIMIT,
) -> None:
    """Thêm một sự kiện vào trace bucket với giới hạn số lượng để tránh log quá dài."""
    entries = trace.get(bucket)
    if entries is None:
        entries = []
        trace[bucket] = entries
    if len(entries) >= limit:
        return
    entries.append(item)

def food_trace_snapshot(food: Food) -> dict:
    """Tạo snapshot tối giản của món ăn để ghi vào retrieval trace."""
    return {
        "id": str(food.id),
        "name": food.name,
    }

def matched_keys(food_keys: list[str], target_keys: list[str]) -> list[str]:
    """Lấy ra các ingredient key của món ăn đang giao với tập key mục tiêu."""
    target_set = set(target_keys or [])
    return sorted(key for key in (food_keys or []) if key in target_set)

def collect_medical_caution_ingredient_key_matches(
    food: Food,
    symptoms: list[str],
) -> list[dict]:
    """Tìm ingredient-key cần cảnh báo/penalty mềm theo bệnh lý, không loại cứng."""
    food_keys = set(food.core_ingredient_keys or [])
    matches = []
    seen_keys = set()
    for symptom in symptoms or []:
        for key, label in MEDICAL_CAUTION_INGREDIENT_KEY_RULES.get(symptom, {}).items():
            if key not in food_keys or key in seen_keys:
                continue
            seen_keys.add(key)
            matches.append({
                "symptom": symptom,
                "key": key,
                "label": label,
            })
    return matches

def log_retrieval_trace_for_debug(trace: dict, *, enabled: bool) -> None:
    """Print retrieval trace to backend logs without exposing exclusions in API response."""
    if not enabled or not trace:
        return

    excluded_buckets = [
        "hard_filtered_out",
        "allergy_text_filtered_out",
        "context_filtered_out",
        "dish_name_filtered_out",
        "ingredient_include_filtered_out",
        "embedding_skipped",
    ]
    print("\n" + "=" * 70)
    print("[RETRIEVAL TRACE] Debug trace chỉ in ở BE, không trả trong API response")
    for bucket in excluded_buckets:
        items = trace.get(bucket) or []
        print(f"- {bucket}: {len(items)} item(s)")
        for index, item in enumerate(items, start=1):
            reason = item.get("reason") or item.get("stage") or "unknown"
            name = item.get("name") or item.get("id") or "<unknown>"
            print(f"  [{index}] {name} | reason={reason}")
            if item.get("matched_keys"):
                print(f"      matched_keys={item['matched_keys']}")
            if item.get("matched_contexts"):
                print(f"      matched_contexts={item['matched_contexts']}")
            if item.get("matches"):
                print(f"      matches={item['matches']}")

    score_items = trace.get("score_breakdown") or []
    returned_items = trace.get("returned") or []
    print(f"- score_breakdown: {len(score_items)} item(s)")
    for item in score_items[:10]:
        print(
            "  "
            f"{item.get('name', '<unknown>')} | "
            f"mode={item.get('retrieval_mode')} | "
            f"base={item.get('base_similarity')} | "
            f"meal_role={item.get('meal_role_adjustment')} | "
            f"final={item.get('final_score')}"
        )
    print(f"- returned: {len(returned_items)} item(s)")
    for item in returned_items:
        print(
            "  "
            f"rank={item.get('rank')} | "
            f"{item.get('name', '<unknown>')} | "
            f"score={item.get('score')}"
        )
    print("=" * 70 + "\n")

def build_score_trace_item(
    food: Food,
    final_score: float,
    score_details: dict,
    ingredient_priority_match: bool,
) -> dict:
    """Đóng gói breakdown tính điểm của một món để phục vụ debug retrieval trace."""
    item = {
        **food_trace_snapshot(food),
        "retrieval_mode": score_details.get("retrieval_mode"),
        "base_similarity": score_details.get("base_similarity"),
        "tag_bonus": score_details.get("tag_bonus"),
        "tag_penalty": score_details.get("tag_penalty"),
        "meal_role_adjustment": score_details.get("meal_role_adjustment"),
        "final_score": final_score,
        "serving_role": score_details.get("serving_role"),
        "ingredient_priority_match": ingredient_priority_match,
        "matched_prefer_tags": score_details.get("matched_prefer_tags", []),
        "matched_avoid_tags": score_details.get("matched_avoid_tags", []),
        "medical_caution_penalty": score_details.get("medical_caution_penalty", 0),
        "medical_caution_matches": score_details.get("medical_caution_matches", []),
        "explicit_preference_conflicts": score_details.get("explicit_preference_conflicts", []),
    }
    if score_details.get("lexical_signal_breakdown"):
        item["lexical_signal_breakdown"] = score_details["lexical_signal_breakdown"]
    return item

def build_returned_trace_item(
    rank: int,
    result: FoodResult,
) -> dict:
    """Tạo trace item cho một món đã lọt vào danh sách kết quả trả về cuối cùng."""
    return {
        "rank": rank,
        "id": str(result.id),
        "name": result.name,
        "score": result.matchScore,
        "reason": result.reason,
    }

def _new_llm_runtime_state() -> dict:
    """Khởi tạo trạng thái runtime để theo dõi latency, fallback và lỗi của từng stage LLM."""
    return {
        "supervisor_status": "ok",
        "embedding_status": "ok",
        "post_processing_status": "ok",
        "retrieval_mode": "semantic",
        "fallbacks_used": [],
        "stage_latency_ms": {},
        "user_visible_warning_applied": False,
        "user_visible_retrieval_note_applied": False,
    }
