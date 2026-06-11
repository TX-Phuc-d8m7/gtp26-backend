from __future__ import annotations

import argparse
import asyncio
import contextlib
import csv
import io
import json
import os
import re
import statistics
import sys
import time
import traceback
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

# Ensure backend root is in path.
BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(BACKEND_ROOT / ".env")
except Exception:
    pass

from app.db.session import AsyncSessionLocal
from app.modules.search.schemas import SearchResponse
from app.modules.search.service import search_food
from google import genai
from google.genai import types


DEFAULT_BENCHMARK_CSV = (
    BACKEND_ROOT.parent / "[GTP26] Test case - Test Case bệnh lý.csv"
)
DEFAULT_EXTENDED_CSV = (
    Path("/Users/truongxuanphuc/Downloads/[GTP26] Test case - Bổ sung 4 Pattern.csv")
)
DEFAULT_OUTPUT_DIR = BACKEND_ROOT / "reports" / "pathology_tests"
TAGS_DATA_PATH = BACKEND_ROOT / "standard-data" / "tags_data.json"

FALSE_POSITIVE_EXCEPTIONS = {
    "Dị ứng động vật thân mềm": [
        "nấm sò",
        "nấm sò nâu",
        "nấm bào ngư",
    ],
    "Dị ứng cá có vây": [
        "cá nhân",
        "cá tính",
    ],
    "Dị ứng sữa bò": [
        "sữa đậu nành",
        "sữa hạt",
    ],
}

PATTERN_LABELS = {
    "POSITIVE FRAMING": "Positive Framing",
    "VAGUE SYMPTOM": "Vague Symptom",
    "MEAL-TIME CONTEXT": "Meal-Time Context",
    "HIDDEN INGREDIENT": "Hidden Ingredient",
}

JUDGE_PROMPT = """Bạn là một kiểm thử viên y tế và dinh dưỡng độc lập chuyên đánh giá hệ thống gợi ý món ăn.
Hãy đánh giá kết quả gợi ý của hệ thống đối với test case sau đây:

MÃ TEST CASE: {id}
TÊN TEST CASE (TAG KIỂM CHỨNG): {tag}
NHÓM BỆNH/DỊ ỨNG: {category}
LOẠI BỘ TEST: {source_label}
NHÓM PATTERN MỞ RỘNG: {pattern_group}
TRUY VẤN CỦA USER: "{query}"
MỤC TIÊU KIỂM THỬ: {objective}
KẾT QUẢ MONG ĐỢI: {expected}

--- KẾT QUẢ THỰC TẾ TỪ HỆ THỐNG ---
1. Các ràng buộc sức khỏe trích xuất được (ai_insight):
   - Exclude (Kiêng): {exclude}
   - Include (Ưu tiên): {include}
   - Prefer (Gợi ý mềm): {prefer}
   - Cảnh báo (warning_message): {warning_message}

2. Danh sách món ăn được đề xuất (Top 5):
{food_results_str}

3. Lời khuyên tự nhiên từ AI (ai_response):
"{ai_response}"

--- YÊU CẦU ĐÁNH GIÁ ---
Hãy phân tích cẩn thận xem kết quả thực tế có tuân thủ đầy đủ "KẾT QUẢ MONG ĐỢI" hay không.
Hãy kiểm tra:
1. Có món ăn nào chứa nguyên liệu bị cấm hoặc vi phạm quy tắc an toàn không?
2. Câu trả lời của AI có cảnh báo chính xác và rõ ràng về thành phần xung đột/bệnh lý không?
3. Hệ thống có xử lý hợp lý khi sở thích người dùng xung đột với ràng buộc sức khỏe không?

Hãy quyết định trạng thái kiểm thử là "PASS" (Đạt) hoặc "FAIL" (Không đạt).
Chỉ ghi FAIL nếu có vi phạm nghiêm trọng về an toàn thực phẩm/y tế hoặc vi phạm trực tiếp Expected Result.
Nếu kết quả gợi ý an toàn nhưng có thể cải thiện nhẹ, hãy đánh giá PASS kèm nhận xét.

Định dạng trả về duy nhất dưới dạng JSON sau:
{{
  "status": "PASS" hoặc "FAIL",
  "reason": "Lý do ngắn gọn bằng tiếng Việt giải thích cho quyết định của bạn..."
}}
"""

