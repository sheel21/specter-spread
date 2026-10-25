"""The spread pipeline: Fetcher -> Spreader -> Checker (capped fix loop). Emits progress events as it goes."""

from datetime import datetime, timezone

from specter import edgar
from specter.agents.checker import Checker
from specter.agents.fetcher import Fetcher
from specter.agents.spreader import Spreader
from specter.llm import RunCtx
from specter.xbrl import FactIndex, annual_periods, quarterly_periods


def build_spread(ticker: str, years: int, period_type: str, ctx: RunCtx) -> dict:
    """Build and check the spread for one company. Progress goes to ctx.emit(agent, tool, message)."""
    emit = ctx.emit
    before = dict(edgar.stats)
    fetcher = Fetcher(emit)
    company = fetcher.lookup_cik(ticker)
    cik = company["cik"]
    facts = fetcher.get_company_facts(cik)
    forms = {"annual": "10-K", "quarterly": "10-Q", "both": "both"}[period_type]
    filings = fetcher.list_filings(cik, forms, years)

    idx = FactIndex(facts, cik)
    annual = annual_periods(idx)
    if not annual:
        raise edgar.EdgarError(f"{ticker} has no annual XBRL financial data on EDGAR.")

    spreader = Spreader(idx, emit)
    checker = Checker(ctx, spreader)
    views, check_results = {}, {}
    plan = []
    if period_type in ("annual", "both"):
        plan.append(("annual", annual[-(years + 1):], years))  # one extra year for growth and the cash tie-out
    if period_type in ("quarterly", "both"):
        plan.append(("quarterly", quarterly_periods(idx, annual)[-(4 * years + 4):], 4 * years))

    for name, periods, display in plan:
        if name == "annual":
            for p in periods[1:]:
                emit("Spreader", "get_facts_for_concept", f"Closing the books on {p['label']}…")
        else:
            emit("Spreader", "get_facts_for_concept", f"Working through {min(len(periods), display)} quarters of 10-Qs…")
        spreader.fill(periods)
        emit("Checker", "check_balance_sheet", f"Auditing the {name} numbers. Every subtotal has to foot.")
        check_results[name] = checker.run(name, periods, display)
        views[name] = spreader.view(periods, display)

    used_sample = edgar.stats["sample_hits"] > before["sample_hits"]
    used_live = edgar.stats["http_requests"] > before["http_requests"]
    return {
        "company": {"ticker": company["ticker"], "name": facts.get("entityName") or company["name"], "cik": cik},
        "request": {"years": years, "period_type": period_type},
        "units": "USD millions, except per-share amounts (USD) and share counts (millions)",
        "data_source": ("bundled sample data (offline)" if used_sample else
                        "SEC EDGAR (live)" if used_live else "SEC EDGAR (disk cache)"),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "filings": filings,
        "fiscal_years": {str(p["fy"]): {"start": p["start"].isoformat(), "end": p["end"].isoformat()} for p in annual},
        "views": views,
        "checks": check_results,
        "run": {"run_id": ctx.run_id, "tokens": ctx.totals(), "budget": {
            "tokens": ctx.budget.tokens, "max_tokens": ctx.budget.max_tokens,
            "model_calls": ctx.budget.calls, "max_model_calls": ctx.budget.max_calls,
            "tool_calls": ctx.budget.tool_calls, "max_tool_calls": ctx.budget.max_tool_calls}},
    }
