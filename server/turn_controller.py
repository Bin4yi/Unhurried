"""Turn controller: on every pause, decide "hold" (wait) or "send" (turn is done).

Time is audio seconds (see audio_router). The session calls:
  on_partial / on_speech_start / on_pause / on_model_turn / on_check / tick
Each returns a list of actions:
  {"do": "hold",  "reason": ...}
  {"do": "send",  "text": ..., "reason": ...}
  {"do": "check", "text": ...}           ask the completeness checker (async)
  {"do": "resume"}                        speech started again inside the turn
Decision log rows are collected in self.decisions (written by the session).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

LINKING = {
    "to", "the", "a", "an", "for", "and", "or", "my", "at", "of", "with", "can", "is",
    "are", "in", "on", "from", "but", "because", "your", "our", "some", "this", "that",
    "i'd", "i'm", "want", "like", "would", "could", "please", "about", "into", "than",
}
FILLERS = {"uh", "um", "er", "erm", "uhm", "hmm", "ah", "eh", "mm", "umm", "uhh"}
SHORT_WORDS = {
    "a", "i", "to", "at", "on", "in", "is", "it", "of", "my", "me", "we", "us", "he", "be",
    "do", "go", "no", "so", "up", "or", "an", "am", "as", "by", "if", "ok", "hi", "pm",
    "yes", "yep", "oh", "two", "six", "ten", "one", "mon", "tue", "wed", "thu", "fri", "sat", "sun",
}
_WORD = re.compile(r"[a-z0-9']+-*|-")


def tokens(text: str) -> list[str]:
    """Lowercase word tokens. A trailing '-' (cut word) is kept on the token."""
    return _WORD.findall(text.lower().replace("…", "-"))


def check_key(text: str) -> str:
    """Normalized text used to match completeness answers (case and punctuation free)."""
    return " ".join(tokens(text))


def classify(text: str) -> dict:
    """Code rules on the current text. Returns the signals and `unfinished`."""
    toks = tokens(text)
    words = [t.strip("-") for t in toks if t.strip("-")]
    real = [w for w in words if w not in FILLERS]
    last = toks[-1] if toks else ""
    lw = last.strip("-")
    signals = {
        "no_words": not real,
        "linking_word": lw in LINKING,
        "cut_word": bool(last) and (last.endswith("-") or
                                    (len(lw) <= 2 and lw not in SHORT_WORDS and not lw.isdigit())),
        "repeat": len(words) >= 2 and words[-1] == words[-2] and words[-1] not in FILLERS,
        "filler": lw in FILLERS,
    }
    signals["unfinished"] = any(signals.values())
    return signals


@dataclass
class TurnController:
    max_wait_ms: int = 6000
    send_delay_ms: int = 300
    use_checker: bool = False
    check_timeout_ms: int = 700
    segments: list[str] = field(default_factory=list)
    partial: str = ""
    pause_start: float | None = None
    opened_at: float = 0.0
    pending_send_at: float | None = None
    awaiting: tuple[str, float] | None = None  # (text, deadline)
    holding: bool = False
    inner_pauses_ms: list[int] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)
    check_cache: dict[str, dict] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return " ".join(s for s in [*self.segments, self.partial] if s).strip()

    # ---------------------------------------------------------- inputs

    def on_partial(self, text: str, now: float) -> list[dict]:
        self.partial = text
        return []

    def on_speech_start(self, now: float, start_t: float | None = None) -> list[dict]:
        acts: list[dict] = []
        if self.pause_start is not None and self.text:
            gap = (start_t if start_t is not None else now) - self.pause_start
            if gap > 0:
                self.inner_pauses_ms.append(int(gap * 1000))
            acts.append({"do": "resume"})
        if not self.text:
            self.opened_at = now
        self.pause_start = None
        self.pending_send_at = None
        self.awaiting = None
        return acts

    def on_pause(self, end_t: float, now: float) -> list[dict]:
        self.pause_start = end_t
        return []

    def on_model_turn(self, text: str, now: float) -> list[dict]:
        if text:
            self.segments.append(text)
        self.partial = ""
        if self.pause_start is None:
            self.pause_start = now
        return self.decide(now)

    def on_check(self, text: str, answer: str, ms: float, now: float) -> list[dict]:
        key = check_key(text)
        self.check_cache[key] = {"answer": answer, "ms": round(ms)}
        if not self.awaiting or self.awaiting[0] != key or self.pause_start is None:
            return []
        self.awaiting = None
        spark = {"answer": answer, "ms": round(ms)}
        if answer == "no":
            return self._hold(now, "check_no", classify(self.text), spark=spark)
        # yes, or the checker failed: do not make the person wait for a broken check
        return self._send(now, "check_yes" if answer == "yes" else "check_failed", spark=spark)

    def on_typed(self, text: str, now: float) -> list[dict]:
        """Typed text joins the open turn and sends it."""
        if text.strip():
            self.segments.append(text.strip())
        self.partial = ""
        return self._send(now, "typed")

    def tick(self, now: float) -> list[dict]:
        if self.pending_send_at is not None and now >= self.pending_send_at:
            return self._send(now, "rules")
        if self.awaiting and now >= self.awaiting[1]:
            return self._send(now, "check_timeout", spark={"answer": "timeout"})
        if self.pause_start is not None and self.text:
            if classify(self.text)["no_words"]:
                if (now - self.opened_at) * 1000 >= self.max_wait_ms:
                    return self._send(now, "max_wait_empty")
            elif (now - self.pause_start) * 1000 >= self.max_wait_ms:
                return self._send(now, "max_wait")
        return []

    # ---------------------------------------------------------- logic

    def decide(self, now: float) -> list[dict]:
        text = self.text
        if not text:
            return []
        sig = classify(text)
        if sig["unfinished"]:
            return self._hold(now, "no_words" if sig["no_words"] else _first_reason(sig), sig)
        if self.use_checker:
            cached = self.check_cache.get(check_key(text))
            if cached and cached["answer"] in ("yes", "no"):
                return self.on_check_cached(text, cached, now)
            self.awaiting = (check_key(text), now + self.check_timeout_ms / 1000)
            self._log(now, sig, "check", spark=None)
            return [{"do": "check", "text": text}]
        self.pending_send_at = now + self.send_delay_ms / 1000
        self._log(now, sig, "send_soon")
        return []

    def on_check_cached(self, text: str, cached: dict, now: float) -> list[dict]:
        spark = {**cached, "cached": True}
        if cached["answer"] == "yes":
            return self._send(now, "check_yes", spark=spark)
        return self._hold(now, "check_no", classify(text), spark=spark)

    def _hold(self, now: float, reason: str, sig: dict, spark: dict | None = None) -> list[dict]:
        self.holding = True
        self._log(now, sig, "hold", spark=spark, reason=reason)
        return [{"do": "hold", "reason": reason, "max_wait_ms": self.max_wait_ms}]

    def _send(self, now: float, reason: str, spark: dict | None = None) -> list[dict]:
        text = self.text
        self._log(now, classify(text), "send", spark=spark, reason=reason)
        self.segments, self.partial = [], ""
        self.pause_start = self.pending_send_at = self.awaiting = None
        self.holding = False
        self.opened_at = now
        return [{"do": "send", "text": text, "reason": reason}] if text else []

    def _log(self, now: float, sig: dict, decision: str, spark: dict | None = None,
             reason: str | None = None) -> None:
        pause_ms = int((now - self.pause_start) * 1000) if self.pause_start is not None else 0
        self.decisions.append({
            "t": round(now, 3), "pause_ms": pause_ms, "last_words": tokens(self.text)[-2:],
            "signals": {k: sig[k] for k in ("linking_word", "cut_word", "repeat", "filler")},
            "spark_check": spark, "decision": decision, "reason": reason,
            "max_wait_ms": self.max_wait_ms,
        })


def _first_reason(sig: dict) -> str:
    for k in ("cut_word", "repeat", "filler", "linking_word"):
        if sig[k]:
            return k
    return "unfinished"
