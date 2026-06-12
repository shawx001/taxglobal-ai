"""M3.7: token estimation + context compression for LLM calls.

Two cost levers:
- ``estimate_tokens``: tiktoken when installed, otherwise a CJK-aware
  heuristic (CJK ≈ 1 token/char, ASCII ≈ 1 token/4 chars).
- ``compress_knowledge_context``: the knowledge path used to send full
  KB chunks to the LLM (flagged in the M3.3 review). Caps chunk count
  and per-chunk length while preserving source attributions verbatim.

Engine amounts are NEVER compressed — only retrieved prose is. Cache
alignment note: all system prompts are constant module-level strings
placed first in the message list, which keeps the provider-side prefix
cache warm; keep it that way when editing prompts.
"""

from __future__ import annotations

import re
from typing import Any

_MAX_KB_RESULTS = 3
_MAX_CHUNK_CHARS = 600

# A truncated chunk must never end inside an amount: "…$13,8" invites the
# LLM to complete it into a neighbor figure that the fact-checker (which
# checks set membership against the FULL chunk) cannot distinguish.
_TRAILING_PARTIAL_AMOUNT = re.compile(r"[$￥]?[\d][\d,.]*$")


def estimate_tokens(text: str) -> int:
    """Best-effort token count for budgeting/cost estimates."""

    if not text:
        return 0
    try:
        import tiktoken

        return len(tiktoken.get_encoding("cl100k_base").encode(text))
    except Exception:
        cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
        return cjk + max(1, (len(text) - cjk) // 4)


def compress_knowledge_context(answer: dict[str, Any]) -> dict[str, Any]:
    """Shrink a knowledge answer before it goes into an LLM prompt.

    Returns a NEW dict — the original response payload is untouched.
    Non-knowledge answers pass through unchanged (engine numbers must
    reach the LLM verbatim).
    """

    if not isinstance(answer, dict) or answer.get("type") != "knowledge":
        return answer

    results = answer.get("results")
    if not isinstance(results, list):
        return answer

    compressed: list[dict[str, Any]] = []
    for item in results[:_MAX_KB_RESULTS]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", ""))
        if len(text) > _MAX_CHUNK_CHARS:
            text = _TRAILING_PARTIAL_AMOUNT.sub("", text[:_MAX_CHUNK_CHARS]).rstrip() + "…"
        slim: dict[str, Any] = {"text": text}
        if item.get("sources") is not None:
            slim["sources"] = item["sources"]
        compressed.append(slim)

    return {"type": "knowledge", "results": compressed, "total": answer.get("total", len(compressed))}
