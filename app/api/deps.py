"""Shared FastAPI dependencies."""

from app.db.session import get_db
from app.modules.auth.service import get_current_admin_user, get_current_user, get_current_user_optional

__all__ = ["get_db", "get_current_admin_user", "get_current_user", "get_current_user_optional"]

