"""FastAPI routes for the e-commerce connectors (sandbox-first).

Errors use the API-wide ``error_response`` envelope with an ``X-Request-ID``
header, matching backend/routes/calc.py, instead of FastAPI's default
``{detail: ...}``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from backend.errors import error_response
from engine.rules_loader import RuleLoadError

from .base import ConnectorNotConfigured
from .nexus_bridge import evaluate_connector_nexus
from .registry import get_connector, list_connectors

router = APIRouter()


class ConnectorNexusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tax_year: int = 2026
    sandbox: bool = True


def _request_id(request: Request) -> str:
    return str(request.state.request_id)


def _error(request: Request, *, status_code: int, code: str, message: str) -> JSONResponse:
    rid = _request_id(request)
    return JSONResponse(
        status_code=status_code,
        headers={"X-Request-ID": rid},
        content=error_response(code=code, message=message, request_id=rid),
    )


@router.get("/api/connectors")
def get_connectors() -> dict[str, object]:
    """List available connectors with facilitator + configured status."""

    return {"connectors": list_connectors()}


@router.post("/api/connectors/{platform}/nexus", response_model=None)
def connector_nexus(platform: str, payload: ConnectorNexusRequest, request: Request) -> dict[str, Any] | JSONResponse:
    """Fetch sales (sandbox by default) and evaluate economic nexus per state."""

    try:
        connector = get_connector(platform)
    except KeyError:
        return _error(
            request,
            status_code=404,
            code="unknown_connector",
            message=f"Unknown connector platform '{platform}'.",
        )
    try:
        result = connector.fetch_sales(sandbox=payload.sandbox)
    except ConnectorNotConfigured as exc:
        return _error(request, status_code=400, code="connector_not_configured", message=str(exc))
    try:
        return evaluate_connector_nexus(result, tax_year=payload.tax_year)
    except RuleLoadError:
        return _error(
            request,
            status_code=422,
            code="unsupported_tax_year",
            message=f"Tax year {payload.tax_year} is not supported yet.",
        )


@router.get("/api/connectors/{platform}/authorize", response_model=None)
def connector_authorize(platform: str, request: Request) -> dict[str, Any] | JSONResponse:
    """Return the OAuth authorize redirect URL, or an honest not-configured notice."""

    try:
        connector = get_connector(platform)
    except KeyError:
        return _error(
            request,
            status_code=404,
            code="unknown_connector",
            message=f"Unknown connector platform '{platform}'.",
        )
    if not connector.configured:
        return {
            "platform": connector.platform,
            "configured": False,
            "authorize_url": None,
            "detail": "OAuth not configured; set the platform credentials to enable the live authorize redirect.",
        }
    try:
        authorize_url = connector.authorize_url()
    except ConnectorNotConfigured as exc:
        return _error(request, status_code=400, code="connector_not_configured", message=str(exc))
    return {"platform": connector.platform, "configured": True, "authorize_url": authorize_url}
