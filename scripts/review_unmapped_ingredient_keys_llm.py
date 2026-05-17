"""Review unmapped ingredient base keys with an LLM.

Script này chỉ tạo file review đề xuất, không sửa alias rules, không cập nhật DB,
không thay đổi search flow.

Input mặc định:
- standard-data/alias-rules/ingredient_key_preview.v1.json
- standard-data/tags_data.json

Output mặc định:
- standard-data/alias-rules/unmapped_ingredient_key_llm_review.v1.json

Ví dụ:
venv/bin/python scripts/review_unmapped_ingredient_keys_llm.py \
  --limit 80 \
  --batch-size 20 \
  --force
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

# =====================================================================
# CẤU HÌNH KHỞI TẠO
# =====================================================================
PROJECT_ID = os.getenv("PROJECT_ID")
client = genai.Client(vertexai=True, project=PROJECT_ID, location="us-central1")



DEFAULT_PREVIEW_INPUT = Path("standard-data/alias-rules/ingredient_key_preview.v1.json")
DEFAULT_TAGS_INPUT = Path("standard-data/tags_data.json")
DEFAULT_OUTPUT = Path("standard-data/alias-rules/unmapped_ingredient_key_llm_review.v1.json")
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_BATCH_SIZE = 20


ACTION_VALUES = [
    "map_existing",
    "create_new_canon",
    "create_new_group",
    "no_mapping_needed",
    "needs_human_review",
]

CONFIDENCE_VALUES = ["high", "medium", "low"]


def strip_accents(value: str) -> str:
    """Bỏ dấu tiếng Việt để chuẩn hóa rule/raw text về cùng hệ base key."""
    value = unicodedata.normalize("NFD", value or "")
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    return value.replace("đ", "d").replace("Đ", "D")


def normalize_base_key(value: str) -> str:
    """Tạo base key snake_case giống script sinh ingredient preview."""
    value = strip_accents(value or "").lower()
    value = re.sub(r"[_\-/,.;:()\\[\\]{}]+", " ", value)
    value = re.sub(r"[^a-z0-9\s]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value.replace(" ", "_")


def dedupe_keep_order(values: Iterable[str]) -> list[str]:
    """Loại trùng nhưng giữ thứ tự để output ổn định, dễ review diff."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def load_json(path: Path) -> Any:
    """Đọc JSON UTF-8."""
    return json.loads(path.read_text(encoding="utf-8"))


def collect_existing_keys(alias_rules: list[dict]) -> tuple[list[str], list[str]]:
    """Lấy danh sách canon/group hiện có từ alias_rules trong preview."""
    canon_keys = sorted(
        {
            str(rule.get("canonical_key", "")).strip()
            for rule in alias_rules
            if str(rule.get("canonical_key", "")).startswith("canon:")
        }
    )
    group_keys = sorted(
        {
            str(group_key).strip()
            for rule in alias_rules
            for group_key in rule.get("group_keys", []) or []
            if str(group_key).startswith("group:")
        }
    )
    return canon_keys, group_keys


def collect_tag_rule_usage(tags_data: list[dict]) -> dict[str, dict]:
    """
    Gom nguyên liệu trong tags_data theo base key.

    Thông tin này giúp LLM biết một nguyên liệu unmapped có đang nằm trong
    exclude/prefer của bệnh lý nào hay không, từ đó ưu tiên map cẩn thận hơn.
    """
    usage: dict[str, dict] = defaultdict(lambda: {"exclude_in": [], "prefer_in": [], "raw_values": []})

    for tag in tags_data:
        tag_name = tag.get("name", "")
        for field, target in [("exclude_ingredient", "exclude_in"), ("prefer_ingredient", "prefer_in")]:
            for raw_value in tag.get(field, []) or []:
                base_key = f"base:{normalize_base_key(str(raw_value))}"
                usage[base_key][target].append(tag_name)
                usage[base_key]["raw_values"].append(str(raw_value))

    result = {}
    for base_key, data in usage.items():
        result[base_key] = {
            "exclude_in": sorted(set(data["exclude_in"])),
            "prefer_in": sorted(set(data["prefer_in"])),
            "raw_values": sorted(set(data["raw_values"])),
        }
    return result


