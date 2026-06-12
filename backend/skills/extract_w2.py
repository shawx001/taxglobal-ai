"""Skill #9 extract_w2 — W-2 photo field extraction (M3.6).

Unlike calculation skills, this skill performs no tax math: it wraps the
vision extraction layer and returns field values + confidence so the
user can confirm them before any calculation runs.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from backend.skills.base import TaxSkill


class ExtractW2Input(BaseModel):
    """Input schema: a base64-encoded W-2 image."""

    # 12M chars ≈ the 8MB decoded cap × 4/3 — reject oversized payloads at
    # the schema boundary before any decoding.
    image_base64: str = Field(..., min_length=1, max_length=12 * 1024 * 1024)
    media_type: str = Field(default="image/jpeg")


class ExtractW2(TaxSkill):
    name: str = "extract_w2"
    description: str = (
        "Extract W-2 box fields (wages, withholding, state) from a photo. "
        "Returns decimal-string values with per-field confidence; performs no tax math."
    )
    args_schema: type[BaseModel] | None = ExtractW2Input
    source_attribution: ClassVar[str] = "Vision extraction (user-confirmed before calculation)"
    engine_function_name: ClassVar[str] = "extract_w2_fields"
    # Vision output is not engine truth — served only via /api/documents,
    # never through the guardrailed generic skills route.
    expose_via_api: ClassVar[bool] = False

    def _execute_engine(self, params: dict[str, Any]) -> dict[str, Any]:
        from backend.llm.vision import (
            extract_w2_fields,
            is_vision_available,
            pdf_first_page_to_png,
            validate_image,
        )

        if not is_vision_available():
            return {"status": "vision_unavailable", "reason": "Vision model is not configured."}

        image_base64 = str(params.get("image_base64", ""))
        media_type = str(params.get("media_type", "image/jpeg"))
        input_error = validate_image(image_base64, media_type)
        if input_error is not None:
            return {"status": "invalid_input", "reason": input_error}

        if media_type == "application/pdf":
            rendered = pdf_first_page_to_png(image_base64)
            if rendered is None:
                return {"status": "invalid_input", "reason": "pdf_render_failed"}
            image_base64, media_type = rendered, "image/png"

        extracted = extract_w2_fields(image_base64, media_type)
        if extracted is None:
            return {"status": "extraction_failed", "reason": "Vision model returned no usable result."}
        return {"status": "ok", **extracted}
