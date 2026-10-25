"""The only door to the model: Portkey gateway, gpt-6-luna, with token logging and a budget guard.

Every call is logged (agent, input tokens, cached input tokens, output tokens, cost) to
logs/tokens.jsonl and to the in-memory ledger the UI's cost panel reads. Keys are never logged.
"""

import hashlib
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache

from openai import OpenAI

import config

from specter.safety import redact  # noqa: E402

_log = logging.getLogger("specter.llm")
TOKEN_LOG = config.LOG_DIR / "tokens.jsonl"
MODEL_CACHE = config.CACHE_DIR / "model"
_log_lock = threading.Lock()


class BudgetExceeded(RuntimeError):
    """A per-run cap (tokens, model calls, or tool calls) was hit. The run stops cleanly."""


class ModelUnavailable(RuntimeError):
    """No key configured or the gateway failed."""


# ---------------------------------------------------------------- run context


@dataclass
class RunBudget:
    max_tokens: int = config.MAX_TOKENS_PER_RUN
    max_calls: int = config.MAX_MODEL_CALLS_PER_RUN
    max_tool_calls: int = config.MAX_TOOL_CALLS_PER_RUN
    tokens: int = 0
    calls: int = 0
    tool_calls: int = 0

    def before_call(self, estimated_input: int = 0) -> None:
        """Refuse a call that would exceed a cap. The input size is estimated (about 4 characters
        per token) so a single large request can't blow far past the token cap."""
        if self.calls >= self.max_calls:
            raise BudgetExceeded(f"Budget guard: this run hit its cap of {self.max_calls} model calls.")
        if self.tokens + estimated_input >= self.max_tokens:
            raise BudgetExceeded(f"Budget guard: the next call (~{estimated_input:,} input tokens) would take this run "
                                 f"past its cap of {self.max_tokens:,} tokens ({self.tokens:,} used).")

    def add_tool_call(self) -> None:
        if self.tool_calls >= self.max_tool_calls:
            raise BudgetExceeded(f"Budget guard: this run hit its cap of {self.max_tool_calls} tool calls.")
        self.tool_calls += 1


@dataclass
class RunCtx:
    """Everything one run (a spread build or a chat answer) carries around."""
    kind: str                                   # "spread" or "chat"
    session_id: str = "cli"
    persona: str = "harvey"
    emit: callable = lambda agent, tool, message: None
    budget: RunBudget = field(default_factory=RunBudget)
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    records: list = field(default_factory=list)  # token records for this run

    def totals(self) -> dict:
        return summarize(self.records)


@dataclass
class LLMResult:
    text: str
    tool_calls: list[dict]                      # [{"name", "arguments" (dict), "call_id"}]
    usage: dict
    cache_hit: bool = False


# ---------------------------------------------------------------- client


