/* LLM Wiki desktop GUI — vanilla JS, no dependencies.
 * Force-directed knowledge graph on <canvas> + search/ask/ingest panels. */
"use strict";

const $ = (id) => document.getElementById(id);
const api = {
  async get(url) { const r = await fetch(url); if (!r.ok) throw new Error((await r.json()).detail || r.statusText); return r.json(); },
  async post(url, body) { const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); if (!r.ok) throw new Error((await r.json()).detail || r.statusText); return r.json(); },
};

const TYPE_COLORS = {
  entity: "#4f9da6", concept: "#c97b5a", source: "#6c7a89",
  query: "#b56576", comparison: "#8e7cc3", synthesis: "#5a8f69", overview: "#2f3640",
};

function setStatus(msg) { $("status").textContent = msg || ""; }

/* ── Graph model + physics ───────────────────────────────────── */
let nodes = [];          // {id,label,type,color,x,y,vx,vy}
let edges = [];          // {from,to}
let nodeById = {};
let view = { scale: 1, ox: 0, oy: 0 };
let dragNode = null, panning = false, lastMouse = null, hoverNode = null;

const canvas = $("graph");
const ctx = canvas.getContext("2d");

function resize() {
  // Idempotent: only resize the backing buffer when the element size actually
  // changes. Called every frame so the canvas self-heals once layout is ready
  // (embedded WebViews often report 0×0 at initial script run).
  const r = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const w = Math.max(1, Math.round(r.width * dpr));
  const h = Math.max(1, Math.round(r.height * dpr));
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}
window.addEventListener("resize", resize);

async function loadGraph() {
  const g = await api.get("/api/graph");
  const W = canvas.clientWidth || 800, H = canvas.clientHeight || 600;
  nodes = g.nodes.map((n, i) => ({
    ...n,
    x: W / 2 + Math.cos(i) * 150 + (Math.random() - 0.5) * 80,
    y: H / 2 + Math.sin(i) * 150 + (Math.random() - 0.5) * 80,
    vx: 0, vy: 0,
  }));
  edges = g.edges;
  nodeById = {};
  nodes.forEach((n) => (nodeById[n.id] = n));
  buildLegend();
  setStatus(`${nodes.length} pages · ${edges.length} links`);
}

function buildLegend() {
  const present = [...new Set(nodes.map((n) => n.type))];
  $("legend").innerHTML = present
    .map((t) => `<div class="row"><span class="dot" style="background:${TYPE_COLORS[t] || "#8395a7"}"></span>${t}</div>`)
    .join("");
}

/* Simple force-directed layout: repulsion + spring edges + centering. */
function tick() {
  const W = canvas.clientWidth, H = canvas.clientHeight;
  const k = 0.02, repulse = 4000, spring = 0.01, restLen = 90;

  for (let i = 0; i < nodes.length; i++) {
    const a = nodes[i];
    a.vx += (W / 2 - a.x) * k * 0.02;
    a.vy += (H / 2 - a.y) * k * 0.02;
    for (let j = i + 1; j < nodes.length; j++) {
      const b = nodes[j];
      let dx = a.x - b.x, dy = a.y - b.y;
      let d2 = dx * dx + dy * dy || 0.01;
      const f = repulse / d2;
      const d = Math.sqrt(d2);
      const fx = (dx / d) * f, fy = (dy / d) * f;
      a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
    }
  }
  for (const e of edges) {
    const a = nodeById[e.from], b = nodeById[e.to];
    if (!a || !b) continue;
    let dx = b.x - a.x, dy = b.y - a.y;
    const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
    const f = (d - restLen) * spring;
    const fx = (dx / d) * f, fy = (dy / d) * f;
    a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
  }
  for (const n of nodes) {
    if (n === dragNode) continue;
    n.vx *= 0.85; n.vy *= 0.85;
    n.x += n.vx; n.y += n.vy;
  }
}

function toScreen(p) { return { x: p.x * view.scale + view.ox, y: p.y * view.scale + view.oy }; }
function toWorld(sx, sy) { return { x: (sx - view.ox) / view.scale, y: (sy - view.oy) / view.scale }; }

