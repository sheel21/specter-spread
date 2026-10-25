"""Fetcher Agent: pulls raw EDGAR data for one company. Whitelisted tools only."""

from specter import edgar


class Fetcher:
    name = "Fetcher"
    TOOLS = ("lookup_cik", "get_company_facts", "list_filings")

    def __init__(self, emit):
        self.emit = emit

    def lookup_cik(self, ticker: str) -> dict:
        self.emit(self.name, "lookup_cik", f"Pulling the file on {ticker}…")
        company = edgar.lookup_cik(ticker)
        self.emit(self.name, "lookup_cik", f"{ticker} is {company['name']} (CIK {company['cik']}).")
        return company

    def get_company_facts(self, cik: str) -> dict:
        self.emit(self.name, "get_company_facts", "Requesting the XBRL Company Facts from EDGAR…")
        facts = edgar.get_company_facts(cik)
        n = len(facts.get("facts", {}).get("us-gaap", {}))
        self.emit(self.name, "get_company_facts", f"Received {n} us-gaap concepts.")
        return facts

    def list_filings(self, cik: str, form_type: str, years: int) -> list[dict]:
        filings = edgar.list_filings(cik, form_type, years)
        counts = {f: sum(1 for x in filings if x["form"] == f) for f in ("10-K", "10-Q")}
        self.emit(self.name, "list_filings",
                  f"Found {counts['10-K']} 10-K and {counts['10-Q']} 10-Q filings in range.")
        return filings
