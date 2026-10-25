"""Input validation and per-session rate limiting."""

import re
import threading
import time
from collections import defaultdict, deque

import config
from specter import edgar


class RequestRejected(ValueError):
    """A friendly, user-facing reason a request was refused."""


_TICKER_RE = re.compile(config.TICKER_PATTERN)
_SESSION_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")


def validate_spread_request(ticker, years, period_type) -> tuple[str, int, str]:
    """Normalize and check a spread request. Raises RequestRejected with a plain-English reason."""
    if not isinstance(ticker, str) or not _TICKER_RE.match(ticker.strip().upper()):
        raise RequestRejected("That doesn't look like a ticker. Use 1–5 letters, like AAPL or BRK-B.")
    ticker = ticker.strip().upper()
    try:
        years = int(years)
    except (TypeError, ValueError):
        raise RequestRejected("Years must be a whole number from 1 to 10.") from None
    if not config.MIN_YEARS <= years <= config.MAX_YEARS:
        raise RequestRejected(f"Years must be from {config.MIN_YEARS} to {config.MAX_YEARS}.")
    if period_type not in config.PERIOD_TYPES:
        raise RequestRejected("Choose annual, quarterly, or both.")
    try:
        known = ticker in edgar.load_tickers()
    except edgar.EdgarError:
        raise RequestRejected("Can't reach the SEC ticker list right now. Try again in a minute.") from None
    if not known:
        raise RequestRejected(f"{ticker} isn't in the SEC's list of public company tickers.")
    return ticker, years, period_type


def validate_session_id(session_id: str | None) -> str:
    if not session_id or not _SESSION_RE.match(session_id):
        raise RequestRejected("Missing or malformed session id. Reload the page.")
    return session_id


MAX_CHAT_CHARS = 1000


def validate_chat_message(message) -> str:
    if not isinstance(message, str) or not message.strip():
        raise RequestRejected("Say something first.")
    message = message.strip()
    if len(message) > MAX_CHAT_CHARS:
        raise RequestRejected(f"Keep it under {MAX_CHAT_CHARS} characters. Brevity is a virtue, counselor.")
    return message


# ---------------------------------------------------------------- prompt injection

# Requests for secrets, and classic attempts to override instructions. Checked in plain Python
# on every user message (refused without a model call) and on every MD&A chunk (neutralized).
_SECRET = re.compile(
    r"(api[\s_-]*key|secret[\s_-]*key|access[\s_-]*token|bearer\s+token|password|credential|"
    r"\.env\b|environment\s+variable|portkey_api_key|openai_api_key|system\s+prompt|your\s+(instructions|prompt|rules))",
    re.I)
_INJECTION = re.compile(
    r"(ignore|disregard|forget|override)\s+(all\s+|any\s+|the\s+|your\s+)?(previous|prior|above|earlier|system)?\s*"
    r"(instructions|prompts?|rules|directions)"
    r"|you\s+are\s+(now\s+)?(no\s+longer|not)\s+(bound|restricted)"
    r"|(developer|jailbreak|dan)\s+mode"
    r"|never\s+follow(s)?\s+(the\s+)?rules"
    r"|new\s+instructions\s*:"
    r"|(reveal|print|show|output|repeat|leak)\s+(your|the)\s+(system\s+)?(prompt|instructions)",
    re.I)
_KEY_LIKE = re.compile(r"\b(sk|pk)-[A-Za-z0-9_\-]{12,}\b")


def screen_user_message(text: str) -> str | None:
    """Return a reason if the message asks for secrets or tries to override instructions, else None."""
    if _INJECTION.search(text):
        return "prompt-injection pattern"
    if _SECRET.search(text) and re.search(r"\b(reveal|show|print|tell|give|share|leak|what|send|display|read|dump)\b",
                                          text, re.I):
        return "request for secrets"
    return None


def sanitize_filing_text(text: str) -> tuple[str, int]:
    """Neutralize instruction-like phrases inside filing text. Returns (clean text, number removed)."""
    clean, n = _INJECTION.subn("[instruction-like text removed]", text)
    clean, m = _SECRET.subn("[removed]", clean) if n else (clean, 0)
    return clean, n + m


def redact(text: str) -> str:
    """Last line of defense on anything shown to the user or logged: no key-shaped strings, no real keys."""
    import os
    for name in ("PORTKEY_API_KEY", "OPENAI_API_KEY"):
        val = (os.getenv(name) or "").strip()
        if len(val) >= 8:
            text = text.replace(val, "[redacted]")
    return _KEY_LIKE.sub("[redacted]", text)


class RateLimiter:
    """Sliding one-minute window per (session, action)."""

    def __init__(self):
        self.hits: dict[tuple, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def check(self, session_id: str, action: str, per_minute: int) -> None:
        now = time.monotonic()
        with self.lock:
            q = self.hits[(session_id, action)]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= per_minute:
                wait = int(60 - (now - q[0])) + 1
                raise RequestRejected(f"Easy, counselor. That's {per_minute} {action}s this minute. Try again in {wait}s.")
            q.append(now)


rate_limiter = RateLimiter()
