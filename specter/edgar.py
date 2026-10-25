"""SEC EDGAR client: polite (throttled, identified), cached on disk, with an offline sample fallback.

Every download is saved under cache/edgar/ with the same file name the bundled sample uses
(data/sample/), so the sample is simply a copy of cached files for one company.
"""

import json
import threading
import time
from datetime import date
from pathlib import Path

import requests

import config

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/{name}"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{doc}"

EDGAR_CACHE = config.CACHE_DIR / "edgar"


class EdgarError(RuntimeError):
    """EDGAR could not provide the data (network down, unknown company, etc.)."""


# ---------------------------------------------------------------- polite HTTP


class _Throttle:
    """Spaces requests so we never exceed SEC_MAX_REQUESTS_PER_SECOND across all threads."""

    def __init__(self, per_second: float):
        self.interval = 1.0 / per_second
        self.lock = threading.Lock()
        self.next_ok = 0.0

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            delay = self.next_ok - now
            self.next_ok = max(now, self.next_ok) + self.interval
        if delay > 0:
            time.sleep(delay)


_throttle = _Throttle(config.SEC_MAX_REQUESTS_PER_SECOND)
_session = requests.Session()
_session.headers.update({"User-Agent": config.SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"})

# Counts what actually happened, so the UI and the cost report can show cache effectiveness.
stats = {"http_requests": 0, "cache_hits": 0, "sample_hits": 0}


def _http_get(url: str) -> bytes:
    last_error = None
    for attempt in range(3):
        _throttle.wait()
        stats["http_requests"] += 1
        try:
            resp = _session.get(url, timeout=config.SEC_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            last_error = exc
        else:
            if resp.status_code == 200:
                return resp.content
            if resp.status_code == 404:
                raise EdgarError(f"EDGAR has no document at {url}")
            last_error = EdgarError(f"EDGAR returned HTTP {resp.status_code} for {url}")
        time.sleep(1.5 * (attempt + 1))  # back off on 429/5xx/network errors
    raise EdgarError(f"EDGAR unreachable: {last_error}")


# ---------------------------------------------------------------- cache layer


def _fresh(path: Path, kind: str) -> bool:
    if not path.is_file():
        return False
    age_hours = (time.time() - path.stat().st_mtime) / 3600
    return age_hours < config.CACHE_MAX_AGE_HOURS[kind]


def _fetch(kind: str, filename: str, url: str, as_json: bool = True):
    """Return a document from: fresh cache -> live EDGAR -> stale cache -> bundled sample."""
    cached = EDGAR_CACHE / filename
    sample = config.SAMPLE_DIR / filename
    mode = config.DATA_MODE

    def parse(raw: bytes):
        return json.loads(raw) if as_json else raw.decode("utf-8", errors="replace")

    if mode == "sample":
        if sample.is_file():
            stats["sample_hits"] += 1
            return parse(sample.read_bytes())
        raise EdgarError(f"Sample mode: {filename} is not in data/sample/. Only the bundled company works offline.")

    if _fresh(cached, kind):
        stats["cache_hits"] += 1
        return parse(cached.read_bytes())
    try:
        raw = _http_get(url)
        data = parse(raw)  # validate before caching
    except EdgarError:
        if mode == "live":
            if cached.is_file():
                stats["cache_hits"] += 1
                return parse(cached.read_bytes())
            raise
        for fallback in (cached, sample):
            if fallback.is_file():
                stats["sample_hits" if fallback == sample else "cache_hits"] += 1
                return parse(fallback.read_bytes())
        raise
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(raw)
    return data


# ---------------------------------------------------------------- public API


def pad_cik(cik: int | str) -> str:
    return str(int(cik)).zfill(10)


def load_tickers() -> dict[str, dict]:
    """Ticker -> {cik, name} for every company in the SEC ticker list."""
    raw = _fetch("tickers", "company_tickers.json", TICKERS_URL)
    return {row["ticker"].upper(): {"cik": pad_cik(row["cik_str"]), "name": row["title"]} for row in raw.values()}


def lookup_cik(ticker: str) -> dict:
    """Resolve a ticker to {ticker, cik, name}. Raises EdgarError if the SEC list does not have it."""
    ticker = ticker.upper()
    info = load_tickers().get(ticker)
    if info is None:
        raise EdgarError(f"{ticker} is not in the SEC ticker list.")
    return {"ticker": ticker, **info}


def get_company_facts(cik: str) -> dict:
    """All XBRL facts the company has filed (the XBRL Company Facts API)."""
    cik = pad_cik(cik)
    return _fetch("companyfacts", f"companyfacts_CIK{cik}.json", FACTS_URL.format(cik=cik))


def _submissions_page(name: str) -> dict:
    return _fetch("submissions", f"submissions_{name}", SUBMISSIONS_URL.format(name=name))


def list_filings(cik: str, form_type: str = "10-K", years: int = 5) -> list[dict]:
    """10-K and/or 10-Q filings from the last `years` years, newest first.

    form_type: "10-K", "10-Q", or "both". Amendments (10-K/A) are skipped; their numbers
    already appear in Company Facts with a later filing date.
    """
    cik = pad_cik(cik)
    forms = {"10-K", "10-Q"} if form_type == "both" else {form_type}
    cutoff = date(date.today().year - years - 1, 1, 1).isoformat()

    first = _submissions_page(f"CIK{cik}.json")
    pages = [first["filings"]["recent"]]
    # Busy filers push older 10-Ks out of "recent"; follow the older pages only as far as needed.
    for extra in first["filings"].get("files", []):
        if extra.get("filingTo", "") < cutoff:
            continue
        try:
            pages.append(_submissions_page(extra["name"]))
        except EdgarError:
            break

    out = []
    for page in pages:
        for i, form in enumerate(page["form"]):
            if form not in forms or page["filingDate"][i] < cutoff:
                continue
            acc = page["accessionNumber"][i]
            doc = page["primaryDocument"][i]
            out.append({
                "form": form,
                "accession": acc,
                "filing_date": page["filingDate"][i],
                "report_date": page["reportDate"][i],
                "primary_document": doc,
                "url": filing_url(cik, acc, doc),
            })
    out.sort(key=lambda f: f["filing_date"], reverse=True)
    return out


def filing_url(cik: str, accession: str, doc: str = "") -> str:
    return ARCHIVE_URL.format(cik_int=int(cik), acc_nodash=accession.replace("-", ""), doc=doc)


def company_name(cik: str) -> str:
    return get_company_facts(cik).get("entityName", "")