_TAG_RULE_CACHE: dict[str, list[str]] | None = None


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text or "")
    without_accents = "".join(
        ch for ch in normalized if unicodedata.category(ch) != "Mn"
    )
    without_accents = without_accents.replace("đ", "d").replace("Đ", "D")
    return " ".join(without_accents.lower().strip().split())


def normalize_header(value: str) -> str:
    value = (value or "").replace("\ufeff", "").strip()
    return " ".join(value.split())


def normalize_category(value: str) -> str:
    clean = normalize_text(value)
    if "di ung" in clean:
        return "Dị ứng"
    if "benh ly" in clean and "ho hap" not in clean:
        return "Bệnh lý"
    if "trieu chung" in clean or "tinh trang" in clean:
        return "Triệu chứng/tình trạng"
    if "tich hop" in clean:
        return "Tích hợp"
    return value.strip() or "Khác"


def phrase_matches(text: str, phrase: str) -> bool:
    text = normalize_text(text)
    phrase = normalize_text(phrase)
    if not text or not phrase:
        return False
    return (
        f" {phrase} " in f" {text} "
        or text.startswith(f"{phrase} ")
        or text.endswith(f" {phrase}")
        or text == phrase
    )


def has_normalized_token(text: str, token: str) -> bool:
    normalized = normalize_text(text)
    normalized_token = normalize_text(token)
    if not normalized or not normalized_token:
        return False
    return bool(
        re.search(rf"(?<!\w){re.escape(normalized_token)}(?!\w)", normalized)
    )


def is_false_positive_match(rule_name: str, text: str, word: str) -> bool:
    raw_text = " ".join((text or "").lower().strip().split())
    normalized_text = normalize_text(text)
    word = normalize_text(word)

    if word == "chao":
        has_chao = bool(re.search(r"(?<!\w)chao(?!\w)", raw_text))
        has_chao_soup = bool(re.search(r"(?<!\w)cháo(?!\w)", raw_text))
        if has_chao_soup and not has_chao:
            return True

    bell_pepper_pattern = r"(?<!\w)ot chuong(?:\s+(?:do|vang|xanh|ngot))?(?!\w)"
    if word == "ot" and re.search(bell_pepper_pattern, normalized_text):
        text_without_bell_pepper = re.sub(
            bell_pepper_pattern,
            " ",
            normalized_text,
        )
        if not has_normalized_token(text_without_bell_pepper, "ớt"):
            return True

    exceptions = FALSE_POSITIVE_EXCEPTIONS.get(rule_name, [])
    return any(phrase_matches(normalized_text, exception) for exception in exceptions)


def load_tag_exclusion_rules() -> dict[str, list[str]]:
    global _TAG_RULE_CACHE
    if _TAG_RULE_CACHE is not None:
        return _TAG_RULE_CACHE

    if not TAGS_DATA_PATH.exists():
        print(f"Không tìm thấy tags_data.json tại: {TAGS_DATA_PATH}")
        _TAG_RULE_CACHE = {}
        return _TAG_RULE_CACHE

    with TAGS_DATA_PATH.open(mode="r", encoding="utf-8") as f:
        tags_data = json.load(f)

    rules: dict[str, list[str]] = {}
    for item in tags_data:
        name = item.get("name")
        exclude_ingredients = item.get("exclude_ingredient") or []
        if name and exclude_ingredients:
            rules[name] = [
                ingredient.strip()
                for ingredient in exclude_ingredients
                if isinstance(ingredient, str) and ingredient.strip()
            ]

    _TAG_RULE_CACHE = rules
    return rules


def extract_pattern_group(row: list[str]) -> str | None:
    joined = " ".join(cell.strip() for cell in row if cell and cell.strip())
    if "PATTERN" not in joined.upper():
        return None
    for raw, label in PATTERN_LABELS.items():
        if raw in joined.upper():
            return label
    match = re.search(r"PATTERN\s+\d+:\s*([A-Z -]+)", joined.upper())
    if match:
        return match.group(1).title()
    return joined.strip("─ -")


