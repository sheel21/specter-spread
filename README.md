# Specter Spread

A conversational financial analyst with a Suits-inspired personality. Type a public company ticker
and a number of years; Specter Spread pulls the company's 10-K and 10-Q filings from SEC EDGAR, lays
out an investment-banking-style spread (Income Statement, Balance Sheet, Cash Flow), checks that it
foots, and exports a formatted Excel workbook. Then keep chatting: ask why margins moved or what
management says about supply chain, and get answers that separate *what the numbers show* from
*what management says*, with citations to the filing and year.

MGT 409 (AI Foundations for Managers) final project. Model: `gpt-6-luna` through Portkey.

---

**Report and slides:** [`report/report.html`](report/report.html) and [`report/slides.html`](report/slides.html)
(self-contained; double-click to open). Rebuilt from the app's own logs by `report/build_report.py`.

## Run it from a fresh clone (about 5 minutes)

Requires Python 3.11+ and internet access (SEC EDGAR + Portkey). No database, Docker, or Node.

1. **Clone**
   ```bash
   git clone https://github.com/sheel21/specter-spread.git
   cd specter-spread
   ```
2. **Create a virtual environment and install**
   ```bash
   python -m venv .venv
   ```
   - Windows: `.venv\Scripts\python -m pip install -r requirements.txt`
   - macOS/Linux: `.venv/bin/python -m pip install -r requirements.txt`
3. **Add your keys.** Copy `.env.example` to `.env` and fill in:
   - `PORTKEY_API_KEY`: your Portkey key (or `OPENAI_API_KEY`; calls always go through Portkey)
   - `SEC_USER_AGENT`: your name and email (the SEC asks every client to identify itself)

   **Where `.env` can live:** the app looks in two places, in this order:
   1. this repo's folder: `specter-spread/.env`
   2. the folder one level above it: `../.env` (handy for keeping one `.env` above several projects)

   The first one found is loaded. Variables already set in your shell take precedence over both.
   The startup line tells you which file was used (never its contents).
4. **Run**
   - Windows: `.venv\Scripts\python app.py`
   - macOS/Linux: `.venv/bin/python app.py`

   Open <http://127.0.0.1:8000>. (Change the port with `SPECTER_PORT=8001`.)

## Using it

- **Build a spread:** type a ticker (or click AAPL / MSFT / COST), pick 1–10 years and Annual /
  Quarterly / Both, and press **Build the Spread**. Or just say it in chat: *"Spread MSFT for 5 years."*
- **Read it:** years across the top, USD millions, negatives in parentheses, bold subtotals.
  Hover any number for its XBRL tag, form, accession number and filing date; click to open the
  filing on EDGAR. *Italic* = computed; gold edge = re-extracted by the Checker; yellow = a check
  failed (hover for the note); N/A = not filed (never estimated).
- **Ask counsel:** *"Why did gross margin improve between FY2023 and FY2025?"*, *"What does management
  say about supply chain risks?"*, *"What's driving the jump in capex?"*
- **Harvey / Mike:** the toggle in the header changes the voice only. Numbers, quotes, citations,
  the Checker and the Excel file are identical in both.
- **Download Excel:** Summary, statement sheets (annual and/or quarterly), Checks, and Sources.
- **Panels:** activity log (which agent and tool is working), Checker results (passed / fixed /
  flagged), tokens & cost per agent, and two trend charts.

## Offline demo data (AAPL)

`data/sample/` bundles Apple's EDGAR data: Company Facts (trimmed to the concepts the template
uses), the filing index, MD&A text chunks for 10 annual reports, and the SEC ticker list. It lets
you demo the app when EDGAR is slow or unreachable.

| `SPECTER_DATA_MODE` | Behavior |
|---|---|
| `auto` (default) | Live EDGAR with a disk cache; falls back to the bundled sample if EDGAR is unreachable |
| `live` | Live EDGAR (and disk cache) only |
| `sample` | Bundled sample only: fully offline for EDGAR; only AAPL builds (chat still needs Portkey) |

