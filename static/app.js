"use strict";

// ---------------------------------------------------------------- state
const state = {
  persona: localStorage.getItem("persona") || "harvey",
  periodType: "annual",
  view: "annual",
  tab: "income",
  spread: null,
  running: false,
};
const sessionId = sessionStorage.getItem("sid") || (() => {
  const id = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2));
  sessionStorage.setItem("sid", id);
  return id;
})();

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};

// Themed status lines while a spread is being built. Numbers never depend on persona.
const LINES = {
  harvey: {
    start: (t) => `Harvey's reviewing the ${t} file. Don't keep him waiting.`,
    done: (t) => `${t} is spread. That's how you close.`,
    fail: "That didn't go our way. Here's why:",
  },
  mike: {
    start: (t) => `Mike is reading the ${t} 10-K… all of it.`,
    done: (t) => `Done! ${t} is spread, and I've checked every tag twice.`,
    fail: "Okay, small problem:",
  },
};

// ---------------------------------------------------------------- setup
async function init() {
  const meta = await fetch("/api/meta").then((r) => r.json()).catch(() => null);
  const years = $("#years");
  for (let y = meta?.min_years ?? 1; y <= (meta?.max_years ?? 10); y++) {
    const o = el("option", "", String(y));
    o.value = y;
    if (y === 5) o.selected = true;
    years.append(o);
  }
  const ex = $("#examples");
  ex.append(el("span", "muted-label", "Try:"));
  for (const t of meta?.examples ?? ["AAPL", "MSFT", "COST"]) {
    const b = el("button", "chip", t);
    b.type = "button";
    b.addEventListener("click", () => { $("#ticker").value = t; runSpread(); });
    ex.append(b);
  }

  setPersona(state.persona);
  document.querySelectorAll(".persona-btn").forEach((b) =>
    b.addEventListener("click", () => setPersona(b.dataset.persona)));
  segmented("#period-type", (v) => { state.periodType = v; });
  segmented("#view-toggle", (v) => { state.view = v; renderTable(); renderChecks(); });
  document.querySelectorAll("#tabs button").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll("#tabs button").forEach((x) => x.classList.toggle("active", x === b));
    state.tab = b.dataset.tab;
    renderTable();
  }));
  $("#run-form").addEventListener("submit", (e) => { e.preventDefault(); runSpread(); });
  setupTooltip();
  setupChat();
}

function segmented(sel, onChange) {
  const root = $(sel);
  root.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    root.querySelectorAll("button").forEach((x) => x.classList.toggle("active", x === b));
    onChange(b.dataset.value);
  }));
}

function setPersona(p) {
  state.persona = p;
  localStorage.setItem("persona", p);
  document.querySelectorAll(".persona-btn").forEach((b) => {
    const on = b.dataset.persona === p;
    b.classList.toggle("active", on);
    b.setAttribute("aria-checked", on);
  });
  const who = $("#chat-who");
  if (who) who.textContent = p === "mike" ? "Mike" : "Harvey";
}

// ---------------------------------------------------------------- run
async function runSpread() {
  if (state.running) return;
  const ticker = $("#ticker").value.trim().toUpperCase();
  $("#form-error").textContent = "";
  if (!ticker) { $("#form-error").textContent = "Enter a ticker first."; return; }

  state.running = true;
  $("#run-btn").disabled = true;
  $("#run-btn").textContent = "Building…";
  $("#activity").replaceChildren();
  showStatus(LINES[state.persona].start(ticker));

  try {
    const resp = await fetch("/api/spread", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Session-Id": sessionId },
      body: JSON.stringify({ ticker, years: Number($("#years").value), period_type: state.periodType, persona: state.persona }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ error: `HTTP ${resp.status}` }));
      throw new Error(err.error || err.detail || "Request refused.");
    }
    await readStream(resp, handleEvent);
  } catch (e) {
    fail(e.message);
  } finally {
    state.running = false;
    $("#run-btn").disabled = false;
    $("#run-btn").textContent = "Build the Spread";
  }
}

