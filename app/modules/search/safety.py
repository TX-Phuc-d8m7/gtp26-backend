"""Safety layer cho food search.

Module này giữ allergy text fallback, rule match theo core ingredients và phần
resolve medical/allergy constraints từ supervisor, user profile và bảng tags.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable

TAGS_DATA_PATH = Path(__file__).resolve().parents[3] / "standard-data" / "tags_data.json"

ALLERGEN_TEXT_PATTERNS: dict[str, list[str]] = {
    "Dị ứng động vật giáp xác": [
        "tôm", "tép", "cua", "ghẹ", "bề bề", "chả cua", "thanh cua",
        "mắm tôm", "mắm tép", "muối tôm", "sa tế tôm", "hạt nêm hải sản",
        "gia vị lẩu thái",
    ],
    "Dị ứng động vật thân mềm": [
        "ốc", "sò điệp", "sò huyết", "sò lông", "sò lụa", "nghêu",
        "ngao", "hến", "hàu", "vẹm", "tu hài", "mực", "bạch tuộc",
        "dầu hào",
    ],
    "Dị ứng cá có vây": [
        "vi cá", "chả cá", "cá viên", "cá hồi", "cá ngừ", "cá basa",
        "cá bớp", "cá chẽm", "cá diêu hồng", "cá lóc", "cá thu",
        "cá trích", "nước mắm", "mắm nêm",
    ],
    "Dị ứng đậu phộng": [
        "đậu phộng", "đậu phụng", "lạc", "bơ đậu phộng",
    ],
    "Dị ứng hạt cây": [
        "hạt điều", "hạt hồ đào", "hạt dẻ", "hạt thông", "óc chó",
        "hạnh nhân", "bột hạnh nhân",
    ],
    "Dị ứng sữa bò": [
        "sữa", "sữa đặc", "sữa chua", "sữa bột", "sữa công thức",
        "bơ lạt", "bơ mặn", "phô mai", "pho mai", "phomai",
        "whipping cream", "fresh cream", "cream cheese", "kem",
        "sốt kem", "sốt caesar", "mascarpone", "fromage", "bánh flan",
        "caramel", "chocolate", "socola", "bột phô mai",
    ],
    "Bất dung nạp Lactose": [
        "sữa", "sữa đặc", "sữa chua", "sữa bột", "sữa công thức",
        "bơ lạt", "bơ mặn", "phô mai", "pho mai", "phomai",
        "whipping cream", "fresh cream", "cream cheese", "kem",
        "sốt kem", "mascarpone", "fromage", "bánh flan", "sốt caesar",
    ],
    "Dị ứng đậu nành": [
        "đậu nành", "đậu hũ", "đậu phụ", "tàu hũ", "tàu hũ ky",
        "nước tương", "xì dầu", "sữa đậu nành", "tương đậu",
        "tương hột", "tempeh", "miso", "tương miso", "dầu hào chay",
        "sườn chay", "thịt chay", "chả chay", "nước tương tamari",
        "sốt teriyaki", "hoisin sauce",
    ],
    "Dị ứng lúa mì": [
        "bột mì", "bánh mì", "bánh sandwich", "mì trứng", "mì udon",
        "mì ramen", "mì ý", "hoành thánh", "sủi cảo", "bánh tortilla",
        "bột chiên giòn", "bột xù", "bột bánh mì", "màn thầu",
        "đế bánh pizza", "bánh lady finger", "ngũ cốc",
    ],
    "Dị ứng trứng": [
        "trứng", "trứng gà", "trứng cút", "trứng vịt", "trứng vịt lộn",
        "trứng muối", "trứng bắc thảo", "trứng non", "lòng đỏ trứng",
        "lòng trắng trứng", "chả trứng", "mayonnaise", "sốt mayonnaise",
        "sốt mayonaise", "mì trứng", "bánh flan", "kem trứng",
    ],
    "Dị ứng cà chua": [
        "cà chua", "cà chua bi", "tương cà", "tương cà chua",
        "sốt cà chua", "ketchup",
    ],
    "Dị ứng trái cây có múi": [
        "chanh", "chanh dây", "cam", "bưởi", "quất", "tắc", "lá chanh",
        "nước chanh", "nước cốt chanh", "nước ép cam", "nước cốt tắc",
        "muối tiêu chanh",
    ],
    "Dị ứng mè / vừng": [
        "mè", "vừng", "dầu mè", "mè rang", "mè đen", "vừng rang",
        "sốt mè", "sốt mè rang", "nước sốt mè rang",
    ],
    "Dị ứng bột ngọt (MSG)": [
        "bột ngọt", "mì chính", "hạt nêm", "bột nêm", "hạt nêm chay",
    ],
    "Dị ứng mắm lên men": [
        "mắm", "nước mắm", "mắm tôm", "mắm ruốc", "mắm nêm", "mắm tép",
        "nước mắm chua ngọt", "nước mắm tỏi ớt", "dầu hào",
    ],
}

ALLERGY_TAG_ALIASES = {
    "dị ứng mè/vừng": "Dị ứng mè / vừng",
    "di ung me/vung": "Dị ứng mè / vừng",
    "bất dung nạp lactose": "Bất dung nạp Lactose",
    "bat dung nap lactose": "Bất dung nạp Lactose",
}

ALLERGEN_TEXT_EXCLUSION_PATTERNS: dict[tuple[str, str], list[str]] = {
    ("Dị ứng động vật giáp xác", "tép"): [
        "tép hành",
        "tép tỏi",
    ],
    ("Dị ứng sữa bò", "sữa"): [
        "sữa đậu nành",
    ],
    ("Bất dung nạp Lactose", "sữa"): [
        "sữa đậu nành",
    ],
    ("Dị ứng trứng", "trứng"): [
        "mực trứng",
    ],

}

COLLISION_PRONE_UNACCENTED_WORDS = {
    "bo", "bot", "ca", "dau", "gia", "kem", "me", "mi", "sot", "sua", "ot", "gao",
}

_TAGS_DATA_ALLERGEN_PATTERNS_CACHE: dict[str, list[str]] | None = None
_TAGS_DATA_ALLERGEN_PATTERNS_SIGNATURE: tuple[int, int] | None = None


def normalize_vietnamese_text(value: str) -> str:
    """Chuẩn hóa text nhưng vẫn giữ dấu tiếng Việt để match phrase an toàn hơn."""
    text = unicodedata.normalize("NFC", str(value or "")).lower()
    text = re.sub(r"[_/(){}\[\],.;:!?+*='\"`~|\\<>-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_vietnamese_ascii(value: str) -> str:
    """Chuẩn hóa text và bỏ dấu để bắt được các phrase lưu ở dạng không dấu."""
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("đ", "d").replace("Đ", "D")
    text = text.lower()
    text = re.sub(r"[_/(){}\[\],.;:!?+*='\"`~|\\<>-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def has_vietnamese_diacritic(value: str) -> bool:
    """Kiểm tra phrase có chứa ký tự dấu tiếng Việt hay không."""
    return normalize_vietnamese_ascii(value) != normalize_vietnamese_text(value)


def phrase_in_normalized_text(normalized_text: str, normalized_phrase: str) -> bool:
    """Kiểm tra phrase đã chuẩn hóa có xuất hiện như một cụm từ độc lập hay không."""
    if not normalized_phrase:
        return False
    return f" {normalized_phrase} " in f" {normalized_text} "


def phrase_in_text(text_value: str, phrase: str) -> bool:
    """Match phrase theo cụm token độc lập, có fallback không dấu khi phrase vốn không dấu."""
    normalized_phrase = normalize_vietnamese_text(phrase)
    if phrase_in_normalized_text(normalize_vietnamese_text(text_value), normalized_phrase):
        return True

    # tags_data.json stores many ingredients without accents (e.g. "tom", "so huyet").
    # Only use accent-insensitive matching for no-accent phrases to avoid collisions
    # such as curated "mè" accidentally matching tamarind "me".
    if not has_vietnamese_diacritic(phrase):
        return phrase_in_normalized_text(
            normalize_vietnamese_ascii(text_value),
            normalize_vietnamese_ascii(phrase),
        )
    return False


def get_field_value(food: Any, field_name: str) -> Any:
    """Lấy field từ object hoặc dict để dùng chung cho nhiều kiểu dữ liệu food."""
    if isinstance(food, dict):
        return food.get(field_name)
    return getattr(food, field_name, None)


def coerce_text_list(value: Any) -> list[str]:
    """Ép dữ liệu về list[str] để xử lý đồng nhất ở các bước match text."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def build_allergy_text_source(food: Any) -> str:
    """Gộp core_ingredients thành một chuỗi text để phục vụ kiểm tra dị ứng."""
    parts: list[str] = []
    parts.extend(coerce_text_list(get_field_value(food, "core_ingredients")))
    return " ".join(parts)


