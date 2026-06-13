from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from backend.audit.middleware import AuditMiddleware
from backend.audit.routes import router as audit_router
from backend.errors import error_response
from backend.knowledge.search_routes import router as search_router
from backend.knowledge.tips_routes import router as tips_router
from backend.orchestrator.routes import router as orchestrator_router
from backend.profiles.routes import router as profiles_router
from backend.ratelimit import RateLimitMiddleware
from backend.routes.calc import router as calc_router
from backend.routes.documents import router as documents_router
from backend.skills.routes import router as skills_router
from engine.rules_loader import RuleLoadError, load_rule_file

logger = logging.getLogger("taxglobal.api")
logging.basicConfig(level=logging.INFO, format="%(message)s")
# SDK debug logging can dump full request payloads (including W-2 image data
# URLs) — pin these above INFO regardless of the root level.
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize optional M2 stores without making calc routes depend on them."""

    from backend.database import close_db, init_db
    from backend.knowledge.embedder import close_embedder, init_embedder
    from backend.knowledge.neo4j_client import close_neo4j, init_neo4j
    from backend.knowledge.vector_store import close_chroma, init_chroma
    from backend.llm.client import close_llm, init_llm

    await init_db()
    init_neo4j()
    init_chroma()
    init_embedder()
    init_llm()
    try:
        yield
    finally:
        close_llm()
        close_embedder()
        close_chroma()
        close_neo4j()
        await close_db()


def create_app() -> FastAPI:
    app = FastAPI(title="TaxGlobal AI API", version="0.1.0", lifespan=lifespan)
    # Middleware execution order is OUTER→INNER: RequestId → Audit → CORS →
    # RateLimit → route. RateLimit is added first so it ends up innermost —
    # request_id is already set (carried in the 429), CORS still wraps the
    # 429 (browser can read it), and the throttle fires before the route's
    # LLM calls. (Starlette wraps last-added = outermost.)
    app.add_middleware(RateLimitMiddleware)
    # Dev default allows local frontend origins; production should set TAXGLOBAL_CORS_ORIGINS explicitly.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Admin-Token"],
    )
    app.add_middleware(AuditMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.include_router(calc_router)
    app.include_router(search_router)
    app.include_router(tips_router)
    app.include_router(profiles_router)
    app.include_router(skills_router)
    app.include_router(orchestrator_router)
    app.include_router(documents_router)
    app.include_router(audit_router)

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
            if not isinstance(state, Mapping):
                state = {}
            state_name = state.get("name")
            if not isinstance(state_name, str) or not state_name:
                state_name = STATE_NAMES.get(code, code)
            result.append(
                {
                    "code": code,
                    "name": state_name,
                    "income_tax_type": state.get("income_tax_type", "unknown"),
                }
            )
        return {"tax_year": tax_year, "states": result}

    @app.get("/api/health")
    def health_check() -> dict[str, Any]:
        """Return service health including optional M2 storage status."""

        from backend.database import is_pg_available
        from backend.knowledge.embedder import is_embedder_available
        from backend.knowledge.neo4j_client import is_neo4j_available
        from backend.knowledge.vector_store import is_chroma_available
        from backend.llm.client import is_llm_available

        return {
            "status": "ok",
            "stores": {
                "postgresql": is_pg_available(),
                "neo4j": is_neo4j_available(),
                "chroma": is_chroma_available(),
                "embedder": is_embedder_available(),
                "llm": is_llm_available(),
            },
        }

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
