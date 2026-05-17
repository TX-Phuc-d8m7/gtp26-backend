from pydantic import BaseModel
from pydantic import Field
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
    taste_profile: List[str] = Field(default_factory=list)
    meal_context: List[str] = Field(default_factory=list)
    occasion_context: List[str] = Field(default_factory=list)
    matchScore: float             # Nên để kiểu float cho số điểm Vector thay vì str
    reason: Optional[str] = None  # Giải thích ngắn vì sao món được gợi ý

class SearchResponse(BaseModel):
    query: str
    ai_insight: AIInsight
    results: List[FoodResult]
    ai_response: Optional[str] = None  # Lời tư vấn tự nhiên từ Post-processing Agent


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
