#!/usr/bin/env python3
"""
Áp dụng nhãn dining_context đã review vào bảng foods trong database.

Workflow đầy đủ:
  Bước 1 — Đề xuất nhãn (Gemini):
    python scripts/propose_dining_context.py

  Bước 2 — Review và chỉnh tay:
    standard-data/dining-context/proposed_dining_context.json
    (chỉnh "dining_context" cho từng món nếu thấy sai)

  Bước 3 — Xem trước (không thay đổi DB):
    python scripts/apply_dining_context.py --dry-run

  Bước 4 — Áp dụng thực sự:
    python scripts/apply_dining_context.py --apply

Lưu ý:
  - Script tự động thêm cột dining_context vào bảng foods nếu chưa có.
  - Mặc định bảo toàn giá trị hiện tại nếu đã được set thủ công.
    Dùng --force để ghi đè toàn bộ.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# ── Thêm project root vào sys.path ───────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import AsyncSessionLocal

# ── Config ────────────────────────────────────────────────────────────────────

INPUT_JSON = PROJECT_ROOT / "standard-data" / "dining-context" / "proposed_dining_context.json"
VALID_CONTEXTS = {"home_cooked", "restaurant", "both"}


# ── Database helpers ──────────────────────────────────────────────────────────

async def _ensure_column_exists(db) -> bool:
    """Thêm cột dining_context vào bảng foods nếu chưa có. Trả về True nếu vừa tạo mới."""
    check_sql = text("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'foods' AND column_name = 'dining_context'
    """)
    result = await db.execute(check_sql)
    exists = result.fetchone() is not None

    if not exists:
        alter_sql = text("""
            ALTER TABLE foods
            ADD COLUMN dining_context VARCHAR(20) NOT NULL DEFAULT 'both'
        """)
        await db.execute(alter_sql)
        await db.commit()
        print("✅ Đã thêm cột dining_context vào bảng foods (DEFAULT 'both').")
        return True

    return False


async def _get_current_values(db) -> dict[str, str]:
    """Lấy giá trị dining_context hiện tại trong DB (id → value)."""
    result = await db.execute(
        text("SELECT id::text, dining_context FROM foods")
    )
    return {row[0]: row[1] for row in result.fetchall()}


async def _update_batch(db, updates: list[tuple[str, str]]) -> None:
    """Cập nhật dining_context cho danh sách [(food_id, new_value), ...]."""
    for food_id, ctx in updates:
        await db.execute(
            text("UPDATE foods SET dining_context = :ctx WHERE id = :id"),
            {"ctx": ctx, "id": food_id},
        )


# ── Main ──────────────────────────────────────────────────────────────────────

