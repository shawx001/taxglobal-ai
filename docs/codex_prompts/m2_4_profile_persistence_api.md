# Codex Prompt: M2.4 Profile Persistence API

> Pre-read: `/AGENTS.md` → `/ARCHITECTURE.md` → `docs/m2_step_plan.md` §M2.4

## Task

Build a profile persistence API that moves user tax profiles from browser localStorage to server-side PostgreSQL. This enables cross-device access and creates the foundation for audit logging. The API supports create/read/update (upsert by `user_id + tax_year`) via standard REST endpoints.

PostgreSQL and the ORM models (`User`, `Profile`) already exist in `backend/database.py` and `backend/models.py` from M2.1. This step adds the route layer, Pydantic schemas, and service logic on top of them.

Existing `/calc/*` endpoints and `/api/knowledge/search` must be completely unaffected.

## Core Constraints

1. **Backward compatibility**: all existing tests and routes must pass unchanged.
2. **Graceful degradation**: if PostgreSQL is unavailable (`ENABLE_POSTGRES=false` or connection fails), profile endpoints return `503 Service Unavailable` with a clear error message — but **`/calc/*` and `/api/knowledge/search` continue working**.
3. **Idempotent upsert**: `POST /api/profiles` with the same `user_id + tax_year` updates the existing record (no duplicates). The `Profile` model already has `UniqueConstraint("user_id", "tax_year")`.
4. **PII awareness**: MVP stores profile `data` as JSONB plaintext (column-level encryption deferred to M5). Do NOT log the `data` field contents. Log only `user_id`, `tax_year`, and `profile_id`.
5. **No authentication (MVP)**: `user_id` is passed as a field in the request body / query param. Real auth is M5. This is explicitly acceptable for the MVP.
6. **Stateless + idempotent**: all endpoints are pure CRUD — no side effects beyond database writes.

## Section 1: Profile Pydantic Schemas

### File: `backend/profiles/schemas.py`

Define request/response schemas using Pydantic v2. The `data` field is a flexible JSONB dict that mirrors the frontend localStorage structure.

```python
"""Pydantic schemas for profile persistence API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProfileCreate(BaseModel):
    """Request body for creating/upserting a profile."""

    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID
    tax_year: int = Field(default=2026, ge=2020, le=2030)
    data: dict[str, Any] = Field(
        ...,
        description="Tax profile data (filing_status, income sources, deductions, etc.)",
    )
    # PII note: `data` may contain sensitive fields (income amounts, SSN in future).
    # MVP stores plaintext JSONB; M5 adds column-level encryption.


class ProfileResponse(BaseModel):
    """Response body for a single profile."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    tax_year: int
    data: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ProfileListResponse(BaseModel):
    """Response body for listing profiles."""

    profiles: list[ProfileResponse]
    total: int
```

## Section 2: Profile Service Layer

### File: `backend/profiles/service.py`

Thin async service that wraps SQLAlchemy queries. This keeps route handlers clean and makes testing easier.

```python
"""Profile CRUD service — async SQLAlchemy operations."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Profile


async def upsert_profile(
    session: AsyncSession,
    user_id: uuid.UUID,
    tax_year: int,
    data: dict[str, Any],
) -> Profile:
    """Create or update a profile for the given user_id + tax_year.

    Uses SELECT + INSERT/UPDATE pattern (not raw ON CONFLICT) for
    portability and clarity. The UniqueConstraint on (user_id, tax_year)
    ensures no duplicates even under concurrent requests.
    """
    stmt = select(Profile).where(Profile.user_id == user_id, Profile.tax_year == tax_year)
    result = await session.execute(stmt)
    profile = result.scalar_one_or_none()

    if profile is not None:
        profile.data = data
        # updated_at is handled by onupdate=func.now() in the model
    else:
        profile = Profile(user_id=user_id, tax_year=tax_year, data=data)
        session.add(profile)

    await session.commit()
    await session.refresh(profile)
    return profile


async def get_profile_by_id(session: AsyncSession, profile_id: uuid.UUID) -> Profile | None:
    """Fetch a single profile by its primary key."""
    result = await session.execute(select(Profile).where(Profile.id == profile_id))
    return result.scalar_one_or_none()


async def get_profiles_by_user(
    session: AsyncSession,
    user_id: uuid.UUID,
    tax_year: int | None = None,
) -> list[Profile]:
    """Fetch profiles for a user, optionally filtered by tax_year."""
    stmt = select(Profile).where(Profile.user_id == user_id)
    if tax_year is not None:
        stmt = stmt.where(Profile.tax_year == tax_year)
    stmt = stmt.order_by(Profile.tax_year.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())
```

## Section 3: Profile Routes

### File: `backend/profiles/routes.py`

FastAPI router with three endpoints. Uses `Depends(get_session)` for database access.