async function readStream(resp, onEvent) {
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let nl;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (line) onEvent(JSON.parse(line));
    }
  }
}

function handleEvent(ev) {
  if (ev.type === "activity") {
    logActivity(ev.agent, ev.tool, ev.message);
    showStatus(ev.message);
  } else if (ev.type === "spread") {
    showSpread(ev.spread);
    showStatus(LINES[state.persona].done(ev.spread.company.ticker), "done");
  } else if (ev.type === "error") {
    fail(ev.message);
  }
}

function showSpread(spread) {
  state.spread = spread;
  state.lastRun = spread.run;
  const views = Object.keys(spread.views);
  state.view = views[0];
  $("#view-toggle").hidden = views.length < 2;
  $("#view-toggle").querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.value === state.view));
  $("#ticker").value = spread.company.ticker;
  renderCompany();
  renderTable();
  renderChecks();
  loadTokens();
}

// ---------------------------------------------------------------- chat
const SUGGESTIONS = [
  "Spread AAPL for the last 5 years",
  "Why did gross margin change over this period?",
  "What does management say about supply chain risks?",
  "How did free cash flow trend, and why?",
];
const NAMES = { harvey: "Harvey", mike: "Mike" };

function setupChat() {
  const box = $("#chat-suggestions");
  for (const text of SUGGESTIONS) {
    const b = el("button", "", text);
    b.type = "button";
    b.addEventListener("click", () => sendChat(text));
    box.append(b);
  }
  $("#chat-form").addEventListener("submit", (e) => { e.preventDefault(); sendChat($("#chat-input").value); });
  $("#chat-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat($("#chat-input").value); }
  });
}

function chatBubble(cls) {
  $("#chat-empty")?.remove();
  const div = el("div", `msg ${cls}`);
  $("#chat-log").append(div);
  return div;
}

function scrollChat() { const log = $("#chat-log"); log.scrollTop = log.scrollHeight; }

async function sendChat(text) {
  text = (text || "").trim();
  if (!text || state.running) return;
  state.running = true;
  $("#chat-send").disabled = true;
  $("#chat-input").value = "";
  chatBubble("user").textContent = text;
  const persona = state.persona;
  const thinking = chatBubble("bot thinking");
  thinking.textContent = persona === "mike" ? "Mike is on it…" : "Harvey is reviewing the file…";
  scrollChat();
  $("#activity").replaceChildren();
  try {
    const resp = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Session-Id": sessionId },
      body: JSON.stringify({ message: text, persona }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ error: `HTTP ${resp.status}` }));
      throw new Error(err.error || "Request refused.");
    }
    await readStream(resp, (ev) => {
      if (ev.type === "activity") {
        logActivity(ev.agent, ev.tool, ev.message);
        thinking.textContent = ev.message;
        scrollChat();
      } else if (ev.type === "chat") {
        thinking.remove();
        state.lastRun = ev.reply.run;
        renderReply(ev.reply, persona);
        if (ev.reply.spread) {
          showSpread(ev.reply.spread);
          showStatus(LINES[persona].done(ev.reply.spread.company.ticker), "done");
        } else {
          loadTokens();
        }
      } else if (ev.type === "error") {
        thinking.remove();
        renderReply({ kind: "error", text: ev.message }, persona);
      }
    });
  } catch (e) {
    thinking.remove();
    renderReply({ kind: "error", text: e.message }, persona);
  } finally {
    state.running = false;
    $("#chat-send").disabled = false;
    scrollChat();
  }
}

function citeChip(text, url) {
  const c = el(url ? "a" : "span", "cite", text);
  if (url) { c.href = url; c.target = "_blank"; c.rel = "noopener"; }
  return c;
}

