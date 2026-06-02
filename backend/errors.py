from __future__ import annotations

from typing import Any


def error_response(
    *,
    code: str,
    message: str,
    request_id: str,
    details: list[Any] | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
            "details": details or [],
        }
    }
