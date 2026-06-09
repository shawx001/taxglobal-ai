"""Async audit log writer."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any

from backend.audit.sanitizer import sanitize_payload
from backend.database import is_pg_available

logger = logging.getLogger("taxglobal.audit")
GENESIS_HASH = "0" * 64

try:
    from sqlalchemy import select
except ModuleNotFoundError:
    select = None  # type: ignore[assignment]


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
        # KNOWN LIMITATION: concurrent fire-and-forget tasks can read the same
        # latest entry_hash before either commits, forking the hash chain.
        # Fix requires pg_advisory_xact_lock — deferred to hash-chain hardening PR.
        prev_hash = await _latest_entry_hash(session)
        entry_hash = _compute_entry_hash(
            request_id=str(parsed_request_id),
            action=action[:50],
            request_payload=request_payload,
            response_payload=response_payload,
            prev_hash=prev_hash,
        )
        record = AuditLog(
            request_id=parsed_request_id,
            user_id=parsed_user_id,
            action=action[:50],
            request_payload=request_payload,
            response_payload=response_payload,
            entry_hash=entry_hash,
            prev_hash=prev_hash,
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


def _compute_entry_hash(
    *,
    request_id: str,
    action: str,
    request_payload: dict[str, Any] | None,
    response_payload: dict[str, Any] | None,
    prev_hash: str,
) -> str:
    canonical = json.dumps(
        {
            "request_id": request_id,
            "action": action,
            "request_payload": request_payload,
            "response_payload": response_payload,
            "prev_hash": prev_hash,
        },
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _latest_entry_hash(session: Any) -> str:
    from backend.models import AuditLog

    if select is None or not hasattr(AuditLog, "entry_hash"):
        return GENESIS_HASH
    result = await session.execute(select(AuditLog.entry_hash).order_by(AuditLog.id.desc()).limit(1))
    latest_hash = result.scalar_one_or_none()
    return latest_hash if isinstance(latest_hash, str) and latest_hash else GENESIS_HASH
