import json
import os
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models import Food
from database import AsyncSessionLocal
from google import genai

PROJECT_ID = os.getenv("PROJECT_ID")
client = genai.Client(vertexai=True, project=PROJECT_ID, location="us-central1")

async def seed_data():
    async with AsyncSessionLocal() as db:
        # Kiểm tra xem có dữ liệu chưa
        result = await db.execute(select(Food).limit(1))
        first_food = result.scalar_one_or_none()

        if first_food is None:
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
                    ingredients=item.get("ingredients", []),
                    description=item.get("description", ""),
                    category=item.get("category", "Món khác"),
                    hard_filters=item.get("hard_filters", []),
                    dietary_filters=item.get("dietary_filters", []),
                    soft_filters=item.get("soft_filters", []),
                    embedding=None
                )
                db.add(new_food)
            await db.commit()
            print(f"✅ Đã nạp xong {len(foods)} món ăn vào database.")
        else:
            print("✅ Dữ liệu thô đã tồn tại. Bỏ qua bước nạp file JSON.")

        # Tạo embeddings cho các món chưa có
        result = await db.execute(select(Food).where(Food.embedding.is_(None)))
        foods_to_vectorize = result.scalars().all()

        if not foods_to_vectorize:
            print("✨ Tất cả món ăn đã có Vector AI. Hệ thống sẵn sàng!")
            return

        print(f"🚀 Bắt đầu tạo Vector cho {len(foods_to_vectorize)} món...")

        for i, food in enumerate(foods_to_vectorize):
            try:
                text_to_embed = f"{', '.join(food.ingredients)}. {food.description}"
                
                embedding_response = client.models.embed_content(
                    model='text-embedding-004',
                    contents=text_to_embed
                )
                vector = embedding_response.embeddings[0].values
                
                food.embedding = vector
                await db.commit()
                
                print(f"[{i + 1}/{len(foods_to_vectorize)}] ✅ Vectorized: {food.name}")
                await asyncio.sleep(4.1) # Tránh rate limit

            except Exception as e:
                print(f"❌ Lỗi tại món {food.name}: {e}")
                await asyncio.sleep(10)
        
        print("Hoàn tất quá trình embedding.")
