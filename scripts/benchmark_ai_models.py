from __future__ import annotations

import argparse
import asyncio
import csv
import os
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import desc, select

from app.db.session import AsyncSessionLocal
from app.modules.query_logs.models import QueryLog
from app.modules.search.service import search_food


DEFAULT_MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
DEFAULT_TEST_FILE = Path(__file__).resolve().parents[1] / "[GTP26] Test case - Test Case bệnh lý.csv"
DEFAULT_OUTPUT_FILE = Path(__file__).resolve().parents[1] / "docs" / "ai_model_selection_evidence.md"


@dataclass
class TestCase:
    test_case_id: str
    group: str
    verification_tag: str
    query: str
    objective: str
    expected_result: str


@dataclass
class BenchmarkResult:
    model: str
    test_case: TestCase
    request_total_ms: int
    supervisor_ms: int
    embedding_ms: int
    post_processing_ms: int
    other_ms: int
    llm_total_ms: int
    returned_count: int
    query_log_id: str | None
    error: str | None = None


def parse_test_cases(path: Path, *, limit: int | None = None) -> list[TestCase]:
    test_cases: list[TestCase] = []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.reader(file)
        header: list[str] | None = None
        for row in reader:
            normalized_row = [cell.strip() for cell in row]
            if "Test Case ID" in normalized_row:
                header = normalized_row
                continue

            if header is None or not normalized_row:
                continue

            row_by_name = {
                name: normalized_row[index] if index < len(normalized_row) else ""
                for index, name in enumerate(header)
                if name
            }
            test_case_id = row_by_name.get("Test Case ID", "")
            query = row_by_name.get("Prompt test", "")
            if not test_case_id.startswith("TC-") or not query:
                continue

            test_cases.append(
                TestCase(
                    test_case_id=test_case_id,
                    group=row_by_name.get("Nhóm", ""),
                    verification_tag=row_by_name.get("Tag kiểm chứng", ""),
                    query=query,
                    objective=row_by_name.get("Mục tiêu kiểm thử", ""),
                    expected_result=row_by_name.get("Expected Result", ""),
                )
            )
            if limit and len(test_cases) >= limit:
                break

    return test_cases


async def _load_query_log_runtime(query_log_id: Any) -> dict[str, Any]:
    if not query_log_id:
        return {}
    async with AsyncSessionLocal() as db:
        log = (
            await db.execute(
                select(QueryLog)
                .where(QueryLog.id == query_log_id)
                .order_by(desc(QueryLog.created_at))
            )
        ).scalar_one_or_none()
        if log is None:
            return {}
        return (log.excluded_summary or {}).get("llm_runtime") or {}


async def run_one_case(model: str, test_case: TestCase) -> BenchmarkResult:
    os.environ["GEMINI_TEXT_MODEL"] = model
    started_at = time.perf_counter()
    query_log_id = None
    try:
        async with AsyncSessionLocal() as db:
            response = await search_food(test_case.query, db, profile=None, top_k=5)
            query_log_id = response.query_log_id

        request_total_ms = round((time.perf_counter() - started_at) * 1000)
        runtime = await _load_query_log_runtime(query_log_id)
        stage = runtime.get("stage_latency_ms") or {}
        supervisor_ms = int(stage.get("supervisor") or 0)
        embedding_ms = int(stage.get("embedding") or 0)
        post_processing_ms = int(stage.get("post_processing") or 0)
        llm_total_ms = supervisor_ms + embedding_ms + post_processing_ms
        other_ms = request_total_ms - llm_total_ms
        return BenchmarkResult(
            model=model,
            test_case=test_case,
            request_total_ms=request_total_ms,
            supervisor_ms=supervisor_ms,
            embedding_ms=embedding_ms,
            post_processing_ms=post_processing_ms,
            other_ms=other_ms,
            llm_total_ms=llm_total_ms,
            returned_count=len(response.results),
            query_log_id=str(query_log_id) if query_log_id else None,
        )
    except Exception as exc:
        request_total_ms = round((time.perf_counter() - started_at) * 1000)
        return BenchmarkResult(
            model=model,
            test_case=test_case,
            request_total_ms=request_total_ms,
            supervisor_ms=0,
            embedding_ms=0,
            post_processing_ms=0,
            other_ms=0,
            llm_total_ms=0,
            returned_count=0,
            query_log_id=str(query_log_id) if query_log_id else None,
            error=str(exc),
        )


def _avg(values: list[int]) -> int:
    return round(statistics.mean(values)) if values else 0


def _pct_improvement(before_ms: int, after_ms: int) -> str:
    if before_ms <= 0:
        return "N/A"
    value = ((before_ms - after_ms) / before_ms) * 100
    return f"{value:.1f}%"