def build_allergy_text_items(food: Any) -> list[str]:
    """Trả từng core ingredient riêng lẻ để rule exclusion chỉ áp dụng đúng item liên quan."""
    return coerce_text_list(get_field_value(food, "core_ingredients"))


def canonical_allergy_name(name: str) -> str:
    """Chuẩn hóa tên dị ứng về canonical name mà hệ thống đang dùng."""
    raw = (name or "").strip()
    if raw in get_allergen_text_patterns():
        return raw
    normalized = normalize_vietnamese_text(raw)
    return ALLERGY_TAG_ALIASES.get(normalized, raw)


def should_include_exclude_phrase(phrase: str) -> bool:
    """Lọc bớt các phrase quá ngắn/dễ va chạm trước khi đưa vào bộ pattern dị ứng.

    Chỉ loại bỏ từ ĐƠN không dấu có nguy cơ va chạm cao (VD: "ca", "bo", "gao").
    Cụm NHIỀU TỪ như "ca loc", "thit bo" được giữ lại vì phrase_in_text() đã xử lý
    chuẩn hoá ASCII hai chiều — so sánh "ca loc" sẽ khớp với "cá lóc" đúng cách.
    """
    normalized = normalize_vietnamese_text(phrase)
    if not normalized:
        return False
    words = normalized.split()
    if len(words) == 1 and words[0] in COLLISION_PRONE_UNACCENTED_WORDS:
        return False
    return True


