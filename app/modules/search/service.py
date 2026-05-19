from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid

import numpy as np
from google import genai
from google.genai import types
from app.models import Food, Tag
from app.schemas import AIInsight, FoodResult, SearchResponse
from sqlalchemy import not_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.ingredients.service import (
    generate_filter_keys,
    has_any_ingredient_key,
    load_enabled_alias_override_rules,
)
from app.modules.search.safety import detect_allergy_text_matches
from app.modules.query_logs.service import create_query_log
from app.shared.paths import STANDARD_DATA_DIR

# =====================================================================
# CẤU HÌNH KHỞI TẠO
# =====================================================================
PROJECT_ID = os.getenv("PROJECT_ID")
client = genai.Client(vertexai=True, project=PROJECT_ID, location="us-central1")
SEARCH_DISCLAIMER = "Hệ thống đã sàng lọc nguyên liệu theo điều kiện sức khỏe cá nhân nhưng không thay thế tư vấn từ bác sĩ/chuyên gia y tế. Vui lòng kiểm tra lại thành phần thực tế trước khi gọi món."
SUPERVISOR_TIMEOUT_SECONDS = 10
EMBEDDING_TIMEOUT_SECONDS = 10
POST_PROCESSING_TIMEOUT_SECONDS = 20
SUPERVISOR_FALLBACK_WARNING = (
    "Hệ thống tạm thời không thể phân tích đầy đủ yêu cầu của bạn. "
    "Nếu bạn có dị ứng hoặc bệnh lý, vui lòng kiểm tra kỹ nguyên liệu từng món trước khi sử dụng."
)
EMBEDDING_FALLBACK_RETRIEVAL_NOTE = (
    "Kết quả đang được gợi ý theo tìm kiếm từ khóa do dịch vụ phân tích tạm thời gián đoạn."
)
FALLBACK_AI_RESPONSE_TEMPLATE = """Chào bạn, hiện hệ thống đang trả gợi ý theo chế độ dự phòng.

Dưới đây là một số món phù hợp để bạn tham khảo: {top_food_names}.

{retrieval_note_sentence}

{health_sentence}

Bạn vui lòng kiểm tra lại thành phần thực tế của từng món trước khi sử dụng."""
FALLBACK_STOPWORDS = {
    "toi", "minh", "muon", "can", "tim", "dang", "cho", "nguoi", "voi",
    "cua", "nay", "hom", "nay", "giup", "goi", "y", "mon", "an",
    "thit", "ca", "rau", "com", "bun",
}
TRACE_LIMIT = 30

# =====================================================================
# 1. AGENT & LUỒNG XỬ LÝ XUNG ĐỘT 
# =====================================================================

# --- Khai báo các danh mục Tag chuẩn ---
valid_health_tags = [
    "Vết thương hở / Mới phẫu thuật", "Đang cho con bú", "Phụ nữ mang thai",
    "Gan nhiễm mỡ / Men gan cao", "Béo phì", "Đầy bụng / Khó tiêu",
    "Nhiệt miệng/Loét miệng", "Tiêu chảy", "Gout",
    "Bệnh lý hô hấp trên (Ho/Viêm họng/Cảm/Amidan)", "Táo bón",
    "Tim mạch", "Trào ngược dạ dày thực quản (GERD)", "Viêm loét dạ dày",
    "Suy thận", "Cao huyết áp", "Tiểu đường",
    "Dị ứng mắm lên men", "Dị ứng bột ngọt (MSG)", "Dị ứng mè / vừng",
    "Dị ứng trái cây có múi", "Dị ứng trứng", "Dị ứng cà chua",
    "Dị ứng lúa mì", "Dị ứng đậu nành", "Bất dung nạp Lactose",
    "Dị ứng sữa bò", "Dị ứng hạt cây", "Dị ứng đậu phộng",
    "Dị ứng cá có vây", "Dị ứng động vật thân mềm", "Dị ứng động vật giáp xác"
]

# Ánh xạ từ khóa đồng nghĩa cho Health Tags và Medical Advice
HEALTH_TAG_ALIAS_MAP = {
    "Vết thương hở/Mới phẫu thuật": "Vết thương hở / Mới phẫu thuật",
    "Gan nhiễm mỡ/Men gan cao": "Gan nhiễm mỡ / Men gan cao",
    "Đầy bụng/Khó tiêu": "Đầy bụng / Khó tiêu",
    "Dị ứng mè/vừng": "Dị ứng mè / vừng",
}

MEDICAL_ADVICE_ALIAS_MAP = {
    "Gout": "Bệnh Gout",
    "Gan nhiễm mỡ / Men gan cao": "Gan nhiễm mỡ",
}

valid_soft_tags = [
    "Đậm đà", "Thanh đạm", "Chua", "Cay", "Mặn", "Ngọt", "Đắng", "Béo ngậy",
    "Nóng hổi", "Thanh mát/Giải nhiệt", "Món nước", "Món khô", "Nước sền sệt", "Món lạnh", "Sống/Chín tái",
    "Giòn / Giòn rụm", "Dai / Sần sật", "Mềm", 
    "Chiên / Rán", "Nướng", "Hấp / Luộc", "Xào", "Gỏi / Nộm / Trộn", "Cuốn / Gói", "Hầm / Ninh", "Lẩu", "Kho/Rim", "Súp", "Cháo", "Rang",
    "Ăn no", "Ăn vặt", "Mồi nhậu", "Ăn sáng", "Ăn trưa", "Ăn chiều / xế", "Ăn tối", "Ăn khuya", "Tráng miệng", "Giải rượu", "Giải cảm", "Ấm bụng",
    "Đặc sản Đà Nẵng", "Ẩm thực đường phố", "Món Việt truyền thống", "Món Á", "Món Âu", "Thức ăn nhanh", "Món chay",
    "Giàu chất xơ", "Giàu đạm", "Giàu vitamin", "Giàu tinh bột", "Nội tạng", "Từ sữa / Phô mai", "Thực phẩm chế biến sẵn", "Bánh ngọt",
    "Dễ tiêu", "Khó tiêu / Nặng bụng", "Healthy / Eat Clean", "Nhiều dầu mỡ / Calo cao", "Hải sản"
]

# Phân loại các Soft Tags thành từng nhóm ngữ cảnh cụ thể
TASTE_PROFILE_TAGS = {"Đậm đà", "Thanh đạm", "Chua", "Cay", "Mặn", "Ngọt", "Đắng", "Béo ngậy"}
MEAL_CONTEXT_TAGS = {"Ăn sáng", "Ăn trưa", "Ăn tối", "Ăn chiều / xế", "Ăn khuya"}
OCCASION_CONTEXT_TAGS = {"Ăn no", "Ăn vặt", "Mồi nhậu", "Tráng miệng", "Giải rượu", "Giải cảm", "Ấm bụng"}
DISH_TYPE_TAGS = {"Lẩu", "Nướng", "Cháo", "Súp", "Gỏi / Nộm / Trộn", "Cuốn / Gói", "Kho/Rim", "Chiên / Rán", "Hấp / Luộc", "Xào", "Rang"}

# --- Trọng số & Cấu hình cho thuật toán tính điểm (Scoring) ---
USER_SOFT_TAG_BONUS = 0.018
USER_TASTE_BONUS = 0.018
USER_MEAL_CONTEXT_BONUS = 0.035
USER_OCCASION_CONTEXT_BONUS = 0.035
MEDICAL_PREFER_TAG_BONUS = 0.014

USER_AVOID_TAG_PENALTY = 0.035
MEDICAL_AVOID_TAG_PENALTY = 0.045

MAX_MEDICAL_TAG_BONUS = 0.06
MAX_USER_CONTEXT_BONUS = 0.07
MAX_USER_SOFT_TASTE_BONUS = 0.03
MAX_TAG_BONUS = 0.12
MAX_TAG_PENALTY = 0.16

MIN_CONTEXT_FILTER_CANDIDATES = 5
PRIMARY_MEAL_ROLES = {"one_dish_meal", "main_dish"}
MEAL_ROLE_ADJUSTMENTS = {
    "one_dish_meal": 0.08,
    "main_dish": 0.05,
    "side_soup": -0.08,
    "side_vegetable": -0.08,
    "snack_dessert": -0.16,
    "unknown": -0.02,
}
PREFERENCE_CONFLICT_PAIRS = [
    ("Món khô", "Món nước"),
    ("Món khô", "Nước sền sệt"),
    ("Món nước", "Món khô"),
    ("Món lạnh", "Nóng hổi"),
    ("Nóng hổi", "Món lạnh"),
    ("Thanh đạm", "Đậm đà"),
    ("Đậm đà", "Thanh đạm"),
    ("Mềm", "Giòn / Giòn rụm"),
    ("Giòn / Giòn rụm", "Mềm"),
    ("Hấp / Luộc", "Chiên / Rán"),
    ("Chiên / Rán", "Hấp / Luộc"),
    ("Ăn vặt", "Ăn no"),
    ("Tráng miệng", "Ăn no"),
]

TAG_ALIAS_MAP = {
    "hap/luoc": "Hấp / Luộc",
    "hap / luoc": "Hấp / Luộc",
    "song / chin tai": "Sống/Chín tái",
    "cuon/goi": "Cuốn / Gói",
    "thanh dam": "Thanh đạm",
    "thanh mat / giai nhiet": "Thanh mát/Giải nhiệt",
    "thanh mat/giai nhiet": "Thanh mát/Giải nhiệt",
    "do an nhanh": "Thức ăn nhanh",
    "an dem": "Ăn khuya",
    "it beo": "Thanh đạm",
    "giau chat so": "Giàu chất xơ",
    "sua / pho mai": "Từ sữa / Phô mai",
}


# =====================================================================
# CÁC HÀM TIỆN ÍCH CHUẨN HOÁ DỮ LIỆU TÍNH CHẤT (SOFT TAGS)
# =====================================================================

def _normalize_tag_key(tag: str) -> str:
    """Loại bỏ khoảng trắng, chữ hoa, và chuyển 'đ' thành 'd' để làm key đối chiếu."""
    return (tag or "").strip().lower().replace("đ", "d").replace(" ", "")

