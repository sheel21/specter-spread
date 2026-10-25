"""Specter Spread web server. Run with:  python app.py   then open http://127.0.0.1:8000"""

import json
import logging
import queue
import threading
import time

import uvicorn
from fastapi import FastAPI, Header, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

import config
from specter import edgar
from specter.env import env_source
from specter.chat import handle_message
from specter.excel import build_workbook
from specter.llm import BudgetExceeded, ModelUnavailable, RunCtx, session_records, summarize
from specter.pipeline import build_spread
from specter.safety import (RequestRejected, rate_limiter, redact, validate_chat_message, validate_session_id,
                            validate_spread_request)

log = logging.getLogger("specter")
app = FastAPI(title="Specter Spread")
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")

# Per-browser-session state (in memory; no database). session_id -> {"spread": {...}}
SESSIONS: dict[str, dict] = {}


@app.exception_handler(RequestRejected)
async def _rejected(_: Request, exc: RequestRejected):
    return JSONResponse({"error": str(exc)}, status_code=400)


@app.get("/")
def index():
    return FileResponse(config.STATIC_DIR / "index.html")


@app.get("/api/meta")
def meta():
    return {
        "examples": config.EXAMPLE_TICKERS,
        "min_years": config.MIN_YEARS,
        "max_years": config.MAX_YEARS,
        "data_mode": config.DATA_MODE,
        "env_source": env_source(),
    }


@app.get("/api/tokens")
def tokens(x_session_id: str | None = Header(default=None)):
    records = session_records(validate_session_id(x_session_id))
    return {"summary": summarize(records), "records": records[-50:], "prices": config.PRICE_PER_MILLION,
            "model": config.MODEL, "optimized": config.OPTIMIZED}


def _persona(body: dict) -> str:
    return body.get("persona") if body.get("persona") in ("harvey", "mike") else "harvey"


def _streamed(kind: str, session_id: str, persona: str, work) -> StreamingResponse:
    """Run `work(ctx, session)` in a thread; stream its progress and result as NDJSON lines."""
    events: queue.Queue = queue.Queue()

    def emit(agent: str, tool: str, message: str) -> None:
        events.put({"type": "activity", "agent": agent, "tool": tool, "message": redact(message), "t": time.time()})

    ctx = RunCtx(kind=kind, session_id=session_id, persona=persona, emit=emit)
    session = SESSIONS.setdefault(session_id, {})

    def run() -> None:
        try:
            events.put(work(ctx, session))
        except (edgar.EdgarError, RequestRejected, BudgetExceeded, ModelUnavailable) as exc:
            events.put({"type": "error", "message": redact(str(exc))})
        except Exception:
            log.exception("%s run failed", kind)
            events.put({"type": "error", "message": "Something broke on our side. Check the server log."})
        finally:
            events.put(None)

    threading.Thread(target=run, daemon=True).start()

    def stream():
        while (item := events.get()) is not None:
            yield json.dumps(item, default=str) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@app.get("/api/export")
def export(sid: str = ""):
    """The current spread as a banker-formatted .xlsx. sid is passed as a query param so a plain link works."""
    spread = SESSIONS.get(validate_session_id(sid), {}).get("spread")
    if not spread:
        raise RequestRejected("Build a spread first, then download it.")
    data = build_workbook(spread)
    name = f"{spread['company']['ticker']}_Specter_Spread.xlsx"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/api/spread")
async def spread(body: dict, x_session_id: str | None = Header(default=None)):
    session_id = validate_session_id(x_session_id)
    ticker, years, period_type = validate_spread_request(body.get("ticker"), body.get("years"), body.get("period_type"))
    rate_limiter.check(session_id, "run", config.RUNS_PER_MINUTE)

    def work(ctx, session):
        result = build_spread(ticker, years, period_type, ctx)
        session["spread"] = result
        return {"type": "spread", "spread": result}

    return _streamed("spread", session_id, _persona(body), work)


@app.post("/api/chat")
async def chat(body: dict, x_session_id: str | None = Header(default=None)):
    session_id = validate_session_id(x_session_id)
    message = validate_chat_message(body.get("message"))
    rate_limiter.check(session_id, "chat message", config.CHATS_PER_MINUTE)

    def work(ctx, session):
        return {"type": "chat", "reply": handle_message(message, session, ctx)}

    return _streamed("chat", session_id, _persona(body), work)


if __name__ == "__main__":
    print(f"Specter Spread on http://{config.HOST}:{config.PORT}  (.env: {env_source()}, data mode: {config.DATA_MODE})")
    uvicorn.run(app, host=config.HOST, port=config.PORT, reload=False, log_level="warning")
