"""
Tách các tag ngữ cảnh ra khỏi soft_tags sau relabel bằng Heuristic hoặc LLM (Google GenAI SDK - Chế độ Batch).

Ví dụ:
venv/bin/python scripts/split_food_categories.py \
  --input 'standard-data/ingredients-data/raw_foods_enriched_labeled(final_488).json' \
  --output 'standard-data/ingredients-data/raw_foods_enriched_labeled(final_488).categorized.json' \
  --use-llm \
  --batch-size 10
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

TASTE_TAGS = {
    "Đậm đà", "Thanh đạm", "Chua", "Cay",
    "Mặn", "Ngọt", "Đắng", "Béo ngậy",
}

MEAL_CONTEXT_TAGS = {
    "Ăn sáng", "Ăn trưa", "Ăn tối", "Ăn chiều / xế", "Ăn khuya",
}

OCCASION_CONTEXT_TAGS = {
    "Ăn no", "Ăn vặt", "Mồi nhậu", "Tráng miệng",
    "Giải rượu", "Giải cảm", "Ấm bụng",
}

DEFAULT_INPUT = Path("standard-data/ingredients-data/raw_foods_enriched_labeled(final_488).json")
DEFAULT_OUTPUT = Path("standard-data/ingredients-data/raw_foods_enriched_labeled(final_488).categorized.json")
DEFAULT_LLM_MODEL = "gemini-2.5-flash"
DEFAULT_BATCH_SIZE = 10

# Đã cập nhật System Instruction để báo LLM xử lý danh sách
SYSTEM_INSTRUCTION = f"""Bạn là chuyên gia phân loại món ăn Việt Nam cho hệ thống đề xuất.
Nhiệm vụ của bạn: Xử lý MỘT DANH SÁCH các món ăn. Với mỗi món ăn, hãy SUY LUẬN `meal_context` và `occasion_context` phù hợp dựa trên tên món, mô tả, nguyên liệu, cách làm, soft_tags còn lại và heuristic_suggestion.

DANH SÁCH TAG HỢP LỆ:
1. MEAL_CONTEXT_TAGS: {sorted(MEAL_CONTEXT_TAGS)}
2. OCCASION_CONTEXT_TAGS: {sorted(OCCASION_CONTEXT_TAGS)}

QUY TẮC BẮT BUỘC:
- Chỉ trả về `meal_context` và `occasion_context`; KHÔNG phân loại taste_profile hay remaining_soft_tags.
- Hai trường này CHỈ được dùng các tag hợp lệ trong danh sách trên. Không tự bịa tag mới.
- `heuristic_suggestion` là gợi ý tham khảo. Nếu hợp lý, hãy dùng nó; nếu quá rộng hoặc sai ngữ cảnh, hãy chỉnh lại.
- Không gán quá rộng. Chỉ chọn bữa/ngữ cảnh CHÍNH, tự nhiên nhất với món.
- `meal_context` và `occasion_context` KHÔNG BẮT BUỘC. Nếu món khó xác định, không có bối cảnh rõ, hoặc gán tag sẽ gượng ép, hãy trả mảng rỗng [].
- `meal_context`: ưu tiên 1-2 tag. Chỉ dùng 3 tag nếu món thật sự phổ biến ở nhiều bữa chính. Hầu như KHÔNG dùng 4-5 tag.
- `occasion_context`: ưu tiên 0-1 tag chính. Chỉ dùng 2 tag khi hai ngữ cảnh đều rất rõ. Không dùng 3 tag trở lên.
- BẮT BUỘC trả về `id` nguyên gốc của từng món ăn để hệ thống map dữ liệu.

QUY TẮC MEAL_CONTEXT:
- [Ăn sáng]: chỉ gán cho món rất phổ biến buổi sáng như phở, bún nước, mì quảng, hủ tiếu, cháo, xôi, bánh mì, bánh cuốn, bánh bao.
- [Ăn trưa] và [Ăn tối]: gán cho món chính, món ăn với cơm, lẩu, nướng, xào/kho/canh, hoặc món mặn giàu đạm. Thường đi theo cặp ["Ăn trưa", "Ăn tối"].
- [Ăn chiều / xế]: gán cho snack, món ăn vặt, tráng miệng, món ăn chơi nhẹ. Không gán cho món chính chỉ vì có thể ăn lúc xế.
- [Ăn khuya]: chỉ gán cho cháo, súp, mì/hủ tiếu bán đêm, ốc, lẩu, món nhậu/ăn đêm rõ ràng. Không gán cho mọi món sáng hoặc mọi món hải sản.
- Nếu món là đồ nhắm như ốc, răng mực, mực nướng, chân gà, khô mực, hải sản rang/nướng/xào dạng nhắm: ưu tiên ["Ăn chiều / xế", "Ăn khuya"] hoặc ["Ăn tối", "Ăn khuya"] tùy món; KHÔNG gán cả 4 bữa.

