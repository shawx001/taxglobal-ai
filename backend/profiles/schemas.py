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
        description="Tax profile data (filing_status, income sources, deductions, etc.).",
    )
    # PII note: `data` may contain sensitive fields such as income amounts.
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