def _strip_accents(text: str) -> str:
    """Loại bỏ dấu tiếng Việt ra khỏi chuỗi."""
    accents = {
        "àáạảãâầấậẩẫăằắặẳẵ": "a",
        "èéẹẻẽêềếệểễ": "e",
        "ìíịỉĩ": "i",
        "òóọỏõôồốộổỗơờớợởỡ": "o",
        "ùúụủũưừứựửữ": "u",
        "ỳýỵỷỹ": "y",
        "đ": "d",
    }
    result = text or ""
    for source, target in accents.items():
        for ch in source:
            result = result.replace(ch, target).replace(ch.upper(), target.upper())
    return result

def _normalize_ingredient_match_text(value: str) -> str:
    """Làm sạch văn bản nguyên liệu (bỏ dấu, chuyển chữ thường, giữ lại ký tự cơ bản)."""
    text_value = _strip_accents(value or "").lower()
    text_value = re.sub(r"[^a-z0-9/\s-]", " ", text_value)
    return re.sub(r"\s+", " ", text_value).strip()

def _normalize_search_text(value: str) -> str:
    """Chuẩn hóa text tự do để match keyword theo từ/cụm từ."""
    text_value = _strip_accents(value or "").lower()
    text_value = re.sub(r"[^a-z0-9\s/-]", " ", text_value)
    return re.sub(r"\s+", " ", text_value).strip()

def _phrase_in_text(text_value: str, phrase: str) -> bool:
    normalized_phrase = _normalize_search_text(phrase)
    if not normalized_phrase:
        return False
    pattern = rf"(?<![a-z0-9]){re.escape(normalized_phrase)}(?![a-z0-9])"
    return re.search(pattern, text_value) is not None

def _has_any_phrase(text_value: str, phrases: list[str]) -> bool:
    return any(_phrase_in_text(text_value, phrase) for phrase in phrases)

def _ingredient_phrase_matches(text_value: str, phrase: str) -> bool:
    """Kiểm tra xem một cụm từ (phrase) có tồn tại độc lập trong chuỗi văn bản (text_value) không."""
    normalized_phrase = _normalize_ingredient_match_text(phrase)
    if not normalized_phrase:
        return False
    # Sử dụng Regex để tìm cụm từ chính xác, không bị dính chữ (Word boundary)
    pattern = rf"(?<![a-z0-9]){re.escape(normalized_phrase)}(?![a-z0-9])"
    return re.search(pattern, text_value) is not None

def _food_has_excluded_ingredient(food: Food, excluded_ingredients: list[str]) -> bool:
    """Kiểm tra xem món ăn có chứa nguyên liệu nằm trong danh sách cần loại trừ hay không."""
    ingredient_text = " ".join(food.core_ingredients or [])
    normalized_text = _normalize_ingredient_match_text(ingredient_text)
    return any(_ingredient_phrase_matches(normalized_text, ing) for ing in excluded_ingredients)

def _food_has_any_ingredient_key(food: Food, target_keys: list[str]) -> bool:
    """Kiểm tra món ăn có giao với các ingredient key cần lọc hay không."""
    return has_any_ingredient_key(food.core_ingredient_keys or [], target_keys)

