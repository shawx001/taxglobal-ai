"""Tests for M3.6 W-2 vision extraction."""

from __future__ import annotations

import base64
import json
import logging
import unittest

from starlette.testclient import TestClient

from backend.llm.vision import (
    MockVisionExtractor,
    extract_w2_fields,
    set_mock_extractor,
    validate_image,
)
from backend.main import create_app

_TINY_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n fake-image-bytes").decode("ascii")


def _w2_json(**overrides) -> str:
    payload = {
        "box1": "85000.00",
        "box2": "9200.50",
        "box3": "85000.00",
        "box4": "5270.00",
        "box5": "85000.00",
        "box6": "1232.50",
        "box15_state": "CA",
        "box16": "85000.00",
        "box17": "3100.00",
        "confidence": {
            "box1": 0.98, "box2": 0.97, "box3": 0.96, "box4": 0.95,
            "box5": 0.96, "box6": 0.95, "box15_state": 0.99,
            "box16": 0.9, "box17": 0.88,
        },
    }
    payload.update(overrides)
    return json.dumps(payload)


class TestVisionExtraction(unittest.TestCase):
    def tearDown(self) -> None:
        set_mock_extractor(None)

    def _install(self, response: str) -> None:
        extractor = MockVisionExtractor()
        extractor.enqueue(response)
        set_mock_extractor(extractor)

    def test_extracts_all_boxes(self) -> None:
        self._install(_w2_json())
        result = extract_w2_fields(_TINY_PNG, "image/png")
        self.assertIsNotNone(result)
        fields = result["fields"]
        self.assertEqual(fields["box1"]["value"], "85000.00")
        self.assertEqual(fields["box2"]["value"], "9200.50")
        self.assertEqual(fields["box15_state"]["value"], "CA")
        self.assertEqual(fields["box17"]["value"], "3100.00")
        self.assertGreaterEqual(fields["box1"]["confidence"], 0.9)

    def test_amounts_are_decimal_strings_not_floats(self) -> None:
        self._install(_w2_json(box1=85000.555))  # model returned a float
        result = extract_w2_fields(_TINY_PNG, "image/png")
        value = result["fields"]["box1"]["value"]
        self.assertIsInstance(value, str)
        self.assertEqual(value, "85000.56")  # explicit ROUND_HALF_UP

    def test_missing_box_is_null_with_zero_confidence(self) -> None:
        self._install(_w2_json(box2=None))
        result = extract_w2_fields(_TINY_PNG, "image/png")
        self.assertIsNone(result["fields"]["box2"]["value"])
        self.assertEqual(result["fields"]["box2"]["confidence"], 0.0)

    def test_non_numeric_amount_is_null(self) -> None:
        self._install(_w2_json(box1="eighty five thousand"))
        result = extract_w2_fields(_TINY_PNG, "image/png")
        self.assertIsNone(result["fields"]["box1"]["value"])

    def test_negative_and_absurd_amounts_rejected(self) -> None:
        self._install(_w2_json(box1="-5", box2="999999999999"))
        result = extract_w2_fields(_TINY_PNG, "image/png")
        self.assertIsNone(result["fields"]["box1"]["value"])
        self.assertIsNone(result["fields"]["box2"]["value"])

    def test_dollar_and_comma_formatting_cleaned(self) -> None:
        self._install(_w2_json(box1="$85,000.00"))
        result = extract_w2_fields(_TINY_PNG, "image/png")
        self.assertEqual(result["fields"]["box1"]["value"], "85000.00")

    def test_invalid_state_code_nulled(self) -> None:
        self._install(_w2_json(box15_state="California"))
        result = extract_w2_fields(_TINY_PNG, "image/png")
        self.assertIsNone(result["fields"]["box15_state"]["value"])

    def test_invalid_json_returns_none(self) -> None:
        self._install("The W-2 shows wages of $85,000")
        self.assertIsNone(extract_w2_fields(_TINY_PNG, "image/png"))

    def test_non_dict_json_returns_none(self) -> None:
        self._install("[]")
        self.assertIsNone(extract_w2_fields(_TINY_PNG, "image/png"))

    def test_nan_confidence_clamped_to_zero(self) -> None:
        self._install(_w2_json(confidence={"box1": "nan"}))
        result = extract_w2_fields(_TINY_PNG, "image/png")
        self.assertEqual(result["fields"]["box1"]["confidence"], 0.0)

    def test_extractor_returning_none_propagates_none(self) -> None:
        set_mock_extractor(MockVisionExtractor())  # empty queue, no default
        self.assertIsNone(extract_w2_fields(_TINY_PNG, "image/png"))

    def test_logs_never_contain_extracted_values(self) -> None:
        self._install("not json $85,000 SSN 123-45-6789")
        logger = logging.getLogger("taxglobal.llm")
        with self.assertLogs(logger, level=logging.WARNING) as logs:
            extract_w2_fields(_TINY_PNG, "image/png")
        joined = "\n".join(logs.output)
        self.assertNotIn("85,000", joined)
        self.assertNotIn("123-45-6789", joined)
        self.assertNotIn(_TINY_PNG[:16], joined)


