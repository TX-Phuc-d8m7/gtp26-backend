#!/usr/bin/env python3
"""
Dùng Gemini để đề xuất nhãn dining_context cho toàn bộ món ăn trong database.

Mỗi món được phân loại thành một trong ba nhãn:
  "home_cooked"  — thường nấu tại nhà, không phù hợp để gợi ý địa điểm quán ăn
  "restaurant"   — phổ biến bán ở quán ăn, street food, nhà hàng
  "both"         — có thể gặp ở cả hai ngữ cảnh (mặc định an toàn)

Output (để review và chỉnh tay):
  standard-data/dining-context/proposed_dining_context.json
  standard-data/dining-context/proposed_dining_context.csv

Sau khi review xong, áp dụng vào database:
  python scripts/apply_dining_context.py --apply

Ví dụ chạy:
  python scripts/propose_dining_context.py                 # toàn bộ 479 món
  python scripts/propose_dining_context.py --pilot 20      # test 20 món đầu
  python scripts/propose_dining_context.py --overwrite     # phân loại lại từ đầu
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
import time
from pathlib import Path

# ── Thêm project root vào sys.path ───────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv()

from google import genai
from google.genai import types
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.modules.foods.models import Food

# ── Config ────────────────────────────────────────────────────────────────────

PROJECT_ID = os.getenv("PROJECT_ID")
MODEL_ID = "gemini-2.5-flash"
BATCH_SIZE = 15           # Số món mỗi lần gọi LLM
SLEEP_BETWEEN_BATCHES = 2.0   # Giây nghỉ giữa các batch (tránh rate limit)

OUTPUT_DIR = PROJECT_ROOT / "standard-data" / "dining-context"
OUTPUT_JSON = OUTPUT_DIR / "proposed_dining_context.json"
OUTPUT_CSV  = OUTPUT_DIR / "proposed_dining_context.csv"

VALID_CONTEXTS = {"home_cooked", "restaurant", "both"}

# ── LLM client ────────────────────────────────────────────────────────────────

client = genai.Client(vertexai=True, project=PROJECT_ID, location="us-central1")

# ── Prompt ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Bạn là chuyên gia phân loại ẩm thực Việt Nam.
Nhiệm vụ: phân loại ngữ cảnh phục vụ của từng món ăn để quyết định có nên gợi ý địa điểm quán ăn hay không.

Phân loại:

"home_cooked" — Món thường chỉ được nấu và ăn tại nhà, không có hoặc rất hiếm khi bán ở quán ăn.
  Ví dụ điển hình:
  - "Canh mướp nấu nấm" (tên mô tả công thức nấu tại nhà)
  - "Rau muống luộc chấm mắm tôm" (món cơm nhà đơn giản)
  - "Trứng chiên hành lá" (đồ nhà nấu)
  - "Thịt bò hầm khoai tây cà rốt" (nấu theo công thức gia đình)
  - Dấu hiệu: tên gồm nguyên liệu chính + động từ nấu + nguyên liệu phụ (A nấu B, A hầm B, A om B)

"restaurant" — Món phổ biến bán ở quán ăn, nhà hàng, tiệm street food, có tên riêng nổi tiếng.
  Ví dụ điển hình:
  - "Phở bò" (tiệm phở)
  - "Bún bò Huế" (đặc sản vùng miền)
  - "Cơm tấm sườn bì chả" (quán cơm tấm)
  - "Gỏi cuốn" (street food)
  - "Bánh mì pâté" (tiệm bánh mì)
  - "Lẩu thái hải sản" (quán lẩu)

"both" — Phổ biến ở cả nhà lẫn quán, hoặc không đủ thông tin để phân loại rõ ràng.
  Ví dụ:
  - "Cá kho tộ" (vừa là món cơm nhà vừa bán ở quán cơm bình dân)
  - "Gà nướng mật ong" (có thể nhà làm hoặc mua ở quán)
  - Nếu không chắc chắn → chọn "both" (an toàn nhất)

Quy tắc quan trọng:
1. Tên có cấu trúc "[nguyên liệu] nấu/hầm/om [nguyên liệu]" → rất có khả năng "home_cooked"
2. Tên là tên riêng của một món ăn đặc sản/street food nổi tiếng → "restaurant"
3. Khi nghi ngờ → "both"
4. Trường "reason" phải ngắn gọn, ≤ 15 từ tiếng Việt

Trả về JSON array theo đúng format sau, KHÔNG có markdown fence, KHÔNG giải thích thêm:
[
  {"id": "uuid-ở-đây", "dining_context": "home_cooked", "reason": "tên mô tả công thức nấu tại nhà"},
  ...
]"""


