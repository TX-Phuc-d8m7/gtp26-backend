"""Compatibility re-export for SQLAlchemy models.

Model definitions live in their owning modules. Prefer importing from
`app.modules.<domain>.models` in new code.
"""

from app.modules.admin.alias_overrides.models import IngredientAliasOverride
from app.modules.chat.models import ChatMessage, ChatThread, FoodRecommendationFeedback
from app.modules.favorites.models import FavoriteFood
from app.modules.foods.models import Food, Tag
from app.modules.places.models import PlaceSearchCache
from app.modules.query_logs.models import QueryLog
from app.modules.users.models import User, UserHealthProfile

__all__ = [
    "ChatMessage",
    "ChatThread",
    "FavoriteFood",
    "FoodRecommendationFeedback",
    "Food",
    "IngredientAliasOverride",
    "PlaceSearchCache",
    "QueryLog",
    "Tag",
    "User",
    "UserHealthProfile",
]