Switch by setting it in `.env` (`SPECTER_DATA_MODE=sample`) or the shell, e.g. PowerShell:
`$env:SPECTER_DATA_MODE="sample"; .venv\Scripts\python app.py`. To bundle a different company
instead: `python scripts/make_sample.py MSFT` (needs network once).

## How it works

```
chat message ──► safety screen (Python) ──► Router ──┬──► Fetcher ─► Spreader ─► Checker (≤2 fixes/check) ─► spread + Excel
                                                      ├──► Analyst ─► read_spread / fetch_mdna / search_mdna ─► cited answer
                                                      └──► direct reply
Build button ─────────────────────────────────────────┘ (straight to the spread pipeline)
```

| Agent | Tools (whitelist) | Uses the model for |
|---|---|---|
| **Router** | `route` | Deciding who handles each chat message (one small call) |
| **Fetcher** | `lookup_cik`, `get_company_facts`, `list_filings` | Nothing: plain Python against EDGAR |
| **Spreader** | `get_facts_for_concept`, `write_line_item` | Nothing: prioritized XBRL tag lists per line (companies switch tags over time); quarters missing from 10-Qs are computed from year-to-date figures and labeled as such |
| **Checker** | `check_balance_sheet`, `check_subtotals`, `check_cash_reconciliation`, `re_extract_line_item` | Only when a check fails: choosing which *filed* alternative to re-extract (each option pre-tested in Python). Max 2 attempts, then the cells are flagged yellow with a note. It can pick an option id, never type a number |
| **Analyst** | `read_spread`, `fetch_mdna`, `search_mdna` | Answering from the spread plus the top few MD&A chunks (TF-IDF). Quotes are verified word-for-word against the retrieved filing text; unverifiable ones are removed |

Checks (plain Python): Assets = Liabilities + Equity; subtotals foot; Gross Profit = Revenue − COGS;
EBITDA = EBIT + D&A; FCF = CFO − Capex; CFO + CFI + CFF + FX = net change in cash; net change ties
to the change in balance-sheet cash; signs; implausible year-over-year jumps (unit errors).