QUY TẮC OCCASION_CONTEXT:
- [Ăn no]: CHỈ gán cho món có nền tảng là tinh bột khối lượng lớn hoặc món chính khẩu phần lớn (VD: cơm, bún, phở, mì, hủ tiếu, mì quảng, bánh canh, bánh mì kẹp, xôi, pizza, burger, poke bowl, lẩu).
- Không gán [Ăn no] chỉ vì món có thể ăn kèm cơm/bánh mì. Nếu bản chất món là đồ nhắm/ăn chơi, hãy bỏ [Ăn no].
- [Ăn vặt]: dành cho snack, món ăn chơi, đồ viên, bánh tráng, món nhỏ không phải bữa chính.
- [Mồi nhậu]: ưu tiên gán cho các món đặc thù uống bia/rượu (VD: ốc, răng mực, chân gà, sụn gà, khô mực, mực nướng, hải sản rang/nướng/xào dạng nhắm).
- [Ấm bụng]: dành cho cháo, súp, canh, hầm/ninh, món nước nóng có cảm giác làm ấm.
- [Tráng miệng]: dành cho chè, kem, bánh ngọt, trái cây tô, sữa chua ngọt, món ngọt/lạnh sau bữa ăn.
- XUNG ĐỘT [Ăn no] vs [Ăn vặt]: thường loại trừ lẫn nhau. Chỉ chọn bản chất chính.

