"""Cost vs. accuracy: the same scripted session with optimizations ON and OFF.

    python scripts/cost_compare.py

Scenario (identical in both modes, each mode starts with an empty model cache):
  1. Spread COST, 10 years annual            (real Checker flag: FY2019 gross profit tag)
  2. Spread AAPL, 5 years annual, with total assets for FY2023 corrupted x1000
  3. Harvey: "Why did gross margin improve between FY2023 and FY2025?"
  4. Harvey: "What does management say about supply chain and component risks?"
  5. Mike:   the step-3 question in a fresh session with the same state (persona switch; with
             optimizations ON the persona-free facts are reused from cache, so they match exactly)

OFF = no model-result or MD&A caches, the Analyst gets the whole MD&A, and the model audits the
spread arithmetic itself (scored against the Python checks). Writes logs/cost_comparison.md.
"""

import copy
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from specter import llm, mdna  # noqa: E402
from specter.agents.spreader import Spreader  # noqa: E402
from specter.chat import handle_message  # noqa: E402
from specter.llm import RunBudget, RunCtx, summarize  # noqa: E402
from specter.pipeline import build_spread  # noqa: E402

Q_MARGIN = "Why did gross margin improve between FY2023 and FY2025?"
Q_SUPPLY = "What does management say about supply chain and component risks?"


def run_mode(optimized: bool) -> dict:
    config.OPTIMIZED = optimized
    tag = "on" if optimized else "off"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    # Fresh, empty caches for this mode, so the comparison starts cold.
    llm.MODEL_CACHE = config.CACHE_DIR / f"compare-{stamp}-{tag}" / "model"
    mdna.MDNA_CACHE = config.CACHE_DIR / f"compare-{stamp}-{tag}" / "mdna"
    big = RunBudget(max_tokens=400_000, max_calls=40)  # the baseline must be allowed to finish
    steps, all_records = [], []

    def record(name, c, started, extra):
        t = summarize(c.records)["total"]
        steps.append({"step": name, "seconds": round(time.time() - started, 1), **t, **extra})
        all_records.extend(c.records)
        print(f"  [{tag}] {name}: {t['input_tokens']:,} in / {t['cached_input_tokens']:,} cached / "
              f"{t['output_tokens']:,} out, ${t['cost_usd']:.4f}", flush=True)

    c = RunCtx(kind="compare-spread", session_id=f"compare-{tag}", budget=copy.deepcopy(big))
    t0 = time.time()
    cost = build_spread("COST", 10, "annual", c)
    record("Spread COST 10y", c, t0, _check_stats(cost))

    real_fill = Spreader.fill

    def corrupt(self, periods):
        real_fill(self, periods)
        cell = self.cells.get(("total_assets", "FY2023"))
        if cell:
            cell["v"] *= 1000

    Spreader.fill = corrupt
    try:
        c = RunCtx(kind="compare-spread", session_id=f"compare-{tag}", budget=copy.deepcopy(big))
        t0 = time.time()
        aapl = build_spread("AAPL", 5, "annual", c)
    finally:
        Spreader.fill = real_fill
    record("Spread AAPL 5y (corrupted)", c, t0, _check_stats(aapl))

    fresh = {"spread": build_spread("AAPL", 5, "annual", RunCtx(kind="compare-setup"))}
    session, answers = copy.deepcopy(fresh), {}
    for name, persona, q in (("Q1 margin (Harvey)", "harvey", Q_MARGIN), ("Q2 supply chain (Harvey)", "harvey", Q_SUPPLY),
                             ("Q1 margin, new session (Mike)", "mike", Q_MARGIN)):
        if "Mike" in name:
            session = copy.deepcopy(fresh)  # same state Harvey had when asking Q1
        c = RunCtx(kind="compare-chat", session_id=f"compare-{tag}", persona=persona, budget=copy.deepcopy(big))
        t0 = time.time()
        reply = handle_message(q, session, c)
        a = reply.get("answer") or {}
        au = a.get("audit", {})
        record(name, c, t0, {"kind": reply["kind"], "quotes_verified": au.get("quotes_verified"),
                             "quotes_removed": au.get("quotes_removed"),
                             "figures_traced": f"{au.get('figures', {}).get('traced', 0)}/{au.get('figures', {}).get('total', 0)}",
                             "headline": a.get("headline", reply.get("text", ""))[:160]})
        answers[name] = a
    return {"mode": tag, "steps": steps, "by_agent": summarize(all_records)["by_agent"],
            "total": summarize(all_records)["total"],
            "persona_identical": all(answers["Q1 margin (Harvey)"].get(k) == answers["Q1 margin, new session (Mike)"].get(k)
                                     for k in ("numbers_show", "management_says"))}


