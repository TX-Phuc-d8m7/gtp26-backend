"""
Script chuẩn hóa soft_tags, nguyên liệu và mô tả cho TỪNG MÓN ĂN (Single Mode)
bằng LLM (Gemini 2.5 Flash) với JSON Schema mode và Chain-of-Thought.

Chạy: python3 scripts/relabel_single.py [--pilot N] [--start N]
"""

import argparse
import json
import os
import random
import re
import sys
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

PROJECT_ID = os.getenv("PROJECT_ID")
client = genai.Client(vertexai=True, project=PROJECT_ID, location="us-central1")
MODEL_ID = 'gemini-2.5-flash'

# =====================================================================
# DANH SÁCH SOFT TAGS HỢP LỆ
# =====================================================================
VALID_SOFT_TAGS = [
    # Vị chủ đạo
    "Đậm đà", "Thanh đạm", "Chua", "Cay", "Mặn", "Ngọt", "Đắng", "Béo ngậy",
    # Nhiệt độ & cảm giác
    "Nóng hổi", "Thanh mát/Giải nhiệt", "Món lạnh",
    # Kết cấu
    "Giòn / Giòn rụm", "Dai / Sần sật", "Mềm", "Sống/Chín tái",
    # Dạng món
    "Món nước", "Món khô", "Nước sền sệt",
    # Phương pháp chế biến
    "Chiên / Rán", "Nướng", "Hấp / Luộc", "Xào",
    "Gỏi / Nộm / Trộn", "Cuốn / Gói", "Hầm / Ninh",
    "Lẩu", "Kho/Rim", "Súp", "Cháo", "Rang",
    # [NHÓM ĐỊA PHƯƠNG & DANH MỤC — Gán đúng xuất xứ]
    "Đặc sản Đà Nẵng", "Ẩm thực đường phố", "Món Việt truyền thống",
    "Món Á", "Món Âu", "Thức ăn nhanh", "Món chay", "Hải sản",
    "Ăn sáng", "Ăn trưa", "Ăn tối", "Ăn chiều / xế", "Ăn khuya", 
    "Ăn no", "Ăn vặt", "Mồi nhậu", "Tráng miệng",
    "Giải rượu", "Giải cảm", "Ấm bụng",
    # Dinh dưỡng
    "Giàu chất xơ", "Giàu đạm", "Giàu vitamin", "Giàu tinh bột",
    "Nội tạng", "Từ sữa / Phô mai", "Thực phẩm chế biến sẵn", "Bánh ngọt",
    # Tiêu hoá
    "Dễ tiêu", "Khó tiêu / Nặng bụng", "Healthy / Eat Clean", "Nhiều dầu mỡ / Calo cao",
]

TASTE_TAGS = {"Đậm đà", "Thanh đạm", "Chua", "Cay", "Mặn", "Ngọt", "Đắng", "Béo ngậy"}
FORM_TAGS = {"Món nước", "Món khô", "Nước sền sệt"}
METHOD_TAGS = {
    "Chiên / Rán", "Nướng", "Hấp / Luộc", "Xào", "Gỏi / Nộm / Trộn", "Cuốn / Gói",
    "Hầm / Ninh", "Lẩu", "Kho/Rim", "Súp", "Cháo", "Rang"
}
MEAL_TIME_TAGS = {"Ăn sáng", "Ăn trưa", "Ăn tối", "Ăn chiều / xế", "Ăn khuya"}
OCCASION_TAGS = {"Ăn no", "Ăn vặt", "Mồi nhậu", "Tráng miệng", "Giải rượu", "Giải cảm", "Ấm bụng"}
CATEGORY_LIKE_TAGS = TASTE_TAGS | MEAL_TIME_TAGS | OCCASION_TAGS

SWEET_DISH_KEYWORDS = ["chè", "kẹo", "bánh ngọt", "bánh kem", "kem", "flan", "mousse", "panna cotta", "rau câu", "bingsu", "brownie", "macaron", "tiramisu", "cheesecake", "lava", "waffle"]
SALTY_DISH_KEYWORDS = ["mắm", "khô", "muối", "kho quẹt", "chao", "muối tiêu", "dưa muối", "cá khô", "mực khô", "ruốc"]
SOUR_DISH_KEYWORDS = ["chua", "canh chua", "lẩu thái", "gỏi", "nộm", "trộn", "kim chi", "sốt me", "rang me", "om sấu", "mẻ"]
SOUR_CORE_KEYWORDS = ["me", "sấu", "mẻ", "giấm", "dấm", "măng chua", "kim chi", "dưa muối", "tôm chua"]
SPICY_DISH_KEYWORDS = ["cay", "mì cay", "lẩu thái", "sa tế", "bún bò huế", "cà ri", "gà rán sốt cay", "sốt cay"]
SPICY_CORE_KEYWORDS = ["sa tế", "tương ớt", "gochujang", "ớt bột", "dầu ớt", "ớt khô", "ớt hiểm", "gia vị lẩu thái"]
BITTER_CORE_KEYWORDS = ["khổ qua", "mướp đắng", "ngải cứu", "lá đắng"]
RICH_CORE_KEYWORDS = ["mỡ", "ba chỉ", "da heo", "da gà", "da vịt", "bơ", "phô mai", "cheese", "kem", "whipping cream", "nước cốt dừa", "mayonnaise", "mayo", "sữa đặc", "sữa tươi", "cá hồi"]
PROTEIN_CORE_KEYWORDS = [
    "thịt", "heo", "lợn", "bò", "gà", "vịt", "ngan", "ếch", "cá", "tôm", "cua",
    "mực", "bạch tuộc", "ốc", "nghêu", "ngao", "sò", "hến", "lươn", "trứng",
    "đậu hũ", "đậu hủ", "đậu phụ", "tàu hủ", "đậu nành", "tofu", "chả", "giò",
    "nem", "lòng", "gan", "tim", "mề"
]
SEAFOOD_CORE_KEYWORDS = ["tôm", "tôm tít", "bề bề", "cua", "ghẹ", "cá", "mực", "bạch tuộc", "ốc", "nghêu", "ngao", "sò", "hến", "vi cá"]
NOODLE_DISH_KEYWORDS = ["mì quảng", "mỳ quảng", "bún", "phở", "hủ tiếu", "miến", "bánh canh", "mì nước"]
CRUNCHY_MAIN_NAME_KEYWORDS = ["chiên giòn", "rán giòn", "xào giòn", "giòn", "ram", "chả giò", "bánh xèo"]
CHEWY_MAIN_INGREDIENT_KEYWORDS = ["gân", "sụn", "mực", "bạch tuộc", "ốc", "lòng", "bao tử", "dạ dày", "da heo", "da bò"]
GENERIC_CORE_INGREDIENTS = {"nước", "nước lọc", "nước chan", "nước dùng", "gia vị", "gia vị cơ bản"}
DAIRY_NAME_KEYWORDS = ["phô mai", "sữa chua", "yaourt", "kem", "flan", "panna cotta", "mousse", "bingsu", "cheesecake"]
DAIRY_INGREDIENT_KEYWORDS = ["sữa tươi", "sữa đặc", "sữa chua", "whipping cream", "cream cheese", "phô mai", "bơ lạt", "bơ nhạt"]