def parse_csv_file(csv_path: Path, source_kind: str) -> list[dict[str, str]]:
    test_cases: list[dict[str, str]] = []
    if not csv_path.exists():
        raise FileNotFoundError(f"File CSV không tồn tại: {csv_path}")

    header: list[str] | None = None
    current_pattern = ""

    with csv_path.open(mode="r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or not any(cell.strip() for cell in row):
                continue

            pattern = extract_pattern_group(row)
            if pattern:
                current_pattern = pattern
                continue

            normalized_row = [normalize_header(cell) for cell in row]
            if "Test Case ID" in normalized_row:
                header = normalized_row
                continue

            if header is None:
                continue

            row_map = {
                header[idx]: normalized_row[idx]
                for idx in range(min(len(header), len(normalized_row)))
                if header[idx]
            }
            tc_id = row_map.get("Test Case ID", "").strip()
            if not tc_id.startswith(("TC-", "OB-", "GAS-", "HBP-")):
                continue

            category = row_map.get("Nhóm", "").strip()
            test_cases.append(
                {
                    "id": tc_id,
                    "category": normalize_category(category),
                    "raw_category": category,
                    "tag": row_map.get("Tag kiểm chứng", "").strip(),
                    "query": row_map.get("Prompt test", "").strip(),
                    "objective": row_map.get("Mục tiêu kiểm thử", "").strip(),
                    "expected": row_map.get("Expected Result", "").strip(),
                    "suggested": row_map.get("Món ăn đang gợi ý", "").strip(),
                    "source_kind": source_kind,
                    "source_label": (
                        "Benchmark 35 case"
                        if source_kind == "benchmark"
                        else "Extended pattern case"
                    ),
                    "pattern_group": current_pattern if source_kind == "extended" else "",
                    "source_file": str(csv_path),
                }
            )

    return test_cases


def parse_all_test_cases(
    benchmark_paths: list[Path],
    extended_paths: list[Path],
) -> list[dict[str, str]]:
    test_cases: list[dict[str, str]] = []
    for path in benchmark_paths:
        test_cases.extend(parse_csv_file(path, "benchmark"))
    for path in extended_paths:
        test_cases.extend(parse_csv_file(path, "extended"))

    seen: set[str] = set()
    duplicates: list[str] = []
    for tc in test_cases:
        if tc["id"] in seen:
            duplicates.append(tc["id"])
        seen.add(tc["id"])
    if duplicates:
        raise ValueError(f"Trùng Test Case ID: {', '.join(sorted(set(duplicates)))}")

    return test_cases


def run_programmatic_checks(
    tc: dict[str, str],
    results: list[dict[str, Any]],
) -> list[str]:
    violations: list[str] = []
    category = tc["category"]
    tag = tc["tag"]
    rules = load_tag_exclusion_rules()

    for rule_name, forbidden_words in rules.items():
        if rule_name not in tag and rule_name not in category:
            continue
        for word in forbidden_words:
            for result in results:
                name = result["name"]
                if phrase_matches(name, word) and not is_false_positive_match(
                    rule_name, name, word
                ):
                    violations.append(
                        f"Món ăn '{name}' chứa từ khóa cấm trong tên: '{word}'"
                    )
                for ing in result.get("ingredients", []):
                    if phrase_matches(ing, word) and not is_false_positive_match(
                        rule_name, ing, word
                    ):
                        violations.append(
                            f"Món '{name}' có nguyên liệu '{ing}' chứa từ khóa cấm: '{word}'"
                        )

    return sorted(set(violations))


def build_judge_client() -> genai.Client:
    project_id = os.getenv("PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
    if project_id:
        return genai.Client(vertexai=True, project=project_id, location="us-central1")
    return genai.Client(api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))


async def evaluate_llm_judge(
    tc: dict[str, str],
    actual_response: SearchResponse,
    client: genai.Client,
    judge_model: str,
    timeout_seconds: float,
) -> dict[str, str]:
    food_results_str = ""
    for idx, result in enumerate(actual_response.results, 1):
        food_results_str += f"  #{idx}. {result.name}\n"
        food_results_str += f"       Nguyên liệu chính: {result.core_ingredients}\n"
        food_results_str += f"       Tính chất (soft_tags): {result.soft_tags}\n"
        food_results_str += (
            f"       Vị: {result.taste_profile} | "
            f"Ngữ cảnh bữa ăn: {result.meal_context} | "
            f"Ngữ cảnh dịp: {result.occasion_context}\n"
        )
        food_results_str += f"       Lý do gợi ý: {result.reason}\n\n"

    prompt = JUDGE_PROMPT.format(
        id=tc["id"],
        tag=tc["tag"],
        category=tc["category"],
        source_label=tc["source_label"],
        pattern_group=tc["pattern_group"] or "Không áp dụng",
        query=tc["query"],
        objective=tc["objective"],
        expected=tc["expected"],
        exclude=actual_response.ai_insight.exclude,
        include=actual_response.ai_insight.include,
        prefer=actual_response.ai_insight.prefer,
        warning_message=actual_response.ai_insight.warning_message,
        food_results_str=food_results_str,
        ai_response=actual_response.ai_response or "",
    )

    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(
                client.models.generate_content,
                model=judge_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "status": types.Schema(
                                type=types.Type.STRING,
                                enum=["PASS", "FAIL"],
                            ),
                            "reason": types.Schema(type=types.Type.STRING),
                        },
                        required=["status", "reason"],
                    ),
                    temperature=0.0,
                ),
            ),
            timeout=timeout_seconds,
        )
        result = json.loads(response.text)
        return {
            "status": str(result.get("status", "FAIL")).upper(),
            "reason": str(result.get("reason", "")).strip(),
        }
    except asyncio.TimeoutError:
        reason = f"LLM Judge timeout sau {timeout_seconds:.0f} giây"
        print(f"Lỗi khi gọi LLM Judge cho {tc['id']}: {reason}")
        return {"status": "FAIL", "reason": reason}
    except Exception as exc:
        print(f"Lỗi khi gọi LLM Judge cho {tc['id']}: {exc}")
        return {"status": "FAIL", "reason": f"Lỗi hệ thống LLM Judge: {exc}"}


