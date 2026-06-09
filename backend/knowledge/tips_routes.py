"""FastAPI routes for KB-driven tax tips and deadlines."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query

from backend.database import get_session, is_pg_available
from backend.knowledge.tips import (
    TipContext,
    context_from_params,
    context_from_profile,
    get_deadlines,
    get_tips,
)

router = APIRouter(prefix="/api/tips", tags=["tips"])


async def tips_session() -> Any:
    """Yield a DB session or None when PostgreSQL is unavailable."""

    if not is_pg_available():
        yield None
        return
    async for session in get_session():
        yield session


async def _context_from_profile_id(profile_id: str, tax_year: int, session: Any) -> tuple[TipContext | None, bool]:
    if session is None:
        return None, False
    from backend.profiles.service import get_profile_by_id, is_database_unavailable_error

    try:
        profile = await get_profile_by_id(session, uuid.UUID(profile_id))
    except (ValueError, TypeError):
        return None, False
    except Exception as exc:
        if is_database_unavailable_error(exc):
            return None, False
        raise
    if profile is None:
        return None, False
    return context_from_profile(profile.data, tax_year), True


@router.get("")
async def tips_and_deadlines(
    profile_id: str | None = Query(None, description="Profile UUID to load context from"),
    state: str = Query("", max_length=2, description="2-letter state code"),
    filing_status: str = Query("single", description="Filing status"),
    income_types: str = Query("", description="Comma-separated: w2,self_employment,foreign,crypto,rsu"),
    tax_year: int = Query(2026, ge=2025, le=2030),
    session: Any = Depends(tips_session),
) -> dict[str, Any]:
    """Return personalized KB-driven tips and upcoming deadlines."""

    profile_used = False
    ctx: TipContext | None = None
    if profile_id:
        ctx, profile_used = await _context_from_profile_id(profile_id, tax_year, session)
    if ctx is None:
        ctx = context_from_params(
            state=state,
            filing_status=filing_status,
            income_types=income_types,
            tax_year=tax_year,
        )

    return {
        "tips": get_tips(ctx),
        "deadlines": get_deadlines(ctx),
        "profile_used": profile_used,
        "context": {
            "state": ctx.state,
            "filing_status": ctx.filing_status,
            "income_types": list(ctx.income_types),
            "tax_year": ctx.tax_year,
            "has_crypto": ctx.has_crypto,
            "has_rsu": ctx.has_rsu,
        },
    }