def _build_batch_prompt(batch: list[dict]) -> str:
    lines = ["Phân loại các món ăn sau:\n"]
    for item in batch:
        tags_str = ", ".join(item.get("soft_tags", [])[:4]) or "—"
        meal_str = ", ".join(item.get("meal_context", [])) or "—"
        lines.append(
            f'- id="{item["id"]}" | Tên: "{item["name"]}" | Tags: {tags_str} | Bữa ăn: {meal_str}'
        )
    return "\n".join(lines)


# ── Database ──────────────────────────────────────────────────────────────────

async def _load_all_foods() -> list[dict]:
    async with AsyncSessionLocal() as db:
        stmt = select(Food).order_by(Food.name)
        result = await db.execute(stmt)
        foods = result.scalars().all()
        return [
            {
                "id": str(food.id),
                "name": food.name,
                "soft_tags": list(food.soft_tags or []),
                "meal_context": list(food.meal_context or []),
            }
            for food in foods
        ]


# ── LLM batch call ────────────────────────────────────────────────────────────

def _classify_batch(batch: list[dict]) -> list[dict]:
    """Gọi Gemini phân loại một batch. Trả về list {id, dining_context, reason}."""
    prompt = _build_batch_prompt(batch)
    try:
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        raw = response.text.strip()
        # Gỡ markdown fence nếu model trả về có ```json ... ```
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:])
            raw = raw.rsplit("```", 1)[0].strip()

        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            raise ValueError(f"Gemini trả về không phải list: {type(parsed).__name__}")
        return parsed

    except Exception as exc:
        print(f"  ⚠️ Lỗi khi gọi LLM cho batch: {exc}")
        # Fallback: mark all as "both" để không bị mất data
        return [
            {"id": item["id"], "dining_context": "both", "reason": "lỗi phân loại — cần review tay"}
            for item in batch
        ]


# ── Save helpers ──────────────────────────────────────────────────────────────

def _save(results: dict[str, dict], all_foods: list[dict]) -> None:
    """Lưu JSON và CSV theo thứ tự tên món (incremental — an toàn để resume)."""
    name_order = {item["id"]: item["name"] for item in all_foods}
    sorted_rows = sorted(
        results.values(),
        key=lambda r: name_order.get(r["id"], r.get("name", "")),
    )

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(sorted_rows, f, ensure_ascii=False, indent=2)

    with open(OUTPUT_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "name", "dining_context", "reason"])
        writer.writeheader()
        writer.writerows(sorted_rows)


# ── Main ──────────────────────────────────────────────────────────────────────

