"""M3.6: Vision-based W-2 field extraction.

Sends a W-2 image to an OpenAI-compatible vision model and returns the
amount boxes as decimal-strings with per-field confidence. The LLM only
READS the document — every returned amount is validated through Decimal
and the user confirms values before any calculation runs.

PII rules (per docs/m3_step_plan.md M3.6):
- The image is never logged and never persisted — it exists only in the
  request scope.
- SSN / EIN / names / addresses are explicitly NOT extracted; the prompt
  forbids them and the response schema has no field for them.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import math
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from backend import config

logger = logging.getLogger("taxglobal.llm")

# Decoded image size cap (8 MB) — defends the API and the vision bill.
MAX_IMAGE_BYTES = 8 * 1024 * 1024

_ALLOWED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}

# Render scale for PDF page 1 → PNG: W-2 PDFs are letter-size; 2x gives
# the vision model legible box text without ballooning the payload.
_PDF_RENDER_SCALE = 2.0

# W-2 amount boxes we extract. box15_state is a 2-letter state code.
W2_AMOUNT_BOXES = ("box1", "box2", "box3", "box4", "box5", "box6", "box16", "box17")
W2_ALL_BOXES = W2_AMOUNT_BOXES + ("box15_state",)

_W2_SYSTEM_PROMPT = """\
You read US Form W-2 images. Extract ONLY these fields:

- box1: Wages, tips, other compensation
- box2: Federal income tax withheld
- box3: Social security wages
- box4: Social security tax withheld
- box5: Medicare wages and tips
- box6: Medicare tax withheld
- box15_state: State (two-letter code)
- box16: State wages
- box17: State income tax

Do NOT extract or mention SSN, EIN, employee or employer names, or
addresses. Respond with ONLY a JSON object, no markdown:
{"box1": "85000.00", ..., "box15_state": "CA",
 "confidence": {"box1": 0.98, ..., "box15_state": 0.99}}

