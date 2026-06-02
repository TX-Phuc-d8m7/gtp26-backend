from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field


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
