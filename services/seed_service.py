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
        # 1. NẠP DỮ LIỆU LUẬT Y TẾ (TAGS)
        # ==========================================
        result_tag = await db.execute(select(Tag).limit(1))
        if result_tag.scalar_one_or_none() is None:
            print("🏥 Bảng Tags trống. Đang nạp luật y tế...")
            if os.path.exists("tags_data.json"):
                with open("tags_data.json", "r", encoding="utf-8") as f:
                    tags_data = json.load(f)
                
                for item in tags_data:
                    new_tag = Tag(
                        name=item.get("name"),
                        tag_type=item.get("tag_type"),
                        exclude_soft_tag=item.get("exclude_soft_tag", []),
                        prefer_soft_tag=item.get("prefer_soft_tag", []),
                        exclude_ingredient=item.get("exclude_ingredient", []),
                        prefer_ingredient=item.get("prefer_ingredient", [])
                    )
                    db.add(new_tag)
                await db.commit()
                print(f"✅ Đã nạp xong {len(tags_data)} quy tắc y khoa!")
            else:
                print("⚠️ Không tìm thấy file tags_data.json")
        else:
            print("✅ Dữ liệu Tags đã tồn tại.")

        # ==========================================
        # 2. NẠP DỮ LIỆU MÓN ĂN (FOOD) VÀ EMBEDDING
        # ==========================================

        # 1. Check and import raw data
        result = await db.execute(select(Food).limit(1))
        first_food = result.scalar_one_or_none()

        if first_food is None:
            # 1.1 Get foods_enriched.json from backend-food-preparing/label-data
            print("📂 Database trống. Đang nạp dữ liệu từ foods_enriched.json...")
            file_path = "foods_enriched.json"
            if not os.path.exists(file_path):
                print(f"❌ Không tìm thấy file {file_path}")
                return

            with open(file_path, "r", encoding="utf-8") as f:
                foods = json.load(f)

            for item in foods:
                new_food = Food(
                    name=item.get("name"),
                    core_ingredients=item.get("core_ingredients", []),
                    description=item.get("description", ""),
                    soft_tags=item.get("soft_tags", []),

                    # preprocessing_ingredients=item.get("preprocessing_ingredients", []),
                    # raw_ingredients=item.get("raw_ingredients", []),
                    # raw_instructions=item.get("raw_instructions", ""),
                    embedding=None
                )
                db.add(new_food)
            await db.commit()
            print(f"✅ Đã nạp xong {len(foods)} món ăn vào database.")
        else:
            print("✅ Dữ liệu thô đã tồn tại. Bỏ qua bước nạp file JSON.")

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
                        config=types.EmbedContentConfig(output_dimensionality=3072)
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