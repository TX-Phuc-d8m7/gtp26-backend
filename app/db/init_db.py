"""Database startup initialization.

This keeps the current MVP `CREATE/ALTER IF NOT EXISTS` behavior in one place.
When the project adopts Alembic, this module is the boundary to replace.
"""

from __future__ import annotations

from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine
from app.db.base import Base
from app.db.seed import seed_data


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("ALTER TABLE foods ADD COLUMN IF NOT EXISTS taste_profile TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[]"))
        await conn.execute(text("ALTER TABLE foods ADD COLUMN IF NOT EXISTS meal_context TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[]"))
        await conn.execute(text("ALTER TABLE foods ADD COLUMN IF NOT EXISTS occasion_context TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[]"))
        await conn.execute(text("ALTER TABLE foods ADD COLUMN IF NOT EXISTS raw_ingredients TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[]"))
        await conn.execute(text("ALTER TABLE foods ADD COLUMN IF NOT EXISTS raw_instructions TEXT NOT NULL DEFAULT ''"))
        await conn.execute(text("ALTER TABLE foods ADD COLUMN IF NOT EXISTS core_ingredient_keys TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[]"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_foods_core_ingredient_keys_gin ON foods USING GIN (core_ingredient_keys)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_foods_soft_tags_gin ON foods USING GIN (soft_tags)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_foods_taste_profile_gin ON foods USING GIN (taste_profile)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_foods_meal_context_gin ON foods USING GIN (meal_context)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_foods_occasion_context_gin ON foods USING GIN (occasion_context)"))
        await conn.execute(text("ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS thread_id UUID"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_query_logs_created_at ON query_logs (created_at)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_query_logs_user_id ON query_logs (user_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_query_logs_thread_id ON query_logs (thread_id)"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'user'"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name TEXT"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_email ON users (email)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_user_health_profiles_user_id ON user_health_profiles (user_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_favorite_foods_user_id ON favorite_foods (user_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_favorite_foods_food_id ON favorite_foods (food_id)"))
        await conn.execute(text("ALTER TABLE favorite_foods ADD COLUMN IF NOT EXISTS rating INTEGER"))
        await conn.execute(text("""
            DELETE FROM favorite_foods ff
            WHERE NOT EXISTS (
                SELECT 1 FROM users u WHERE u.id = ff.user_id
            )
            OR NOT EXISTS (
                SELECT 1 FROM foods f WHERE f.id = ff.food_id
            )
        """))
        await conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'fk_favorite_foods_user_id'
                ) THEN
                    ALTER TABLE favorite_foods
                    ADD CONSTRAINT fk_favorite_foods_user_id
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
                END IF;
            END $$;
        """))
        await conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'fk_favorite_foods_food_id'
                ) THEN
                    ALTER TABLE favorite_foods
                    ADD CONSTRAINT fk_favorite_foods_food_id
                    FOREIGN KEY (food_id) REFERENCES foods(id) ON DELETE CASCADE;
                END IF;
            END $$;
        """))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_chat_threads_user_id ON chat_threads (user_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_chat_threads_updated_at ON chat_threads (updated_at)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_chat_messages_thread_id ON chat_messages (thread_id)"))
        await conn.execute(text("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS feedback VARCHAR"))
        await conn.execute(text("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS structured_result JSONB"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_food_recommendation_feedbacks_user_id ON food_recommendation_feedbacks (user_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_food_recommendation_feedbacks_thread_id ON food_recommendation_feedbacks (thread_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_food_recommendation_feedbacks_assistant_message_id ON food_recommendation_feedbacks (assistant_message_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_food_recommendation_feedbacks_food_id ON food_recommendation_feedbacks (food_id)"))

    if settings.run_seed_on_startup:
        await seed_data(
            sync_tags_enabled=settings.sync_tags_on_startup,
            sync_foods_enabled=settings.sync_foods_on_startup,
            delete_stale_foods_enabled=settings.sync_foods_delete_stale_on_startup,
            run_embedding_enabled=settings.run_embedding_on_startup,
            embedding_limit=settings.embedding_backfill_limit or None,
            embedding_sleep_seconds=settings.embedding_backfill_sleep_seconds,
        )
    else:
        print("⏭️ Bỏ qua seed dữ liệu khi startup (RUN_SEED_ON_STARTUP=false).")
