"""Summarize every logged model call (logs/tokens.jsonl) for the report.

    python scripts/token_report.py [path/to/tokens.jsonl]

Tables: by agent, spread runs vs chat questions (per run), Harvey vs Mike, optimizations on vs off.
Also writes logs/token_report.md.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from specter.llm import cost_usd  # noqa: E402


def table(title: str, groups: dict, per_run: bool = False) -> list[str]:
    head = "| Group | Runs | Calls | Input | Cached | Output | Cost |" if per_run else \
        "| Group | Calls | Input | Cached | Output | Cost |"
    out = [f"## {title}", "", head, "|" + "|".join(["---"] * (head.count("|") - 1)) + "|"]
    for name, recs in sorted(groups.items()):
        calls = sum(1 for r in recs if not r["model_cache_hit"])
        tin, tc, tout = (sum(r[k] for r in recs) for k in ("input_tokens", "cached_input_tokens", "output_tokens"))
        # Re-priced from the logged token counts with the current config prices, so older entries
        # (logged under different prices) are comparable.
        cost = sum(cost_usd(r["input_tokens"], r["cached_input_tokens"], r["output_tokens"]) for r in recs)
        if per_run:
            runs = len({r["run_id"] for r in recs}) or 1
            out.append(f"| {name} | {runs} | {calls / runs:.1f} | {tin / runs:,.0f} | {tc / runs:,.0f} | {tout / runs:,.0f} | "
                       f"${cost / runs:.4f} |")
        else:
            out.append(f"| {name} | {calls} | {tin:,} | {tc:,} | {tout:,} | ${cost:.4f} |")
    return out + [""]


def main(path: Path) -> None:
    recs = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not recs:
        print("No records yet. Use the app (or run scripts/cost_compare.py) first.")
        return
    lines = [f"# Token usage report", "", f"{len(recs)} logged model calls from `{path.name}` "
             f"({recs[0]['ts']} to {recs[-1]['ts']}). Per-run tables average over runs.", ""]
    lines += table("By agent (totals)", _group(recs, lambda r: r["agent"]))
    lines += table("Spread runs vs chat questions (average per run)",
                   _group(recs, lambda r: "spread build" if "spread" in r["run_kind"] else "chat turn" if "chat" in r["run_kind"]
                      else r["run_kind"]), per_run=True)
    chat = [r for r in recs if "chat" in r["run_kind"]]
    lines += table("Harvey vs Mike (chat turns, average per run)", _group(chat, lambda r: r["persona"]), per_run=True)
    lines += table("Optimizations on vs off (average per run)",
                   _group(recs, lambda r: "optimized" if r["optimized"] else "baseline"), per_run=True)
    text = "\n".join(lines)
    print(text)
    (config.LOG_DIR / "token_report.md").write_text(text + "\n", encoding="utf-8")
    print("Saved logs/token_report.md")


def _group(recs, key):
    g = defaultdict(list)
    for r in recs:
        g[key(r)].append(r)
    return g


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else config.LOG_DIR / "tokens.jsonl")
