import asyncio
import json
import os
import re

import numpy as np
from google import genai
from google.genai import types
from models import Food, Tag
from schemas import AIInsight, FoodResult, SearchResponse
from sqlalchemy import not_, select
from sqlalchemy.ext.asyncio import AsyncSession
from services.ingredient_key_service import (
    generate_filter_keys,
    has_any_ingredient_key,
    load_enabled_alias_override_rules,
)

# =====================================================================
# CẤU HÌNH KHỞI TẠO
# =====================================================================
PROJECT_ID = os.getenv("PROJECT_ID")
client = genai.Client(vertexai=True, project=PROJECT_ID, location="us-central1")


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

def collect_ingredient_priority_food_ids(
    foods: list[Food],
    include_keys: list[str],
) -> set:
    """
    Đánh dấu món khớp nguyên liệu user muốn.

    Nguyên liệu include không nên làm rớt sạch candidate an toàn. Thay vào đó,
    món khớp nguyên liệu sẽ được xếp trong nhóm ưu tiên khi lấy top kết quả.
    """
    if not include_keys:
        return set()

    matched_foods = [
        food for food in foods
        if _food_has_any_ingredient_key(food, include_keys)
    ]
    print(
        f"🧭 [INGREDIENT PRIORITY] Có {len(matched_foods)}/{len(foods)} món "
        f"khớp ingredient keys user muốn: {include_keys}"
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
    extracted_data = await asyncio.to_thread(supervisor_agent, user_input)
    if "error" in extracted_data:
        return None

    # Lấy thông tin trích xuất
    symptoms = [canonicalize_health_tag(tag) for tag in extracted_data.get("health_constraints", [])]
    user_include_dishes = extracted_data.get("include_dishes", [])
    user_exclude_dishes = extracted_data.get("exclude_dishes", [])

    user_likes_ings = set(extracted_data.get("include_ingredients", []))
    user_dislikes_ings = set(extracted_data.get("exclude_ingredients", []))

    user_include_tags = set(extracted_data.get("include_soft_tags", []))
    user_exclude_tags = set(extracted_data.get("exclude_soft_tags", []))

    # Khởi tạo tập hợp y khoa
    medical_exclude_tags = set()
    medical_prefer_tags = set()
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
            if tag.tag_type != "ALLERGY":
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

    return {
        "symptoms": symptoms,
        "final_exclude_ings": list(user_dislikes_ings.union(medical_exclude_ings)),
        "final_include_ings": list(safe_user_include_ings),
        "medical_exclude_tags": list(medical_exclude_tags),
        "medical_prefer_tags": list(medical_prefer_tags),
        "medical_prefer_ings": list(medical_prefer_ings),
        "user_include_tags": list(safe_user_include_tags),
        "user_exclude_tags": list(user_exclude_tags),
        "user_include_dishes": user_include_dishes,
        "user_exclude_dishes": user_exclude_dishes,
        "warning_message": warning_message
    }


# =====================================================================
# 3. POST-PROCESSING AGENT (Tư vấn ẩm thực tự nhiên với Dynamic Rule)
# =====================================================================

# Load file luật một lần khi khởi động server (tránh đọc file lặp lại mỗi request)
_ADVICE_RULES_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "standard-data", "generated-rules", "medical-advice-rules", "medical_advice_rules.json")
with open(_ADVICE_RULES_PATH, "r", encoding="utf-8") as _f:
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