TAG_PRIORITY = [
    "Đậm đà", "Thanh đạm", "Chua", "Cay", "Mặn", "Ngọt", "Đắng", "Béo ngậy",
    "Món nước", "Món khô", "Nước sền sệt",
    "Chiên / Rán", "Nướng", "Hấp / Luộc", "Xào", "Gỏi / Nộm / Trộn", "Cuốn / Gói",
    "Hầm / Ninh", "Lẩu", "Kho/Rim", "Súp", "Cháo", "Rang",
    "Hải sản", "Nội tạng", "Từ sữa / Phô mai", "Thực phẩm chế biến sẵn", "Bánh ngọt",
    "Giàu chất xơ", "Giàu đạm", "Giàu vitamin", "Giàu tinh bột",
    "Dễ tiêu", "Khó tiêu / Nặng bụng", "Healthy / Eat Clean", "Nhiều dầu mỡ / Calo cao",
    "Nóng hổi", "Thanh mát/Giải nhiệt", "Món lạnh",
    "Giòn / Giòn rụm", "Dai / Sần sật", "Mềm", "Sống/Chín tái",
    "Đặc sản Đà Nẵng", "Ẩm thực đường phố", "Món Việt truyền thống", "Món Á", "Món Âu",
    "Thức ăn nhanh", "Món chay",
    "Ăn sáng", "Ăn trưa", "Ăn tối", "Ăn chiều / xế", "Ăn khuya", "Ăn no", "Ăn vặt",
    "Mồi nhậu", "Tráng miệng", "Giải rượu", "Giải cảm", "Ấm bụng",
]

TAG_PRIORITY_INDEX = {tag: i for i, tag in enumerate(TAG_PRIORITY)}

OFFAL_KEYWORDS = ["gan", "lòng", "mề", "óc", "tim", "cật", "dồi", "ruột", "bao tử", "dạ dày", "phèo", "huyết", "tiết", "pín"]
DANANG_KEYWORDS = ["mì quảng", "mỳ quảng", "bún chả cá", "bún mắm nêm", "bánh tráng cuốn thịt heo", "nem lụi", "mít non trộn", "ốc hút", "gỏi cá nam ô", "tré", "bánh đập", "cao lầu"]
VIETNAMESE_KEYWORDS = ["phở", "bún", "miến", "hủ tiếu", "cơm", "canh", "kho", "gỏi cuốn", "bánh mì", "xôi", "cháo", "lẩu", "mì quảng", "mỳ quảng"]
ASIAN_KEYWORDS = [
    "hàn quốc", "nhật", "thái", "trung quốc", "bibimbap", "teriyaki", "miso",
    "kim chi", "gochujang", "gyudon", "tonkatsu", "omurice", "udon", "indomie",
    "tokbokki", "topokki", "tteokbokki", "hải nam"
]
WESTERN_KEYWORDS = ["pizza", "pasta", "mì ý", "spaghetti", "steak", "burger", "sandwich", "cheesecake", "panna cotta", "mousse"]

# Heuristic dictionary: minh bạch hóa rủi ro ẩn từ nguyên liệu
INGREDIENT_RISK_TAG_MAP = {
    "Khó tiêu / Nặng bụng": [
        "thịt vịt", "vịt", "thịt ngan", "ngan", "nội tạng", "gân", "sụn", "da gà", "da vịt"
    ],
    "Béo ngậy": [
        "mỡ heo", "mỡ lợn", "bơ", "phô mai", "sốt phô mai", "kem tươi", "whipping cream",
        "nước cốt dừa", "thịt ba chỉ", "da heo"
    ],
    "Đắng": [
        "ngải cứu", "khổ qua", "mướp đắng", "lá đắng"
    ],
}

def apply_ingredient_risk_heuristics(tags: set[str], ingredient_text: str) -> list[str]:
    logs = []
    for risk_tag, keywords in INGREDIENT_RISK_TAG_MAP.items():
        if any(kw in ingredient_text for kw in keywords) and risk_tag not in tags:
            tags.add(risk_tag)
            logs.append(f"Thêm '{risk_tag}' (heuristic ingredient map)")
    return logs

