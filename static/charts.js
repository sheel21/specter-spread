"use strict";
// Small dependency-free SVG charts. Palette validated with the dataviz checker (light surface):
// lightness band, chroma floor, colorblind separation and 3:1 contrast all pass.
const CHART_COLORS = { revenue: "#3057a8", netIncome: "#b38420", gross: "#3057a8", ebitda: "#b38420", net: "#0f8f84" };
const SVGNS = "http://www.w3.org/2000/svg";
// Drawn at the container's real width so 11px text stays 11px (no viewBox shrinking).
let W = 560;
const H = 250;
const fitWidth = (el) => { W = Math.max(300, Math.round(el.clientWidth || 560)); };

function svgEl(tag, attrs = {}, text) {
  const e = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text !== undefined) e.textContent = text;
  return e;
}

function niceTicks(min, max, count = 4) {
  if (min === max) { max = min + 1; }
  const raw = (max - min) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw);
  const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(+v.toFixed(10));
  return ticks;
}

function fmtMoneyM(v) {
  const a = Math.abs(v), sign = v < 0 ? "−" : "";
  if (a >= 1000) return `${sign}$${(a / 1000).toFixed(a >= 100000 ? 0 : 1)}B`;
  return `${sign}$${a.toFixed(0)}M`;
}
const fmtPct = (v) => `${(v * 100).toFixed(1)}%`;

function seriesValues(view, key, scale) {
  const rows = [...Object.values(view.statements).flat(), ...view.ratios];
  const row = rows.find((r) => r.key === key);
  return view.periods.map((p) => {
    const v = row?.cells[p.key]?.v;
    return v === null || v === undefined ? null : v / scale;
  });
}

function legend(items) {
  const box = document.createElement("div");
  box.className = "legend";
  for (const it of items) {
    const s = document.createElement("span");
    const sw = document.createElement("i");
    if (it.line) sw.className = "line";
    sw.style.background = it.color;
    s.append(sw, document.createTextNode(it.label));
    box.append(s);
  }
  return box;
}

function frame(svg, ticks, fmt, m, yOf) {
  for (const t of ticks) {
    const y = yOf(t);
    svg.append(svgEl("line", { x1: m.l, x2: W - m.r, y1: y, y2: y, class: t === 0 ? "baseline" : "grid" }));
    svg.append(svgEl("text", { x: m.l - 8, y: y + 4, "text-anchor": "end" }, fmt(t)));
  }
}

function xLabels(svg, periods, m, xCenter) {
  const every = Math.ceil(periods.length / Math.max(2, Math.floor((W - m.l - m.r) / 64)));  // keep tick labels from colliding
  periods.forEach((p, i) => {
    if ((periods.length - 1 - i) % every === 0) {
      svg.append(svgEl("text", { x: xCenter(i), y: H - m.b + 16, "text-anchor": "middle" }, p.label));
    }
  });
}

function showTip(evt, html) {
  const tip = document.getElementById("tooltip");
  tip.replaceChildren(...html);
  tip.hidden = false;
  const x = Math.min(evt.clientX + 14, window.innerWidth - tip.offsetWidth - 10);
  tip.style.left = `${x}px`;
  tip.style.top = `${evt.clientY + 16}px`;
}
function hideTip() { document.getElementById("tooltip").hidden = true; }
function tipLines(title, rows) {
  const out = [Object.assign(document.createElement("div"), { innerHTML: "" })];
  const head = document.createElement("b");
  head.textContent = title;
  out[0].append(head);
  for (const [color, label, value] of rows) {
    const d = document.createElement("div");
    const key = document.createElement("span");
    key.style.cssText = `display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;background:${color}`;
    d.append(key, document.createTextNode(`${label}: ${value}`));
    out.push(d);
  }
  return out;
}

function svgX(svg, evt) {
  const r = svg.getBoundingClientRect();
  return ((evt.clientX - r.left) * W) / r.width;
}

// ---------------------------------------------------------------- grouped columns
function columnChart(el, periods, series) {
  fitWidth(el);
  el.replaceChildren(legend(series.map((s) => ({ label: s.label, color: s.color }))));
  const m = { t: 22, r: 12, b: 26, l: 58 };
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": `${series.map((s) => s.label).join(" and ")} by period` });
  const vals = series.flatMap((s) => s.values).filter((v) => v !== null);
  if (!vals.length) { el.append(Object.assign(document.createElement("p"), { className: "muted", textContent: "No data." })); return; }
  const ticks = niceTicks(Math.min(0, ...vals), Math.max(0, ...vals));
  const lo = ticks[0], hi = ticks[ticks.length - 1];
  const yOf = (v) => m.t + ((hi - v) / (hi - lo)) * (H - m.t - m.b);
  frame(svg, ticks, fmtMoneyM, m, yOf);
  const band = (W - m.l - m.r) / periods.length;
  const gap = 2;
  const barW = Math.max(2, Math.min(24, (band * 0.72 - gap) / series.length));
  const groupW = barW * series.length + gap * (series.length - 1);
  const xCenter = (i) => m.l + band * i + band / 2;
  const y0 = yOf(0);
  series.forEach((s, k) => {
    s.values.forEach((v, i) => {
      if (v === null) return;
      const x = xCenter(i) - groupW / 2 + k * (barW + gap);
      const y1 = yOf(v), h = Math.abs(y0 - y1), r = Math.min(4, barW / 2, h);
      const d = v >= 0
        ? `M${x},${y0} L${x},${y1 + r} Q${x},${y1} ${x + r},${y1} L${x + barW - r},${y1} Q${x + barW},${y1} ${x + barW},${y1 + r} L${x + barW},${y0} Z`
        : `M${x},${y0} L${x},${y1 - r} Q${x},${y1} ${x + r},${y1} L${x + barW - r},${y1} Q${x + barW},${y1} ${x + barW},${y1 - r} L${x + barW},${y0} Z`;
      svg.append(svgEl("path", { d, fill: s.color }));
    });
  });
  // Direct label: the latest value of the lead series only (selective). The other series is
  // carried by the legend and the hover tooltip, so its label can never sit on a neighbor's bar.
  const last = periods.length - 1, v = series[0].values[last];
  if (v !== null) {
    const x = xCenter(last) - groupW / 2 + barW / 2;
    svg.append(svgEl("text", { x: Math.min(x + barW / 2, W - m.r), y: v >= 0 ? yOf(v) - 6 : yOf(v) + 14,
      "text-anchor": "end", class: "value" }, fmtMoneyM(v)));
  }
  xLabels(svg, periods, m, xCenter);
  // Hover: one hit target per period band, bigger than the bars.
  periods.forEach((p, i) => {
    const hit = svgEl("rect", { x: m.l + band * i, y: m.t, width: band, height: H - m.t - m.b, fill: "transparent" });
    hit.addEventListener("mousemove", (e) => showTip(e, tipLines(p.label,
      series.map((s) => [s.color, s.label, s.values[i] === null ? "N/A" : fmtMoneyM(s.values[i])]))));
    hit.addEventListener("mouseleave", hideTip);
    svg.append(hit);
  });
  el.append(svg);
}

