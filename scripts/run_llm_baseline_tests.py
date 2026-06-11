from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
import time
import traceback
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from google.genai import types
from sqlalchemy import select

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT / "scripts"))

from app.db.session import AsyncSessionLocal
from app.modules.foods.models import Food
from app.modules.search.schemas import AIInsight, FoodResult, SearchResponse
from run_pathology_tests import (
    DEFAULT_BENCHMARK_CSV,
    DEFAULT_EXTENDED_CSV,
    DEFAULT_OUTPUT_DIR,
    build_judge_client,
    build_summary,
    evaluate_llm_judge,
    markdown_table,
    normalize_text,
    parse_all_test_cases,
    run_programmatic_checks,
)


FOCUS_TAG_LABELS = {
    "Dị ứng động vật giáp xác": "Dị ứng giáp xác",
    "Dị ứng động vật thân mềm": "Dị ứng thân mềm",
    "Dị ứng trứng": "Dị ứng trứng",
    "Dị ứng sữa bò": "Dị ứng sữa bò",
    "Đầy bụng / Khó tiêu": "Đầy bụng / Khó tiêu",
    "Cao huyết áp": "Cao huyết áp",
    "Viêm loét dạ dày": "Viêm loét dạ dày",
    "Béo phì": "Béo phì",
}


BASELINE_PROMPT = """Bạn là một trợ lý gợi ý món ăn.
Hãy trả lời trực tiếp dựa trên hiểu biết chung của bạn, KHÔNG dùng cơ sở dữ liệu món ăn, KHÔNG dùng rule engine và KHÔNG dùng pipeline truy xuất.

TRUY VẤN NGƯỜI DÙNG:
"{query}"

YÊU CẦU:
- Gợi ý tối đa {top_k} món ăn phù hợp.
- Nếu người dùng có bệnh lý hoặc dị ứng, hãy tự cân nhắc an toàn sức khỏe.
- Nếu sở thích người dùng xung đột với bệnh lý/dị ứng, hãy cảnh báo ngắn gọn.
- Trả về JSON duy nhất, không thêm văn bản ngoài JSON.

SCHEMA JSON:
{{
  "exclude": ["các yếu tố cần tránh nếu có"],
  "include": ["bệnh lý/dị ứng/ngữ cảnh nhận diện được nếu có"],
  "prefer": ["các tiêu chí nên ưu tiên nếu có"],
  "warning_message": "cảnh báo ngắn nếu có, ngược lại để rỗng",
  "foods": [
    {{
      "name": "Tên món",
      "core_ingredients": ["nguyên liệu chính mà bạn cho là có trong món"],
      "soft_tags": ["tính chất món ăn"],
      "reason": "Lý do gợi ý ngắn gọn"
    }}
  ],
  "ai_response": "Lời tư vấn tự nhiên ngắn gọn cho người dùng"
}}
"""


DB_CANDIDATE_PROMPT = """Bạn là một trợ lý chọn món ăn từ cơ sở dữ liệu có sẵn.
Bạn PHẢI chỉ chọn món từ danh sách CATALOG bên dưới bằng mã `code`.
KHÔNG được tự tạo món mới, KHÔNG được đổi tên món, KHÔNG được chọn món ngoài CATALOG.
Bạn không có Rule Engine hoặc vector search; hãy tự đánh giá dựa trên tên món, nguyên liệu, tag và ngữ cảnh bữa ăn được cung cấp.

TRUY VẤN NGƯỜI DÙNG:
"{query}"

CATALOG MÓN ĂN:
{catalog}

YÊU CẦU:
- Chọn tối đa {top_k} món phù hợp nhất từ CATALOG.
- Nếu người dùng có bệnh lý/dị ứng, hãy tránh món có nguyên liệu hoặc tag rủi ro.
- Nếu sở thích người dùng xung đột với sức khỏe, hãy cảnh báo rõ.
- Nếu không đủ món an toàn, có thể trả ít hơn {top_k} món.
- Trả về JSON duy nhất, không thêm văn bản ngoài JSON.

SCHEMA JSON:
{{
  "exclude": ["các yếu tố cần tránh nếu có"],
  "include": ["bệnh lý/dị ứng/ngữ cảnh nhận diện được nếu có"],
  "prefer": ["các tiêu chí nên ưu tiên nếu có"],
  "warning_message": "cảnh báo ngắn nếu có, ngược lại để rỗng",
  "selected_foods": [
    {{
      "code": "mã món trong CATALOG, ví dụ F001",
      "reason": "Lý do chọn món ngắn gọn"
    }}
  ],
  "ai_response": "Lời tư vấn tự nhiên ngắn gọn cho người dùng"
}}
"""