function renderReply(reply, persona) {
  const div = chatBubble(`bot ${reply.kind === "error" ? "error" : reply.kind === "refusal" ? "refusal" : ""}`);
  const who = el("span", "who", NAMES[persona] || "Counsel");
  if (reply.kind === "refusal") who.append(el("span", "safety-badge", "Safety"));
  div.append(who);
  if (reply.kind !== "analysis") {
    div.append(el("div", reply.kind === "error" ? "" : "voice", reply.text || ""));
    return;
  }
  const a = reply.answer;
  if (reply.voice) div.append(el("div", "voice", reply.voice));
  div.append(el("div", "headline", a.headline));
  if (a.numbers_show?.length) {
    div.append(el("h4", "", "What the numbers show"));
    const ul = el("ul");
    for (const p of a.numbers_show) {
      const li = el("li", "", p.point);
      li.append(citeChip(p.citation));
      ul.append(li);
    }
    div.append(ul);
  }
  if (a.management_says?.length) {
    div.append(el("h4", "", "What management says"));
    for (const q of a.management_says) {
      const bq = el("blockquote", "", `“${q.quote}”`);
      bq.append(citeChip(q.citation, q.url));
      div.append(bq);
    }
  }
  if (a.not_covered) {
    div.append(el("h4", "", "Not covered by the filings"));
    div.append(el("div", "not-covered", a.not_covered));
  }
  const au = a.audit || {};
  if (au.figures) {
    const removed = au.quotes_removed ? ` · ${au.quotes_removed} unverifiable quote(s) removed` : "";
    div.append(el("div", "audit", `${au.quotes_verified} quote(s) verified word-for-word against the filing${removed} · ` +
      `${au.figures.traced}/${au.figures.total} figures traced to the spread or excerpts`));
  }
}

function fail(msg) {
  $("#form-error").textContent = msg;
  logActivity("System", "", msg, true);
  showStatus(`${LINES[state.persona].fail} ${msg}`, "failed");
}

function showStatus(text, cls = "") {
  const s = $("#status");
  s.hidden = false;
  s.className = `status ${cls}`;
  s.textContent = text;
}

function logActivity(agent, tool, message, isError = false) {
  const li = el("li");
  li.append(el("span", "agent", agent));
  if (tool) li.append(el("span", "tool", `${tool}() `));
  li.append(el("span", isError ? "error" : "", message));
  const log = $("#activity");
  log.append(li);
  log.scrollTop = log.scrollHeight;
}

// ---------------------------------------------------------------- rendering
function renderCompany() {
  const s = state.spread;
  $("#empty").hidden = true;
  $("#spread").hidden = false;
  $("#company-name").textContent = s.company.name;
  $("#download-btn").href = `/api/export?sid=${encodeURIComponent(sessionId)}`;
  $("#company-meta").textContent =
    `${s.company.ticker} · CIK ${s.company.cik} · ${s.units} · Source: ${s.data_source}`;
}

function fmt(v, unit) {
  if (v === null || v === undefined) return "N/A";
  let txt;
  if (unit === "pct") txt = `${(Math.abs(v) * 100).toFixed(1)}%`;
  else if (unit === "per_share") txt = Math.abs(v).toFixed(2);
  else txt = (Math.abs(v) / 1e6).toLocaleString("en-US", { maximumFractionDigits: 0 });
  return v < 0 ? `(${txt})` : txt;
}

function renderTable() {
  const s = state.spread;
  if (!s) return;
  const view = s.views[state.view];
  const table = $("#spread-table");
  table.replaceChildren();

  const thead = el("thead");
  const hr = el("tr");
  hr.append(el("th", "", s.company.ticker + (state.view === "annual" ? " · Fiscal Years" : " · Fiscal Quarters")));
  for (const p of view.periods) {
    const th = el("th", "", p.label);
    th.append(el("small", "", `ended ${p.end}`));
    hr.append(th);
  }
  thead.append(hr);
  table.append(thead);

  const tbody = el("tbody");
  const addRows = (rows) => rows.forEach((row) => tbody.append(renderRow(row, view.periods)));
  addRows(view.statements[state.tab]);
  if (state.tab === "income") {
    const sec = el("tr", "section");
    const td = el("td", "", "Growth & Margins");
    td.colSpan = view.periods.length + 1;
    sec.append(td);
    tbody.append(sec);
    addRows(view.ratios);
  }
  table.append(tbody);
  renderCharts(view);
}

