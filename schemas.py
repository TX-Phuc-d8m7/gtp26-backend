from pydantic import BaseModel
from pydantic import Field
from datetime import datetime
from typing import Any, Dict, List, Optional
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
    taste_profile: List[str] = Field(default_factory=list)
    meal_context: List[str] = Field(default_factory=list)
    occasion_context: List[str] = Field(default_factory=list)
    matchScore: float             # Nên để kiểu float cho số điểm Vector thay vì str
    reason: Optional[str] = None  # Giải thích ngắn vì sao món được gợi ý

class SearchResponse(BaseModel):
    query: str
    ai_insight: AIInsight
    results: List[FoodResult]
    disclaimer: str
    query_log_id: Optional[uuid.UUID] = None
    ai_response: Optional[str] = None  # Lời tư vấn tự nhiên từ Post-processing Agent


class QueryLogResult(BaseModel):
    id: uuid.UUID
    user_id: Optional[uuid.UUID] = None
    thread_id: Optional[uuid.UUID] = None
    query: str
    ai_insight: Dict[str, Any] = Field(default_factory=dict)
    final_exclude_ings: List[str] = Field(default_factory=list)
    exclude_ingredient_keys: List[str] = Field(default_factory=list)
    user_include_tags: List[str] = Field(default_factory=list)
    user_exclude_tags: List[str] = Field(default_factory=list)
    candidate_count: int
    filtered_count: int
    scored_count: int
    returned_count: int
    excluded_summary: Dict[str, Any] = Field(default_factory=dict)
    retrieval_notes: List[str] = Field(default_factory=list)
    top_results: List[Dict[str, Any]] = Field(default_factory=list)
    warning_message: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class QueryLogListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[QueryLogResult]


class IngredientAliasOverrideCreate(BaseModel):
    alias: str
    canonical_key: str
    group_keys: List[str] = Field(default_factory=list)
    enabled: bool = True
    notes: str = ""


class IngredientAliasOverrideUpdate(BaseModel):
    alias: Optional[str] = None
    canonical_key: Optional[str] = None
    group_keys: Optional[List[str]] = None
    enabled: Optional[bool] = None
    notes: Optional[str] = None


class IngredientAliasOverrideResult(BaseModel):
    id: uuid.UUID
    alias: str
    alias_key: str
    canonical_key: str
    group_keys: List[str] = Field(default_factory=list)
    enabled: bool
    notes: str = ""

    model_config = {"from_attributes": True}


class RebuildFoodKeysResponse(BaseModel):
    foods_count: int
    updated_count: int
