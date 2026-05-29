from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field


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
    taste_profile: List[str] = Field(default_factory=list)
    meal_context: List[str] = Field(default_factory=list)
    occasion_context: List[str] = Field(default_factory=list)
    matchScore: float             # Nên để kiểu float cho số điểm Vector thay vì str
    reason: Optional[str] = None  # Giải thích ngắn vì sao món được gợi ý
    dining_context: Optional[str] = None  # "restaurant" | "home_cooked" | "both"


class SearchResponse(BaseModel):
    query: str
    ai_insight: AIInsight
    results: List[FoodResult]
    disclaimer: str
    query_log_id: Optional[uuid.UUID] = None
    retrieval_note: Optional[str] = None
    retrieval_trace: Optional[Dict[str, Any]] = None
    ai_response: Optional[str] = None  # Lời tư vấn tự nhiên từ Post-processing Agent