**Personas.** Harvey (blunt, short, witty) and Mike (eager, explains the why, "read everything in
the filing") are a short, fixed block at the start of the Router and voice prompts, followed by
guardrails that always win. Analyst facts come from a persona-free prompt; one short persona call
adds 1–2 framing sentences, and any sentence containing a figure is dropped.

## Safety controls

| Control | Where | Demonstrated by |
|---|---|---|
| Budget guard: per-run caps on tokens, model calls, tool calls; the next call's size is estimated so one big request can't blow past the cap | `config.py`, `specter/llm.py` | test (d) |
| Loop guard: max 4 model turns per agent loop, max 2 Checker fix attempts per check, max 10 model-assisted fixes per run, max 3 filings per question | `config.py` | test (e), Checker panel |
| Input validation: ticker pattern + must exist in the SEC ticker list; years 1–10; period type; chat ≤ 1,000 chars | `specter/safety.py` | test (c) |
| Prompt injection: user messages screened in Python (refused with zero model calls); MD&A text neutralized and wrapped as `<filing_excerpt>` data; refused messages never re-enter the conversation | `specter/safety.py`, `specter/mdna.py`, `specter/chat.py` | tests (a), (b), (f) |
| Tool whitelists: an agent can only call its own tools; anything else is blocked and logged | `specter/agents/base.py` | test (i) |
| No hallucinated numbers: every cell carries its tag + filing; `write_line_item` refuses values the filing doesn't report; N/A instead of estimates | `specter/xbrl.py`, `specter/agents/spreader.py` | test (j), hover any cell |
| Secrets: keys only from env/.env, redacted from anything shown or logged | `specter/safety.py` | test (k) |
| Rate limiting: 5 spread runs and 12 chat messages per session per minute | `config.py` | test (h) |

Run the demonstrations (prints PASS/FAIL per defense; about 2 minutes; uses the AAPL sample + live model):
```bash
.venv\Scripts\python tests\test_safety.py
```
(macOS/Linux: `.venv/bin/python tests/test_safety.py`). Results are also saved to `logs/safety_results.txt`.

## Token usage and cost

Every model call is logged with agent, persona, input tokens, cached input tokens, output tokens,
cost and latency, both in the **Tokens & Cost** panel and in `logs/tokens.jsonl`
(`logs/sample_tokens.jsonl` shows the format).

- Summarize the log (by agent, spread runs vs chat questions, Harvey vs Mike, optimized vs baseline):
  `python scripts/token_report.py` → `logs/token_report.md`
- Cost vs. accuracy with optimizations ON vs OFF on a fixed scenario:
  `python scripts/cost_compare.py` → `logs/cost_comparison.md`

Cost reductions (all on by default; `SPECTER_OPTIMIZED=false` turns them off for comparison):
parsing, mapping and arithmetic in Python (a clean spread costs 0 tokens); the model only for routing,
failed-check fixes and analysis; EDGAR, MD&A-chunk and model-result caches; top-k MD&A chunks instead
of whole sections; short stable prompts with the persona block first so provider prompt caching applies;
short conversation memory (spread summary + last few turns).

**Prices:** `PRICE_PER_MILLION` in `config.py` sets $/1M tokens for input, cached input and output.
Token counts are measured; costs are computed from those prices.

## Configuration (`config.py`)

| Setting | Default | Notes |
|---|---|---|
| `MODEL` | `gpt-6-luna` | via `PORTKEY_BASE_URL` |
| `SPECTER_DATA_MODE` (env) | `auto` | `auto` / `live` / `sample` |
| `SPECTER_OPTIMIZED` (env) | `true` | `false` = naive baseline for cost comparison |
| `MAX_TOKENS_PER_RUN` / `MAX_MODEL_CALLS_PER_RUN` / `MAX_TOOL_CALLS_PER_RUN` | 60,000 / 16 / 40 | budget guard |
| `MAX_AGENT_ITERATIONS` / `MAX_FIX_ATTEMPTS` | 4 / 2 | loop guard |
| `RUNS_PER_MINUTE` / `CHATS_PER_MINUTE` | 5 / 12 | per browser session |
| `SEC_MAX_REQUESTS_PER_SECOND` | 5 | SEC allows 10 |

## Project layout

```
app.py                  FastAPI server and API (python app.py)
config.py               every setting in one place
specter/
  env.py                two-place .env lookup
  edgar.py              SEC client: User-Agent, throttle, disk cache, sample fallback
  xbrl.py               fiscal periods, tag resolution, sources
  template.py           banker template + prioritized XBRL tags per line
  checks.py             plain-Python accounting checks
  mdna.py               MD&A extraction, chunking, TF-IDF search
  llm.py                Portkey client, token ledger, budget guard, model-result cache
  personas.py           Harvey / Mike blocks + guardrails
  safety.py             validation, injection screening, redaction, rate limits
  chat.py               one chat turn: screen -> Router -> agent
  pipeline.py           Fetcher -> Spreader -> Checker
  excel.py              openpyxl workbook with real formulas
  agents/               router, fetcher, spreader, checker, analyst, base (guarded tool loop)
static/                 index.html, styles.css, app.js, charts.js (no build step, no CDN JS)
data/sample/            bundled AAPL data for offline demos
tests/test_safety.py    safety demonstrations (a)-(k)
scripts/                cost_compare.py, token_report.py, make_sample.py
logs/                   token log and reports (gitignored except samples)
```

## Troubleshooting

- **"No model key configured"**: put `PORTKEY_API_KEY` in `.env` (repo folder or one above).
- **EDGAR errors / HTTP 403**: set `SEC_USER_AGENT` to a real name and email, or use `SPECTER_DATA_MODE=sample`.
- **"The model provider's safety filter blocked this request"**: the upstream provider's content
  filter rejected the prompt (it flags jailbreak-like text). Rephrase.
- **Port in use**: `SPECTER_PORT=8001`.
- **Stopping the server**: Ctrl+C in its terminal.
