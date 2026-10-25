"""Plain-Python accounting checks. No model calls: arithmetic is never delegated to the LLM.

Each check takes `get(line_key, period_key) -> value | None`, `src(...)`, the period, and
`prior` = {"prev": the immediately preceding period, "yoy": the same period a year earlier}
(either may be None), and returns a result dict (or list), or None when its inputs are N/A.
"""

M = 1e6  # display unit


def _close(a: float, b: float, rel: float = 0.002, floor: float = 1e6) -> bool:
    return abs(a - b) <= max(floor, rel * max(abs(a), abs(b)))


def _fmt(v: float) -> str:
    return f"(${abs(v) / M:,.0f}M)" if v < 0 else f"${v / M:,.0f}M"


def _result(check, statement, period, ok, detail, lines, suspects=None):
    return {"check": check, "statement": statement, "period": period["key"], "ok": ok, "detail": detail,
            "lines": lines, "suspects": suspects or lines}


# ---------------------------------------------------------------- balance sheet


def balance_equation(get, src, p, prior):
    a, l, e = get("total_assets", p["key"]), get("total_liabilities", p["key"]), get("total_equity", p["key"])
    le = get("total_liabilities_and_equity", p["key"])
    l_src = src("total_liabilities", p["key"]) or {}
    if a is None:
        return None
    if l is not None and e is not None and l_src.get("type") != "derived":
        ok = _close(a, l + e)
        return _result("Assets = Liabilities + Equity", "balance", p, ok,
                       f"Assets {_fmt(a)} vs Liabilities + Equity {_fmt(l + e)} (difference {_fmt(a - l - e)})",
                       ["total_assets", "total_liabilities", "total_equity"])
    if le is not None:  # liabilities not filed as a total, so compare against the filed L&E total
        return _result("Assets = Liabilities + Equity", "balance", p, _close(a, le),
                       f"Assets {_fmt(a)} vs Total Liabilities & Equity {_fmt(le)} (difference {_fmt(a - le)})",
                       ["total_assets", "total_liabilities_and_equity"])
    return None


def _foots(get, p, total_key, parts, name):
    total = get(total_key, p["key"])
    vals = {k: get(k, p["key"]) for k in parts}
    have = {k: v for k, v in vals.items() if v is not None}
    if total is None or len(have) < 2:
        return None
    s = sum(have.values())
    # The template shows the main components only, so they must not exceed the filed subtotal.
    ok = s <= total + max(1e6, 0.002 * abs(total))
    return _result(f"{name} foots", "balance", p, ok,
                   f"Listed components sum to {_fmt(s)} against a filed {name.lower()} of {_fmt(total)}",
                   [total_key, *have], [*have, total_key])


def current_assets_foot(get, src, p, prior):
    return _foots(get, p, "total_current_assets", ["cash", "st_investments", "accounts_receivable", "inventory"],
                  "Total Current Assets")


def total_assets_foot(get, src, p, prior):
    return _foots(get, p, "total_assets", ["total_current_assets", "ppe", "goodwill", "intangibles"], "Total Assets")


def current_liabilities_foot(get, src, p, prior):
    return _foots(get, p, "total_current_liabilities", ["accounts_payable", "st_debt"], "Total Current Liabilities")


def total_liabilities_foot(get, src, p, prior):
    return _foots(get, p, "total_liabilities", ["total_current_liabilities", "lt_debt"], "Total Liabilities")


# ---------------------------------------------------------------- income statement


def gross_profit_ties(get, src, p, prior):
    rev, cogs, gp = get("revenue", p["key"]), get("cogs", p["key"]), get("gross_profit", p["key"])
    if None in (rev, cogs, gp) or (src("gross_profit", p["key"]) or {}).get("type") == "derived":
        return None
    return _result("Gross Profit = Revenue − COGS", "income", p, _close(gp, rev - cogs),
                   f"Gross profit {_fmt(gp)} vs revenue − COGS {_fmt(rev - cogs)}", ["gross_profit", "revenue", "cogs"])


def ebitda_ties(get, src, p, prior):
    ebit, da, ebitda = get("ebit", p["key"]), get("da", p["key"]), get("ebitda", p["key"])
    if None in (ebit, da, ebitda):
        return None
    return _result("EBITDA = EBIT + D&A", "income", p, _close(ebitda, ebit + da),
                   f"EBITDA {_fmt(ebitda)} vs EBIT + D&A {_fmt(ebit + da)}", ["ebitda", "ebit", "da"], ["ebit", "da"])


# ---------------------------------------------------------------- cash flow


def fcf_ties(get, src, p, prior):
    cfo, capex, fcf = get("cfo", p["key"]), get("capex", p["key"]), get("fcf", p["key"])
    if None in (cfo, capex, fcf):
        return None
    return _result("Free Cash Flow = CFO − Capex", "cashflow", p, _close(fcf, cfo + capex),
                   f"FCF {_fmt(fcf)} vs CFO − Capex {_fmt(cfo + capex)}", ["fcf", "cfo", "capex"], ["cfo", "capex"])


