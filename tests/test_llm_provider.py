"""Tests for the M3.1 LLM provider abstraction."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.llm.provider import LLMMessage, MockProvider, create_provider
from backend.llm.sanitize_pipeline import SanitizedProvider, sanitize_kwargs, sanitize_messages, sanitize_text


class TestMockProvider(unittest.TestCase):
    def test_complete_default(self) -> None:
        mock = MockProvider(default_response="Hello!")
        resp = mock.complete([LLMMessage(role="user", content="Hi")])
        self.assertIsNotNone(resp)
        assert resp is not None
        self.assertEqual(resp.content, "Hello!")
        self.assertEqual(resp.model, "mock")

    def test_complete_queued(self) -> None:
        mock = MockProvider()
        mock.enqueue("First")
        mock.enqueue("Second")
        first = mock.complete([])
        second = mock.complete([])
        fallback = mock.complete([])
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertIsNotNone(fallback)
        assert first is not None and second is not None and fallback is not None
        self.assertEqual(first.content, "First")
        self.assertEqual(second.content, "Second")
        self.assertEqual(fallback.content, "Mock LLM response.")

    def test_stream(self) -> None:
        mock = MockProvider(default_response="word1 word2 word3")
        tokens = list(mock.stream([LLMMessage(role="user", content="test")]))
        self.assertEqual(tokens, ["word1 ", "word2 ", "word3 "])

    def test_is_available(self) -> None:
        self.assertTrue(MockProvider().is_available())


class TestSanitizeText(unittest.TestCase):
    def test_ssn_masked(self) -> None:
        text = "My SSN is 123-45-6789 and I earned $150,000."
        result = sanitize_text(text)
        self.assertIn("***-**-6789", result)
        self.assertNotIn("123-45", result)
        self.assertIn("$150,000", result)

    def test_labeled_ssn_masked(self) -> None:
        text = "SSN: 123456789"
        result = sanitize_text(text)
        self.assertIn("***-**-6789", result)
        self.assertNotIn("123456789", result)

    def test_bare_nine_digit_ssn_masked(self) -> None:
        text = "My number is 123456789 and income was $200,000."
        result = sanitize_text(text)
        self.assertIn("***-**-6789", result)
        self.assertNotIn("123456789", result)
        self.assertIn("$200,000", result)

    def test_email_masked(self) -> None:
        text = "Contact me at john.doe@example.com for details."
        result = sanitize_text(text)
        self.assertIn("[email redacted]", result)
        self.assertNotIn("john.doe@example.com", result)

    def test_no_pii_unchanged(self) -> None:
        text = "What is the standard deduction for 2025?"
        self.assertEqual(sanitize_text(text), text)

    def test_dollar_amounts_preserved(self) -> None:
        text = "I made $200,000 in California with SSN 123-45-6789."
        result = sanitize_text(text)
        self.assertIn("$200,000", result)
        self.assertNotIn("123-45-6789", result)

    def test_sanitize_messages_returns_new_messages(self) -> None:
        messages = [LLMMessage(role="user", content="email me at jane@example.com")]
        sanitized = sanitize_messages(messages)
        self.assertIsNot(messages[0], sanitized[0])
        self.assertEqual(sanitized[0].content, "email me at [email redacted]")

    def test_sanitize_kwargs_recurses_without_redacting_schema_names(self) -> None:
        sanitized = sanitize_kwargs(
            {
                "metadata": {
                    "notes": "email jane@example.com and SSN 123-45-6789",
                    "nested": [{"phone": "415-555-1212"}],
                },
                "tools": [{"function": {"name": "calculate_income_tax"}}],
                "response_format": {"json_schema": {"name": "intent_schema"}},
            }
        )
        metadata = sanitized["metadata"]
        self.assertNotIn("jane@example.com", metadata["notes"])
        self.assertNotIn("123-45-6789", metadata["notes"])
        self.assertEqual(metadata["nested"][0]["phone"], "415-555-1212")
        self.assertEqual(sanitized["tools"][0]["function"]["name"], "calculate_income_tax")
        self.assertEqual(sanitized["response_format"]["json_schema"]["name"], "intent_schema")


class TestSanitizedProvider(unittest.TestCase):
    def test_sanitizes_before_complete(self) -> None:
        captured: list[LLMMessage] = []
        captured_kwargs: dict = {}

        class SpyProvider(MockProvider):
            def complete(self, messages, **kwargs):
                captured.extend(messages)
                captured_kwargs.update(kwargs)
                return super().complete(messages, **kwargs)

        provider = SanitizedProvider(SpyProvider())
        provider.complete(
            [LLMMessage(role="user", content="SSN is 123-45-6789")],
            user={"email": "jane@example.com"},
            metadata={"notes": "email jane@example.com"},
        )
        self.assertTrue(captured)
        self.assertNotIn("123-45-6789", captured[0].content)
        self.assertIn("***-**-6789", captured[0].content)
        self.assertEqual(captured_kwargs["user"]["email"], "[email redacted]")
        self.assertNotIn("jane@example.com", captured_kwargs["metadata"]["notes"])

    def test_sanitizes_before_stream(self) -> None:
        captured: list[LLMMessage] = []

        class SpyProvider(MockProvider):
            def stream(self, messages, **kwargs):
                captured.extend(messages)
                yield from super().stream(messages, **kwargs)

        provider = SanitizedProvider(SpyProvider(default_response="ok"))
        self.assertEqual(list(provider.stream([LLMMessage(role="user", content="me@example.com")])), ["ok "])
        self.assertEqual(captured[0].content, "[email redacted]")


class TestCreateProvider(unittest.TestCase):
    def test_mock_provider(self) -> None:
        provider = create_provider(provider_name="mock", api_key="", model="")
        self.assertIsInstance(provider, MockProvider)


class TestClientModule(unittest.TestCase):
    def test_disabled_by_default(self) -> None:
        from backend import config
        from backend.llm import client

        original = config.ENABLE_LLM
        try:
            config.ENABLE_LLM = False
            client.init_llm()
            self.assertIsNone(client.get_provider())
            self.assertFalse(client.is_llm_available())
        finally:
            client.close_llm()
            config.ENABLE_LLM = original

    def test_mock_provider_via_config(self) -> None:
        from backend import config
        from backend.llm import client

        originals = (config.ENABLE_LLM, config.LLM_PROVIDER, config.LLM_API_KEY)
        try:
            config.ENABLE_LLM = True
            config.LLM_PROVIDER = "mock"
            config.LLM_API_KEY = "test"
            client.init_llm()
            self.assertTrue(client.is_llm_available())
            provider = client.get_provider()
            self.assertIsNotNone(provider)
            assert provider is not None
            resp = provider.complete([LLMMessage(role="user", content="test")])
            self.assertIsNotNone(resp)
        finally:
            client.close_llm()
            config.ENABLE_LLM, config.LLM_PROVIDER, config.LLM_API_KEY = originals

    def test_external_provider_is_wrapped_with_sanitizer(self) -> None:
        from backend import config
        from backend.llm import client

        originals = (config.ENABLE_LLM, config.LLM_PROVIDER, config.LLM_API_KEY, config.LLM_BASE_URL, config.LLM_MODEL)
        try:
            config.ENABLE_LLM = True
            config.LLM_PROVIDER = "deepseek"
            config.LLM_API_KEY = "test"
            config.LLM_BASE_URL = ""
            config.LLM_MODEL = ""
            with patch("backend.llm.client.create_provider", return_value=MockProvider()) as create:
                client.init_llm()
            self.assertTrue(client.is_llm_available())
            create.assert_called_once()
            self.assertEqual(create.call_args.kwargs["base_url"], "https://api.deepseek.com")
            self.assertEqual(create.call_args.kwargs["model"], "deepseek-chat")
        finally:
            client.close_llm()
            (
                config.ENABLE_LLM,
                config.LLM_PROVIDER,
                config.LLM_API_KEY,
                config.LLM_BASE_URL,
                config.LLM_MODEL,
            ) = originals


if __name__ == "__main__":
    unittest.main()
