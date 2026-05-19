"""Embedding service — sinh và rebuild vector embedding cho món ăn."""

from __future__ import annotations

import asyncio
import os
import time
from typing import List, Optional

from google import genai
from google.genai import types
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Food

# ---------------------------------------------------------------------------
# Client (dùng chung với food_service)
# ---------------------------------------------------------------------------

PROJECT_ID = os.getenv("PROJECT_ID")
client = genai.Client(vertexai=True, project=PROJECT_ID, location="us-central1")

EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 3072
EMBEDDING_TIMEOUT = 15  # seconds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_food_embed_text(food: Food) -> str:
    """
    Xây dựng văn bản đại diện cho món ăn để embedding.
    Phải đồng bộ với cách seed_service.py tạo embedding khi seed dữ liệu.
    """
    core_ingreds_str = ", ".join(food.core_ingredients) if food.core_ingredients else "Không có"
    soft_tags_str    = ", ".join(food.soft_tags)        if food.soft_tags        else "Không có"
    taste_str        = ", ".join(food.taste_profile)    if food.taste_profile    else "Không có"
    meal_str         = ", ".join(food.meal_context)     if food.meal_context     else "Không có"
    occasion_str     = ", ".join(food.occasion_context) if food.occasion_context else "Không có"

    return (
        f"Món ăn: {food.name}. "
        f"Mô tả: {food.description} "
        f"Nguyên liệu chính: {core_ingreds_str}. "
        f"Tính chất: {soft_tags_str}. "
        f"Hồ sơ vị: {taste_str}. "
        f"Bữa ăn phù hợp: {meal_str}. "
        f"Ngữ cảnh sử dụng: {occasion_str}."
    )


async def generate_embedding_for_text(text: str) -> Optional[List[float]]:
    """
    Gọi Gemini embedding API cho một đoạn văn bản.
    Trả None nếu lỗi hoặc timeout.
    """
    def _call():
        return client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=text,
            config=types.EmbedContentConfig(
                output_dimensionality=EMBEDDING_DIM,
                task_type="RETRIEVAL_DOCUMENT",
            ),
        )

    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(_call),
            timeout=EMBEDDING_TIMEOUT,
        )
        return list(response.embeddings[0].values)
    except asyncio.TimeoutError:
        print(f"[EMBEDDING] Timeout sau {EMBEDDING_TIMEOUT}s")
        return None
    except Exception as e:
        print(f"[EMBEDDING] Lỗi: {e}")
        return None


# ---------------------------------------------------------------------------
# Public API — dùng cho admin food endpoints
# ---------------------------------------------------------------------------

async def rebuild_single_food_embedding(food: Food, db: AsyncSession) -> bool:
    """
    Sinh lại embedding cho 1 món ăn và lưu vào DB.
    Trả True nếu thành công.
    """
    text = build_food_embed_text(food)
    vector = await generate_embedding_for_text(text)
    if vector is None:
        return False

    food.embedding = vector
    await db.commit()
    return True


async def rebuild_all_embeddings(db: AsyncSession) -> dict:
    """
    Sinh lại embedding cho tất cả món ăn.
    Dùng cho endpoint batch rebuild của admin.

    Returns:
        {"total": int, "success": int, "failed": int, "failed_names": List[str]}
    """
    foods = (await db.execute(select(Food))).scalars().all()

    total   = len(foods)
    success = 0
    failed  = 0
    failed_names: List[str] = []

    for food in foods:
        text   = build_food_embed_text(food)
        vector = await generate_embedding_for_text(text)

        if vector is not None:
            food.embedding = vector
            await db.commit()
            success += 1
            print(f"  ✅ {food.name}")
        else:
            failed += 1
            failed_names.append(food.name)
            print(f"  ❌ {food.name} — embedding thất bại")

        # Nghỉ nhỏ tránh rate limit
        await asyncio.sleep(0.3)

    return {
        "total": total,
        "success": success,
        "failed": failed,
        "failed_names": failed_names,
    }
