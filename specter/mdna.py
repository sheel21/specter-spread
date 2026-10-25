"""MD&A only: fetch one filing, keep just Item 7 (10-K) or Item 2 (10-Q), chunk it, cache the chunks.

Search is plain TF-IDF over the chunks loaded for the current conversation, so only the top few
relevant chunks are ever sent to the model. Filing text is untrusted: instruction-like phrases are
neutralized before any chunk is stored.
"""

import json
import math
import re
from collections import Counter
from html.parser import HTMLParser

import config
from specter import edgar
from specter.safety import sanitize_filing_text

MDNA_CACHE = config.CACHE_DIR / "mdna"
SAMPLE_MDNA = config.SAMPLE_DIR / "mdna"
CHUNK_CHARS = 1200
MAX_MDNA_CHARS = 150_000

_DASH = r"\s*[\.:\-–—]?\s*"
SECTION_PATTERNS = {
    "10-K": (rf"item\s*7{_DASH}management[’'`]?s?\s+discussion",
             rf"item\s*7a{_DASH}quantitative|item\s*8{_DASH}financial\s+statements"),
    "10-Q": (rf"item\s*2{_DASH}management[’'`]?s?\s+discussion",
             rf"item\s*3{_DASH}quantitative|item\s*4{_DASH}controls"),
}


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "head", "title", "ix:header"}
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append(" ")

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    p = _TextExtractor()
    p.feed(html)
    text = "".join(p.parts).replace("\xa0", " ").replace("​", "")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def extract_section(text: str, form: str) -> str:
    """The MD&A section. The table of contents also matches, so keep the longest span."""
    start_re, end_re = SECTION_PATTERNS["10-K" if form.startswith("10-K") else "10-Q"]
    best = ""
    for m in re.finditer(start_re, text, re.I):
        end = re.search(end_re, text[m.end():], re.I)
        seg = text[m.start(): m.end() + (end.start() if end else 60_000)]
        if len(seg) > len(best):
            best = seg
    return best[:MAX_MDNA_CHARS]


def chunk(section: str, citation: str, meta: dict) -> list[dict]:
    """~1,200-character chunks on paragraph boundaries, each tagged with its nearest subheading."""
    chunks, buf, heading, buf_heading = [], [], "", ""

    def flush():
        if buf:
            raw = "\n".join(buf)
            clean, removed = sanitize_filing_text(raw)
            chunks.append({"id": f"{citation}#{len(chunks) + 1}", "citation": citation, "section": buf_heading,
                           "text": clean, "sanitized": removed, **meta})

    for line in section.split("\n"):
        line = line.strip()
        if not line:
            continue
        if (len(line) < 90 and re.search(r"[A-Za-z]{3}", line) and not line.endswith((".", ":", ";"))
                and not re.search(r"\d{2,}", line)):
            heading = line  # looks like a subheading
        if buf and sum(len(b) for b in buf) + len(line) > CHUNK_CHARS:
            flush()
            buf = []
        if not buf:
            buf_heading = heading
        buf.append(line)
    flush()
    return chunks


def load_chunks(cik: str, filing: dict, citation: str) -> list[dict]:
    """MD&A chunks for one filing: disk cache -> bundled sample -> download and extract."""
    name = f"mdna_{edgar.pad_cik(cik)}_{filing['accession']}.json"
    cached, sample = MDNA_CACHE / name, SAMPLE_MDNA / name

    def read(path):
        chunks = json.loads(path.read_text(encoding="utf-8"))
        for i, c in enumerate(chunks, 1):  # the label belongs to the caller, not the cache
            c["citation"], c["id"] = citation, f"{citation}#{i}"
        return chunks

    if config.OPTIMIZED and cached.is_file():
        return read(cached)
    if config.DATA_MODE == "sample" and sample.is_file():
        return read(sample)
    try:
        html = edgar._fetch("filing", f"filing_{filing['accession']}.htm", filing["url"], as_json=False)
    except edgar.EdgarError:
        if sample.is_file():
            return read(sample)
        raise
    section = extract_section(html_to_text(html), filing["form"])
    if not section:
        return []
    chunks = chunk(section, citation, {"form": filing["form"], "accn": filing["accession"],
                                       "url": filing["url"], "report_date": filing["report_date"]})
    MDNA_CACHE.mkdir(parents=True, exist_ok=True)
    (MDNA_CACHE / name).write_text(json.dumps(chunks), encoding="utf-8")
    return chunks


# ---------------------------------------------------------------- TF-IDF search

_STOP = set("""a an and are as at be by for from has have in is it its of on or that the this to was were will with
what why how did does do about which their they our we us management say says said company""".split())


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z][a-z\-]{1,}", text.lower()) if t not in _STOP]


def search(chunks: list[dict], query: str, top_k: int = 4) -> list[dict]:
    if not chunks:
        return []
    docs = [Counter(_tokens(c["section"] + " " + c["text"])) for c in chunks]
    n = len(docs)
    df = Counter(t for d in docs for t in d)
    q = _tokens(query)
    scored = []
    for c, d in zip(chunks, docs):
        length = sum(d.values()) or 1
        score = sum((d[t] / length) * math.log(1 + n / (1 + df[t])) for t in q if t in d)
        if score > 0:
            scored.append((score, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:top_k]]
