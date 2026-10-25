"""Plain-Python XBRL work: index Company Facts, find fiscal periods, and pull one value per period.

No model calls here. Every value returned comes with a source record pointing at the exact
us-gaap tag and filing (accession number) it came from.
"""

from collections import Counter
from datetime import date, timedelta

from specter.edgar import filing_url, pad_cik

UNIT_KEYS = {"usd": ("USD",), "per_share": ("USD/shares",), "shares": ("shares",)}
# Concepts nearly every filer reports each period; used to discover fiscal years and quarters.
PERIOD_TAGS = ("NetIncomeLoss", "ProfitLoss", "RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
               "OperatingIncomeLoss")
START_TOLERANCE_DAYS = 7


def _d(s: str) -> date:
    return date.fromisoformat(s)


class FactIndex:
    """us-gaap facts from 10-K/10-Q filings, indexed by (tag, unit) and period end date."""

    def __init__(self, companyfacts: dict, cik: str):
        self.cik = pad_cik(cik)
        self.gaap = companyfacts.get("facts", {}).get("us-gaap", {})
        self._by_end: dict[tuple, dict[date, list]] = {}

    def has(self, tag: str) -> bool:
        return tag in self.gaap

    def facts(self, tag: str, unit: str) -> dict[date, list[dict]]:
        key = (tag, unit)
        if key not in self._by_end:
            units = self.gaap.get(tag, {}).get("units", {})
            by_end: dict[date, list] = {}
            for unit_name in UNIT_KEYS[unit]:
                for f in units.get(unit_name, []):
                    form = f.get("form", "")
                    if not form.startswith(("10-K", "10-Q")):
                        continue
                    fact = {
                        "tag": tag, "val": f["val"], "start": _d(f["start"]) if f.get("start") else None,
                        "end": _d(f["end"]), "accn": f["accn"], "form": form, "filed": f["filed"],
                        "fy": f.get("fy"), "fp": f.get("fp"),
                    }
                    by_end.setdefault(fact["end"], []).append(fact)
            self._by_end[key] = by_end
        return self._by_end[key]

    def find(self, tag: str, unit: str, start: date | None, end: date, prefer: str = "") -> dict | None:
        """The fact for exactly this period (start=None means a point-in-time balance).

        If several filings report it (original plus later comparatives/restatements), facts from the
        `prefer` form type win, then the most recently filed.
        """
        best = None
        for f in self.facts(tag, unit).get(end, []):
            if start is None:
                if f["start"] is not None:
                    continue
            elif f["start"] is None or abs((f["start"] - start).days) > START_TOLERANCE_DAYS:
                continue
            if best is None or (f["form"].startswith(prefer), f["filed"]) > (best["form"].startswith(prefer), best["filed"]):
                best = f
        return best

    def source(self, fact: dict, sign: int = 1) -> dict:
        """A traceable source record for one fact."""
        return {
            "type": "xbrl", "tag": f"us-gaap:{fact['tag']}", "filed_value": fact["val"], "sign_flipped": sign == -1,
            "accn": fact["accn"], "form": fact["form"], "filed": fact["filed"], "fy": fact["fy"], "fp": fact["fp"],
            "period": (f"{fact['start']} to {fact['end']}" if fact["start"] else f"as of {fact['end']}"),
            "url": filing_url(self.cik, fact["accn"], f"{fact['accn']}-index.htm"),
        }


# ---------------------------------------------------------------- fiscal periods


def annual_periods(idx: FactIndex) -> list[dict]:
    """Every fiscal year the company reported in a 10-K, oldest first."""
    by_end: dict[date, dict] = {}
    for tag in PERIOD_TAGS:
        for end, facts in idx.facts(tag, "usd").items():
            for f in facts:
                if not f["form"].startswith("10-K") or f["start"] is None:
                    continue
                if not 350 <= (f["end"] - f["start"]).days <= 380:
                    continue
                e = by_end.setdefault(end, {"starts": Counter(), "first": f})
                e["starts"][f["start"]] += 1
                if f["filed"] < e["first"]["filed"]:
                    e["first"] = f

    # Label each year with the company's own fiscal year. The earliest 10-K reporting a period is
    # normally that year's own 10-K, except in the first XBRL year (only comparatives exist), so walk
    # newest to oldest and never let two periods share a label.
    periods, next_label = [], None
    for end in sorted(by_end, reverse=True):
        e = by_end[end]
        fy = e["first"]["fy"]
        if not isinstance(fy, int) or abs(fy - end.year) > 1:
            fy = end.year - (1 if end.month == 1 and end.day <= 10 else 0)
        if next_label is not None:
            fy = min(fy, next_label - 1)
        next_label = fy
        periods.append({"key": f"FY{fy}", "label": f"FY{fy}", "fy": fy, "fq": None,
                        "start": e["starts"].most_common(1)[0][0], "end": end, "kind": "annual"})
    return periods[::-1]