def collect_unmapped_items(preview_data: dict, tags_data: list[dict], max_examples: int) -> list[dict]:
    """Tạo danh sách base key chưa map, kèm ví dụ món/nguyên liệu để gửi cho LLM."""
    tag_usage = collect_tag_rule_usage(tags_data)
    buckets: dict[str, dict] = defaultdict(
        lambda: {
            "count": 0,
            "ingredients": Counter(),
            "foods": [],
            "soft_tags": Counter(),
            "taste_profile": Counter(),
            "meal_context": Counter(),
            "occasion_context": Counter(),
        }
    )

    for food in preview_data.get("food_key_preview", []) or []:
        details_by_base = {
            detail.get("base_key"): detail
            for detail in food.get("ingredient_details", []) or []
        }

        for base_key in food.get("unmapped_base_keys", []) or []:
            detail = details_by_base.get(base_key, {})
            ingredient = detail.get("ingredient", base_key.removeprefix("base:"))
            bucket = buckets[base_key]
            bucket["count"] += 1
            bucket["ingredients"][ingredient] += 1
            bucket["soft_tags"].update(food.get("soft_tags", []) or [])
            bucket["taste_profile"].update(food.get("taste_profile", []) or [])
            bucket["meal_context"].update(food.get("meal_context", []) or [])
            bucket["occasion_context"].update(food.get("occasion_context", []) or [])
            if len(bucket["foods"]) < max_examples:
                bucket["foods"].append(
                    {
                        "name": food.get("name", ""),
                        "ingredient": ingredient,
                        "soft_tags": food.get("soft_tags", []) or [],
                    }
                )

    items = []
    for idx, (base_key, bucket) in enumerate(
        sorted(buckets.items(), key=lambda kv: (-kv[1]["count"], kv[0])),
        start=1,
    ):
        usage = tag_usage.get(base_key, {"exclude_in": [], "prefer_in": [], "raw_values": []})
        items.append(
            {
                "id": idx,
                "base_key": base_key,
                "count": bucket["count"],
                "representative_ingredients": [
                    {"ingredient": value, "count": count}
                    for value, count in bucket["ingredients"].most_common(8)
                ],
                "example_foods": bucket["foods"],
                "top_soft_tags": [
                    {"tag": tag, "count": count}
                    for tag, count in bucket["soft_tags"].most_common(8)
                ],
                "top_taste_profile": [
                    {"tag": tag, "count": count}
                    for tag, count in bucket["taste_profile"].most_common(5)
                ],
                "top_meal_context": [
                    {"tag": tag, "count": count}
                    for tag, count in bucket["meal_context"].most_common(5)
                ],
                "top_occasion_context": [
                    {"tag": tag, "count": count}
                    for tag, count in bucket["occasion_context"].most_common(5)
                ],
                "tags_data_usage": usage,
            }
        )

    return items


def build_system_instruction(existing_canon_keys: list[str], existing_group_keys: list[str]) -> str:
    """Prompt hệ thống hướng dẫn LLM đánh giá unmapped ingredient keys."""
    return f"""Bạn là chuyên gia chuẩn hóa dữ liệu nguyên liệu món ăn Việt Nam cho hệ thống gợi ý món ăn theo bệnh lý.

Nhiệm vụ: đánh giá các `unmapped_base_keys` chưa map được alias rule. Với mỗi item, hãy quyết định:
- Có nên map vào canon/group hiện có không?
- Có cần tạo canon mới không?
- Có cần tạo group mới không?
- Hay hoàn toàn không cần mapping vì nguyên liệu trung tính/không quan trọng cho filter bệnh lý?

QUY ƯỚC KEY:
- base:* là nguyên liệu gốc đã normalize, chỉ để trace/debug.
- canon:* là nguyên liệu chuẩn cụ thể, ví dụ canon:thit_bo, canon:nuoc_mam.
- group:* là nhóm y tế/dinh dưỡng rộng hơn, ví dụ group:hai_san, group:gia_vi_man_natri_cao.
- Tên key mới bắt buộc dùng tiếng Việt không dấu + snake_case.

CANON HIỆN CÓ:
{json.dumps(existing_canon_keys, ensure_ascii=False)}

GROUP HIỆN CÓ:
{json.dumps(existing_group_keys, ensure_ascii=False)}

ACTION HỢP LỆ:
1. map_existing: map vào canon/group hiện có.
2. create_new_canon: cần tạo canon mới, có thể kèm group hiện có.
3. create_new_group: cần tạo group mới vì nhóm y tế/dinh dưỡng rộng hơn chưa tồn tại.
4. no_mapping_needed: không cần map vì nguyên liệu trung tính, ít rủi ro, hoặc không hữu ích cho filter bệnh lý.
5. needs_human_review: dữ liệu mơ hồ/bẩn, LLM không đủ chắc.

NGUYÊN TẮC:
- Không gán quá rộng. Nếu không chắc, dùng needs_human_review.
- Không tạo group mới nếu chỉ là một nguyên liệu đơn lẻ; khi đó tạo canon mới hoặc no_mapping_needed.
- Chỉ đề xuất group mới nếu nó gom nhiều canon và có ý nghĩa filter bệnh lý/dinh dưỡng.
- Với nguyên liệu xuất hiện trong tags_data exclude_ingredient, ưu tiên kiểm tra kỹ hơn.
- Nếu nguyên liệu là đơn vị/định lượng/mô tả bẩn như 'ít', 'thìa', 'nhánh', hãy no_mapping_needed hoặc needs_human_review.
- Chú ý collision tiếng Việt sau bỏ dấu: bo/bơ/bò, sua/sữa/sứa, me/mè/me chua, ca/cá/cà, nam/nấm/nạm, dau/dầu/đậu, gia/giá/gia vị.
- Không trả text ngoài JSON schema.
"""


