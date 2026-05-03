import uuid
from sqlalchemy import Column, String, Text, JSON
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB
from pgvector.sqlalchemy import HALFVEC
from database import Base

class Food(Base):
    __tablename__ = "foods"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    category = Column(String, nullable=True)
    ingredients = Column(ARRAY(Text), nullable=False)
    description = Column(Text, nullable=False)
    hard_filters = Column(JSONB, nullable=False)
    dietary_filters = Column(JSONB, nullable=False, default=[])
    soft_filters = Column(JSONB, nullable=False)
    
    # Sử dụng HALFVEC với 768 chiều để tương thích với text-embedding-004
    embedding = Column(HALFVEC(768), nullable=True)
