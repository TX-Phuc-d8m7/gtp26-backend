#!/usr/bin/env python3
"""Audit allergy hard-filter coverage against the current food JSON.

The report compares ingredient-key filtering with the allergy text fallback.
Text fallback uses core_ingredients only.
Use --strict in CI/rebuild workflows when text-only matches should fail the run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.allergy_safety_service import detect_allergy_text_matches  # noqa: E402
from services.ingredient_key_service import (  # noqa: E402
    generate_core_ingredient_keys,
    generate_filter_keys,
    has_any_ingredient_key,
)


DEFAULT_FOODS_PATH = PROJECT_ROOT / "standard-data" / "ingredients-data" / "food-clean-categorized" / "raw_foods_enriched_labeled(final_488).categorized.clean.json"
DEFAULT_TAGS_PATH = PROJECT_ROOT / "standard-data" / "tags_data.json"
DEFAULT_PREVIEW_PATH = PROJECT_ROOT / "standard-data" / "alias-rules" / "ingredient_key_preview.v1.json"
INGREDIENT_KEY_CACHE: dict[str, list[str]] = {}
FILTER_KEY_CACHE: dict[str, list[str]] = {}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_preview_keys(path: Path | None) -> dict[str, list[str]]:
    if not path or not path.exists():
        return {}
    data = load_json(path)
    preview_foods = data.get("food_key_preview") or data.get("food_previews") or []
    return {
        item.get("name"): item.get("core_ingredient_keys") or []
        for item in preview_foods
        if item.get("name")
    }


def cached_ingredient_keys(ingredient: str) -> list[str]:
    cache_key = ingredient or ""
    if cache_key not in INGREDIENT_KEY_CACHE:
        INGREDIENT_KEY_CACHE[cache_key] = generate_core_ingredient_keys([ingredient])
    return INGREDIENT_KEY_CACHE[cache_key]


def cached_filter_keys(ingredient: str) -> list[str]:
    cache_key = ingredient or ""
    if cache_key not in FILTER_KEY_CACHE:
        FILTER_KEY_CACHE[cache_key] = generate_filter_keys([ingredient])
    return FILTER_KEY_CACHE[cache_key]


def dedupe_keep_order(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def food_keys(food: dict) -> list[str]:
    cached_keys = food.get("_audit_core_ingredient_keys")
    if cached_keys:
        return cached_keys
    keys = food.get("core_ingredient_keys") or []
    if keys:
        return keys
    all_keys: list[str] = []
    for ingredient in food.get("core_ingredients") or []:
        all_keys.extend(cached_ingredient_keys(ingredient))
    return dedupe_keep_order(all_keys)


def filter_keys_for_ingredients(ingredients: list[str]) -> list[str]:
    keys: list[str] = []
    for ingredient in ingredients or []:
        keys.extend(cached_filter_keys(ingredient))
    return dedupe_keep_order(keys)


def precompute_food_keys(foods: list[dict], preview_keys: dict[str, list[str]]) -> None:
    preview_hit_count = 0
    for food in foods:
        keys = preview_keys.get(food.get("name"))
        if keys:
            preview_hit_count += 1
            food["_audit_core_ingredient_keys"] = keys
        else:
            food["_audit_core_ingredient_keys"] = food_keys(food)
    if preview_keys:
        print(f"Loaded preview core_ingredient_keys for {preview_hit_count}/{len(foods)} foods.")


def compact_matches(matches: list[dict[str, str]], limit: int = 5) -> list[dict[str, str]]:
    seen = set()
    compacted = []
    for match in matches:
        key = (match.get("allergy"), match.get("phrase"))
        if key in seen:
            continue
        seen.add(key)
        compacted.append(match)
        if len(compacted) >= limit:
            break
    return compacted


def print_list_block(label: str, values: list[str], *, indent: str = "    ") -> None:
    print(f"{indent}{label}:")
    if not values:
        print(f"{indent}  - (empty)")
        return
    for value in values:
        print(f"{indent}  - {value}")


def print_match_block(matches: list[dict[str, str]], *, indent: str = "    ") -> None:
    print(f"{indent}text_matches:")
    if not matches:
        print(f"{indent}  - (empty)")
        return
    for match in matches:
        print(
            f"{indent}  - allergy={match.get('allergy')} | "
            f"phrase={match.get('phrase')}"
        )


def audit_allergy_tag(
    tag: dict,
    foods: list[dict],
    max_examples: int,
) -> dict:
    allergy_name = tag.get("name") or "(unknown)"
    exclude_ingredients = tag.get("exclude_ingredient") or []
    allergy_keys = filter_keys_for_ingredients(exclude_ingredients)

    key_matches = []
    text_matches = []
    text_only_key_miss = []

    for food in foods:
        keys = food_keys(food)
        has_key_match = has_any_ingredient_key(keys, allergy_keys)
        matches = detect_allergy_text_matches(
            food,
            [allergy_name],
            exclude_ingredients,
        )
        has_text_match = bool(matches)

        if has_key_match:
            key_matches.append(food)
        if has_text_match:
            text_matches.append(food)
        if has_text_match and not has_key_match:
            text_only_key_miss.append({
                "name": food.get("name"),
                "matches": compact_matches(matches),
                "core_ingredients": food.get("core_ingredients") or [],
                "core_ingredient_keys": keys,
            })

    covered_names = {food.get("name") for food in key_matches + text_matches}
    return {
        "name": allergy_name,
        "allergy_keys": allergy_keys,
        "key_match_count": len(key_matches),
        "text_match_count": len(text_matches),
        "covered_count": len(covered_names),
        "text_only_key_miss_count": len(text_only_key_miss),
        "text_only_key_miss": text_only_key_miss[:max_examples],
    }


def print_report(reports: list[dict]) -> None:
    print("\nALLERGEN FILTER COVERAGE AUDIT")
    print("=" * 72)
    for report in reports:
        print(
            f"- {report['name']}: "
            f"key={report['key_match_count']} | "
            f"text={report['text_match_count']} | "
            f"covered={report['covered_count']} | "
            f"text_only_key_miss={report['text_only_key_miss_count']}"
        )
        if report["covered_count"] == 0:
            print("  ! Không có sample nào bị bắt bởi key hoặc text fallback.")
        if report["text_only_key_miss"]:
            print()
            print("  TEXT-ONLY KEY MISSES")
            print("  " + "-" * 68)
        for index, example in enumerate(report["text_only_key_miss"], 1):
            print(f"  [{index}] {example['name']}")
            print_match_block(example["matches"])
            print_list_block("core_ingredients", example["core_ingredients"])
            print_list_block("core_ingredient_keys", example["core_ingredient_keys"])
            print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--foods", default=str(DEFAULT_FOODS_PATH), help="Clean food JSON path")
    parser.add_argument("--tags", default=str(DEFAULT_TAGS_PATH), help="tags_data.json path")
    parser.add_argument("--preview", default=str(DEFAULT_PREVIEW_PATH), help="Optional ingredient key preview cache")
    parser.add_argument("--max-examples", type=int, default=20, help="Max key-miss examples per allergy")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero if coverage gaps are found")
    args = parser.parse_args()

    foods_path = Path(args.foods)
    tags_path = Path(args.tags)
    preview_path = Path(args.preview) if args.preview else None
    foods = load_json(foods_path)
    tags = load_json(tags_path)
    precompute_food_keys(foods, load_preview_keys(preview_path))

    allergy_tags = [tag for tag in tags if tag.get("tag_type") == "ALLERGY"]
    reports = [
        audit_allergy_tag(tag, foods, args.max_examples)
        for tag in allergy_tags
    ]
    print_report(reports)

    text_only_total = sum(report["text_only_key_miss_count"] for report in reports)
    no_coverage = [report["name"] for report in reports if report["covered_count"] == 0]

    print("=" * 72)
    print(f"Allergy tags audited: {len(reports)}")
    print(f"Total text-only key misses: {text_only_total}")
    if no_coverage:
        print(f"Tags without sample coverage: {', '.join(no_coverage)}")
    else:
        print("Tags without sample coverage: 0")

    if args.strict and (text_only_total or no_coverage):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
