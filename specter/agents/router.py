"""Router Agent: one small model call per chat message decides who handles it."""

from specter.agents.base import tool_schema
from specter.llm import RunCtx, call_model
from specter.personas import persona_block

RULES = """You are the Router for Specter Spread, a financial-spread app built on SEC EDGAR filings.
Call route exactly once.
- "spread": the user wants to build or change a spread (a ticker, more/fewer years, annual/quarterly).
  Fill ticker (uppercase), years (1-10) and period_type only from what the user said; else null.
- "analyst": questions about the current company's trends, reasons, margins, risks, or what management says.
- "direct": greetings, help, off-topic, or anything else. Write a reply of at most 2 sentences in your
  voice. Never state financial figures in a direct reply.
reason: under 12 words, neutral."""

ROUTE_TOOL = tool_schema("route", "Send the message to the right agent.", {
    "route": {"type": "string", "enum": ["spread", "analyst", "direct"]},
    "ticker": {"type": ["string", "null"]},
    "years": {"type": ["integer", "null"]},
    "period_type": {"type": ["string", "null"], "enum": ["annual", "quarterly", "both", None]},
    "reply": {"type": "string", "description": "Only for direct; empty otherwise."},
    "reason": {"type": "string"},
})


def route(ctx: RunCtx, message: str, context_line: str, history: list[dict]) -> dict:
    """Returns {"route", "ticker", "years", "period_type", "reply", "reason"}."""
    instructions = f"{persona_block(ctx.persona)}\n\n{RULES}"
    recent = "\n".join(f"{h['role']}: {h['text'][:200]}" for h in history[-2:])
    payload = (f"Current spread: {context_line}\n"
               + (f"Recent turns:\n{recent}\n" if recent else "")
               + f"<user_message>{message}</user_message>")
    result = call_model(ctx, "Router", instructions, payload, tools=[ROUTE_TOOL], tool_choice="required",
                        cacheable=True, purpose="route")
    call = next((c for c in result.tool_calls if c["name"] == "route"), None)
    if call is None:
        return {"route": "direct", "ticker": None, "years": None, "period_type": None,
                "reply": "Say that again, counselor?", "reason": "no routing decision"}
    args = call["arguments"]
    if args.get("route") not in ("spread", "analyst", "direct"):
        args["route"] = "direct"
    return args  # ticker/years are validated by safety.validate_spread_request before any run
