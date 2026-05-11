from pydantic import BaseModel
from typing import List, Optional
import uuid

class AIInsight(BaseModel):
    exclude: List[str]
    include: List[str]
    prefer: List[str]
    warning_message: Optional[str] = None

class Filters(BaseModel):
    hard: List[str]
    dietary: List[str]
    soft: List[str]

class FoodResult(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    img_url: Optional[str] = None # Bổ sung thêm theo ERD
    core_ingredients: List[str]   # Đổi tên từ ingredients
    soft_tags: List[str]          # Gộp chung các filter lại theo ERD
    matchScore: float             # Nên để kiểu float cho số điểm Vector thay vì str

class SearchResponse(BaseModel):
    query: str
    ai_insight: AIInsight
    results: List[FoodResult]
    ai_response: Optional[str] = None  # Lời tư vấn tự nhiên từ Post-processing Agent