def dedupe_keep_order(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result

def add_tag(tags: list[str], tag: str, logs: list[str], reason: str):
    if tag in VALID_SOFT_TAGS and tag not in tags:
        tags.append(tag)
        logs.append(f"Thêm '{tag}' ({reason})")

def remove_tag(tags: list[str], tag: str, logs: list[str] | None = None, reason: str = ""):
    if tag in tags:
        tags.remove(tag)
        if logs is not None:
            logs.append(f"Xóa '{tag}' ({reason})" if reason else f"Xóa '{tag}'")

def has_any(text: str, keywords: list[str]) -> bool:
    return any(kw in text for kw in keywords)

def has_phrase(text: str, keywords: list[str]) -> bool:
    return any(re.search(rf'(?<!\w){re.escape(kw)}(?!\w)', text) for kw in keywords)

def has_offal_signal(ingredient_text: str) -> bool:
    sanitized = re.sub(r'\blòng\s+(đỏ|trắng)\b', '', ingredient_text)
    return has_phrase(sanitized, OFFAL_KEYWORDS)

def has_seafood_signal(ingredient_text: str) -> bool:
    sanitized = re.sub(r'\bnước\s+dùng\s+cá(\s+khô)?\b', '', ingredient_text)
    sanitized = re.sub(r'\bnước\s+mắm\b', '', sanitized)
    return has_phrase(sanitized, SEAFOOD_CORE_KEYWORDS)

def clean_core_ingredients(core_ingredients: list[str]) -> list[str]:
    cleaned = []
    for ingredient in core_ingredients or []:
        normalized = " ".join(str(ingredient).strip().lower().split())
        if not normalized or normalized in GENERIC_CORE_INGREDIENTS:
            continue
        cleaned.append(str(ingredient).strip())
    return dedupe_keep_order(cleaned)

def has_category_signal(text: str, keywords: list[str]) -> bool:
    return has_any(text, keywords)

def is_dessert_like(name_lower: str, tags: list[str]) -> bool:
    return bool({"Tráng miệng", "Bánh ngọt", "Từ sữa / Phô mai"} & set(tags)) or has_category_signal(name_lower, SWEET_DISH_KEYWORDS)

def is_main_meal_like(name_lower: str, tags: list[str]) -> bool:
    main_meal_words = ["cơm", "bún", "phở", "miến", "hủ tiếu", "mì", "lẩu", "cháo", "bánh canh", "bánh mì", "xôi", "kho", "xào", "nướng"]
    return "Ăn no" in tags or has_category_signal(name_lower, main_meal_words)

def is_snack_like(name_lower: str, tags: list[str]) -> bool:
    snack_words = ["bánh tráng", "bánh rán", "khoai tây chiên", "ốc", "chè", "kem", "bánh ngọt", "bánh xèo", "gỏi", "nộm"]
    return "Tráng miệng" in tags or has_category_signal(name_lower, snack_words)

def is_late_night_like(name_lower: str, tags: list[str]) -> bool:
    late_words = ["cháo", "súp", "phở", "hủ tiếu", "mì nước", "miến"]
    heavy_tags = {"Chiên / Rán", "Nướng", "Nhiều dầu mỡ / Calo cao", "Khó tiêu / Nặng bụng"}
    return has_category_signal(name_lower, late_words) and not bool(heavy_tags & set(tags))

def choose_form_tag(food_name: str, full_text: str, current_tags: list[str]) -> str:
    name_lower = food_name.lower()

    if has_any(name_lower, ["trộn", "xào", "cơm", "xôi", "bánh mì", "bánh mỳ", "pizza", "salad", "gỏi", "nộm", "cuốn", "nướng", "chiên", "rán"]):
        return "Món khô"
    if has_any(name_lower, ["mì quảng", "mỳ quảng", "cao lầu", "cà ri", "kho", "rim", "sốt", "sauce", "cháo", "súp", "soup"]):
        return "Nước sền sệt"
    if has_any(name_lower, ["canh", "phở", "bún bò", "bún riêu", "bún mắm", "bún chả cá", "hủ tiếu", "miến nước", "mì nước", "lẩu", "bánh canh"]):
        return "Món nước"

    for tag in current_tags:
        if tag in FORM_TAGS:
            return tag

    if has_any(full_text, ["nước dùng", "nước lèo", "chan nước", "nước hầm", "nước lẩu"]):
        return "Món nước"
    if has_any(full_text, ["nước sốt", "sốt sệt", "sánh", "sền sệt"]):
        return "Nước sền sệt"
    return "Món khô"

def infer_method_tags(food_name: str, full_text: str) -> list[str]:
    name_lower = food_name.lower()
    checks = [
        ("Lẩu", ["lẩu"]),
        ("Cháo", ["cháo"]),
        ("Súp", ["súp", "soup"]),
        ("Chiên / Rán", ["chiên", "rán", "deep fry", "fry"]),
        ("Nướng", ["nướng", "áp chảo", "grill", "bbq"]),
        ("Hấp / Luộc", ["hấp", "luộc", "trụng", "chần"]),
        ("Xào", ["xào", "đảo chảo"]),
        ("Gỏi / Nộm / Trộn", ["gỏi", "nộm", "trộn", "salad"]),
        ("Cuốn / Gói", ["cuốn", "gói"]),
        ("Kho/Rim", ["kho", "rim", "om"]),
        ("Rang", ["rang"]),
        ("Hầm / Ninh", ["hầm", "ninh", "nước dùng", "nước hầm"]),
    ]

    inferred = []
    for tag, keywords in checks:
        if has_any(name_lower, keywords) or has_any(full_text, keywords):
            inferred.append(tag)
    return inferred[:2]

def ensure_one_form_tag(tags: list[str], food_name: str, full_text: str, logs: list[str]):
    chosen = choose_form_tag(food_name, full_text, tags)
    for tag in list(tags):
        if tag in FORM_TAGS and tag != chosen:
            remove_tag(tags, tag, logs, f"chỉ giữ một tag dạng món: {chosen}")
    add_tag(tags, chosen, logs, "bổ sung dạng món bắt buộc")

def ensure_method_tag(tags: list[str], food_name: str, full_text: str, logs: list[str]):
    if METHOD_TAGS.intersection(tags):
        return
    inferred = infer_method_tags(food_name, full_text)
    if inferred:
        add_tag(tags, inferred[0], logs, "bổ sung phương pháp chế biến bắt buộc")
    else:
        add_tag(tags, "Gỏi / Nộm / Trộn" if "salad" in food_name.lower() else "Hấp / Luộc", logs, "fallback phương pháp chế biến")

def correct_primary_method_tag(tags: list[str], food_name: str, raw_instructions: str, logs: list[str]):
    name_lower = food_name.lower()
    first_step = re.split(r'[\n.]', (raw_instructions or "").lower(), maxsplit=1)[0]

    preferred = None
    if has_any(name_lower, ["rang"]) or " rang" in f" {first_step}":
        preferred = "Rang"
    elif has_any(name_lower, ["kho", "rim"]) or has_any(first_step, [" kho ", " rim "]):
        preferred = "Kho/Rim"
    elif has_any(name_lower, ["lẩu"]):
        preferred = "Lẩu"
    elif has_any(name_lower, ["cháo"]):
        preferred = "Cháo"
    elif re.search(r'\b(súp|soup)\b', name_lower):
        preferred = "Súp"

    if not preferred:
        return

    for tag in list(tags):
        if tag in METHOD_TAGS and tag != preferred:
            remove_tag(tags, tag, logs, f"phương pháp chính là {preferred}")
    add_tag(tags, preferred, logs, "sửa phương pháp chế biến chính")

def ensure_taste_tag(tags: list[str], full_text: str, logs: list[str]):
    if TASTE_TAGS.intersection(tags):
        return
    if has_any(full_text, ["khổ qua", "mướp đắng", "ngải cứu"]):
        add_tag(tags, "Đắng", logs, "bổ sung vị chủ đạo")
    elif has_any(full_text, ["me", "sấu", "mẻ", "giấm", "dấm", "kim chi", "chua"]):
        add_tag(tags, "Chua", logs, "bổ sung vị chủ đạo")
    elif has_any(full_text, ["ớt", "sa tế", "gochujang", "cay"]):
        add_tag(tags, "Cay", logs, "bổ sung vị chủ đạo")
    elif has_any(full_text, ["chè", "kem", "bánh ngọt", "kẹo", "flan"]):
        add_tag(tags, "Ngọt", logs, "bổ sung vị chủ đạo")
    else:
        add_tag(tags, "Đậm đà", logs, "bổ sung vị chủ đạo mặc định")

def prune_tags(tags: list[str], max_tags: int = 8) -> list[str]:
    essential = []
    for group in (TASTE_TAGS, FORM_TAGS, METHOD_TAGS):
        group_tags = [tag for tag in tags if tag in group]
        first = min(group_tags, key=lambda tag: TAG_PRIORITY_INDEX.get(tag, len(TAG_PRIORITY_INDEX))) if group_tags else None
        if first:
            essential.append(first)

    ordered = sorted(
        dedupe_keep_order(tags),
        key=lambda tag: TAG_PRIORITY_INDEX.get(tag, len(TAG_PRIORITY_INDEX)),
    )

    result = dedupe_keep_order(essential)
    for tag in ordered:
        if tag not in result:
            result.append(tag)
        if len(result) >= max_tags:
            break
    return result

def correct_texture_tags(tags: list[str], name_lower: str, ingred_text: str, logs: list[str]):
    is_noodle_dish = has_any(name_lower, NOODLE_DISH_KEYWORDS)
    if is_noodle_dish and "Giòn / Giòn rụm" in tags and not has_any(name_lower, CRUNCHY_MAIN_NAME_KEYWORDS):
        remove_tag(tags, "Giòn / Giòn rụm", logs, "kết cấu giòn chỉ đến từ topping/đồ ăn kèm")
    if is_noodle_dish and "Dai / Sần sật" in tags and not has_any(ingred_text, CHEWY_MAIN_INGREDIENT_KEYWORDS):
        remove_tag(tags, "Dai / Sần sật", logs, "độ dai của sợi mì/bún không phải đặc trưng chính")

def ensure_protein_tag(tags: list[str], name_lower: str, ingred_text: str, logs: list[str]):
    has_protein = has_phrase(ingred_text, PROTEIN_CORE_KEYWORDS)
    if "Giàu đạm" in tags:
        if is_dessert_like(name_lower, tags) or not has_protein:
            remove_tag(tags, "Giàu đạm", logs, "không thấy nguồn đạm chính rõ ràng")
        return
    if has_protein and not is_dessert_like(name_lower, tags):
        add_tag(tags, "Giàu đạm", logs, "nguyên liệu chính có nguồn đạm rõ")

# =====================================================================
# SYSTEM PROMPT
# =====================================================================
SYSTEM_PROMPT = f"""Bạn là chuyên gia ẩm thực Việt Nam có nhiều năm kinh nghiệm, đồng thời là chuyên gia dinh dưỡng và là FOOD BLOGGER. Dựa trên Tên và Nguyên liệu (ingredients) và cách làm (instructions) hãy dán nhãn soft_tags CHÍNH XÁC cho những món ăn sau, viết mô tả và chuẩn hoá dữ liệu cho danh sách món ăn sau.

    [DANH MỤC TAG HỢP LỆ]
    - Soft Filters: {", ".join(VALID_SOFT_TAGS)}

    ═══════════════════════════════════════════════
    PHẦN 1: QUY TẮC BÓC TÁCH VÀ MÔ TẢ MÓN ĂN
    ═══════════════════════════════════════════════

    [QUY TẮC PHÂN LOẠI NGUYÊN LIỆU - BẮT BUỘC LÀM THEO 4 BƯỚC]
    Dữ liệu đầu vào có 2 danh sách:
    - raw_ingredients: nguyên liệu nguyên bản có định lượng/đơn vị, chỉ dùng để hiểu công thức và hiển thị lại.
    - ingredients: nguyên liệu đã chuẩn hóa sơ bộ, dùng làm nguồn chính để tạo core_ingredients/search/filter.

    Bạn phải chạy logic thuật toán sau trong đầu để chia nguyên liệu:

    - BƯỚC 1 (Chuẩn hoá Data gốc): Lấy mảng "ingredients" ban đầu ra. RÚT GỌN các tên còn nhiễu về dạng Root Noun nếu cần (VD: "bì sữa tươi không đường" -> "sữa tươi không đường", "500g thịt bò xắt lát" -> "thịt bò"). Ta gọi đây là [Mảng Nguyên Liệu Chuẩn].

    - BƯỚC 2 (Xác định Preprocessing - Chất khử mùi/Ngâm xả): Đọc kỹ "instructions". Tìm các hành động "rửa", "ngâm", "chà xát", "chần", "khử mùi". Rút trích các nguyên liệu đi kèm MÀ SAU ĐÓ BỊ RỬA TRÔI/ĐỔ BỎ (Ví dụ: sữa tươi ngâm gan rồi rửa, chanh để chà cá, muối xát gà, rượu chần thịt). Đưa chúng vào "preprocessing_ingredients". 
    🚨 LƯU Ý: Tuyệt đối KHÔNG đưa nguyên liệu thịt/cá/rau (như gan, ếch, bò...) vào mảng này.

    - BƯỚC 3 (Xác định Core - Nguyên liệu cấu thành): Lấy toàn bộ mảng "ingredients", CỘNG THÊM các gia vị/nguyên liệu được nhắc đến trong "instructions" (nếu có). Sau đó ĐỐI CHIẾU VÀ LOẠI BỎ hoàn toàn những nguyên liệu đã bị phân vào "preprocessing_ingredients" ở Bước 2.
        + Nếu một chất (VD: muối, rượu) CHỈ xuất hiện ở hành động sơ chế (Bước 2) -> Xoá nó khỏi Core.
        + TRƯỜNG HỢP ĐA NHIỆM: Nếu một chất (VD: muối) VỪA được dùng để ngâm rửa, VỪA được dùng để tẩm ướp/nấu nước sốt -> Giữ nguyên nó ở Core, VÀ cho phép nó xuất hiện ở cả Preprocessing.        
    - BƯỚC 4 (Kỷ luật chống ảo giác): Tự kiểm tra lại 2 mảng vừa tạo. TUYỆT ĐỐI CHỈ DÙNG những nguyên liệu thực sự xuất hiện trong văn bản gốc ("ingredients" và "instructions"). KHÔNG ĐƯỢC TỰ SUY DIỄN, không được bịa ra nguyên liệu không có trong bài (Ví dụ: Bài không ghi dầu ăn thì không được tự thêm dầu ăn vào).

    [QUY TẮC CHUẨN HOÁ QUAN TRỌNG]
    1. Dữ liệu gốc: Trường "name" giữ nguyên nội dung 100%, trường "raw_ingredients" và "ingredients" không được tự ý sửa trong output.
    2. Chuẩn hoá tên: Tên nguyên liệu phải được đưa về dạng Root Noun (VD: "500g thịt bò xắt lát" -> "thịt bò", "1/2 muỗng muối" -> "muối").

    [QUY TẮC VIẾT MÔ TẢ]
    "description": Hãy viết một đoạn văn từ 3-5 câu miêu tả trải nghiệm ăn uống dựa TRÊN CƠ SỞ danh sách nguyên liệu (ingredients) được cung cấp.
    [YÊU CẦU PHONG CÁCH]:
        - Tự nhiên như bài review, gợi cảm xúc.
        - Tập trung vào Khứu giác, Vị giác và Cảm giác (ấm bụng, bùng nổ vị giác, đưa cơm...).
        - Sử dụng từ ngữ đời thường mà người dùng hay dùng khi mô tả mong muốn tìm kiếm.

    [QUY TẮC CỐT LÕI (GROUNDING)]:
    1. Tuyệt đối chỉ suy luận từ "ingredients" được cung cấp. Không tự ý thêm nguyên liệu ngoài danh sách vào mô tả hay dán nhãn.
    2. Không biến topping/đồ ăn kèm phụ thành trải nghiệm chính trong description, vì description còn dùng cho tìm kiếm ngữ nghĩa.
    3. BẮT BUỘC VỚI NHÃN "Nội tạng": NẾU trong nguyên liệu (ingredients) CÓ CHỨA các thành phần như gan, lòng, mề, óc, tim, cật, dồi, ruột, bao tử, dạ dày, huyết/tiết (của heo, bò, gà...) thì BẠN BẮT BUỘC PHẢI THÊM TAG "Nội tạng" vào mảng "soft_tags".

    ═══════════════════════════════════════════════
    PHẦN 2: QUY TẮC BẮT BUỘC — ĐỌC KỸ TRƯỚC KHI GÁN NHÃN SOFT_TAGS
    ═══════════════════════════════════════════════

    [NHÓM VỊ — YÊU CẦU PHÂN TÍCH TOÀN DIỆN]
    🚨 QUY TẮC CỐT LÕI: TUYỆT ĐỐI KHÔNG DÁN NHÃN THEO KIỂU "TỪ KHÓA NGUYÊN LIỆU". Bạn BẮT BUỘC phải kết hợp đọc TÊN MÓN + NGUYÊN LIỆU + CÁCH LÀM để hiểu TỔNG THỂ BẢN CHẤT món ăn. Đường, muối, chanh, ớt đa phần chỉ là gia vị cân bằng. Chỉ gán nhãn vị giác khi đó là VỊ ĐẶC TRƯNG CHỦ ĐẠO, là thứ đầu tiên người ăn cảm nhận được.

    • "Đậm đà": Đây là nhãn dành cho các món có nước sốt sánh, vị mặn ngọt hài hoà, đậm đà, bám đều lên nguyên liệu (VD: Thịt kho tàu, Bò kho, Vịt kho gừng, Sườn rim mặn ngọt, Gà kho gừng, Thỏ kho tộ, Lòng xào dưa, Cá kho tộ, Vịt rim me, Vịt om sấu).
    • "Thanh đạm": Món ăn nhẹ nhàng, ít gia vị, ít dầu mỡ, giữ vị nguyên bản của nguyên liệu chính (VD: Gà luộc, canh rau ngót, cháo trắng).
    • "Mặn": Chỉ gán cho các món ĐẶC TRƯNG LÀ RẤT MẶN, mang tính chất "ăn dè" (VD: Mắm ruốc, cá khô, kho quẹt, dưa cải muối). TUYỆT ĐỐI KHÔNG gán "Mặn" cho món ăn bình thường chỉ vì có nêm "muối" hay "nước mắm".
    • "Ngọt": Mang bản chất là ĐỒ NGỌT (VD: Chè, tráng miệng, bánh ngọt, kẹo). TUYỆT ĐỐI KHÔNG gán "Ngọt" cho các món ăn mặn (như sườn xào chua ngọt, thịt heo quay) dù trong công thức có ướp nhiều "đường" hay "mật ong".
    • "Chua": Vị chua phải là LINH HỒN CỦA MÓN ĂN (VD: Canh chua cá lóc, lẩu mẻ, gỏi ngó sen). TUYỆT ĐỐI KHÔNG gán "Chua" nếu chanh/giấm/tắc chỉ là gia vị vắt thêm ăn kèm.
    • "Cay": Vị cay là ĐIỂM NHẤN THỐNG TRỊ (VD: Mì cay, lẩu Thái, mực nướng sa tế). KHÔNG gán "Cay" chỉ vì trong công thức có "1 trái ớt" dùng để trang trí hoặc tạo chút vị.
    • "Béo ngậy": Cảm giác béo tràn ngập khoang miệng (VD: Các món nấu nước cốt dừa, lẩu phô mai, xốt bơ tỏi).
    • "Đắng": Vị đắng là đặc trưng cốt lõi (VD: Canh khổ qua/mướp đắng, gà hầm ngải cứu).

    [NHÓM PHƯƠNG PHÁP — Gán theo cách CHẾ BIẾN CHÍNH]
    • Chọn 1 phương pháp chính phù hợp nhất
    • Một số món có thể có 2 phương pháp (VD: "Hầm / Ninh" + "Món nước")
    • "Hấp / Luộc": Chế biến bằng hơi nước hoặc nước sôi (hải sản hấp, rau luộc, gà luộc, bánh bao hấp). ĐẶC BIỆT chú ý các món có từ "hấp", "luộc" trong tên.
    • "Nướng": Chế biến bằng nhiệt trực tiếp (thịt nướng, cá nướng, sườn nướng). ĐẶC BIỆT chú ý các món có từ "nướng" trong tên.
    • "Chiên / Rán": Làm chín bằng dầu/mỡ (cá chiên, chả giò rán, bánh xèo).
    • "Xào": Đảo nhanh với ít dầu (rau xào, mì xào, bò xào).
    • "Kho/Rim": Nấu lửa nhỏ với gia vị mặn ngọt cho keo lại (thịt kho, cá kho, tôm rim).
    • "Lẩu": Món nước ăn nóng trực tiếp trên bếp (lẩu thái, lẩu hải sản).
    • "Cuốn / Gói": Các món dùng bánh tráng, lá để cuộn nguyên liệu (gỏi cuốn, phở cuốn, chả giò sống).
    • "Rang": Rang khô không dầu hoặc ít dầu (lạc rang, tôm rang, cơm rang khô).
    • "Gỏi / Nộm / Trộn": Trộn lạnh, gỏi sống/sơ chế, hoặc các món bún/phở trộn.
    • PHÂN BIỆT ĐỊNH NGHĨA: 
    - "Hầm / Ninh": Nấu lửa nhỏ thời gian dài để lấy nước ngọt (thường áp dụng cho nước dùng Phở, Bún, Lẩu).
    - "Súp": Món có độ sệt cao (súp cua, súp lươn) hoặc súp kiểu Âu. TUYỆT ĐỐI KHÔNG gán "Súp" cho các món Bún, Phở, Hủ tiếu, Mì truyền thống của Việt Nam.
    - "Cháo": Gạo nấu nát.

    [NHÓM DẠNG MÓN — BẮT BUỘC gán 1 trong 3]
    • "Món nước": Chan ngập nước dùng lỏng/trong (Phở, Bún nước, Hủ tiếu, Canh...).
    • "Món khô": Không có nước dùng, hoặc dạng TRỘN/CHẤM với mắm lỏng/nước tương (Cơm, Bánh mì, Đồ nướng, Bún trộn, Bún thịt nướng, Bún mắm nêm). TUYỆT ĐỐI KHÔNG gán "Nước sền sệt" cho món trộn mắm lỏng.
    • "Nước sền sệt": Nước sốt/nước lèo đặc sệt, keo lại, chan xăm xắp (Kho tàu, Cà ri, Mì Quảng, Cao lầu). ⚠️ QUY TẮC ĐẶC BIỆT: Các biến thể của Mì Quảng, Cao Lầu BẮT BUỘC gán "Nước sền sệt" hoặc "Món khô".

    [NHÓM DỊP & CHỨC NĂNG]
    • "Ăn vặt": Bánh, snack, đồ ăn nhẹ
    • "Tráng miệng": Chè, bánh ngọt, trái cây
    • "Mồi nhậu": Đồ nhắm bia/rượu
    • "Ấm bụng": Cháo, súp ấm nóng cho người bệnh/se lạnh

    [NHÓM DINH DƯỠNG — Chỉ gán khi rõ ràng]
    • "Giàu đạm": Thịt, cá, trứng là thành phần chính
    • "Giàu tinh bột": Cơm, bún, phở, bánh mì, xôi, bánh bao là thành phần chính
    • "Giàu chất xơ": Nhiều rau củ, đậu.
    • "Nội tạng": Có gan, lòng, tim, thận, dồi...
    • "Từ sữa / Phô mai": Có sữa, phô mai, yogurt là nguyên liệu chính

    [NHÓM KẾT CẤU — CHỈ dựa trên THÀNH PHẦN CHÍNH, KHÔNG tính đồ ăn kèm]
        ⚠️ QUY TẮC QUAN TRỌNG: Kết cấu phải là đặc trưng của CHÍNH MÓN ĂN, không phải của topping/đồ ăn kèm phụ.
        • "Giòn / Giòn rụm":
        - GÁN: Đồ chiên giòn (chả giò, gà rán, bánh xèo), bánh quy, đồ nướng giòn mà CHÍNH MÓN là giòn
        - KHÔNG GÁN: Mì Quảng, Bún, Phở chỉ vì có "bánh tráng nướng", "đậu phộng" ăn kèm
        - KHÔNG GÁN: Các món nước (bún, phở, mì) chỉ vì có topping giòn

        • "Dai / Sần sật":
        - GÁN: Thành phần CHÍNH và ĐẶC TRƯNG là dai một cách NỔI BẬT — bò gân, bò gân nấu, mực khô, sụn heo, gân heo, ốc, phá lấu dai
        - KHÔNG GÁN: Mì Quảng, Bún, Phở, Hủ tiếu — sợi mì/bún có độ dai bình thường không phải đặc trưng NỔI BẬT
        - KHÔNG GÁN: Nếu "dai" không phải là lý do người ta chọn hay đặc tả món đó

        • "Mềm":
        - GÁN: Kết cấu mềm là ĐẶC TRƯNG — cháo, bánh bao, đậu phụ mềm, trứng hấp
        - GÁN: Thịt hầm nhừ, cá kho mềm

        • "Sống/Chín tái":
        - GÁN: Thịt/cá sống hoặc chín tái (gỏi sống, sashimi, nem chua sống, bò tái)
        - KHÔNG GÁN: Rau sống ăn kèm không tính là "Sống / Chín tái"
    
    [NHÓM NĂNG LƯỢNG & ĐẶC TÍNH]
    • "Healthy / Eat Clean": Gán cho món luộc/hấp, nhiều rau, gạo lứt, ức gà.
    • "Nhiều dầu mỡ / Calo cao": Gán cho đồ chiên ngập dầu, phô mai, thịt mỡ.
    • "Hải sản": Bắt buộc gán nếu có tôm, cua, cá, mực, ốc...

    [NHÓM THỜI ĐIỂM BỮA ĂN — BẮT BUỘC TUÂN THỦ]
    • "Ăn sáng": Ưu tiên món nhanh gọn, dễ tiêu (Bún, phở, miến, xôi, bánh mì, cháo).
    • "Ăn trưa" & "Ăn tối" ("Ăn no"): Dành cho món kèm cơm trắng (thịt kho, canh, xào), hoặc món no lâu (Lẩu, Nướng, Cơm tấm).
    • "Ăn vặt" / "Ăn chiều / xế": Món ăn chơi, chua/ngọt, không làm no ngang (Chè, bánh tráng trộn, ốc).
    • "Ăn khuya": Ấm bụng, dễ tiêu (Cháo, súp, mì gõ). TUYỆT ĐỐI KHÔNG gắn cho món nặng bụng như Cơm nếp, Bánh chưng.

    [NHÓM DANH MỤC & ĐỊA PHƯƠNG]
    • "Đặc sản Đà Nẵng": Gán cho các món đặc trưng Đà Nẵng/Quảng Nam: Mì Quảng, Bún chả cá, Bún mắm nêm, Bánh tráng cuốn thịt heo, Cao lầu, Mỳ Quảng, Cơm gà, Bánh xèo miền Trung, Bê thui...
    • "Ẩm thực đường phố": Món thường bán ở hàng quán vỉa hè, xe đẩy, chợ, quán nhỏ
    • "Món Việt truyền thống": Phở, bún bò, cơm tấm, bánh mì, canh, kho, các món thuần Việt phổ biến
    • KHÔNG gán "Món Á", "Món Âu" cho các món Việt Nam thuần túy
    • NỘI TẠNG: Nếu nguyên liệu có gan, lòng, mề, óc, tim, cật, dồi, ruột, bao tử, huyết -> BẮT BUỘC gắn "Nội tạng".

    [QUY TẮC SỐ LƯỢNG]
    • Tối thiểu 3 tags, tối đa 8 tags cho soft_tags (chỉ giữ những tag phù hợp với món nhất, không phù hợp TUYỆT ĐỐI KHÔNG đưa vào)
    • BẮT BUỘC có ít nhất: 1 tag Vị + 1 tag Dạng món + 1 tag Phương pháp
    • Nếu món phù hợp nhiều bữa ăn thì có thể gán đủ tất cả các tag bữa ăn đó

    [YÊU CẦU ĐẦU RA]
    Trả về chính xác mảng JSON tuân thủ tuyệt đối cấu trúc Schema đã được định nghĩa.
    """

# SCHEMA CHỈ TRẢ VỀ OBJECT CHO 1 MÓN
ITEM_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "core_ingredients": {"type": "ARRAY", "items": {"type": "STRING"}},
        "preprocessing_ingredients": {"type": "ARRAY", "items": {"type": "STRING"}},
        "soft_tags": {
            "type": "ARRAY",
            "items": {"type": "STRING", "enum": VALID_SOFT_TAGS},
            "minItems": 3,
            "maxItems": 8,
        },
        "description": {"type": "STRING"},
        "reasoning": {"type": "STRING", "description": "Giải thích ngắn gọn tại sao chọn các tags này"}
    },
    "required": ["core_ingredients", "preprocessing_ingredients", "soft_tags", "description", "reasoning"]
}