def init_retrieval_trace() -> dict:
    return {
        "hard_filtered_out": [],
        "allergy_text_filtered_out": [],
        "context_filtered_out": [],
        "dish_name_filtered_out": [],
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
    entries = trace.get(bucket)
    if entries is None:
        entries = []
        trace[bucket] = entries
    if len(entries) >= limit:
        return
    entries.append(item)

def food_trace_snapshot(food: Food) -> dict:
    return {
        "id": str(food.id),
        "name": food.name,
    }

def matched_keys(food_keys: list[str], target_keys: list[str]) -> list[str]:
    target_set = set(target_keys or [])
    return sorted(key for key in (food_keys or []) if key in target_set)

def log_retrieval_trace_for_debug(trace: dict, *, enabled: bool) -> None:
    """Print retrieval trace to backend logs without exposing exclusions in API response."""
    if not enabled or not trace:
        return

    excluded_buckets = [
        "hard_filtered_out",
        "allergy_text_filtered_out",
        "context_filtered_out",
        "dish_name_filtered_out",
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
        "explicit_preference_conflicts": score_details.get("explicit_preference_conflicts", []),
    }
    if score_details.get("lexical_signal_breakdown"):
        item["lexical_signal_breakdown"] = score_details["lexical_signal_breakdown"]
    return item

def build_returned_trace_item(
    rank: int,
    result: FoodResult,
) -> dict:
    return {
        "rank": rank,
        "id": str(result.id),
        "name": result.name,
        "score": result.matchScore,
        "reason": result.reason,
    }

def infer_serving_role(food: Food) -> str:
    """
    Suy luận vai trò món trong bữa ăn bằng rule runtime.

    Đây là nhãn dẫn xuất để rerank bữa trưa/tối, không phải dữ liệu cố định
    trong DB. Thứ tự rule có chủ ý: salad cần thắng "Ăn vặt", còn các món
    bún/phở/cơm/trộn đủ no cần thắng tag "Gỏi / Nộm / Trộn".
    """
    name_text = _normalize_search_text(food.name)
    soft_tags = set(food.soft_tags or [])
    occasion_context = set(food.occasion_context or [])

    one_dish_keywords = [
        "mì quảng", "mỳ quảng", "bún", "phở", "miến", "hủ tiếu", "mì", "mỳ",
        "pasta", "spaghetti", "bánh canh", "bánh đa cua", "cao lầu", "cơm",
        "xôi", "cháo", "bánh mì", "sandwich", "pizza", "taco", "kebab",
        "burger", "sushi", "ramen", "udon", "bánh cuốn", "bánh xèo",
        "bánh giò", "bánh chưng", "bánh gói", "bánh ướt", "bánh hỏi",
        "bún đậu", "bún chả", "hoành thánh nước", "lẩu", "poke bowl",
    ]
    dessert_keywords = [
        "chè", "kem", "mousse", "brownie", "lava", "tart", "waffle",
        "crepe sầu riêng", "rau câu", "sữa chua", "bánh flan", "flan",
        "pudding", "trà sữa", "milo dầm", "bingsu", "panna cotta",
        "tiramisu", "cheesecake",
    ]
    snack_keywords = [
        "bánh tráng", "bánh bột lọc", "bánh bèo", "bánh nậm", "bánh ram",
        "ram cuốn", "nem chua", "chả giò", "khoai tây chiên",
        "hoành thánh chiên", "bò bía",
    ]
    side_soup_keywords = ["canh", "súp", "soup"]
    side_vegetable_keywords = [
        "salad", "rau", "đậu bắp", "bông cải", "dưa leo", "gỏi rong biển",
    ]
    main_dish_keywords = [
        "kho", "rim", "nướng", "hấp", "chiên", "xào", "rang", "sốt", "hầm",
        "áp chảo", "bò lúc lắc", "thịt", "cá", "gà", "vịt", "tôm", "mực",
        "ếch", "đậu hũ", "đậu phụ", "trứng", "sườn", "bò", "heo",
    ]

    is_one_dish = _has_any_phrase(name_text, one_dish_keywords)
    if (
        not is_one_dish
        and (
            _has_any_phrase(name_text, dessert_keywords)
            or "Tráng miệng" in occasion_context
            or "Bánh ngọt" in soft_tags
        )
    ):
        return "snack_dessert"

    if _phrase_in_text(name_text, "salad"):
        return "side_vegetable"

    if (
        not is_one_dish
        and (
            "Ăn vặt" in occasion_context
            or _has_any_phrase(name_text, snack_keywords)
        )
    ):
        return "snack_dessert"

    if is_one_dish or ("Ăn no" in occasion_context and "Giàu tinh bột" in soft_tags):
        return "one_dish_meal"

    if _has_any_phrase(name_text, side_soup_keywords) or "Súp" in soft_tags:
        return "side_soup"

    if (
        _has_any_phrase(name_text, side_vegetable_keywords)
        or ("Gỏi / Nộm / Trộn" in soft_tags and "Ăn no" not in occasion_context)
    ):
        return "side_vegetable"

    if "Ăn no" in occasion_context or _has_any_phrase(name_text, main_dish_keywords):
        return "main_dish"

    return "unknown"

def is_main_meal_request(query: str, user_include_tags: list[str]) -> bool:
    """Xác định query có đang hỏi bữa trưa/tối/bữa chính không."""
    query_text = _normalize_search_text(query)
    explicit_main_phrases = [
        "ăn trưa", "bữa trưa", "cơm trưa", "trưa nay ăn",
        "ăn tối", "bữa tối", "cơm tối", "tối nay ăn", "bữa chính",
    ]
    snack_phrases = [
        "ăn vặt", "tráng miệng", "ăn xế", "ăn chiều", "buổi xế",
        "xế chiều", "món nhẹ",
    ]

    explicit_main = _has_any_phrase(query_text, explicit_main_phrases)
    explicit_snack = _has_any_phrase(query_text, snack_phrases)
    canonical_tags = set(canonicalize_soft_tags(user_include_tags))
    tag_main = bool({"Ăn trưa", "Ăn tối"}.intersection(canonical_tags))
    tag_snack = bool({"Ăn vặt", "Tráng miệng", "Ăn chiều / xế"}.intersection(canonical_tags))

    if (explicit_snack or tag_snack) and not explicit_main:
        return False
    return explicit_main or tag_main

def has_explicit_side_or_snack_request(
    query: str,
    user_include_dishes: list[str],
    user_include_tags: list[str],
) -> bool:
    """True khi user gọi đích danh món phụ/snack, để không phạt sai intent."""
    combined_text = _normalize_search_text(
        " ".join([query] + (user_include_dishes or []))
    )
    explicit_phrases = [
        "salad", "canh", "súp", "soup", "rau", "gỏi", "chè", "kem", "bánh",
        "ăn vặt", "tráng miệng",
    ]
    canonical_tags = set(canonicalize_soft_tags(user_include_tags))
    explicit_tags = {
        "Ăn vặt", "Tráng miệng", "Gỏi / Nộm / Trộn", "Súp",
    }
    return _has_any_phrase(combined_text, explicit_phrases) or bool(
        explicit_tags.intersection(canonical_tags)
    )

def get_meal_role_adjustment(
    serving_role: str,
    main_meal_request: bool,
    explicit_side_or_snack_request: bool,
) -> float:
    """Tính điểm cộng/trừ vai trò món ăn cho truy vấn bữa chính."""
    if not main_meal_request:
        return 0.0

    adjustment = MEAL_ROLE_ADJUSTMENTS.get(serving_role, MEAL_ROLE_ADJUSTMENTS["unknown"])
    if explicit_side_or_snack_request and adjustment < 0:
        return 0.0
    return adjustment

def build_explicit_preference_conflict_notes(
    user_include_tags: list[str],
    medical_prefer_tags: list[str],
    top5: list[tuple],
    scored: list[tuple],
) -> tuple[list[str], dict, list[dict]]:
    """
    Minh bạch khi top results không khớp hoàn toàn sở thích rõ ràng của user.

    Đây không phải hard filter, nên hệ thống không loại ngay món trái sở thích;
    thay vào đó ghi note và gắn conflict vào từng món để response giải thích.
    """
    canonical_user_include = set(canonicalize_soft_tags(user_include_tags))
    if not canonical_user_include:
        return [], {}, []

    medical_prefer_set = set(canonicalize_soft_tags(medical_prefer_tags))
    notes: list[str] = []
    conflict_by_food_id: dict = {}
    summaries: list[dict] = []

    for requested_tag, returned_tag in PREFERENCE_CONFLICT_PAIRS:
        if requested_tag not in canonical_user_include:
            continue

        conflicting_top_foods = [
            food for food, *_ in top5
            if returned_tag in set(get_food_scoring_tags(food))
        ]
        if not conflicting_top_foods:
            continue

        requested_candidate_count = sum(
            1 for food, *_ in scored
            if requested_tag in set(get_food_scoring_tags(food))
        )
        requested_top_count = sum(
            1 for food, *_ in top5
            if requested_tag in set(get_food_scoring_tags(food))
        )
        conflict_names = ", ".join(food.name for food in conflicting_top_foods[:3])
        medical_signal_text = (
            f" Rule sức khỏe hiện tại cũng ưu tiên {returned_tag}."
            if returned_tag in medical_prefer_set
            else ""
        )

        if requested_candidate_count == 0:
            note = (
                f"Không tìm thấy món có tag {requested_tag} đủ điều kiện sau khi lọc sức khỏe "
                f"và ngữ cảnh, nên hệ thống đề xuất thêm món có tag {returned_tag} "
                f"({conflict_names}) như lựa chọn thay thế."
                f"{medical_signal_text}"
            )
        else:
            note = (
                f"Hệ thống đã nhận yêu cầu {requested_tag} và có {requested_candidate_count} "
                f"ứng viên phù hợp ({requested_top_count} món vào top 5), nhưng vẫn giữ một số "
                f"món có tag {returned_tag} ({conflict_names}) vì sau khi lọc sức khỏe/ngữ cảnh "
                "chúng có điểm phù hợp cao hơn."
                f"{medical_signal_text}"
            )

        notes.append(note)
        summaries.append({
            "requested_tag": requested_tag,
            "returned_conflict_tag": returned_tag,
            "requested_candidate_count": requested_candidate_count,
            "requested_top_count": requested_top_count,
            "conflicting_foods": [food.name for food in conflicting_top_foods],
            "medical_prefer_conflict_tag": returned_tag in medical_prefer_set,
            "note": note,
        })
        for food in conflicting_top_foods:
            conflict_by_food_id.setdefault(food.id, []).append({
                "requested_tag": requested_tag,
                "returned_conflict_tag": returned_tag,
                "note": note,
            })

    return notes, conflict_by_food_id, summaries

def collect_ingredient_priority_food_ids(
    foods: list[Food],
    include_keys: list[str],
    main_meal_request: bool = False,
    require_primary_role: bool = False,
) -> set:
    """
    Đánh dấu món khớp nguyên liệu user muốn.

    Nguyên liệu include không nên làm rớt sạch candidate an toàn. Thay vào đó,
    món khớp nguyên liệu sẽ được xếp trong nhóm ưu tiên khi lấy top kết quả.
    """
    if not include_keys:
        return set()

    matched_foods = []
    for food in foods:
        if not _food_has_any_ingredient_key(food, include_keys):
            continue
        if require_primary_role and infer_serving_role(food) not in PRIMARY_MEAL_ROLES:
            continue
        matched_foods.append(food)

    primary_note = " trong vai trò món chính" if require_primary_role else ""
    print(
        f"🧭 [INGREDIENT PRIORITY] Có {len(matched_foods)}/{len(foods)} món "
        f"khớp ingredient keys user muốn{primary_note}: {include_keys}"
    )
    return {food.id for food in matched_foods}

def canonicalize_soft_tag(tag: str) -> str | None:
    """
    Chuẩn hóa toàn bộ biến thể soft_tag về danh mục chuẩn.
    Mục tiêu: đảm bảo lưới guardrails không bị hụt do khác dấu cách/ký tự.
    """
    raw = (tag or "").strip()
    if not raw:
        return None

    compact = raw.lower().replace("đ", "d")
    compact = re.sub(r"\s+", " ", compact).strip()
    canonical = TAG_ALIAS_MAP.get(compact, raw)

    normalized_lookup = {_normalize_tag_key(t): t for t in valid_soft_tags}
    return normalized_lookup.get(_normalize_tag_key(canonical))

def canonicalize_soft_tags(tags: list[str]) -> list[str]:
    """Chuẩn hoá một danh sách các soft tags và loại bỏ các tag trùng lặp."""
    seen = set()
    result = []
    for tag in tags or []:
        canonical = canonicalize_soft_tag(tag)
        if canonical and canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    return result

def split_food_category_tags(tags: list[str]) -> dict[str, list[str]]:
    """
    Tách danh sách tag đã trích xuất theo cùng cấu trúc dùng để embedding món ăn.
    Hiện supervisor/rules vẫn trả một mảng tag chung, nên query embedding cần
    phân nhóm lại để khớp với text_to_embed trong seed_service.py.
    """
    grouped = {
        "soft_tags": [],
        "taste_profile": [],
        "meal_context": [],
        "occasion_context": [],
    }

    for tag in canonicalize_soft_tags(tags):
        if tag in TASTE_PROFILE_TAGS:
            grouped["taste_profile"].append(tag)
        elif tag in MEAL_CONTEXT_TAGS:
            grouped["meal_context"].append(tag)
        elif tag in OCCASION_CONTEXT_TAGS:
            grouped["occasion_context"].append(tag)
        else:
            grouped["soft_tags"].append(tag)

    return grouped

def get_food_scoring_tags(food: Food) -> list[str]:
    """
    Gom toàn bộ tag dùng cho rerank. Sau khi dữ liệu đã tách category,
    không được chỉ nhìn food.soft_tags nữa vì vị/ngữ cảnh đã nằm ở field riêng.
    """
    return canonicalize_soft_tags(
        (food.soft_tags or []) +
        (food.taste_profile or []) +
        (food.meal_context or []) +
        (food.occasion_context or [])
    )

def matched_canonical_tags(food_tags: list[str], target_tags: list[str]) -> list[str]:
    """Lọc ra các tag mà món ăn sở hữu trùng khớp với danh sách target_tags đưa vào."""
    food_keys = {_normalize_tag_key(tag) for tag in canonicalize_soft_tags(food_tags)}
    matched = []
    for tag in canonicalize_soft_tags(target_tags):
        if _normalize_tag_key(tag) in food_keys and tag not in matched:
            matched.append(tag)
    return matched

def has_matching_context(food_contexts: list[str], target_contexts: list[str]) -> bool:
    """Kiểm tra xem món ăn có chứa bất kì context nào trong target_contexts không."""
    food_keys = {_normalize_tag_key(tag) for tag in canonicalize_soft_tags(food_contexts)}
    target_keys = {_normalize_tag_key(tag) for tag in canonicalize_soft_tags(target_contexts)}
    return bool(food_keys.intersection(target_keys))

def apply_adaptive_context_include_filter(
    foods: list[Food],
    target_contexts: list[str],
    field_name: str,
    label: str,
) -> list[Food]:
    """
    Bộ lọc giữ lại các món ăn (Include):
    Chỉ áp dụng nếu số lượng candidate sau khi lọc vẫn >= MIN_CONTEXT_FILTER_CANDIDATES.
    """
    contexts = canonicalize_soft_tags(target_contexts)
    if not contexts:
        return foods

    matched_foods = [
        food for food in foods
        if has_matching_context(getattr(food, field_name) or [], contexts)
    ]
    if len(matched_foods) >= MIN_CONTEXT_FILTER_CANDIDATES:
        print(
            f"🧭 [CONTEXT FILTER] Giữ {len(matched_foods)}/{len(foods)} món "
            f"có {label}: {contexts}"
        )
        return matched_foods

    print(
        f"🧭 [CONTEXT FILTER] Bỏ qua lọc {label}: {contexts} "
        f"vì chỉ còn {len(matched_foods)} món (< {MIN_CONTEXT_FILTER_CANDIDATES})."
    )
    return foods

def apply_adaptive_context_exclude_filter(
    foods: list[Food],
    target_contexts: list[str],
    field_name: str,
    label: str,
) -> list[Food]:
    """
    Bộ lọc loại bỏ các món ăn (Exclude):
    Chỉ áp dụng nếu số lượng candidate sau khi lọc vẫn >= MIN_CONTEXT_FILTER_CANDIDATES.
    """
    contexts = canonicalize_soft_tags(target_contexts)
    if not contexts:
        return foods

    kept_foods = [
        food for food in foods
        if not has_matching_context(getattr(food, field_name) or [], contexts)
    ]
    if len(kept_foods) >= MIN_CONTEXT_FILTER_CANDIDATES:
        print(
            f"🧭 [CONTEXT FILTER] Loại {len(foods) - len(kept_foods)} món "
            f"có {label} không muốn: {contexts}"
        )
        return kept_foods

    print(
        f"🧭 [CONTEXT FILTER] Bỏ qua loại {label}: {contexts} "
        f"vì chỉ còn {len(kept_foods)} món (< {MIN_CONTEXT_FILTER_CANDIDATES})."
    )
    return foods

def apply_adaptive_context_include_filter_with_trace(
    foods: list[Food],
    target_contexts: list[str],
    field_name: str,
    label: str,
    trace: dict,
) -> list[Food]:
    contexts = canonicalize_soft_tags(target_contexts)
    if not contexts:
        return foods

    matched_foods = [
        food for food in foods
        if has_matching_context(getattr(food, field_name) or [], contexts)
    ]
    if len(matched_foods) >= MIN_CONTEXT_FILTER_CANDIDATES:
        matched_ids = {food.id for food in matched_foods}
        for food in foods:
            if food.id in matched_ids:
                continue
            append_trace_item(trace, "context_filtered_out", {
                **food_trace_snapshot(food),
                "stage": "context_filter",
                "reason": f"missing_required_{label}",
                "required_contexts": contexts,
                "food_contexts": getattr(food, field_name) or [],
            })
        print(
            f"🧭 [CONTEXT FILTER] Giữ {len(matched_foods)}/{len(foods)} món "
            f"có {label}: {contexts}"
        )
        return matched_foods

    print(
        f"🧭 [CONTEXT FILTER] Bỏ qua lọc {label}: {contexts} "
        f"vì chỉ còn {len(matched_foods)} món (< {MIN_CONTEXT_FILTER_CANDIDATES})."
    )
    return foods

def apply_adaptive_context_exclude_filter_with_trace(
    foods: list[Food],
    target_contexts: list[str],
    field_name: str,
    label: str,
    trace: dict,
) -> list[Food]:
    contexts = canonicalize_soft_tags(target_contexts)
    if not contexts:
        return foods

    removed_foods = [
        food for food in foods
        if has_matching_context(getattr(food, field_name) or [], contexts)
    ]
    kept_foods = [
        food for food in foods
        if not has_matching_context(getattr(food, field_name) or [], contexts)
    ]
    if len(kept_foods) >= MIN_CONTEXT_FILTER_CANDIDATES:
        for food in removed_foods:
            append_trace_item(trace, "context_filtered_out", {
                **food_trace_snapshot(food),
                "stage": "context_filter",
                "reason": f"excluded_{label}",
                "matched_contexts": matched_canonical_tags(getattr(food, field_name) or [], contexts),
                "excluded_contexts": contexts,
            })
        print(
            f"🧭 [CONTEXT FILTER] Loại {len(foods) - len(kept_foods)} món "
            f"có {label} không muốn: {contexts}"
        )
        return kept_foods

    print(
        f"🧭 [CONTEXT FILTER] Bỏ qua loại {label}: {contexts} "
        f"vì chỉ còn {len(kept_foods)} món (< {MIN_CONTEXT_FILTER_CANDIDATES})."
    )
    return foods

def calculate_tag_adjusted_similarity(
    food: Food,
    base_similarity: float,
    user_prefer_tags: list[str],
    medical_prefer_tags: list[str],
    user_avoid_tags: list[str],
    medical_avoid_tags: list[str],
) -> tuple[float, dict]:
    """
    Rerank mềm (tính điểm lại) bằng tag/category:
    - Tag hợp nhu cầu/y khoa: cộng điểm nhẹ.
    - Tag nên tránh: trừ điểm, không loại món ngay.
    Hard filter (lọc cứng) vẫn dành cho nguyên liệu/món bị cấm rõ ràng ở bước trước.
    """
    food_tags = get_food_scoring_tags(food)
    
    # Tìm các tag trùng khớp
    matched_user_prefer = matched_canonical_tags(food_tags, user_prefer_tags)
    matched_medical_prefer = matched_canonical_tags(food_tags, medical_prefer_tags)
    matched_user_avoid = matched_canonical_tags(food_tags, user_avoid_tags)
    matched_medical_avoid = matched_canonical_tags(food_tags, medical_avoid_tags)

    # Tính toán điểm cộng
    grouped_user_prefer = split_food_category_tags(matched_user_prefer)
    user_soft_taste_bonus_raw = (
        len(grouped_user_prefer["soft_tags"]) * USER_SOFT_TAG_BONUS +
        len(grouped_user_prefer["taste_profile"]) * USER_TASTE_BONUS
    )
    user_context_bonus_raw = (
        len(grouped_user_prefer["meal_context"]) * USER_MEAL_CONTEXT_BONUS +
        len(grouped_user_prefer["occasion_context"]) * USER_OCCASION_CONTEXT_BONUS
    )
    medical_prefer_bonus_raw = len(matched_medical_prefer) * MEDICAL_PREFER_TAG_BONUS

    # Giới hạn điểm cộng tối đa (Caps)
    user_soft_taste_bonus = min(MAX_USER_SOFT_TASTE_BONUS, user_soft_taste_bonus_raw)
    user_context_bonus = min(MAX_USER_CONTEXT_BONUS, user_context_bonus_raw)
    medical_prefer_bonus = min(MAX_MEDICAL_TAG_BONUS, medical_prefer_bonus_raw)

    tag_bonus = min(
        MAX_TAG_BONUS,
        user_soft_taste_bonus + user_context_bonus + medical_prefer_bonus,
    )
    
    # Tính toán điểm trừ (Caps)
    tag_penalty = min(
        MAX_TAG_PENALTY,
        len(matched_user_avoid) * USER_AVOID_TAG_PENALTY +
        len(matched_medical_avoid) * MEDICAL_AVOID_TAG_PENALTY,
    )
    
    # Tính điểm Similarity sau khi điều chỉnh
    adjusted_similarity = max(0.0, min(1.0, base_similarity + tag_bonus - tag_penalty))

    return adjusted_similarity, {
        "base_similarity": base_similarity,
        "tag_bonus": tag_bonus,
        "user_soft_taste_bonus": user_soft_taste_bonus,
        "user_context_bonus": user_context_bonus,
        "medical_prefer_bonus": medical_prefer_bonus,
        "tag_penalty": tag_penalty,
        "matched_prefer_tags": matched_user_prefer + matched_medical_prefer,
        "matched_user_prefer_tags": matched_user_prefer,
        "matched_medical_prefer_tags": matched_medical_prefer,
        "matched_avoid_tags": matched_user_avoid + matched_medical_avoid,
    }

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

    return opening

def canonicalize_health_tag(tag: str) -> str:
    """Đồng nhất từ khóa sức khỏe về dạng chuẩn (alias mapping)."""
    return HEALTH_TAG_ALIAS_MAP.get((tag or "").strip(), (tag or "").strip())

def _new_llm_runtime_state() -> dict:
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

async def run_embedding_with_timeout(expanded_query: str) -> tuple[list[float] | None, dict]:
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

def _format_top_food_names_for_fallback(top_foods: list[FoodResult]) -> str:
    names = [food.name for food in (top_foods or [])[:2] if food.name]
    if not names:
        return "các món trong danh sách gợi ý"
    if len(names) == 1:
        return names[0]
    return f"{names[0]} và {names[1]}"

def build_fallback_ai_response(top_foods: list[FoodResult], symptoms: list[str]) -> str:
    return build_fallback_ai_response_with_notes(top_foods, symptoms, [])

def build_fallback_ai_response_with_notes(
    top_foods: list[FoodResult],
    symptoms: list[str],
    retrieval_notes: list[str] | None = None,
) -> str:
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

async def run_post_processing_with_timeout(
    user_query: str,
    symptoms: list[str],
    top_foods: list[FoodResult],
    retrieval_notes: list[str] | None = None,
) -> tuple[str, dict]:
    started_at = time.perf_counter()
    runtime = {"status": "ok", "latency_ms": 0, "error_message": None}
    try:
        response_text = await asyncio.wait_for(
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
        if not response_text:
            runtime["status"] = "fallback"
            runtime["error_message"] = "post_processing returned empty response"
            return build_fallback_ai_response_with_notes(top_foods, symptoms, retrieval_notes), runtime
        return response_text, runtime
    except asyncio.TimeoutError:
        runtime["latency_ms"] = round((time.perf_counter() - started_at) * 1000)
        runtime["status"] = "fallback"
        runtime["error_message"] = f"post_processing timeout after {POST_PROCESSING_TIMEOUT_SECONDS}s"
        print(f"[POST-PROCESSING] Timeout sau {POST_PROCESSING_TIMEOUT_SECONDS}s, dùng template fallback.")
        return build_fallback_ai_response_with_notes(top_foods, symptoms, retrieval_notes), runtime
    except Exception as exc:
        runtime["latency_ms"] = round((time.perf_counter() - started_at) * 1000)
        runtime["status"] = "fallback"
        runtime["error_message"] = str(exc)[:300]
        print(f"[POST-PROCESSING] Lỗi wrapper: {exc}, dùng template fallback.")
        return build_fallback_ai_response_with_notes(top_foods, symptoms, retrieval_notes), runtime

def _dedupe_normalized_phrases(values: list[str]) -> list[str]:
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
    if not phrases:
        return 0.0, []
    normalized_text = _normalize_search_text(text_value)
    matched = [phrase for phrase in phrases if _phrase_in_text(normalized_text, phrase)]
    return len(matched) / max(1, len(phrases)), matched

def _normalized_tag_match_ratio(phrases: list[str], values: list[str]) -> tuple[float, list[str]]:
    if not phrases:
        return 0.0, []
    value_keys = {_normalize_search_text(value) for value in (values or [])}
    matched = [phrase for phrase in phrases if phrase in value_keys]
    return len(matched) / max(1, len(phrases)), matched

def calculate_lexical_fallback_score(food: Food, query_signals: dict) -> tuple[float, dict]:
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


# =====================================================================
# TRÍCH XUẤT VÀ XỬ LÝ Ý ĐỊNH NGƯỜI DÙNG (SUPERVISOR AGENT)
# =====================================================================

def supervisor_agent(user_input: str):
    """Sử dụng LLM (Gemini) để phân tích ý định của người dùng ra định dạng JSON tĩnh."""

    system_instruction = f"""
    Bạn là chuyên gia phân tích ý định người dùng trong ẩm thực.
    Nhiệm vụ: Trích xuất thông tin sức khỏe và sở thích ăn uống.

    [DANH SÁCH TAG SỨC KHỎE HỢP LỆ]
    {valid_health_tags}

    [DANH SÁCH TÍNH CHẤT (SOFT TAGS) HỢP LỆ]
    {valid_soft_tags}

    [QUY TẮC PHÂN LOẠI]
    1. health_constraints: Chỉ chọn từ danh sách trên. Map các từ đồng nghĩa (VD: đau dạ dày -> Viêm loét dạ dày).
    2. include_dishes: Tên các món ăn hoàn chỉnh người dùng muốn (VD: phở bò, lẩu thái, pizza).
    3. exclude_dishes: Tên các món ăn hoàn chỉnh KHÔNG muốn ăn.
    4. exclude_ingredients: Danh sách các nguyên liệu người dùng KHÔNG MUỐN.
    5. include_ingredients: Danh sách các nguyên liệu người dùng CẢM THẤY THÍCH.
    6. include_soft_tags: Tính chất, hương vị, bữa ăn hoặc ngữ cảnh người dùng MUỐN. BẮT BUỘC map vào danh sách hợp lệ.
       - Thời điểm/bữa ăn user nói rõ: "sáng mai", "bữa sáng" -> "Ăn sáng"; "trưa" -> "Ăn trưa"; "tối nay" -> "Ăn tối"; "xế/chiều" -> "Ăn chiều / xế"; "khuya/đêm" -> "Ăn khuya".
       - Ngữ cảnh user nói rõ: "vừa no/no bụng" -> "Ăn no"; "ăn vặt" -> "Ăn vặt"; "tráng miệng" -> "Tráng miệng"; "ấm bụng" -> "Ấm bụng"; "mồi nhậu/nhậu" -> "Mồi nhậu".
       - Tính chất user nói rõ: "đồ nước" -> "Món nước", "thanh mát" -> "Thanh mát/Giải nhiệt".
    7. exclude_soft_tags: Tính chất, hương vị người dùng KHÔNG MUỐN (VD: "không dầu mỡ" -> "Chiên / Rán" hoặc "Béo ngậy"). BẮT BUỘC map vào danh sách.
    8. include_soft_tags / exclude_soft_tags chỉ dùng cho sở thích ăn uống được user nói rõ. Không được tự suy diễn tag nên tránh/nên ưu tiên từ bệnh lý. Nếu user nói bệnh lý như đau dạ dày, cao huyết áp, gout..., chỉ điền vào health_constraints. Medical rules ở backend sẽ tự sinh prefer/exclude tags.
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
            model="gemini-2.5-flash",
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

async def resolve_food_conflicts(user_input: str, db: AsyncSession):
    """
    Kết hợp kết quả từ Agent và Database để giải quyết xung đột
    giữa Sở thích (những gì User muốn) và Sức khỏe (những gì y khoa cấm/khuyên).
    """
    extracted_data, supervisor_runtime = await run_supervisor_with_timeout(user_input)

    # Lấy thông tin trích xuất
    symptoms = [canonicalize_health_tag(tag) for tag in extracted_data.get("health_constraints", [])]
    user_include_dishes = extracted_data.get("include_dishes", [])
    user_exclude_dishes = extracted_data.get("exclude_dishes", [])

    user_likes_ings = set(extracted_data.get("include_ingredients", []))
    user_dislikes_ings = set(extracted_data.get("exclude_ingredients", []))

    user_include_tags = set(extracted_data.get("include_soft_tags", []))
    user_exclude_tags = set(extracted_data.get("exclude_soft_tags", []))

    # Khởi tạo tập hợp y khoa
    allergy_constraints = set()
    disease_constraints = set()
    medical_exclude_tags = set()
    medical_prefer_tags = set()
    allergy_exclude_ings = set()
    disease_exclude_ings = set()
    medical_exclude_ings = set()
    medical_prefer_ings = set()

    # Truy vấn DB để lấy quy tắc y khoa theo bệnh lý
    if symptoms:
        stmt = select(Tag).where(Tag.name.in_(symptoms))
        result = await db.execute(stmt)
        tags_db = result.scalars().all()

        for tag in tags_db:
            # Dị ứng cần chặn theo nguyên liệu cụ thể. Chặn theo soft tag như "Hải sản"
            # dễ loại nhầm các món không chứa tác nhân dị ứng trực tiếp.
            if tag.tag_type == "ALLERGY":
                allergy_constraints.add(tag.name)
                allergy_exclude_ings.update(tag.exclude_ingredient)
            else:
                disease_constraints.add(tag.name)
                disease_exclude_ings.update(tag.exclude_ingredient)
                medical_exclude_tags.update(canonicalize_soft_tags(tag.exclude_soft_tag))
            medical_prefer_tags.update(canonicalize_soft_tags(tag.prefer_soft_tag))
            medical_exclude_ings.update(tag.exclude_ingredient)
            medical_prefer_ings.update(tag.prefer_ingredient)

    # Chuẩn hoá tags
    user_include_tags = set(canonicalize_soft_tags(list(user_include_tags)))
    user_exclude_tags = set(canonicalize_soft_tags(list(user_exclude_tags)))

    # Logic kiểm tra thông báo cảnh báo (warning) cho nguyên liệu
    alias_override_rules = await load_enabled_alias_override_rules(db)

    medical_exclude_keys = set(
        generate_filter_keys(medical_exclude_ings, extra_rules=alias_override_rules)
    )

    conflicting_ings = set()
    safe_user_include_ings = set()
    for ing in user_likes_ings:
        user_ing_keys = set(generate_filter_keys([ing], extra_rules=alias_override_rules))
        if user_ing_keys.intersection(medical_exclude_keys):
            conflicting_ings.add(ing.lower())
        else:
            safe_user_include_ings.add(ing.lower())


    # 2. Logic cho tính chất (Soft tags)
    user_tags_map = {_normalize_tag_key(tag): tag for tag in user_include_tags}
    medical_tags_map = {_normalize_tag_key(tag): tag for tag in medical_exclude_tags}
    
    # Phép giao (Intersection) để lấy lỗi
    conflicting_tag_keys = set(user_tags_map.keys()).intersection(set(medical_tags_map.keys()))
    conflicting_tags = {user_tags_map[k] for k in conflicting_tag_keys}

    # Phép trừ (Difference) để lấy danh sách an toàn (Kiểu dữ liệu sinh ra là SET)
    safe_tag_keys = set(user_tags_map.keys()) - set(medical_tags_map.keys())
    safe_user_include_tags = {user_tags_map[k] for k in safe_tag_keys}
    
    all_conflicts = list(conflicting_ings) + list(conflicting_tags)

    print(f"\n[PROCESSING] All Conflicts: {all_conflicts}")

    warning_message = None
    if all_conflicts:
        warning_message = f"Hệ thống phát hiện bạn muốn ăn đồ có ({', '.join(all_conflicts)}), nhưng với tình trạng ({', '.join(symptoms)}), bạn cần kiêng chúng để đảm bảo an toàn."
    if supervisor_runtime.get("status") == "fallback":
        warning_message = SUPERVISOR_FALLBACK_WARNING

    return {
        "symptoms": symptoms,
        "final_exclude_ings": list(user_dislikes_ings.union(medical_exclude_ings)),
        "final_include_ings": list(safe_user_include_ings),
        "allergy_constraints": list(allergy_constraints),
        "disease_constraints": list(disease_constraints),
        "allergy_exclude_ings": list(allergy_exclude_ings),
        "disease_exclude_ings": list(disease_exclude_ings),
        "medical_exclude_tags": list(medical_exclude_tags),
        "medical_prefer_tags": list(medical_prefer_tags),
        "medical_prefer_ings": list(medical_prefer_ings),
        "user_include_tags": list(safe_user_include_tags),
        "user_exclude_tags": list(user_exclude_tags),
        "user_include_dishes": user_include_dishes,
        "user_exclude_dishes": user_exclude_dishes,
        "warning_message": warning_message,
        "llm_runtime": {
            "supervisor_status": supervisor_runtime.get("status"),
            "supervisor_error": supervisor_runtime.get("error_message"),
            "stage_latency_ms": {
                "supervisor": supervisor_runtime.get("latency_ms", 0),
            },
            "fallback_extracted_constraints": symptoms if supervisor_runtime.get("status") == "fallback" else [],
        },
    }


# =====================================================================
# 3. POST-PROCESSING AGENT (Tư vấn ẩm thực tự nhiên với Dynamic Rule)
# =====================================================================

# Load file luật một lần khi khởi động server (tránh đọc file lặp lại mỗi request)
_ADVICE_RULES_PATH = STANDARD_DATA_DIR / "generated-rules" / "medical-advice-rules" / "medical_advice_rules.json"
with _ADVICE_RULES_PATH.open("r", encoding="utf-8") as _f:
    MEDICAL_ADVICE_RULES: dict = json.load(_f)

def post_processing_agent(
    user_query: str,
    user_symptoms: list[str],
    top5_foods: list,  # List[FoodResult] - Pydantic objects
    retrieval_notes: list[str] | None = None,
) -> str:
    """
    Dynamic Rule Injection Agent:
    1. Thu thập tất cả soft_tags + core_ingredients của Top 5 món
    2. Đối chiếu với medical_advice_rules.json theo từng bệnh lý của user
    3. Tổng hợp các cảnh báo phù hợp -> Bơm vào prompt -> Gọi LLM
    """

    # --- Bước 1: Thu thập tags & ingredients từ Top 5 ---
    all_tags: set[str] = set()
    all_ingredients: set[str] = set()
    foods_summary = []

    for food in top5_foods:
        all_tags.update(food.soft_tags)
        all_tags.update(food.taste_profile)
        all_tags.update(food.meal_context)
        all_tags.update(food.occasion_context)
        all_ingredients.update(food.core_ingredients)
        foods_summary.append({
            "name": food.name,
            "tags": food.soft_tags,
            "taste_profile": food.taste_profile,
            "meal_context": food.meal_context,
            "occasion_context": food.occasion_context,
            "score": round(food.matchScore, 1)
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
Nhiệm vụ: Dựa vào dữ liệu có sẵn, hãy tư vấn người dùng một cách gần gũi, thận trọng và không nói quá mức an toàn.

[Tình trạng sức khỏe của người dùng]
{symptoms_text}

[Top món ăn đã qua lọc và xếp hạng]
{foods_text}

[Ghi chú truy xuất từ hệ thống]
{retrieval_notes_text}

[Hướng dẫn sức khỏe bắt buộc]
{medical_warnings}

[QUY TẮC AN TOÀN KHI VIẾT]
- [Top món ăn đã qua lọc và xếp hạng] chỉ là danh sách ứng viên tốt nhất theo dữ liệu, không đồng nghĩa tất cả đều an toàn tuyệt đối.
- Chỉ được nhắc tên món có trong [Top món ăn đã qua lọc và xếp hạng]. Không tự thêm món mới, không suy diễn món tương tự, không bịa món ngoài danh sách.
- Không được gọi một món là "rất phù hợp", "rất an toàn", "lựa chọn tuyệt vời" nếu món đó có tag/nguyên liệu cần lưu ý theo [Hướng dẫn sức khỏe bắt buộc].
- Với món đúng sở thích người dùng nhưng có rủi ro sức khỏe, phải dùng ngôn ngữ thận trọng như: "có thể cân nhắc nếu điều chỉnh", "đáp ứng sở thích nhưng cần ăn thận trọng", "không phải lựa chọn tối ưu nếu ăn ngoài".
- Nếu có món an toàn hơn theo bệnh lý, hãy nói rõ món đó nên được ưu tiên hơn món đúng sở thích nhưng nhiều rủi ro.
- Mọi lời khuyên điều chỉnh cách ăn phải dựa trên [Hướng dẫn sức khỏe bắt buộc]. Không tự tạo thêm khuyến nghị y tế ngoài dữ liệu được cung cấp.
- Nếu [Ghi chú truy xuất từ hệ thống] nói không tìm thấy món khớp nguyên liệu người dùng muốn, bắt buộc nói rõ rằng các món hiện tại là lựa chọn thay thế an toàn hơn.
- Nếu [Ghi chú truy xuất từ hệ thống] nói có xung đột giữa sở thích rõ ràng của người dùng và món được trả về, bắt buộc giải thích ngắn gọn lý do, không được bỏ qua yêu cầu đó.

[QUY TẮC VĂN PHONG]
- Viết trong khoảng 150-200 chữ.
- Giọng gần gũi, dễ hiểu, không dùng bullet point.
- Thể hiện sự thấu hiểu tình trạng sức khỏe của người dùng.
- Giới thiệu 1-2 món nổi bật, nhưng phải phân biệt rõ món "đúng sở thích nhưng cần cẩn thận" và món "nên ưu tiên hơn cho sức khỏe" nếu có.
"""

    # --- Bước 6: Gọi LLM ---
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.2,
            ),
            contents=f"Câu hỏi gốc của người dùng: {user_query}"
        )
        return response.text.strip()
    except Exception as e:
        print(f"[POST-PROCESSING] Lỗi LLM: {e}")
        return ""


