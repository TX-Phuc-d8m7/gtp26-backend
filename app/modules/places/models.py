from __future__ import annotations

import uuid

from sqlalchemy import Column, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.db.session import Base


class PlaceSearchCache(Base):
    __tablename__ = "place_search_cache"
    __table_args__ = (
        UniqueConstraint(
            "dish_key",
            "lat_bucket",
            "lng_bucket",
            "location_text",
            "radius_m",
            "place_id",
            name="uq_place_search_cache_scope_place",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dish_key = Column(String, nullable=False, index=True)
    lat_bucket = Column(Float, nullable=True, index=True)
    lng_bucket = Column(Float, nullable=True, index=True)
    location_text = Column(String, nullable=False, default="", index=True)
    radius_m = Column(Integer, nullable=False, default=3000)
    place_id = Column(String, nullable=False, index=True)
    rank = Column(Integer, nullable=False, default=0)
    search_query = Column(String, nullable=False)
    fetched_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