async def search_food(query: str, db: AsyncSession) -> SearchResponse:
    """
    Luồng chạy chính để tìm kiếm món ăn:
    1. Trích xuất ý định (Supervisor Agent).
    2. Build Enriched Query.
    3. Lọc Database (SQL) bằng nguyên liệu cấm.
    4. Rerank kết quả bằng Vector Similarity + Tag Scoring.
    5. Post-Processing tạo phản hồi tư vấn tự nhiên.
    """
    
    # --- Bước 1: Chạy luồng bảo vệ và xử lý xung đột ---
    payload = await resolve_food_conflicts(query, db)

    if payload:
        print("\n" + "="*50)
        print("🎯 KẾT QUẢ TỪ AGENT & XỬ LÝ XUNG ĐỘT:")
        print(json.dumps(payload, ensure_ascii=False, indent=4))
        print("="*50 + "\n")
    else:
        print("❌ Payload trả về rỗng (Có lỗi từ LLM)")
    
    # Xử lý fallback nếu LLM báo lỗi
    if not payload:
        return SearchResponse(query=query, ai_insight=AIInsight(exclude=[], include=[], prefer=[]), results=[])
    
    # Bóc tách biến từ Payload
    user_exclude_dishes = payload["user_exclude_dishes"]
    symptoms = payload["symptoms"]
    final_e_ings = payload["final_exclude_ings"]
    final_p_ings = payload["final_include_ings"]
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
    include_ingredient_keys = generate_filter_keys(
        final_p_ings,
        extra_rules=alias_override_rules,
    )
    retrieval_notes: list[str] = []

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
    def get_embedding():
        return client.models.embed_content(
            model='gemini-embedding-001',
            contents=expanded_query,
            config=types.EmbedContentConfig(
                output_dimensionality=3072,
                task_type="RETRIEVAL_QUERY"  # Khớp với RETRIEVAL_DOCUMENT của món ăn
            )
        )
    
    embedding_response = await asyncio.to_thread(get_embedding)
    query_vector = embedding_response.embeddings[0].values

    # --- Bước 3: Bộ lọc CSDL (SQL Filter) ---
    # Lọc tập món ăn hợp lệ (loại exclude_ingredients + exclude_dishes)
    # Không dùng cosine_distance trong SQL — vector search sẽ thực hiện in-memory
    stmt = select(Food)

    if exclude_ingredient_keys:
        stmt = stmt.where(not_(Food.core_ingredient_keys.overlap(exclude_ingredient_keys)))

    if user_exclude_dishes:
        for dish in user_exclude_dishes:
            stmt = stmt.where(not_(Food.name.ilike(f"%{dish}%")))

    db_result = await db.execute(stmt)
    filtered_foods = db_result.scalars().all() # Tập món ăn sạch (Candidate)

    # Lọc mềm bằng Python cho dữ liệu cũ/chưa rebuild đủ core_ingredient_keys.
    if exclude_ingredient_keys:
        before_python_filter = len(filtered_foods)
        filtered_foods = [
            food for food in filtered_foods
            if not _food_has_any_ingredient_key(food, exclude_ingredient_keys)
        ]
        print(
            f"🛡️ [PYTHON INGREDIENT FILTER] Loại thêm "
            f"{before_python_filter - len(filtered_foods)} món bằng core_ingredient_keys: "
            f"{exclude_ingredient_keys}"
        )

    # Lọc ngữ cảnh (Context filter) 
    filtered_foods = apply_adaptive_context_include_filter(
        foods=filtered_foods,
        target_contexts=grouped_user_include_tags["meal_context"],
        field_name="meal_context",
        label="meal_context",
    )
    filtered_foods = apply_adaptive_context_include_filter(
        foods=filtered_foods,
        target_contexts=grouped_user_include_tags["occasion_context"],
        field_name="occasion_context",
        label="occasion_context",
    )
    filtered_foods = apply_adaptive_context_exclude_filter(
        foods=filtered_foods,
        target_contexts=grouped_user_exclude_tags["meal_context"],
        field_name="meal_context",
        label="meal_context",
    )
    filtered_foods = apply_adaptive_context_exclude_filter(
        foods=filtered_foods,
        target_contexts=grouped_user_exclude_tags["occasion_context"],
        field_name="occasion_context",
        label="occasion_context",
    )

    ingredient_priority_food_ids = collect_ingredient_priority_food_ids(
        foods=filtered_foods,
        include_keys=include_ingredient_keys,
    )
    if include_ingredient_keys and final_p_ings:
        requested_ingredients_text = ", ".join(final_p_ings)
        if ingredient_priority_food_ids:
            retrieval_notes.append(
                f"Các món khớp nguyên liệu người dùng muốn ({requested_ingredients_text}) "
                "đã được xếp ưu tiên trước; nếu chưa đủ top 5 thì bổ sung món an toàn khác."
            )
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

    # --- Bước 4: In-memory Vector Search trên tập đã lọc ---
    query_arr = np.array(query_vector, dtype=np.float32)
    query_norm = np.linalg.norm(query_arr)

    print(f"🔢 [BƯỚC 4 - COSINE + TAG RERANK] Tính điểm từng món:")
    scored = []
    
    for food in filtered_foods:
        if not food.embedding:
            print(f"  ⚠️  {food.name}: BỎ QUA (không có embedding)")
            continue

        food_arr = np.array(food.embedding.to_list(), dtype=np.float32)
        food_norm = np.linalg.norm(food_arr)
        if food_norm == 0 or query_norm == 0:
            print(f"  ⚠️  {food.name}: BỎ QUA (vector = 0)")
            continue
        
        # Cosine similarity = dot(a, b) / (||a|| * ||b||)
        similarity = float(np.dot(query_arr, food_arr) / (query_norm * food_norm))
        
        # Điều chỉnh điểm (Rerank) dựa trên Tag thưởng/phạt
        adjusted_similarity, score_details = calculate_tag_adjusted_similarity(
            food=food,
            base_similarity=similarity,
            user_prefer_tags=user_include_tags,
            medical_prefer_tags=medical_p_tags,
            user_avoid_tags=user_exclude_tags,
            medical_avoid_tags=medical_e_tags,
        )
        ingredient_priority_match = food.id in ingredient_priority_food_ids
        scored.append((food, adjusted_similarity, score_details, ingredient_priority_match))
        
        # In log chấm điểm
        priority_label = " [ưu tiên nguyên liệu]" if ingredient_priority_match else ""
        print(
            f"  📊 {food.name}{priority_label}: base {similarity*100:.2f}% "
            f"+{score_details['tag_bonus']*100:.1f} "
            f"-{score_details['tag_penalty']*100:.1f} "
            f"=> {adjusted_similarity*100:.2f}%"
        )
        if score_details["matched_prefer_tags"] or score_details["matched_avoid_tags"]:
            print(
                f"       prefer={score_details['matched_prefer_tags']} "
                f"avoid={score_details['matched_avoid_tags']}"
            )

    # Sắp xếp giảm dần theo điểm đã rerank, lấy top 5
    if ingredient_priority_food_ids:
        scored.sort(key=lambda x: (x[3], x[1]), reverse=True)
    else:
        scored.sort(key=lambda x: x[1], reverse=True)
    top5 = scored[:5]

    print(f"\n{'='*60}")
    print(f"🏆 [BƯỚC 5 - KẾT QUẢ CUỐI] Top {len(top5)} món phù hợp nhất:")
    for rank, (food, adjusted_similarity, score_details, ingredient_priority_match) in enumerate(top5, 1):
        priority_label = " [ưu tiên nguyên liệu]" if ingredient_priority_match else ""
        print(
            f"  #{rank} [{adjusted_similarity*100:.2f}%] {food.name}{priority_label} "
            f"(cosine {score_details['base_similarity']*100:.2f}%)"
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

    # --- Bước 7: Post-processing Agent (Dynamic Rule Injection) ---
    ai_response_text = await asyncio.to_thread(
        post_processing_agent,
        query,          # Câu hỏi gốc
        symptoms,       # Danh sách bệnh lý
        results_list,    # Top 5 FoodResult objects
        retrieval_notes,
    )

    # --- Trả về phản hồi cuối cùng ---
    return SearchResponse(
        query=query,
        ai_insight=AIInsight(
            exclude=medical_e_tags + final_e_ings,
            include=symptoms, # Trả về list bệnh lý để UI dễ hiển thị Warning
            prefer=medical_p_tags + final_p_ings + medical_p_ings,
            warning_message=warning_message
        ),
        results=results_list,
        ai_response=ai_response_text or None
    )
