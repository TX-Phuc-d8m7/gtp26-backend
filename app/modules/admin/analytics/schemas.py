from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AdminTopItem(BaseModel):
    name: str
    count: int


class AdminFeedbackSummary(BaseModel):
    total: int
    likes: int
    dislikes: int


class AdminDashboardStatsResponse(BaseModel):
    total_users: int
    active_users: int
    total_foods: int
    total_queries: int
    queries_today: int
    total_chat_threads: int
    total_chat_messages: int
    feedback: AdminFeedbackSummary
    top_health_conditions: List[AdminTopItem] = Field(default_factory=list)
    top_recommended_foods: List[AdminTopItem] = Field(default_factory=list)


class AdminAIFeedbackItem(BaseModel):
    message_id: uuid.UUID
    thread_id: uuid.UUID
    query_log_id: Optional[uuid.UUID] = None
    feedback: str
    assistant_content: str
    food_results: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    user_id: Optional[uuid.UUID] = None
    user_email: Optional[str] = None
    thread_title: Optional[str] = None
    query: Optional[str] = None


class AdminAIFeedbackListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[AdminAIFeedbackItem]