function draw() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.lineWidth = 1;
  ctx.strokeStyle = "rgba(150,160,175,0.25)";
  for (const e of edges) {
    const a = nodeById[e.from], b = nodeById[e.to];
    if (!a || !b) continue;
    const pa = toScreen(a), pb = toScreen(b);
    ctx.beginPath(); ctx.moveTo(pa.x, pa.y); ctx.lineTo(pb.x, pb.y); ctx.stroke();
  }
  for (const n of nodes) {
    const p = toScreen(n);
    const r = (n.orphan ? 5 : 8) * Math.min(1.6, view.scale);
    ctx.beginPath();
    ctx.fillStyle = n.color || "#8395a7";
    ctx.globalAlpha = n.orphan ? 0.6 : 1;
    ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 1;
    if (n === hoverNode || view.scale > 1.1) {
      ctx.fillStyle = "#e6e9ef";
      ctx.font = "12px -apple-system, sans-serif";
      ctx.fillText(n.label, p.x + r + 3, p.y + 4);
    }
  }
}

function loop() { resize(); tick(); draw(); requestAnimationFrame(loop); }

/* ── Interaction ─────────────────────────────────────────────── */
function nodeAt(sx, sy) {
  for (let i = nodes.length - 1; i >= 0; i--) {
    const p = toScreen(nodes[i]);
    const dx = sx - p.x, dy = sy - p.y;
    if (dx * dx + dy * dy < 144) return nodes[i];
  }
  return null;
}

canvas.addEventListener("mousedown", (e) => {
  const rect = canvas.getBoundingClientRect();
  const sx = e.clientX - rect.left, sy = e.clientY - rect.top;
  const n = nodeAt(sx, sy);
  if (n) { dragNode = n; openPage(n.path); }
  else { panning = true; }
  lastMouse = { x: sx, y: sy };
});
canvas.addEventListener("mousemove", (e) => {
  const rect = canvas.getBoundingClientRect();
  const sx = e.clientX - rect.left, sy = e.clientY - rect.top;
  hoverNode = nodeAt(sx, sy);
  canvas.style.cursor = hoverNode ? "pointer" : "grab";
  if (dragNode) { const w = toWorld(sx, sy); dragNode.x = w.x; dragNode.y = w.y; dragNode.vx = dragNode.vy = 0; }
  else if (panning && lastMouse) { view.ox += sx - lastMouse.x; view.oy += sy - lastMouse.y; }
  lastMouse = { x: sx, y: sy };
});
window.addEventListener("mouseup", () => { dragNode = null; panning = false; });
canvas.addEventListener("wheel", (e) => {
  e.preventDefault();
  const rect = canvas.getBoundingClientRect();
  const sx = e.clientX - rect.left, sy = e.clientY - rect.top;
  const before = toWorld(sx, sy);
  view.scale *= e.deltaY < 0 ? 1.1 : 0.9;
  view.scale = Math.max(0.2, Math.min(4, view.scale));
  const after = toWorld(sx, sy);
  view.ox += (after.x - before.x) * view.scale;
  view.oy += (after.y - before.y) * view.scale;
}, { passive: false });

/* ── Side panels ─────────────────────────────────────────────── */
function renderBody(text) {
  // Render [[slug]] as clickable links; escape the rest.
  const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return esc(text).replace(/\[\[([^\]|]+?)(?:\|[^\]]+)?\]\]/g,
    (_, slug) => `<span class="wikilink" data-slug="${slug.trim()}">${slug.trim()}</span>`);
}

async function openPage(path) {
  if (!path) return;
  const pv = $("preview");
  pv.classList.remove("hidden");
  pv.innerHTML = '<div class="spinner">Loading…</div>';
  try {
    const p = await api.get("/api/page?path=" + encodeURIComponent(path));
    const tags = (p.meta.tags || []).map((t) => `<span class="tag">${t}</span>`).join("");
    pv.innerHTML = `<h2 class="page-title">${p.title}</h2><div>${tags}</div><div class="answer-body">${renderBody(p.body)}</div>`;
    bindWikilinks(pv);
  } catch (err) { pv.innerHTML = `<div class="placeholder">${err.message}</div>`; }
}