# =====================================================================
# 4. HÀM TÌM KIẾM CHÍNH (Được gọi từ API)
# =====================================================================

async def search_food(
    query: str,
    db: AsyncSession,
    thread_id: uuid.UUID | None = None,
    debug: bool = False,
) -> SearchResponse:
    """
    Luồng chạy chính để tìm kiếm món ăn:
    1. Trích xuất ý định (Supervisor Agent).
    2. Build Enriched Query.
    3. Lọc Database (SQL) bằng nguyên liệu cấm.
    4. Rerank kết quả bằng Vector Similarity + Tag Scoring.
    5. Post-Processing tạo phản hồi tư vấn tự nhiên.
    """
    llm_runtime = _new_llm_runtime_state()
    retrieval_trace = init_retrieval_trace()

    # --- Bước 1: Chạy luồng bảo vệ và xử lý xung đột ---
    payload = await resolve_food_conflicts(query, db)
    if payload and payload.get("llm_runtime"):
        payload_runtime = payload["llm_runtime"]
        llm_runtime["supervisor_status"] = payload_runtime.get("supervisor_status", "ok")
        llm_runtime["stage_latency_ms"].update(payload_runtime.get("stage_latency_ms", {}))
        if payload_runtime.get("supervisor_error"):
            llm_runtime["supervisor_error"] = payload_runtime["supervisor_error"]
        if payload_runtime.get("fallback_extracted_constraints"):
            llm_runtime["fallback_extracted_constraints"] = payload_runtime["fallback_extracted_constraints"]
        if llm_runtime["supervisor_status"] == "fallback":
            llm_runtime["fallbacks_used"].append("supervisor")
            llm_runtime["user_visible_warning_applied"] = True

    if payload:
        print("\n" + "="*50)
        print("🎯 KẾT QUẢ TỪ AGENT & XỬ LÝ XUNG ĐỘT:")
        print(json.dumps(payload, ensure_ascii=False, indent=4))
        print("="*50 + "\n")
    else:
        print("❌ Payload trả về rỗng (Có lỗi từ LLM)")
    
    # Xử lý fallback nếu LLM báo lỗi
    if not payload:
        return SearchResponse(
            query=query,
            ai_insight=AIInsight(exclude=[], include=[], prefer=[]),
            results=[],
            disclaimer=SEARCH_DISCLAIMER,
        )
    
    # Bóc tách biến từ Payload
    user_exclude_dishes = payload["user_exclude_dishes"]
    symptoms = payload["symptoms"]
    final_e_ings = payload["final_exclude_ings"]
    final_p_ings = payload["final_include_ings"]
    allergy_constraints = payload.get("allergy_constraints", [])
    allergy_e_ings = payload.get("allergy_exclude_ings", [])
    disease_e_ings = payload.get("disease_exclude_ings", [])
    medical_e_tags = payload["medical_exclude_tags"]
    medical_p_tags = payload["medical_prefer_tags"]
    medical_p_ings = payload.get("medical_prefer_ings", [])

    user_include_tags = payload["user_include_tags"]
    user_exclude_tags = payload["user_exclude_tags"]
    user_include_dishes = payload["user_include_dishes"]
    warning_message = payload["warning_message"]
    
    grouped_user_include_tags = split_food_category_tags(user_include_tags)
    grouped_user_exclude_tags = split_food_category_tags(user_exclude_tags)
    alias_override_rules = await load_enabled_alias_override_rules(db)
    exclude_ingredient_keys = generate_filter_keys(
        final_e_ings,
        extra_rules=alias_override_rules,
    )
    allergy_exclude_ingredient_keys = generate_filter_keys(
        allergy_e_ings,
        extra_rules=alias_override_rules,
    )
    disease_exclude_ingredient_keys = generate_filter_keys(
        disease_e_ings,
        extra_rules=alias_override_rules,
    )
    include_ingredient_keys = generate_filter_keys(
        final_p_ings,
        extra_rules=alias_override_rules,
    )
    retrieval_notes: list[str] = []
    main_meal_request = is_main_meal_request(query, user_include_tags)
    explicit_side_or_snack_request = has_explicit_side_or_snack_request(
        query=query,
        user_include_dishes=user_include_dishes,
        user_include_tags=user_include_tags,
    )
    primary_ingredient_priority_only = (
        main_meal_request and not explicit_side_or_snack_request
    )
    if main_meal_request:
        mode_label = (
            "có yêu cầu món phụ/snack rõ ràng"
            if explicit_side_or_snack_request
            else "ưu tiên món chính/đủ no"
        )
        print(f"🍽️ [MEAL ROLE] Bật rerank bữa chính ({mode_label}).")

    # --- Bước 2: Xây dựng Enriched Query ---
    # Đồng bộ cấu trúc query embedding với text_to_embed của món ăn trong seed_service.py.
    # Tên bệnh vẫn dùng cho rule/warning; query embedding ưu tiên các tiêu chí món ăn.
    enriched_parts = [f"Mô tả: {query}"]

    if user_include_dishes:
        enriched_parts.append(f"Món ăn: {', '.join(user_include_dishes)}")

    # Bổ sung nguyên liệu ưa thích (gộp user + y khoa)
    all_prefer_ings = list(set(final_p_ings + medical_p_ings))
    if all_prefer_ings:
        enriched_parts.append(f"Nguyên liệu chính: {', '.join(all_prefer_ings)}")

    # Bổ sung tag ưu tiên theo đúng các nhóm category đã tách
    combined_prefer_tags = list(set(user_include_tags + medical_p_tags))
    grouped_prefer_tags = split_food_category_tags(combined_prefer_tags)

    if grouped_prefer_tags["soft_tags"]:
        enriched_parts.append(f"Tính chất: {', '.join(grouped_prefer_tags['soft_tags'])}")

    if grouped_prefer_tags["taste_profile"]:
        enriched_parts.append(f"Hồ sơ vị: {', '.join(grouped_prefer_tags['taste_profile'])}")

    if grouped_prefer_tags["meal_context"]:
        enriched_parts.append(f"Bữa ăn phù hợp: {', '.join(grouped_prefer_tags['meal_context'])}")

    if grouped_prefer_tags["occasion_context"]:
        enriched_parts.append(f"Ngữ cảnh sử dụng: {', '.join(grouped_prefer_tags['occasion_context'])}")

    expanded_query = ". ".join(enriched_parts)
    print(f"🔎 ENRICHED QUERY: {expanded_query}")

    # --- Nhúng Vector (Embedding) ---
    query_vector, embedding_runtime = await run_embedding_with_timeout(expanded_query)
    llm_runtime["embedding_status"] = embedding_runtime.get("status", "ok")
    llm_runtime["stage_latency_ms"]["embedding"] = embedding_runtime.get("latency_ms", 0)
    if embedding_runtime.get("error_message"):
        llm_runtime["embedding_error"] = embedding_runtime["error_message"]
    retrieval_mode = "semantic" if query_vector is not None else "lexical_fallback"
    llm_runtime["retrieval_mode"] = retrieval_mode
    if retrieval_mode == "lexical_fallback":
        llm_runtime["fallbacks_used"].append("embedding")
        llm_runtime["user_visible_retrieval_note_applied"] = True
        retrieval_notes.append(EMBEDDING_FALLBACK_RETRIEVAL_NOTE)

    # --- Bước 3: Bộ lọc CSDL (SQL Filter) ---
    # Lọc tập món ăn hợp lệ (loại exclude_ingredients + exclude_dishes)
    # Không dùng cosine_distance trong SQL — vector search sẽ thực hiện in-memory
    stmt = select(Food)

    if exclude_ingredient_keys:
        hard_trace_result = await db.execute(
            select(Food).where(Food.core_ingredient_keys.overlap(exclude_ingredient_keys))
        )
        for food in hard_trace_result.scalars().all():
            append_trace_item(retrieval_trace, "hard_filtered_out", {
                **food_trace_snapshot(food),
                "stage": "sql_hard_filter",
                "reason": "ingredient_key_overlap",
                "matched_keys": matched_keys(food.core_ingredient_keys or [], exclude_ingredient_keys),
                "core_ingredient_keys": food.core_ingredient_keys or [],
            })
        stmt = stmt.where(not_(Food.core_ingredient_keys.overlap(exclude_ingredient_keys)))

    if user_exclude_dishes:
        for dish in user_exclude_dishes:
            dish_trace_result = await db.execute(
                select(Food).where(Food.name.ilike(f"%{dish}%"))
            )
            for food in dish_trace_result.scalars().all():
                append_trace_item(retrieval_trace, "dish_name_filtered_out", {
                    **food_trace_snapshot(food),
                    "stage": "sql_dish_filter",
                    "reason": "excluded_dish_name",
                    "matched_dish": dish,
                })
            stmt = stmt.where(not_(Food.name.ilike(f"%{dish}%")))

    db_result = await db.execute(stmt)
    filtered_foods = db_result.scalars().all() # Tập món ăn sạch (Candidate)
    candidate_count = len(filtered_foods)
    python_removed_count = 0
    allergy_text_removed_count = 0
    allergy_key_miss_examples: list[dict] = []

    # Lọc mềm bằng Python cho dữ liệu cũ/chưa rebuild đủ core_ingredient_keys.
    if exclude_ingredient_keys:
        before_python_filter = len(filtered_foods)
        python_safe_foods = []
        for food in filtered_foods:
            food_matched_keys = matched_keys(food.core_ingredient_keys or [], exclude_ingredient_keys)
            if food_matched_keys:
                append_trace_item(retrieval_trace, "hard_filtered_out", {
                    **food_trace_snapshot(food),
                    "stage": "python_hard_filter",
                    "reason": "ingredient_key_overlap",
                    "matched_keys": food_matched_keys,
                    "core_ingredient_keys": food.core_ingredient_keys or [],
                })
            else:
                python_safe_foods.append(food)
        filtered_foods = python_safe_foods
        python_removed_count = before_python_filter - len(filtered_foods)
        print(
            f"🛡️ [PYTHON INGREDIENT FILTER] Loại thêm "
            f"{python_removed_count} món bằng core_ingredient_keys: "
            f"{exclude_ingredient_keys}"
        )

    if allergy_constraints:
        before_allergy_text_filter = len(filtered_foods)
        allergy_safe_foods = []
        for food in filtered_foods:
            allergy_text_matches = detect_allergy_text_matches(
                food,
                allergy_constraints,
                allergy_e_ings,
            )
            if not allergy_text_matches:
                allergy_safe_foods.append(food)
                continue

            allergy_text_removed_count += 1
            has_allergy_key = _food_has_any_ingredient_key(
                food,
                allergy_exclude_ingredient_keys,
            )
            matched_pairs = []
            seen_match_keys = set()
            for match in allergy_text_matches:
                match_key = (match.get("allergy"), match.get("phrase"))
                if match_key in seen_match_keys:
                    continue
                seen_match_keys.add(match_key)
                matched_pairs.append(match)
            append_trace_item(retrieval_trace, "allergy_text_filtered_out", {
                **food_trace_snapshot(food),
                "stage": "allergy_text_filter",
                "reason": "allergy_text_match",
                "matches": matched_pairs[:5],
                "core_ingredients": food.core_ingredients or [],
                "core_ingredient_keys": food.core_ingredient_keys or [],
            })

            if not has_allergy_key and len(allergy_key_miss_examples) < 20:
                miss_example = {
                    "food_id": str(food.id),
                    "food_name": food.name,
                    "matches": matched_pairs[:5],
                    "core_ingredients": food.core_ingredients or [],
                    "core_ingredient_keys": food.core_ingredient_keys or [],
                }
                allergy_key_miss_examples.append(miss_example)
                print(
                    "🚨 [ALLERGY_KEY_MISS] "
                    f"{food.name} text-match={matched_pairs[:3]} "
                    f"nhưng core_ingredient_keys không giao allergy keys."
                )
            else:
                print(
                    "🛡️ [ALLERGY TEXT FILTER] "
                    f"Loại {food.name} vì match={matched_pairs[:3]}"
                )

        filtered_foods = allergy_safe_foods
        print(
            f"🛡️ [ALLERGY TEXT FILTER] Loại "
            f"{allergy_text_removed_count}/{before_allergy_text_filter} món "
            "bằng text fallback trên core_ingredients."
        )

    # Lọc ngữ cảnh (Context filter) 
    context_before_count = len(filtered_foods)
    filtered_foods = apply_adaptive_context_include_filter_with_trace(
        foods=filtered_foods,
        target_contexts=grouped_user_include_tags["meal_context"],
        field_name="meal_context",
        label="meal_context",
        trace=retrieval_trace,
    )
    filtered_foods = apply_adaptive_context_include_filter_with_trace(
        foods=filtered_foods,
        target_contexts=grouped_user_include_tags["occasion_context"],
        field_name="occasion_context",
        label="occasion_context",
        trace=retrieval_trace,
    )
    filtered_foods = apply_adaptive_context_exclude_filter_with_trace(
        foods=filtered_foods,
        target_contexts=grouped_user_exclude_tags["meal_context"],
        field_name="meal_context",
        label="meal_context",
        trace=retrieval_trace,
    )
    filtered_foods = apply_adaptive_context_exclude_filter_with_trace(
        foods=filtered_foods,
        target_contexts=grouped_user_exclude_tags["occasion_context"],
        field_name="occasion_context",
        label="occasion_context",
        trace=retrieval_trace,
    )
    context_after_count = len(filtered_foods)

    include_ingredient_match_count = sum(
        1 for food in filtered_foods
        if include_ingredient_keys and _food_has_any_ingredient_key(food, include_ingredient_keys)
    )
    ingredient_priority_food_ids = collect_ingredient_priority_food_ids(
        foods=filtered_foods,
        include_keys=include_ingredient_keys,
        main_meal_request=main_meal_request,
        require_primary_role=primary_ingredient_priority_only,
    )
    if include_ingredient_keys and final_p_ings:
        requested_ingredients_text = ", ".join(final_p_ings)
        if ingredient_priority_food_ids:
            primary_label = " trong vai trò món chính" if primary_ingredient_priority_only else ""
            retrieval_notes.append(
                f"Các món khớp nguyên liệu người dùng muốn{primary_label} ({requested_ingredients_text}) "
                "đã được xếp ưu tiên trước; nếu chưa đủ top 5 thì bổ sung món an toàn khác."
            )
        elif primary_ingredient_priority_only and include_ingredient_match_count:
            side_match_message = (
                "Có món phụ/canh/salad khớp nguyên liệu người dùng muốn "
                f"({requested_ingredients_text}), nhưng không xem đó là món chính cho bữa trưa/tối; "
                "các món trả về ưu tiên lựa chọn bữa chính an toàn hơn."
            )
            retrieval_notes.append(side_match_message)
            warning_message = f"{warning_message} {side_match_message}" if warning_message else side_match_message
        else:
            no_match_message = (
                "Không tìm thấy món an toàn khớp nguyên liệu người dùng muốn "
                f"({requested_ingredients_text}) sau khi áp dụng bộ lọc bệnh lý/ngữ cảnh; "
                "các món trả về là lựa chọn thay thế an toàn hơn."
            )
            retrieval_notes.append(no_match_message)
            warning_message = f"{warning_message} {no_match_message}" if warning_message else no_match_message

    print(f"\n{'='*60}")
    print(f"📦 [BƯỚC 3 - FILTERED CANDIDATES] Còn lại {len(filtered_foods)} món sau khi lọc nguyên liệu/ngữ cảnh:")
    for i, food in enumerate(filtered_foods, 1):
        print(f"  {i:>3}. {food.name}")
    print(f"{'='*60}\n")

    # --- Bước 4: In-memory Semantic Search hoặc Lexical Fallback trên tập đã lọc ---
    query_arr = np.array(query_vector, dtype=np.float32) if query_vector is not None else None
    query_norm = np.linalg.norm(query_arr) if query_arr is not None else 0
    fallback_query_signals = build_fallback_query_signals(
        query=query,
        user_include_dishes=user_include_dishes,
        final_include_ings=final_p_ings,
        user_include_tags=user_include_tags,
        medical_prefer_tags=medical_p_tags,
    ) if retrieval_mode == "lexical_fallback" else None

    step_label = "COSINE + TAG RERANK" if retrieval_mode == "semantic" else "LEXICAL FALLBACK + TAG RERANK"
    print(f"🔢 [BƯỚC 4 - {step_label}] Tính điểm từng món:")
    scored = []
    missing_embedding_count = 0
    zero_vector_count = 0
    
    for food in filtered_foods:
        lexical_details = {}
        if retrieval_mode == "semantic":
            if not food.embedding:
                missing_embedding_count += 1
                append_trace_item(retrieval_trace, "embedding_skipped", {
                    **food_trace_snapshot(food),
                    "stage": "semantic_scoring",
                    "reason": "missing_embedding",
                })
                print(f"  ⚠️  {food.name}: BỎ QUA (không có embedding)")
                continue

            food_arr = np.array(food.embedding.to_list(), dtype=np.float32)
            food_norm = np.linalg.norm(food_arr)
            if food_norm == 0 or query_norm == 0:
                zero_vector_count += 1
                append_trace_item(retrieval_trace, "embedding_skipped", {
                    **food_trace_snapshot(food),
                    "stage": "semantic_scoring",
                    "reason": "zero_vector",
                })
                print(f"  ⚠️  {food.name}: BỎ QUA (vector = 0)")
                continue

            # Cosine similarity = dot(a, b) / (||a|| * ||b||)
            similarity = float(np.dot(query_arr, food_arr) / (query_norm * food_norm))
        else:
            similarity, lexical_details = calculate_lexical_fallback_score(
                food,
                fallback_query_signals or {},
            )
        
        # Điều chỉnh điểm (Rerank) dựa trên Tag thưởng/phạt
        adjusted_similarity, score_details = calculate_tag_adjusted_similarity(
            food=food,
            base_similarity=similarity,
            user_prefer_tags=user_include_tags,
            medical_prefer_tags=medical_p_tags,
            user_avoid_tags=user_exclude_tags,
            medical_avoid_tags=medical_e_tags,
        )
        score_details["retrieval_mode"] = retrieval_mode
        if lexical_details:
            score_details["lexical_signal_breakdown"] = lexical_details
        tag_adjusted_similarity = adjusted_similarity
        serving_role = infer_serving_role(food)
        meal_role_adjustment = get_meal_role_adjustment(
            serving_role=serving_role,
            main_meal_request=main_meal_request,
            explicit_side_or_snack_request=explicit_side_or_snack_request,
        )
        adjusted_similarity = max(
            0.0,
            min(1.0, tag_adjusted_similarity + meal_role_adjustment),
        )
        score_details.update({
            "serving_role": serving_role,
            "meal_role_adjustment": meal_role_adjustment,
            "main_meal_request": main_meal_request,
            "explicit_side_or_snack_request": explicit_side_or_snack_request,
        })
        ingredient_priority_match = food.id in ingredient_priority_food_ids
        scored.append((food, adjusted_similarity, score_details, ingredient_priority_match))
        
        # In log chấm điểm
        priority_label = " [ưu tiên nguyên liệu]" if ingredient_priority_match else ""
        base_label = "base" if retrieval_mode == "semantic" else "lexical"
        print(
            f"  📊 {food.name}{priority_label} [{serving_role}]: {base_label} {similarity*100:.2f}% "
            f"+{score_details['tag_bonus']*100:.1f} "
            f"-{score_details['tag_penalty']*100:.1f} "
            f"{meal_role_adjustment*100:+.1f} role "
            f"=> {adjusted_similarity*100:.2f}%"
        )
        if score_details["matched_prefer_tags"] or score_details["matched_avoid_tags"]:
            print(
                f"       prefer={score_details['matched_prefer_tags']} "
                f"avoid={score_details['matched_avoid_tags']}"
            )
        if lexical_details:
            print(
                "       lexical="
                f"name:{lexical_details['name_score']:.2f} "
                f"ing:{lexical_details['ingredient_score']:.2f} "
                f"meal:{lexical_details['meal_context_score']:.2f} "
                f"tag:{lexical_details['soft_tag_score']:.2f} "
                f"res:{lexical_details['residual_score']:.2f}"
            )

    scored_count = len(scored)

    # Sắp xếp giảm dần theo điểm đã rerank, lấy top 5
    if ingredient_priority_food_ids:
        scored.sort(key=lambda x: (x[3], x[1]), reverse=True)
    else:
        scored.sort(key=lambda x: x[1], reverse=True)
    top5 = scored[:5]
    preference_conflict_notes, preference_conflicts_by_food_id, preference_conflict_summaries = build_explicit_preference_conflict_notes(
        user_include_tags=user_include_tags,
        medical_prefer_tags=medical_p_tags,
        top5=top5,
        scored=scored,
    )
    if preference_conflict_notes:
        retrieval_notes.extend(preference_conflict_notes)
        for note in preference_conflict_notes:
            print(f"🧭 [PREFERENCE CONFLICT] {note}")
        for food, _, score_details, _ in top5:
            if food.id in preference_conflicts_by_food_id:
                score_details["explicit_preference_conflicts"] = preference_conflicts_by_food_id[food.id]
    for food, adjusted_similarity, score_details, ingredient_priority_match in scored[:TRACE_LIMIT]:
        append_trace_item(
            retrieval_trace,
            "score_breakdown",
            build_score_trace_item(
                food=food,
                final_score=adjusted_similarity,
                score_details=score_details,
                ingredient_priority_match=ingredient_priority_match,
            ),
        )

    print(f"\n{'='*60}")
    print(f"🏆 [BƯỚC 5 - KẾT QUẢ CUỐI] Top {len(top5)} món phù hợp nhất:")
    for rank, (food, adjusted_similarity, score_details, ingredient_priority_match) in enumerate(top5, 1):
        priority_label = " [ưu tiên nguyên liệu]" if ingredient_priority_match else ""
        print(
            f"  #{rank} [{adjusted_similarity*100:.2f}%] {food.name}{priority_label} "
            f"({score_details['retrieval_mode']} {score_details['base_similarity']*100:.2f}%, role {score_details['serving_role']})"
        )
        print(f"       Soft tags: {food.soft_tags}")
        print(f"       Taste: {food.taste_profile} | Meal: {food.meal_context} | Occasion: {food.occasion_context}")
    print(f"{'='*60}\n")

    # --- Bước 6: Map kết quả về Pydantic Schemas ---
    results_list = []
    for food, adjusted_similarity, score_details, ingredient_priority_match in top5:
        match_score = adjusted_similarity * 100
        reason = build_food_reason(
            food=food,
            match_score=match_score,
            score_details=score_details,
            ingredient_priority_match=ingredient_priority_match,
            requested_ingredients=final_p_ings,
        )
        results_list.append(FoodResult(
            id=food.id,
            name=food.name,
            description=food.description,
            img_url=food.img_url,
            core_ingredients=food.core_ingredients,
            soft_tags=food.soft_tags,
            taste_profile=food.taste_profile,
            meal_context=food.meal_context,
            occasion_context=food.occasion_context,
            matchScore=match_score,
            reason=reason,
        ))
    returned_count = len(results_list)
    for rank, result in enumerate(results_list, 1):
        append_trace_item(
            retrieval_trace,
            "returned",
            build_returned_trace_item(rank, result),
        )

    # --- Bước 7: Post-processing Agent (Dynamic Rule Injection) ---
    ai_response_text, post_processing_runtime = await run_post_processing_with_timeout(
        query,
        symptoms,
        results_list,
        retrieval_notes,
    )
    llm_runtime["post_processing_status"] = post_processing_runtime.get("status", "ok")
    llm_runtime["stage_latency_ms"]["post_processing"] = post_processing_runtime.get("latency_ms", 0)
    if post_processing_runtime.get("error_message"):
        llm_runtime["post_processing_error"] = post_processing_runtime["error_message"]
    if post_processing_runtime.get("status") == "fallback":
        llm_runtime["fallbacks_used"].append("post_processing")

    ai_insight = AIInsight(
        exclude=medical_e_tags + final_e_ings,
        include=symptoms, # Trả về list bệnh lý để UI dễ hiển thị Warning
        prefer=medical_p_tags + final_p_ings + medical_p_ings,
        warning_message=warning_message
    )
    excluded_summary = {
        "hard_filter": {
            "exclude_ingredient_keys": exclude_ingredient_keys,
            "allergy_constraints": allergy_constraints,
            "allergy_exclude_ingredient_keys": allergy_exclude_ingredient_keys,
            "disease_exclude_ingredient_keys": disease_exclude_ingredient_keys,
            "user_exclude_dishes": user_exclude_dishes,
            "candidate_count_after_sql": candidate_count,
            "python_removed_count": python_removed_count,
            "allergy_text_removed_count": allergy_text_removed_count,
            "allergy_key_miss_examples": allergy_key_miss_examples,
            "remaining_count_after_python": context_before_count,
        },
        "context_filter": {
            "include_meal_context": grouped_user_include_tags["meal_context"],
            "include_occasion_context": grouped_user_include_tags["occasion_context"],
            "exclude_meal_context": grouped_user_exclude_tags["meal_context"],
            "exclude_occasion_context": grouped_user_exclude_tags["occasion_context"],
            "before_count": context_before_count,
            "after_count": context_after_count,
        },
        "ingredient_priority": {
            "include_ingredient_keys": include_ingredient_keys,
            "candidate_match_count": include_ingredient_match_count,
            "matched_count": len(ingredient_priority_food_ids),
            "primary_ingredient_priority_only": primary_ingredient_priority_only,
        },
        "meal_role_rerank": {
            "enabled": main_meal_request,
            "explicit_side_or_snack_request": explicit_side_or_snack_request,
            "role_adjustments": MEAL_ROLE_ADJUSTMENTS,
            "primary_ingredient_priority_only": primary_ingredient_priority_only,
        },
        "preference_conflict": {
            "enabled": bool(preference_conflict_summaries),
            "pairs_checked": [
                {"requested_tag": requested, "returned_conflict_tag": returned}
                for requested, returned in PREFERENCE_CONFLICT_PAIRS
            ],
            "conflicts": preference_conflict_summaries,
        },
        "embedding": {
            "retrieval_mode": retrieval_mode,
            "missing_embedding_count": missing_embedding_count,
            "zero_vector_count": zero_vector_count,
            "scored_count": scored_count,
        },
        "llm_runtime": llm_runtime,
        "retrieval_trace": retrieval_trace,
    }
    query_log_id = None
    try:
        query_log = await create_query_log(
            db,
            query=query,
            ai_insight=ai_insight,
            final_exclude_ings=final_e_ings,
            exclude_ingredient_keys=exclude_ingredient_keys,
            user_include_tags=user_include_tags,
            user_exclude_tags=user_exclude_tags,
            candidate_count=candidate_count,
            filtered_count=context_after_count,
            scored_count=scored_count,
            returned_count=returned_count,
            excluded_summary=excluded_summary,
            retrieval_notes=retrieval_notes,
            top_results=results_list,
            warning_message=warning_message,
            thread_id=thread_id,
        )
        query_log_id = query_log.id
    except Exception as e:
        print(f"[QUERY LOG] Không thể lưu query log: {e}")
        await db.rollback()

    log_retrieval_trace_for_debug(retrieval_trace, enabled=debug)

    # --- Trả về phản hồi cuối cùng ---
    return SearchResponse(
        query=query,
        ai_insight=ai_insight,
        results=results_list,
        disclaimer=SEARCH_DISCLAIMER,
        query_log_id=query_log_id,
        retrieval_note=EMBEDDING_FALLBACK_RETRIEVAL_NOTE if retrieval_mode == "lexical_fallback" else None,
        ai_response=ai_response_text or None
    )