def filter_test_cases(
    test_cases: list[dict[str, str]],
    *,
    focus_current_scope: bool,
    include_hidden: bool,
) -> list[dict[str, str]]:
    filtered = []
    for tc in test_cases:
        if focus_current_scope and tc.get("tag") not in FOCUS_TAG_LABELS:
            continue
        if not include_hidden and tc.get("pattern_group") == "Hidden Ingredient":
            continue
        filtered.append(tc)
    return filtered


def parse_json_response(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.removeprefix("json").strip()
    return json.loads(raw)


async def generate_llm_baseline_response(
    tc: dict[str, str],
    client: Any,
    model: str,
    timeout_seconds: float,
    top_k: int,
) -> SearchResponse:
    prompt = BASELINE_PROMPT.format(query=tc["query"], top_k=top_k)
    response = await asyncio.wait_for(
        asyncio.to_thread(
            client.models.generate_content,
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2,
            ),
        ),
        timeout=timeout_seconds,
    )
    payload = parse_json_response(response.text)

    food_results: list[FoodResult] = []
    for item in (payload.get("foods") or [])[:top_k]:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        food_results.append(
            FoodResult(
                id=uuid.uuid4(),
                name=name,
                description="",
                img_url=None,
                core_ingredients=[
                    str(value).strip()
                    for value in (item.get("core_ingredients") or [])
                    if str(value).strip()
                ],
                soft_tags=[
                    str(value).strip()
                    for value in (item.get("soft_tags") or [])
                    if str(value).strip()
                ],
                taste_profile=[],
                meal_context=[],
                occasion_context=[],
                matchScore=0.0,
                reason=str(item.get("reason") or "").strip(),
                dining_context=None,
            )
        )

    return SearchResponse(
        query=tc["query"],
        ai_insight=AIInsight(
            exclude=[
                str(value).strip()
                for value in (payload.get("exclude") or [])
                if str(value).strip()
            ],
            include=[
                str(value).strip()
                for value in (payload.get("include") or [])
                if str(value).strip()
            ],
            prefer=[
                str(value).strip()
                for value in (payload.get("prefer") or [])
                if str(value).strip()
            ],
            warning_message=str(payload.get("warning_message") or "").strip() or None,
        ),
        results=food_results,
        disclaimer="Baseline LLM trực tiếp, không dùng CSDL/rule engine.",
        ai_response=str(payload.get("ai_response") or "").strip(),
    )


def _compact_join(values: list[str] | None, max_items: int = 8) -> str:
    items = [str(value).strip() for value in (values or []) if str(value).strip()]
    if not items:
        return "-"
    shown = items[:max_items]
    suffix = ", ..." if len(items) > max_items else ""
    return ", ".join(shown) + suffix


async def load_food_catalog() -> tuple[str, dict[str, Food], set[str]]:
    async with AsyncSessionLocal() as db:
        rows = await db.execute(select(Food).order_by(Food.name))
        foods = list(rows.scalars().all())

    catalog_lines: list[str] = []
    food_by_code: dict[str, Food] = {}
    food_name_set: set[str] = set()
    for index, food in enumerate(foods, 1):
        code = f"F{index:03d}"
        food_by_code[code] = food
        food_name_set.add(normalize_text(food.name))
        catalog_lines.append(
            f"{code} | {food.name} | "
            f"ing={_compact_join(food.core_ingredients)} | "
            f"tags={_compact_join(food.soft_tags, 10)} | "
            f"meal={_compact_join(food.meal_context, 4)}"
        )

    return "\n".join(catalog_lines), food_by_code, food_name_set