async def main(dry_run: bool, force: bool) -> None:
    # ── Đọc file JSON đã review ──
    if not INPUT_JSON.exists():
        print(f"❌ Không tìm thấy file: {INPUT_JSON}")
        print("   Hãy chạy trước: python scripts/propose_dining_context.py")
        sys.exit(1)

    with open(INPUT_JSON, encoding="utf-8") as f:
        rows: list[dict] = json.load(f)

    # Validate
    valid_rows: list[dict] = []
    skipped = 0
    for row in rows:
        food_id = str(row.get("id", "")).strip()
        ctx = str(row.get("dining_context", "")).strip()
        name = row.get("name", "")
        if not food_id:
            print(f"  ⚠️ Bỏ qua dòng thiếu id: {row}")
            skipped += 1
            continue
        if ctx not in VALID_CONTEXTS:
            print(f"  ⚠️ {name!r}: dining_context={ctx!r} không hợp lệ → chuyển về 'both'")
            ctx = "both"
        valid_rows.append({"id": food_id, "name": name, "dining_context": ctx})

    print(f"📄 Đọc được {len(valid_rows)} dòng hợp lệ từ {INPUT_JSON.name}.")
    if skipped:
        print(f"   ⚠️ Bỏ qua {skipped} dòng lỗi.")

    if dry_run:
        print("\n🔍 DRY-RUN mode — không thay đổi database.\n")
    elif force:
        print("\n⚡ FORCE mode — ghi đè toàn bộ, kể cả đã có giá trị.\n")
    else:
        print("\n✏️  APPLY mode — chỉ cập nhật những món chưa được set hoặc đang là 'both'.\n")

    async with AsyncSessionLocal() as db:
        try:
            # Đảm bảo cột tồn tại
            if not dry_run:
                await _ensure_column_exists(db)
            else:
                # Kiểm tra cột tồn tại để báo cáo dry-run
                check = await db.execute(text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='foods' AND column_name='dining_context'"
                ))
                col_exists = check.fetchone() is not None
                if not col_exists:
                    print("ℹ️  Cột dining_context chưa tồn tại — sẽ được tạo khi chạy --apply.\n")

            # Lấy giá trị hiện tại trong DB
            try:
                current_values = await _get_current_values(db)
            except SQLAlchemyError:
                current_values = {}  # Cột chưa tồn tại

            # Tính toán những dòng cần update
            to_update: list[tuple[str, str]] = []
            counts = {"home_cooked": 0, "restaurant": 0, "both": 0, "skip": 0}

            for row in valid_rows:
                food_id = row["id"]
                new_ctx = row["dining_context"]
                current_ctx = current_values.get(food_id)

                if not force and current_ctx is not None and current_ctx != "both":
                    # Giữ nguyên nếu đã có giá trị thực sự (không phải default)
                    counts["skip"] += 1
                    continue

                if current_ctx == new_ctx:
                    counts["skip"] += 1
                    continue

                to_update.append((food_id, new_ctx))
                counts[new_ctx] = counts.get(new_ctx, 0) + 1

            # Báo cáo
            print(f"📊 Thống kê nhãn trong file review:")
            ctx_counts = {"home_cooked": 0, "restaurant": 0, "both": 0}
            for row in valid_rows:
                ctx_counts[row["dining_context"]] = ctx_counts.get(row["dining_context"], 0) + 1
            print(f"   🏠 home_cooked : {ctx_counts['home_cooked']}")
            print(f"   🍜 restaurant  : {ctx_counts['restaurant']}")
            print(f"   🔄 both        : {ctx_counts['both']}")

            print(f"\n📝 Cần cập nhật: {len(to_update)} dòng.")
            print(f"   ⏭️  Bỏ qua (không đổi hoặc đã có giá trị): {counts['skip']}")

            if to_update:
                print("\nDanh sách sẽ cập nhật:")
                for food_id, new_ctx in to_update[:30]:
                    name = next((r["name"] for r in valid_rows if r["id"] == food_id), food_id)
                    current = current_values.get(food_id, "chưa có")
                    icon = "🏠" if new_ctx == "home_cooked" else ("🍜" if new_ctx == "restaurant" else "🔄")
                    print(f"   {icon} {name!r}: {current!r} → {new_ctx!r}")
                if len(to_update) > 30:
                    print(f"   ... và {len(to_update) - 30} dòng nữa.")

            if dry_run:
                print("\n✅ Dry-run xong. Chạy --apply để áp dụng thực sự.")
                return

            if not to_update:
                print("\n✅ Không có gì cần cập nhật.")
                return

            # Thực hiện update
            print(f"\n⏳ Đang cập nhật {len(to_update)} dòng...")
            await _update_batch(db, to_update)
            await db.commit()
            print(f"✅ Đã cập nhật {len(to_update)} dòng thành công.")
            print(f"   🏠 home_cooked : {counts.get('home_cooked', 0)}")
            print(f"   🍜 restaurant  : {counts.get('restaurant', 0)}")
            print(f"   🔄 both        : {counts.get('both', 0)}")

        except SQLAlchemyError as exc:
            await db.rollback()
            print(f"❌ Lỗi database: {exc}")
            sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Áp dụng nhãn dining_context đã review vào database."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Xem trước những gì sẽ thay đổi, KHÔNG ghi vào database.",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Áp dụng thực sự vào database.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ghi đè toàn bộ, kể cả những món đã có giá trị dining_context rồi.",
    )
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run, force=args.force))