def render_markdown(results: list[BenchmarkResult], models: list[str], source_file: Path) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    by_model = {model: [item for item in results if item.model == model and not item.error] for model in models}
    baseline = models[0] if models else ""
    candidate = models[-1] if models else ""

    lines: list[str] = [
        "# Evidence So Sánh Model AI",
        "",
        f"- Thời điểm chạy: `{now}`",
        f"- File test case: `{source_file}`",
        f"- Models so sánh: `{', '.join(models)}`",
        "- Endpoint logic: `search_food()` nội bộ, không qua frontend.",
        "- Metric chính: latency từng stage lấy từ `query_logs.excluded_summary.llm_runtime.stage_latency_ms`.",
        "",
        "## Tổng Hợp",
        "",
        "| Model | Số case thành công | Avg request total | Avg supervisor | Avg embedding | Avg post-processing | Avg LLM total |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]

    for model in models:
        items = by_model.get(model, [])
        lines.append(
            "| "
            f"`{model}` | "
            f"{len(items)} | "
            f"{_avg([x.request_total_ms for x in items])}ms | "
            f"{_avg([x.supervisor_ms for x in items])}ms | "
            f"{_avg([x.embedding_ms for x in items])}ms | "
            f"{_avg([x.post_processing_ms for x in items])}ms | "
            f"{_avg([x.llm_total_ms for x in items])}ms |"
        )

    if baseline and candidate and baseline != candidate:
        base_items = by_model.get(baseline, [])
        candidate_items = by_model.get(candidate, [])
        base_avg = _avg([x.request_total_ms for x in base_items])
        candidate_avg = _avg([x.request_total_ms for x in candidate_items])
        lines.extend(
            [
                "",
                "## Kết Luận Nhanh",
                "",
                f"- `{candidate}` cải thiện request total trung bình so với `{baseline}`: `{_pct_improvement(base_avg, candidate_avg)}`.",
                "- `embedding` gần như không thay đổi vì vẫn dùng `gemini-embedding-001`; model text chỉ ảnh hưởng `supervisor` và `post_processing`.",
                "- Nếu cần chatbot nhanh hơn nữa, bước tiếp theo nên tối ưu số lần gọi LLM tuần tự, không chỉ đổi model.",
            ]
        )

    lines.extend(["", "## Chi Tiết Từng Test Case", ""])

    grouped: dict[str, list[BenchmarkResult]] = {}
    for item in results:
        grouped.setdefault(item.test_case.test_case_id, []).append(item)

    for test_case_id, items in grouped.items():
        tc = items[0].test_case
        lines.extend(
            [
                f"### {tc.test_case_id} - {tc.verification_tag}",
                "",
                f'Query: "{tc.query}"',
                "",
            ]
        )

        previous = next((item for item in items if item.model == baseline), None)
        current = next((item for item in items if item.model == candidate), None)
        if previous:
            lines.extend(
                [
                    f"Trước đây (`{previous.model}`):",
                    f"supervisor:       {previous.supervisor_ms}ms",
                    f"embedding:        {previous.embedding_ms}ms",
                    f"post_processing:  {previous.post_processing_ms}ms",
                    f"LLM total:       ~{previous.llm_total_ms}ms",
                    f"request total:    {previous.request_total_ms}ms",
                    "",
                ]
            )
        if current:
            lines.extend(
                [
                    f"Hiện tại (`{current.model}`):",
                    f"supervisor:       {current.supervisor_ms}ms",
                    f"embedding:        {current.embedding_ms}ms",
                    f"post_processing:  {current.post_processing_ms}ms",
                    f"LLM total:       ~{current.llm_total_ms}ms",
                    f"request total:    {current.request_total_ms}ms",
                    "",
                ]
            )
        if previous and current:
            lines.append(f"Cải thiện request total: `{_pct_improvement(previous.request_total_ms, current.request_total_ms)}`")
            lines.append("")

    failures = [item for item in results if item.error]
    if failures:
        lines.extend(["## Case Lỗi", ""])
        for item in failures:
            lines.append(f"- `{item.model}` / `{item.test_case.test_case_id}`: {item.error}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


async def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Gemini text models with pathology/search test cases.")
    parser.add_argument("--test-file", type=Path, default=DEFAULT_TEST_FILE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_FILE)
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--sleep", type=float, default=0.0, help="Sleep seconds between cases to avoid rate limits.")
    args = parser.parse_args()

    test_cases = parse_test_cases(args.test_file, limit=args.limit)
    if not test_cases:
        raise SystemExit(f"Không tìm thấy test case hợp lệ trong {args.test_file}")

    results: list[BenchmarkResult] = []
    for test_case in test_cases:
        for model in args.models:
            print(f"▶ {test_case.test_case_id} | {model} | {test_case.query}")
            result = await run_one_case(model, test_case)
            results.append(result)
            status = "ERROR" if result.error else f"{result.request_total_ms}ms"
            print(f"  -> {status}")
            if args.sleep:
                await asyncio.sleep(args.sleep)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_markdown(results, args.models, args.test_file), encoding="utf-8")
    print(f"✅ Đã ghi evidence: {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