function renderRow(row, periods) {
  const tr = el("tr", row.kind);
  tr.append(el("td", "", row.label));
  for (const p of periods) {
    const c = row.cells[p.key] || { v: null, src: null };
    const td = el("td", "", fmt(c.v, row.unit));
    if (c.v === null || c.v === undefined) td.classList.add("na");
    else {
      td.classList.add("num");
      if (c.src && !["xbrl", "ratio"].includes(c.src.type)) td.classList.add("derived");
      if (c.src?.re_extracted_by) td.classList.add("fixed");
    }
    if (c.flag) td.classList.add("flag");
    td.dataset.row = row.key;
    td.dataset.period = p.key;
    tr.append(td);
  }
  return tr;
}

// ---------------------------------------------------------------- checker + token panels
function renderChecks() {
  const res = state.spread?.checks?.[state.view];
  const counts = $("#check-counts");
  const list = $("#check-list");
  counts.replaceChildren();
  list.replaceChildren();
  if (!res) return;
  for (const k of ["passed", "fixed", "flagged"]) {
    const box = el("div", `count ${k}`);
    box.append(el("b", "", String(res.counts[k])), el("span", "", k));
    counts.append(box);
  }
  if (res.stopped_reason) list.append(el("p", "form-error", res.stopped_reason));
  const notable = res.results.filter((r) => r.status !== "passed");
  for (const r of notable) {
    const item = el("div", "check-item");
    item.append(el("span", `badge ${r.status}`, r.status), el("b", "", `${r.period_label} · ${r.check}`));
    item.append(el("div", "", r.detail));
    for (const a of r.attempts) {
      const what = a.choice === "none" ? "Model chose no fix" : `Re-extracted ${a.line} from ${a.hint}: ${a.passed ? "check passes" : "still failing"}`;
      item.append(el("div", "attempt", `Attempt ${a.attempt}: ${what}${a.reason ? ` (“${a.reason}”)` : ""}`));
    }
    if (r.note && r.status === "fixed" && !r.attempts.length) item.append(el("div", "attempt", r.note));
    if (r.status === "flagged") item.append(el("div", "attempt", r.note));
    list.append(item);
  }
  const passed = res.results.filter((r) => r.status === "passed");
  const byCheck = {};
  passed.forEach((r) => { byCheck[r.check] = (byCheck[r.check] || 0) + 1; });
  const det = el("details", "passed-list");
  det.append(el("summary", "", `${passed.length} checks passed`));
  const ul = el("ul");
  Object.entries(byCheck).forEach(([k, n]) => ul.append(el("li", "", `${k} (${n} periods)`)));
  det.append(ul);
  list.append(det);
}

async function loadTokens() {
  const data = await fetch("/api/tokens", { headers: { "X-Session-Id": sessionId } }).then((r) => r.json()).catch(() => null);
  const panel = $("#token-panel");
  panel.replaceChildren();
  const run = state.lastRun;
  if (!data) { panel.append(el("p", "muted", "Token data unavailable.")); return; }
  const table = el("table", "token-table");
  const head = el("tr");
  ["Agent", "Calls", "In", "Cached", "Out", "Cost"].forEach((h) => head.append(el("th", "", h)));
  table.append(head);
  const row = (name, b, cls = "") => {
    const tr = el("tr", cls);
    [name, b.calls + (b.cache_hits ? ` (+${b.cache_hits} cached)` : ""), b.input_tokens.toLocaleString(),
      b.cached_input_tokens.toLocaleString(), b.output_tokens.toLocaleString(), `$${b.cost_usd.toFixed(4)}`]
      .forEach((v) => tr.append(el("td", "", String(v))));
    table.append(tr);
  };
  Object.entries(data.summary.by_agent).forEach(([a, b]) => row(a, b));
  row("Session total", data.summary.total, "total");
  panel.append(table);
  const last = run ? `Last run: ${run.tokens.total.input_tokens + run.tokens.total.output_tokens} tokens, ` +
    `${run.budget.model_calls}/${run.budget.max_model_calls} model calls, $${run.tokens.total.cost_usd.toFixed(4)}. ` : "";
  panel.append(el("p", "token-note", `${last}Model ${data.model} via Portkey · optimizations ${data.optimized ? "on" : "off"}. ` +
    "Fetching, mapping and arithmetic are plain Python and cost no tokens."));
}