# =====================================================================
# HÀM HẬU XỬ LÝ PYTHON (POST-PROCESSING)
# =====================================================================
def post_process_tags(food_name, raw_ingredients_list, raw_instructions, ai_tags):
    tags = [tag for tag in dedupe_keep_order(ai_tags or []) if tag in VALID_SOFT_TAGS]
    logs = []

    name_lower = food_name.lower()
    ingred_text = " ".join(raw_ingredients_list).lower()
    full_text = f"{name_lower} {ingred_text} {(raw_instructions or '').lower()}"

    heuristic_tags = set(tags)
    logs.extend(apply_ingredient_risk_heuristics(heuristic_tags, ingred_text))
    for tag in TAG_PRIORITY:
        if tag in heuristic_tags and tag not in tags:
            tags.append(tag)

    # --- 1. HARD-MAPPING (Thêm tag bắt buộc) ---
    has_offal = has_offal_signal(ingred_text)
    if has_offal and "Nội tạng" not in tags:
        tags.append("Nội tạng")
        logs.append("Thêm 'Nội tạng'")
    elif not has_offal and "Nội tạng" in tags:
        remove_tag(tags, "Nội tạng")

    has_seafood = has_seafood_signal(ingred_text)
    if has_seafood and "Hải sản" not in tags:
        add_tag(tags, "Hải sản", logs, "nguyên liệu chính có hải sản")
    elif not has_seafood and "Hải sản" in tags:
        remove_tag(tags, "Hải sản", logs, "không thấy hải sản trong ingredients")

    if any(kw in name_lower for kw in DANANG_KEYWORDS) and "Đặc sản Đà Nẵng" not in tags:
        tags.append("Đặc sản Đà Nẵng")
        logs.append("Thêm 'Đặc sản Đà Nẵng'")
    elif "Đặc sản Đà Nẵng" in tags and not any(kw in name_lower for kw in DANANG_KEYWORDS):
        remove_tag(tags, "Đặc sản Đà Nẵng", logs, "không khớp danh sách đặc sản Đà Nẵng")

    if has_any(name_lower, ASIAN_KEYWORDS):
        add_tag(tags, "Món Á", logs, "nhận diện nhóm món Á")
        remove_tag(tags, "Món Việt truyền thống", logs, "món không phải Việt thuần túy")
    elif has_any(name_lower, WESTERN_KEYWORDS):
        add_tag(tags, "Món Âu", logs, "nhận diện nhóm món Âu")
        remove_tag(tags, "Món Việt truyền thống", logs, "món không phải Việt thuần túy")
    elif has_any(name_lower, VIETNAMESE_KEYWORDS):
        add_tag(tags, "Món Việt truyền thống", logs, "nhận diện món Việt")
        remove_tag(tags, "Món Á", logs, "không gán Món Á cho món Việt thuần túy")

    if any(kw in name_lower for kw in ["mì quảng", "mỳ quảng", "cao lầu"]):
        remove_tag(tags, "Món nước", logs, "Mì Quảng/Cao lầu không phải món nước ngập")
        if "Món khô" not in tags:
            add_tag(tags, "Nước sền sệt", logs, "Mì Quảng/Cao lầu có nước chan xăm xắp")

    if "cháo" in name_lower:
        add_tag(tags, "Cháo", logs, "nhận diện từ tên món")
        remove_tag(tags, "Món nước", logs, "cháo được xếp dạng nước sền sệt")
        add_tag(tags, "Nước sền sệt", logs, "bổ sung dạng món cho cháo")
    elif re.search(r'\b(súp|soup)\b', name_lower):
        add_tag(tags, "Súp", logs, "nhận diện từ tên món")
        remove_tag(tags, "Món nước", logs, "súp được xếp dạng nước sền sệt")
        add_tag(tags, "Nước sền sệt", logs, "bổ sung dạng món cho súp")

    if re.search(r'\b(bánh mì|bánh mỳ)\b', name_lower):
        add_tag(tags, "Món khô", logs, "bánh mì là món khô")
        add_tag(tags, "Giòn / Giòn rụm", logs, "kết cấu đặc trưng của bánh mì")
        remove_tag(tags, "Món nước", logs, "bánh mì không phải món nước")
    elif re.search(r'\b(xôi)\b', name_lower):
        add_tag(tags, "Món khô", logs, "xôi là món khô")
        add_tag(tags, "Mềm", logs, "kết cấu đặc trưng của xôi")
        remove_tag(tags, "Món nước", logs, "xôi không phải món nước")

    if re.search(r'\b(cơm|canh|xào|kho)\b', name_lower):
        add_tag(tags, "Ăn trưa", logs, "phù hợp bữa chính")
        add_tag(tags, "Ăn tối", logs, "phù hợp bữa chính")

    if has_phrase(name_lower, DAIRY_NAME_KEYWORDS) or has_phrase(ingred_text, DAIRY_INGREDIENT_KEYWORDS):
        add_tag(tags, "Từ sữa / Phô mai", logs, "có sữa/phô mai/kem")
        add_tag(tags, "Béo ngậy", logs, "có sữa/phô mai/kem")
        if re.search(r'\b(kem|flan|panna cotta|mousse|rau câu|bingsu|chè|bánh|cheesecake)\b', name_lower):
            add_tag(tags, "Tráng miệng", logs, "nhận diện món tráng miệng")

    # --- 2. KIỂM SOÁT VỊ GIÁC (Chống AI ảo giác theo gia vị) ---
    if "Ngọt" in tags:
        if not is_dessert_like(name_lower, tags):
            remove_tag(tags, "Ngọt")
            logs.append("Xóa 'Ngọt' (Chỉ có đường nêm nếm)")

    if "Mặn" in tags:
        if not has_category_signal(name_lower, SALTY_DISH_KEYWORDS):
            remove_tag(tags, "Mặn")
            if not (TASTE_TAGS & set(tags)):
                add_tag(tags, "Đậm đà", logs, "dùng thay cho vị mặn nêm nếm thông thường")
            logs.append("Xóa 'Mặn' (muối/nước mắm chỉ là gia vị cân bằng)")

    if "Chua" in tags:
        has_sour_identity = has_category_signal(name_lower, SOUR_DISH_KEYWORDS)
        has_sour_core = has_category_signal(name_lower + " " + ingred_text, SOUR_CORE_KEYWORDS)
        if not (has_sour_identity or has_sour_core):
            remove_tag(tags, "Chua")
            logs.append("Xóa 'Chua' (Chanh/tắc chỉ là gia vị ăn kèm)")

    if "Cay" in tags:
        has_spicy_identity = has_category_signal(name_lower, SPICY_DISH_KEYWORDS)
        has_spicy_core = has_category_signal(name_lower + " " + ingred_text, SPICY_CORE_KEYWORDS)
        if not (has_spicy_identity or has_spicy_core):
            remove_tag(tags, "Cay", logs, "ớt/tiêu chỉ là gia vị phụ")

    if "Đắng" in tags:
        if not has_category_signal(name_lower + " " + ingred_text, BITTER_CORE_KEYWORDS):
            remove_tag(tags, "Đắng", logs, "không có nguyên liệu đắng làm vị chủ đạo")

    if "Béo ngậy" in tags:
        has_rich_core = has_category_signal(name_lower + " " + ingred_text, RICH_CORE_KEYWORDS)
        if not (has_rich_core or {"Chiên / Rán", "Từ sữa / Phô mai", "Bánh ngọt"} & set(tags)):
            remove_tag(tags, "Béo ngậy", logs, "không có nguyên liệu/cách chế biến tạo cảm giác béo ngậy rõ")

    # --- 3. MUTUALLY EXCLUSIVE (Loại trừ mâu thuẫn) ---
    if {"Chiên / Rán", "Nhiều dầu mỡ / Calo cao"} & set(tags):
        for t in ["Thanh đạm", "Healthy / Eat Clean"]:
            if t in tags:
                remove_tag(tags, t)
                logs.append(f"Xóa '{t}' (Trái ngược đồ chiên xào)")

    if {"Tráng miệng", "Bánh ngọt", "Ngọt"} & set(tags):
        for t in ["Giàu đạm", "Nội tạng", "Mồi nhậu"]:
            if t in tags:
                remove_tag(tags, t)

    # --- 4. KIỂM SOÁT TAG DỊP/BỮA ĂN (tránh làm loãng soft_tags) ---
    if "Tráng miệng" in tags and not is_dessert_like(name_lower, tags):
        remove_tag(tags, "Tráng miệng", logs, "không phải món ngọt/tráng miệng rõ ràng")

    if "Mồi nhậu" in tags and not has_category_signal(name_lower, ["ốc", "nướng", "lòng", "khô", "gỏi", "nem chua", "bê thui", "mực", "ram", "chả"]):
        remove_tag(tags, "Mồi nhậu", logs, "không phải đồ nhắm rõ ràng")

    if "Ăn khuya" in tags and not is_late_night_like(name_lower, tags):
        remove_tag(tags, "Ăn khuya", logs, "không phù hợp ăn khuya")

    if "Ăn vặt" in tags and is_main_meal_like(name_lower, tags) and not is_snack_like(name_lower, tags):
        remove_tag(tags, "Ăn vặt", logs, "món chính, không phải ăn vặt")

    if "Ăn no" in tags and is_dessert_like(name_lower, tags):
        remove_tag(tags, "Ăn no", logs, "món tráng miệng không nên là ăn no")

    if "Ăn sáng" in tags and {"Chiên / Rán", "Nướng", "Mồi nhậu", "Tráng miệng"} & set(tags):
        if not has_category_signal(name_lower, ["bánh mì", "xôi", "phở", "bún", "cháo", "mì", "hủ tiếu"]):
            remove_tag(tags, "Ăn sáng", logs, "không phải món sáng điển hình")

    correct_primary_method_tag(tags, food_name, raw_instructions, logs)
    correct_texture_tags(tags, name_lower, ingred_text, logs)
    ensure_protein_tag(tags, name_lower, ingred_text, logs)

    ensure_one_form_tag(tags, food_name, full_text, logs)
    ensure_method_tag(tags, food_name, full_text, logs)
    ensure_taste_tag(tags, full_text, logs)

    pruned = prune_tags(tags, max_tags=8)
    if len(dedupe_keep_order(tags)) > len(pruned):
        logs.append(f"Cắt còn {len(pruned)} tags quan trọng nhất")

    return pruned, logs

