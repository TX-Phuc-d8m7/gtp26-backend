from pydantic import BaseModel
from typing import List, Optional
import uuid

class AIInsight(BaseModel):
    exclude: List[str]
    include: List[str]
    prefer: List[str]

class Filters(BaseModel):
    hard: List[str]
    dietary: List[str]
    soft: List[str]

class FoodResult(BaseModel):
    id: uuid.UUID
    name: str
    category: Optional[str]
    description: str
    ingredients: List[str]
    filters: Filters
    matchScore: str

class SearchResponse(BaseModel):
    query: str
    ai_insight: AIInsight
    results: List[FoodResult]
