import json
import os
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models import Food, Tag
from database import AsyncSessionLocal
from google import genai
from google.genai import types

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

        print("📂 Đang kiểm tra và đồng bộ dữ liệu từ foods_enriched.json...")
        file_path = 'foods_enriched.json'

        if not os.path.exists(file_path):
            print(f"❌ Không tìm thấy file {file_path}")
            return
        
        with open(file_path, "r", encoding="utf-8") as f:
            foods_data = json.load(f)
        
        existing_foods_result = await db.execute(select(Food))
        existing_foods = {food.name: food for food in existing_foods_result.scalars().all()}

        new_count = 0
        update_count = 0

        for item in foods_data:
            food_name = item.get("name")
            new_core_ingredients = item.get("core_ingredients", [])
            new_description = item.get("description", "")
            new_soft_tags = item.get("soft_tags", [])

            if food_name in existing_foods:
                food = existing_foods[food_name]
                
                # Text thay đổi nên cần tạo lại vector
                is_text_changed = (
                    food.core_ingredients != new_core_ingredients or
                    food.description != new_description or
                    food.soft_tags != new_soft_tags
                )
                
                if is_text_changed:
                    # Cập nhật mọi dữ liệu mới vào DB
                    food.core_ingredients = new_core_ingredients
                    food.description = new_description
                    food.soft_tags = new_soft_tags
                    
                    # CHỈ reset vector nếu nội dung text bị thay đổi
                    if is_text_changed:
                        food.embedding = None 
                        
                    update_count += 1
            else:
                new_food = Food(
                    name=food_name,
                    core_ingredients=new_core_ingredients,
                    description=new_description,
                    soft_tags=new_soft_tags,
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

                text_to_embed = (
                    f"Món ăn: {food.name}. "
                    f"Mô tả: {food.description} "
                    f"Nguyên liệu chính: {core_ingreds_str}. "
                    f"Tính chất: {soft_tags_str}."
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