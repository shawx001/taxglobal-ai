"""Admin routes for compliance audit log review."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from backend.database import get_session, is_pg_available
from backend.errors import error_response
from backend.models import AuditLog

try:
    from sqlalchemy import Select, select
    from sqlalchemy.ext.asyncio import AsyncSession
except ModuleNotFoundError:
    Select = Any  # type: ignore[misc, assignment]
    select = None  # type: ignore[assignment]
    AsyncSession = Any  # type: ignore[misc, assignment]

router = APIRouter(prefix="/api/admin", tags=["admin"])


async def audit_session() -> AsyncGenerator[AsyncSession | None, None]:
    if not is_pg_available():
        yield None
        return
    try:
        async for session in get_session():
            yield session
    except RuntimeError:
        yield None


@router.get("/audit", response_model=None)
async def list_audit_records(
    request: Request,
    user_id: str | None = None,
    action: str | None = None,
    from_date: str | None = Query(default=None, alias="from"),
    to_date: str | None = Query(default=None, alias="to"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession | None = Depends(audit_session),
) -> dict[str, Any] | JSONResponse:
    """Return sanitized audit records for internal compliance review."""

    request_id = str(getattr(request.state, "request_id", "unknown"))
    parsed_user_id = _parse_user_id(user_id)
    if user_id and parsed_user_id is None:
        return _invalid_filter(request_id, "user_id must be a valid UUID.")

    parsed_from = _parse_date(from_date)
    parsed_to = _parse_date(to_date)
    if from_date and parsed_from is None:
        return _invalid_date(request_id, "from must be an ISO-8601 datetime.")
    if to_date and parsed_to is None:
        return _invalid_date(request_id, "to must be an ISO-8601 datetime.")

    if session is None or select is None:
        return _postgres_unavailable(request_id)

    statement = _build_query(
        user_id=parsed_user_id,
        action=action,
        from_date=parsed_from,
        to_date=parsed_to,
        limit=limit,
        offset=offset,
    )
    result = await session.execute(statement)
    records = result.scalars().all()
    return {"records": [_serialize_record(record) for record in records], "count": len(records)}


def _build_query(
    *,
    user_id: uuid.UUID | None,
    action: str | None,
    from_date: datetime | None,
    to_date: datetime | None,
    limit: int,
    offset: int,
) -> Select[Any]:
    statement = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    if user_id is not None:
        statement = statement.where(AuditLog.user_id == user_id)
    if action:
        statement = statement.where(AuditLog.action.startswith(action))
    if from_date is not None:
        statement = statement.where(AuditLog.created_at >= from_date)
    if to_date is not None:
        statement = statement.where(AuditLog.created_at <= to_date)
    return statement


def _serialize_record(record: Any) -> dict[str, Any]:
    created_at = getattr(record, "created_at", None)
    return {
        "id": getattr(record, "id", None),
        "request_id": str(getattr(record, "request_id", "")),
        "user_id": str(getattr(record, "user_id")) if getattr(record, "user_id", None) is not None else None,
        "action": getattr(record, "action", ""),
        "request_payload": getattr(record, "request_payload", None),
        "response_payload": getattr(record, "response_payload", None),
        "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else None,
    }


def _parse_user_id(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _postgres_unavailable(request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        headers={"X-Request-ID": request_id},
        content=error_response(
            code="postgres_unavailable",
            message="PostgreSQL is unavailable; audit records cannot be queried.",
            request_id=request_id,
        ),
    )


def _invalid_filter(request_id: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        headers={"X-Request-ID": request_id},
        content=error_response(code="invalid_filter", message=message, request_id=request_id),
    )


def _invalid_date(request_id: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        headers={"X-Request-ID": request_id},
        content=error_response(code="invalid_date_filter", message=message, request_id=request_id),
    )
