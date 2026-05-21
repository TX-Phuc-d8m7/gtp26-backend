from __future__ import annotations

import uuid

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from app.db.session import Base


class IngredientAliasOverride(Base):
    __tablename__ = "ingredient_alias_overrides"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alias = Column(String, nullable=False)
    alias_key = Column(String, nullable=False, unique=True, index=True)
    canonical_key = Column(String, nullable=False)
    group_keys = Column(ARRAY(Text), nullable=False, default=[])
    enabled = Column(Boolean, nullable=False, default=True)
    notes = Column(Text, nullable=False, default="")