async def generate_db_candidate_baseline_response(
    tc: dict[str, str],
    client: Any,
    model: str,
    timeout_seconds: float,
    top_k: int,
    catalog_text: str,
    food_by_code: dict[str, Food],
) -> SearchResponse:
    prompt = DB_CANDIDATE_PROMPT.format(
        query=tc["query"],
        top_k=top_k,
        catalog=catalog_text,
    )
    response = await asyncio.wait_for(
        asyncio.to_thread(
            client.models.generate_content,
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        ),
        timeout=timeout_seconds,
    )
    payload = parse_json_response(response.text)

    food_results: list[FoodResult] = []
    seen_codes: set[str] = set()
    for item in (payload.get("selected_foods") or [])[:top_k]:
        code = str(item.get("code") or "").strip().upper()
        if not code or code in seen_codes or code not in food_by_code:
            continue
        seen_codes.add(code)
        food = food_by_code[code]
        food_results.append(
            FoodResult(
                id=food.id,
                name=food.name,
                description=food.description,
                img_url=food.img_url,
                core_ingredients=food.core_ingredients or [],
                soft_tags=food.soft_tags or [],
                taste_profile=food.taste_profile or [],
                meal_context=food.meal_context or [],
                occasion_context=food.occasion_context or [],
                matchScore=0.0,
                reason=str(item.get("reason") or "").strip(),
                dining_context=food.dining_context,
            )
        )

    return SearchResponse(
        query=tc["query"],
        ai_insight=AIInsight(
            exclude=[
                str(value).strip()
                for value in (payload.get("exclude") or [])
                if str(value).strip()
            ],
            include=[
                str(value).strip()
                for value in (payload.get("include") or [])
                if str(value).strip()
            ],
            prefer=[
                str(value).strip()
                for value in (payload.get("prefer") or [])
                if str(value).strip()
            ],
            warning_message=str(payload.get("warning_message") or "").strip() or None,
        ),
        results=food_results,
        disclaimer="Baseline LLM chọn từ CSDL, không dùng rule engine/vector search.",
        ai_response=str(payload.get("ai_response") or "").strip(),
    )


async def load_food_name_set() -> set[str]:
    try:
        async with AsyncSessionLocal() as db:
            rows = await db.execute(select(Food.name))
            return {normalize_text(name) for name in rows.scalars().all() if name}
    except Exception as exc:
        print(f"Không thể tải danh sách món ăn để tính grounded rate: {exc}")
        return set()


def annotate_grounded_metrics(
    result: dict[str, Any],
    food_name_set: set[str],
) -> None:
    dishes = result.get("actual_dishes") or []
    if not food_name_set or not dishes:
        result["grounded_total"] = len(dishes)
        result["grounded_count"] = 0
        result["grounded_rate"] = None
        return

    grounded = sum(1 for dish in dishes if normalize_text(dish) in food_name_set)
    result["grounded_total"] = len(dishes)
    result["grounded_count"] = grounded
    result["grounded_rate"] = round(grounded / len(dishes) * 100, 1)


async def run_single_baseline_test(
    tc: dict[str, str],
    *,
    baseline_client: Any,
    judge_client: Any | None,
    baseline_model: str,
    judge_model: str,
    baseline_timeout_seconds: float,
    judge_timeout_seconds: float,
    top_k: int,
    skip_judge: bool,
    food_name_set: set[str],
    mode: str,
    catalog_text: str = "",
    food_by_code: dict[str, Food] | None = None,
) -> dict[str, Any]:
    print(f"Đang chạy baseline {tc['id']}: {tc['query']}")
    start_time = time.perf_counter()
    try:
        if mode == "db-candidates":
            llm_response = await generate_db_candidate_baseline_response(
                tc,
                baseline_client,
                baseline_model,
                baseline_timeout_seconds,
                top_k,
                catalog_text,
                food_by_code or {},
            )
        else:
            llm_response = await generate_llm_baseline_response(
                tc,
                baseline_client,
                baseline_model,
                baseline_timeout_seconds,
                top_k,
            )
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
            for result in llm_response.results
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
                llm_response,
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

        result = {
            **tc,
            "actual_dishes": [item.name for item in llm_response.results],
            "actual_dishes_text": ", ".join(item.name for item in llm_response.results),
            "ai_insight": {
                "exclude": llm_response.ai_insight.exclude,
                "include": llm_response.ai_insight.include,
                "prefer": llm_response.ai_insight.prefer,
                "warning_message": llm_response.ai_insight.warning_message,
            },
            "ai_response": llm_response.ai_response,
            "judge_status": judge_result["status"],
            "judge_reason": judge_result["reason"],
            "programmatic_violations": programmatic_violations,
            "hard_filter_violation": bool(programmatic_violations),
            "status": status,
            "reason": reason,
            "latency_ms": latency_ms,
        }
        annotate_grounded_metrics(result, food_name_set)
        print(f"  -> {status} ({latency_ms}ms). {reason}\n")
        return result
    except Exception as exc:
        latency_ms = round((time.perf_counter() - start_time) * 1000)
        print(f"Lỗi nghiêm trọng khi chạy baseline {tc['id']}: {exc}")
        traceback.print_exc()
        result = {
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
            "reason": f"Lỗi hệ thống trong lúc chạy baseline: {exc}",
            "latency_ms": latency_ms,
        }
        annotate_grounded_metrics(result, food_name_set)
        return result


