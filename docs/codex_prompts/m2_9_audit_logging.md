# Codex Prompt: M2.9 Audit Logging

> Pre-read: `/AGENTS.md` → `/ARCHITECTURE.md` → `docs/m2_step_plan.md` §M2.9

## Task

Build a **full-chain audit logging system** that records every Skill invocation,
assistant query, and tips request with PII-sanitized payloads, correlated to the
existing `X-Request-ID` header. The system writes to the existing `audit_log`
PostgreSQL table via async fire-and-forget tasks (never blocking the HTTP response),
and gracefully degrades to a no-op when PostgreSQL is unavailable.

An internal admin query endpoint `GET /api/admin/audit` exposes filtered audit
records for compliance review.

## Core Constraints

1. **Backward compatibility**: existing tests/APIs (`/calc/*`, `/api/skills`,
   `/api/assistant/query`, `/api/knowledge/search`, `/api/tips`, `/api/profiles`)
   must not break. Run `python -m unittest discover -s tests` — all existing tests
   pass unchanged.
2. **Data sovereignty**: no external API calls. All processing is local.
3. **Graceful degradation**: when PostgreSQL is unavailable, audit logging silently
   skips. No endpoint may fail because audit writing failed. The audit subsystem
   must never raise into the request path.
4. **PII sanitization**: SSN patterns → `***-**-{last4}`; name/email fields →
   `[redacted]`; income dollar amounts are **preserved** (needed for audit trail).
   No PII may appear in application logs (`logger.*` calls).
5. **Module size**: no single file > 500 lines; prefer 200-300 lines.
6. **Non-blocking writes**: audit records are written via `asyncio.create_task()`
   after the response is sent. The audit write must never increase response latency.
7. **Hash-chain tamper-evidence**: every audit record stores a SHA-256 hash of its
   own content and the hash of the previous record, forming a cryptographic chain.
   Altering any historical record invalidates all subsequent hashes.

## Existing Infrastructure (DO NOT recreate)

| What | Where | Notes |
|---|---|---|
| `AuditLog` ORM model | `backend/models.py` lines 52-67 | Columns: `id`, `request_id`, `user_id`, `action`, `request_payload`, `response_payload`, `created_at`. Already has indexes on `request_id` and `user_id`. **You will ADD two columns**: `entry_hash` (String(64)) and `prev_hash` (String(64)). |
| Alembic migration | `alembic/versions/001_initial_tables.py` | Table `audit_log` already created. **Create a new migration** `002_audit_hash_chain.py` to add the two hash columns. |
| PII regex patterns | `backend/guardrail/escalation.py` lines 14-18 | `_SSN_PATTERN`, `_COMMA_AMOUNT_PATTERN`, `_MONEY_LIKE_PATTERN`, `_LARGE_INTEGER_PATTERN`, `_PII_FIELD_PATTERN`. Import and reuse these — do NOT duplicate. |
| `RequestIdMiddleware` | `backend/main.py` lines 107-132 | Already generates `request.state.request_id` UUID and sets `X-Request-ID` response header. The audit middleware runs AFTER this. |
| Async session management | `backend/database.py` | `is_pg_available()`, `get_session()`, `_session_factory`. |
| SQLAlchemy fallback pattern | `backend/models.py` lines 69-83 | When SQLAlchemy is not installed, models are stub classes. Follow this pattern for imports in audit code. |

## Architecture

```
Request arrives → RequestIdMiddleware sets request_id
         │
         ▼
    ┌──────────────┐
    │  AuditMiddle  │  Captures request body for audited paths
    │  ware         │  (/api/skills/*, /api/assistant/*, /api/tips)
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │  Route handler│  Normal processing, returns response
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │  AuditMiddle  │  Captures response body, then fires:
    │  ware (after) │  asyncio.create_task(log_action(...))
    └──────┬───────┘
           │
           ▼
    Response sent to client (audit write happens in background)
```