def print_diff(old_tags: list, new_tags: list):
    old_set = set(old_tags)
    new_set = set(new_tags)
    added = new_set - old_set
    removed = old_set - new_set

    if not added and not removed:
        print(f"  ≡  Không thay đổi tags")
    if added:
        print(f"  ✅ Thêm: {sorted(added)}")
    if removed:
        print(f"  ❌ Bỏ:   {sorted(removed)}")

# =====================================================================
# VÒNG LẶP CHÍNH
# =====================================================================
async def main():
    parser = argparse.ArgumentParser(description="Tách nguyên liệu, dán nhãn (Chế độ Single)")
    parser.add_argument("--input", default="raw_foods_input.json", help="File dữ liệu món ăn đầu vào")
    parser.add_argument("--output", default="raw_foods_enriched(beta_v2).json", help="File lưu kết quả relabel")
    parser.add_argument("--pilot", type=int, default=0, help="Chỉ chạy N món đầu")
    parser.add_argument("--start", type=int, default=0, help="Bắt đầu từ index N")
    parser.add_argument("--delay", type=int, default=3, help="Thời gian chờ giữa các món")
    parser.add_argument("--sample", type=int, default=0, help="Chạy N món ngẫu nhiên từ toàn bộ input")
    parser.add_argument("--seed", type=int, default=42, help="Seed cho chế độ sample")
    parser.add_argument("--force", action="store_true", help="Ghi lại output từ đầu thay vì resume")
    parser.add_argument("--error-delay", type=int, default=10, help="Thời gian chờ sau mỗi lỗi")
    args = parser.parse_args()

    input_file = args.input
    output_file = args.output

    try:
        with open(input_file, "r", encoding="utf-8") as f:
            foods = json.load(f)
    except FileNotFoundError:
        print(f"❌ Lỗi: Không tìm thấy file {input_file}")
        sys.exit(1)

    relabeled = []
    if args.force and os.path.exists(output_file):
        print(f"♻️  --force được bật. Ghi lại {output_file} từ đầu.")
    elif os.path.exists(output_file):
        try:
            with open(output_file, "r", encoding="utf-8") as f:
                relabeled = json.load(f)
            print(f"📂 Đã tìm thấy {output_file}. Đang có {len(relabeled)} món.")
        except json.JSONDecodeError:
            print(f"⚠️ File lỗi định dạng JSON. Bắt đầu lại từ đầu.")

    if args.sample > 0:
        sample_size = min(args.sample, len(foods))
        rng = random.Random(args.seed)
        foods_to_process = rng.sample(list(enumerate(foods)), sample_size)
        run_label = f"SAMPLE MODE — {sample_size}/{len(foods)} món, seed={args.seed}"
    else:
        start_idx = max(args.start, len(relabeled))
        end_idx = args.pilot if args.pilot > 0 else len(foods)
        foods_to_process = list(enumerate(foods[start_idx:end_idx], start_idx))
        run_label = f"SINGLE MODE — Bắt đầu từ: {start_idx}"

    print(f"\n{'='*60}")
    print(f"🏷️  PIPELINE XỬ LÝ ({run_label})")
    print(f"{'='*60}\n")

    if not foods_to_process:
        print("✅ Đã hoàn tất xử lý mọi món ăn. Kết thúc.")
        sys.exit(0)

    for global_idx, item in foods_to_process:
        food_name = item.get("name", "Không rõ tên")
        display_ingredients = item.get("raw_ingredients") or item.get("ingredients", [])
        normalized_ingredients = item.get("ingredients", [])
        raw_instructions = item.get("instructions", "")
        old_tags = item.get("soft_tags", [])

        print(f"[{global_idx}] {food_name}")
        
        # Prompt build cho 1 món
        prompt_content = f"""
Tên món: {food_name}
Nguyên liệu nguyên bản có định lượng (raw_ingredients): {", ".join(display_ingredients)}
Nguyên liệu đã chuẩn hóa sơ bộ dùng cho search/filter (ingredients): {", ".join(normalized_ingredients)}
Cách làm: {raw_instructions}
"""
        try:
            response = client.models.generate_content(
                model=MODEL_ID,
                contents=[prompt_content],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT, 
                    temperature=0.1,
                    response_mime_type="application/json",
                    response_schema=ITEM_SCHEMA
                )
            )
            
            res = json.loads(response.text)
            
            # Post processing
            cleaned_tags, autofix_logs = post_process_tags(food_name, normalized_ingredients, raw_instructions, res.get("soft_tags", []))
            cleaned_core_ingredients = clean_core_ingredients(res.get("core_ingredients", []))
            cleaned_preprocessing_ingredients = clean_core_ingredients(res.get("preprocessing_ingredients", []))

            # In logs
            if autofix_logs:
                print(f"  🔧 Auto-Fix: {'; '.join(autofix_logs)}")
            print_diff(old_tags, cleaned_tags)
            print(f"  💬 LLM Reasoning: {res.get('reasoning', '')}")

            # Lưu vào danh sách
            enriched_item = {
                "name": food_name,
                "description": res.get("description", ""),
                "core_ingredients": cleaned_core_ingredients,
                "preprocessing_ingredients": cleaned_preprocessing_ingredients,
                "soft_tags": cleaned_tags,
                "raw_ingredients": display_ingredients,
                "ingredients": normalized_ingredients,
                "raw_instructions": raw_instructions
            }
            if args.sample > 0:
                enriched_item["source_index"] = global_idx
            relabeled.append(enriched_item)

            # Ghi đè file
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(relabeled, f, ensure_ascii=False, indent=2)

            time.sleep(args.delay) 

        except Exception as e:
            print(f"  ❌ Lỗi: {str(e)}")
            time.sleep(args.error_delay)
        
        print("-" * 50)

    print(f"\n✅ HOÀN TẤT PIPELINE! Kết quả tại: {output_file}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