def summarize_grounded(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = sum(int(result.get("grounded_total") or 0) for result in results)
    grounded = sum(int(result.get("grounded_count") or 0) for result in results)
    return {
        "total_dishes": total,
        "grounded_dishes": grounded,
        "grounded_rate": round(grounded / total * 100, 1) if total else None,
    }


def build_tag_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        grouped[FOCUS_TAG_LABELS.get(result.get("tag"), result.get("tag") or "Khác")].append(
            result
        )

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


def load_pipeline_results(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return payload["results"]
    if isinstance(payload, list):
        return payload
    raise ValueError(f"Không đọc được results từ {path}")


def metric_delta(proposed: float | int | None, baseline: float | int | None) -> str:
    if proposed is None or baseline is None:
        return "-"
    delta = round(float(proposed) - float(baseline), 1)
    sign = "+" if delta > 0 else ""
    return f"{sign}{delta}"


def build_comparison_markdown(
    *,
    proposed_results: list[dict[str, Any]],
    baseline_results: list[dict[str, Any]],
    proposed_label: str,
    baseline_label: str,
) -> str:
    proposed_summary = build_summary(proposed_results)
    baseline_summary = build_summary(baseline_results)
    proposed_grounded = {"grounded_rate": 100.0}
    baseline_grounded = summarize_grounded(baseline_results)

    proposed_hf_rate = (
        round(proposed_summary["hard_filter_violations"] / proposed_summary["total"] * 100, 1)
        if proposed_summary["total"]
        else 0.0
    )
    baseline_hf_rate = (
        round(baseline_summary["hard_filter_violations"] / baseline_summary["total"] * 100, 1)
        if baseline_summary["total"]
        else 0.0
    )

    rows = [
        [
            "Tỷ lệ PASS",
            f"{proposed_summary['pass_rate']}%",
            f"{baseline_summary['pass_rate']}%",
            metric_delta(proposed_summary["pass_rate"], baseline_summary["pass_rate"]),
        ],
        [
            "Số case PASS",
            f"{proposed_summary['pass']}/{proposed_summary['total']}",
            f"{baseline_summary['pass']}/{baseline_summary['total']}",
            metric_delta(proposed_summary["pass"], baseline_summary["pass"]),
        ],
        [
            "Tỷ lệ vi phạm hard-filter",
            f"{proposed_hf_rate}%",
            f"{baseline_hf_rate}%",
            metric_delta(proposed_hf_rate, baseline_hf_rate),
        ],
        [
            "Grounded dish rate",
            f"{proposed_grounded['grounded_rate']}%",
            (
                f"{baseline_grounded['grounded_rate']}%"
                if baseline_grounded["grounded_rate"] is not None
                else "Không đo được"
            ),
            metric_delta(proposed_grounded["grounded_rate"], baseline_grounded["grounded_rate"]),
        ],
        [
            "Latency trung bình",
            f"{round(proposed_summary['latency']['avg_ms'] / 1000, 1)}s",
            f"{round(baseline_summary['latency']['avg_ms'] / 1000, 1)}s",
            metric_delta(
                round(proposed_summary["latency"]["avg_ms"] / 1000, 1),
                round(baseline_summary["latency"]["avg_ms"] / 1000, 1),
            ),
        ],
        [
            "P95 latency",
            f"{round(proposed_summary['latency']['p95_ms'] / 1000, 1)}s",
            f"{round(baseline_summary['latency']['p95_ms'] / 1000, 1)}s",
            metric_delta(
                round(proposed_summary["latency"]["p95_ms"] / 1000, 1),
                round(baseline_summary["latency"]["p95_ms"] / 1000, 1),
            ),
        ],
    ]

    tag_rows = []
    baseline_by_tag = {row["group"]: row for row in build_tag_rows(baseline_results)}
    for proposed_row in build_tag_rows(proposed_results):
        label = proposed_row["group"]
        baseline_row = baseline_by_tag.get(
            label,
            {"total": 0, "pass": 0, "fail": 0, "pass_rate": 0.0},
        )
        tag_rows.append(
            [
                label,
                proposed_row["total"],
                f"{proposed_row['pass_rate']}%",
                f"{baseline_row['pass_rate']}%",
                metric_delta(proposed_row["pass_rate"], baseline_row["pass_rate"]),
            ]
        )

    return "\n".join(
        [
            "# So sánh Pipeline đề xuất và LLM trực tiếp",
            "",
            f"**{proposed_label}**: `{proposed_summary['pass']}/{proposed_summary['total']}` PASS",
            f"**{baseline_label}**: `{baseline_summary['pass']}/{baseline_summary['total']}` PASS",
            "",
            "## Bảng so sánh tổng quan",
            markdown_table(
                ["Tiêu chí", proposed_label, baseline_label, "Chênh lệch"],
                rows,
            ),
            "",
            "## Bảng so sánh theo nhóm sức khỏe",
            markdown_table(
                ["Nhóm", "Số case", proposed_label, baseline_label, "Chênh lệch"],
                tag_rows,
            ),
            "",
        ]
    )


def build_baseline_markdown(
    summary: dict[str, Any],
    results: list[dict[str, Any]],
    baseline_model: str,
    judge_model: str,
) -> str:
    return "\n".join(
        [
            f"# Báo cáo đánh giá baseline {summary.get('baseline_mode_label', 'LLM trực tiếp')}",
            "",
            f"**Ngày thực hiện**: {summary['generated_at']}",
            f"**Mô hình baseline**: `{baseline_model}`",
            f"**Mô hình LLM-as-a-Judge**: `{judge_model}`",
            f"**Tổng số test case**: `{summary['total']}`",
            f"**Tỷ lệ đạt chung**: `{summary['pass_rate']}%` ({summary['pass']}/{summary['total']})",
            f"**Số case vi phạm hard-filter**: `{summary['hard_filter_violations']}`",
            f"**Grounded dish rate**: `{summarize_grounded(results)['grounded_rate']}%`",
            "",
            "## Kết quả theo nhóm sức khỏe",
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
                    for row in build_tag_rows(results)
                ],
            ),
            "",
            "## Thống kê latency",
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
        ]
    )


