"""Base contracts cho chat intent handlers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from app.modules.search.schemas import SearchResponse


@dataclass
class IntentHandlerResult:
    """Kết quả chuẩn mà mọi intent handler trả về cho dispatcher/service."""

    intent: str
    content: str
    query_log_id: uuid.UUID | None = None
    search_result: SearchResponse | None = None
    place_result: Any | None = None
    food_results: list[dict[str, Any]] | None = None
    structured_result: dict[str, Any] | None = None
