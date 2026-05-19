from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.integrations.vertex_ai import build_food_embed_text, generate_embedding_for_text
from app.models import Food, Tag
from app.modules.ingredients.service import (
    generate_core_ingredient_keys,
    load_enabled_alias_override_rules,
)
from app.shared.paths import STANDARD_DATA_DIR


def _food_seed_path() -> Path:
    categorized_file_path = (
        STANDARD_DATA_DIR
        / "ingredients-data"
        / "food-clean-categorized"
        / "raw_foods_enriched_labeled(final_488).categorized.clean.json"
    )
    legacy_categorized_file_path = (
        STANDARD_DATA_DIR
        / "ingredients-data"
        / "raw_foods_enriched_labeled(final_488).categorized.clean.json"
    )
    return categorized_file_path if categorized_file_path.exists() else legacy_categorized_file_path


async def sync_tags(db: AsyncSession) -> tuple[int, int]:
    print("🏥 Đang kiểm tra và đồng bộ dữ liệu từ tags_data.json...")
    tags_file_path = STANDARD_DATA_DIR / "tags_data.json"

    if not tags_file_path.exists():
        print(f"⚠️ Không tìm thấy file {tags_file_path}")
        return 0, 0

    with tags_file_path.open("r", encoding="utf-8") as f:
        tags_data = json.load(f)

    existing_tags_result = await db.execute(select(Tag))
    existing_tags = {tag.name: tag for tag in existing_tags_result.scalars().all()}

    new_count = 0
    update_count = 0

    for item in tags_data:
        tag_name = item.get("name")
        if not tag_name:
            continue

        new_tag_type = item.get("tag_type")
        new_exclude_soft = item.get("exclude_soft_tag", [])
        new_prefer_soft = item.get("prefer_soft_tag", [])
        new_exclude_ing = item.get("exclude_ingredient", [])
        new_prefer_ing = item.get("prefer_ingredient", [])

        if tag_name in existing_tags:
            tag = existing_tags[tag_name]
            is_tag_changed = (
                tag.tag_type != new_tag_type
                or tag.exclude_soft_tag != new_exclude_soft
                or tag.prefer_soft_tag != new_prefer_soft
                or tag.exclude_ingredient != new_exclude_ing
                or tag.prefer_ingredient != new_prefer_ing
            )

            if is_tag_changed:
                tag.tag_type = new_tag_type
                tag.exclude_soft_tag = new_exclude_soft
                tag.prefer_soft_tag = new_prefer_soft
                tag.exclude_ingredient = new_exclude_ing
                tag.prefer_ingredient = new_prefer_ing
                update_count += 1
        else:
            db.add(
                Tag(
                    name=tag_name,
                    tag_type=new_tag_type,
                    exclude_soft_tag=new_exclude_soft,
                    prefer_soft_tag=new_prefer_soft,
                    exclude_ingredient=new_exclude_ing,
                    prefer_ingredient=new_prefer_ing,
                )
            )
            new_count += 1

    await db.commit()
    print(f"✅ Hoàn tất đồng bộ Tags: Thêm mới {new_count} quy tắc, Cập nhật {update_count} quy tắc.")
    return new_count, update_count


async def sync_foods(db: AsyncSession) -> tuple[int, int, int]:
    print("📂 Đang kiểm tra và đồng bộ dữ liệu món ăn đã phân category...")
    file_path = _food_seed_path()

    if not file_path.exists():
        print(f"❌ Không tìm thấy file {file_path}")
        return 0, 0, 0

    print(f"📄 Food seed source: {file_path}")
    with file_path.open("r", encoding="utf-8") as f:
        foods_data = json.load(f)

    existing_foods_result = await db.execute(select(Food))
    existing_foods = {food.name: food for food in existing_foods_result.scalars().all()}
    alias_override_rules = await load_enabled_alias_override_rules(db)

    new_count = 0
    update_count = 0
    reset_embedding_count = 0

    for item in foods_data:
        food_name = item.get("name")
        if not food_name:
            continue

        new_core_ingredients = item.get("core_ingredients", [])
        new_raw_ingredients = item.get("raw_ingredients", [])
        new_raw_instructions = item.get("raw_instructions", item.get("instructions", ""))
        new_core_ingredient_keys = generate_core_ingredient_keys(
            new_core_ingredients,
            extra_rules=alias_override_rules,
        )
        new_description = item.get("description", "")
        new_soft_tags = item.get("soft_tags", [])
        new_taste_profile = item.get("taste_profile", [])
        new_meal_context = item.get("meal_context", [])
        new_occasion_context = item.get("occasion_context", [])

        if food_name in existing_foods:
            food = existing_foods[food_name]
            is_embedding_text_changed = (
                food.core_ingredients != new_core_ingredients
                or food.description != new_description
                or food.soft_tags != new_soft_tags
                or food.taste_profile != new_taste_profile
                or food.meal_context != new_meal_context
                or food.occasion_context != new_occasion_context
            )
            is_storage_changed = (
                is_embedding_text_changed
                or food.raw_ingredients != new_raw_ingredients
                or food.raw_instructions != new_raw_instructions
                or food.core_ingredient_keys != new_core_ingredient_keys
            )

            if is_storage_changed:
                food.core_ingredients = new_core_ingredients
                food.raw_ingredients = new_raw_ingredients
                food.raw_instructions = new_raw_instructions
                food.core_ingredient_keys = new_core_ingredient_keys
                food.description = new_description
                food.soft_tags = new_soft_tags
                food.taste_profile = new_taste_profile
                food.meal_context = new_meal_context
                food.occasion_context = new_occasion_context

                if is_embedding_text_changed:
                    food.embedding = None
                    reset_embedding_count += 1

                update_count += 1
        else:
            db.add(
                Food(
                    name=food_name,
                    core_ingredients=new_core_ingredients,
                    raw_ingredients=new_raw_ingredients,
                    raw_instructions=new_raw_instructions,
                    core_ingredient_keys=new_core_ingredient_keys,
                    description=new_description,
                    soft_tags=new_soft_tags,
                    taste_profile=new_taste_profile,
                    meal_context=new_meal_context,
                    occasion_context=new_occasion_context,
                    embedding=None,
                )
            )
            new_count += 1
            reset_embedding_count += 1

    await db.commit()
    print(
        "✅ Hoàn tất đồng bộ món ăn: "
        f"Thêm mới {new_count} món, Cập nhật {update_count} món, "
        f"Cần tạo lại embedding {reset_embedding_count} món."
    )
    return new_count, update_count, reset_embedding_count