LLM_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "results": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "INTEGER"},
                    "base_key": {"type": "STRING"},
                    "action": {"type": "STRING", "enum": ACTION_VALUES},
                    "suggested_canon_keys": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                    },
                    "suggested_group_keys": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                    },
                    "proposed_aliases": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                    },
                    "confidence": {"type": "STRING", "enum": CONFIDENCE_VALUES},
                    "should_update_alias_rules": {"type": "BOOLEAN"},
                    "reasoning": {"type": "STRING"},
                },
                "required": [
                    "id",
                    "base_key",
                    "action",
                    "suggested_canon_keys",
                    "suggested_group_keys",
                    "proposed_aliases",
                    "confidence",
                    "should_update_alias_rules",
                    "reasoning",
                ],
            },
        }
    },
    "required": ["results"],
}


def normalize_llm_result(raw: dict, item_by_id: dict[int, dict]) -> dict:
    """Chuẩn hóa response của LLM để output ổn định và an toàn hơn."""
    item_id = int(raw.get("id", 0) or 0)
    source_item = item_by_id.get(item_id, {})
    action = raw.get("action") if raw.get("action") in ACTION_VALUES else "needs_human_review"
    confidence = raw.get("confidence") if raw.get("confidence") in CONFIDENCE_VALUES else "low"

    def clean_keys(values: Any, prefix: str) -> list[str]:
        if not isinstance(values, list):
            return []
        cleaned = []
        for value in values:
            text = str(value or "").strip()
            if not text:
                continue
            if not text.startswith(prefix):
                text = f"{prefix}{normalize_base_key(text)}"
            cleaned.append(text)
        return dedupe_keep_order(cleaned)

    aliases = raw.get("proposed_aliases", [])
    if not isinstance(aliases, list):
        aliases = []

    return {
        "id": item_id,
        "base_key": raw.get("base_key") or source_item.get("base_key", ""),
        "action": action,
        "suggested_canon_keys": clean_keys(raw.get("suggested_canon_keys", []), "canon:"),
        "suggested_group_keys": clean_keys(raw.get("suggested_group_keys", []), "group:"),
        "proposed_aliases": dedupe_keep_order(str(value).strip() for value in aliases if str(value).strip()),
        "confidence": confidence,
        "should_update_alias_rules": bool(raw.get("should_update_alias_rules", False)),
        "reasoning": str(raw.get("reasoning", "")).strip(),
        "source_item": source_item,
    }


def call_llm_batch(
    llm_client: Any,
    *,
    model: str,
    system_instruction: str,
    batch: list[dict],
) -> list[dict]:
    """Gọi LLM một batch unmapped items và trả về results raw."""
    from google.genai import types

    payload = [
        {
            "id": item["id"],
            "base_key": item["base_key"],
            "count": item["count"],
            "representative_ingredients": item["representative_ingredients"],
            "example_foods": item["example_foods"],
            "top_soft_tags": item["top_soft_tags"],
            "tags_data_usage": item["tags_data_usage"],
        }
        for item in batch
    ]

    response = llm_client.models.generate_content(
        model=model,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=LLM_RESPONSE_SCHEMA,
        ),
        contents=json.dumps(payload, ensure_ascii=False, indent=2),
    )
    data = json.loads(response.text)
    return data.get("results", []) or []


