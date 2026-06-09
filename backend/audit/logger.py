"""Async audit log writer."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from backend.audit.sanitizer import sanitize_payload
from backend.database import is_pg_available

logger = logging.getLogger("taxglobal.audit")


async def log_action(
    *,
    request_id: str,
    user_id: str | None,
    action: str,
    request_payload: dict[str, Any] | None,
    response_payload: dict[str, Any] | None,
) -> None:
    """Write a sanitized audit record to PostgreSQL, never raising to callers."""

    if not is_pg_available():
        return

    try:
        await _write_record(
            request_id=request_id,
            user_id=user_id,
            action=action,
            request_payload=sanitize_payload(request_payload),
            response_payload=sanitize_payload(response_payload),
        )
    except Exception:
        logger.warning("Audit log write failed for request_id=%s", request_id)


async def _write_record(
    *,
    request_id: str,
    user_id: str | None,
    action: str,
    request_payload: dict[str, Any] | None,
    response_payload: dict[str, Any] | None,
) -> None:
    """Open an async session and insert the audit row."""

    from backend.database import _session_factory
    from backend.models import AuditLog

    if _session_factory is None:
        return

    parsed_request_id = _parse_uuid_or_new(request_id)
    parsed_user_id = _parse_uuid_or_none(user_id)

    async with _session_factory() as session:
        record = AuditLog(
            request_id=parsed_request_id,
            user_id=parsed_user_id,
            action=action[:50],
            request_payload=request_payload,
            response_payload=response_payload,
        )
        session.add(record)
        await session.commit()


def _parse_uuid_or_new(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (TypeError, ValueError, AttributeError):
        return uuid.uuid4()


def _parse_uuid_or_none(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None