def api_key() -> str:
    return (os.getenv("PORTKEY_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    key = api_key()
    if not key:
        raise ModelUnavailable("No model key configured. Set PORTKEY_API_KEY in .env (see .env.example).")
    # Force-refresh: Portkey's response cache would otherwise replay identical requests and hide
    # real token usage. Repeat-request savings come from our own, logged, model-result cache.
    return OpenAI(api_key=key, base_url=config.PORTKEY_BASE_URL, max_retries=2, timeout=90,
                  default_headers={"x-portkey-api-key": key, "x-portkey-cache-force-refresh": "true"})


def cost_usd(input_tokens: int, cached: int, output: int) -> float:
    p = config.PRICE_PER_MILLION
    return ((input_tokens - cached) * p["input"] + cached * p["cached_input"] + output * p["output"]) / 1e6


def call_model(ctx: RunCtx, agent: str, instructions: str, input, tools: list[dict] | None = None,
               tool_choice: str = "auto", cacheable: bool = False, purpose: str = "") -> LLMResult:
    """One model call through Portkey. Enforces the run budget and logs token usage per agent.

    `instructions` should be stable text (persona block first) so the provider's prompt cache applies.
    `cacheable` results are stored on disk and replayed for identical requests (OPTIMIZED mode only).
    """
    request = {"model": config.MODEL, "instructions": instructions, "input": input,
               "reasoning": {"effort": config.REASONING_EFFORT}, "max_output_tokens": config.MAX_OUTPUT_TOKENS}
    if tools:
        request["tools"] = tools
        request["tool_choice"] = tool_choice

    cache_path = None
    if cacheable and config.OPTIMIZED:
        digest = hashlib.sha256(json.dumps(request, sort_keys=True, default=str).encode()).hexdigest()[:32]
        cache_path = MODEL_CACHE / f"{agent.lower()}_{digest}.json"
        if cache_path.is_file():
            saved = json.loads(cache_path.read_text())
            _record(ctx, agent, purpose, {"input_tokens": 0, "cached_tokens": 0, "output_tokens": 0,
                                          "reasoning_tokens": 0}, 0, cache_hit=True)
            return LLMResult(saved["text"], saved["tool_calls"], saved["usage"], cache_hit=True)

    ctx.budget.before_call(len(json.dumps(request, default=str)) // 4)
    ctx.budget.calls += 1
    started = time.perf_counter()
    try:
        resp = _client().responses.create(**request)
    except ModelUnavailable:
        raise
    except Exception as exc:  # gateway/network errors: report without echoing request headers
        detail = getattr(exc, "message", "") or str(exc)
        _log.warning("model call failed for %s: %s %s", agent, type(exc).__name__, redact(detail)[:500])
        if "content_filter" in detail or "content management policy" in detail:
            raise ModelUnavailable("The model provider's safety filter blocked this request. "
                                   "Rephrase the question and try again.") from None
        raise ModelUnavailable(f"The model gateway failed ({type(exc).__name__}).") from None
    latency_ms = int((time.perf_counter() - started) * 1000)

    u = resp.usage
    usage = {
        "input_tokens": u.input_tokens,
        "cached_tokens": getattr(u.input_tokens_details, "cached_tokens", 0) or 0,
        "output_tokens": u.output_tokens,
        "reasoning_tokens": getattr(u.output_tokens_details, "reasoning_tokens", 0) or 0,
    }
    ctx.budget.tokens += u.input_tokens + u.output_tokens
    _record(ctx, agent, purpose, usage, latency_ms)

    text_parts, tool_calls = [], []
    for item in resp.output:
        if item.type == "message":
            text_parts += [c.text for c in item.content if getattr(c, "type", "") == "output_text"]
        elif item.type == "function_call":
            try:
                args = json.loads(item.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append({"name": item.name, "arguments": args, "call_id": item.call_id})
    result = LLMResult("\n".join(text_parts).strip(), tool_calls, usage)
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({"text": result.text, "tool_calls": result.tool_calls, "usage": usage}))
    return result


# ---------------------------------------------------------------- ledger


_session_records: dict[str, list] = {}


def _record(ctx: RunCtx, agent: str, purpose: str, usage: dict, latency_ms: int, cache_hit: bool = False) -> None:
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_id": ctx.run_id, "run_kind": ctx.kind, "session": ctx.session_id[:8], "agent": agent,
        "purpose": purpose, "persona": ctx.persona, "model": config.MODEL, "optimized": config.OPTIMIZED,
        "input_tokens": usage["input_tokens"], "cached_input_tokens": usage["cached_tokens"],
        "output_tokens": usage["output_tokens"], "reasoning_tokens": usage["reasoning_tokens"],
        "cost_usd": round(cost_usd(usage["input_tokens"], usage["cached_tokens"], usage["output_tokens"]), 6),
        "latency_ms": latency_ms, "model_cache_hit": cache_hit,
    }
    ctx.records.append(rec)
    with _log_lock:
        _session_records.setdefault(ctx.session_id, []).append(rec)
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        with TOKEN_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")


def session_records(session_id: str) -> list[dict]:
    with _log_lock:
        return list(_session_records.get(session_id, []))


def summarize(records: list[dict]) -> dict:
    """Totals overall and per agent."""
    def blank():
        return {"calls": 0, "input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
                "cache_hits": 0}

    total, by_agent = blank(), {}
    for r in records:
        for bucket in (total, by_agent.setdefault(r["agent"], blank())):
            bucket["calls"] += 0 if r["model_cache_hit"] else 1
            bucket["cache_hits"] += 1 if r["model_cache_hit"] else 0
            for k in ("input_tokens", "cached_input_tokens", "output_tokens", "cost_usd"):
                bucket[k] += r[k]
    total["cost_usd"] = round(total["cost_usd"], 6)
    for b in by_agent.values():
        b["cost_usd"] = round(b["cost_usd"], 6)
    return {"total": total, "by_agent": by_agent}
