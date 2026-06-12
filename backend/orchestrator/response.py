"""M3.3: LLM natural-language response generation.

Turns the structured engine/KB answer into a friendly natural-language
reply. The structured answer is never replaced — the LLM text is an
additive ``answer_text`` field, and any LLM failure means the caller
simply keeps the M2 template response.

NOTE: ``answer_text`` is NOT yet fact-checked against the engine output.
M3.4 adds the fact-checker guardrail; until it lands, ``ENABLE_LLM``
must stay off in production.
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

1. Every dollar amount MUST match ENGINE_RESULT exactly to the cent.
   You may add "$" and thousands separators (13200.0 -> $13,200.00),
   but never round, never recompute, never invent a number.
2. Mention the sources from SOURCES so the user can verify.
3. Answer in the same language as the user's question (Chinese question
   gets a Chinese answer).
4. Do NOT give investment, insurance, or financial-planning advice.
5. Do NOT use absolute words like "guaranteed" / "保证" / "一定".
6. Keep the answer under 200 words.

Respond with plain text only — no markdown headers, no JSON.
"""

_KNOWLEDGE_SYSTEM_PROMPT = """\
You are the assistant for TaxGlobal AI, a US tax product. The user asked
a tax-knowledge question. You will receive the question, knowledge-base
excerpts (ENGINE_RESULT, may be empty), and source citations (SOURCES).

1. If the excerpts contain relevant content, base your answer on them
   and mention the sources.
2. If the excerpts are empty or irrelevant, explain the CONCEPT from
   your general US-tax knowledge — but NEVER state any monetary figure
   (in ANY format: $130,000 / 13万美元 / 130k) or year-specific
   threshold from memory; your training data is stale and wrong figures
   harm users. Instead, tell the user you can give exact numbers if
   they ask a calculation question (e.g. include their income and state).
3. Answer in the user's language. Be clear and conversational, like a
   knowledgeable colleague — not a brochure.
4. No investment/insurance/financial-planning advice. No absolute words
   like "guaranteed" / "保证" / "一定". Under 200 words.

Respond with plain text only.
"""

_MISSING_PARAMS_SYSTEM_PROMPT = """\
You are the TaxGlobal AI tax assistant. The user asked a tax question
the rule engine CAN compute, but required inputs are missing — they are
listed in ENGINE_RESULT.missing_params.

1. FIRST answer the user's underlying question helpfully at the concept
   level (e.g. a US person working abroad: worldwide income filing,
   FEIE vs foreign tax credit, the physical-presence idea, which forms
   are involved) — like a knowledgeable colleague, not a form.
2. THEN naturally ask for the missing inputs in HUMAN terms (e.g.
   "你去年在海外住了大概多少天？年收入多少？"), explaining you can
   compute exact numbers once you have them. Do not use raw parameter
   names like w2_wages.
3. NEVER state any monetary figure from memory, in ANY format
   ($130,000 / 13万美元 / 130k) — your training data is stale; exact
   numbers only come from the engine. Statutory day counts (330 days)
   are fine.
4. Do not repeat explanations the conversation already covered — build
   on them.
5. User's language. No investment advice. No absolute promises. Under
   150 words.

Respond with plain text only.
"""

_CHAT_SYSTEM_PROMPT = """\
You are the TaxGlobal AI tax assistant — warm, natural, human. The
user's message is small talk or off-topic (ENGINE_RESULT is just a
clarification placeholder; ignore its wording).

1. Answer the user's actual message directly, in their language, the
   way a friendly human assistant would. Vary your phrasing; do NOT
   recite your feature list unless the user explicitly asks what you
   can do.
2. If the message is playful or personal ("你爱我吗"), respond briefly
   with warmth or light humor, then gently steer toward how you can
   help with US tax questions — one short sentence, not a menu.
3. Never invent tax numbers. No investment advice. No absolute promises.
4. Keep it under 80 words.

Respond with plain text only.
"""


def llm_format_response(
    query: str,
    answer: dict,
    sources: list[str],
    retry_feedback: str | None = None,
) -> str | None:
    """Generate a natural-language answer from the structured engine result.

    Returns the generated text on success, ``None`` on any failure so the
    caller keeps the M2 template response.
    """

    from backend.llm.client import get_provider
    from backend.llm.provider import LLMMessage

    provider = get_provider()
    if provider is None:
        return None

    prompt_answer = answer
    if isinstance(answer, dict) and answer.get("type") == "knowledge":
        # M3.7: cap KB chunk count/length before prompting — full chunks
        # were the main token cost. The response payload stays uncompressed.
        from backend.llm.token_optimizer import compress_knowledge_context

        prompt_answer = compress_knowledge_context(answer)

    try:
        answer_json = json.dumps(prompt_answer, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        logger.warning("Engine answer not JSON-serializable, skipping LLM response")
        return None

    answer_type = answer.get("type") if isinstance(answer, dict) else None
    if answer_type == "clarification" and answer.get("missing_params"):
        system_prompt = _MISSING_PARAMS_SYSTEM_PROMPT
        temperature = 0.4
    elif answer_type == "clarification":
        system_prompt = _CHAT_SYSTEM_PROMPT
        temperature = 0.6  # variety for small talk — no numbers involved
    elif answer_type == "knowledge":
        system_prompt = _KNOWLEDGE_SYSTEM_PROMPT
        temperature = 0.3
    else:
        system_prompt = _RESPONSE_SYSTEM_PROMPT
        temperature = 0.2

    user_content = (
        f"QUESTION:\n{query}\n\n"
        f"ENGINE_RESULT:\n{answer_json}\n\n"
        f"SOURCES:\n{json.dumps(sources, ensure_ascii=False)}"
    )
    if retry_feedback:
        user_content += f"\n\nFEEDBACK ON YOUR PREVIOUS DRAFT:\n{retry_feedback}"
    messages = [
        LLMMessage(role="system", content=system_prompt),
        LLMMessage(role="user", content=user_content),
    ]

    try:
        response = provider.complete(messages, temperature=temperature, max_tokens=_MAX_RESPONSE_TOKENS)
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
