"""FastAPI routes for the e-commerce connectors (sandbox-first)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from .base import ConnectorNotConfigured
from .nexus_bridge import evaluate_connector_nexus
from .registry import get_connector, list_connectors

router = APIRouter()


class ConnectorNexusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tax_year: int = 2026
    sandbox: bool = True


@router.get("/api/connectors")
def get_connectors() -> dict[str, object]:
    """List available connectors with facilitator + configured status."""

    return {"connectors": list_connectors()}


@router.post("/api/connectors/{platform}/nexus")
def connector_nexus(platform: str, request: ConnectorNexusRequest) -> dict[str, object]:
    """Fetch sales (sandbox by default) and evaluate economic nexus per state."""

    try:
        connector = get_connector(platform)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        result = connector.fetch_sales(sandbox=request.sandbox)
    except ConnectorNotConfigured as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return evaluate_connector_nexus(result, tax_year=request.tax_year)


@router.get("/api/connectors/{platform}/authorize")
def connector_authorize(platform: str) -> dict[str, object]:
    """Return the OAuth authorize redirect URL, or an honest not-configured notice."""

    try:
        connector = get_connector(platform)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not connector.configured:
        return {
            "platform": platform,
            "configured": False,
            "authorize_url": None,
            "detail": "OAuth not configured; set the platform credentials to enable the live authorize redirect.",
        }
    return {"platform": platform, "configured": True, "authorize_url": connector.authorize_url()}
