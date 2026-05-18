import uuid
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB
from pgvector.sqlalchemy import HALFVEC
from database import Base

class Food(Base):
    __tablename__ = "foods"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    img_url = Column(String, nullable=True)
    
    core_ingredients = Column(ARRAY(Text), nullable=False, default=[])
    raw_ingredients = Column(ARRAY(Text), nullable=False, default=[])
    raw_instructions = Column(Text, nullable=False, default="")
    core_ingredient_keys = Column(ARRAY(Text), nullable=False, default=[])
    soft_tags = Column(ARRAY(Text), nullable=False, default=[]) 
    taste_profile = Column(ARRAY(Text), nullable=False, default=[])
    meal_context = Column(ARRAY(Text), nullable=False, default=[])
    occasion_context = Column(ARRAY(Text), nullable=False, default=[])
    
    # gemini-embedding-001 need vector 3072 dimension
    embedding = Column(HALFVEC(3072), nullable=True)

class Tag(Base):
    __tablename__ = "tags"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False, unique=True) 
    tag_type = Column(String, nullable=False)         
    
    # Rule Engine
    exclude_soft_tag = Column(ARRAY(String), nullable=False, default=[])
    prefer_soft_tag = Column(ARRAY(String), nullable=False, default=[])
    exclude_ingredient = Column(ARRAY(String), nullable=False, default=[])
    prefer_ingredient = Column(ARRAY(String), nullable=False, default=[])


class IngredientAliasOverride(Base):
    __tablename__ = "ingredient_alias_overrides"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alias = Column(String, nullable=False)
    alias_key = Column(String, nullable=False, unique=True, index=True)
    canonical_key = Column(String, nullable=False)
    group_keys = Column(ARRAY(Text), nullable=False, default=[])
    enabled = Column(Boolean, nullable=False, default=True)
    notes = Column(Text, nullable=False, default="")


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
