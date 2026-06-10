"""M3.3: LLM natural-language response generation.

Turns the structured engine/KB answer into a friendly natural-language
reply. The structured answer is never replaced — the LLM text is an
additive ``answer_text`` field, and any LLM failure means the caller
simply keeps the M2 template response.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger("taxglobal.orchestrator")

_MAX_RESPONSE_TOKENS = 512

_RESPONSE_SYSTEM_PROMPT = """\
You are the assistant for TaxGlobal AI, a US tax calculation product.
You will receive the user's question, the tax engine's exact structured
result (ENGINE_RESULT), and source citations (SOURCES). Write a short,
friendly answer following ALL of these rules:

1. Every dollar amount MUST be copied verbatim from ENGINE_RESULT —
   never round, never recompute, never invent a number.
2. Mention the sources from SOURCES so the user can verify.
3. Answer in the same language as the user's question (Chinese question
   gets a Chinese answer).
4. Do NOT give investment, insurance, or financial-planning advice.
5. Do NOT use absolute words like "guaranteed" / "保证" / "一定".
6. Keep the answer under 200 words.

Respond with plain text only — no markdown headers, no JSON.
"""


def llm_format_response(query: str, answer: dict, sources: list[str]) -> str | None:
    """Generate a natural-language answer from the structured engine result.

    Returns the generated text on success, ``None`` on any failure so the
    caller keeps the M2 template response.
    """

    from backend.llm.client import get_provider
    from backend.llm.provider import LLMMessage

    provider = get_provider()
    if provider is None:
        return None

    try:
        answer_json = json.dumps(answer, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        logger.warning("Engine answer not JSON-serializable, skipping LLM response")
        return None

    user_content = (
        f"QUESTION:\n{query}\n\n"
        f"ENGINE_RESULT:\n{answer_json}\n\n"
        f"SOURCES:\n{json.dumps(sources, ensure_ascii=False)}"
    )
    messages = [
        LLMMessage(role="system", content=_RESPONSE_SYSTEM_PROMPT),
        LLMMessage(role="user", content=user_content),
    ]

    try:
        response = provider.complete(messages, temperature=0.2, max_tokens=_MAX_RESPONSE_TOKENS)
    except Exception:
        logger.exception("LLM provider.complete() failed, keeping template response")
        return None
    if response is None:
        return None

    text = response.content if isinstance(response.content, str) else ""
    text = text.strip()
    if not text:
        # Do not log response content — it may echo user-provided PII.
        logger.warning("LLM returned empty response text (model=%s)", response.model)
        return None
    return text
