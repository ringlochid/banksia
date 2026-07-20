from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from autoclaw.interfaces.http.errors import raise_runtime_exception
from autoclaw.persistence.session import get_db_session
from autoclaw.runtime.contracts import (
    RuntimeFlowSummaryListResponse,
    RuntimeTaskListQuery,
)
from autoclaw.runtime.flow.service import list_runtime_flows

router = APIRouter(prefix="/runtime", tags=["runtime"])
type DBSession = Annotated[AsyncSession, Depends(get_db_session)]
type RuntimeTaskListParams = Annotated[RuntimeTaskListQuery, Query()]


@router.get("/tasks", response_model=RuntimeFlowSummaryListResponse)
async def get_runtime_tasks(
    session: DBSession,
    query: RuntimeTaskListParams,
) -> RuntimeFlowSummaryListResponse:
    try:
        return await list_runtime_flows(
            session,
            q=query.q,
            cursor=query.cursor,
            limit=query.limit,
            sort=query.sort,
            status=query.status,
        )
    except Exception as exc:  # pragma: no cover - thin HTTP wrapper
        raise_runtime_exception(exc)
