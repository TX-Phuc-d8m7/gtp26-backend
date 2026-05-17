from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import engine, Base, get_db
from schemas import SearchResponse
from services.food_service import search_food
from services.seed_service import seed_data
from routers.admin_alias_overrides import router as admin_alias_overrides_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Khởi tạo DB schemas nếu chưa có
    async with engine.begin() as conn:
        # Cài đặt extension vector nếu chưa có
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("ALTER TABLE foods ADD COLUMN IF NOT EXISTS taste_profile TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[]"))
        await conn.execute(text("ALTER TABLE foods ADD COLUMN IF NOT EXISTS meal_context TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[]"))
        await conn.execute(text("ALTER TABLE foods ADD COLUMN IF NOT EXISTS occasion_context TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[]"))
        await conn.execute(text("ALTER TABLE foods ADD COLUMN IF NOT EXISTS raw_ingredients TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[]"))
        await conn.execute(text("ALTER TABLE foods ADD COLUMN IF NOT EXISTS raw_instructions TEXT NOT NULL DEFAULT ''"))
        await conn.execute(text("ALTER TABLE foods ADD COLUMN IF NOT EXISTS core_ingredient_keys TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[]"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_foods_core_ingredient_keys_gin ON foods USING GIN (core_ingredient_keys)"))
    
    # Chạy data seeder
    await seed_data()
    yield
    # Cleanup khi tắt server
    await engine.dispose()

app = FastAPI(lifespan=lifespan, title="Food AI API")
app.include_router(admin_alias_overrides_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/foods/search", response_model=SearchResponse)
async def search_endpoint(q: str = Query(None), db: AsyncSession = Depends(get_db)):
    if not q:
        raise HTTPException(status_code=400, detail="Vui lòng nhập câu hỏi tìm kiếm.")
    return await search_food(q, db)