def main() -> None:
    """CLI entrypoint: gom unmapped_base_keys, gọi LLM, ghi file review."""
    parser = argparse.ArgumentParser(description="Use LLM to review unmapped ingredient base keys.")
    parser.add_argument("--preview", default=str(DEFAULT_PREVIEW_INPUT), help="ingredient_key_preview JSON")
    parser.add_argument("--tags", default=str(DEFAULT_TAGS_INPUT), help="tags_data.json")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="LLM review output JSON")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini model name")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="LLM batch size")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of unmapped keys to review")
    parser.add_argument("--offset", type=int, default=0, help="Skip first N unmapped keys")
    parser.add_argument("--max-examples", type=int, default=6, help="Max example foods per base key")
    parser.add_argument("--sleep", type=float, default=0.5, help="Sleep seconds between LLM batches")
    parser.add_argument("--force", action="store_true", help="Overwrite output if it exists")
    args = parser.parse_args()

    preview_path = Path(args.preview)
    tags_path = Path(args.tags)
    output_path = Path(args.output)

    if not preview_path.exists():
        raise FileNotFoundError(f"Preview input not found: {preview_path}")
    if not tags_path.exists():
        raise FileNotFoundError(f"Tags input not found: {tags_path}")
    if output_path.exists() and not args.force:
        raise FileExistsError(f"Output already exists, use --force to overwrite: {output_path}")

    preview_data = load_json(preview_path)
    tags_data = load_json(tags_path)
    alias_rules = preview_data.get("alias_rules", []) or []
    existing_canon_keys, existing_group_keys = collect_existing_keys(alias_rules)

    unmapped_items = collect_unmapped_items(preview_data, tags_data, max_examples=args.max_examples)
    selected_items = unmapped_items[args.offset :]
    if args.limit is not None:
        selected_items = selected_items[: args.limit]

    llm_client = client
    system_instruction = build_system_instruction(existing_canon_keys, existing_group_keys)

    results: list[dict] = []
    errors: list[dict] = []
    item_by_id = {item["id"]: item for item in selected_items}

    for start in range(0, len(selected_items), args.batch_size):
        batch = selected_items[start : start + args.batch_size]
        if not batch:
            continue
        try:
            raw_results = call_llm_batch(
                llm_client,
                model=args.model,
                system_instruction=system_instruction,
                batch=batch,
            )
            results.extend(normalize_llm_result(raw, item_by_id) for raw in raw_results)
        except Exception as exc:
            errors.append(
                {
                    "batch_start": start,
                    "batch_size": len(batch),
                    "error": str(exc),
                    "item_ids": [item["id"] for item in batch],
                }
            )
        if args.sleep and start + args.batch_size < len(selected_items):
            time.sleep(args.sleep)

    reviewed_ids = {item["id"] for item in results}
    missing_results = [
        {
            "id": item["id"],
            "base_key": item["base_key"],
            "reason": "LLM did not return a result for this item",
            "source_item": item,
        }
        for item in selected_items
        if item["id"] not in reviewed_ids
    ]

    action_counts = Counter(item["action"] for item in results)
    confidence_counts = Counter(item["confidence"] for item in results)

    output = {
        "metadata": {
            "source_preview_file": str(preview_path),
            "source_tags_file": str(tags_path),
            "model": args.model,
            "total_unmapped_base_keys": len(unmapped_items),
            "reviewed_offset": args.offset,
            "requested_review_count": len(selected_items),
            "returned_review_count": len(results),
            "note": "LLM suggestions only. Do not apply automatically without human review.",
        },
        "existing_canon_keys": existing_canon_keys,
        "existing_group_keys": existing_group_keys,
        "summary": {
            "action_counts": dict(sorted(action_counts.items())),
            "confidence_counts": dict(sorted(confidence_counts.items())),
            "errors_count": len(errors),
            "missing_results_count": len(missing_results),
        },
        "results": results,
        "missing_results": missing_results,
        "errors": errors,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Output: {output_path}")
    print(f"Total unmapped base keys: {len(unmapped_items)}")
    print(f"Requested review count: {len(selected_items)}")
    print(f"Returned review count: {len(results)}")
    print(f"Errors: {len(errors)}")
    print(f"Missing results: {len(missing_results)}")
    print(f"Action counts: {dict(sorted(action_counts.items()))}")


if __name__ == "__main__":
    main()