class TestValidateImage(unittest.TestCase):
    def test_valid_image_passes(self) -> None:
        self.assertIsNone(validate_image(_TINY_PNG, "image/png"))

    def test_unsupported_media_type(self) -> None:
        self.assertEqual(validate_image(_TINY_PNG, "image/gif"), "unsupported_media_type")

    def test_invalid_base64(self) -> None:
        self.assertEqual(validate_image("not-base64!!!", "image/png"), "invalid_base64")

    def test_empty_image(self) -> None:
        self.assertEqual(validate_image("", "image/png"), "empty_image")

    def test_oversized_image(self) -> None:
        big = base64.b64encode(b"x" * (8 * 1024 * 1024 + 1)).decode("ascii")
        self.assertEqual(validate_image(big, "image/png"), "image_too_large")


class TestExtractW2Route(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(create_app())

    def tearDown(self) -> None:
        set_mock_extractor(None)

    def test_route_returns_fields(self) -> None:
        extractor = MockVisionExtractor()
        extractor.enqueue(_w2_json())
        set_mock_extractor(extractor)
        response = self.client.post(
            "/api/documents/extract-w2",
            json={"image_base64": _TINY_PNG, "media_type": "image/png"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["fields"]["box1"]["value"], "85000.00")

    def test_route_503_when_vision_unconfigured(self) -> None:
        # No mock extractor + default config (no VISION_MODEL) → unavailable.
        response = self.client.post(
            "/api/documents/extract-w2",
            json={"image_base64": _TINY_PNG, "media_type": "image/png"},
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "vision_unavailable")

    def test_route_422_on_bad_media_type(self) -> None:
        set_mock_extractor(MockVisionExtractor(default_response=_w2_json()))
        response = self.client.post(
            "/api/documents/extract-w2",
            json={"image_base64": _TINY_PNG, "media_type": "application/pdf"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "invalid_image")

    def test_route_502_on_extraction_failure(self) -> None:
        set_mock_extractor(MockVisionExtractor(default_response="not json"))
        response = self.client.post(
            "/api/documents/extract-w2",
            json={"image_base64": _TINY_PNG, "media_type": "image/png"},
        )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "extraction_failed")

    def test_route_rejects_empty_body(self) -> None:
        response = self.client.post("/api/documents/extract-w2", json={"image_base64": ""})
        self.assertEqual(response.status_code, 422)

    def test_skill_registered(self) -> None:
        from backend.skills.registry import get_skill

        skill = get_skill("extract_w2")
        self.assertIsNotNone(skill)
        self.assertEqual(skill.engine_function_name, "extract_w2_fields")

    def test_audit_capture_redacts_image_base64(self) -> None:
        """W-2 images must never land in the audit store (PII at rest)."""
        from backend.audit.middleware import _request_payload

        body = json.dumps({"image_base64": _TINY_PNG, "media_type": "image/png"}).encode("utf-8")
        payload = _request_payload("POST", body, b"")
        self.assertEqual(payload["image_base64"], "[image redacted]")
        self.assertNotIn(_TINY_PNG, json.dumps(payload))

    def test_sanitizer_redacts_nested_image_base64(self) -> None:
        """Belt-and-suspenders: nested images are redacted at the audit
        sanitizer (the middleware fast-path only checks the top level)."""
        from backend.audit.sanitizer import sanitize_payload

        sanitized = sanitize_payload({"params": {"image_base64": _TINY_PNG}})
        self.assertNotIn(_TINY_PNG, json.dumps(sanitized))

    def test_skills_route_does_not_expose_extract_w2(self) -> None:
        """Vision output is not engine truth — the guardrailed generic route
        must neither list nor invoke it (it would always be blocked)."""
        listing = self.client.get("/api/skills").json()
        self.assertNotIn("extract_w2", {skill["name"] for skill in listing["skills"]})
        response = self.client.post(
            "/api/skills/extract_w2", json={"image_base64": _TINY_PNG, "media_type": "image/png"}
        )
        self.assertEqual(response.status_code, 404)

    def test_amount_comma_decimal_rejected(self) -> None:
        """'85000,50' (comma-decimal misread) must be rejected, not 8500050."""
        from backend.llm.vision import _clean_amount

        self.assertIsNone(_clean_amount("85000,50"))
        self.assertIsNone(_clean_amount("85.000,50"))
        self.assertEqual(_clean_amount("85,000.50"), "85000.50")

    def test_amount_rounding_is_half_up(self) -> None:
        """Repo standard ROUND_HALF_UP: .125 → .13 (HALF_EVEN would give .12)."""
        from backend.llm.vision import _clean_amount

        self.assertEqual(_clean_amount("85000.125"), "85000.13")

    def test_leading_zero_integer_rejected_as_identifier(self) -> None:
        from backend.llm.vision import _clean_amount

        self.assertIsNone(_clean_amount("012345678"))
        self.assertEqual(_clean_amount("0.50"), "0.50")

    def test_negative_zero_normalized(self) -> None:
        from backend.llm.vision import _clean_amount

        self.assertEqual(_clean_amount("-0"), "0.00")

    def test_oversized_base64_rejected_without_decoding(self) -> None:
        from backend.llm.vision import MAX_IMAGE_BYTES, validate_image

        huge = "A" * (MAX_IMAGE_BYTES * 4 // 3 + 100)
        self.assertEqual(validate_image(huge, "image/png"), "image_too_large")


_MINIMAL_PDF = base64.b64encode(
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n"
).decode("ascii")


class TestPdfSupport(unittest.TestCase):
    """W-2 PDFs: page 1 renders to PNG before vision extraction."""

    def tearDown(self) -> None:
        set_mock_extractor(None)

    def test_pdf_media_type_accepted_by_validation(self) -> None:
        self.assertIsNone(validate_image(_MINIMAL_PDF, "application/pdf"))

    def test_non_pdf_bytes_with_pdf_media_type_rejected(self) -> None:
        self.assertEqual(validate_image(_TINY_PNG, "application/pdf"), "invalid_pdf")

    def test_pdf_first_page_renders_to_png(self) -> None:
        from backend.llm.vision import pdf_first_page_to_png

        rendered = pdf_first_page_to_png(_MINIMAL_PDF)
        self.assertIsNotNone(rendered)
        self.assertTrue(base64.b64decode(rendered).startswith(b"\x89PNG"))

    def test_corrupt_pdf_render_returns_none(self) -> None:
        from backend.llm.vision import pdf_first_page_to_png

        corrupt = base64.b64encode(b"%PDF-1.4 garbage no objects").decode("ascii")
        self.assertIsNone(pdf_first_page_to_png(corrupt))

    def test_skill_converts_pdf_before_extraction(self) -> None:
        """The vision model must receive a PNG, never the raw PDF."""
        from backend.llm import vision
        from backend.skills.registry import get_skill

        captured = {}

        class CapturingExtractor(MockVisionExtractor):
            def complete_vision(self, image_base64: str, media_type: str) -> str | None:
                captured["media_type"] = media_type
                captured["is_png"] = base64.b64decode(image_base64).startswith(b"\x89PNG")
                return _w2_json()

        vision.set_mock_extractor(CapturingExtractor())
        result = get_skill("extract_w2").invoke(
            {"image_base64": _MINIMAL_PDF, "media_type": "application/pdf"}
        )
        self.assertEqual(result["result"]["status"], "ok")
        self.assertEqual(captured["media_type"], "image/png")
        self.assertTrue(captured["is_png"])

    def test_route_accepts_pdf(self) -> None:
        extractor = MockVisionExtractor()
        extractor.enqueue(_w2_json())
        set_mock_extractor(extractor)
        client = TestClient(create_app())
        response = client.post(
            "/api/documents/extract-w2",
            json={"image_base64": _MINIMAL_PDF, "media_type": "application/pdf"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["fields"]["box1"]["value"], "85000.00")

    def test_route_rejects_corrupt_pdf(self) -> None:
        set_mock_extractor(MockVisionExtractor(default_response=_w2_json()))
        client = TestClient(create_app())
        corrupt = base64.b64encode(b"%PDF-1.4 garbage no objects").decode("ascii")
        response = client.post(
            "/api/documents/extract-w2",
            json={"image_base64": corrupt, "media_type": "application/pdf"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["message"], "pdf_render_failed")


if __name__ == "__main__":
    unittest.main()