QUY TẮC KẾT HỢP [Mồi nhậu] + [Ăn no] (CỰC KỲ QUAN TRỌNG):
1. ĐƯỢC PHÉP gán cả hai: NẾU VÀ CHỈ NẾU cấu trúc cốt lõi của món đó vốn dĩ là món ăn no/món chính nhưng thường phục vụ trên bàn nhậu (VD: Lẩu các loại, Cơm chiên, Mì/Miến xào, Gà nướng nguyên con kèm xôi, Bê thui cuốn bánh tráng).
2. NGHIÊM CẤM gán cả hai: Nếu món ăn bản chất là đồ nhắm/ăn chơi (ốc, răng mực, sụn gà, gỏi, mực khô). Những món này CẤM gán [Ăn no] dù mô tả có ghi "ăn cực tốn cơm" hay "ăn kèm bánh mì". Hệ thống sẽ đánh giá sai ý định tìm kiếm của người dùng.
"""

# Đã cập nhật Schema để trả về mảng kết quả
LLM_BATCH_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "results": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "INTEGER", "description": "ID của món ăn tương ứng trong request"},
                    "meal_context": {"type": "ARRAY", "items": {"type": "STRING", "enum": sorted(MEAL_CONTEXT_TAGS)}},
                    "occasion_context": {"type": "ARRAY", "items": {"type": "STRING", "enum": sorted(OCCASION_CONTEXT_TAGS)}},
                    "reasoning": {"type": "STRING", "description": "Giải thích ngắn gọn bằng tiếng Việt"}
                },
                "required": ["id", "meal_context", "occasion_context", "reasoning"]
            }
        }
    },
    "required": ["results"]
}


def dedupe_keep_order(values: Iterable[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result

def normalize_text(value: str) -> str:
    value = (value or "").lower()
    value = re.sub(r"[_\-/,.;:()\\[\\]{}]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()

def item_text(item: dict, remaining_soft_tags: list[str]) -> str:
    parts: list[str] = [
        item.get("name", ""),
        " ".join(item.get("core_ingredients", []) or []),
        " ".join(remaining_soft_tags),
    ]
    return normalize_text(" ".join(str(part) for part in parts if part))

def has_phrase(text: str, keywords: Iterable[str]) -> bool:
    for keyword in keywords:
        pattern = rf"(?<![a-z0-9_àáảãạâầấẩẫậăằắẳẵặèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]){re.escape(keyword)}(?![a-z0-9_àáảãạâầấẩẫậăằắẳẵặèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ])"
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False

def has_any(text: str, keywords: Iterable[str]) -> bool:
    return has_phrase(text, keywords)

def sort_context_tags(tags: Iterable[str], valid_tags: set[str]) -> list[str]:
    ordered_valid_tags = sorted(valid_tags)
    priority = {tag: idx for idx, tag in enumerate(ordered_valid_tags)}
    return sorted(
        dedupe_keep_order(tag for tag in tags if tag in valid_tags),
        key=lambda tag: priority.get(tag, len(priority)),
    )

def normalize_llm_categories(raw_value: Any, valid_tags: set[str]) -> list[str]:
    if not isinstance(raw_value, list):
        return []
    return sort_context_tags((str(v).strip() for v in raw_value if v), valid_tags)

def load_llm_client():
    try:
        from google import genai
        from dotenv import load_dotenv
    except ImportError as exc:
        raise RuntimeError("Thiếu dependency. Hãy chạy: pip install google-genai python-dotenv") from exc

    load_dotenv()
    project_id = os.getenv("PROJECT_ID")
    if not project_id:
        raise RuntimeError("Thiếu PROJECT_ID trong file .env để gọi Vertex AI.")
    
    return genai.Client(
        vertexai=True, 
        project=project_id, 
        location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    )


def infer_meal_context(text: str, remaining_soft_tags: list[str], occasion_context: list[str]) -> tuple[list[str], list[str]]:
    meals = set()
    notes = []

    if "Tráng miệng" in occasion_context or "Ăn vặt" in occasion_context:
        meals.add("Ăn chiều / xế")
        notes.append("snack/dessert context")

    snack_keywords = ["bánh tráng kẹp", "bánh tráng trộn", "bánh tráng cuốn", "kem", "sữa chua", "trái cây", "đồ viên", "nem chua", "ốc", "gỏi", "mít trộn", "phá lấu", "trứng vịt lộn", "trứng cút lộn", "bánh bèo", "bánh nậm", "bánh lọc", "bánh căn", "bánh xèo", "nem lụi", "tàu hũ", "sương sáo", "xiên que", "cá viên"]
    if has_any(text, snack_keywords):
        meals.add("Ăn chiều / xế")
        notes.append("afternoon-snack keyword")

    breakfast_keywords = ["bánh mì", "bánh mỳ", "xôi", "phở", "bún", "mì quảng", "mỳ quảng", "hủ tiếu", "cháo", "miến", "bánh cuốn", "bánh ướt", "bánh bao", "bánh canh", "mì nước", "bò né", "bánh mì chảo", "bánh đúc", "khoai lang", "sắn"]
    if has_any(text, breakfast_keywords):
        meals.add("Ăn sáng")
        notes.append("breakfast-friendly")

    main_meal_keywords = ["cơm", "canh", "kho", "rim", "xào", "nướng", "lẩu", "sườn", "mắm nêm", "mắm tôm", "thịt", "gà", "vịt", "cá", "tôm", "đậu hũ", "đậu hủ", "bò", "hải sản", "cua", "mực", "bê thui", "pizza", "bít tết", "beefsteak", "bbq", "spaghetti", "sushi", "bento"]
    if has_any(text, main_meal_keywords) or any(tag in remaining_soft_tags for tag in ["Món nước", "Món khô", "Nước sền sệt", "Giàu đạm"]):
        meals.add("Ăn trưa")
        meals.add("Ăn tối")
        notes.append("main-meal dish")
    
    late_night_keywords = ["cháo trắng", "cháo lòng", "cháo vịt", "mì gõ", "hủ tiếu gõ", "mì tôm", "súp cua", "đêm", "khuya", "ốc", "lẩu"]
    if has_any(text, late_night_keywords) or (has_any(text, ["bánh mì", "xôi", "hủ tiếu", "cháo"])) or "Mồi nhậu" in occasion_context:
        meals.add("Ăn khuya")
        notes.append("late-night/supper friendly")

    return sorted(list(meals)), notes


def infer_occasion_context(text: str, remaining_soft_tags: list[str]) -> tuple[list[str], list[str]]:
    notes: list[str] = []
    occasions: set[str] = set()

    if has_any(text, ["tía tô", "cháo hành", "giải cảm", "cảm cúm", "gừng", "nóng toát mồ hôi"]):
        notes.append("flu-relief signal")
        occasions.update(["Giải cảm", "Ấm bụng"])

    if has_any(text, ["giải rượu", "canh chua", "nước chanh", "nước ép", "trà gừng", "sắn dây"]):
        notes.append("hangover-relief signal")
        occasions.add("Giải rượu")

    if has_any(text, ["chè", "kem", "bánh ngọt", "bánh kem", "flan", "panna cotta", "mousse", "rau câu", "trái cây tô", "sữa chua", "yaourt", "bingsu", "tiramisu", "cheesecake", "xoa xoa"]) or any(tag in remaining_soft_tags for tag in ["Món lạnh", "Bánh ngọt"]):
        notes.append("dessert/cold sweet signal")
        occasions.add("Tráng miệng")

    if has_any(text, ["bánh tráng kẹp", "bánh tráng trộn", "đồ viên", "nem chua rán", "khoai tây chiên", "ăn vặt", "xiên que", "taco", "cuốn sốt", "da heo"]):
        notes.append("street-food/snack signal")
        occasions.add("Ăn vặt")

    if has_any(text, ["mồi nhậu", "nhậu", "chip chip", "ghẹ", "khô mực", "mực khô", "chân gà", "sụn", "lòng", "bao tử", "bê thui", "gỏi cá", "nướng ngói"]) or has_phrase(text, ["ốc"]):
        notes.append("drinking-food signal")
        occasions.add("Mồi nhậu")

    if has_any(text, ["cháo", "súp", "canh", "hầm", "ninh", "nóng hổi", "tiềm"]) or any(tag in remaining_soft_tags for tag in ["Món nước", "Cháo", "Súp", "Hầm / Ninh"]):
        notes.append("warm soup/stew signal")
        occasions.add("Ấm bụng")

    filling_keywords = ["cơm", "bún", "phở", "mì", "miến", "hủ tiếu", "xôi", "bánh mì", "pizza", "burger", "poke bowl", "lẩu", "tortilla", "mì quảng", "bánh canh"]
    if has_any(text, filling_keywords) or "Giàu tinh bột" in remaining_soft_tags or "Giàu đạm" in remaining_soft_tags:
        notes.append("filling starch/main dish signal")
        occasions.add("Ăn no")

    if ("salad" in text or "gỏi" in text) and "gỏi cá" not in text and not has_any(text, filling_keywords):
        notes.append("salad/light dish signal")
        occasions.add("Ăn vặt")

    return sorted(list(occasions)), notes

def is_filling_main_dish(text: str, remaining_soft_tags: list[str]) -> bool:
    main_dish_keywords = [
        "cơm", "bún", "phở", "mì quảng", "mỳ quảng", "mì", "miến", "hủ tiếu",
        "bánh canh", "bánh mì", "xôi", "lẩu", "pizza", "burger", "poke bowl",
        "bento", "spaghetti", "cơm chiên", "mì xào", "miến xào",
    ]
    return (
        has_any(text, main_dish_keywords)
        or "Giàu tinh bột" in remaining_soft_tags
        or "Lẩu" in remaining_soft_tags
    )


def is_noodle_or_rice_main(text: str, remaining_soft_tags: list[str]) -> bool:
    main_keywords = [
        "cơm", "bún", "phở", "mì", "miến", "hủ tiếu", "mì quảng", "mỳ quảng",
        "bánh canh", "xôi", "cháo",
    ]
    return has_any(text, main_keywords) or "Giàu tinh bột" in remaining_soft_tags


def is_soup_or_hotpot_main(text: str, remaining_soft_tags: list[str]) -> bool:
    soup_keywords = ["canh", "lẩu", "súp", "cháo", "nước lèo", "nước dùng"]
    return has_any(text, soup_keywords) or bool({"Món nước", "Lẩu", "Súp", "Cháo"}.intersection(remaining_soft_tags))


def is_seafood_grilled_snack(text: str, remaining_soft_tags: list[str]) -> bool:
    seafood_keywords = ["mực", "tôm", "cua", "ghẹ", "hàu", "sò", "ốc", "bạch tuộc", "nhum", "vẹm", "tu hài", "răng mực"]
    snack_methods = ["nướng", "rang", "xào", "hấp", "sốt", "sa tế", "mỡ hành", "bơ tỏi", "muối ớt"]
    return (
        ("Hải sản" in remaining_soft_tags or has_any(text, seafood_keywords))
        and has_any(text, snack_methods)
        and not is_noodle_or_rice_main(text, remaining_soft_tags)
        and "Lẩu" not in remaining_soft_tags
    )


def is_drinking_snack(text: str, remaining_soft_tags: list[str]) -> bool:
    drinking_keywords = [
        "mồi nhậu", "nhậu", "đồ nhắm", "mồi nhắm", "ốc", "răng mực",
        "khô mực", "mực khô", "mực nướng", "mực rang", "mực xào", "sụn gà",
        "chân gà", "bao tử", "lòng", "bê thui", "gỏi cá", "tôm rang",
        "tôm nướng", "cua rang", "ghẹ rang", "hải sản nướng", "hải sản rang",
    ]
    return has_any(text, drinking_keywords) or "Mồi nhậu" in remaining_soft_tags


def is_late_night_friendly(text: str, occasion_context: list[str]) -> bool:
    late_night_keywords = [
        "cháo", "súp", "mì gõ", "hủ tiếu gõ", "mì tôm", "ốc", "lẩu",
        "khuya", "đêm", "ăn đêm", "mồi nhậu", "nhậu",
    ]
    return has_any(text, late_night_keywords) or "Mồi nhậu" in occasion_context


def is_heavy_for_late_night(remaining_soft_tags: list[str], taste_profile: list[str]) -> bool:
    heavy_tags = {
        "Khó tiêu / Nặng bụng",
        "Nhiều dầu mỡ / Calo cao",
        "Chiên / Rán",
        "Thức ăn nhanh",
    }
    return bool(heavy_tags.intersection(remaining_soft_tags)) or "Béo ngậy" in taste_profile


def supports_drinking_context(identity_text: str, full_text: str, remaining_soft_tags: list[str]) -> bool:
    if is_noodle_or_rice_main(identity_text, remaining_soft_tags):
        return False
    if is_soup_or_hotpot_main(identity_text, remaining_soft_tags) and "Lẩu" not in remaining_soft_tags:
        return False

    drinking_table_main_keywords = [
        "lẩu", "bê thui", "cơm chiên", "mì xào", "miến xào", "gà nướng",
    ]
    return (
        is_drinking_snack(full_text, remaining_soft_tags)
        or has_any(identity_text, drinking_table_main_keywords)
    )


def post_process_contexts(
    item: dict,
    remaining_soft_tags: list[str],
    taste_profile: list[str],
    meal_context: list[str],
    occasion_context: list[str],
) -> tuple[list[str], list[str], list[str]]:
    notes: list[str] = []
    text = item_text(item, remaining_soft_tags)
    category_identity_text = normalize_text(
        " ".join([
            str(item.get("name", "")),
            " ".join(remaining_soft_tags),
        ])
    )

    meal = sort_context_tags(meal_context, MEAL_CONTEXT_TAGS)
    occasion = sort_context_tags(occasion_context, OCCASION_CONTEXT_TAGS)

    filling_main = is_filling_main_dish(category_identity_text, remaining_soft_tags)
    drinking_snack = is_drinking_snack(text, remaining_soft_tags)
    drinking_compatible = supports_drinking_context(category_identity_text, text, remaining_soft_tags)
    seafood_grilled_snack = is_seafood_grilled_snack(category_identity_text, remaining_soft_tags)
    late_night_friendly = is_late_night_friendly(text, occasion)

    if drinking_snack and "Mồi nhậu" not in occasion:
        occasion = sort_context_tags(occasion + ["Mồi nhậu"], OCCASION_CONTEXT_TAGS)
        notes.append("post_process: add Mồi nhậu for clear drinking/snack dish")

    if "Mồi nhậu" in occasion and not drinking_compatible:
        occasion = [tag for tag in occasion if tag != "Mồi nhậu"]
        notes.append("post_process: remove Mồi nhậu because dish has no drinking/snack signal")

    if "Mồi nhậu" in occasion and "Ăn no" in occasion and not filling_main:
        occasion = [tag for tag in occasion if tag != "Ăn no"]
        notes.append("post_process: remove Ăn no because Mồi nhậu dish is not a filling main dish")

    if "Mồi nhậu" in occasion and "Ăn no" in occasion and seafood_grilled_snack and "Lẩu" not in remaining_soft_tags:
        occasion = [tag for tag in occasion if tag != "Ăn no"]
        notes.append("post_process: remove Ăn no from grilled/seafood snack with Mồi nhậu")

    if "Ăn no" in occasion and "Ăn vặt" in occasion:
        if filling_main:
            occasion = [tag for tag in occasion if tag != "Ăn vặt"]
            notes.append("post_process: remove Ăn vặt because dish is primarily filling/main")
        else:
            occasion = [tag for tag in occasion if tag != "Ăn no"]
            notes.append("post_process: remove Ăn no because dish is primarily snack/light")

    if "Ăn khuya" in meal and is_heavy_for_late_night(remaining_soft_tags, taste_profile) and not late_night_friendly:
        meal = [tag for tag in meal if tag != "Ăn khuya"]
        notes.append("post_process: remove Ăn khuya for heavy/greasy dish without late-night signal")

    if drinking_snack:
        preferred_meal = [tag for tag in ["Ăn chiều / xế", "Ăn khuya", "Ăn tối"] if tag in meal]
        if len(meal) > 2 and preferred_meal:
            meal = preferred_meal[:2]
            notes.append("post_process: cap drinking/snack meal_context to two strongest contexts")
    elif len(meal) > 3:
        if "Ăn sáng" in meal and {"Ăn trưa", "Ăn tối"}.issubset(meal) and filling_main:
            meal = [tag for tag in ["Ăn sáng", "Ăn trưa", "Ăn tối"] if tag in meal]
            notes.append("post_process: cap all-day main dish meal_context to breakfast/lunch/dinner")
        elif {"Ăn trưa", "Ăn tối"}.issubset(meal):
            meal = ["Ăn trưa", "Ăn tối"]
            notes.append("post_process: cap meal_context to lunch/dinner for main dish")
        else:
            meal = meal[:3]
            notes.append("post_process: cap meal_context to three tags")

    if len(occasion) > 2:
        priority = ["Mồi nhậu", "Ăn no", "Tráng miệng", "Ăn vặt", "Ấm bụng", "Giải cảm", "Giải rượu"]
        occasion = [tag for tag in priority if tag in occasion][:2]
        notes.append("post_process: cap occasion_context to two strongest tags")

    return (
        sort_context_tags(meal, MEAL_CONTEXT_TAGS),
        sort_context_tags(occasion, OCCASION_CONTEXT_TAGS),
        notes,
    )


def process_items_batch(
    batch_items: list[dict],
    include_review_metadata: bool,
    llm_client: Any | None = None,
    llm_model: str = DEFAULT_LLM_MODEL,
) -> list[dict]:
    # Bước 1: Tính toán Heuristic cho toàn bộ batch
    prepared_data = []
    for idx, item in enumerate(batch_items):
        original_tags = dedupe_keep_order(item.get("soft_tags", []) or [])
        
        existing_taste = [tag for tag in original_tags if tag in TASTE_TAGS]
        existing_meal = [tag for tag in original_tags if tag in MEAL_CONTEXT_TAGS]
        existing_occ = [tag for tag in original_tags if tag in OCCASION_CONTEXT_TAGS]

        remaining_h = [tag for tag in original_tags if tag not in TASTE_TAGS and tag not in MEAL_CONTEXT_TAGS and tag not in OCCASION_CONTEXT_TAGS]

        text = item_text(item, remaining_h)
        h_occ, occ_notes = infer_occasion_context(text, remaining_h)
        h_meal, meal_notes = infer_meal_context(text, remaining_h, sort_context_tags(existing_occ + h_occ, OCCASION_CONTEXT_TAGS))

        prepared_data.append({
            "id": idx,
            "original_item": item,
            "original_tags": original_tags,
            "existing_taste": existing_taste,
            "existing_meal": existing_meal,
            "existing_occ": existing_occ,
            "h_meal": h_meal,
            "h_occ": h_occ,
            "remaining_h": remaining_h,
            "meal_notes": meal_notes,
            "occ_notes": occ_notes
        })

    # Bước 2: Gọi LLM cho cả Batch
    llm_results_map = {}
    llm_error = None

    if llm_client is not None:
        try:
            from google.genai import types

            # Tạo payload chỉ chứa thông tin cần thiết
            llm_payload = []
            for d in prepared_data:
                llm_payload.append({
                    "id": d["id"],
                    "name": d["original_item"].get("name", ""),
                    "description": d["original_item"].get("description", ""),
                    "raw_ingredients": d["original_item"].get("raw_ingredients", []) or [],
                    "core_ingredients": d["original_item"].get("core_ingredients", []),
                    "raw_instructions": d["original_item"].get("raw_instructions", "") or d["original_item"].get("instructions", ""),
                    "remaining_soft_tags": d["remaining_h"],
                    "heuristic_suggestion": {
                        "meal_context": d["h_meal"],
                        "occasion_context": d["h_occ"],
                    },
                })
            
            user_input = json.dumps(llm_payload, ensure_ascii=False, indent=2)

            response = llm_client.models.generate_content(
                model=llm_model,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.2,
                    response_mime_type="application/json",
                    response_schema=LLM_BATCH_SCHEMA
                ),
                contents=user_input
            )
            
            res_data = json.loads(response.text)
            # Map kết quả dựa trên id LLM trả về
            for res_item in res_data.get("results", []):
                llm_results_map[res_item["id"]] = res_item

        except Exception as exc:
            llm_error = str(exc)

    # Bước 3: Merge dữ liệu và gán fallback nếu LLM xót item hoặc lỗi
    categorized_batch = []
    
    for d in prepared_data:
        idx = d["id"]
        result = dict(d["original_item"])
        review_notes = []

        # Default fallback về heuristic
        final_taste = d["existing_taste"]
        final_meal = sort_context_tags(d["existing_meal"] + d["h_meal"], MEAL_CONTEXT_TAGS)
        final_occ = sort_context_tags(d["existing_occ"] + d["h_occ"], OCCASION_CONTEXT_TAGS)
        final_soft = d["remaining_h"]
        
        taste_source = "from_soft_tags" if final_taste else "missing"
        meal_source = "hybrid" if d["existing_meal"] and d["h_meal"] else "heuristic" if d["h_meal"] else "from_soft_tags" if d["existing_meal"] else "missing"
        occ_source = "hybrid" if d["existing_occ"] and d["h_occ"] else "heuristic" if d["h_occ"] else "from_soft_tags" if d["existing_occ"] else "missing"

        # Nếu item này có kết quả từ LLM
        if llm_results_map and idx in llm_results_map:
            llm_res = llm_results_map[idx]
            llm_meal = normalize_llm_categories(llm_res.get("meal_context", []), MEAL_CONTEXT_TAGS)
            llm_occ = normalize_llm_categories(llm_res.get("occasion_context", []), OCCASION_CONTEXT_TAGS)

            if llm_meal:
                final_meal = sort_context_tags(d["existing_meal"] + llm_meal, MEAL_CONTEXT_TAGS)
                meal_source = "hybrid_llm" if d["existing_meal"] else "llm"
            elif final_meal:
                meal_source = "hybrid" if d["existing_meal"] and d["h_meal"] else "heuristic" if d["h_meal"] else "from_soft_tags"
                review_notes.append("meal_llm_field_fallback: LLM returned empty meal_context")
            else:
                meal_source = "missing"
                review_notes.append("meal_llm_field_fallback: LLM returned empty meal_context and heuristic was empty")

            if llm_occ:
                final_occ = sort_context_tags(d["existing_occ"] + llm_occ, OCCASION_CONTEXT_TAGS)
                occ_source = "hybrid_llm" if d["existing_occ"] else "llm"
            elif final_occ:
                occ_source = "hybrid" if d["existing_occ"] and d["h_occ"] else "heuristic" if d["h_occ"] else "from_soft_tags"
                review_notes.append("occasion_llm_field_fallback: LLM returned empty occasion_context")
            else:
                occ_source = "missing"
                review_notes.append("occasion_llm_field_fallback: LLM returned empty occasion_context and heuristic was empty")

            review_notes.append(f"llm: {llm_res.get('reasoning', 'no reasoning')}")
            
        else:
            # Fallback
            review_notes.extend(f"meal_heuristic: {n}" for n in d["meal_notes"])
            review_notes.extend(f"occ_heuristic: {n}" for n in d["occ_notes"])
            if llm_client is not None:
                err_msg = llm_error if llm_error else "Item omitted in LLM batch response"
                review_notes.append(f"llm_fallback: {err_msg}")

        final_meal, final_occ, post_process_notes = post_process_contexts(
            item=d["original_item"],
            remaining_soft_tags=final_soft,
            taste_profile=final_taste,
            meal_context=final_meal,
            occasion_context=final_occ,
        )
        review_notes.extend(post_process_notes)

        result["taste_profile"] = final_taste
        result["meal_context"] = final_meal
        result["occasion_context"] = final_occ
        result["soft_tags"] = final_soft

        if include_review_metadata:
            result["category_review"] = {
                "taste_profile_source": taste_source,
                "meal_context_source": meal_source,
                "occasion_context_source": occ_source,
                "needs_review": meal_source == "heuristic" or occ_source == "heuristic" or not final_taste,
                "notes": review_notes,
            }
            
        categorized_batch.append(result)

    return categorized_batch


def build_stats(items: list[dict]) -> Counter:
    stats = Counter()
    stats["total_foods"] = len(items)

    for item in items:
        review = item.get("category_review") or {}
        if not item.get("taste_profile"):
            stats["missing_taste_profile"] += 1
        if not item.get("meal_context"):
            stats["missing_meal_context"] += 1
        if not item.get("occasion_context"):
            stats["missing_occasion_context"] += 1
        if review.get("needs_review"):
            stats["needs_review"] += 1

        for field in ["taste_profile_source", "meal_context_source", "occasion_context_source"]:
            if source := review.get(field):
                stats[f"{field}:{source}"] += 1

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Tach soft_tags thanh soft_tags/category fields")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="File relabel da review")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="File output categorized")
    parser.add_argument("--no-review-metadata", action="store_true", help="Khong ghi category_review vao output")
    parser.add_argument("--force", action="store_true", help="Cho phep overwrite output neu da ton tai")
    parser.add_argument("--use-llm", action="store_true", help="Dung LLM de gan tag; heuristic lam fallback")
    parser.add_argument("--llm-model", default=DEFAULT_LLM_MODEL, help="Model LLM dung khi bat --use-llm")
    parser.add_argument("--llm-delay", type=float, default=1.0, help="So giay nghi giua cac request batch")
    parser.add_argument("--offset", type=int, default=0, help="Bo qua n mon dau tien truoc khi xu ly")
    parser.add_argument("--limit", type=int, default=None, help="Chi xu ly toi da n mon sau offset")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="So mon an goi len LLM trong 1 request")
    
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        raise FileNotFoundError(f"Khong tim thay input: {input_path}")
    if output_path.exists() and not args.force:
        raise FileExistsError(f"Output da ton tai, dung --force de ghi de: {output_path}")

    with input_path.open("r", encoding="utf-8") as f:
        items = json.load(f)

    if args.offset < 0:
        raise ValueError("--offset phai >= 0")

    if args.offset:
        items = items[args.offset:]
        print(f"⚠️ Bo qua {args.offset} mon dau tien.")

    if args.limit is not None and args.limit > 0:
        items = items[:args.limit]
        print(f"⚠️ Chi xu ly toi da {args.limit} mon sau offset.")

    llm_client = load_llm_client() if args.use_llm else None

    # CHIA BATCH TẠI ĐÂY
    categorized = []
    batch_size = args.batch_size
    batches = [items[i:i + batch_size] for i in range(0, len(items), batch_size)]

    print(f"Bắt đầu xử lý {len(items)} món ăn (chia làm {len(batches)} batches)...")

    for i, batch in enumerate(batches, 1):
        print(f"Đang xử lý Batch {i}/{len(batches)} ({len(batch)} món)...")
        
        batch_results = process_items_batch(
            batch_items=batch,
            include_review_metadata=not args.no_review_metadata,
            llm_client=llm_client,
            llm_model=args.llm_model,
        )
        
        categorized.extend(batch_results)
        
        if args.use_llm and args.llm_delay > 0 and i < len(batches):
            time.sleep(args.llm_delay)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(categorized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    stats = build_stats(categorized)

    print(f"\n--- THỐNG KÊ ---")
    print(f"Input: {input_path}")
    print(f"Output: {output_path}")
    print(f"Foods: {stats['total_foods']}")
    print(f"Missing taste_profile: {stats['missing_taste_profile']}")
    print(f"Missing meal_context: {stats['missing_meal_context']}")
    print(f"Missing occasion_context: {stats['missing_occasion_context']}")
    print(f"Needs review: {stats['needs_review']}")

if __name__ == "__main__":
    main()
