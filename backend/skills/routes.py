"""FastAPI routes for Skill discovery and invocation."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from backend.errors import error_response
from backend.skills.registry import get_all_skills, get_skill
from engine.rules_loader import RuleLoadError

router = APIRouter(prefix="/api/skills", tags=["skills"])


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unknown"))


def _safe_validation_details(exc: ValidationError) -> list[dict[str, Any]]:
    return [{key: value for key, value in err.items() if key in ("type", "loc", "msg")} for err in exc.errors()]


@router.get("")
def list_skills() -> dict[str, Any]:
    """List all available tax calculation skills with input schemas."""

    skills = get_all_skills()
    return {
        "skills": [
            {
                "name": skill.name,
                "description": skill.description,
                "input_schema": skill.args_schema.model_json_schema() if skill.args_schema else {},
            }
            for skill in skills
        ],
        "total": len(skills),
    }


@router.post("/{skill_name}", response_model=None)
def invoke_skill(skill_name: str, request: Request, body: dict[str, Any]) -> dict[str, Any] | JSONResponse:
    """Invoke a registered Skill by name."""

    skill = get_skill(skill_name)
    request_id = _request_id(request)
    if skill is None:
        return JSONResponse(
            status_code=404,
            headers={"X-Request-ID": request_id},
            content=error_response(
                code="skill_not_found",
                message=f"Skill '{skill_name}' not found.",
                request_id=request_id,
            ),
        )

    try:
        result = skill.invoke(body)
        if result.get("status") == "invalid_input":
            return JSONResponse(
                status_code=422,
                headers={"X-Request-ID": request_id},
                content=error_response(
                    code="invalid_input",
                    message=result.get("result", {}).get("reason") or "Invalid input.",
                    request_id=request_id,
                ),
            )
        return result
    except RuleLoadError:
        tax_year = body.get("tax_year", "requested")
        return JSONResponse(
            status_code=422,
            headers={"X-Request-ID": request_id},
            content=error_response(
                code="unsupported_tax_year",
                message=f"Tax year {tax_year} is not supported yet.",
                request_id=request_id,
            ),
        )
    except ValidationError as exc:
        return JSONResponse(
            status_code=422,
            headers={"X-Request-ID": request_id},
            content=error_response(
                code="validation_error",
                message="Request validation failed.",
                request_id=request_id,
                details=_safe_validation_details(exc),
            ),
        )