async def backfill_missing_embeddings(
    db: AsyncSession,
    *,
    limit: Optional[int] = None,
    sleep_seconds: float = 3,
) -> tuple[int, int]:
    stmt = select(Food).where(Food.embedding.is_(None)).order_by(Food.name)
    if limit:
        stmt = stmt.limit(limit)

    result = await db.execute(stmt)
    foods_to_vectorize = result.scalars().all()

    if not foods_to_vectorize:
        print("✨ Tất cả món ăn đã có Vector AI.")
        return 0, 0

    print(f"🚀 Bắt đầu tạo Vector cho {len(foods_to_vectorize)} món...")
    success_count = 0
    failed_count = 0

    for i, food in enumerate(foods_to_vectorize):
        text_to_embed = build_food_embed_text(food)
        vector = await generate_embedding_for_text(text_to_embed)

        if vector:
            food.embedding = vector
            await db.commit()
            success_count += 1
            print(f"[{i + 1}/{len(foods_to_vectorize)}] ✅ Vectorized: {food.name}")
        else:
            failed_count += 1
            print(f"[{i + 1}/{len(foods_to_vectorize)}] ❌ Embedding thất bại: {food.name}")

        if sleep_seconds > 0 and i < len(foods_to_vectorize) - 1:
            await asyncio.sleep(sleep_seconds)

    print(f"Hoàn tất embedding: thành công {success_count}, thất bại {failed_count}.")
    return success_count, failed_count


async def seed_data(
    *,
    sync_tags_enabled: bool = True,
    sync_foods_enabled: bool = True,
    run_embedding_enabled: bool = False,
    embedding_limit: Optional[int] = None,
    embedding_sleep_seconds: float = 3,
) -> None:
    async with AsyncSessionLocal() as db:
        if sync_tags_enabled:
            await sync_tags(db)
        else:
            print("⏭️ Bỏ qua sync tags.")

        if sync_foods_enabled:
            await sync_foods(db)
        else:
            print("⏭️ Bỏ qua sync foods.")

        if run_embedding_enabled:
            await backfill_missing_embeddings(
                db,
                limit=embedding_limit,
                sleep_seconds=embedding_sleep_seconds,
            )
        else:
            print("⏭️ Bỏ qua tạo embedding khi seed.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync seed data and optionally backfill embeddings.")
    parser.add_argument("--tags", action="store_true", help="Sync tags_data.json")
    parser.add_argument("--foods", action="store_true", help="Sync food JSON data")
    parser.add_argument("--embeddings", action="store_true", help="Backfill missing food embeddings")
    parser.add_argument("--all", action="store_true", help="Sync tags, sync foods, and backfill embeddings")
    parser.add_argument("--embedding-limit", type=int, default=settings.embedding_backfill_limit or None)
    parser.add_argument("--embedding-sleep", type=float, default=settings.embedding_backfill_sleep_seconds)
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    no_specific_task = not (args.tags or args.foods or args.embeddings or args.all)
    asyncio.run(
        seed_data(
            sync_tags_enabled=args.all or args.tags or no_specific_task,
            sync_foods_enabled=args.all or args.foods or no_specific_task,
            run_embedding_enabled=args.all or args.embeddings,
            embedding_limit=args.embedding_limit,
            embedding_sleep_seconds=args.embedding_sleep,
        )
    )
