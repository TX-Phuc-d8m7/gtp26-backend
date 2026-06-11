"""Thành phần dùng chung của search engine.

Module này chứa constants, Gemini client/model config, danh mục tag chuẩn và
helper chuẩn hóa text/tag. Các module search khác được phép phụ thuộc vào
`common.py`; chiều ngược lại không nên xảy ra để tránh circular import.
"""

from __future__ import annotations

import os
import re

from google import genai

from app.core.config import settings
from app.modules.foods.models import Food
from app.modules.ingredients.service import has_any_ingredient_key

PROJECT_ID = os.getenv("PROJECT_ID")
client = genai.Client(vertexai=True, project=PROJECT_ID, location="us-central1")
def get_gemini_text_model() -> str:
    """Lấy tên model text Gemini từ env, nếu không có thì dùng cấu hình mặc định."""
    return os.getenv("GEMINI_TEXT_MODEL", settings.gemini_text_model)

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
# Giới hạn số món bị loại bởi SQL hard filter được lưu vào retrieval trace.
SQL_HARD_FILTER_TRACE_LIMIT = 20

def _env_bool(name: str, default: bool = False) -> bool:
    """Đọc biến môi trường dạng boolean theo các giá trị truthy quen thuộc."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

def _env_int(name: str, default: int) -> int:
    """Đọc biến môi trường dạng số nguyên, fallback về default nếu parse lỗi."""
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default

# Mặc định giữ console gọn để dễ đọc intent LLM; bật true khi cần debug sâu pipeline search.
SEARCH_VERBOSE_LOGS = _env_bool("SEARCH_VERBOSE_LOGS", False)
# Số candidate tối đa được in khi SEARCH_VERBOSE_LOGS=true.
SEARCH_CANDIDATE_LOG_LIMIT = _env_int("SEARCH_CANDIDATE_LOG_LIMIT", 20)
# Số dòng scoring/rerank tối đa được in khi SEARCH_VERBOSE_LOGS=true.
SEARCH_SCORE_LOG_LIMIT = _env_int("SEARCH_SCORE_LOG_LIMIT", 20)

# =====================================================================
# 1. AGENT & LUỒNG XỬ LÝ XUNG ĐỘT 
# =====================================================================

# --- Khai báo các danh mục Tag chuẩn ---
valid_health_tags = [
    "Vết thương hở / Mới phẫu thuật", "Đang cho con bú", "Phụ nữ mang thai",
    "Gan nhiễm mỡ / Men gan cao", "Béo phì", "Đầy bụng / Khó tiêu",
    "Nhiệt miệng / Loét miệng", "Tiêu chảy", "Gout",
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
    "Nóng hổi", "Thanh mát / Giải nhiệt", "Món nước", "Món khô", "Nước sền sệt", "Món lạnh", "Sống / Chín tái",
    "Giòn / Giòn rụm", "Dai / Sần sật", "Mềm",
    "Chiên / Rán", "Nướng", "Hấp / Luộc", "Xào", "Gỏi / Nộm / Trộn", "Cuốn / Gói", "Hầm / Ninh", "Lẩu", "Kho / Rim", "Súp", "Cháo", "Rang",
    "Ăn no", "Ăn vặt", "Mồi nhậu", "Ăn sáng", "Ăn trưa", "Ăn chiều / xế", "Ăn tối", "Ăn khuya", "Tráng miệng", "Giải rượu", "Giải cảm", "Ấm bụng",
    "Đặc sản Đà Nẵng", "Ẩm thực đường phố", "Món Việt truyền thống", "Món Á", "Món Âu", "Thức ăn nhanh", "Món chay",
    "Giàu chất xơ", "Giàu đạm", "Giàu vitamin", "Giàu tinh bột", "Nội tạng", "Từ sữa / Phô mai", "Thực phẩm chế biến sẵn", "Bánh ngọt",
    "Dễ tiêu", "Khó tiêu / Nặng bụng", "Healthy / Eat Clean", "Nhiều dầu mỡ / Calo cao", "Hải sản"
]

# Phân loại các Soft Tags thành từng nhóm ngữ cảnh cụ thể
TASTE_PROFILE_TAGS = {"Đậm đà", "Thanh đạm", "Chua", "Cay", "Mặn", "Ngọt", "Đắng", "Béo ngậy"}
MEAL_CONTEXT_TAGS = {"Ăn sáng", "Ăn trưa", "Ăn tối", "Ăn chiều / xế", "Ăn khuya"}
OCCASION_CONTEXT_TAGS = {"Ăn no", "Ăn vặt", "Mồi nhậu", "Tráng miệng", "Giải rượu", "Giải cảm", "Ấm bụng"}

# --- Trọng số & Cấu hình cho thuật toán tính điểm (Scoring) ---
USER_SOFT_TAG_BONUS = 0.018
USER_TASTE_BONUS = 0.018
USER_MEAL_CONTEXT_BONUS = 0.035
USER_OCCASION_CONTEXT_BONUS = 0.035
MEDICAL_PREFER_TAG_BONUS = 0.014

USER_AVOID_TAG_PENALTY = 0.035
MEDICAL_AVOID_TAG_PENALTY = 0.045
MEDICAL_CAUTION_INGREDIENT_KEY_PENALTY = 0.045

MAX_MEDICAL_TAG_BONUS = 0.06
MAX_USER_CONTEXT_BONUS = 0.07
MAX_USER_SOFT_TASTE_BONUS = 0.03
MAX_TAG_BONUS = 0.12
MAX_TAG_PENALTY = 0.16
MAX_MEDICAL_CAUTION_INGREDIENT_KEY_PENALTY = 0.09

MIN_CONTEXT_FILTER_CANDIDATES = 5
PRIMARY_MEAL_ROLES = {"one_dish_meal", "main_dish"}
# Các ingredient include được phép thu hẹp candidate như hard filter thích nghi.
# Hiện chỉ bật cho intent "món cá" để tránh làm cứng các nguyên liệu mơ hồ như cà chua.
ADAPTIVE_INGREDIENT_INCLUDE_KEYS: set[str] = set()
MEAL_ROLE_ADJUSTMENTS = {
    "one_dish_meal": 0.08,
    "main_dish": 0.05,
    # Role chỉ là tín hiệu phụ. Không phạt quá nặng canh/súp/rau vì trong
    # nhiều bệnh lý, đặc biệt dạ dày/tim mạch/béo phì, chúng có thể an toàn hơn.
    "side_soup": -0.02,
    "side_vegetable": -0.03,
    "snack_dessert": -0.08,
    "unknown": -0.01,
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

MEDICAL_CAUTION_INGREDIENT_KEY_RULES = {
    "Gout": {
        "group:purine_vua": "chao/đậu nành lên men",
    },
}

TAG_ALIAS_MAP = {
    "hap/luoc": "Hấp / Luộc",
    "hap / luoc": "Hấp / Luộc",
    "song / chin tai": "Sống / Chín tái",
    "cuon/goi": "Cuốn / Gói",
    "thanh dam": "Thanh đạm",
    "thanh mat / giai nhiet": "Thanh mát / Giải nhiệt",
    "thanh mat/giai nhiet": "Thanh mát / Giải nhiệt",
    "do an nhanh": "Thức ăn nhanh",
    "an dem": "Ăn khuya",
    "it beo": "Thanh đạm",
    "giau chat so": "Giàu chất xơ",
    "sua / pho mai": "Từ sữa / Phô mai",
}

USER_INGREDIENT_CATEGORY_TAG_MAP = {
    "hai san": ["Hải sản"],
    "do bien": ["Hải sản"],
    "tom cua": ["Hải sản"],
    "do ngot": ["Ngọt"],
    "mon ngot": ["Ngọt"],
    "che": ["Ngọt", "Tráng miệng"],
    "tra sua": ["Ngọt", "Từ sữa / Phô mai"],
    "banh ngot": ["Bánh ngọt", "Ngọt"],
    "tinh bot": ["Giàu tinh bột"],
    "do chien": ["Chiên / Rán"],
    "chien ran": ["Chiên / Rán"],
    "do ran": ["Chiên / Rán"],
    "do dau mo": ["Nhiều dầu mỡ / Calo cao"],
    "nhieu dau mo": ["Nhiều dầu mỡ / Calo cao"],
    "do beo": ["Béo ngậy"],
    "beo ngay": ["Béo ngậy"],
    "do tu sua": ["Từ sữa / Phô mai"],
    "san pham tu sua": ["Từ sữa / Phô mai"],
    "pho mai": ["Từ sữa / Phô mai"],
    "do co trung": ["Bánh ngọt"],
    "do cay": ["Cay"],
    "cay": ["Cay"],
    "do chua": ["Chua"],
    "chua": ["Chua"],
    "do man": ["Mặn"],
    "man": ["Mặn"],
    "dam da": ["Đậm đà"],
    "dam vi": ["Đậm đà"],
    "noi tang": ["Nội tạng"],
    "do song": ["Sống / Chín tái"],
    "tai": ["Sống / Chín tái"],
    "song tai": ["Sống / Chín tái"],
    "goi": ["Gỏi / Nộm / Trộn"],
    "nom": ["Gỏi / Nộm / Trộn"],
    "tron": ["Gỏi / Nộm / Trộn"],
    "lau": ["Lẩu"],
    "do nuong": ["Nướng"],
    "nuong": ["Nướng"],
    "xao": ["Xào"],
    "do an nhanh": ["Thức ăn nhanh"],
    "fast food": ["Thức ăn nhanh"],
    "do che bien san": ["Thực phẩm chế biến sẵn"],
    "thuc pham che bien san": ["Thực phẩm chế biến sẵn"],
    "do lanh": ["Món lạnh"],
    "mon lanh": ["Món lạnh"],
    "do gion": ["Giòn / Giòn rụm"],
    "gion": ["Giòn / Giòn rụm"],
    "dai": ["Dai / Sần sật"],
    "kho tieu": ["Khó tiêu / Nặng bụng"],
    "nong": ["Nóng hổi"],
    "nong hoi": ["Nóng hổi"],
}

USER_FOOD_BASE_PHRASES = {
    "mi quang": "mì quảng",
    "my quang": "mì quảng",
    "cao lau": "cao lầu",
    "banh canh": "bánh canh",
    "hu tieu": "hủ tiếu",
    "banh mi": "bánh mì",
    "banh xeo": "bánh xèo",
    "banh cuon": "bánh cuốn",
    "banh nam": "bánh nậm",
    "banh goi": "bánh gói",
    "banh bot loc": "bánh bột lọc",
    "banh beo": "bánh bèo",
    "bun": "bún",
    "com": "cơm",
    "pho": "phở",
    "mien": "miến",
    "mi": "mì",
    "my": "mì",
    "lau": "lẩu",
    "nuong": "nướng",
    "chao": "cháo",
    "sup": "súp",
    "xoi": "xôi",
    "goi": "gỏi",
    "nom": "gỏi",
    "cuon": "cuốn",
    "salad": "salad",
}

USER_FOOD_BASE_PROMPT_LIST = ", ".join(dict.fromkeys(USER_FOOD_BASE_PHRASES.values()))


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

def _normalize_search_text(value: str) -> str:
    """Chuẩn hóa text tự do để match keyword theo từ/cụm từ."""
    text_value = _strip_accents(value or "").lower()
    text_value = re.sub(r"[^a-z0-9\s/-]", " ", text_value)
    return re.sub(r"\s+", " ", text_value).strip()

def _phrase_in_text(text_value: str, phrase: str) -> bool:
    """Kiểm tra phrase có xuất hiện như một cụm từ độc lập trong text đã chuẩn hóa hay không."""
    normalized_phrase = _normalize_search_text(phrase)
    if not normalized_phrase:
        return False
    pattern = rf"(?<![a-z0-9]){re.escape(normalized_phrase)}(?![a-z0-9])"
    return re.search(pattern, text_value) is not None

def _has_any_phrase(text_value: str, phrases: list[str]) -> bool:
    """True nếu text khớp với ít nhất một phrase trong danh sách đầu vào."""
    return any(_phrase_in_text(text_value, phrase) for phrase in phrases)

def _food_has_any_ingredient_key(food: Food, target_keys: list[str]) -> bool:
    """Kiểm tra món ăn có giao với các ingredient key cần lọc hay không."""
    return has_any_ingredient_key(food.core_ingredient_keys or [], target_keys)

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

def infer_soft_tags_from_user_ingredient_phrase(value: str) -> list[str]:
    """
    Nhận diện các cụm sở thích bị supervisor đưa vào include_ingredients
    nhưng thực chất là nhóm món/tính chất, ví dụ "hải sản", "đồ ngọt".
    """
    normalized = _normalize_search_text(value)
    if not normalized:
        return []

    matched_tags: list[str] = []
    for phrase, tags in USER_INGREDIENT_CATEGORY_TAG_MAP.items():
        if normalized == phrase or _phrase_in_text(normalized, phrase):
            for tag in canonicalize_soft_tags(tags):
                if tag not in matched_tags:
                    matched_tags.append(tag)
    return matched_tags

def extend_soft_tags_from_user_ingredients(ingredients: set[str]) -> set[str]:
    """Chuyển các ingredient dạng category an toàn thành soft tag để rerank đúng hơn."""
    tags: set[str] = set()
    for ingredient in ingredients or []:
        tags.update(infer_soft_tags_from_user_ingredient_phrase(ingredient))
    return tags

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

def canonicalize_health_tag(tag: str) -> str:
    """Đồng nhất từ khóa sức khỏe về dạng chuẩn (alias mapping)."""
    return HEALTH_TAG_ALIAS_MAP.get((tag or "").strip(), (tag or "").strip())
