"""
Ho tro review category fields sau khi tach soft_tags.

Lenh thuong dung:

1. Xem tong quan:
venv/bin/python scripts/review_food_categories.py summary \
  --input 'standard-data/ingredients-data/raw_foods_enriched_labeled(final_488).categorized.json'

2. Xuat report cac item can review:
venv/bin/python scripts/review_food_categories.py export \
  --input 'standard-data/ingredients-data/raw_foods_enriched_labeled(final_488).categorized.json' \
  --output 'standard-data/ingredients-data/category_review_report.md'

3. Sau khi review/chinh JSON xong, tao file sach khong con category_review:
venv/bin/python scripts/review_food_categories.py strip \
  --input 'standard-data/ingredients-data/raw_foods_enriched_labeled(final_488).categorized.json' \
  --output 'standard-data/ingredients-data/raw_foods_enriched_labeled(final_488).categorized.clean.json' \
  --force
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


DEFAULT_INPUT = Path("standard-data/ingredients-data/raw_foods_enriched_labeled(final_488).categorized.json")


def load_items(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        items = json.load(f)
    if not isinstance(items, list):
        raise ValueError("Input JSON phai la list mon an")
    return items


def write_json(path: Path, items: list[dict], force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"Output da ton tai, dung --force de ghi de: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def category_stats(items: list[dict]) -> Counter:
    stats = Counter()
    for item in items:
        review = item.get("category_review") or {}
        if review.get("needs_review"):
            stats["needs_review"] += 1
        if not item.get("taste_profile"):
            stats["missing_taste_profile"] += 1
        if not item.get("meal_context"):
            stats["missing_meal_context"] += 1
        if not item.get("occasion_context"):
            stats["missing_occasion_context"] += 1
        for key in ["taste_profile_source", "meal_context_source", "occasion_context_source"]:
            source = review.get(key)
            if source:
                stats[f"{key}:{source}"] += 1
    return stats


def print_summary(items: list[dict]) -> None:
    stats = category_stats(items)
    print(f"Foods: {len(items)}")
    print(f"Needs review: {stats['needs_review']}")
    print(f"Missing taste_profile: {stats['missing_taste_profile']}")
    print(f"Missing meal_context: {stats['missing_meal_context']}")
    print(f"Missing occasion_context: {stats['missing_occasion_context']}")
    print("")
    print("Sources:")
    for key, count in sorted(stats.items()):
        if "_source:" in key:
            print(f"- {key}: {count}")


def build_review_report(items: list[dict]) -> str:
    lines = [
        "# Category Review Report",
        "",
        "Review cac mon co `category_review.needs_review = true`.",
        "Sua truc tiep trong file categorized JSON neu can, sau do chay lai lenh summary/strip.",
        "",
    ]

    needs_review = [
        (idx, item)
        for idx, item in enumerate(items)
        if (item.get("category_review") or {}).get("needs_review")
    ]
    lines.append(f"- Tong mon can review: {len(needs_review)}")
    lines.append("")

    for idx, item in needs_review:
        review = item.get("category_review") or {}
        lines += [
            f"## {idx}. {item.get('name', 'Không rõ tên')}",
            "",
            f"- soft_tags: {item.get('soft_tags', [])}",
            f"- taste_profile: {item.get('taste_profile', [])}",
            f"- meal_context: {item.get('meal_context', [])}",
            f"- occasion_context: {item.get('occasion_context', [])}",
            f"- sources: taste={review.get('taste_profile_source')}, meal={review.get('meal_context_source')}, occasion={review.get('occasion_context_source')}",
            f"- notes: {review.get('notes', [])}",
            "",
        ]
    return "\n".join(lines)


def export_report(input_path: Path, output_path: Path, force: bool) -> None:
    items = load_items(input_path)
    if output_path.exists() and not force:
        raise FileExistsError(f"Output da ton tai, dung --force de ghi de: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_review_report(items), encoding="utf-8")
    print(f"Exported review report: {output_path}")


def strip_review_metadata(input_path: Path, output_path: Path, force: bool) -> None:
    items = load_items(input_path)
    cleaned = []
    for item in items:
        copy = dict(item)
        copy.pop("category_review", None)
        cleaned.append(copy)
    write_json(output_path, cleaned, force=force)
    print(f"Wrote clean categorized data: {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Review/strip category fields")
    subparsers = parser.add_subparsers(dest="command", required=True)

    summary = subparsers.add_parser("summary", help="In thong ke review")
    summary.add_argument("--input", default=str(DEFAULT_INPUT))

    export = subparsers.add_parser("export", help="Xuat markdown report cac item can review")
    export.add_argument("--input", default=str(DEFAULT_INPUT))
    export.add_argument("--output", required=True)
    export.add_argument("--force", action="store_true")

    strip = subparsers.add_parser("strip", help="Xoa category_review va ghi file sach")
    strip.add_argument("--input", default=str(DEFAULT_INPUT))
    strip.add_argument("--output", required=True)
    strip.add_argument("--force", action="store_true")

    args = parser.parse_args()
    input_path = Path(args.input)

    if args.command == "summary":
        print_summary(load_items(input_path))
    elif args.command == "export":
        export_report(input_path, Path(args.output), force=args.force)
    elif args.command == "strip":
        strip_review_metadata(input_path, Path(args.output), force=args.force)


if __name__ == "__main__":
    main()
