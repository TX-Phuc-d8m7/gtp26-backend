"""Admin APIs for food search query logs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.query_logs.models import QueryLog
from app.modules.users.models import User
from app.modules.query_logs.schemas import QueryLogListResponse, QueryLogResult
from app.modules.auth.service import get_current_admin_user

router = APIRouter(prefix="/admin/query-logs", tags=["Admin Query Logs"])


def _apply_query_log_filters(
    stmt,
    *,
    q: Optional[str],
    user_id: Optional[uuid.UUID],
    thread_id: Optional[uuid.UUID],
    from_date: Optional[datetime],
    to_date: Optional[datetime],
):
    """Apply shared filters for query log list/count queries."""
    if q:
        stmt = stmt.where(QueryLog.query.ilike(f"%{q}%"))
    if user_id:
        stmt = stmt.where(QueryLog.user_id == user_id)
    if thread_id:
        stmt = stmt.where(QueryLog.thread_id == thread_id)
    if from_date:
        stmt = stmt.where(QueryLog.created_at >= from_date)
    if to_date:
        stmt = stmt.where(QueryLog.created_at <= to_date)
    return stmt


@router.get("", response_model=QueryLogListResponse)
async def list_query_logs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    q: Optional[str] = Query(default=None),
    user_id: Optional[uuid.UUID] = Query(default=None),
    thread_id: Optional[uuid.UUID] = Query(default=None),
    from_date: Optional[datetime] = Query(default=None),
    to_date: Optional[datetime] = Query(default=None),
    _: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """List food search logs for admin debugging."""
    count_stmt = _apply_query_log_filters(
        select(func.count()).select_from(QueryLog),
        q=q,
        user_id=user_id,
        thread_id=thread_id,
        from_date=from_date,
        to_date=to_date,
    )
    total = (await db.execute(count_stmt)).scalar_one()

    list_stmt = _apply_query_log_filters(
        select(QueryLog),
        q=q,
        user_id=user_id,
        thread_id=thread_id,
        from_date=from_date,
        to_date=to_date,
    ).order_by(QueryLog.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(list_stmt)
    return QueryLogListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=result.scalars().all(),
    )


@router.get("/{log_id}", response_model=QueryLogResult)
async def get_query_log(
    log_id: uuid.UUID,
    _: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Return one query log by id."""
    log = await db.get(QueryLog, log_id)
    if not log:
        raise HTTPException(status_code=404, detail="Không tìm thấy query log.")
    return log


@router.delete("/{log_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_query_log(
    log_id: uuid.UUID,
    _: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete one query log by id."""
    log = await db.get(QueryLog, log_id)
    if not log:
        raise HTTPException(status_code=404, detail="Không tìm thấy query log.")

    await db.delete(log)
    await db.commit()
