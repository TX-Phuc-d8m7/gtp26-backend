"""Versioned API router.

The current public API keeps its existing paths without an `/api/v1` prefix to
avoid breaking the frontend while the internal source layout is refactored.
"""

from fastapi import APIRouter

from app.modules.admin.alias_overrides.router import router as admin_alias_overrides_router
from app.modules.admin.foods.router import router as admin_foods_router
from app.modules.admin.tags.router import router as admin_tags_router
from app.modules.admin.users.router import router as admin_users_router
from app.modules.auth.router import router as auth_router
from app.modules.chat.router import router as chat_router
from app.modules.favorites.router import router as favorites_router
from app.modules.foods.router import router as foods_router
from app.modules.query_logs.router import router as query_logs_router
from app.modules.search.router import router as search_router
from app.modules.users.router import router as users_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(users_router)
router.include_router(favorites_router)
router.include_router(admin_alias_overrides_router)
router.include_router(query_logs_router)
router.include_router(search_router)
router.include_router(foods_router)
router.include_router(chat_router)
router.include_router(admin_foods_router)
router.include_router(admin_tags_router)
router.include_router(admin_users_router)