async def run_single_test(
    tc: dict[str, str],
    db: Any,
    judge_client: genai.Client | None,
    judge_model: str,
    judge_timeout_seconds: float,
    top_k: int,
    skip_judge: bool,
    show_search_log: bool,
) -> dict[str, Any]:
    print(f"Đang chạy {tc['id']}: {tc['query']}")
    start_time = time.perf_counter()

    try:
        if show_search_log:
            search_res = await search_food(tc["query"], db, top_k=top_k)
        else:
            with contextlib.redirect_stdout(io.StringIO()):
                search_res = await search_food(tc["query"], db, top_k=top_k)
        latency_ms = round((time.perf_counter() - start_time) * 1000)

        results_list = [
            {
                "name": result.name,
                "ingredients": result.core_ingredients,
                "soft_tags": result.soft_tags,
                "taste_profile": result.taste_profile,
                "meal_context": result.meal_context,
                "occasion_context": result.occasion_context,
                "reason": result.reason,
                "matchScore": result.matchScore,
            }
            for result in search_res.results
        ]

        programmatic_violations = run_programmatic_checks(tc, results_list)
        if skip_judge:
            judge_result = {
                "status": "PASS",
                "reason": "Bỏ qua LLM-as-a-Judge; chỉ chạy programmatic checks.",
            }
        else:
            assert judge_client is not None
            judge_result = await evaluate_llm_judge(
                tc,
                search_res,
                judge_client,
                judge_model,
                judge_timeout_seconds,
            )

        status = judge_result["status"]
        reason = judge_result["reason"]
        if programmatic_violations:
            status = "FAIL"
            reason = (
                "[Vi phạm nguyên liệu cấm phát hiện tự động]: "
                + "; ".join(programmatic_violations)
                + ". "
                + reason
            )

        print(f"  -> {status} ({latency_ms}ms). {reason}\n")

        return {
            **tc,
            "actual_dishes": [result.name for result in search_res.results],
            "actual_dishes_text": ", ".join(result.name for result in search_res.results),
            "ai_insight": {
                "exclude": search_res.ai_insight.exclude,
                "include": search_res.ai_insight.include,
                "prefer": search_res.ai_insight.prefer,
                "warning_message": search_res.ai_insight.warning_message,
            },
            "ai_response": search_res.ai_response,
            "judge_status": judge_result["status"],
            "judge_reason": judge_result["reason"],
            "programmatic_violations": programmatic_violations,
            "hard_filter_violation": bool(programmatic_violations),
            "status": status,
            "reason": reason,
            "latency_ms": latency_ms,
        }
    except Exception as exc:
        latency_ms = round((time.perf_counter() - start_time) * 1000)
        print(f"Lỗi nghiêm trọng khi chạy {tc['id']}: {exc}")
        traceback.print_exc()
        return {
            **tc,
            "actual_dishes": [],
            "actual_dishes_text": "",
            "ai_insight": {},
            "ai_response": "",
            "judge_status": "FAIL",
            "judge_reason": "",
            "programmatic_violations": [],
            "hard_filter_violation": False,
            "status": "FAIL",
            "reason": f"Lỗi hệ thống trong lúc chạy test: {exc}",
            "latency_ms": latency_ms,
        }


def percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = (len(sorted_values) - 1) * percent
    lower = int(index)
    upper = min(lower + 1, len(sorted_values) - 1)
    if lower == upper:
        return float(sorted_values[lower])
    weight = index - lower
    return float(sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight)


def summarize_group(results: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        label = result.get(key) or "Không áp dụng"
        grouped[str(label)].append(result)

    rows = []
    for label in sorted(grouped):
        items = grouped[label]
        passed = sum(1 for item in items if item["status"] == "PASS")
        failed = len(items) - passed
        rows.append(
            {
                "group": label,
                "total": len(items),
                "pass": passed,
                "fail": failed,
                "pass_rate": round(passed / len(items) * 100, 1) if items else 0.0,
            }
        )
    return rows


def build_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [float(result.get("latency_ms", 0)) for result in results]
    passed = sum(1 for result in results if result["status"] == "PASS")
    failed = len(results) - passed
    hard_filter_violations = sum(
        1 for result in results if result.get("hard_filter_violation")
    )

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(results),
        "pass": passed,
        "fail": failed,
        "pass_rate": round(passed / len(results) * 100, 1) if results else 0.0,
        "hard_filter_violations": hard_filter_violations,
        "latency": {
            "avg_ms": round(statistics.mean(latencies), 1) if latencies else 0.0,
            "min_ms": round(min(latencies), 1) if latencies else 0.0,
            "max_ms": round(max(latencies), 1) if latencies else 0.0,
            "p50_ms": round(percentile(latencies, 0.50), 1),
            "p95_ms": round(percentile(latencies, 0.95), 1),
        },
        "by_source": summarize_group(results, "source_kind"),
        "by_category": summarize_group(results, "category"),
        "by_pattern": summarize_group(
            [result for result in results if result.get("source_kind") == "extended"],
            "pattern_group",
        ),
    }


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    output = ["| " + " | ".join(headers) + " |"]
    output.append("|" + "|".join(["---"] * len(headers)) + "|")
    for row in rows:
        clean = [str(value).replace("\n", " ").replace("|", "\\|") for value in row]
        output.append("| " + " | ".join(clean) + " |")
    return "\n".join(output)