def _check_stats(spread: dict) -> dict:
    res = spread["checks"]["annual"]
    out = {"checks": f"{res['counts']['passed']} passed / {res['counts']['fixed']} fixed / {res['counts']['flagged']} flagged"}
    if "llm_audit" in res:
        a = res["llm_audit"]
        out["model_audit"] = (f"model flagged {len(a.get('model_reported', []))}, Python {len(a.get('python_failures', []))}, "
                              f"agreed {a.get('agreed')}, false alarms {a.get('false_alarms')}, missed {a.get('missed')}"
                              if "error" not in a else a["error"])
    return out


def to_markdown(results: list[dict]) -> str:
    p = config.PRICE_PER_MILLION
    lines = [f"# Cost vs. accuracy: optimizations ON vs OFF", "",
             f"Generated {datetime.now():%Y-%m-%d %H:%M}. Model {config.MODEL} via Portkey. Prices used ($/1M tokens): "
             f"input {p['input']}, cached input {p['cached_input']}, output {p['output']} (see config.py).", ""]
    for r in results:
        lines += [f"## Optimizations {r['mode'].upper()}", "",
                  "| Step | Input | Cached | Output | Calls | Cost | Seconds | Accuracy |", "|---|---|---|---|---|---|---|---|"]
        for s in r["steps"]:
            acc = s.get("checks") or f"quotes verified {s.get('quotes_verified')}, removed {s.get('quotes_removed')}, figures {s.get('figures_traced')}"
            if s.get("model_audit"):
                acc += f"; model audit: {s['model_audit']}"
            lines.append(f"| {s['step']} | {s['input_tokens']:,} | {s['cached_input_tokens']:,} | {s['output_tokens']:,} | "
                         f"{s['calls']} (+{s['cache_hits']} cached) | ${s['cost_usd']:.4f} | {s['seconds']} | {acc} |")
        t = r["total"]
        lines += [f"| **Total** | **{t['input_tokens']:,}** | **{t['cached_input_tokens']:,}** | **{t['output_tokens']:,}** | "
                  f"**{t['calls']}** | **${t['cost_usd']:.4f}** | | Harvey/Mike facts identical: {r['persona_identical']} |", "",
                  "| Agent | Calls | Input | Cached | Output | Cost |", "|---|---|---|---|---|---|"]
        for agent, b in r["by_agent"].items():
            lines.append(f"| {agent} | {b['calls']} | {b['input_tokens']:,} | {b['cached_input_tokens']:,} | "
                         f"{b['output_tokens']:,} | ${b['cost_usd']:.4f} |")
        lines.append("")
    on, off = (next(r for r in results if r["mode"] == m)["total"] for m in ("on", "off"))
    if off["cost_usd"]:
        lines += [f"**Savings:** optimizations cut cost by {100 * (1 - on['cost_usd'] / off['cost_usd']):.0f}% "
                  f"(${off['cost_usd']:.4f} → ${on['cost_usd']:.4f}) and input tokens by "
                  f"{100 * (1 - on['input_tokens'] / max(1, off['input_tokens'])):.0f}%.", ""]
    lines += ["Headlines (for a side-by-side quality read):", ""]
    for r in results:
        for s in r["steps"]:
            if s.get("headline"):
                lines.append(f"- [{r['mode']}] {s['step']}: {s['headline']}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    print("Running the scenario with optimizations ON, then OFF (about 3-6 minutes)…")
    results = [run_mode(True), run_mode(False)]
    config.LOG_DIR.mkdir(exist_ok=True)
    md = to_markdown(results)
    (config.LOG_DIR / "cost_comparison.md").write_text(md, encoding="utf-8")
    (config.LOG_DIR / "cost_comparison.json").write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    print("\n" + md)
    print(f"Saved logs/cost_comparison.md and logs/cost_comparison.json")
