from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import or_, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db.session import AsyncSessionLocal
from app.modules.foods.models import Food
from app.modules.ingredients.service import (
    generate_core_ingredient_keys,
    load_enabled_alias_override_rules,
)


async def backfill_missing_core_ingredient_keys(
    *,
    dry_run: bool = False,
    limit: int | None = None,
) -> tuple[int, int]:
    """
    Sinh lại `core_ingredient_keys` cho các món đang thiếu key trong DB.

    "Thiếu key" ở đây bao gồm:
    - `core_ingredient_keys IS NULL`
    - `core_ingredient_keys = []`
    """
    async with AsyncSessionLocal() as db:
        override_rules = await load_enabled_alias_override_rules(db)

        stmt = (
            select(Food)
            .where(
                or_(
                    Food.core_ingredient_keys.is_(None),
                    Food.core_ingredient_keys == [],
                )
            )
            .order_by(Food.name.asc())
        )
        if limit and limit > 0:
            stmt = stmt.limit(limit)

        foods = (await db.execute(stmt)).scalars().all()
        if not foods:
            print("✅ Không có món nào đang thiếu core_ingredient_keys.")
            return 0, 0

        print(f"🔎 Tìm thấy {len(foods)} món cần sinh lại core_ingredient_keys.")
        updated_count = 0

        for food in foods:
            new_keys = generate_core_ingredient_keys(
                food.core_ingredients or [],
                extra_rules=override_rules,
            )
            print(f"- {food.name}: {new_keys}")
            if food.core_ingredient_keys != new_keys:
                food.core_ingredient_keys = new_keys
                updated_count += 1

        if dry_run:
            await db.rollback()
            print(f"🧪 Dry-run: sẽ cập nhật {updated_count}/{len(foods)} món.")
            return len(foods), updated_count

        await db.commit()
        print(f"✅ Đã cập nhật {updated_count}/{len(foods)} món.")
        return len(foods), updated_count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill core_ingredient_keys cho các món đang NULL hoặc rỗng."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Chỉ in kết quả dự kiến, không ghi vào DB.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Giới hạn số món xử lý để test nhanh.",
    )
    args = parser.parse_args()

    asyncio.run(
        backfill_missing_core_ingredient_keys(
            dry_run=args.dry_run,
            limit=args.limit,
        )
    )


if __name__ == "__main__":
    main()