## Section 1: PII Sanitizer

### File: `backend/audit/__init__.py`

Empty `__init__.py` to make `backend/audit/` a package.

### File: `backend/audit/sanitizer.py` (~80 lines)

Recursively sanitize dicts/lists before writing to `audit_log`. Reuse regex
patterns from `backend/guardrail/escalation.py`.

```python
"""PII sanitizer for audit log payloads."""

from __future__ import annotations

import copy
import re
from typing import Any

# Reuse existing PII patterns — single source of truth.
from backend.guardrail.escalation import _SSN_PATTERN

# Field names whose VALUES should be redacted (case-insensitive match).
_REDACT_FIELDS: frozenset[str] = frozenset({
    "ssn", "social_security_number", "ein",
    "name", "first_name", "last_name", "taxpayer_name", "spouse_name",
    "email", "email_address",
    "phone", "phone_number",
    "address", "street", "street_address",
})

# SSN-like patterns for value scanning (reuse from escalation).
# Already compiled as _SSN_PATTERN: r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"


def sanitize_payload(data: Any) -> Any:
    """Return a deep copy of *data* with PII fields and SSN values masked.

    - Dict keys in _REDACT_FIELDS → value replaced with "[redacted]"
    - SSN patterns in string values → "***-**-{last4}"
    - Income/dollar amounts are PRESERVED (needed for audit trail).
    - Non-dict/list values are returned as-is.
    """
    if data is None:
        return None
    # Deep-copy so the original response dict is never mutated.
    return _sanitize(copy.deepcopy(data))


def _sanitize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _sanitize_value(k, v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(item) for item in obj]
    if isinstance(obj, str):
        return _mask_ssn(obj)
    return obj


def _sanitize_value(key: str, value: Any) -> Any:
    if key.lower() in _REDACT_FIELDS:
        return "[redacted]"
    return _sanitize(value)


def _mask_ssn(text: str) -> str:
    """Replace SSN patterns with masked form, preserving last 4 digits."""
    def _replacer(match: re.Match[str]) -> str:
        digits = match.group().replace("-", "")
        return f"***-**-{digits[-4:]}"
    return _SSN_PATTERN.sub(_replacer, text)
```

**Key design decisions**:
- Import `_SSN_PATTERN` from escalation.py — do NOT duplicate the regex.
- Field-name redaction is a frozen set of known PII field names. This is safer than
  regex-matching field names (which caused false positives in M2.6 where "income"
  was redacted from code identifiers).
- Dollar amounts are explicitly NOT redacted — the audit trail needs them for
  compliance (e.g., "this calculation returned $X for user Y").
- Deep copy prevents mutation of the live response dict.

## Section 2: Audit Logger

### File: `backend/audit/logger.py` (~100 lines)

The core `log_action()` function writes one row to `audit_log`. It is always
called via `asyncio.create_task()` from the middleware — never awaited in the
request path.

```python
"""Async audit log writer."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from backend.audit.sanitizer import sanitize_payload
from backend.database import is_pg_available

logger = logging.getLogger("taxglobal.audit")

# Conditional SQLAlchemy imports — follow the same pattern as backend/models.py.
try:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
except ModuleNotFoundError:
    AsyncSession = Any  # type: ignore[misc, assignment]
    async_sessionmaker = None  # type: ignore[assignment]


async def log_action(
    *,
    request_id: str,
    user_id: str | None,
    action: str,
    request_payload: dict[str, Any] | None,
    response_payload: dict[str, Any] | None,
) -> None:
    """Write a sanitized audit record to PostgreSQL.

    This function is designed to be called via ``asyncio.create_task()``
    and must NEVER raise — all exceptions are caught and logged.

    When PostgreSQL is unavailable the call is a silent no-op.
    """
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
        # Never propagate — audit failure must not affect the user.
        logger.warning("Audit log write failed for request_id=%s", request_id)


async def _write_record(
    *,
    request_id: str,
    user_id: str | None,
    action: str,
    request_payload: dict[str, Any] | None,
    response_payload: dict[str, Any] | None,
) -> None:
    """Internal: open a session and INSERT the audit row."""
    from backend.database import _session_factory
    from backend.models import AuditLog

    if _session_factory is None:
        return

    parsed_request_id = uuid.UUID(request_id) if request_id and request_id != "unknown" else uuid.uuid4()
    parsed_user_id = uuid.UUID(user_id) if user_id else None

    async with _session_factory() as session:
        record = AuditLog(
            request_id=parsed_request_id,
            user_id=parsed_user_id,
            action=action[:50],  # column is VARCHAR(50)
            request_payload=request_payload,
            response_payload=response_payload,
        )
        session.add(record)
        await session.commit()
```

