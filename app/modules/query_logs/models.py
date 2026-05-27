from __future__ import annotations

import uuid

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from app.db.session import Base


class QueryLog(Base):
    __tablename__ = "query_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    thread_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    query = Column(Text, nullable=False)
    ai_insight = Column(JSONB, nullable=False, default=dict)
    final_exclude_ings = Column(ARRAY(Text), nullable=False, default=[])
    exclude_ingredient_keys = Column(ARRAY(Text), nullable=False, default=[])
    user_include_tags = Column(ARRAY(Text), nullable=False, default=[])
    user_exclude_tags = Column(ARRAY(Text), nullable=False, default=[])
    candidate_count = Column(Integer, nullable=False, default=0)
    filtered_count = Column(Integer, nullable=False, default=0)
    scored_count = Column(Integer, nullable=False, default=0)
    returned_count = Column(Integer, nullable=False, default=0)
    excluded_summary = Column(JSONB, nullable=False, default=dict)
    retrieval_notes = Column(ARRAY(Text), nullable=False, default=[])
    top_results = Column(JSONB, nullable=False, default=list)
    warning_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
