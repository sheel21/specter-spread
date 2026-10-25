"""Spreader Agent: maps XBRL tags onto the banker template and fills every line for every period.

The mapping runs in plain Python (prioritized tag lists in template.py). write_line_item refuses
any value that does not match what the company actually filed under the cited tag, so nothing
can enter the spread without a source.
"""

from specter import template
from specter.xbrl import FactIndex, resolve, value_for_tag

RATIOS = [
    ("revenue_growth", "Revenue Growth %"),
    ("gross_margin", "Gross Margin %"),
    ("ebit_margin", "Operating Margin %"),
    ("ebitda_margin", "EBITDA Margin %"),
    ("net_margin", "Net Margin %"),
]


class Spreader:
    name = "Spreader"
    TOOLS = ("get_facts_for_concept", "write_line_item")

    def __init__(self, idx: FactIndex, emit):
        self.idx = idx
        self.emit = emit
        self.cells: dict[tuple[str, str], dict] = {}  # (line key, period key) -> {"v", "src"}
        self.periods: dict[str, dict] = {}

    # ------------------------------------------------------------ tools

    def get_facts_for_concept(self, concept_list: list[str], periods: list[dict], line_item: str) -> dict:
        """What the company filed under each candidate tag, per period (for tag-mapping decisions)."""
        item = template.ITEMS[line_item]
        out = {}
        for p in periods:
            out[p["key"]] = {}
            for tag in concept_list:
                hit = value_for_tag(self.idx, tag, item, p) if self.idx.has(tag) else None
                out[p["key"]][tag] = hit[0] if hit else None
        return out

    def write_line_item(self, statement: str, label: str, period: str, value: float, source_tag: str) -> dict:
        """Write one cell, only if `value` is what the filing reports under `source_tag` for `period`."""
        item = next((i for i in template.ITEMS.values() if i["statement"] == statement and i["label"] == label), None)
        if item is None:
            return {"ok": False, "error": f"Unknown line item {statement}/{label}."}
        p = self.periods.get(period)
        if p is None:
            return {"ok": False, "error": f"Unknown period {period}."}
        hit = value_for_tag(self.idx, source_tag.removeprefix("us-gaap:"), item, p)
        if hit is None or abs(hit[0] - value) > 0.5:
            return {"ok": False, "error": f"{source_tag} does not report {value} for {period}; nothing written."}
        self._set(item["key"], period, hit[0], hit[1])
        return {"ok": True}

    # ------------------------------------------------------------ the deterministic pass

    def _set(self, key: str, period: str, value, source: dict | None) -> None:
        self.cells[(key, period)] = {"v": value, "src": source}

    def fill(self, periods: list[dict]) -> None:
        """Fill every template line for every period: filed tags first, then derived lines."""
        self.periods.update({p["key"]: p for p in periods})
        for st, items in template.TEMPLATE.items():
            filled = 0
            for item in items:
                if not (item["tags"] or item["sum_of"]):
                    continue
                for p in periods:
                    hit = resolve(self.idx, item, p)
                    if hit:
                        self._set(item["key"], p["key"], *hit)
                        filled += 1
            self.emit(self.name, "write_line_item", f"{template.STATEMENTS[st]}: wrote {filled} cells from filed tags.")

        derived = sum(self.rederive(p["key"]) for p in periods)
        self.emit(self.name, "write_line_item", f"Derived {derived} cells (gross profit, EBITDA, FCF, etc.).")

    def rederive(self, period: str) -> int:
        """(Re)compute derived lines for one period: ones still empty, or previously derived."""
        n = 0
        for item in template.ITEMS.values():
            if not item["derive"]:
                continue
            cur = self.cells.get((item["key"], period))
            if cur and cur["v"] is not None and (cur["src"] or {}).get("type") != "derived":
                continue  # filed value wins over derivation
            formula, fn = item["derive"]
            values = {k: c["v"] for (k, pk), c in self.cells.items() if pk == period and c["v"] is not None}
            try:
                v = fn(values)
            except KeyError:  # an input is N/A, so the derived line is N/A too
                if cur:
                    self._set(item["key"], period, None, None)
                continue
            self._set(item["key"], period, v, {"type": "derived", "formula": formula})
            n += 1
        return n

    def view(self, periods: list[dict], display: int) -> dict:
        """Rows for the last `display` periods (earlier periods are only used for growth rates)."""
        shown = periods[-display:]

        def cell(key, pk):
            return self.cells.get((key, pk), {"v": None, "src": None})

        statements = {
            st: [{"key": i["key"], "label": i["label"], "kind": i["kind"], "unit": i["unit"],
                  "cells": {p["key"]: cell(i["key"], p["key"]) for p in shown}} for i in items]
            for st, items in template.TEMPLATE.items()
        }
        return {"periods": [_period_json(p) for p in shown], "statements": statements,
                "ratios": self._ratios(periods, shown)}

    def _ratios(self, periods: list[dict], shown: list[dict]) -> list[dict]:
        def v(key, p):
            return self.cells.get((key, p["key"]), {}).get("v") if p else None

        def div(a, b):
            return a / b if a is not None and b not in (None, 0) else None

        by_key = {p["key"]: p for p in periods}
        rows = {k: {} for k, _ in RATIOS}
        for p in shown:
            prior_key = f"FY{p['fy'] - 1}" + (f"Q{p['fq']}" if p["fq"] else "")  # YoY, also for quarters
            prior = by_key.get(prior_key)
            rev, prev_rev = v("revenue", p), v("revenue", prior)
            rows["revenue_growth"][p["key"]] = div(rev, prev_rev) - 1 if div(rev, prev_rev) is not None else None
            rows["gross_margin"][p["key"]] = div(v("gross_profit", p), rev)
            rows["ebit_margin"][p["key"]] = div(v("ebit", p), rev)
            rows["ebitda_margin"][p["key"]] = div(v("ebitda", p), rev)
            rows["net_margin"][p["key"]] = div(v("net_income", p), rev)
        return [{"key": k, "label": label, "kind": "ratio", "unit": "pct",
                 "cells": {pk: {"v": val, "src": {"type": "ratio"}} for pk, val in rows[k].items()}}
                for k, label in RATIOS]


def _period_json(p: dict) -> dict:
    return {"key": p["key"], "label": p["label"], "fy": p["fy"], "fq": p["fq"],
            "start": p["start"].isoformat(), "end": p["end"].isoformat()}
