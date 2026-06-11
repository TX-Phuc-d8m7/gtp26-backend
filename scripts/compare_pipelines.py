"""So sánh kết quả giữa legacy pipeline và semantic_first pipeline.

Chạy:
    source venv/bin/activate
    python scripts/compare_pipelines.py

Mỗi query được chạy qua cả hai pipeline. Script in kết quả song song gồm:
  - Thời gian xử lý
  - Danh sách món trả về (tên + điểm)
  - Số món bị filter/reject ở mỗi bước
  - Điểm khác biệt cụ thể giữa hai luồng
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db.session import AsyncSessionLocal
from app.modules.search.service import search_food_legacy
from app.modules.search.pipeline.orchestrator import semantic_first_search_food
from app.modules.search.schemas import SearchResponse

# ---------------------------------------------------------------------------
# Danh sách query test — chỉnh tùy ý
# ---------------------------------------------------------------------------

TEST_CASES = [
    {
        "label": "Query đơn giản (không bệnh lý)",
        "query": "Tôi muốn ăn bún bò",
        "profile": None,
    },
    {
        "label": "Có bệnh lý Gout",
        "query": "Tôi bị Gout, muốn ăn bún bò",
        "profile": None,
    },
    {
        "label": "Có bệnh lý Tiểu đường, thích đồ ăn nhẹ",
        "query": "Tôi bị tiểu đường, muốn ăn gì nhẹ nhàng cho bữa sáng",
        "profile": None,
    },
    {
        "label": "Dị ứng hải sản, muốn ăn hải sản",
        "query": "Tôi dị ứng tôm nhưng muốn ăn bún hải sản",
        "profile": None,
    },
    {
        "label": "Query ngữ nghĩa phức tạp",
        "query": "Món ăn thanh đạm, ít dầu mỡ, phù hợp buổi tối",
        "profile": None,
    },
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_COL = 46  # độ rộng mỗi cột

def _header(text: str) -> None:
    print(f"\n{'=' * 100}")
    print(f"  {text}")
    print(f"{'=' * 100}")


def _row(label: str, left: str, right: str) -> None:
    print(f"  {label:<22} {left:<{_COL}} {right:<{_COL}}")


def _section(title: str) -> None:
    print(f"\n  {'─' * 96}")
    print(f"  {title}")
    print(f"  {'─' * 96}")


def _format_results(results) -> list[str]:
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"  {i}. {r.name:<35} {r.matchScore:.1f}%")
    return lines if lines else ["  (không có kết quả)"]


def _extract_legacy_stats(response: SearchResponse) -> dict:
    summary = {}
    ex = response.retrieval_trace or {}
    if isinstance(ex, dict):
        hf = ex.get("hard_filter", {})
        summary["candidates_after_sql"] = hf.get("candidate_count_after_sql", "?")
        summary["python_removed"] = hf.get("python_removed_count", 0)
        summary["allergy_removed"] = hf.get("allergy_text_removed_count", 0)
        summary["soft_tag_removed"] = hf.get("medical_soft_tag_removed_count", 0)

        emb = ex.get("embedding", {})
        summary["scored_count"] = emb.get("scored_count", "?")
        summary["retrieval_mode"] = emb.get("retrieval_mode", "?")

        val = ex.get("final_validation", {})
        summary["validation_status"] = val.get("status", "skipped")
        summary["validation_rejected"] = len(val.get("rejected_foods", []))
        rejected_names = [f["name"] for f in (val.get("rejected_foods") or [])]
        summary["validation_rejected_names"] = rejected_names
    return summary


def _extract_semantic_stats(response: SearchResponse) -> dict:
    summary = {}
    ex = response.retrieval_trace or {}
    if isinstance(ex, dict):
        ret = ex.get("retrieval", {})
        summary["retrieval_mode"] = ret.get("mode", "?")
        summary["candidates_retrieved"] = ret.get("candidate_count", "?")
        summary["expanded_top_k"] = ret.get("expanded_top_k")

        cs = ex.get("critical_safety", {})
        summary["rejected_count"] = cs.get("rejected_count", 0)
        summary["safe_count"] = cs.get("safe_count", "?")
        rejected_sample = cs.get("rejected_sample") or []
        summary["rejected_names"] = [r.get("food_name") for r in rejected_sample[:5]]

        ss = ex.get("soft_scoring", {})
        summary["scored_count"] = ss.get("scored_count", "?")
    return summary


def _diff_results(legacy_results, semantic_results) -> list[str]:
    legacy_names = {r.name for r in legacy_results}
    semantic_names = {r.name for r in semantic_results}

    only_legacy = legacy_names - semantic_names
    only_semantic = semantic_names - legacy_names
    common = legacy_names & semantic_names

    lines = []
    if common:
        lines.append(f"  Trùng nhau ({len(common)}): {', '.join(sorted(common))}")
    if only_legacy:
        lines.append(f"  Chỉ legacy ({len(only_legacy)}): {', '.join(sorted(only_legacy))}")
    if only_semantic:
        lines.append(f"  Chỉ semantic ({len(only_semantic)}): {', '.join(sorted(only_semantic))}")
    return lines or ["  Kết quả giống hệt nhau."]


# ---------------------------------------------------------------------------
# Core comparison function
# ---------------------------------------------------------------------------

async def compare_one(case: dict) -> None:
    query = case["query"]
    profile = case.get("profile")

    _header(f"[{case['label']}]  Query: \"{query}\"")

    async with AsyncSessionLocal() as db:
        # --- Legacy ---
        t0 = time.perf_counter()
        try:
            legacy_resp = await search_food_legacy(
                query=query, db=db, profile=profile, top_k=5, debug=True
            )
        except Exception as exc:
            print(f"\n  ❌ LEGACY lỗi: {exc}")
            legacy_resp = None
        legacy_ms = round((time.perf_counter() - t0) * 1000)

    async with AsyncSessionLocal() as db:
        # --- Semantic-first ---
        t0 = time.perf_counter()
        try:
            semantic_resp = await semantic_first_search_food(
                query=query, db=db, profile=profile, top_k=5, debug=True
            )
        except Exception as exc:
            print(f"\n  ❌ SEMANTIC lỗi: {exc}")
            semantic_resp = None
        semantic_ms = round((time.perf_counter() - t0) * 1000)

    # --- Header columns ---
    print()
    _row("", "── LEGACY ──", "── SEMANTIC FIRST ──")

    # Timing
    faster = "legacy" if legacy_ms < semantic_ms else "semantic"
    delta = abs(legacy_ms - semantic_ms)
    _row("⏱  Thời gian", f"{legacy_ms} ms", f"{semantic_ms} ms  (delta {delta}ms, {faster} nhanh hơn)")

    # Retrieval mode
    if legacy_resp and semantic_resp:
        l_stats = _extract_legacy_stats(legacy_resp)
        s_stats = _extract_semantic_stats(semantic_resp)

        _row("🔍 Retrieval mode", str(l_stats.get("retrieval_mode", "?")), str(s_stats.get("retrieval_mode", "?")))

        # Candidates / filtering
        _section("Pool & Filter")
        _row("Candidates vào scoring",
             str(l_stats.get("candidates_after_sql", "?")),
             str(s_stats.get("candidates_retrieved", "?")))
        _row("Scored count",
             str(l_stats.get("scored_count", "?")),
             str(s_stats.get("scored_count", "?")))
        _row("Bị loại (ingredient key)",
             str(l_stats.get("python_removed", 0)),
             str(s_stats.get("rejected_count", 0)) + " (sau retrieval)")
        _row("Bị loại (allergy text)",
             str(l_stats.get("allergy_removed", 0)),
             "(gộp trong rejected_count)")
        _row("Bị loại (soft tag)",
             str(l_stats.get("soft_tag_removed", 0)),
             "(gộp trong rejected_count)")

        if s_stats.get("rejected_names"):
            print(f"\n  Safety rejected (semantic): {', '.join(s_stats['rejected_names'])}")

        if s_stats.get("expanded_top_k"):
            print(f"\n  ⚡ Retrieval expansion kích hoạt: top_k mở rộng → {s_stats['expanded_top_k']}")

        # Validation step
        _section("Validation LLM")
        val_status = l_stats.get("validation_status", "skipped")
        val_rejected = l_stats.get("validation_rejected", 0)
        val_names = l_stats.get("validation_rejected_names", [])
        legacy_val_str = f"{val_status}"
        if val_rejected:
            legacy_val_str += f" | REJECT {val_rejected} món: {', '.join(val_names)}"
        _row("Validation", legacy_val_str, "Không có (bỏ hẳn)")

    # Results
    _section("Kết quả trả về")
    if legacy_resp and semantic_resp:
        legacy_lines = _format_results(legacy_resp.results)
        semantic_lines = _format_results(semantic_resp.results)
        max_lines = max(len(legacy_lines), len(semantic_lines))
        for i in range(max_lines):
            l = legacy_lines[i] if i < len(legacy_lines) else ""
            s = semantic_lines[i] if i < len(semantic_lines) else ""
            print(f"  {l:<{_COL + 4}} {s}")

        # Diff
        _section("Phân tích khác biệt")
        diff_lines = _diff_results(legacy_resp.results, semantic_resp.results)
        for line in diff_lines:
            print(line)

        # Warning
        lw = (legacy_resp.ai_insight.warning_message or "").strip()
        sw = (semantic_resp.ai_insight.warning_message or "").strip()
        if lw or sw:
            _section("Warning message")
            if lw:
                print(f"  Legacy:   {lw[:120]}")
            if sw:
                print(f"  Semantic: {sw[:120]}")


async def main() -> None:
    print("\n" + "█" * 100)
    print("  PIPELINE COMPARISON: legacy vs semantic_first")
    print("  Mỗi query chạy qua cả hai pipeline. Log chi tiết của từng pipeline xuất hiện ở trên.")
    print("█" * 100)

    for case in TEST_CASES:
        await compare_one(case)
        print()

    print("\n" + "█" * 100)
    print("  KẾT THÚC SO SÁNH")
    print("█" * 100 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
