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


class AdminFoodRecommendationFeedbackSummary(BaseModel):
    total: int = 0
    likes: int = 0
    neutrals: int = 0
    dislikes: int = 0
    average_rating: Optional[float] = None


class AdminDashboardStatsResponse(BaseModel):
    total_users: int
    active_users: int
    total_foods: int
    total_queries: int
    queries_today: int
    total_chat_threads: int
    total_chat_messages: int
    feedback: AdminFeedbackSummary
    food_recommendation_feedback: AdminFoodRecommendationFeedbackSummary
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


class AdminFoodRecommendationFeedbackItem(BaseModel):
    id: uuid.UUID
    thread_id: uuid.UUID
    assistant_message_id: uuid.UUID
    food_id: uuid.UUID
    food_name: Optional[str] = None
    verdict: str
    rating: Optional[int] = None
    reasons: List[str] = Field(default_factory=list)
    comment: Optional[str] = None
    tried: bool
    created_at: datetime
    updated_at: datetime
    user_id: Optional[uuid.UUID] = None
    user_email: Optional[str] = None
    thread_title: Optional[str] = None
    query: Optional[str] = None


class AdminFoodRecommendationFeedbackListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    summary: AdminFoodRecommendationFeedbackSummary
    top_disliked_foods: List[AdminTopItem] = Field(default_factory=list)
    top_reasons: List[AdminTopItem] = Field(default_factory=list)
    items: List[AdminFoodRecommendationFeedbackItem]