def build_markdown_report(
    summary: dict[str, Any],
    results: list[dict[str, Any]],
    judge_model: str,
) -> str:
    failed_cases = [result for result in results if result["status"] == "FAIL"]
    benchmark = next(
        (row for row in summary["by_source"] if row["group"] == "benchmark"),
        {"total": 0, "pass": 0, "fail": 0, "pass_rate": 0},
    )
    extended = next(
        (row for row in summary["by_source"] if row["group"] == "extended"),
        {"total": 0, "pass": 0, "fail": 0, "pass_rate": 0},
    )

    parts = [
        "# Báo cáo đánh giá định lượng hệ thống gợi ý món ăn",
        "",
        f"**Ngày thực hiện**: {summary['generated_at']}",
        f"**Mô hình LLM-as-a-Judge**: `{judge_model}`",
        f"**Tổng số test case**: `{summary['total']}`",
        f"**Tỷ lệ đạt chung**: `{summary['pass_rate']}%` ({summary['pass']}/{summary['total']})",
        f"**Số case vi phạm hard-filter**: `{summary['hard_filter_violations']}`",
        "",
        "## 1. Tổng quan bộ test",
        markdown_table(
            ["Bộ test", "Số case", "PASS", "FAIL", "Tỷ lệ PASS"],
            [
                [
                    "Benchmark chính",
                    benchmark["total"],
                    benchmark["pass"],
                    benchmark["fail"],
                    f"{benchmark['pass_rate']}%",
                ],
                [
                    "Mở rộng theo pattern",
                    extended["total"],
                    extended["pass"],
                    extended["fail"],
                    f"{extended['pass_rate']}%",
                ],
            ],
        ),
        "",
        "## 2. Kết quả theo nhóm sức khỏe",
        markdown_table(
            ["Nhóm", "Số case", "PASS", "FAIL", "Tỷ lệ PASS"],
            [
                [
                    row["group"],
                    row["total"],
                    row["pass"],
                    row["fail"],
                    f"{row['pass_rate']}%",
                ]
                for row in summary["by_category"]
            ],
        ),
        "",
        "## 3. Kết quả theo pattern mở rộng",
        markdown_table(
            ["Pattern", "Số case", "PASS", "FAIL", "Tỷ lệ PASS"],
            [
                [
                    row["group"],
                    row["total"],
                    row["pass"],
                    row["fail"],
                    f"{row['pass_rate']}%",
                ]
                for row in summary["by_pattern"]
            ],
        ),
        "",
        "## 4. Thống kê thời gian phản hồi",
        markdown_table(
            ["Chỉ số", "Giá trị"],
            [
                ["Trung bình", f"{summary['latency']['avg_ms']} ms"],
                ["Min", f"{summary['latency']['min_ms']} ms"],
                ["Max", f"{summary['latency']['max_ms']} ms"],
                ["P50", f"{summary['latency']['p50_ms']} ms"],
                ["P95", f"{summary['latency']['p95_ms']} ms"],
            ],
        ),
        "",
        "## 5. Các test case chưa đạt",
    ]

    if not failed_cases:
        parts.append("Không có test case nào thất bại.")
    else:
        fail_rows = []
        for result in failed_cases:
            fail_rows.append(
                [
                    result["id"],
                    result["source_kind"],
                    result.get("pattern_group") or "-",
                    result["tag"],
                    result["query"],
                    result["actual_dishes_text"],
                    result["reason"],
                ]
            )
        parts.append(
            markdown_table(
                [
                    "ID",
                    "Bộ test",
                    "Pattern",
                    "Tag",
                    "Truy vấn",
                    "Món thực tế",
                    "Lý do",
                ],
                fail_rows,
            )
        )

    return "\n".join(parts) + "\n"


