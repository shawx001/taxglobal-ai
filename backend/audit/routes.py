"""Admin routes for compliance audit log review."""

from __future__ import annotations

import hmac
import os
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse

from backend.audit.logger import GENESIS_HASH, _compute_entry_hash
from backend.audit.sanitizer import sanitize_payload
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
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    session: AsyncSession | None = Depends(audit_session),
) -> dict[str, Any] | JSONResponse:
    """Return sanitized audit records for internal compliance review."""

    request_id = str(getattr(request.state, "request_id", "unknown"))
    auth_error = _authorize_admin(request_id, x_admin_token)
    if auth_error is not None:
        return auth_error

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


@router.get("/audit/verify", response_model=None)
async def verify_audit_chain(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    session: AsyncSession | None = Depends(audit_session),
) -> dict[str, Any] | JSONResponse:
    """Verify the integrity of recent audit log hash-chain records."""

    request_id = str(getattr(request.state, "request_id", "unknown"))
    auth_error = _authorize_admin(request_id, x_admin_token)
    if auth_error is not None:
        return auth_error
    if session is None or select is None:
        return _postgres_unavailable(request_id)

    result = await session.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit))
    records = list(result.scalars().all())
    records.reverse()
    return _verify_records(records)


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
    # Defense-in-depth: re-sanitize on read in case historical records
    # were written before a sanitizer fix (e.g. undashed SSN gap).
    return {
        "id": getattr(record, "id", None),
        "request_id": str(getattr(record, "request_id", "")),
        "user_id": str(getattr(record, "user_id")) if getattr(record, "user_id", None) is not None else None,
        "action": getattr(record, "action", ""),
        "request_payload": sanitize_payload(getattr(record, "request_payload", None)),
        "response_payload": sanitize_payload(getattr(record, "response_payload", None)),
        "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else None,
    }


def _verify_records(records: list[Any]) -> dict[str, Any]:
    previous_entry_hash: str | None = None
    verified = 0
    skipped_legacy = 0
    for record in records:
        record_id = getattr(record, "id", None)
        entry_hash = getattr(record, "entry_hash", None)

        # Legacy rows written before the hash-chain migration have NULL
        # entry_hash.  These are unverifiable — skip them rather than
        # reporting a false "tampered" result.
        if entry_hash is None:
            skipped_legacy += 1
            previous_entry_hash = None  # reset chain — next hashed row starts fresh
            continue

        prev_hash = getattr(record, "prev_hash", None) or GENESIS_HASH
        if previous_entry_hash is not None and prev_hash != previous_entry_hash:
            return {"status": "tampered", "verified": verified, "broken_at": record_id}
        expected_hash = _compute_entry_hash(
            request_id=str(getattr(record, "request_id", "")),
            action=getattr(record, "action", ""),
            request_payload=getattr(record, "request_payload", None),
            response_payload=getattr(record, "response_payload", None),
            prev_hash=prev_hash,
        )
        if entry_hash != expected_hash:
            return {"status": "tampered", "verified": verified, "broken_at": record_id}
        previous_entry_hash = entry_hash
        verified += 1
    return {"status": "ok", "verified": verified, "skipped_legacy": skipped_legacy, "broken_at": None}


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
        normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _authorize_admin(request_id: str, provided_token: str | None) -> JSONResponse | None:
    expected_token = os.environ.get("TAXGLOBAL_ADMIN_AUDIT_TOKEN")
    if not expected_token:
        return JSONResponse(
            status_code=503,
            headers={"X-Request-ID": request_id},
            content=error_response(
                code="admin_audit_auth_not_configured",
                message="Admin audit access is not configured.",
                request_id=request_id,
            ),
        )
    if provided_token is None or not hmac.compare_digest(provided_token, expected_token):
        return JSONResponse(
            status_code=403,
            headers={"X-Request-ID": request_id},
            content=error_response(
                code="admin_forbidden",
                message="Admin audit access denied.",
                request_id=request_id,
            ),
        )
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
