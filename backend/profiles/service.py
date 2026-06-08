"""Profile CRUD service using async SQLAlchemy operations."""

from __future__ import annotations

import uuid
from typing import Any

from backend.models import Profile, User

try:
    from sqlalchemy import select
    from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
except ModuleNotFoundError:

    class IntegrityError(Exception):  # type: ignore[no-redef]
        """Fallback marker when SQLAlchemy is not installed."""

    class DBAPIError(Exception):  # type: ignore[no-redef]
        """Fallback marker when SQLAlchemy is not installed."""

    class OperationalError(DBAPIError):  # type: ignore[no-redef]
        """Fallback marker when SQLAlchemy is not installed."""

    class _FallbackSelect:
        def where(self, *conditions: Any) -> _FallbackSelect:
            return self

        def order_by(self, *columns: Any) -> _FallbackSelect:
            return self

    def select(*models: Any) -> _FallbackSelect:  # type: ignore[no-redef]
        return _FallbackSelect()


def _profile_by_user_year_stmt(user_id: uuid.UUID, tax_year: int) -> Any:
    stmt = select(Profile)
    try:
        return stmt.where(Profile.user_id == user_id, Profile.tax_year == tax_year)
    except AttributeError:
        return stmt


def _profile_by_id_stmt(profile_id: uuid.UUID) -> Any:
    stmt = select(Profile)
    try:
        return stmt.where(Profile.id == profile_id)
    except AttributeError:
        return stmt


def _user_by_id_stmt(user_id: uuid.UUID) -> Any:
    stmt = select(User)
    try:
        return stmt.where(User.id == user_id)
    except AttributeError:
        return stmt


def _profiles_by_user_stmt(user_id: uuid.UUID, tax_year: int | None) -> Any:
    stmt = select(Profile)
    try:
        stmt = stmt.where(Profile.user_id == user_id)
        if tax_year is not None:
            stmt = stmt.where(Profile.tax_year == tax_year)
        return stmt.order_by(Profile.tax_year.desc())
    except AttributeError:
        return stmt


def _new_user(user_id: uuid.UUID) -> User:
    return User(id=user_id)


def _new_profile(user_id: uuid.UUID, tax_year: int, data: dict[str, Any]) -> Profile:
    return Profile(user_id=user_id, tax_year=tax_year, data=data)


def is_database_unavailable_error(exc: Exception) -> bool:
    """Return whether an exception should degrade profile endpoints to 503."""

    return (
        isinstance(exc, OperationalError)
        or (isinstance(exc, DBAPIError) and bool(getattr(exc, "connection_invalidated", False)))
        or str(exc) == "PostgreSQL is not available"
    )


async def _ensure_user_exists(session: Any, user_id: uuid.UUID) -> None:
    result = await session.execute(_user_by_id_stmt(user_id))
    if result.scalar_one_or_none() is None:
        session.add(_new_user(user_id))
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            result = await session.execute(_user_by_id_stmt(user_id))
            if result.scalar_one_or_none() is None:
                raise


async def upsert_profile(session: Any, user_id: uuid.UUID, tax_year: int, data: dict[str, Any]) -> Profile:
    """Create or update a profile for the given user_id + tax_year."""

    result = await session.execute(_profile_by_user_year_stmt(user_id, tax_year))
    profile = result.scalar_one_or_none()

    if profile is not None:
        profile.data = data
        await session.commit()
        await session.refresh(profile)
        return profile

    await _ensure_user_exists(session, user_id)
    profile = _new_profile(user_id=user_id, tax_year=tax_year, data=data)
    session.add(profile)
    try:
        await session.commit()
        await session.refresh(profile)
        return profile
    except IntegrityError:
        await session.rollback()

    result = await session.execute(_profile_by_user_year_stmt(user_id, tax_year))
    profile = result.scalar_one_or_none()
    if profile is None:
        raise RuntimeError("Profile upsert conflict could not be recovered")
    profile.data = data
    await session.commit()
    await session.refresh(profile)
    return profile


async def get_profile_by_id(session: Any, profile_id: uuid.UUID) -> Profile | None:
    """Fetch a single profile by its primary key."""

    result = await session.execute(_profile_by_id_stmt(profile_id))
    return result.scalar_one_or_none()


async def get_profiles_by_user(session: Any, user_id: uuid.UUID, tax_year: int | None = None) -> list[Profile]:
    """Fetch profiles for a user, optionally filtered by tax_year."""

    result = await session.execute(_profiles_by_user_stmt(user_id, tax_year))
    return list(result.scalars().all())