def flows_sum_to_net_change(get, src, p, prior):
    cfo, cfi, cff, net = (get(k, p["key"]) for k in ("cfo", "cfi", "cff", "net_change_cash"))
    if None in (cfo, cfi, cff, net):
        return None
    fx = get("fx_effect", p["key"])
    excludes_fx = "ExcludingExchangeRate" in ((src("net_change_cash", p["key"]) or {}).get("tag") or "")
    s = cfo + cfi + cff + (0 if excludes_fx or fx is None else fx)
    ok = _close(s, net, rel=0.002, floor=2e6)
    fx_text = f" + FX {_fmt(fx)}" if fx is not None and not excludes_fx else ""
    return _result("CFO + CFI + CFF + FX = Net Change in Cash", "cashflow", p, ok,
                   f"Operating + investing + financing{fx_text} = {_fmt(s)} vs net change {_fmt(net)}",
                   ["cfo", "cfi", "cff", "fx_effect", "net_change_cash"])


def cash_reconciliation(get, src, p, prior):
    net, end = get("net_change_cash", p["key"]), get("cash_end_cf", p["key"])
    prev = prior.get("prev")
    start = get("cash_end_cf", prev["key"]) if prev else None
    if None in (net, end, start):
        return None
    return _result("Net change in cash ties to balance sheet cash", "cashflow", p, _close(end - start, net),
                   f"Ending cash {_fmt(end)} − prior {_fmt(start)} = {_fmt(end - start)} vs reported net change {_fmt(net)}",
                   ["net_change_cash", "cash_end_cf"])


def cash_within_total_cash(get, src, p, prior):
    cash, total = get("cash", p["key"]), get("cash_end_cf", p["key"])
    if None in (cash, total):
        return None
    return _result("Balance sheet cash ≤ cash incl. restricted", "cashflow", p,
                   cash <= total + max(1e6, 0.002 * abs(total)),
                   f"Balance sheet cash {_fmt(cash)} vs cash incl. restricted {_fmt(total)}", ["cash", "cash_end_cf"])


# ---------------------------------------------------------------- signs and plausibility

SIGN_RULES = {  # line: (statement, rule, description)
    "revenue": ("income", lambda v: v > 0, "positive"),
    "cogs": ("income", lambda v: v >= 0, "zero or positive (an expense)"),
    "sga": ("income", lambda v: v >= 0, "zero or positive (an expense)"),
    "rnd": ("income", lambda v: v >= 0, "zero or positive (an expense)"),
    "shares_diluted": ("income", lambda v: v > 0, "positive"),
    "total_assets": ("balance", lambda v: v > 0, "positive"),
    "total_current_assets": ("balance", lambda v: v > 0, "positive"),
    "capex": ("cashflow", lambda v: v <= 0, "zero or negative (a cash outflow)"),
}


def sign_checks(get, src, p, prior):
    out = []
    for key, (st, rule, desc) in SIGN_RULES.items():
        v = get(key, p["key"])
        if v is not None:
            out.append(_result(f"Sign of {key.replace('_', ' ')}", st, p, rule(v),
                               f"{key.replace('_', ' ').title()} is {_fmt(v)}; it should be {desc}", [key]))
    return out


JUMP_LINES = {"revenue": "income", "total_assets": "balance"}


def yoy_jumps(get, src, p, prior):
    """A line that triples or falls by two-thirds year over year usually means a unit or tag error."""
    out = []
    prior = prior.get("yoy")
    if prior is None:
        return out
    for key, st in JUMP_LINES.items():
        v, pv = get(key, p["key"]), get(key, prior["key"])
        if v is None or not pv or v <= 0 or pv <= 0:
            continue
        ratio = v / pv
        out.append(_result(f"Year-over-year change in {key.replace('_', ' ')}", st, p, 1 / 3 <= ratio <= 3,
                           f"{key.replace('_', ' ').title()} moved from {_fmt(pv)} ({prior['label']}) to {_fmt(v)}: "
                           f"{ratio:.1f}x", [key]))
    return out


# Grouped by the Checker tool that runs them.
BALANCE_SHEET_CHECKS = (balance_equation, current_assets_foot, total_assets_foot, current_liabilities_foot,
                        total_liabilities_foot)
SUBTOTAL_CHECKS = {"income": (gross_profit_ties, ebitda_ties), "cashflow": (fcf_ties, flows_sum_to_net_change),
                   "balance": ()}
CASH_CHECKS = (cash_reconciliation, cash_within_total_cash)
PLAUSIBILITY_CHECKS = (sign_checks, yoy_jumps)


def as_list(r) -> list:
    return [] if r is None else r if isinstance(r, list) else [r]
