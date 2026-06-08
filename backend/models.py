"""SQLAlchemy ORM models for M2 business data."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from backend.database import Base

try:
    from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
    from sqlalchemy.dialects.postgresql import JSONB, UUID
    from sqlalchemy.orm import Mapped, mapped_column, relationship

    class User(Base):
        """Application user record."""

        __tablename__ = "users"

        id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
        created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
        updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

        profiles: Mapped[list[Profile]] = relationship("Profile", back_populates="user")

    class Profile(Base):
        """Per-user tax profile snapshot for one tax year."""

        __tablename__ = "profiles"
        __table_args__ = (UniqueConstraint("user_id", "tax_year", name="uq_profiles_user_tax_year"),)

        id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
        user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
        tax_year: Mapped[int] = mapped_column(Integer, nullable=False, server_default="2026")
        data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
        created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
        updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

        user: Mapped[User] = relationship("User", back_populates="profiles")

    class AuditLog(Base):
        """Append-only audit log for API and assistant actions."""

        __tablename__ = "audit_log"
        __table_args__ = (
            Index("idx_audit_request", "request_id"),
            Index("idx_audit_user", "user_id"),
        )

        id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
        request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
        user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
        action: Mapped[str] = mapped_column(String(50), nullable=False)
        input: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
        output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
        created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

except ModuleNotFoundError:
    class User:  # type: ignore[no-redef]
        """Fallback model marker when SQLAlchemy is not installed."""

        __tablename__ = "users"

    class Profile:  # type: ignore[no-redef]
        """Fallback model marker when SQLAlchemy is not installed."""

        __tablename__ = "profiles"

    class AuditLog:  # type: ignore[no-redef]
        """Fallback model marker when SQLAlchemy is not installed."""

        __tablename__ = "audit_log"
