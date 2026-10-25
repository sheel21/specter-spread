"""One chat turn: safety screen -> Router -> (spread pipeline | Analyst | direct reply).

Conversation memory is deliberately short: the current spread (summarized for the Analyst) and
the last few turns, where assistant turns are stored as their neutral headline only.
"""

import config
from specter import edgar
from specter.agents.analyst import Analyst, voice
from specter.agents.router import route
from specter.llm import BudgetExceeded, ModelUnavailable, RunCtx
from specter.personas import REFUSALS
from specter.pipeline import build_spread
from specter.safety import RequestRejected, rate_limiter, redact, screen_user_message, validate_spread_request

HISTORY_TURNS = 6
SPREAD_DONE = {
    "harvey": "{t} is spread. Every number has a source. Now ask me something worth answering.",
    "mike": "{t} is spread, and I checked every tag! Ask me why anything moved and I'll pull it from the MD&A.",
}
NO_SPREAD = {
    "harvey": "I don't argue without the file. Build a spread first: give me a ticker.",
    "mike": "I'd love to dig in, but I need a company first. Give me a ticker and I'll read everything.",
}


def handle_message(message: str, session: dict, ctx: RunCtx) -> dict:
    history = session.setdefault("history", [])
    try:
        reply = _dispatch(message, session, ctx, history)
    except BudgetExceeded as exc:
        reply = {"kind": "error", "text": f"{exc} Stopped cleanly; nothing further was spent."}
    except ModelUnavailable as exc:
        reply = {"kind": "error", "text": str(exc)}
    except RequestRejected as exc:
        reply = {"kind": "error", "text": str(exc)}
    except edgar.EdgarError as exc:
        reply = {"kind": "error", "text": str(exc)}
    for key in ("text", "voice"):
        if reply.get(key):
            reply[key] = redact(reply[key])
    # A refused message never goes back to the model: it would ride along in every later prompt
    # (and the provider's own jailbreak filter would then reject those prompts).
    history.append({"role": "user", "text": "[message refused by the safety screen]" if reply["kind"] == "refusal"
                    else message})
    history.append({"role": "assistant", "text": reply.get("answer", {}).get("headline") or reply.get("text", "")})
    del history[:-HISTORY_TURNS]
    reply["run"] = {"run_id": ctx.run_id, "tokens": ctx.totals(), "budget": {
        "tokens": ctx.budget.tokens, "max_tokens": ctx.budget.max_tokens, "model_calls": ctx.budget.calls,
        "max_model_calls": ctx.budget.max_calls, "tool_calls": ctx.budget.tool_calls,
        "max_tool_calls": ctx.budget.max_tool_calls}}
    return reply


def _dispatch(message: str, session: dict, ctx: RunCtx, history: list) -> dict:
    reason = screen_user_message(message)
    if reason:
        ctx.emit("Router", "", f"Safety: {reason} detected. Refused without calling the model.")
        return {"kind": "refusal", "text": REFUSALS[ctx.persona]}

    spread = session.get("spread")
    context_line = (f"{spread['company']['ticker']} ({spread['company']['name']}), {spread['request']['years']} years, "
                    f"{spread['request']['period_type']}" if spread else "none built yet")
    decision = route(ctx, message, context_line, history)
    ctx.emit("Router", "route", f"→ {decision['route'].title()}. {decision.get('reason', '')}".strip())

    if decision["route"] == "spread":
        req = spread["request"] if spread else {}
        ticker = decision.get("ticker") or (spread["company"]["ticker"] if spread else None)
        if not ticker:
            return {"kind": "direct", "text": NO_SPREAD[ctx.persona]}
        years = decision.get("years") or req.get("years") or 5
        period_type = decision.get("period_type") or req.get("period_type") or "annual"
        ticker, years, period_type = validate_spread_request(ticker, years, period_type)
        rate_limiter.check(ctx.session_id, "run", config.RUNS_PER_MINUTE)
        result = build_spread(ticker, years, period_type, ctx)
        session["spread"] = result
        return {"kind": "spread", "text": SPREAD_DONE[ctx.persona].format(t=ticker), "spread": result}

    if decision["route"] == "analyst":
        if not spread:
            return {"kind": "direct", "text": NO_SPREAD[ctx.persona]}
        ctx.emit("Analyst", "read_spread", "Reviewing the spread and the filings…")
        answer = Analyst(ctx, spread, session).answer(message, history)
        audit = answer.get("audit", {}).get("figures", {})
        if audit:
            ctx.emit("Analyst", "submit_answer",
                     f"Number audit: {audit['traced']}/{audit['total']} figures trace to the spread or excerpts.")
        return {"kind": "analysis", "voice": voice(ctx, message, answer["headline"]), "answer": answer}

    return {"kind": "direct", "text": decision.get("reply") or "Ask me about a company's numbers."}
