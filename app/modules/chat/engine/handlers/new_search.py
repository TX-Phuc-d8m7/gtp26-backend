from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.chat.engine.handlers.base import IntentHandlerResult
from app.modules.chat.engine.response_factory import (
    build_search_message_content,
    build_structured_result,
    serialize_food_results,
)
from app.modules.search.service import search_food
from app.modules.users.models import UserHealthProfile


async def handle_new_search(
    *,
    raw_query: str,
    query_with_context: str,
    db: AsyncSession,
    profile: UserHealthProfile | None,
    thread_id: uuid.UUID | None,
) -> IntentHandlerResult:
    search_result = await search_food(
        query_with_context,
        db,
        profile=profile,
        thread_id=thread_id,
    )
    serialized = serialize_food_results(search_result)
    content = build_search_message_content(search_result)
    return IntentHandlerResult(
        intent="new_search",
        content=content,
        query_log_id=search_result.query_log_id,
        search_result=search_result,
        food_results=serialized,
        structured_result=build_structured_result(
            "food_search",
            {
                "query": raw_query,
                "food_results": serialized or [],
                "query_log_id": str(search_result.query_log_id) if search_result.query_log_id else None,
                "ai_insight": search_result.ai_insight.model_dump(),
            },
        ),
    )
