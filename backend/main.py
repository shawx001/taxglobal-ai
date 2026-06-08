from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections.abc import Callable, Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from backend.errors import error_response
from backend.routes.calc import router as calc_router
from engine.rules_loader import RuleLoadError, load_rule_file

logger = logging.getLogger("taxglobal.api")
logging.basicConfig(level=logging.INFO, format="%(message)s")

DEFAULT_DEV_CORS_ORIGINS = [
    "http://127.0.0.1",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8000",
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8000",
]

DEFAULT_TAX_YEAR = 2026
STATE_NAMES = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "DC": "District of Columbia",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
}


def _cors_origins() -> list[str]:
    configured = os.environ.get("TAXGLOBAL_CORS_ORIGINS")
    if configured is not None:
        origins = [origin.strip() for origin in configured.split(",") if origin.strip()]
        if origins:
            return origins
    return DEFAULT_DEV_CORS_ORIGINS


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Response]) -> Response:
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.info(
                json.dumps(
                    {
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": status_code,
                        "duration_ms": duration_ms,
                        "request_id": request_id,
                    },
                    separators=(",", ":"),
                )
            )
            if "response" in locals():
                response.headers["X-Request-ID"] = request_id


def create_app() -> FastAPI:
    app = FastAPI(title="TaxGlobal AI API", version="0.1.0")
    # Dev default allows local frontend origins; production should set TAXGLOBAL_CORS_ORIGINS explicitly.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    app.add_middleware(RequestIdMiddleware)
    app.include_router(calc_router)

    @app.get("/api/states", response_model=None)
    def get_available_states(request: Request, tax_year: int = DEFAULT_TAX_YEAR) -> dict[str, Any] | JSONResponse:
        """Return all available states for the given tax year."""

        try:
            states_data = load_rule_file(tax_year, "us_states.json")
        except RuleLoadError:
            return JSONResponse(
                status_code=422,
                content=error_response(
                    code="unsupported_tax_year",
                    message=f"Tax year {tax_year} is not supported yet.",
                    request_id=str(getattr(request.state, "request_id", "unknown")),
                ),
            )
        states_block = states_data.get("states", {})
        if not isinstance(states_block, Mapping):
            states_block = {}
        result = []
        for code in sorted(states_block):
            state = states_block[code]
            result.append(
                {
                    "code": code,
                    "name": STATE_NAMES.get(code, code),
                    "income_tax_type": state.get("income_tax_type", "unknown"),
                }
            )
        return {"tax_year": tax_year, "states": result}

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = str(getattr(request.state, "request_id", "unknown"))
        return JSONResponse(
            status_code=422,
            headers={"X-Request-ID": request_id},
            content=error_response(
                code="validation_error",
                message="Request validation failed.",
                request_id=request_id,
                # Keep only JSON-safe, PII-free fields: drop `input` (echoes sensitive
                # income values) and `ctx` (may hold non-serializable exception objects).
                details=[{k: v for k, v in err.items() if k in ("type", "loc", "msg")} for err in exc.errors()],
            ),
        )

    @app.exception_handler(Exception)
    async def internal_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = str(getattr(request.state, "request_id", "unknown"))
        logger.error(
            json.dumps(
                {
                    "event": "internal_error",
                    "path": request.url.path,
                    "request_id": request_id,
                    "error_type": exc.__class__.__name__,
                },
                separators=(",", ":"),
            )
        )
        return JSONResponse(
            status_code=500,
            headers={"X-Request-ID": request_id},
            content=error_response(
                code="internal_error",
                message="Internal server error.",
                request_id=request_id,
            ),
        )

    return app


app = create_app()
