"""
Pipeline:
1) Đọc bảng foods từ DB.
2) Sinh unique_ingredients.json.
3) Sinh ingredient_to_soft_tags_suggestions.json.
4) Sinh patch đề xuất cập nhật tags_data.json (KHÔNG ghi đè trực tiếp).

Chạy:
    python3 scripts/build_ingredient_guardrail_pipeline.py

Tuỳ chọn:
    python3 scripts/build_ingredient_guardrail_pipeline.py --min-frequency 2 --min-support 0.6
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


BASE_DIR = PROJECT_ROOT
TAGS_DATA_PATH = BASE_DIR / "tags_data.json"
UNIQUE_ING_PATH = BASE_DIR / "unique_ingredients.json"
SUGGESTIONS_PATH = BASE_DIR / "tags_suggestions_to_ingredients.json"
PATCH_PROPOSAL_PATH = BASE_DIR / "tags_data_patch_proposal.json"
PATCH_PREVIEW_PATH = BASE_DIR / "tags_data.patch.preview.md"


TAG_ALIAS_MAP = {
    # ==========================
    # 1. VỊ CHỦ ĐẠO
    # ==========================
    "dam da": "Đậm đà",
    "thanh dam": "Thanh đạm",
    "chua": "Chua",
    "cay": "Cay",
    "man": "Mặn",
    "ngot": "Ngọt",
    "dang": "Đắng",
    "beo ngay": "Béo ngậy",

    # ==========================
    # 2. NHIỆT ĐỘ & CẢM GIÁC
    # ==========================
    "nong hoi": "Nóng hổi",
    "thanh mat / giai nhiet": "Thanh mát / Giải nhiệt",
    "thanh mat/giai nhiet": "Thanh mát / Giải nhiệt",
    "mon lanh": "Món lạnh",

    # ==========================
    # 3. KẾT CẤU
    # ==========================
    "gion / gion rum": "Giòn / Giòn rụm",
    "gion/gion rum": "Giòn / Giòn rụm",
    "gion rum": "Giòn / Giòn rụm",
    "dai / san sat": "Dai / Sần sật",
    "dai/san sat": "Dai / Sần sật",
    "san sat": "Dai / Sần sật",
    "mem": "Mềm",
    "song / chin tai": "Sống / Chín tái",
    "song/chin tai": "Sống / Chín tái",

    # ==========================
    # 4. DẠNG MÓN
    # ==========================
    "mon nuoc": "Món nước",
    "mon kho": "Món khô",
    "nuoc sen set": "Nước sền sệt",
    "sen set": "Nước sền sệt",

    # ==========================
    # 5. PHƯƠNG PHÁP CHẾ BIẾN
    # ==========================
    "chien / ran": "Chiên / Rán",
    "chien/ran": "Chiên / Rán",
    "chien": "Chiên / Rán",
    "ran": "Chiên / Rán",
    "nuong": "Nướng",
    "hap / luoc": "Hấp / Luộc",
    "hap/luoc": "Hấp / Luộc",
    "xao": "Xào",
    "goi / nom / tron": "Gỏi / Nộm / Trộn",
    "goi/nom/tron": "Gỏi / Nộm / Trộn",
    "nom": "Gỏi / Nộm / Trộn",
    "tron": "Gỏi / Nộm / Trộn",
    "cuon / goi": "Cuốn / Gói",
    "cuon/goi": "Cuốn / Gói",
    "ham / ninh": "Hầm / Ninh",
    "ham/ninh": "Hầm / Ninh",
    "lau": "Lẩu",
    "kho / rim": "Kho / Rim",
    "kho/rim": "Kho / Rim",
    "sup": "Súp",
    "chao": "Cháo",
    "rang": "Rang",

    # ==========================
    # 6. NHÓM ĐỊA PHƯƠNG & DANH MỤC
    # ==========================
    "dac san da nang": "Đặc sản Đà Nẵng",
    "am thuc duong pho": "Ẩm thực đường phố",
    "mon viet truyen thong": "Món Việt truyền thống",
    "mon viet": "Món Việt truyền thống",
    "mon a": "Món Á",
    "mon au": "Món Âu",
    "do an nhanh": "Thức ăn nhanh", # Alias phổ biến
    "thuc an nhanh": "Thức ăn nhanh",
    "mon chay": "Món chay",
    "hai san": "Hải sản",
    "an sang": "Ăn sáng",
    "an trua": "Ăn trưa",
    "an toi": "Ăn tối",
    "an chieu / xe": "Ăn chiều / xế",
    "an chieu/xe": "Ăn chiều / xế",
    "an xe": "Ăn chiều / xế",
    "an khuya": "Ăn khuya",
    "an dem": "Ăn khuya",      # Alias phổ biến
    "an no": "Ăn no",
    "an vat": "Ăn vặt",
    "moi nhau": "Mồi nhậu",
    "do nhau": "Mồi nhậu",     # Alias phổ biến
    "trang mieng": "Tráng miệng",
    "giai ruou": "Giải rượu",
    "giai cam": "Giải cảm",
    "am bung": "Ấm bụng",

    # ==========================
    # 7. DINH DƯỠNG
    # ==========================
    "giau chat xo": "Giàu chất xơ",
    "giau dam": "Giàu đạm",
    "giau protein": "Giàu đạm", # Alias tiếng Anh
    "giau vitamin": "Giàu vitamin",
    "giau tinh bot": "Giàu tinh bột",
    "noi tang": "Nội tạng",
    "sua / pho mai": "Từ sữa / Phô mai", # Alias cũ
    "tu sua / pho mai": "Từ sữa / Phô mai",
    "tu sua/pho mai": "Từ sữa / Phô mai",
    "thuc pham che bien san": "Thực phẩm chế biến sẵn",
    "banh ngot": "Bánh ngọt",

    # ==========================
    # 8. TIÊU HOÁ
    # ==========================
    "de tieu": "Dễ tiêu",
    "kho tieu / nang bung": "Khó tiêu / Nặng bụng",
    "kho tieu/nang bung": "Khó tiêu / Nặng bụng",
    "nang bung": "Khó tiêu / Nặng bụng",
    "healthy / eat clean": "Healthy / Eat Clean",
    "healthy/eat clean": "Healthy / Eat Clean",
    "eat clean": "Healthy / Eat Clean",
    "nhieu dau mo / calo cao": "Nhiều dầu mỡ / Calo cao",
    "nhieu dau mo/calo cao": "Nhiều dầu mỡ / Calo cao",
    "calo cao": "Nhiều dầu mỡ / Calo cao",
}


# Heuristic map theo "sổ đen nguyên liệu" -> soft tags rủi ro.
# Có thể mở rộng dần theo review thực tế.
HEURISTIC_INGREDIENT_SOFT_TAGS: dict[str, list[str]] = {
    r"\b(vit|thit vit|ngan|thit ngan)\b": ["Khó tiêu / Nặng bụng"],
    r"\b(mo heo|mo lon|thit ba chi|da heo|da ga|da vit)\b": ["Béo ngậy", "Khó tiêu / Nặng bụng"],
    r"\b(pho mai|whipping cream|kem tuoi|bot beo|nuoc cot dua)\b": ["Béo ngậy"],
    r"\b(ngai cuu|kho qua|muop dang|la dang)\b": ["Đắng"],
    r"\b(mam tom|mam ruoc|mam nem|mam tep|mam cai)\b": ["Mặn", "Khó tiêu / Nặng bụng"],
    r"\b(ot|sa te|tieu)\b": ["Cay"],
    r"\b(noi tang|gan|long|me|tim|than|oc heo|tiet)\b": ["Nội tạng", "Khó tiêu / Nặng bụng"],
    r"\b(chanh|tac|quat|me|giam|dam)\b": ["Chua"],
}


@dataclass
class IngredientStats:
    count: int
    food_names_sample: list[str]
    tag_counter: dict[str, int]


def _strip_accents(text: str) -> str:
    accents = {
        "àáạảãâầấậẩẫăằắặẳẵ": "a",
        "èéẹẻẽêềếệểễ": "e",
        "ìíịỉĩ": "i",
        "òóọỏõôồốộổỗơờớợởỡ": "o",
        "ùúụủũưừứựửữ": "u",
        "ỳýỵỷỹ": "y",
        "đ": "d",
    }
    result = text
    for source, target in accents.items():
        for ch in source:
            result = result.replace(ch, target).replace(ch.upper(), target.upper())
    return result


def normalize_text(value: str) -> str:
    s = (value or "").strip().lower()
    s = _strip_accents(s)
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"\d+[.,]?\d*\s*(g|kg|ml|l|muong|thia|qua|trai|tep|cay)\b", " ", s)
    s = re.sub(r"[^a-z0-9/\s-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_ingredient(ingredient: str) -> str:
    normalized = normalize_text(ingredient)
    normalized = re.sub(
        r"\b(tuoi|song|chin|thai lat|bam|xay|uop|luoc|hap|chien|nuong)\b",
        " ",
        normalized,
    )
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def normalize_tag_key(tag: str) -> str:
    return normalize_text(tag).replace(" ", "")


def canonicalize_tag(tag: str) -> str | None:
    raw = (tag or "").strip()
    if not raw:
        return None
    compact = normalize_text(raw)
    mapped = TAG_ALIAS_MAP.get(compact, raw)
    return mapped.strip()


def suggest_tags_by_heuristic(ingredient: str) -> list[str]:
    norm = normalize_text(ingredient)
    suggested: list[str] = []
    for pattern, tags in HEURISTIC_INGREDIENT_SOFT_TAGS.items():
        if re.search(pattern, norm):
            for tag in tags:
                if tag not in suggested:
                    suggested.append(tag)
    return suggested


async def fetch_foods() -> list[dict[str, Any]]:
    try:
        from sqlalchemy import select
        from database import AsyncSessionLocal
        from models import Food
    except ModuleNotFoundError as exc:
        missing_pkg = str(exc).split("'")[-2] if "'" in str(exc) else str(exc)
        raise RuntimeError(
            f"Thiếu dependency '{missing_pkg}'. Cài bằng: pip3 install {missing_pkg}"
        ) from exc

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Food.name, Food.core_ingredients, Food.soft_tags))
        rows = result.all()
    foods: list[dict[str, Any]] = []
    for name, core_ingredients, soft_tags in rows:
        foods.append(
            {
                "name": name,
                "core_ingredients": core_ingredients or [],
                "soft_tags": [t for t in (soft_tags or []) if t],
            }
        )
    return foods


def build_ingredient_stats(foods: list[dict[str, Any]]) -> dict[str, IngredientStats]:
    ingredient_counter: Counter[str] = Counter()
    ingredient_tag_counter: dict[str, Counter[str]] = defaultdict(Counter)
    ingredient_food_sample: dict[str, list[str]] = defaultdict(list)

    for food in foods:
        canonical_tags = [canonicalize_tag(t) for t in food["soft_tags"]]
        canonical_tags = [t for t in canonical_tags if t]

        seen_in_food: set[str] = set()
        for ingredient in food["core_ingredients"] or []:
            ing = normalize_ingredient(ingredient)
            if not ing:
                continue
            if ing in seen_in_food:
                continue
            seen_in_food.add(ing)

            ingredient_counter[ing] += 1
            if len(ingredient_food_sample[ing]) < 5:
                ingredient_food_sample[ing].append(food["name"])

            for tag in canonical_tags:
                ingredient_tag_counter[ing][tag] += 1

    stats: dict[str, IngredientStats] = {}
    for ing, count in ingredient_counter.items():
        stats[ing] = IngredientStats(
            count=count,
            food_names_sample=ingredient_food_sample[ing],
            tag_counter=dict(ingredient_tag_counter[ing]),
        )
    return stats


def build_unique_ingredients_json(stats: dict[str, IngredientStats]) -> list[dict[str, Any]]:
    rows = []
    for ingredient, s in stats.items():
        rows.append(
            {
                "ingredient": ingredient,
                "count_in_foods": s.count,
                "sample_foods": s.food_names_sample,
            }
        )
    rows.sort(key=lambda x: (-x["count_in_foods"], x["ingredient"]))
    return rows


def build_suggestions_json(
    stats: dict[str, IngredientStats],
    min_frequency: int,
    min_support: float,
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []

    for ingredient, s in sorted(stats.items(), key=lambda x: (-x[1].count, x[0])):
        if s.count < min_frequency:
            continue

        heuristic_tags = suggest_tags_by_heuristic(ingredient)
        cooccur_tags = []
        for tag, cooccur_count in sorted(s.tag_counter.items(), key=lambda x: (-x[1], x[0])):
            support = cooccur_count / s.count if s.count else 0
            if support >= min_support and cooccur_count >= 2:
                cooccur_tags.append(
                    {"tag": tag, "support": round(support, 3), "cooccur_count": cooccur_count}
                )

        merged_tags: list[str] = []
        for t in heuristic_tags + [x["tag"] for x in cooccur_tags]:
            if t not in merged_tags:
                merged_tags.append(t)

        if not merged_tags:
            continue

        suggestions.append(
            {
                "ingredient": ingredient,
                "count_in_foods": s.count,
                "suggested_soft_tags": merged_tags,
                "heuristic_tags": heuristic_tags,
                "cooccurrence_evidence": cooccur_tags,
                "sample_foods": s.food_names_sample,
            }
        )

    return suggestions


def build_tags_patch_proposal(
    tags_data: list[dict[str, Any]],
    suggestions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    suggestion_map: dict[str, set[str]] = {}
    for row in suggestions:
        suggestion_map[row["ingredient"]] = set(row["suggested_soft_tags"])

    proposal_updates: list[dict[str, Any]] = []
    preview_lines = [
        "# Patch preview for tags_data.json",
        "",
        "Danh sách dưới đây chỉ là đề xuất. Script KHÔNG ghi đè tags_data.json.",
        "",
    ]

    for rule in tags_data:
        rule_name = rule.get("name", "")
        exclude_soft_tags = [canonicalize_tag(t) for t in rule.get("exclude_soft_tag", [])]
        exclude_soft_tags = [t for t in exclude_soft_tags if t]
        exclude_soft_tag_set = set(exclude_soft_tags)

        if not exclude_soft_tag_set:
            continue

        current_exclude_ings = {normalize_ingredient(i): i for i in rule.get("exclude_ingredient", []) if i}
        to_add: list[str] = []

        for ing, ing_tags in suggestion_map.items():
            if ing in current_exclude_ings:
                continue
            if exclude_soft_tag_set.intersection(ing_tags):
                to_add.append(ing)

        if not to_add:
            continue

        to_add_sorted = sorted(set(to_add))
        proposal_updates.append(
            {
                "rule_name": rule_name,
                "matched_exclude_soft_tags": sorted(exclude_soft_tag_set),
                "proposed_add_exclude_ingredient": to_add_sorted,
                "proposed_add_count": len(to_add_sorted),
            }
        )

        preview_lines.append(f"## {rule_name}")
        preview_lines.append(f"- matched_exclude_soft_tags: {sorted(exclude_soft_tag_set)}")
        preview_lines.append(f"- add {len(to_add_sorted)} ingredients:")
        for ing in to_add_sorted[:30]:
            preview_lines.append(f"  - {ing}")
        if len(to_add_sorted) > 30:
            preview_lines.append(f"  - ... (+{len(to_add_sorted) - 30} more)")
        preview_lines.append("")

    return proposal_updates, preview_lines


async def run_pipeline(min_frequency: int, min_support: float) -> None:
    print("🔎 Đang đọc dữ liệu từ DB foods...")
    foods = await fetch_foods()
    if not foods:
        raise RuntimeError("Không có dữ liệu foods trong DB.")
    print(f"✅ Đã đọc {len(foods)} món.")

    stats = build_ingredient_stats(foods)
    unique_rows = build_unique_ingredients_json(stats)
    UNIQUE_ING_PATH.write_text(json.dumps(unique_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ Đã sinh {UNIQUE_ING_PATH.name} ({len(unique_rows)} nguyên liệu).")

    suggestions = build_suggestions_json(stats, min_frequency=min_frequency, min_support=min_support)
    SUGGESTIONS_PATH.write_text(json.dumps(suggestions, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ Đã sinh {SUGGESTIONS_PATH.name} ({len(suggestions)} gợi ý).")

    tags_data = json.loads(TAGS_DATA_PATH.read_text(encoding="utf-8"))
    proposal_updates, preview_lines = build_tags_patch_proposal(tags_data, suggestions)

    patch_payload = {
        "meta": {
            "source_table": "foods",
            "source_columns": ["core_ingredients", "soft_tags"],
            "min_frequency": min_frequency,
            "min_support": min_support,
            "note": "Đề xuất update exclude_ingredient theo exclude_soft_tag. KHÔNG tự động ghi đè tags_data.json.",
        },
        "proposed_rule_updates": proposal_updates,
    }
    PATCH_PROPOSAL_PATH.write_text(json.dumps(patch_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    PATCH_PREVIEW_PATH.write_text("\n".join(preview_lines), encoding="utf-8")

    print(
        f"✅ Đã sinh {PATCH_PROPOSAL_PATH.name} và {PATCH_PREVIEW_PATH.name} "
        f"({len(proposal_updates)} rule có đề xuất)."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build ingredient guardrail suggestions from DB foods.")
    parser.add_argument(
        "--min-frequency",
        type=int,
        default=2,
        help="Tần suất tối thiểu của nguyên liệu để xét gợi ý.",
    )
    parser.add_argument(
        "--min-support",
        type=float,
        default=0.6,
        help="Ngưỡng support co-occurrence ingredient <-> soft_tag (0-1).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(run_pipeline(min_frequency=args.min_frequency, min_support=args.min_support))
