"""
Test script cho Intent Classifier
==================================
Chạy: python scripts/test_intent_classifier.py

Yêu cầu: phải có file .env ở thư mục backend/
Script tự load dotenv rồi gọi classify_intent thực tế.

Output:
  - Per-intent accuracy
  - Confusion matrix
  - Kết quả lưu vào scripts/intent_classifier_results.json
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Bootstrap: thêm thư mục backend vào sys.path và load .env
# ---------------------------------------------------------------------------
BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_ROOT / ".env")

# Import sau khi sys.path đã được thiết lập
from app.modules.chat.engine.intent_classifier import classify_intent, INTENT_OPTIONS  # noqa: E402

# ---------------------------------------------------------------------------
# Định nghĩa test case
# ---------------------------------------------------------------------------

@dataclass
class TestCase:
    id: int
    description: str
    current_query: str
    expected_intent: str
    # Context (tuỳ chọn)
    last_user_message: str | None = None
    last_assistant_message: str | None = None
    last_assistant_has_food_results: bool = False
    last_food_names: list[str] = field(default_factory=list)
    last_intent: str | None = None


# ---------------------------------------------------------------------------
# 60+ test cases  — phủ đủ 7 intent x nhiều ngữ cảnh
# ---------------------------------------------------------------------------
TEST_CASES: list[TestCase] = [

    # ── greeting (9 cases) ──────────────────────────────────────────────
    TestCase(1,  "Chào đơn giản",          "Chào bạn",               "greeting"),
    TestCase(2,  "Hello",                   "Hello",                  "greeting"),
    TestCase(3,  "Hi bot",                  "Hi",                     "greeting"),
    TestCase(4,  "Xin chào",               "Xin chào",               "greeting"),
    TestCase(5,  "Chào buổi sáng",         "Chào buổi sáng bạn",     "greeting"),
    TestCase(6,  "Hey there",               "Hey",                    "greeting"),
    TestCase(7,  "Chào bot",               "Chào bot ơi",            "greeting"),
    TestCase(8,  "Chào + tên",             "Chào bạn, mình mới dùng lần đầu", "greeting"),
    TestCase(9,  "Helo typo",              "Helo",                   "greeting"),

    # ── new_search (12 cases) ────────────────────────────────────────────
    TestCase(10, "Ăn gì hôm nay",         "Hôm nay mình nên ăn gì?",                 "new_search"),
    TestCase(11, "Gợi ý bữa trưa",        "Gợi ý cho mình món ăn trưa nhẹ",         "new_search"),
    TestCase(12, "Tìm món ít calo",        "Tìm món ăn ít calo cho buổi tối",        "new_search"),
    TestCase(13, "Món giàu đạm",           "Tôi muốn ăn gì nhiều protein",           "new_search"),
    TestCase(14, "Ăn tối nay",             "Tối nay ăn gì ngon",                     "new_search"),
    TestCase(15, "Món Việt nhẹ",           "Gợi ý món Việt Nam thanh đạm",           "new_search"),
    TestCase(16, "Món cho người ăn kiêng", "Món ăn phù hợp cho người đang giảm cân", "new_search"),
    TestCase(17, "Ăn sáng nhanh",         "Ăn sáng nhanh có gì ngon",               "new_search"),
    TestCase(18, "Món không cay",          "Tìm món không cay cho mình",             "new_search"),
    TestCase(19, "Đổi món hôm nay",        "Cho mình gợi ý món khác hôm nay",
             "new_search",
             last_user_message="Hôm qua ăn phở",
             last_intent="new_search"),
    TestCase(20, "Món chay",               "Gợi ý món chay ngon",                    "new_search"),
    TestCase(21, "Món no bụng",            "Muốn ăn gì no, ít tiền",                 "new_search"),

    # ── follow_up (9 cases) ──────────────────────────────────────────────
    TestCase(22, "Loại món nước",
             "Bỏ mấy món nước đi",
             "follow_up",
             last_assistant_has_food_results=True,
             last_food_names=["Phở bò", "Bún bò", "Cơm gà", "Xôi xéo"],
             last_intent="new_search"),

    TestCase(23, "Ưu tiên thanh đạm",
             "Mấy món trên ưu tiên thanh đạm hơn",
             "follow_up",
             last_assistant_has_food_results=True,
             last_food_names=["Bún bò", "Cơm sườn", "Gỏi cuốn"],
             last_intent="new_search"),

    TestCase(24, "Loại món chiên",
             "Loại ra các món chiên",
             "follow_up",
             last_assistant_has_food_results=True,
             last_food_names=["Cơm sườn chiên", "Gà chiên"],
             last_intent="new_search"),

    TestCase(25, "Không thích gỏi",
             "Không thích ăn gỏi",
             "follow_up",
             last_assistant_has_food_results=True,
             last_food_names=["Gỏi cuốn", "Gỏi gà", "Cơm tấm"],
             last_intent="new_search"),

    TestCase(26, "Sắp xếp lại",
             "Sắp xếp lại theo độ phù hợp",
             "follow_up",
             last_assistant_has_food_results=True,
             last_food_names=["Bún chả", "Phở gà"],
             last_intent="new_search"),

    TestCase(27, "Loại bún phở",
             "Bỏ những món bún và phở",
             "follow_up",
             last_assistant_has_food_results=True,
             last_food_names=["Bún bò", "Phở bò", "Cơm gà"],
             last_intent="new_search"),

    TestCase(28, "Ưu tiên ấm bụng",
             "Ưu tiên món ấm bụng hơn trong mấy món trên",
             "follow_up",
             last_assistant_has_food_results=True,
             last_food_names=["Cháo", "Súp", "Xôi"],
             last_intent="new_search"),

    TestCase(29, "Loại món sống",
             "Loại các món sống/tái ra",
             "follow_up",
             last_assistant_has_food_results=True,
             last_food_names=["Bò tái", "Gỏi gà"],
             last_intent="new_search"),

    TestCase(30, "Loại top 3",
             "Loại top 3 đó ra, còn lại gợi ý gì",
             "follow_up",
             last_assistant_has_food_results=True,
             last_food_names=["Bún bò", "Phở gà", "Cơm sườn", "Bánh mì"],
             last_intent="new_search"),

    # ── food_info (8 cases) ──────────────────────────────────────────────
    TestCase(31, "Hỏi thành phần",         "Phở bò có những thành phần gì?",          "food_info"),
    TestCase(32, "Calo món ăn",            "Bánh mì thịt bao nhiêu calo?",            "food_info"),
    TestCase(33, "Mô tả bún bò",           "Bún bò Huế là gì, mô tả cho mình nghe",  "food_info"),
    TestCase(34, "Protein trong thịt",     "Cơm gà có bao nhiêu protein?",            "food_info"),
    TestCase(35, "Nguyên liệu chả cá",    "Chả cá Lã Vọng làm từ gì?",              "food_info"),
    TestCase(36, "Nên ăn lúc nào",        "Xôi nên ăn lúc nào thì hợp?",            "food_info"),
    TestCase(37, "Kcal gỏi cuốn",         "Gỏi cuốn tôm thịt bao nhiêu kcal?",      "food_info"),
    TestCase(38, "Mô tả cháo",            "Cháo trắng có gì đặc biệt?",             "food_info"),

    # ── food_safety_check (8 cases) ──────────────────────────────────────
    TestCase(39, "Tiểu đường ăn phở",
             "Người bị tiểu đường ăn phở có sao không?",
             "food_safety_check"),

    TestCase(40, "Dị ứng hải sản",
             "Mình dị ứng hải sản, ăn cháo hải sản có sao không?",
             "food_safety_check"),

    TestCase(41, "Gout ăn thịt đỏ",
             "Bị gout có ăn được bò né không?",
             "food_safety_check"),

    TestCase(42, "Huyết áp cao",
             "Huyết áp cao ăn mì tôm có an toàn không?",
             "food_safety_check"),

    TestCase(43, "Có ổn không",
             "Cơm tấm sườn ăn vào buổi tối có ổn không?",
             "food_safety_check"),

    TestCase(44, "Lactose intolerance",
             "Không dung nạp lactose uống sữa chua được không?",
             "food_safety_check"),

    TestCase(45, "Trẻ em ăn được không",
             "Trẻ 3 tuổi ăn bánh tráng trộn có hại không?",
             "food_safety_check"),

    TestCase(46, "Có dị ứng",
             "Ăn tôm có gây dị ứng không?",
             "food_safety_check"),

    # ── location_search (8 cases) ────────────────────────────────────────
    TestCase(47, "Tìm quán phở",
             "Quán phở ngon ở Liên Chiểu",
             "location_search"),

    TestCase(48, "Địa chỉ bán bún",
             "Địa chỉ bán bún bò Huế gần đây",
             "location_search"),

    TestCase(49, "Quán gần Bách Khoa",
             "Quán ăn gần Đại học Bách Khoa Đà Nẵng",
             "location_search"),

    TestCase(50, "Tìm quán cơm",
             "Tìm quán cơm bình dân ở Đà Nẵng",
             "location_search"),

    TestCase(51, "Bán cháo ở đâu",
             "Cháo gà ở đâu ngon, gần trung tâm",
             "location_search"),

    TestCase(52, "Quán chay gần đây",
             "Quán ăn chay ngon gần đây",
             "location_search"),

    TestCase(53, "Mua bánh mì đâu",
             "Bánh mì que ở đâu bán ngon nhất",
             "location_search"),

    TestCase(54, "Theo dõi từ food_info",
             "Bán ở đâu?",
             "location_search",
             last_user_message="Bún đậu mắm tôm có thành phần gì?",
             last_assistant_message="Bún đậu mắm tôm gồm bún tươi, đậu phụ chiên, mắm tôm...",
             last_intent="food_info"),

    # ── off_topic (6 cases) ──────────────────────────────────────────────
    TestCase(55, "Hỏi về code",
             "Làm sao viết API bằng FastAPI?",
             "off_topic"),

    TestCase(56, "Thời tiết",
             "Hôm nay trời nắng hay mưa?",
             "off_topic"),

    TestCase(57, "NodeJS",
             "Giải thích Node.js cho mình",
             "off_topic"),

    TestCase(58, "Giá cổ phiếu",
             "Cổ phiếu VNM hôm nay thế nào?",
             "off_topic"),

    TestCase(59, "Python crawl",
             "Hướng dẫn crawl web bằng Python",
             "off_topic"),

    TestCase(60, "Hỏi về bóng đá",
             "Đêm nay có trận bóng nào không?",
             "off_topic"),

    # ── Edge cases / Ambiguous ───────────────────────────────────────────
    TestCase(61, "Chào kèm hỏi (new_search)",
             "Chào bạn, mình muốn tìm món ăn sáng nhanh",
             "new_search"),

    TestCase(62, "Follow-up không có kết quả cũ → new_search",
             "Loại bỏ các món nước đi",
             "new_search",                    # không có last_food_results → new_search
             last_assistant_has_food_results=False),

    TestCase(63, "Hỏi thông tin sau new_search",
             "Cơm gà có bao nhiêu calo?",
             "food_info",
             last_assistant_has_food_results=True,
             last_food_names=["Cơm gà", "Cơm sườn"],
             last_intent="new_search"),

    TestCase(64, "Safety check kết hợp location",
             "Bị tiểu đường có ăn bún bò không và quán nào phù hợp?",
             "food_safety_check"),          # intent chính là safety

    TestCase(65, "Không rõ ràng nhưng có context tốt",
             "Còn gì nữa không?",
             "follow_up",
             last_assistant_has_food_results=True,
             last_food_names=["Phở bò", "Cơm tấm"],
             last_intent="new_search"),
]

# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

@dataclass
class TestResult:
    case: TestCase
    predicted: str
    confidence: float
    extracted: dict[str, Any]
    passed: bool
    latency_ms: float
    error: str | None = None


async def run_single(case: TestCase) -> TestResult:
    t0 = time.perf_counter()
    error = None
    predicted = "ERROR"
    confidence = 0.0
    extracted: dict[str, Any] = {}

    try:
        result = await classify_intent(
            current_query=case.current_query,
            last_user_message=case.last_user_message,
            last_assistant_message=case.last_assistant_message,
            last_assistant_has_food_results=case.last_assistant_has_food_results,
            last_food_names=case.last_food_names,
            last_intent=case.last_intent,
        )
        predicted = result.get("intent", "ERROR")
        confidence = float(result.get("confidence") or 0.0)
        extracted = result.get("extracted") or {}
    except Exception as exc:
        error = str(exc)

    latency_ms = (time.perf_counter() - t0) * 1000
    passed = predicted == case.expected_intent

    return TestResult(
        case=case,
        predicted=predicted,
        confidence=confidence,
        extracted=extracted,
        passed=passed,
        latency_ms=latency_ms,
        error=error,
    )


async def run_all(concurrency: int = 5) -> list[TestResult]:
    """Chạy song song theo batch để tránh rate-limit Gemini."""
    results: list[TestResult] = []
    total = len(TEST_CASES)

    for i in range(0, total, concurrency):
        batch = TEST_CASES[i : i + concurrency]
        batch_results = await asyncio.gather(*[run_single(tc) for tc in batch])
        results.extend(batch_results)

        # Progress
        done = min(i + concurrency, total)
        print(f"  [{done:>3}/{total}] " + " ".join(
            ("✅" if r.passed else f"❌({r.predicted})") for r in batch_results
        ))

    return results


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _confusion_matrix(results: list[TestResult]) -> dict[str, dict[str, int]]:
    matrix: dict[str, dict[str, int]] = {
        intent: {i: 0 for i in INTENT_OPTIONS} for intent in INTENT_OPTIONS
    }
    for r in results:
        exp = r.case.expected_intent
        pred = r.predicted if r.predicted in INTENT_OPTIONS else "ERROR"
        if exp in matrix:
            if pred in matrix[exp]:
                matrix[exp][pred] += 1
            else:
                matrix[exp]["off_topic"] += 1   # bucket lỗi vào off_topic
    return matrix


def _print_report(results: list[TestResult]) -> None:
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    accuracy = passed / total * 100

    print("\n" + "=" * 70)
    print(f"  INTENT CLASSIFIER — KẾT QUẢ TEST")
    print(f"  Tổng: {total}  |  Đúng: {passed}  |  Sai: {total - passed}")
    print(f"  Accuracy tổng thể: {accuracy:.1f}%")
    print("=" * 70)

    # Per-intent accuracy
    by_intent: dict[str, list[TestResult]] = defaultdict(list)
    for r in results:
        by_intent[r.case.expected_intent].append(r)

    print(f"\n{'Intent':<22} {'#Cases':>7} {'Correct':>8} {'Accuracy':>10}  {'Avg conf':>10}  {'Avg ms':>8}")
    print("-" * 70)
    for intent in INTENT_OPTIONS:
        cases = by_intent.get(intent, [])
        if not cases:
            continue
        n = len(cases)
        ok = sum(1 for r in cases if r.passed)
        avg_conf = sum(r.confidence for r in cases) / n
        avg_ms = sum(r.latency_ms for r in cases) / n
        mark = "✅" if ok == n else ("⚠️ " if ok / n >= 0.5 else "❌")
        print(f"{mark} {intent:<20} {n:>7} {ok:>8} {ok/n*100:>9.1f}%  {avg_conf:>9.2f}   {avg_ms:>7.0f}ms")

    # Confusion matrix
    matrix = _confusion_matrix(results)
    col_w = 13
    print("\nConfusion Matrix  (hàng = expected, cột = predicted):")
    header = f"{'':22}" + "".join(f"{i[:col_w]:>{col_w}}" for i in INTENT_OPTIONS)
    print(header)
    print("-" * (22 + col_w * len(INTENT_OPTIONS)))
    for exp in INTENT_OPTIONS:
        row_data = matrix.get(exp, {})
        if not any(row_data.values()):
            continue
        row = f"{exp:<22}" + "".join(
            f"{row_data.get(pred, 0):>{col_w}}" for pred in INTENT_OPTIONS
        )
        print(row)

    # Failed cases
    failed = [r for r in results if not r.passed]
    if failed:
        print(f"\n{'─'*70}")
        print(f"  CÁC CASE SAI ({len(failed)}):")
        print(f"{'─'*70}")
        for r in failed:
            tc = r.case
            error_note = f"  [ERR: {r.error}]" if r.error else ""
            print(
                f"  #{tc.id:>3}  [{tc.expected_intent:<20}] → predicted: {r.predicted:<20}"
                f"  conf={r.confidence:.2f}  {tc.current_query[:55]!r}{error_note}"
            )

    # Avg latency overall
    all_ms = [r.latency_ms for r in results]
    print(f"\n  Latency trung bình: {sum(all_ms)/len(all_ms):.0f}ms  |  max: {max(all_ms):.0f}ms  |  min: {min(all_ms):.0f}ms")
    print("=" * 70)


def _save_json(results: list[TestResult], out_path: Path) -> None:
    payload = {
        "summary": {
            "total": len(results),
            "passed": sum(1 for r in results if r.passed),
            "accuracy": round(sum(1 for r in results if r.passed) / len(results) * 100, 2),
        },
        "per_intent": {},
        "cases": [],
    }

    by_intent: dict[str, list[TestResult]] = defaultdict(list)
    for r in results:
        by_intent[r.case.expected_intent].append(r)

    for intent, cases in by_intent.items():
        n = len(cases)
        ok = sum(1 for r in cases if r.passed)
        payload["per_intent"][intent] = {
            "total": n,
            "correct": ok,
            "accuracy": round(ok / n * 100, 2),
        }

    for r in results:
        tc = r.case
        payload["cases"].append({
            "id": tc.id,
            "description": tc.description,
            "query": tc.current_query,
            "expected": tc.expected_intent,
            "predicted": r.predicted,
            "passed": r.passed,
            "confidence": round(r.confidence, 3),
            "latency_ms": round(r.latency_ms, 1),
            "extracted": r.extracted,
            "context": {
                "last_user_message": tc.last_user_message,
                "last_assistant_has_food_results": tc.last_assistant_has_food_results,
                "last_food_names": tc.last_food_names,
                "last_intent": tc.last_intent,
            },
            "error": r.error,
        })

    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  Kết quả JSON lưu tại: {out_path}")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

async def main() -> None:
    print(f"\n{'='*70}")
    print(f"  INTENT CLASSIFIER TEST  —  {len(TEST_CASES)} test cases")
    print(f"  Intents: {', '.join(INTENT_OPTIONS)}")
    print(f"{'='*70}\n")

    t_start = time.perf_counter()
    results = await run_all(concurrency=5)
    elapsed = time.perf_counter() - t_start

    print(f"\n  Hoàn thành trong {elapsed:.1f}s")
    _print_report(results)

    out_path = Path(__file__).parent / "intent_classifier_results.json"
    _save_json(results, out_path)


if __name__ == "__main__":
    asyncio.run(main())