def load_tags_data_allergen_patterns() -> dict[str, list[str]]:
    """Đọc thêm pattern dị ứng từ tags_data.json và tự refresh khi file dữ liệu thay đổi."""
    global _TAGS_DATA_ALLERGEN_PATTERNS_CACHE, _TAGS_DATA_ALLERGEN_PATTERNS_SIGNATURE

    grouped: dict[str, list[str]] = {}
    if not TAGS_DATA_PATH.exists():
        _TAGS_DATA_ALLERGEN_PATTERNS_CACHE = grouped
        _TAGS_DATA_ALLERGEN_PATTERNS_SIGNATURE = None
        return grouped

    try:
        stat = TAGS_DATA_PATH.stat()
        current_signature = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        _TAGS_DATA_ALLERGEN_PATTERNS_CACHE = grouped
        _TAGS_DATA_ALLERGEN_PATTERNS_SIGNATURE = None
        return grouped

    if (
        _TAGS_DATA_ALLERGEN_PATTERNS_CACHE is not None
        and _TAGS_DATA_ALLERGEN_PATTERNS_SIGNATURE == current_signature
    ):
        return _TAGS_DATA_ALLERGEN_PATTERNS_CACHE

    try:
        tags_data = json.loads(TAGS_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _TAGS_DATA_ALLERGEN_PATTERNS_CACHE or grouped

    for item in tags_data:
        if item.get("tag_type") != "ALLERGY":
            continue
        allergy_name = item.get("name")
        if not allergy_name:
            continue

        patterns = []
        for phrase in item.get("exclude_ingredient") or []:
            if isinstance(phrase, str) and should_include_exclude_phrase(phrase):
                patterns.append(phrase)
        grouped[allergy_name] = patterns

    _TAGS_DATA_ALLERGEN_PATTERNS_CACHE = grouped
    _TAGS_DATA_ALLERGEN_PATTERNS_SIGNATURE = current_signature
    return grouped


def get_allergen_text_patterns() -> dict[str, list[str]]:
    """Trả về toàn bộ pattern dị ứng sau khi gộp hard-code và dữ liệu từ tags_data.json."""
    merged = {name: list(patterns) for name, patterns in ALLERGEN_TEXT_PATTERNS.items()}

    for allergy_name, patterns in load_tags_data_allergen_patterns().items():
        merged.setdefault(allergy_name, [])
        merged[allergy_name].extend(patterns)

    deduped_by_allergy: dict[str, list[str]] = {}
    for allergy_name, patterns in merged.items():
        seen = set()
        deduped = []
        for pattern in patterns:
            normalized = normalize_vietnamese_ascii(pattern)
            if normalized and normalized not in seen:
                seen.add(normalized)
                deduped.append(pattern)
        deduped_by_allergy[allergy_name] = deduped

    return deduped_by_allergy


def patterns_for_allergy_constraints(
    allergy_constraints: Iterable[str],
    allergy_exclude_ingredients: Iterable[str] | None = None,
) -> dict[str, list[str]]:
    """Sinh danh sách pattern text cần kiểm tra cho từng ràng buộc dị ứng đầu vào."""
    all_patterns = get_allergen_text_patterns()
    canonical_constraints = [
        canonical_allergy_name(allergy) for allergy in (allergy_constraints or [])
    ]
    exclude_patterns = []
    if (
        len(canonical_constraints) == 1
        and canonical_constraints[0] not in all_patterns
    ):
        exclude_patterns = [
            phrase for phrase in (allergy_exclude_ingredients or [])
            if should_include_exclude_phrase(phrase)
        ]
    grouped: dict[str, list[str]] = {}
    for canonical in canonical_constraints:
        patterns = list(all_patterns.get(canonical, []))
        patterns.extend(exclude_patterns)

        seen = set()
        deduped = []
        for pattern in patterns:
            normalized = normalize_vietnamese_text(pattern)
            if normalized and normalized not in seen:
                seen.add(normalized)
                deduped.append(pattern)
        grouped[canonical] = deduped
    return grouped


def phrase_is_excluded(text_value: str, allergy: str, phrase: str) -> bool:
    """Kiểm tra phrase match hiện tại có nằm trong nhóm ngoại lệ cần bỏ qua hay không."""
    normalized_phrase = normalize_vietnamese_text(phrase)
    ascii_phrase = normalize_vietnamese_ascii(phrase)
    exclusions: list[str] = []
    for (pattern_allergy, pattern_phrase), pattern_exclusions in ALLERGEN_TEXT_EXCLUSION_PATTERNS.items():
        if pattern_allergy != allergy:
            continue
        if (
            normalize_vietnamese_text(pattern_phrase) == normalized_phrase
            or normalize_vietnamese_ascii(pattern_phrase) == ascii_phrase
        ):
            exclusions.extend(pattern_exclusions)
    return any(phrase_in_text(text_value, exclusion) for exclusion in exclusions)


def detect_allergy_text_matches(
    food: Any,
    allergy_constraints: Iterable[str],
    allergy_exclude_ingredients: Iterable[str] | None = None,
) -> list[dict[str, str]]:
    """Tìm các phrase dị ứng trùng trong core_ingredients và trả về danh sách match chi tiết."""
    source_items = build_allergy_text_items(food)
    if not source_items:
        return []

    matches: list[dict[str, str]] = []
    for allergy, patterns in patterns_for_allergy_constraints(
        allergy_constraints,
        allergy_exclude_ingredients,
    ).items():
        for source_item in source_items:
            for phrase in patterns:
                if phrase_in_text(source_item, phrase) and not phrase_is_excluded(source_item, allergy, phrase):
                    matches.append({
                        "allergy": allergy,
                        "phrase": normalize_vietnamese_text(phrase),
                    })
    return matches


def has_allergy_text_match(
    food: Any,
    allergy_constraints: Iterable[str],
    allergy_exclude_ingredients: Iterable[str] | None = None,
) -> bool:
    """Wrapper boolean: chỉ cần biết món có dính match dị ứng text hay không."""
    return bool(detect_allergy_text_matches(
        food,
        allergy_constraints,
        allergy_exclude_ingredients,
    ))

# =====================================================================
# Medical/allergy constraint resolution used by the search engine
# =====================================================================

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingredients.service import generate_filter_keys, load_enabled_alias_override_rules
from app.modules.search.common import (
    SUPERVISOR_FALLBACK_WARNING,
    _normalize_tag_key,
    _normalize_search_text,
    _phrase_in_text,
    canonicalize_health_tag,
    canonicalize_soft_tags,
    extend_soft_tags_from_user_ingredients,
    get_food_scoring_tags,
    infer_soft_tags_from_user_ingredient_phrase,
    matched_canonical_tags,
)
from app.modules.search.intent import run_supervisor_with_timeout
from app.modules.search.repository import list_tags_by_names
from app.modules.search.tracing import append_trace_item, food_trace_snapshot
from app.modules.users.models import UserHealthProfile
from app.modules.foods.models import Food


def apply_medical_soft_tag_hard_filter_with_trace(
    foods: list[Food],
    excluded_tags: list[str],
    trace: dict,
) -> tuple[list[Food], int]:
    """
    Loại cứng món có soft tag trùng rule y khoa cần tránh.

    Các tag này đến từ tags_data theo bệnh lý/triệu chứng (không phải sở thích).
    Nếu để chúng chỉ là penalty, semantic rerank có thể kéo món nguy cơ cao
    như hải sản cho Gout quay lại top kết quả.
    """
    canonical_excluded_tags = canonicalize_soft_tags(excluded_tags)
    if not foods or not canonical_excluded_tags:
        return foods, 0

    kept_foods = []
    removed_count = 0
    for food in foods:
        matched_tags = matched_canonical_tags(
            get_food_scoring_tags(food),
            canonical_excluded_tags,
        )
        if matched_tags:
            removed_count += 1
            append_trace_item(trace, "hard_filtered_out", {
                **food_trace_snapshot(food),
                "stage": "medical_soft_tag_filter",
                "reason": "medical_soft_tag_overlap",
                "matched_tags": matched_tags,
            })
            continue
        kept_foods.append(food)

    print(
        f"🛡️ [MEDICAL SOFT TAG FILTER] Loại {removed_count}/{len(foods)} món "
        f"có tag y khoa cần tránh: {canonical_excluded_tags}"
    )
    return kept_foods, removed_count

async def resolve_food_conflicts(
    user_input: str,
    db: AsyncSession,
    profile: UserHealthProfile | None = None,
):
    """
    Kết hợp kết quả từ Agent và Database để giải quyết xung đột
    giữa Sở thích (những gì User muốn) và Sức khỏe (những gì y khoa cấm/khuyên).

    Profile (nếu có) được merge trực tiếp vào kết quả supervisor — không qua LLM parse:
      - health_conditions + allergies → symptoms
      - preferred_ingredients         → user_likes_ings
      - taste_profile + dish_preferences → user_include_tags
    """
    extracted_data, supervisor_runtime = await run_supervisor_with_timeout(user_input)

    # Lấy thông tin trích xuất từ supervisor
    symptoms = [canonicalize_health_tag(tag) for tag in extracted_data.get("health_constraints", [])]
    user_include_dishes = extracted_data.get("include_dishes", [])
    user_exclude_dishes = extracted_data.get("exclude_dishes", [])

    user_likes_ings = set(extracted_data.get("include_ingredients", []))
    user_dislikes_ings = set(extracted_data.get("exclude_ingredients", []))
    excluded_dish_keys = [_normalize_search_text(dish) for dish in user_exclude_dishes]
    user_include_dishes = [
        dish for dish in user_include_dishes
        if not any(
            excluded_key and _phrase_in_text(_normalize_search_text(dish), excluded_key)
            for excluded_key in excluded_dish_keys
        )
    ]

    user_include_tags = set(extracted_data.get("include_soft_tags", []))
    user_exclude_tags = set(extracted_data.get("exclude_soft_tags", []))

    # Merge trực tiếp từ user profile (deterministic, không qua LLM)
    if profile is not None:
        # health_conditions + allergies → gộp vào symptoms, canonicalize để match valid_health_tags
        profile_health_tags = [
            canonicalize_health_tag(tag)
            for tag in (profile.health_conditions or []) + (profile.allergies or [])
        ]
        symptoms = list(dict.fromkeys(symptoms + profile_health_tags))

        # preferred_ingredients → gộp vào user_likes_ings
        user_likes_ings.update(profile.preferred_ingredients or [])

        # taste_profile + dish_preferences → canonicalize rồi gộp vào user_include_tags
        profile_soft_tags = canonicalize_soft_tags(
            (profile.taste_profile or []) + (profile.dish_preferences or [])
        )
        user_include_tags.update(profile_soft_tags)

    # Khởi tạo tập hợp y khoa
    allergy_constraints = set()
    disease_constraints = set()
    allergy_exclude_tags = set()
    medical_exclude_tags = set()
    medical_prefer_tags = set()
    allergy_exclude_ings = set()
    disease_exclude_ings = set()
    medical_exclude_ings = set()
    medical_prefer_ings = set()

    # Truy vấn DB để lấy quy tắc y khoa theo bệnh lý
    if symptoms:
        tags_db = await list_tags_by_names(db, symptoms)

        for tag in tags_db:
            # Dị ứng cần chặn theo nguyên liệu cụ thể. Chặn theo soft tag như "Hải sản"
            # dễ loại nhầm các món không chứa tác nhân dị ứng trực tiếp.
            if tag.tag_type == "ALLERGY":
                allergy_constraints.add(tag.name)
                allergy_exclude_ings.update(tag.exclude_ingredient)
                allergy_exclude_tags.update(canonicalize_soft_tags(tag.exclude_soft_tag))
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
    safety_exclude_tags = medical_exclude_tags.union(allergy_exclude_tags)

    # Logic kiểm tra thông báo cảnh báo (warning) cho nguyên liệu
    alias_override_rules = await load_enabled_alias_override_rules(db)

    medical_exclude_keys = set(
        generate_filter_keys(medical_exclude_ings, extra_rules=alias_override_rules)
    )

    conflicting_ings = set()
    conflicting_category_tags = set()
    safe_user_include_ings = set()
    for ing in user_likes_ings:
        inferred_tags = set(infer_soft_tags_from_user_ingredient_phrase(ing))
        matched_excluded_tags = inferred_tags.intersection(safety_exclude_tags)
        if matched_excluded_tags:
            conflicting_category_tags.update(matched_excluded_tags)
            continue

        user_ing_keys = set(generate_filter_keys([ing], extra_rules=alias_override_rules))
        if user_ing_keys.intersection(medical_exclude_keys):
            conflicting_ings.add(ing.lower())
        else:
            safe_user_include_ings.add(ing.lower())

    user_include_tags.update(extend_soft_tags_from_user_ingredients(safe_user_include_ings))


    # 2. Logic cho tính chất (Soft tags)
    user_tags_map = {_normalize_tag_key(tag): tag for tag in user_include_tags}
    medical_tags_map = {_normalize_tag_key(tag): tag for tag in safety_exclude_tags}
    
    # Phép giao (Intersection) để lấy lỗi
    conflicting_tag_keys = set(user_tags_map.keys()).intersection(set(medical_tags_map.keys()))
    conflicting_tags = {user_tags_map[k] for k in conflicting_tag_keys}

    # Phép trừ (Difference) để lấy danh sách an toàn (Kiểu dữ liệu sinh ra là SET)
    safe_tag_keys = set(user_tags_map.keys()) - set(medical_tags_map.keys())
    safe_user_include_tags = {user_tags_map[k] for k in safe_tag_keys}
    
    all_conflicts = list(conflicting_ings) + list(conflicting_tags) + list(conflicting_category_tags)

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
        "user_dislike_ings": list(user_dislikes_ings),
        "allergy_constraints": list(allergy_constraints),
        "disease_constraints": list(disease_constraints),
        "allergy_exclude_ings": list(allergy_exclude_ings),
        "allergy_exclude_tags": list(allergy_exclude_tags),
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