// ---------------------------------------------------------------- lines
function lineChart(el, periods, series) {
  fitWidth(el);
  el.replaceChildren(legend(series.map((s) => ({ label: s.label, color: s.color, line: true }))));
  const m = { t: 16, r: 92, b: 26, l: 48 };
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Margins by period" });
  const vals = series.flatMap((s) => s.values).filter((v) => v !== null);
  if (!vals.length) { el.append(Object.assign(document.createElement("p"), { className: "muted", textContent: "No data." })); return; }
  const ticks = niceTicks(Math.min(0, ...vals), Math.max(...vals));
  const lo = ticks[0], hi = ticks[ticks.length - 1];
  const yOf = (v) => m.t + ((hi - v) / (hi - lo)) * (H - m.t - m.b);
  frame(svg, ticks, (t) => `${Math.round(t * 100)}%`, m, yOf);
  const n = periods.length;
  const xOf = (i) => (n === 1 ? (m.l + W - m.r) / 2 : m.l + 8 + (i * (W - m.l - m.r - 16)) / (n - 1));
  const ends = [];
  for (const s of series) {
    let d = "", pen = false;
    s.values.forEach((v, i) => {
      if (v === null) { pen = false; return; }
      d += `${pen ? "L" : "M"}${xOf(i)},${yOf(v)} `;
      pen = true;
    });
    svg.append(svgEl("path", { d, fill: "none", stroke: s.color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
    const li = s.values.map((v, i) => (v === null ? -1 : i)).filter((i) => i >= 0).pop();
    if (li !== undefined) {
      svg.append(svgEl("circle", { cx: xOf(li), cy: yOf(s.values[li]), r: 4, fill: s.color, stroke: "#fff", "stroke-width": 2 }));
      ends.push({ y: yOf(s.values[li]), x: xOf(li), text: `${s.short} ${fmtPct(s.values[li])}` });
    }
  }
  // End labels; when two would collide, drop the later one (legend + tooltip still carry it).
  ends.sort((a, b) => a.y - b.y);
  let lastY = -Infinity;
  for (const e of ends) {
    if (e.y - lastY < 13) continue;
    lastY = e.y;
    svg.append(svgEl("text", { x: e.x + 9, y: e.y + 4, class: "value" }, e.text));
  }
  xLabels(svg, periods, m, xOf);
  const cross = svgEl("line", { y1: m.t, y2: H - m.b, class: "crosshair", visibility: "hidden" });
  svg.append(cross);
  const hit = svgEl("rect", { x: m.l, y: m.t, width: W - m.l - m.r + 8, height: H - m.t - m.b, fill: "transparent" });
  hit.addEventListener("mousemove", (e) => {
    const x = svgX(svg, e);
    let i = 0;
    for (let j = 1; j < n; j++) if (Math.abs(xOf(j) - x) < Math.abs(xOf(i) - x)) i = j;
    cross.setAttribute("x1", xOf(i)); cross.setAttribute("x2", xOf(i)); cross.setAttribute("visibility", "visible");
    showTip(e, tipLines(periods[i].label, series.map((s) => [s.color, s.label, s.values[i] === null ? "N/A" : fmtPct(s.values[i])])));
  });
  hit.addEventListener("mouseleave", () => { cross.setAttribute("visibility", "hidden"); hideTip(); });
  svg.append(hit);
  el.append(svg);
}

let lastChartView = null;
let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { if (lastChartView) renderCharts(lastChartView); }, 150);
});

function renderCharts(view) {
  lastChartView = view;
  columnChart(document.getElementById("chart-income"), view.periods, [
    { label: "Revenue", color: CHART_COLORS.revenue, values: seriesValues(view, "revenue", 1e6) },
    { label: "Net income", color: CHART_COLORS.netIncome, values: seriesValues(view, "net_income", 1e6) },
  ]);
  lineChart(document.getElementById("chart-margins"), view.periods, [
    { label: "Gross margin", short: "Gross", color: CHART_COLORS.gross, values: seriesValues(view, "gross_margin", 1) },
    { label: "EBITDA margin", short: "EBITDA", color: CHART_COLORS.ebitda, values: seriesValues(view, "ebitda_margin", 1) },
    { label: "Net margin", short: "Net", color: CHART_COLORS.net, values: seriesValues(view, "net_margin", 1) },
  ]);
}