```python
"""FastAPI routes for profile persistence."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from backend.database import get_session
from backend.errors import error_response
from backend.profiles.schemas import ProfileCreate, ProfileListResponse, ProfileResponse
from backend.profiles.service import get_profile_by_id, get_profiles_by_user, upsert_profile

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


@router.post("", response_model=ProfileResponse, status_code=201)
async def create_or_update_profile(
    body: ProfileCreate,
    session=Depends(get_session),
) -> Any:
    """Create or update a tax profile (upsert by user_id + tax_year)."""
    profile = await upsert_profile(
        session=session,
        user_id=body.user_id,
        tax_year=body.tax_year,
        data=body.data,
    )
    return profile


@router.get("/{profile_id}", response_model=ProfileResponse)
async def read_profile(
    profile_id: uuid.UUID,
    session=Depends(get_session),
) -> Any:
    """Read a single profile by ID."""
    profile = await get_profile_by_id(session, profile_id)
    if profile is None:
        return JSONResponse(
            status_code=404,
            content=error_response(
                code="profile_not_found",
                message=f"Profile {profile_id} not found.",
                request_id="",  # middleware will set the real one
            ),
        )
    return profile


@router.get("", response_model=ProfileListResponse)
async def list_profiles(
    user_id: uuid.UUID = Query(..., description="Filter by user ID"),
    tax_year: int | None = Query(None, ge=2020, le=2030, description="Filter by tax year"),
    session=Depends(get_session),
) -> Any:
    """List profiles for a user, optionally filtered by tax year."""
    profiles = await get_profiles_by_user(session, user_id, tax_year)
    return {"profiles": profiles, "total": len(profiles)}
```

**Important**: when PostgreSQL is unavailable, `get_session()` raises `RuntimeError("PostgreSQL is not available")`. The route should NOT catch this — let FastAPI's global exception handler (already in `main.py`) return a 500. This is consistent with graceful degradation: profile endpoints fail, but calc/search endpoints are unaffected.

### File: `backend/profiles/__init__.py`

Empty `__init__.py` to make this a Python package.

## Section 4: Wire into main.py

In `create_app()`, import and include the profiles router:

```python
from backend.profiles.routes import router as profiles_router
# ...
app.include_router(profiles_router)
```

Place this after `app.include_router(search_router)`.

## Section 5: Tests

### File: `tests/test_m2_4_profiles.py`

Use `unittest` with `unittest.mock.patch`. Since the real database isn't available in CI, mock the `get_session` dependency to return an in-memory mock session. For the service layer tests, mock `AsyncSession`.

**TestProfileSchemas** (3 tests):
- `test_profile_create_valid`: valid input → no error
- `test_profile_create_missing_data`: missing `data` field → ValidationError
- `test_profile_create_extra_field_rejected`: extra field → ValidationError (extra="forbid")

**TestProfileService** (4 tests — mock AsyncSession):
- `test_upsert_creates_new_profile`: no existing record → INSERT
- `test_upsert_updates_existing_profile`: existing record → UPDATE `data` field
- `test_get_profile_by_id_found`: profile exists → returns it
- `test_get_profile_by_id_not_found`: no profile → returns None

**TestProfileRoutes** (6 tests — mock get_session + service functions):
- `test_create_profile_returns_201`: valid POST → 201 with profile data
- `test_create_profile_missing_data_returns_422`: POST without `data` → 422
- `test_read_profile_returns_200`: GET /{id} with existing profile → 200
- `test_read_profile_not_found_returns_404`: GET /{id} with missing profile → 404
- `test_list_profiles_returns_200`: GET ?user_id=... → 200 with list
- `test_list_profiles_missing_user_id_returns_422`: GET without user_id → 422

**TestProfileGracefulDegradation** (2 tests):
- `test_profile_endpoint_503_when_pg_unavailable`: ENABLE_POSTGRES=false → profile endpoints return 500/503, but...
- `test_calc_endpoint_unaffected_when_pg_unavailable`: ...`/calc/income-tax` still returns 200

**Total: ~15 tests.**

## Section 6: Files Changed Summary

| File | Action | Purpose |
|---|---|---|
| `backend/profiles/__init__.py` | **NEW** | Package init |
| `backend/profiles/schemas.py` | **NEW** | Pydantic request/response schemas |
| `backend/profiles/service.py` | **NEW** | Async CRUD service layer |
| `backend/profiles/routes.py` | **NEW** | FastAPI router for `/api/profiles` |
| `backend/main.py` | **EDIT** | Include profiles_router |
| `tests/test_m2_4_profiles.py` | **NEW** | ~15 tests |

No changes to: `engine/`, `data/`, `backend/routes/calc.py`, `backend/knowledge/`, `backend/models.py`, existing tests.

## Acceptance Gates

```powershell
# All existing + new tests pass
python -m unittest discover -s tests

# Lint clean
python -m ruff check engine backend tests

# No trailing whitespace / merge conflicts
git diff --check
```

Additional verification:
- `POST /api/profiles` with valid body → 201 with profile data
- `POST /api/profiles` with same user_id + tax_year → updates (not duplicates)
- `GET /api/profiles/{id}` → 200 with profile
- `GET /api/profiles/{nonexistent_id}` → 404
- `GET /api/profiles?user_id=...` → 200 with list
- `GET /api/health` still returns store status
- All existing `/calc/*` and `/api/knowledge/search` endpoints unaffected
- `ENABLE_POSTGRES=false` → profile endpoints fail gracefully, calc works

## Commit Format

```
feat(profiles): add profile persistence API (M2.4)

Implement REST endpoints for tax profile CRUD (POST/GET /api/profiles)
backed by PostgreSQL. Upsert by user_id + tax_year ensures idempotent
writes. Graceful degradation when PG unavailable. ~15 tests covering
schemas, service layer, routes, and degradation paths.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```