function openSlug(slug) {
  const n = nodeById[slug];
  if (n) openPage(n.path);
}

function bindWikilinks(root) {
  root.querySelectorAll(".wikilink").forEach((el) =>
    el.addEventListener("click", () => openSlug(el.dataset.slug)));
}

async function doSearch() {
  const q = $("q").value.trim();
  if (!q) return;
  const box = $("results");
  box.classList.remove("hidden");
  $("answer").classList.add("hidden");
  box.innerHTML = '<div class="spinner">Searching…</div>';
  try {
    const res = await api.post("/api/search", { query: q, k: 8 });
    if (!res.results.length) { box.innerHTML = "<h3>Results</h3><div class='placeholder'>No matches.</div>"; return; }
    box.innerHTML = `<h3>Results · ${res.mode}</h3>` + res.results.map((r) =>
      `<div class="result-item" data-path="${r.path}"><div class="title">${r.title}</div>
       <div class="meta">${r.type} · score ${r.score}${r.vectorScore != null ? " · vec " + r.vectorScore.toFixed(2) : ""}</div></div>`).join("");
    box.querySelectorAll(".result-item").forEach((el) =>
      el.addEventListener("click", () => openPage(el.dataset.path)));
  } catch (err) { box.innerHTML = `<h3>Results</h3><div class="placeholder">${err.message}</div>`; }
}

async function doAsk() {
  const q = $("q").value.trim();
  if (!q) return;
  const box = $("answer");
  box.classList.remove("hidden");
  $("results").classList.add("hidden");
  box.innerHTML = '<h3>Answer</h3><div class="spinner">Thinking…</div>';
  try {
    const res = await api.post("/api/query", { question: q, k: 8, save: false });
    box.innerHTML = `<h3>Answer</h3><div class="answer-body">${renderBody(res.answer)}</div>`;
    bindWikilinks(box);
  } catch (err) { box.innerHTML = `<h3>Answer</h3><div class="placeholder">${err.message}</div>`; }
}

async function doIngest() {
  const path = $("ingest-path").value.trim();
  if (!path) return;
  setStatus("Ingesting…");
  try {
    const res = await api.post("/api/ingest", { path, embed: true });
    const ok = res.results.filter((r) => !r.error && !r.skipped).length;
    setStatus(`Ingested ${ok} source(s). Refreshing graph…`);
    await loadGraph();
  } catch (err) { setStatus("Ingest failed: " + err.message); }
}

async function doIngestLark() {
  const url = $("lark-url").value.trim();
  if (!url) return;
  setStatus("Importing from Lark…");
  try {
    const res = await api.post("/api/ingest-lark", { url, embed: true });
    const ok = res.results.filter((r) => !r.error && !r.skipped).length;
    setStatus(`Lark: ${res.exported} doc(s) exported, ${ok} ingested${res.skipped ? `, ${res.skipped} skipped` : ""}. Refreshing graph…`);
    await loadGraph();
  } catch (err) { setStatus("Lark import failed: " + err.message); }
}

$("btn-search").addEventListener("click", doSearch);
$("btn-ask").addEventListener("click", doAsk);
$("btn-ingest").addEventListener("click", doIngest);
$("btn-ingest-lark").addEventListener("click", doIngestLark);
$("q").addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(); });
$("ingest-path").addEventListener("keydown", (e) => { if (e.key === "Enter") doIngest(); });
$("lark-url").addEventListener("keydown", (e) => { if (e.key === "Enter") doIngestLark(); });

/* ── Boot ─────────────────────────────────────────────────────── */
(async function boot() {
  resize();
  try {
    const h = await api.get("/api/health");
    if (!h.has_llm) setStatus("No API key — search is keyword-only; Ask/Ingest disabled.");
  } catch (_) {}
  try { await loadGraph(); } catch (err) { setStatus("Graph error: " + err.message); }
  loop();
})();
