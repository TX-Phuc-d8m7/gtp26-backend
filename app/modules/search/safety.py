"""Allergy text safety helpers shared by search and audit scripts.

The hard filter still relies on canonical ingredient keys first. This module
adds a conservative text fallback for allergy/intolerance constraints only,
using accented Vietnamese phrase matching over core ingredients.
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
    """Normalize text while preserving Vietnamese accents for safer matching."""
    text = unicodedata.normalize("NFC", str(value or "")).lower()
    text = re.sub(r"[_/(){}\[\],.;:!?+*='\"`~|\\<>-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_vietnamese_ascii(value: str) -> str:
    """Normalize text and remove Vietnamese accents for no-accent rule phrases."""
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("đ", "d").replace("Đ", "D")
    text = text.lower()
    text = re.sub(r"[_/(){}\[\],.;:!?+*='\"`~|\\<>-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def has_vietnamese_diacritic(value: str) -> bool:
    return normalize_vietnamese_ascii(value) != normalize_vietnamese_text(value)


def phrase_in_normalized_text(normalized_text: str, normalized_phrase: str) -> bool:
    if not normalized_phrase:
        return False
    return f" {normalized_phrase} " in f" {normalized_text} "


def phrase_in_text(text_value: str, phrase: str) -> bool:
    """Match a phrase as independent normalized tokens."""
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
    if isinstance(food, dict):
        return food.get(field_name)
    return getattr(food, field_name, None)


def coerce_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def build_allergy_text_source(food: Any) -> str:
    """Use core ingredients only; raw/preprocessing ingredients are excluded."""
    parts: list[str] = []
    parts.extend(coerce_text_list(get_field_value(food, "core_ingredients")))
    return " ".join(parts)


def build_allergy_text_items(food: Any) -> list[str]:
    """Return core ingredient items separately so exclusions stay local."""
    return coerce_text_list(get_field_value(food, "core_ingredients"))


def canonical_allergy_name(name: str) -> str:
    raw = (name or "").strip()
    if raw in get_allergen_text_patterns():
        return raw
    normalized = normalize_vietnamese_text(raw)
    return ALLERGY_TAG_ALIASES.get(normalized, raw)


def should_include_exclude_phrase(phrase: str) -> bool:
    normalized = normalize_vietnamese_text(phrase)
    if not normalized:
        return False
    words = normalized.split()
    if len(words) == 1 and words[0] in COLLISION_PRONE_UNACCENTED_WORDS:
        return False
    if any(word in COLLISION_PRONE_UNACCENTED_WORDS for word in words):
        return False
    return True


def load_tags_data_allergen_patterns() -> dict[str, list[str]]:
    """Load allergy exclude_ingredient phrases and refresh when tags_data.json changes."""
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
    """Return curated allergy text patterns merged with tags_data exclude_ingredient."""
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
    """Return curated patterns plus low-risk rule phrases for each allergy."""
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
    """Detect allergy phrase matches in core ingredient text."""
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
    return bool(detect_allergy_text_matches(
        food,
        allergy_constraints,
        allergy_exclude_ingredients,
    ))
