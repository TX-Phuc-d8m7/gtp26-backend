"""SQLAlchemy metadata import hub."""

from app.db.session import Base
from app import models as _models  # noqa: F401

__all__ = ["Base"]

