import json
import os
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models import Food, Tag
from database import AsyncSessionLocal
from google import genai
from google.genai import types
from services.ingredient_key_service import (
    generate_core_ingredient_keys,
    load_enabled_alias_override_rules,
)

PROJECT_ID = os.getenv("PROJECT_ID")
client = genai.Client(vertexai=True, project=PROJECT_ID, location="us-central1")

async def seed_data():
    async with AsyncSessionLocal() as db:
        # ==========================================
        # 1. NẠP VÀ CẬP NHẬT DỮ LIỆU LUẬT Y TẾ (TAGS)
        # ==========================================
        print("🏥 Đang kiểm tra và đồng bộ dữ liệu từ tags_data.json...")
        tags_file_path = "standard-data/tags_data.json"

        if not os.path.exists(tags_file_path):
            print(f"⚠️ Không tìm thấy file {tags_file_path}")
        else:
            with open(tags_file_path, "r", encoding="utf-8") as f:
                tags_data = json.load(f)

            # Lấy toàn bộ Tags hiện có trong DB để đối chiếu (Key là tên tag)
            existing_tags_result = await db.execute(select(Tag))
            existing_tags = {tag.name: tag for tag in existing_tags_result.scalars().all()}

            tags_new_count = 0
            tags_update_count = 0

            for item in tags_data:
                tag_name = item.get("name")
                new_tag_type = item.get("tag_type")
                new_exclude_soft = item.get("exclude_soft_tag", [])
                new_prefer_soft = item.get("prefer_soft_tag", [])
                new_exclude_ing = item.get("exclude_ingredient", [])
                new_prefer_ing = item.get("prefer_ingredient", [])

                if tag_name in existing_tags:
                    tag = existing_tags[tag_name]
                    
                    # Kiểm tra xem có luật nào bị thay đổi so với DB không
                    is_tag_changed = (
                        tag.tag_type != new_tag_type or
                        tag.exclude_soft_tag != new_exclude_soft or
                        tag.prefer_soft_tag != new_prefer_soft or
                        tag.exclude_ingredient != new_exclude_ing or
                        tag.prefer_ingredient != new_prefer_ing
                    )

                    if is_tag_changed:
                        # Cập nhật luật mới
                        tag.tag_type = new_tag_type
                        tag.exclude_soft_tag = new_exclude_soft
                        tag.prefer_soft_tag = new_prefer_soft
                        tag.exclude_ingredient = new_exclude_ing
                        tag.prefer_ingredient = new_prefer_ing
                        tags_update_count += 1
                else:
                    # Thêm mới nếu luật y tế này chưa tồn tại
                    new_tag = Tag(
                        name=tag_name,
                        tag_type=new_tag_type,
                        exclude_soft_tag=new_exclude_soft,
                        prefer_soft_tag=new_prefer_soft,
                        exclude_ingredient=new_exclude_ing,
                        prefer_ingredient=new_prefer_ing
                    )
                    db.add(new_tag)
                    tags_new_count += 1

            await db.commit()
            print(f"✅ Hoàn tất đồng bộ Tags: Thêm mới {tags_new_count} quy tắc, Cập nhật {tags_update_count} quy tắc.")

        # ==========================================
        # 2. NẠP DỮ LIỆU MÓN ĂN (FOOD) VÀ EMBEDDING
        # ==========================================

        print("📂 Đang kiểm tra và đồng bộ dữ liệu món ăn đã phân category...")
        BASE_DIR = os.path.dirname(os.path.dirname(__file__))
        categorized_file_path = os.path.join(
            BASE_DIR, 
            "standard-data", 
            "ingredients-data", 
            "food-clean-categorized",
            "raw_foods_enriched_labeled(final_488).categorized.clean.json"
        )
        legacy_categorized_file_path = os.path.join(
            BASE_DIR,
            "standard-data",
            "ingredients-data",
            "raw_foods_enriched_labeled(final_488).categorized.clean.json"
        )
        fallback_file_path = os.path.join(
            BASE_DIR,
            "standard-data",
            "ingredients-data",
            "food-clean-categorized",
            "raw_foods_enriched_labeled(final_488).categorized.clean.json"
        )
        if os.path.exists(categorized_file_path):
            file_path = categorized_file_path
        elif os.path.exists(legacy_categorized_file_path):
            file_path = legacy_categorized_file_path
        else:
            file_path = fallback_file_path

        if not os.path.exists(file_path):
            print(f"❌ Không tìm thấy file {file_path}")
            return
        print(f"📄 Food seed source: {file_path}")
        
        with open(file_path, "r", encoding="utf-8") as f:
            foods_data = json.load(f)
        
        existing_foods_result = await db.execute(select(Food))
        existing_foods = {food.name: food for food in existing_foods_result.scalars().all()}
        alias_override_rules = await load_enabled_alias_override_rules(db)

        new_count = 0
        update_count = 0

        for item in foods_data:
            food_name = item.get("name")
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
                
                # Các field dùng trong embedding thay đổi thì cần tạo lại vector.
                is_embedding_text_changed = (
                    food.core_ingredients != new_core_ingredients or
                    food.description != new_description or
                    food.soft_tags != new_soft_tags or
                    food.taste_profile != new_taste_profile or
                    food.meal_context != new_meal_context or
                    food.occasion_context != new_occasion_context
                )

                # Raw fields chỉ lưu trữ/truy vết, không đưa vào embedding để tránh nhiễu.
                is_storage_changed = (
                    is_embedding_text_changed or
                    food.raw_ingredients != new_raw_ingredients or
                    food.raw_instructions != new_raw_instructions or
                    food.core_ingredient_keys != new_core_ingredient_keys
                )
                
                if is_storage_changed:
                    # Cập nhật mọi dữ liệu mới vào DB
                    food.core_ingredients = new_core_ingredients
                    food.raw_ingredients = new_raw_ingredients
                    food.raw_instructions = new_raw_instructions
                    food.core_ingredient_keys = new_core_ingredient_keys
                    food.description = new_description
                    food.soft_tags = new_soft_tags
                    food.taste_profile = new_taste_profile
                    food.meal_context = new_meal_context
                    food.occasion_context = new_occasion_context
                    
                    # CHỈ reset vector nếu nội dung dùng để embedding bị thay đổi.
                    if is_embedding_text_changed:
                        food.embedding = None 
                        
                    update_count += 1
            else:
                new_food = Food(
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
                    embedding=None
                )
                db.add(new_food)
                new_count += 1

        await db.commit()
        print(f"✅ Hoàn tất đồng bộ: Thêm mới {new_count} món, Cập nhật {update_count} món.")

        # 2. Check and create embedding vector
        result = await db.execute(select(Food).where(Food.embedding.is_(None)))
        foods_to_vectorize = result.scalars().all()

        if not foods_to_vectorize:
            print("✨ Tất cả món ăn đã có Vector AI. Hệ thống sẵn sàng!")
            return

        print(f"🚀 Bắt đầu tạo Vector cho {len(foods_to_vectorize)} món...")

        for i, food in enumerate(foods_to_vectorize):
            try:
                # Check None/Null except join list error
                core_ingreds_str = ", ".join(food.core_ingredients) if food.core_ingredients else "Không có"
                soft_tags_str = ", ".join(food.soft_tags) if food.soft_tags else "Không có"
                taste_profile_str = ", ".join(food.taste_profile) if food.taste_profile else "Không có"
                meal_context_str = ", ".join(food.meal_context) if food.meal_context else "Không có"
                occasion_context_str = ", ".join(food.occasion_context) if food.occasion_context else "Không có"

                text_to_embed = (
                    f"Món ăn: {food.name}. "
                    f"Mô tả: {food.description} "
                    f"Nguyên liệu chính: {core_ingreds_str}. "
                    f"Tính chất: {soft_tags_str}. "
                    f"Hồ sơ vị: {taste_profile_str}. "
                    f"Bữa ăn phù hợp: {meal_context_str}. "
                    f"Ngữ cảnh sử dụng: {occasion_context_str}."
                )

                # Chạy gọi API đồng bộ trong thread để không block Event Loop của Asyncio
                def get_embedding():
                    return client.models.embed_content(
                        model='gemini-embedding-001', 
                        contents=text_to_embed,
                        config=types.EmbedContentConfig(
                            output_dimensionality=3072,
                            task_type="RETRIEVAL_DOCUMENT"  # Đây là document (món ăn), không phải query
                        )
                    )
                
                embedding_response = await asyncio.to_thread(get_embedding)
                vector = embedding_response.embeddings[0].values
                
                food.embedding = vector
                await db.commit()
                
                print(f"[{i + 1}/{len(foods_to_vectorize)}] ✅ Vectorized: {food.name}")
                await asyncio.sleep(3) # Tránh rate limit

            except Exception as e:
                print(f"❌ Lỗi tại món {food.name}: {e}")
                await asyncio.sleep(10)
        
        print("Hoàn tất quá trình embedding.")

if __name__ == "__main__":
    asyncio.run(seed_data())