def quarterly_periods(idx: FactIndex, annual: list[dict]) -> list[dict]:
    """Fiscal quarters (Q1..Q4) inside each fiscal year, oldest first. Q4 ends on the fiscal year end."""
    q_ends: set[date] = set()
    for tag in PERIOD_TAGS:
        for end, facts in idx.facts(tag, "usd").items():
            if any(f["form"].startswith("10-Q") and f["start"] and 80 <= (f["end"] - f["start"]).days <= 100
                   for f in facts):
                q_ends.add(end)

    out = []
    years = [(y, sorted(e for e in q_ends if y["start"] < e < y["end"] - timedelta(days=30)) + [y["end"]])
             for y in annual]
    current = None
    if annual:
        # The fiscal year in progress has 10-Qs but no 10-K yet; include its quarters too.
        last = annual[-1]
        current = {"fy": last["fy"] + 1, "start": last["end"] + timedelta(days=1)}
        ends = sorted(e for e in q_ends if e > last["end"])[:3]
        if ends:
            years.append((current, ends))
    for year, ends in years:
        if len(ends) != 4 and year is not current:
            continue  # incomplete or irregular year (e.g. a fiscal year change): skip rather than mislabel
        start = year["start"]
        for n, end in enumerate(ends, 1):
            out.append({"key": f"FY{year['fy']}Q{n}", "label": f"Q{n} FY{year['fy'] % 100:02d}", "fy": year["fy"],
                        "fq": n, "start": start, "end": end, "kind": "quarter",
                        "fy_start": year["start"], "prev_end": ends[n - 2] if n > 1 else None})
            start = end + timedelta(days=1)
    return out


# ---------------------------------------------------------------- one value for one period


def value_for_tag(idx: FactIndex, tag: str, item: dict, period: dict) -> tuple[float, dict] | None:
    """(value, source) for one tag in one period, or None if the company did not file it."""
    unit, sign = item["unit"], item["sign"]
    prefer = "10-K" if period["kind"] == "annual" else ""
    if item["period"] == "instant":
        f = idx.find(tag, unit, None, period["end"], prefer)
        return (f["val"] * sign, idx.source(f, sign)) if f else None

    f = idx.find(tag, unit, period["start"], period["end"], prefer)
    if f:
        return f["val"] * sign, idx.source(f, sign)
    if period["kind"] != "quarter" or unit != "usd" or period["fq"] == 1:
        return None
    # 10-Qs report cash flows year-to-date and 10-Ks have no Q4 column, so a quarter is
    # (YTD through this quarter) - (YTD through last quarter). Not valid for EPS or share counts.
    cur = idx.find(tag, unit, period["fy_start"], period["end"])
    prev = idx.find(tag, unit, period["fy_start"], period["prev_end"])
    if not (cur and prev):
        return None
    months = {2: "6M", 3: "9M", 4: "12M"}
    return (cur["val"] - prev["val"]) * sign, {
        "type": "ytd_difference", "tag": f"us-gaap:{tag}", "sign_flipped": sign == -1,
        "formula": f"{months[period['fq']]} YTD − {months[period['fq'] - 1] if period['fq'] > 2 else '3M'} YTD",
        "parts": [idx.source(cur, sign), idx.source(prev, sign)],
    }


def filed_versions(idx: FactIndex, tag: str, item: dict, period: dict) -> list[tuple[float, dict]]:
    """Every distinct value filed for exactly this period under `tag` (original vs. restated), newest first."""
    start = None if item["period"] == "instant" else period["start"]
    seen: dict[float, dict] = {}
    for f in idx.facts(tag, item["unit"]).get(period["end"], []):
        if start is None and f["start"] is not None:
            continue
        if start is not None and (f["start"] is None or abs((f["start"] - start).days) > START_TOLERANCE_DAYS):
            continue
        if f["val"] not in seen or f["filed"] > seen[f["val"]]["filed"]:
            seen[f["val"]] = f
    facts = sorted(seen.values(), key=lambda f: f["filed"], reverse=True)
    return [(f["val"] * item["sign"], idx.source(f, item["sign"])) for f in facts]


def resolve(idx: FactIndex, item: dict, period: dict) -> tuple[float, dict] | None:
    """Try the item's tags in priority order, then its sum-of-components fallback."""
    for tag in item["tags"]:
        hit = value_for_tag(idx, tag, item, period)
        if hit:
            return hit
    if item["sum_of"]:
        parts = []
        for group in item["sum_of"]:
            for tag in group:
                hit = value_for_tag(idx, tag, item, period)
                if hit:
                    parts.append(hit)
                    break
        if parts:
            return sum(v for v, _ in parts), {
                "type": "sum", "tag": " + ".join(src["tag"] for _, src in parts),
                "formula": " + ".join(src["tag"].split(":")[1] for _, src in parts),
                "parts": [src for _, src in parts],
            }
    return None