Use null for any box that is empty or unreadable. Amounts are plain
decimal strings without "$" or commas.
"""


class MockVisionExtractor:
    """Deterministic extractor for tests — enqueue raw JSON responses."""

    def __init__(self, default_response: str = "") -> None:
        self._default = default_response
        self._responses: list[str] = []

    def enqueue(self, response: str) -> None:
        self._responses.append(response)

    def complete_vision(self, image_base64: str, media_type: str) -> str | None:
        _ = (image_base64, media_type)
        if self._responses:
            return self._responses.pop(0)
        return self._default or None


_mock_extractor: MockVisionExtractor | None = None


def set_mock_extractor(extractor: MockVisionExtractor | None) -> None:
    """Install a deterministic extractor (tests only)."""

    global _mock_extractor  # noqa: PLW0603
    _mock_extractor = extractor


def _vision_credentials() -> tuple[str, str | None]:
    """(api_key, base_url) for the vision provider, falling back to the
    text-LLM credentials when no dedicated vision config is set."""

    api_key = config.VISION_API_KEY or config.LLM_API_KEY
    if config.VISION_BASE_URL:
        return api_key, config.VISION_BASE_URL
    from backend.llm.client import DEEPSEEK_BASE_URL

    base_url = config.LLM_BASE_URL or (DEEPSEEK_BASE_URL if config.LLM_PROVIDER == "deepseek" else None)
    return api_key, base_url


def is_vision_available() -> bool:
    if _mock_extractor is not None:
        return True
    # Real calls need a key — the "mock" text provider has no vision path.
    api_key, _ = _vision_credentials()
    return bool(config.ENABLE_LLM and config.VISION_MODEL and api_key)


def _vision_complete(image_base64: str, media_type: str) -> str | None:
    """Send the image to the vision model; return raw response text."""

    if _mock_extractor is not None:
        return _mock_extractor.complete_vision(image_base64, media_type)

    try:
        from openai import OpenAI

        api_key, base_url = _vision_credentials()
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=config.LLM_TIMEOUT)
        response = client.chat.completions.create(
            model=config.VISION_MODEL,
            messages=[
                {"role": "system", "content": _W2_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{media_type};base64,{image_base64}"},
                        }
                    ],
                },
            ],
            temperature=0.0,
            max_tokens=512,
        )
        if response.usage is not None:
            from backend.llm.usage_tracker import record_usage

            record_usage(
                response.model or config.VISION_MODEL,
                {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                },
            )
        return response.choices[0].message.content or ""
    except Exception as exc:
        # Never log the image or any extracted content — SDK error bodies are
        # provider-controlled and can echo request fragments, so log only the
        # exception type (same precedent as main.py internal_exception_handler).
        logger.warning(
            "Vision extraction call failed (model=%s, error=%s)",
            config.VISION_MODEL,
            type(exc).__name__,
        )
        return None


def validate_image(image_base64: str, media_type: str) -> str | None:
    """Return an error code when the image input is unusable, else None."""

    if media_type not in _ALLOWED_MEDIA_TYPES:
        return "unsupported_media_type"
    # O(1) pre-check BEFORE decoding — a multi-GB payload must be rejected
    # without base64-decoding it in full.
    if len(image_base64) > MAX_IMAGE_BYTES * 4 // 3 + 4:
        return "image_too_large"
    try:
        decoded = base64.b64decode(image_base64, validate=True)
    except (binascii.Error, ValueError):
        return "invalid_base64"
    if not decoded:
        return "empty_image"
    if len(decoded) > MAX_IMAGE_BYTES:
        return "image_too_large"
    if media_type == "application/pdf" and not decoded.startswith(b"%PDF"):
        return "invalid_pdf"
    return None


def pdf_first_page_to_png(pdf_base64: str) -> str | None:
    """Render page 1 of a W-2 PDF to PNG base64 (in memory, never on disk).

    Returns ``None`` on any failure (corrupt PDF, renderer unavailable,
    oversized render) so the caller reports a structured error. W-2 forms
    live on page 1; extra pages (instructions/copies) are ignored.
    """

    try:
        import io

        import pypdfium2

        pdf_bytes = base64.b64decode(pdf_base64, validate=True)
        document = pypdfium2.PdfDocument(pdf_bytes)
        try:
            if len(document) < 1:
                return None
            page = document[0]
            bitmap = page.render(scale=_PDF_RENDER_SCALE)
            image = bitmap.to_pil()
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
        finally:
            document.close()
        png_bytes = buffer.getvalue()
        if not png_bytes or len(png_bytes) > MAX_IMAGE_BYTES:
            return None
        return base64.b64encode(png_bytes).decode("ascii")
    except Exception as exc:
        # Never log document content — type name only (PII discipline).
        logger.warning("PDF render failed (error=%s)", type(exc).__name__)
        return None


# Commas are stripped ONLY when they form valid US thousands grouping —
# "85000,50" (comma-decimal misread) must be rejected, not become 8500050.
_THOUSANDS_GROUPED = re.compile(r"^\d{1,3}(,\d{3})+(\.\d+)?$")


def _clean_amount(value: Any) -> str | None:
    """Validate an LLM-returned amount; return a decimal-string or None."""

    if value is None:
        return None
    text = str(value).strip().replace("$", "").strip()
    if not text:
        return None
    if "," in text:
        if not _THOUSANDS_GROUPED.match(text):
            return None
        text = text.replace(",", "")
    # Bare integers with a leading zero ("012345678") are identifiers
    # (leading-zero SSNs), never amounts.
    if len(text) > 1 and text.startswith("0") and "." not in text:
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    if not amount.is_finite() or amount < 0 or amount > Decimal("99999999.99"):
        return None
    if amount == 0:
        amount = Decimal("0")  # normalize -0
    return format(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def _clean_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(confidence) or confidence < 0.0 or confidence > 1.0:
        return 0.0
    return confidence


def extract_w2_fields(image_base64: str, media_type: str) -> dict[str, Any] | None:
    """Extract W-2 fields from an image.

    Returns ``{"fields": {box: {"value": str|None, "confidence": float}}}``
    on success, ``None`` on any provider/parse failure.
    """

    raw = _vision_complete(image_base64, media_type)
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        return None

    try:
        parsed = json.loads(raw.strip())
    except (json.JSONDecodeError, ValueError):
        # Never log the response — it may contain document PII.
        logger.warning("Vision response not valid JSON (model=%s, len=%d)", config.VISION_MODEL, len(raw))
        return None
    if not isinstance(parsed, dict):
        logger.warning("Vision response is not a JSON object (model=%s)", config.VISION_MODEL)
        return None

    confidences = parsed.get("confidence")
    if not isinstance(confidences, dict):
        confidences = {}

    fields: dict[str, Any] = {}
    for box in W2_AMOUNT_BOXES:
        value = _clean_amount(parsed.get(box))
        confidence = _clean_confidence(confidences.get(box)) if value is not None else 0.0
        fields[box] = {"value": value, "confidence": confidence}

    state_raw = parsed.get("box15_state")
    state = str(state_raw).strip().upper() if state_raw is not None else ""
    if len(state) == 2 and state.isascii() and state.isalpha():
        fields["box15_state"] = {
            "value": state,
            "confidence": _clean_confidence(confidences.get("box15_state")),
        }
    else:
        fields["box15_state"] = {"value": None, "confidence": 0.0}

    return {"fields": fields}
