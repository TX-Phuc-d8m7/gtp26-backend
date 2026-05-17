import uuid
from sqlalchemy import Column, String, Text
from sqlalchemy.dialects.postgresql import UUID, ARRAY
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
