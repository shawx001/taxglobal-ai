"""Audit logging middleware for selected API routes."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import parse_qs

from backend.audit.logger import log_action


def _should_audit(path: str) -> bool:
    return (
        path == "/api/skills"
        or path.startswith("/api/skills/")
        or path.startswith("/api/assistant/")
        or path == "/api/tips"
        or path.startswith("/api/admin/audit")
    )


def _extract_action(method: str, path: str) -> str:
    if path == "/api/skills":
        return "skill:list"
    if path.startswith("/api/skills/"):
        skill_name = path.removeprefix("/api/skills/").split("/", 1)[0]
        return f"skill:{skill_name}" if skill_name else "skill:unknown"
    if path.startswith("/api/assistant/"):
        return "assistant:query"
    if path == "/api/tips":
        return "tips:list"
    if path.startswith("/api/admin/audit"):
        return "admin:audit:list"
    return f"{method.lower()}:{path}"


class AuditMiddleware:
    """Capture sanitized request/response payloads for compliance audit logs."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))
        if not _should_audit(path):
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method", "GET")).upper()
        request_chunks: list[bytes] = []
        response_chunks: list[bytes] = []

        async def audit_receive() -> dict[str, Any]:
            message = await receive()
            if method in {"POST", "PUT", "PATCH"} and message.get("type") == "http.request":
                body = message.get("body", b"")
                if isinstance(body, bytes):
                    request_chunks.append(body)
            return message

        async def audit_send(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.body":
                chunk = message.get("body", b"")
                if isinstance(chunk, bytes):
                    response_chunks.append(chunk)
            await send(message)

        await self.app(scope, audit_receive, audit_send)

        _schedule_log(
            scope=scope,
            method=method,
            path=path,
            request_body=b"".join(request_chunks),
            query_string=scope.get("query_string", b""),
            response_body=b"".join(response_chunks),
        )


def _json_payload(raw_body: bytes) -> dict[str, Any] | None:
    if not raw_body:
        return None
    try:
        parsed = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if isinstance(parsed, dict):
        return parsed
    return {"value": parsed}


def _schedule_log(
    *,
    scope: dict[str, Any],
    method: str,
    path: str,
    request_body: bytes,
    query_string: bytes,
    response_body: bytes,
) -> None:
    request_payload = _request_payload(method, request_body, query_string)
    response_payload = _response_payload(path, response_body)
    state = scope.get("state") or {}
    request_id = str(state.get("request_id", "unknown"))
    try:
        asyncio.create_task(
            log_action(
                request_id=request_id,
                user_id=_extract_user_id(request_payload),
                action=_extract_action(method, path),
                request_payload=request_payload,
                response_payload=response_payload,
            )
        )
    except RuntimeError:
        return


def _request_payload(method: str, request_body: bytes, query_string: bytes) -> dict[str, Any] | None:
    if method in {"POST", "PUT", "PATCH"}:
        return _json_payload(request_body)
    if not query_string:
        return None
    try:
        parsed = parse_qs(query_string.decode("utf-8"), keep_blank_values=True)
    except UnicodeDecodeError:
        return None
    return {key: values[0] if len(values) == 1 else values for key, values in parsed.items()}


def _response_payload(path: str, response_body: bytes) -> dict[str, Any] | None:
    payload = _json_payload(response_body)
    if path.startswith("/api/admin/audit") and payload is not None:
        records = payload.get("records")
        count = len(records) if isinstance(records, list) else payload.get("count")
        return {"audit_query_count": count}
    return payload


def _extract_user_id(payload: dict[str, Any] | None) -> str | None:
    if not payload:
        return None
    user_id = payload.get("user_id")
    if isinstance(user_id, str) and user_id:
        return user_id
    return None
