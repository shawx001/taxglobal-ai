"""FastAPI routes for profile persistence."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response

from backend.database import get_session, is_pg_available
from backend.errors import error_response
from backend.profiles.schemas import ProfileCreate, ProfileListResponse, ProfileResponse
from backend.profiles.service import (
    get_profile_by_id,
    get_profiles_by_user,
    is_database_unavailable_error,
    upsert_profile,
)

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


async def profile_session() -> Any:
    """Yield a profile DB session, or None when PostgreSQL is unavailable."""

    if not is_pg_available():
        yield None
        return
    async for session in get_session():
        yield session


def _postgres_unavailable(request: Request) -> JSONResponse:
    request_id = str(getattr(request.state, "request_id", "unknown"))
    return JSONResponse(
        status_code=503,
        headers={"X-Request-ID": request_id},
        content=error_response(
            code="postgres_unavailable",
            message="Profile persistence is temporarily unavailable.",
            request_id=request_id,
        ),
    )


async def _profile_action(request: Request, action: Any) -> Any:
    try:
        return await action()
    except Exception as exc:
        if is_database_unavailable_error(exc):
            return _postgres_unavailable(request)
        raise


@router.post("", response_model=ProfileResponse, status_code=201)
async def create_or_update_profile(
    request: Request,
    body: ProfileCreate,
    session: Any = Depends(profile_session),
) -> Any:
    """Create or update a tax profile (upsert by user_id + tax_year)."""

    if session is None:
        return _postgres_unavailable(request)
    return await _profile_action(
        request,
        lambda: upsert_profile(
            session=session,
            user_id=body.user_id,
            tax_year=body.tax_year,
            data=body.data,
        ),
    )


@router.get("/{profile_id}", response_model=ProfileResponse)
async def read_profile(request: Request, profile_id: uuid.UUID, session: Any = Depends(profile_session)) -> Any:
    """Read a single profile by ID."""

    if session is None:
        return _postgres_unavailable(request)
    profile = await _profile_action(request, lambda: get_profile_by_id(session, profile_id))
    if profile is None:
        request_id = str(getattr(request.state, "request_id", "unknown"))
        return JSONResponse(
            status_code=404,
            headers={"X-Request-ID": request_id},
            content=error_response(
                code="profile_not_found",
                message=f"Profile {profile_id} not found.",
                request_id=request_id,
            ),
        )
    return profile


@router.get("", response_model=ProfileListResponse)
async def list_profiles(
    request: Request,
    user_id: uuid.UUID = Query(..., description="Filter by user ID"),
    tax_year: int | None = Query(None, ge=2020, le=2030, description="Filter by tax year"),
    session: Any = Depends(profile_session),
) -> Any:
    """List profiles for a user, optionally filtered by tax year."""

    if session is None:
        return _postgres_unavailable(request)
    profiles = await _profile_action(request, lambda: get_profiles_by_user(session, user_id, tax_year))
    if isinstance(profiles, Response):
        return profiles
    return {"profiles": profiles, "total": len(profiles)}