**Key design decisions**:
- `log_action()` has a top-level `try/except` that catches EVERYTHING. This is
  intentional: audit writes must never crash the application.
- Uses `_session_factory` directly (not `get_session()` dependency) because this
  runs outside the FastAPI request lifecycle (in a background task).
- `action` is truncated to 50 chars to match the VARCHAR(50) column.
- `sanitize_payload()` is called BEFORE the write, not after — PII never reaches
  the database.

## Section 2b: Hash-Chain Tamper-Evidence

### ORM model change: `backend/models.py`

Add two columns to `AuditLog`:

```python
class AuditLog(Base):
    # ... existing columns ...
    entry_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
```

Both nullable so existing rows (if any) are not broken by the migration.

### New migration: `alembic/versions/002_audit_hash_chain.py`

```python
"""add hash chain columns to audit_log

Revision ID: 002_audit_hash_chain
Revises: 001_initial_tables
Create Date: 2026-06-08
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "002_audit_hash_chain"
down_revision = "001_initial_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_log", sa.Column("entry_hash", sa.String(64), nullable=True))
    op.add_column("audit_log", sa.Column("prev_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("audit_log", "prev_hash")
    op.drop_column("audit_log", "entry_hash")
```

### Hash computation in `backend/audit/logger.py`

Add hash computation before writing the record. The hash chain works as follows:

```python
import hashlib
import json

def _compute_entry_hash(
    *,
    request_id: str,
    action: str,
    request_payload: dict | None,
    response_payload: dict | None,
    prev_hash: str,
) -> str:
    """SHA-256 hash of the audit record content + previous hash."""
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
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

In `_write_record()`, before inserting:
1. Query the most recent `entry_hash` from `audit_log` (ORDER BY id DESC LIMIT 1).
   If no rows exist, use `"0" * 64` as the genesis hash.
2. Compute `entry_hash = _compute_entry_hash(...)` using the prev record's hash.
3. Store both `entry_hash` and `prev_hash` on the new record.

**Important**: The hash query + insert should be within the same session/transaction
to avoid race conditions between concurrent audit writes. If two writes race, one
will get a stale `prev_hash` — this is acceptable at M2 scale; the chain is still
verifiable. For strict ordering, a future enhancement could use a DB sequence lock.

### Hash chain verification in `backend/audit/routes.py`

Add a `GET /api/admin/audit/verify` endpoint:

```python
@router.get("/audit/verify")
async def verify_audit_chain(
    limit: int = Query(100, ge=1, le=1000),
    session: Any = Depends(_audit_session),
) -> dict[str, Any]:
    """Verify the integrity of the audit log hash chain."""
    # Query last N records ordered by id ASC
    # For each consecutive pair, verify:
    #   record[i].prev_hash == record[i-1].entry_hash
    #   record[i].entry_hash == _compute_entry_hash(record[i] fields + prev_hash)
    # Return: {"verified": N, "broken_at": null or record_id, "status": "ok"|"tampered"}
