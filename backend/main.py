from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from backend.errors import error_response
from backend.routes.calc import router as calc_router

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


def _cors_origins() -> list[str]:
    configured = os.environ.get("TAXGLOBAL_CORS_ORIGINS")
    if configured:
        return [origin.strip() for origin in configured.split(",") if origin.strip()]
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
                details=exc.errors(),
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