def write_outputs(
    output_dir: Path,
    run_id: str,
    results: list[dict[str, Any]],
    summary: dict[str, Any],
    judge_model: str,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"pathology_test_results_{run_id}.json"
    csv_path = output_dir / f"pathology_test_results_{run_id}.csv"
    md_path = output_dir / f"pathology_test_summary_{run_id}.md"

    json_payload = {"summary": summary, "results": results}
    json_path.write_text(
        json.dumps(json_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    fieldnames = [
        "id",
        "source_kind",
        "pattern_group",
        "category",
        "tag",
        "query",
        "objective",
        "expected",
        "actual_dishes_text",
        "status",
        "reason",
        "judge_status",
        "judge_reason",
        "hard_filter_violation",
        "latency_ms",
    ]
    with csv_path.open(mode="w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow({key: result.get(key, "") for key in fieldnames})

    md_path.write_text(
        build_markdown_report(summary, results, judge_model),
        encoding="utf-8",
    )

    return {"json": json_path, "csv": csv_path, "markdown": md_path}


def print_parse_summary(test_cases: list[dict[str, str]]) -> None:
    by_source = Counter(tc["source_kind"] for tc in test_cases)
    by_pattern = Counter(
        tc["pattern_group"] for tc in test_cases if tc["source_kind"] == "extended"
    )
    by_category = Counter(tc["category"] for tc in test_cases)
    print("Tổng test case đọc được:", len(test_cases))
    print("Theo bộ test:", dict(by_source))
    print("Theo nhóm:", dict(by_category))
    print("Theo pattern mở rộng:", dict(by_pattern))


async def run(args: argparse.Namespace) -> None:
    benchmark_paths = [
        Path(path).expanduser()
        for path in (args.benchmark_csv or [str(DEFAULT_BENCHMARK_CSV)])
    ]
    extended_paths = [
        Path(path).expanduser()
        for path in (args.extended_csv or [str(DEFAULT_EXTENDED_CSV)])
    ]
    test_cases = parse_all_test_cases(benchmark_paths, extended_paths)
    print_parse_summary(test_cases)

    if args.expect_count is not None and len(test_cases) != args.expect_count:
        raise SystemExit(
            f"Số test case đọc được là {len(test_cases)}, khác kỳ vọng {args.expect_count}."
        )

    if args.dry_run:
        print("Dry-run hoàn tất. Không chạy backend search.")
        return

    judge_client = None if args.skip_judge else build_judge_client()
    results: list[dict[str, Any]] = []
    start = time.perf_counter()

    async with AsyncSessionLocal() as db:
        for idx, tc in enumerate(test_cases, 1):
            print(f"[{idx}/{len(test_cases)}]")
            result = await run_single_test(
                tc,
                db,
                judge_client,
                args.judge_model,
                args.judge_timeout_seconds,
                args.top_k,
                args.skip_judge,
                args.show_search_log,
            )
            results.append(result)
            if args.sleep_seconds > 0 and idx < len(test_cases):
                await asyncio.sleep(args.sleep_seconds)

    total_elapsed = round((time.perf_counter() - start) * 1000)
    summary = build_summary(results)
    summary["elapsed_ms"] = total_elapsed
    summary["input_files"] = {
        "benchmark": [str(path) for path in benchmark_paths],
        "extended": [str(path) for path in extended_paths],
    }
    summary["top_k"] = args.top_k
    summary["judge_model"] = args.judge_model
    summary["judge_timeout_seconds"] = args.judge_timeout_seconds
    summary["skip_judge"] = args.skip_judge

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    paths = write_outputs(Path(args.output_dir), run_id, results, summary, args.judge_model)

    print("\nKẾT QUẢ ĐÁNH GIÁ CHUNG")
    print(f"- Tổng số test case: {summary['total']}")
    print(f"- Đạt (PASS): {summary['pass']}")
    print(f"- Không đạt (FAIL): {summary['fail']}")
    print(f"- Tỷ lệ đạt: {summary['pass_rate']}%")
    print(f"- Hard-filter violations: {summary['hard_filter_violations']}")
    print(f"- Latency trung bình: {summary['latency']['avg_ms']}ms")
    print(f"- P95 latency: {summary['latency']['p95_ms']}ms")
    print("\nĐã lưu kết quả:")
    for kind, path in paths.items():
        print(f"- {kind}: {path}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run pathology/allergy recommendation evaluation cases.",
    )
    parser.add_argument(
        "--benchmark-csv",
        action="append",
        default=None,
        help="CSV benchmark 35 case. Có thể truyền nhiều lần.",
    )
    parser.add_argument(
        "--extended-csv",
        action="append",
        default=None,
        help="CSV extended pattern cases. Có thể truyền nhiều lần.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Thư mục lưu CSV/JSON/Markdown kết quả.",
    )
    parser.add_argument("--expect-count", type=int, default=95)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--sleep-seconds", type=float, default=1.0)
    parser.add_argument("--judge-model", default="gemini-2.5-flash")
    parser.add_argument("--judge-timeout-seconds", type=float, default=45.0)
    parser.add_argument("--skip-judge", action="store_true")
    parser.add_argument(
        "--show-search-log",
        action="store_true",
        help="In log chi tiết từ pipeline search_food. Mặc định runner sẽ ẩn log này.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
