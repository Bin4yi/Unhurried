"""Completeness check: "is this a complete request?" on live text.

Spark takes about 1-2 s per call, so the session starts checks early
(speculatively, on live partial text whenever the code rules say "not
unfinished") and caches answers by normalized text. At a pause the answer
is often ready already; if not, the turn controller waits at most
check_timeout_ms, then sends.
"""

from __future__ import annotations

import time

from server import llm

SYSTEM = (
    "You help a voice assistant decide when a caller has finished speaking. "
    "You get the words the caller has said so far (speech-to-text, may lack punctuation). "
    "Answer 'yes' if the words form a complete request, question or answer that the assistant "
    "could reply to now, even if some booking details are missing. "
    "Answer 'no' only if the caller is clearly in the middle of a sentence. "
    "Reply with one word: yes or no."
)


def parse_answer(content: str) -> str:
    c = (content or "").strip().lower()
    if c.startswith("yes"):
        return "yes"
    if c.startswith("no"):
        return "no"
    return "unknown"


async def check_complete(text: str, provider: str = "spark", chat=llm.chat) -> tuple[str, float]:
    """Returns (answer, ms). answer is 'yes', 'no', 'unknown' or 'error'."""
    start = time.monotonic()
    try:
        out = await chat([{"role": "system", "content": SYSTEM},
                          {"role": "user", "content": text}],
                         purpose="completeness", provider=provider,
                         reasoning_effort="minimal", max_tokens=300, timeout=8)
        answer = parse_answer(out["content"])
    except Exception:
        answer = "error"
    return answer, (time.monotonic() - start) * 1000
