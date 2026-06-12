"""M3.6: document extraction routes (W-2 photo upload)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.errors import error_response

router = APIRouter(prefix="/api/documents", tags=["documents"])

# Base64 inflates ~4/3 over the 8 MB decoded cap in backend/llm/vision.py.
_MAX_BASE64_CHARS = 12 * 1024 * 1024


class ExtractW2Request(BaseModel):
    """W-2 extraction request: base64 image, never persisted."""

    image_base64: str = Field(..., min_length=1, max_length=_MAX_BASE64_CHARS)
    media_type: str = Field(default="image/jpeg")


@router.post("/extract-w2", response_model=None)
def extract_w2(request: Request, body: ExtractW2Request) -> dict[str, Any] | JSONResponse:
    """Extract W-2 box fields from an uploaded photo.

    The image lives only in this request scope: it is not stored, not
    audited, and never logged.
    """

    request_id = str(getattr(request.state, "request_id", "unknown"))

    from backend.skills.registry import get_skill

    skill = get_skill("extract_w2")
    if skill is None:
        return JSONResponse(
            status_code=503,
            content=error_response(
                code="skill_not_found", message="W-2 extraction is not available.", request_id=request_id
            ),
        )

    output = skill.invoke({"image_base64": body.image_base64, "media_type": body.media_type})
    result = output.get("result", {})
    status = result.get("status", "ok")
    if status == "vision_unavailable":
        return JSONResponse(
            status_code=503,
            content=error_response(
                code="vision_unavailable",
                message="Vision extraction is not configured on this server.",
                request_id=request_id,
            ),
        )
    if status == "invalid_input":
        return JSONResponse(
            status_code=422,
            content=error_response(
                code="invalid_image",
                message=str(result.get("reason", "The uploaded image is not usable.")),
                request_id=request_id,
            ),
        )
    if status != "ok":
        return JSONResponse(
            status_code=502,
            content=error_response(
                code="extraction_failed",
                message="The vision model could not extract W-2 fields from this image.",
                request_id=request_id,
            ),
        )
    return {
        "status": "ok",
        "fields": result.get("fields", {}),
        "source_attribution": output.get("source_attribution", ""),
        "request_id": request_id,
    }