def write_outputs(
    output_dir: Path,
    run_id: str,
    results: list[dict[str, Any]],
    summary: dict[str, Any],
    baseline_model: str,
    judge_model: str,
    comparison_markdown: str | None,
    mode: str,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = "llm_db_baseline" if mode == "db-candidates" else "llm_baseline"
    json_path = output_dir / f"{prefix}_results_{run_id}.json"
    csv_path = output_dir / f"{prefix}_results_{run_id}.csv"
    md_path = output_dir / f"{prefix}_summary_{run_id}.md"

    json_path.write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2),
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
        "grounded_count",
        "grounded_total",
        "grounded_rate",
        "latency_ms",
    ]
    with csv_path.open(mode="w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow({key: result.get(key, "") for key in fieldnames})

    md_path.write_text(
        build_baseline_markdown(summary, results, baseline_model, judge_model),
        encoding="utf-8",
    )

    paths = {"json": json_path, "csv": csv_path, "markdown": md_path}
    if comparison_markdown:
        comparison_name = (
            f"llm_db_vs_pipeline_comparison_{run_id}.md"
            if mode == "db-candidates"
            else f"llm_vs_pipeline_comparison_{run_id}.md"
        )
        comparison_path = output_dir / comparison_name
        comparison_path.write_text(comparison_markdown, encoding="utf-8")
        paths["comparison"] = comparison_path
    return paths


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
    test_cases = filter_test_cases(
        test_cases,
        focus_current_scope=not args.all_cases,
        include_hidden=args.include_hidden,
    )

    print(f"Tổng test case baseline sẽ chạy: {len(test_cases)}")
    if args.dry_run:
        for tc in test_cases:
            print(f"{tc['id']}\t{tc['tag']}\t{tc['pattern_group'] or '-'}\t{tc['query']}")
        return

    baseline_client = build_judge_client()
    judge_client = None if args.skip_judge else build_judge_client()
    catalog_text = ""
    food_by_code: dict[str, Food] = {}
    if args.mode == "db-candidates":
        catalog_text, food_by_code, food_name_set = await load_food_catalog()
        print(f"Đã tải {len(food_by_code)} món trong database cho baseline LLM chọn món.")
    else:
        food_name_set = set() if args.skip_grounded else await load_food_name_set()

    results: list[dict[str, Any]] = []
    for idx, tc in enumerate(test_cases, 1):
        print(f"[{idx}/{len(test_cases)}]")
        result = await run_single_baseline_test(
            tc,
            baseline_client=baseline_client,
            judge_client=judge_client,
            baseline_model=args.baseline_model,
            judge_model=args.judge_model,
            baseline_timeout_seconds=args.baseline_timeout_seconds,
            judge_timeout_seconds=args.judge_timeout_seconds,
            top_k=args.top_k,
            skip_judge=args.skip_judge,
            food_name_set=food_name_set,
            mode=args.mode,
            catalog_text=catalog_text,
            food_by_code=food_by_code,
        )
        results.append(result)
        if args.sleep_seconds > 0 and idx < len(test_cases):
            await asyncio.sleep(args.sleep_seconds)

    summary = build_summary(results)
    summary["baseline_model"] = args.baseline_model
    summary["judge_model"] = args.judge_model
    summary["grounded"] = summarize_grounded(results)
    summary["baseline_mode"] = args.mode
    summary["baseline_mode_label"] = (
        "LLM chọn từ database" if args.mode == "db-candidates" else "LLM trực tiếp"
    )
    summary["scope"] = {
        "focus_current_scope": not args.all_cases,
        "include_hidden": args.include_hidden,
    }

    comparison_markdown = None
    if args.pipeline_results_json:
        pipeline_results = load_pipeline_results(Path(args.pipeline_results_json).expanduser())
        pipeline_results = filter_test_cases(
            pipeline_results,
            focus_current_scope=not args.all_cases,
            include_hidden=args.include_hidden,
        )
        comparison_markdown = build_comparison_markdown(
            proposed_results=pipeline_results,
            baseline_results=results,
            proposed_label="Pipeline đề xuất",
            baseline_label=summary["baseline_mode_label"],
        )

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    paths = write_outputs(
        Path(args.output_dir),
        run_id,
        results,
        summary,
        args.baseline_model,
        args.judge_model,
        comparison_markdown,
        args.mode,
    )

    print(f"\nKẾT QUẢ BASELINE {summary['baseline_mode_label'].upper()}")
    print(f"- Tổng số test case: {summary['total']}")
    print(f"- PASS: {summary['pass']}")
    print(f"- FAIL: {summary['fail']}")
    print(f"- Tỷ lệ PASS: {summary['pass_rate']}%")
    print(f"- Hard-filter violations: {summary['hard_filter_violations']}")
    print(f"- Grounded dish rate: {summary['grounded']['grounded_rate']}%")
    print(f"- Latency trung bình: {summary['latency']['avg_ms']}ms")
    print("\nĐã lưu kết quả:")
    for kind, path in paths.items():
        print(f"- {kind}: {path}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run direct-LLM baseline evaluation on pathology test cases.",
    )
    parser.add_argument(
        "--benchmark-csv",
        action="append",
        default=None,
    )
    parser.add_argument(
        "--extended-csv",
        action="append",
        default=None,
    )
    parser.add_argument(
        "--pipeline-results-json",
        default=str(DEFAULT_OUTPUT_DIR / "pathology_test_results_20260604_174152.json"),
        help="File JSON kết quả pipeline để xuất bảng so sánh. Để rỗng nếu không cần.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
    )
    parser.add_argument("--baseline-model", default="gemini-2.5-flash-lite")
    parser.add_argument("--judge-model", default="gemini-2.5-flash")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--baseline-timeout-seconds", type=float, default=45)
    parser.add_argument("--judge-timeout-seconds", type=float, default=45)
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    parser.add_argument(
        "--mode",
        choices=["free", "db-candidates"],
        default="free",
        help="free: LLM tự do gợi ý món; db-candidates: LLM chỉ chọn món trong database.",
    )
    parser.add_argument(
        "--all-cases",
        action="store_true",
        help="Không lọc theo 8 nhóm sức khỏe hiện tại.",
    )
    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help="Tính cả pattern Hidden Ingredient. Mặc định loại bỏ.",
    )
    parser.add_argument("--skip-judge", action="store_true")
    parser.add_argument("--skip-grounded", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


if __name__ == "__main__":
    asyncio.run(run(build_arg_parser().parse_args()))