async def main(pilot: int | None, overwrite: bool) -> None:
    if not PROJECT_ID:
        print("❌ Thiếu PROJECT_ID trong .env — không thể gọi Gemini.")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load kết quả cũ nếu có (để resume khi bị ngắt giữa chừng)
    existing: dict[str, dict] = {}
    if OUTPUT_JSON.exists() and not overwrite:
        with open(OUTPUT_JSON, encoding="utf-8") as f:
            for row in json.load(f):
                existing[row["id"]] = row
        if existing:
            print(f"📂 Resume: đã có {len(existing)} kết quả từ lần chạy trước.")

    # Load món ăn từ DB
    print("🔍 Đang load món ăn từ database...")
    foods = await _load_all_foods()
    print(f"✅ {len(foods)} món ăn.")

    if pilot:
        foods = foods[:pilot]
        print(f"🧪 Pilot mode: chỉ xử lý {pilot} món đầu tiên.")

    # Bỏ qua những món đã có kết quả (resume)
    pending = [f for f in foods if f["id"] not in existing]
    already_done = len(foods) - len(pending)
    if already_done:
        print(f"⏭️  Bỏ qua {already_done} món đã phân loại.")
    print(f"⏳ Cần phân loại: {len(pending)} món.")

    if not pending:
        print("✅ Tất cả đã phân loại. Kiểm tra file output:")
        print(f"   JSON: {OUTPUT_JSON}")
        print(f"   CSV:  {OUTPUT_CSV}")
        return

    results: dict[str, dict] = dict(existing)
    batches = [pending[i:i + BATCH_SIZE] for i in range(0, len(pending), BATCH_SIZE)]
    total_batches = len(batches)

    for batch_idx, batch in enumerate(batches, start=1):
        print(f"\n🤖 Batch {batch_idx}/{total_batches} ({len(batch)} món)...")
        for item in batch:
            print(f"   • {item['name']}")

        classified = _classify_batch(batch)

        # Merge — dùng id làm khóa, bổ sung tên từ food data gốc
        id_to_food = {item["id"]: item for item in batch}
        classified_ids = set()
        for row in classified:
            food_id = row.get("id", "")
            if food_id not in id_to_food:
                print(f"  ⚠️ ID không hợp lệ từ LLM: {food_id!r} — bỏ qua.")
                continue

            ctx = row.get("dining_context", "both")
            if ctx not in VALID_CONTEXTS:
                print(f"  ⚠️ dining_context không hợp lệ: {ctx!r} → chuyển về 'both'")
                ctx = "both"

            food_info = id_to_food[food_id]
            results[food_id] = {
                "id": food_id,
                "name": food_info["name"],
                "dining_context": ctx,
                "reason": str(row.get("reason", "")).strip(),
            }
            classified_ids.add(food_id)
            icon = "🏠" if ctx == "home_cooked" else ("🍜" if ctx == "restaurant" else "🔄")
            print(f"   {icon} {food_info['name']!r} → {ctx}")

        # Fallback cho các id trong batch mà LLM bỏ sót
        for item in batch:
            if item["id"] not in classified_ids and item["id"] not in results:
                results[item["id"]] = {
                    "id": item["id"],
                    "name": item["name"],
                    "dining_context": "both",
                    "reason": "LLM bỏ sót — cần review tay",
                }
                print(f"   ⚠️ {item['name']!r} → both (LLM bỏ sót)")

        # Lưu sau mỗi batch (incremental, an toàn khi bị ngắt)
        _save(results, foods)
        print(f"   💾 Đã lưu {len(results)}/{len(foods)} món.")

        if batch_idx < total_batches:
            time.sleep(SLEEP_BETWEEN_BATCHES)

    # Thống kê cuối
    counts = {"home_cooked": 0, "restaurant": 0, "both": 0}
    for r in results.values():
        counts[r.get("dining_context", "both")] += 1

    print(f"\n{'─'*50}")
    print(f"✅ Hoàn thành! {len(results)} món đã phân loại.")
    print(f"   🏠 home_cooked : {counts['home_cooked']}")
    print(f"   🍜 restaurant  : {counts['restaurant']}")
    print(f"   🔄 both        : {counts['both']}")
    print(f"\n📄 JSON: {OUTPUT_JSON}")
    print(f"📊 CSV : {OUTPUT_CSV}")
    print("\n👉 Bước tiếp theo:")
    print("   1. Mở CSV/JSON, kiểm tra và chỉnh sửa nếu cần.")
    print("   2. Chạy: python scripts/apply_dining_context.py --dry-run")
    print("   3. Chạy: python scripts/apply_dining_context.py --apply")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Đề xuất nhãn dining_context cho tất cả món ăn bằng Gemini."
    )
    parser.add_argument(
        "--pilot",
        type=int,
        default=None,
        metavar="N",
        help="Chỉ xử lý N món đầu tiên (để test trước khi chạy full).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Bỏ qua kết quả cũ, phân loại lại toàn bộ từ đầu.",
    )
    args = parser.parse_args()
    asyncio.run(main(pilot=args.pilot, overwrite=args.overwrite))