// ---------------------------------------------------------------- source tooltip
function findCell(td) {
  const view = state.spread?.views[state.view];
  if (!view || !td.dataset.row) return null;
  const rows = [...view.statements[state.tab], ...(state.tab === "income" ? view.ratios : [])];
  const row = rows.find((r) => r.key === td.dataset.row);
  return row ? { row, cell: row.cells[td.dataset.period], period: td.dataset.period } : null;
}

function describeSource(src) {
  const box = el("div");
  const line = (label, value, code = false) => {
    const d = el("div");
    d.append(el("b", "", `${label}: `));
    d.append(code ? el("code", "", value) : document.createTextNode(value));
    box.append(d);
  };
  const xbrl = (s, target = box) => {
    const d = el("div");
    d.append(el("b", "", "Tag: "), el("code", "", s.tag));
    d.append(el("div", "", `${s.form} · accession ${s.accn} · filed ${s.filed}`));
    d.append(el("div", "", `Period ${s.period}` + (s.sign_flipped ? " · sign flipped (cash outflow)" : "")));
    target.append(d);
  };
  if (!src) { line("Source", "Not filed for this period. Shown as N/A, never estimated."); return box; }
  if (src.re_extracted_by) line("Checker", "Re-extracted from the filing to fix a failed check");
  if (src.type === "xbrl") xbrl(src);
  else if (src.type === "derived") line("Computed", src.formula);
  else if (src.type === "ratio") line("Ratio", "Computed from the spread lines above.");
  else {
    line(src.type === "sum" ? "Sum of components" : "Quarter from year-to-date", src.formula);
    const flat = (s) => (s.type === "xbrl" ? [s] : (s.parts || []).flatMap(flat));
    for (const part of (src.parts || []).flatMap(flat)) { const p = el("div", "part"); xbrl(part, p); box.append(p); }
  }
  return box;
}

function setupTooltip() {
  const tip = $("#tooltip");
  const table = $("#spread-table");
  table.addEventListener("mousemove", (e) => {
    const td = e.target.closest("td[data-row]");
    const found = td && findCell(td);
    if (!found) { tip.hidden = true; return; }
    tip.replaceChildren();
    const head = el("div");
    head.append(el("b", "", `${found.row.label} · ${found.period}`));
    tip.append(head, describeSource(found.cell?.src));
    if (found.cell?.flag) tip.append(el("div", "part", `⚠ ${found.cell.flag}`));
    tip.hidden = false;
    const x = Math.min(e.clientX + 14, window.innerWidth - tip.offsetWidth - 10);
    const y = e.clientY + 16 + tip.offsetHeight > window.innerHeight ? e.clientY - tip.offsetHeight - 12 : e.clientY + 16;
    tip.style.left = `${x}px`;
    tip.style.top = `${y}px`;
  });
  table.addEventListener("mouseleave", () => { tip.hidden = true; });
  table.addEventListener("click", (e) => {
    const td = e.target.closest("td[data-row]");
    const src = td && findCell(td)?.cell?.src;
    const url = src?.url || src?.parts?.[0]?.url;
    if (url) window.open(url, "_blank", "noopener");
  });
}

init();