```

## Section 3: Audit Middleware

### File: `backend/audit/middleware.py` (~120 lines)

FastAPI/Starlette middleware that auto-captures request/response payloads for
audited route prefixes.

```python
"""Audit logging middleware for FastAPI."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from backend.audit.logger import log_action

logger = logging.getLogger("taxglobal.audit")

# Only audit these path prefixes. /calc/* is NOT audited (high-volume,
# engine-only, no user-facing side effects).
AUDITED_PREFIXES: tuple[str, ...] = (
    "/api/skills/",
    "/api/assistant/",
    "/api/tips",
    "/api/admin/audit",
)


def _should_audit(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in AUDITED_PREFIXES)


def _extract_action(method: str, path: str) -> str:
    """Derive a short action label from the HTTP method and path.

    Examples:
      POST /api/skills/calculate_income_tax → "skill:calculate_income_tax"
      POST /api/assistant/query             → "assistant:query"
      GET  /api/tips                        → "tips:get"
      GET  /api/admin/audit                 → "admin:audit"
    """
    if path.startswith("/api/skills/"):
        skill_name = path.removeprefix("/api/skills/").split("/")[0].split("?")[0]
        return f"skill:{skill_name}" if skill_name else "skill:list"
    if path.startswith("/api/assistant/"):
        sub = path.removeprefix("/api/assistant/").split("/")[0].split("?")[0]
        return f"assistant:{sub}" if sub else "assistant:unknown"
    if path.startswith("/api/tips"):
        return "tips:get"
    if path.startswith("/api/admin/audit"):
        return "admin:audit"
    return f"{method.lower()}:{path}"


class AuditMiddleware(BaseHTTPMiddleware):
    """Capture request/response for audited routes and log asynchronously."""

    async def dispatch(self, request: Request, call_next):
        if not _should_audit(request.url.path):
            return await call_next(request)

        # --- Capture request body (for POST/PUT/PATCH) ---
        request_body: dict[str, Any] | None = None
        if request.method in {"POST", "PUT", "PATCH"}:
            try:
                raw = await request.body()
                request_body = json.loads(raw) if raw else None
            except Exception:
                request_body = None

        # --- Process the request normally ---
        response = await call_next(request)

        # --- Capture response body ---
        response_body: dict[str, Any] | None = None
        body_chunks: list[bytes] = []
        async for chunk in response.body_iterator:
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8")
            body_chunks.append(chunk)
        full_body = b"".join(body_chunks)

        try:
            response_body = json.loads(full_body) if full_body else None
        except Exception:
            response_body = None

        # Reconstruct the response with the same body
        from starlette.responses import Response as StarletteResponse
        new_response = StarletteResponse(
            content=full_body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )

        # --- Fire-and-forget audit write ---
        request_id = str(getattr(request.state, "request_id", "unknown"))
        action = _extract_action(request.method, request.url.path)

        asyncio.create_task(
            log_action(
                request_id=request_id,
                user_id=None,  # user_id extraction deferred to M2.10 (auth)
                action=action,
                request_payload=request_body,
                response_payload=response_body,
            )
        )

        return new_response
```

**Key design decisions**:
- Only audits specific path prefixes — `/calc/*` is excluded (high volume, pure
  engine, no user-facing side effects worth auditing individually).
- `user_id` is `None` for now — auth/session support comes in later milestones.
  The column is nullable for exactly this reason.
- Response body is captured by draining `body_iterator` and reconstructing the
  response. This is the standard Starlette pattern for body interception.
- `asyncio.create_task()` fires the audit write without awaiting it, ensuring
  zero added latency on the response.

### Wire into `backend/main.py`

Add the `AuditMiddleware` after `RequestIdMiddleware` (so `request.state.request_id`
is already set when audit runs):

```python
from backend.audit.middleware import AuditMiddleware

# In create_app(), after app.add_middleware(RequestIdMiddleware):
app.add_middleware(AuditMiddleware)
```

**Important**: Starlette middleware is a LIFO stack. The LAST `add_middleware()`
call runs FIRST on request entry. So adding `AuditMiddleware` AFTER
`RequestIdMiddleware` means:
- Request enters → AuditMiddleware.dispatch → RequestIdMiddleware.dispatch → route
- Response exits → RequestIdMiddleware (sets X-Request-ID) → AuditMiddleware (logs)

Wait — that means `request.state.request_id` might NOT be set when AuditMiddleware
runs. To fix this, add `AuditMiddleware` BEFORE `RequestIdMiddleware`:

```python
# Correct order in create_app():
app.add_middleware(RequestIdMiddleware)    # runs first on request (sets request_id)
app.add_middleware(AuditMiddleware)        # runs second (reads request_id)
```

No — Starlette LIFO means the LAST added runs OUTERMOST. So:

```python
app.add_middleware(AuditMiddleware)        # added last → runs outermost
app.add_middleware(RequestIdMiddleware)    # added first → runs innermost
```

**Correct final order in `create_app()`**:

```python
app.add_middleware(CORSMiddleware, ...)
app.add_middleware(RequestIdMiddleware)     # inner: sets request_id
app.add_middleware(AuditMiddleware)         # outer: reads request_id after inner sets it
```

Actually, because Starlette is LIFO, the LAST `add_middleware` processes the
request FIRST. Since `AuditMiddleware` needs `request_id` to be already set,
`RequestIdMiddleware` must process the request first, meaning it must be added
LAST:

```python
# In create_app() — order matters (Starlette LIFO):
app.add_middleware(AuditMiddleware)         # added first → processes request LAST
app.add_middleware(RequestIdMiddleware)     # added last → processes request FIRST
```

**Codex**: validate the middleware ordering by checking that `request.state.request_id`
is available inside `AuditMiddleware.dispatch`. If the test
`test_audit_request_id_correlation` fails, swap the `add_middleware` order.

## Section 4: Admin Audit Query Route

### File: `backend/audit/routes.py` (~80 lines)

```python
"""Admin route for querying audit logs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from backend.database import get_session, is_pg_available
from backend.errors import error_response

