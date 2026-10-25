"""All Specter Spread settings in one place.

Environment variables (from .env or the shell) override the defaults marked "env".
"""

import os
from pathlib import Path

from specter.env import load_env

load_env()

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "cache"
SAMPLE_DIR = ROOT / "data" / "sample"
LOG_DIR = ROOT / "logs"
STATIC_DIR = ROOT / "static"

# ---- server ---------------------------------------------------------------------------
HOST = "127.0.0.1"
PORT = int(os.getenv("SPECTER_PORT", "8000"))  # env

# ---- model (Portkey gateway, gpt-6-luna only) -------------------------------------------
MODEL = "gpt-6-luna"
PORTKEY_BASE_URL = "https://api.portkey.ai/v1"
REASONING_EFFORT = "low"                 # routing, fix decisions and short answers don't need more
MAX_OUTPUT_TOKENS = 2000                 # per model response, reasoning included

# USD per 1M tokens, used for the cost panel. PLACEHOLDER RATES: replace them with gpt-6-luna's
# real prices from your Portkey dashboard. Token counts are measured either way.
PRICE_PER_MILLION = {"input": 1.25, "cached_input": 0.125, "output": 10.00}

# ---- cost optimizations ---------------------------------------------------------------
# True (default): model-result cache and MD&A chunk cache; the Analyst sees only the top few
#   MD&A chunks; accounting checks are plain Python and the model is asked only about failures.
# False (naive baseline, for the report): no model-result or MD&A caches; the Analyst gets the
#   whole MD&A of every filing it loads; and the Checker additionally has the model audit the full
#   spread itself ("let the LLM do the math"), scored against the Python checks for accuracy.
# EDGAR downloads stay cached either way (that's SEC politeness, not token cost).
OPTIMIZED = os.getenv("SPECTER_OPTIMIZED", "true").strip().lower() != "false"  # env

# ---- safety: budget and loop guards (per run) -------------------------------------------
MAX_TOKENS_PER_RUN = int(os.getenv("SPECTER_MAX_TOKENS", "60000"))  # env; all model calls in one run
MAX_MODEL_CALLS_PER_RUN = 16
MAX_TOOL_CALLS_PER_RUN = 40              # tool calls requested by the model
MAX_AGENT_ITERATIONS = 4                 # model turns in any single agent's tool loop
MAX_FIX_ATTEMPTS = 2                     # Checker attempts per failed check
MAX_CHECKER_MODEL_FIXES = 10             # failed checks per run that may use the model at all

# ---- data source ----------------------------------------------------------------------
# "auto":   live EDGAR, falling back to the bundled sample data if EDGAR is unreachable
# "live":   live EDGAR only
# "sample": bundled sample data only (works offline; see data/sample/)
DATA_MODE = os.getenv("SPECTER_DATA_MODE", "auto").strip().lower()  # env

# SEC asks for a descriptive User-Agent with a contact email.
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "").strip() or (  # env
    "SpecterSpread/1.0 (MGT 409 student project; specter-spread@example.com)"
)
SEC_MAX_REQUESTS_PER_SECOND = 5          # SEC allows 10; stay well under
SEC_TIMEOUT_SECONDS = 30
CACHE_MAX_AGE_HOURS = {                  # how long each kind of download stays fresh on disk
    "tickers": 24 * 7,
    "companyfacts": 24,
    "submissions": 24,
    "filing": 24 * 365,                  # filed documents never change
}

# ---- input validation -----------------------------------------------------------------
TICKER_PATTERN = r"^[A-Z]{1,5}([.-][A-Z]{1,2})?$"
MIN_YEARS, MAX_YEARS = 1, 10
PERIOD_TYPES = ("annual", "quarterly", "both")
EXAMPLE_TICKERS = ("AAPL", "MSFT", "COST")

# ---- rate limiting --------------------------------------------------------------------
RUNS_PER_MINUTE = 5                      # spread builds per browser session per minute
CHATS_PER_MINUTE = 12                    # chat messages per browser session per minute
