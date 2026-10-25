"""Bundle one company's EDGAR data into data/sample/ so the app runs offline.

    python scripts/make_sample.py AAPL

Copies the SEC ticker list, plus the company's Company Facts (trimmed to the concepts the
template uses) and its filing index (trimmed to 10-K/10-Q rows). File names match cache/edgar/,
so the app reads them the same way in SPECTER_DATA_MODE=sample.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from specter import edgar, mdna, template  # noqa: E402


def main(ticker: str) -> None:
    out = config.SAMPLE_DIR
    out.mkdir(parents=True, exist_ok=True)
    company = edgar.lookup_cik(ticker)
    cik = company["cik"]

    (out / "company_tickers.json").write_bytes((edgar.EDGAR_CACHE / "company_tickers.json").read_bytes())

    facts = edgar.get_company_facts(cik)
    keep = template.all_tags()
    facts["facts"] = {"us-gaap": {k: v for k, v in facts["facts"]["us-gaap"].items() if k in keep}}
    (out / f"companyfacts_CIK{cik}.json").write_text(json.dumps(facts, separators=(",", ":")))

    subs = edgar._submissions_page(f"CIK{cik}.json")
    recent = subs["filings"]["recent"]
    rows = [i for i, form in enumerate(recent["form"]) if form in ("10-K", "10-Q")]
    subs["filings"] = {"recent": {k: [v[i] for i in rows] for k, v in recent.items()}, "files": []}
    (out / f"submissions_CIK{cik}.json").write_text(json.dumps(subs, separators=(",", ":")))

    # MD&A chunks for the last 10 annual reports, so the Analyst also works offline.
    (out / "mdna").mkdir(exist_ok=True)
    for filing in edgar.list_filings(cik, "10-K", 10):
        chunks = mdna.load_chunks(cik, filing, f"{filing['report_date']} 10-K, MD&A")
        if chunks:
            name = f"mdna_{cik}_{filing['accession']}.json"
            (out / "mdna" / name).write_text(json.dumps(chunks), encoding="utf-8")

    for f in sorted(p for p in out.rglob("*") if p.is_file()):
        print(f"{str(f.relative_to(out)):60s} {f.stat().st_size / 1024:8.0f} KB")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "AAPL")