router = APIRouter(prefix="/api/admin", tags=["admin"])


async def _audit_session():
    """Yield DB session or return 503 when PG unavailable."""
    if not is_pg_available():
        yield None
        return
    async for session in get_session():
        yield session


@router.get("/audit")
async def query_audit_log(
    request: Request,
    user_id: str | None = Query(None, description="Filter by user UUID"),
    action: str | None = Query(None, description="Filter by action prefix, e.g. 'skill:'"),
    from_date: str | None = Query(None, alias="from", description="ISO date lower bound"),
    to_date: str | None = Query(None, alias="to", description="ISO date upper bound"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: Any = Depends(_audit_session),
) -> dict[str, Any] | JSONResponse:
    """Query audit log records with filters. Internal admin use."""

    request_id = str(getattr(request.state, "request_id", "unknown"))

    if session is None:
        return JSONResponse(
            status_code=503,
            headers={"X-Request-ID": request_id},
            content=error_response(
                code="storage_unavailable",
                message="PostgreSQL is not available.",
                request_id=request_id,
            ),
        )

    # Build query with filters
    from backend.models import AuditLog
    try:
        from sqlalchemy import select
    except ModuleNotFoundError:
        return JSONResponse(status_code=503, content={"error": "SQLAlchemy not available"})

    stmt = select(AuditLog).order_by(AuditLog.created_at.desc())

    if user_id:
        import uuid as _uuid
        stmt = stmt.where(AuditLog.user_id == _uuid.UUID(user_id))
    if action:
        stmt = stmt.where(AuditLog.action.startswith(action))
    if from_date:
        stmt = stmt.where(AuditLog.created_at >= datetime.fromisoformat(from_date))
    if to_date:
        stmt = stmt.where(AuditLog.created_at <= datetime.fromisoformat(to_date))

    stmt = stmt.limit(limit).offset(offset)

    result = await session.execute(stmt)
    records = result.scalars().all()

    return {
        "records": [
            {
                "id": record.id,
                "request_id": str(record.request_id),
                "user_id": str(record.user_id) if record.user_id else None,
                "action": record.action,
                "request_payload": record.request_payload,
                "response_payload": record.response_payload,
                "created_at": record.created_at.isoformat() if record.created_at else None,
            }
            for record in records
        ],
        "total_returned": len(records),
        "limit": limit,
        "offset": offset,
    }
```

### Wire into `backend/main.py`

```python
from backend.audit.routes import router as audit_router
# ...
app.include_router(audit_router)
```

## Section 5: Tests

### File: `tests/test_m2_9_audit.py` (~250 lines)

```python
"""Tests for M2.9 Audit Logging."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from backend.audit.sanitizer import sanitize_payload


class TestSanitizer(unittest.TestCase):
    """PII sanitization for audit payloads."""

    def test_ssn_masked_with_last_four(self) -> None:
        data = {"notes": "SSN is 123-45-6789"}
        result = sanitize_payload(data)
        self.assertNotIn("123-45-6789", result["notes"])
        self.assertIn("***-**-6789", result["notes"])

    def test_name_fields_redacted(self) -> None:
        data = {"first_name": "John", "last_name": "Doe", "email": "john@example.com"}
        result = sanitize_payload(data)
        self.assertEqual(result["first_name"], "[redacted]")
        self.assertEqual(result["last_name"], "[redacted]")
        self.assertEqual(result["email"], "[redacted]")

    def test_income_amounts_preserved(self) -> None:
        data = {"gross_income": 150000, "taxable_income": 120000.50}
        result = sanitize_payload(data)
        self.assertEqual(result["gross_income"], 150000)
        self.assertEqual(result["taxable_income"], 120000.50)

    def test_nested_dict_sanitized(self) -> None:
        data = {"profile": {"ssn": "987-65-4321", "w2_wages": 85000}}
        result = sanitize_payload(data)
        self.assertEqual(result["profile"]["ssn"], "[redacted]")
        self.assertEqual(result["profile"]["w2_wages"], 85000)

    def test_list_items_sanitized(self) -> None:
        data = {"items": [{"name": "Alice"}, {"name": "Bob"}]}
        result = sanitize_payload(data)
        self.assertEqual(result["items"][0]["name"], "[redacted]")
        self.assertEqual(result["items"][1]["name"], "[redacted]")

    def test_none_input_returns_none(self) -> None:
        self.assertIsNone(sanitize_payload(None))

    def test_original_dict_not_mutated(self) -> None:
        data = {"ssn": "111-22-3333", "income": 50000}
        sanitize_payload(data)
        self.assertEqual(data["ssn"], "111-22-3333")

    def test_ssn_in_nested_string(self) -> None:
        data = {"description": "Taxpayer SSN 123-45-6789 filed on time"}
        result = sanitize_payload(data)
        self.assertIn("***-**-6789", result["description"])
        self.assertNotIn("123-45", result["description"])


class TestActionExtraction(unittest.TestCase):
    """Audit action label derivation from HTTP method + path."""

    def test_skill_invocation(self) -> None:
        from backend.audit.middleware import _extract_action
        self.assertEqual(_extract_action("POST", "/api/skills/calculate_income_tax"), "skill:calculate_income_tax")

    def test_assistant_query(self) -> None:
        from backend.audit.middleware import _extract_action
        self.assertEqual(_extract_action("POST", "/api/assistant/query"), "assistant:query")

    def test_tips_get(self) -> None:
        from backend.audit.middleware import _extract_action
        self.assertEqual(_extract_action("GET", "/api/tips"), "tips:get")

    def test_admin_audit(self) -> None:
        from backend.audit.middleware import _extract_action
        self.assertEqual(_extract_action("GET", "/api/admin/audit"), "admin:audit")

    def test_skill_list(self) -> None:
        from backend.audit.middleware import _extract_action
        self.assertEqual(_extract_action("GET", "/api/skills/"), "skill:list")


class TestAuditMiddlewarePaths(unittest.TestCase):
    """Verify which paths are audited."""

    def test_skills_path_audited(self) -> None:
        from backend.audit.middleware import _should_audit
        self.assertTrue(_should_audit("/api/skills/calculate_income_tax"))

    def test_assistant_path_audited(self) -> None:
        from backend.audit.middleware import _should_audit
        self.assertTrue(_should_audit("/api/assistant/query"))

    def test_tips_path_audited(self) -> None:
        from backend.audit.middleware import _should_audit
        self.assertTrue(_should_audit("/api/tips"))

    def test_calc_path_not_audited(self) -> None:
        from backend.audit.middleware import _should_audit
        self.assertFalse(_should_audit("/calc/federal-income"))

    def test_profiles_path_not_audited(self) -> None:
        from backend.audit.middleware import _should_audit
        self.assertFalse(_should_audit("/api/profiles"))

    def test_health_path_not_audited(self) -> None:
        from backend.audit.middleware import _should_audit
        self.assertFalse(_should_audit("/api/health"))


class TestAuditIntegration(unittest.TestCase):
    """Integration tests against the FastAPI app."""

    def setUp(self) -> None:
        from fastapi.testclient import TestClient
        from backend.main import create_app
        self.client = TestClient(create_app())

    def test_skill_call_still_works_with_audit(self) -> None:
        """Audit middleware does not break skill invocation."""
        response = self.client.post(
            "/api/skills/calculate_income_tax",
            json={"gross_income": 100000, "filing_status": "single", "tax_year": 2026},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("X-Request-ID", response.headers)

    def test_assistant_query_still_works_with_audit(self) -> None:
        response = self.client.post(
            "/api/assistant/query",
            json={"query": "What is FEIE?"},
        )
        self.assertEqual(response.status_code, 200)

    def test_tips_endpoint_still_works_with_audit(self) -> None:
        response = self.client.get("/api/tips")
        self.assertEqual(response.status_code, 200)

    def test_calc_endpoint_unaffected(self) -> None:
        """Non-audited routes must work exactly as before."""
        response = self.client.post(
            "/calc/federal-income",
            json={"gross_income": 100000, "filing_status": "single", "tax_year": 2026},
        )
        self.assertEqual(response.status_code, 200)

    def test_admin_audit_endpoint_returns_503_when_pg_down(self) -> None:
        """Admin audit returns 503 gracefully when PG unavailable."""
        response = self.client.get("/api/admin/audit")
        # In test env PG is typically unavailable → expect 503
        self.assertIn(response.status_code, [200, 503])

    def test_existing_routes_unaffected(self) -> None:
        """Regression: all existing endpoint families still work."""
        calc = self.client.post(
            "/calc/federal-income",
            json={"gross_income": 100000, "filing_status": "single", "tax_year": 2026},
        )
        skills = self.client.get("/api/skills")
        search = self.client.get("/api/knowledge/search", params={"q": "FEIE"})
        assistant = self.client.post("/api/assistant/query", json={"query": "hello"})
        tips = self.client.get("/api/tips")

        self.assertEqual(calc.status_code, 200)
        self.assertEqual(skills.status_code, 200)
        self.assertEqual(search.status_code, 200)
        self.assertEqual(assistant.status_code, 200)
        self.assertEqual(tips.status_code, 200)


class TestHashChain(unittest.TestCase):
    """SHA-256 hash-chain tamper-evidence tests."""

    def test_compute_entry_hash_deterministic(self) -> None:
        """Same inputs produce same hash."""
        from backend.audit.logger import _compute_entry_hash
        h1 = _compute_entry_hash(
            request_id="abc", action="skill:test",
            request_payload={"a": 1}, response_payload={"b": 2},
            prev_hash="0" * 64,
        )
        h2 = _compute_entry_hash(
            request_id="abc", action="skill:test",
            request_payload={"a": 1}, response_payload={"b": 2},
            prev_hash="0" * 64,
        )
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)  # SHA-256 hex

    def test_different_payload_different_hash(self) -> None:
        from backend.audit.logger import _compute_entry_hash
        h1 = _compute_entry_hash(
            request_id="abc", action="skill:test",
            request_payload={"income": 100000}, response_payload=None,
            prev_hash="0" * 64,
        )
        h2 = _compute_entry_hash(
            request_id="abc", action="skill:test",
            request_payload={"income": 100001}, response_payload=None,
            prev_hash="0" * 64,
        )
        self.assertNotEqual(h1, h2)

    def test_different_prev_hash_different_entry_hash(self) -> None:
        """Changing prev_hash breaks the chain."""
        from backend.audit.logger import _compute_entry_hash
        h1 = _compute_entry_hash(
            request_id="abc", action="test",
            request_payload=None, response_payload=None,
            prev_hash="0" * 64,
        )
        h2 = _compute_entry_hash(
            request_id="abc", action="test",
            request_payload=None, response_payload=None,
            prev_hash="a" * 64,
        )
        self.assertNotEqual(h1, h2)

    def test_admin_verify_endpoint_returns_503_or_200(self) -> None:
        """Verify endpoint works or returns 503 when PG unavailable."""
        from fastapi.testclient import TestClient
        from backend.main import create_app
        client = TestClient(create_app())
        response = client.get("/api/admin/audit/verify")
        self.assertIn(response.status_code, [200, 503])
```

## Acceptance Gates

```powershell
# All tests pass (existing + new M2.9 tests)
python -m unittest discover -s tests

# Lint clean
python -m ruff check engine backend tests

# No uncommitted changes
git diff --check

# Specific: audit middleware does not break existing endpoints
python -c "from fastapi.testclient import TestClient; from backend.main import create_app; c=TestClient(create_app()); print('skills', c.get('/api/skills').status_code); print('calc', c.post('/calc/federal-income', json={'gross_income':100000,'filing_status':'single','tax_year':2026}).status_code); print('tips', c.get('/api/tips').status_code)"
```

## File Summary

| File | Action | ~Lines |
|---|---|---|
| `backend/audit/__init__.py` | **New** | ~1 |
| `backend/audit/sanitizer.py` | **New** | ~80 |
| `backend/audit/logger.py` | **New** — includes `_compute_entry_hash()` + hash-chain logic | ~130 |
| `backend/audit/middleware.py` | **New** | ~120 |
| `backend/audit/routes.py` | **New** — includes `/api/admin/audit/verify` chain verification | ~120 |
| `backend/models.py` | **Edit** — add `entry_hash`, `prev_hash` columns to AuditLog | +2 |
| `backend/main.py` | **Edit** — add AuditMiddleware + audit_router | +5 |
| `alembic/versions/002_audit_hash_chain.py` | **New** — migration for hash columns | ~25 |
| `tests/test_m2_9_audit.py` | **New** — includes hash-chain tests | ~300 |

**Total new code**: ~780 lines across 6 new files + 2 edits.

## Commit Format

```
feat(audit): M2.9 audit logging with PII sanitization + hash-chain

Add async audit logging middleware that captures request/response payloads
for /api/skills/*, /api/assistant/*, /api/tips routes. PII (SSN, names,
emails) sanitized before database write; income amounts preserved for
audit trail. Fire-and-forget via asyncio.create_task — zero response
latency impact. Graceful degradation when PostgreSQL unavailable.

SHA-256 hash-chain: each audit record stores entry_hash and prev_hash,
forming a tamper-evident chain. GET /api/admin/audit/verify validates
chain integrity.

Includes admin query endpoint GET /api/admin/audit with date/user/action
filters.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```
