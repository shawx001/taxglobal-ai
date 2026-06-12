"""Multi-turn query rewriting (conversation memory, 2026-06-11).

Each chat message used to be classified in isolation, so a follow-up
like "我大概10个月在日本 package20w美金" re-entered the pipeline with no
context and dead-ended. The fix: the LLM condenses the recent
conversation + the new message into ONE self-contained question, and
THAT goes through the unchanged pipeline (classify → extract → engine).
LLM = ears only — the rewrite carries the user's stated facts, never
invents amounts, and any failure falls back to the original message.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("taxglobal.orchestrator")

MAX_HISTORY_MESSAGES = 8
_MAX_REWRITE_TOKENS = 200

_REWRITE_SYSTEM_PROMPT = """\
You condense a tax-assistant conversation into ONE self-contained
question, in the same language the user writes.

Rules:
1. Merge ALL facts the user has stated across the conversation into the
   rewritten question: amounts, durations, locations, filing status.
   Normalize slang amounts ("20w" / "20万" -> 200000美元) and convert
   stated durations to approximate days when the topic needs days
   ("10个月" -> "约300天"), keeping the word 约 for approximations.
2. NEVER invent facts the user did not state. Do not add amounts,
   states, or years that never appeared.
3. If the latest message is already self-contained, return it as-is.
4. If the latest message is small talk unrelated to tax, return it
   as-is.
5. Output ONLY the rewritten question — no explanation, no quotes.
"""


def llm_rewrite_query(history: list[dict[str, str]], query: str) -> str | None:
    """Rewrite the latest message into a self-contained question.

    Returns the rewritten question, or ``None`` on any failure so the
    caller uses the original query unchanged.
    """

    if not history:
        return None

    from backend.llm.client import get_provider
    from backend.llm.provider import LLMMessage

    provider = get_provider()
    if provider is None:
        return None

    lines: list[str] = []
    for item in history[-MAX_HISTORY_MESSAGES:]:
        role = "用户" if item.get("role") == "user" else "助手"
        content = str(item.get("content", ""))[:500]
        if content:
            lines.append(f"{role}: {content}")
    lines.append(f"用户(最新): {query}")

    messages = [
        LLMMessage(role="system", content=_REWRITE_SYSTEM_PROMPT),
        LLMMessage(role="user", content="\n".join(lines)),
    ]

    try:
        response = provider.complete(messages, temperature=0.0, max_tokens=_MAX_REWRITE_TOKENS)
    except Exception:
        logger.exception("Query rewrite failed, using original query")
        return None
    if response is None:
        return None

    text = response.content if isinstance(response.content, str) else ""
    text = text.strip().strip('"').strip()
    if not text or len(text) > 2000:
        return None
    return text
