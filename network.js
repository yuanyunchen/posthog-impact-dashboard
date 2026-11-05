/* Team collaboration network (spec §F). Data: network_data.json from impact/site_network.py; layout is precomputed,
   so nothing here runs a force simulation. Look follows the starmap visual system. */
(() => {
"use strict";
const EMBED = new URLSearchParams(location.search).get("embed") === "1";
if (EMBED) document.body.classList.add("embed");
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = n => n == null ? "—" : Number(n).toLocaleString("en-US");
const pct = v => v == null ? "—" : `${Math.round(v * 100)}%`;

const KIND = {
  r: { name: "Review", color: "#8d9fc4", unit: "pts", verb: "reviewed",
       says: (s, t) => `<b>${s}</b> reviewed PRs by <b>${t}</b> (approvals, written comments, change requests). Weight = sum of those PRs' tier points.` },
  c: { name: "Builds on code", color: "#9ee493", unit: "pts", verb: "built on",
       says: (s, t) => `<b>${s}</b> later changed source files that <b>${t}</b> had written (≥20 lines) earlier in the window. Weight = sum of ${s}'s PRs' tier points.` },
  f: { name: "Fix / revert", color: "#c98d84", unit: "×", verb: "fixed",
       says: (s, t) => `<b>${s}</b> merged a revert or follow-up fix that explicitly references a PR by <b>${t}</b>. Weight = number of such PRs.` },
};
const EV = { A: "approved", R: "changes requested", C: "commented", D: "built on", V: "reverted", F: "follow-up fix" };
const PALETTE = ["#c3a8ff", "#6fd3c7", "#f2a65a", "#e6d36a", "#7e9bff", "#e48fd8", "#d9a07a", "#a7b8d8", "#cfc6a8"];
const OTHER = "#5f6b8c";
const CAND_URL = l => `index.html#candidate=${encodeURIComponent(l)}`;  // main page detail anchor

let D, P, E, POOL, BY, cy, baseZoom = 1, near = false;
const EIDX = new Map();  // "src|dst|kind" → edge, for reading a relation in both directions
const S = { focus: null, kinds: { r: true, c: true, f: true }, topN: 50, top20: false, sel: null, hi: null };

// network_data.js (script tag) works from file:// as well; the JSON fetch is the fallback over http
(window.NETWORK_DATA ? Promise.resolve(window.NETWORK_DATA)
  : fetch("network_data.json").then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })).then(init).catch(err => {
  $("#err").classList.add("on");
  $("#err").innerHTML = `<div>Could not load the network data (${esc(err.message)}).<br>Rebuild it with <code>python -m impact.site_network data/prs.jsonl out_full site</code>; it writes <code>network_data.js</code> and <code>network_data.json</code> next to this page.</div>`;
});

function init(data) {
  D = data;
  P = D.people;
  BY = Object.fromEntries(P.map((p, i) => [p.id, i]));
  E = D.edges.map(([s, t, k, w, n, pool, prs, ev], i) => ({ i, id: "e" + i, s, t, k, w, n, pool: !!pool, prs, ev: ev || {} }));
  for (const e of E) EIDX.set(`${e.s}|${e.t}|${e.k}`, e);
  POOL = { r: [], c: [], f: [] };
  for (const e of E) if (e.pool) POOL[e.k].push(e);
  for (const k in POOL) POOL[k].sort((a, b) => b.w - a.w || b.n - a.n);
  S.topN = D.meta.caps.overview_per_kind;
  const slider = $("#topn");
  slider.max = D.meta.caps.core_edges_per_kind; slider.value = S.topN;

  const maxW = {};
  for (const k in POOL) maxW[k] = Math.max(1, ...POOL[k].map(e => e.w));
  const col = c => c != null && c < PALETTE.length ? PALETTE[c] : OTHER;
  const els = [];
  for (const c of D.communities) if (c.blob) {
    const [x, y, rx, ry, , lx, ly] = c.blob;
    els.push({ group: "nodes", classes: "blob", position: { x, y }, data: { id: "b" + c.id, w: 2 * rx, h: 2 * ry, col: col(c.id) } });
    if (lx != null)  // label spot chosen at build time so it never sits on a person or a name
      els.push({ group: "nodes", classes: "blob blab", position: { x: lx, y: ly }, data: { id: "bl" + c.id, col: col(c.id), label: c.team || "mixed" } });
  }
  P.forEach((p, i) => els.push({ group: "nodes", position: { x: p.x, y: p.y },
    classes: [p.cand && "cand named", p.rank && "top5", !p.core && "extra"].filter(Boolean).join(" "),
    data: { id: p.id, i, label: p.rank ? `#${p.rank} ${p.id}` : p.id, col: col(p.comm), d: p.d,
            label2: `${p.rank ? `#${p.rank} ` : ""}${p.id}${p.prof && p.prof.traits[0] ? "\n" + p.prof.traits[0] : ""}` } }));
  const CPD = { r: 8, c: 16, f: 24 };
  for (const e of E) {
    const r = Math.sqrt(Math.min(1, e.w / maxW[e.k]));  // sqrt: a few heavy relations stand out, the rest stay thin
    els.push({ group: "edges", classes: e.k,
      data: { id: e.id, source: P[e.s].id, target: P[e.t].id, col: KIND[e.k].color, cpd: CPD[e.k],
              width: .6 + 1.8 * r, op: .18 + .17 * r, label: e.k === "f" ? `${e.w}×` : `${fmt(e.w)}` } });
  }

  cy = cytoscape({
    container: $("#cy"), elements: els, layout: { name: "preset" }, minZoom: .2, maxZoom: 2.5,
    autoungrabify: true, autounselectify: true, boxSelectionEnabled: false, style: STYLE,
  });
  window.__net = { cy, S };  // handle for the Playwright self-check
  header(); legend(); controls(); events(); insightsBar();
  apply();
  requestAnimationFrame(() => { fitTo(visiblePeople(), false); baseZoom = cy.zoom(); });
}

const MONO = "JetBrains Mono, ui-monospace, Menlo, monospace";
const STYLE = [
  { selector: "node", style: { "z-index-compare": "manual", "z-index": 10, width: "data(d)", height: "data(d)",
    "background-color": "data(col)", "background-opacity": .6, "border-width": 0, "border-color": "#e9eefb",
    label: "", color: "#e9eefb", "font-family": MONO, "font-size": 11, "text-valign": "bottom", "text-margin-y": 4,
    "text-outline-color": "#060913", "text-outline-width": 2.2, "text-outline-opacity": .95,
    "underlay-opacity": 0, "min-zoomed-font-size": 0 } },
  { selector: "node.cand", style: { "background-opacity": .95, "border-width": 1.3, "border-opacity": .7,
    "underlay-color": "data(col)", "underlay-opacity": .18, "underlay-padding": 5, "underlay-shape": "ellipse" } },
  { selector: "node.top5", style: { "border-width": 3.5, "border-opacity": 1, "underlay-opacity": .3, "font-size": 12, "font-weight": 500 } },
  { selector: "node.named, node.labelled", style: { label: "data(label)" } },
  { selector: "node.blob", style: { "z-index": 0, shape: "ellipse", width: "data(w)", height: "data(h)",
    "background-color": "data(col)", "background-opacity": .04, "border-width": .8, "border-color": "data(col)",
    "border-opacity": .12, label: "", color: "data(col)", "font-size": 9, "text-transform": "uppercase",
    "text-opacity": .5, "text-outline-width": 0, "text-valign": "center", "text-margin-y": 0, "underlay-opacity": 0, events: "no" } },
  { selector: "node.blab", style: { width: 1, height: 1, "background-opacity": 0, "border-width": 0, label: "data(label)", "z-index": 1 } },
  // slight per-kind curvature (unbundled): opposite directions bow to opposite sides, kinds don't sit on each other
  { selector: "edge", style: { "z-index-compare": "manual", "z-index": 5, "curve-style": "unbundled-bezier",
    "control-point-distances": "data(cpd)", "control-point-weights": .5, width: "data(width)", "line-color": "data(col)",
    "target-arrow-color": "data(col)", "target-arrow-shape": "none", "arrow-scale": .55, opacity: "data(op)", label: "",
    "font-family": MONO, "font-size": 9, color: "#9aa7c9", "text-outline-color": "#060913", "text-outline-width": 2,
    "text-rotation": "autorotate" } },
  { selector: "edge.f", style: { "line-style": "dashed", "line-dash-pattern": [3, 3], opacity: .35 } },
  { selector: "edge.arrows", style: { "target-arrow-shape": "triangle" } },
  { selector: "edge.labelled", style: { label: "data(label)" } },
  { selector: ".hidden", style: { display: "none" } },
  { selector: "node.blob.faded", style: { opacity: .35 } },
  { selector: "edge.fe", style: { opacity: .6 } },
  { selector: "node.faded", style: { opacity: .07 } },
  { selector: "edge.dim", style: { opacity: .06 } },
  { selector: "node.dim", style: { opacity: .3 } },
  { selector: "edge.hl", style: { opacity: 1, "z-index": 8, "target-arrow-shape": "triangle" } },
  { selector: "node.hl", style: { "border-width": 2.5, "border-color": "#8fc6ff", "border-opacity": 1, opacity: 1,
    "underlay-color": "#8fc6ff", "underlay-opacity": .28, "underlay-padding": 5, "underlay-shape": "ellipse", label: "data(label)" } },
  { selector: "node.focus", style: { "border-width": 4, "border-color": "#8fc6ff", "border-opacity": 1,
    "underlay-color": "#8fc6ff", "underlay-opacity": .34, "underlay-padding": 6, "underlay-shape": "ellipse",
    label: "data(label)", "font-size": 13, "z-index": 12 } },
  { selector: "edge.sel", style: { opacity: 1, "line-color": "#8fc6ff", "target-arrow-color": "#8fc6ff", "z-index": 9,
    "target-arrow-shape": "triangle", label: "data(label)", color: "#8fc6ff" } },
  { selector: "node.lo", style: { opacity: .22 } },
  { selector: "edge.lo", style: { opacity: .05 } },
  { selector: "node.hi", style: { opacity: 1, "border-width": 2.5, "border-color": "#8fc6ff", "border-opacity": 1, label: "data(label)",
    "underlay-color": "#8fc6ff", "underlay-opacity": .3, "underlay-padding": 6, "underlay-shape": "ellipse" } },
  { selector: "node.top5.tagged", style: { label: "data(label2)", "text-wrap": "wrap", "line-height": 1.35 } },
];

/* ---------- visibility ---------- */
const kindsOn = k => S.kinds[k];
const egoOf = i => (D.ego[i] || []).map(j => j);
function focusEdges(i) {
  const nb = new Set(egoOf(i));
  return E.filter(e => (e.s === i && nb.has(e.t)) || (e.t === i && nb.has(e.s)));
}
function apply() {
  cy.batch(() => {
    cy.elements().removeClass("hidden faded labelled hl focus sel fe hi lo");
    const show = new Set();
    if (S.focus == null) {
      const vis = new Set(P.map((p, i) => i).filter(i => P[i].core && (!S.top20 || P[i].cand)));
      cy.nodes().not(".blob").forEach(n => n.toggleClass("hidden", !vis.has(n.data("i"))));
      for (const k of "rcf") if (kindsOn(k)) {
        let c = 0;
        for (const e of POOL[k]) {
          if (c >= S.topN) break;
          if (vis.has(e.s) && vis.has(e.t)) { show.add(e.id); c++; }
        }
      }
    } else {
      const f = S.focus, nb = new Set([f, ...egoOf(f)]);
      cy.nodes().not(".blob").forEach(n => {
        const i = n.data("i");
        n.toggleClass("hidden", !nb.has(i) && !P[i].core);
        n.toggleClass("faded", !nb.has(i));
        if (nb.has(i)) n.addClass("labelled");
      });
      cy.nodes(".blob").addClass("faded");
      for (const e of focusEdges(f)) if (kindsOn(e.k)) { show.add(e.id); cy.getElementById(e.id).addClass("fe"); }
      cy.getElementById(P[f].id).addClass("focus");
    }
    cy.edges().forEach(ed => ed.toggleClass("hidden", !show.has(ed.id())));
    if (S.sel) cy.getElementById(S.sel).addClass("sel");
    if (S.focus == null) highlight();
  });
  labels(true);
  thresholds();
  document.body.classList.toggle("focusing", S.focus != null);
  $("#focus-note").innerHTML = S.focus == null ? "" :
    `Focused on <b>${esc(P[S.focus].id)}</b>: their ${egoOf(S.focus).length} strongest relations. Esc to go back.`;
}
function visiblePeople() { return cy.nodes().not(".blob").not(".hidden").not(".faded"); }

/* semantic zoom: past 1.6× the overview zoom every visible person gets a name and every line its weight */
function labels(force) {
  cy.nodes(".cand").toggleClass("named", cy.zoom() >= .45);  // tiny phone-width overview: names only after zooming in
  cy.nodes(".top5").toggleClass("tagged", cy.zoom() > baseZoom * 1.6);  // zoomed in: one trait under each Top-5 name
  const n = cy.zoom() > baseZoom * 1.6;
  if (n === near && !force) return;
  near = n;
  cy.batch(() => {
    if (S.focus == null) cy.nodes().not(".blob").not(".hidden").forEach(x => x.toggleClass("labelled", near));
    cy.edges().not(".hidden").forEach(x => x.toggleClass("labelled", near).toggleClass("arrows", near || S.focus != null));
  });
}

function thresholds() {
  const out = [];
  for (const k of "rcf") {
    if (!kindsOn(k)) continue;
    const vis = POOL[k].filter(e => !cy.getElementById(e.id).hasClass("hidden"));
    if (S.focus == null && vis.length) out.push(`${KIND[k].name} <b>≥ ${fmt(vis[vis.length - 1].w)}${k === "f" ? "×" : " pts"}</b> (${vis.length})`);
  }
  $("#thr").innerHTML = S.focus == null ? (out.join("<br>") || "No relation type selected") : "Focus view lists every relation to the strongest neighbours.";
  $("#topn-v").textContent = S.topN;
}

/* labels keep a constant on-screen size (starmap: text is information, not geometry) */
let lastZ = 0;
function textScale() {
  const z = cy.zoom();
  if (Math.abs(z - lastZ) / (lastZ || 1) < .04) return;
  lastZ = z;
  cy.style().selector("node").style({ "font-size": 11 / z, "text-margin-y": 4 / z, "text-outline-width": 2.2 / z })
    .selector("node.top5").style({ "font-size": 12 / z }).selector("node.focus").style({ "font-size": 13 / z })
    .selector("node.blob").style({ "font-size": 9 / z, "text-margin-y": 0, "text-outline-width": 0 })
    .selector("edge").style({ "font-size": 9.5 / z, "text-outline-width": 2 / z,
      width: e => e.data("width") / Math.sqrt(Math.max(z, 1)) }).update();
}

/* fit into the area the panels leave free (left controls, top header, right drawer) */
function fitTo(eles, animate = true) {
  if (!eles.length) return;
  const bb = eles.boundingBox({ includeLabels: false });
  const W = cy.width(), H = cy.height(), wide = innerWidth > 720;
  const ctl = $("#ctl").getBoundingClientRect();
  const strip = $("#insights").getBoundingClientRect();
  const L = wide ? ctl.right + 24 : 16, R = W - 70, T = wide && strip.height ? strip.bottom + 22 : EMBED ? 24 : 90, B = H - 44;
  const zoom = Math.min(2.4, Math.max(cy.minZoom(), Math.min((R - L) / (bb.w + 60), (B - T) / (bb.h + 60))));
  const pan = { x: (L + R) / 2 - zoom * (bb.x1 + bb.w / 2), y: (T + B) / 2 - zoom * (bb.y1 + bb.h / 2) };
  if (animate) cy.animate({ zoom, pan }, { duration: 420, easing: "ease-out-cubic", complete: () => labels() });
  else { cy.viewport({ zoom, pan }); labels(); }
}

/* ---------- actions ---------- */
/* Focus arranges the neighbours on two rings around the person (strongest 12 inside), each keeping its original
   direction from the person; deterministic, no simulation. Leaving focus puts everyone back. */
function rings(i) {
  const c = P[i], nb = egoOf(i), inner = nb.slice(0, 12), outer = nb.slice(12);
  const ang = j => Math.atan2(P[j].y - c.y, P[j].x - c.x);
  const pos = {};
  for (const [ring, R] of [[inner, 165], [outer, 285]]) {
    const order = ring.slice().sort((a, b) => ang(a) - ang(b));
    order.forEach((j, k) => {
      const a = (order.length ? ang(order[0]) : 0) + 2 * Math.PI * k / order.length;
      pos[P[j].id] = { x: c.x + R * Math.cos(a), y: c.y + R * Math.sin(a) };
    });
  }
  return pos;
}
function moveTo(pos, done) {
  cy.nodes().not(".blob").forEach(n => {
    const p = P[n.data("i")], to = pos[p.id] || { x: p.x, y: p.y }, at = n.position();
    if (Math.abs(at.x - to.x) + Math.abs(at.y - to.y) > .5) n.animate({ position: to }, { duration: 340, easing: "ease-out-cubic" });
  });
  setTimeout(done, 400);
}
function focus(i) {
  S.focus = i; S.sel = null;
  apply();
  openPerson(i);
  moveTo(rings(i), () => fitTo(visiblePeople()));  // also waits out the drawer shrinking the canvas
}
function overview() {
  S.focus = null; S.sel = null;
  apply();
  moveTo({}, () => fitTo(visiblePeople()));
}
function reset() {
  Object.assign(S, { focus: null, sel: null, kinds: { r: true, c: true, f: true }, topN: D.meta.caps.overview_per_kind, top20: false });
  document.querySelectorAll("[data-kind]").forEach(b => b.checked = true);
  $("#topn").value = S.topN; $("#top20").checked = false; $("#find").value = "";
  closeDrawer(false);
  apply();
  moveTo({}, () => fitTo(visiblePeople()));
}

/* ---------- drawer ---------- */
function drawer(head, body) {
  $("#insp-head").innerHTML = head; $("#insp-body").innerHTML = body; $("#insp-body").scrollTop = 0;
  const ins = $("#insp");
  const was = ins.classList.contains("on");
  ins.classList.add("on"); ins.setAttribute("aria-hidden", "false"); document.body.classList.add("drawer-open");
  if (!was && innerWidth > 900) {
    document.documentElement.style.setProperty("--insp", ins.offsetWidth + "px");
    setTimeout(() => cy.resize(), 360);
  }
}
function closeDrawer(refit = true) {
  const ins = $("#insp");
  if (!ins.classList.contains("on")) return false;
  ins.classList.remove("on"); ins.setAttribute("aria-hidden", "true"); document.body.classList.remove("drawer-open");
  document.documentElement.style.setProperty("--insp", "0px");
  if (S.sel) { cy.getElementById(S.sel).removeClass("sel"); S.sel = null; }
  setTimeout(() => { cy.resize(); if (refit) fitTo(visiblePeople()); }, 360);
  return true;
}

function tierTxt(t) {
  if (t == null) return `<span class="tier">not triaged</span>`;
  const name = D.meta.tiers[t];
  return `<span class="tier ${t >= 4 ? "hi" : ""}">${name} · ${D.meta.tier_points[t]} pts</span>`;
}
function prList(e) {
  if (!e.prs.length) return "";
  return `<ul class="prs">${e.prs.map(ref => {
    const n = ref.match(/^\d+/)[0], ev = ref.slice(n.length).split("").map(c => EV[c]).join(", ");
    const [title, t, d] = D.prs[n] || ["", null, ""];
    return `<li><a class="n" href="https://github.com/${D.meta.repo}/pull/${n}" target="_blank" rel="noopener">#${n} ↗</a>
      <span class="t">${esc(title)}</span>
      <span class="meta">${tierTxt(t)} · ${esc(ev)} · ${esc(d)}</span></li>`;
  }).join("")}</ul>`;
}
function ghSearch(e) {
  const [w0, w1] = D.meta.window;
  const q = `is:pr is:merged author:${P[e.t].id} reviewed-by:${P[e.s].id} merged:${w0}..${w1}`;
  return `https://github.com/${D.meta.repo}/pulls?q=${encodeURIComponent(q)}`;
}
function moreNote(e) {
  const shown = e.prs.length;
  if (shown >= e.n) return "";
  const head = `Showing the ${shown} highest-impact of ${e.n} PRs.`;
  const tail = e.k === "r" ? ` <a href="${ghSearch(e)}" target="_blank" rel="noopener">All on GitHub ↗</a>` : "";
  return `<p class="more">${head}${tail}</p>`;
}
const metric = e => e.k === "f" ? `${e.w}× · ${e.n} PR${e.n > 1 ? "s" : ""}` : `${fmt(e.w)} pts · ${fmt(e.n)} PR${e.n > 1 ? "s" : ""}`;
const nm = i => `<b>${esc(P[i].id)}</b>`;
const many = (n, one, more = one + "s") => `${fmt(n)} ${n === 1 ? one : more}`;
const edgeOf = (s, t, k) => EIDX.get(`${s}|${t}|${k}`);

/* What a relation means, read from its counts in both directions. Returns [tag, sentence]. */
function meaning(e) {
  const x = e.s, y = e.t, ev = e.ev || {}, back = edgeOf(y, x, e.k);
  if (e.k === "r") {
    if (back && Math.min(e.n, back.n) >= 5 && Math.min(e.n, back.n) / Math.max(e.n, back.n) >= .33)
      return ["Review partners", `${nm(x)} and ${nm(y)} review each other: ${many(e.n, "PR")} one way, ${fmt(back.n)} the other.`];
    const a = ev.A || 0, share = P[y].rev_n ? a / P[y].rev_n : null;
    const cr = ev.R ? `, ${many(ev.R, "PR")} with change requests` : "";
    if (a && share >= .25)
      return ["Main approver", `${nm(x)} approved ${fmt(a)} of ${nm(y)}'s PRs (${pct(share)} of their human-reviewed PRs)${cr}.`];
    return [share >= .05 ? "Regular reviewer" : "Occasional reviewer",
      `${nm(x)} reviewed ${many(e.n, "PR")} by ${nm(y)}${a ? `, approving ${fmt(a)}${share != null ? ` (${pct(share)} of ${esc(P[y].id)}'s reviewed PRs)` : ""}` : ""}${cr}.`];
  }
  if (e.k === "c")
    return back ? ["Build on each other", `${nm(x)}'s ${many(e.n, "PR")} changed files ${nm(y)} had written; ${fmt(back.n)} the other way.`]
      : ["Builds on their work", `${nm(x)}'s ${many(e.n, "PR")} changed files ${nm(y)} had written earlier in the window.`];
  const v = ev.V || 0, f = ev.F || 0;
  return [v && !f ? "Reverted their work" : "Fixes their breakages",
    `${nm(x)} merged ${[f && many(f, "follow-up fix", "follow-up fixes"), v && many(v, "revert")].filter(Boolean).join(" and ")} for ${nm(y)}'s PRs.`];
}
function counts(x, y) {  // both directions, every relation type drawn between the two
  const row = (a, b) => ["r", "c", "f"].map(k => { const e = edgeOf(a, b, k); return e && `${{ r: "review", c: "builds on", f: "fix" }[k]} ${fmt(e.n)}`; })
    .filter(Boolean).join(" · ") || "—";
  return `<div class="cnt"><span>${esc(P[x].id)} →</span>${row(x, y)}</div><div class="cnt"><span>${esc(P[y].id)} →</span>${row(y, x)}</div>`;
}
/* Relation card: meaning, both-direction counts, top 3 PRs (≤ 8 lines). links=false inside the hover tooltip. */
function relCard(e, links = true) {
  const [tag, text] = meaning(e);
  const top = e.prs.slice(0, 3).map(ref => {
    const n = ref.match(/^\d+/)[0], [title, t] = D.prs[n] || ["", null];
    const num = links ? `<a href="https://github.com/${D.meta.repo}/pull/${n}" target="_blank" rel="noopener">#${n}</a>` : `<span class="n">#${n}</span>`;
    return `<li>${num} <span class="tier ${t >= 4 ? "hi" : ""}">${t == null ? "untriaged" : D.meta.tiers[t]}</span> <span class="t">${esc(title)}</span></li>`;
  }).join("");
  const rest = e.n - Math.min(3, e.prs.length);
  const more = rest <= 0 ? "" : links ? `<a href="#" data-edge="${e.i}">+${fmt(rest)} more PRs</a>` : `+${fmt(rest)} more · click the line`;
  return `<div class="rel"><p class="mean"><span class="tag">${tag}</span>${text}</p>${counts(e.s, e.t)}
    ${top ? `<ul class="top3">${top}</ul>` : ""}${more ? `<p class="more">${more}</p>` : ""}</div>`;
}

function openPerson(i) {
  const p = P[i], pr = p.prof, id = esc(p.id);
  const c = D.communities.find(x => x.id === p.comm);
  const rel = focusEdges(i);
  const appr = e => (e.ev && e.ev.A) || 0;
  const by = (list, val) => { const m = Math.max(1, ...list.map(val)); return list.map(e => [e, val(e), val(e) / m]).sort((a, b) => b[1] - a[1]); };
  const groups = [
    [`Who gates ${id}'s work`, "share of their human-reviewed PRs each reviewer approved",
      rel.filter(e => e.k === "r" && e.t === i).map(e => [e, appr(e), p.rev_n ? appr(e) / p.rev_n : 0]).sort((a, b) => b[1] - a[1] || b[0].n - a[0].n),
      e => e.s, (e, v, f) => `${fmt(v || e.n)} ${v ? "approved" : "reviewed"} · ${pct(f)}`],
    [`Whose work ${id} gates`, "share of that author's human-reviewed PRs",
      rel.filter(e => e.k === "r" && e.s === i).map(e => [e, appr(e), P[e.t].rev_n ? appr(e) / P[e.t].rev_n : 0]).sort((a, b) => b[1] - a[1] || b[0].n - a[0].n),
      e => e.t, (e, v, f) => `${fmt(v || e.n)} of theirs · ${pct(f)}`],
    [`Who builds on ${id}'s code`, "PRs that changed files they had written",
      by(rel.filter(e => e.k === "c" && e.t === i), e => e.n), e => e.s, e => `${many(e.n, "PR")}`],
    ["Fix / revert ties", "follow-up fixes and reverts, either way",
      by(rel.filter(e => e.k === "f"), e => e.n), e => e.s === i ? e.t : e.s,
      e => e.t === i ? `fixed ${fmt(e.n)} of ${id}'s` : `${id} fixed ${fmt(e.n)}`],
  ];
  const row = (e, v, f, other, txt) => `<details class="sm-rel"><summary><span class="who">${esc(P[other(e)].id)}</span>
      <span class="bar"><i style="width:${Math.max(2, Math.min(100, f * 100))}%"></i></span><span class="m">${txt(e, v, f)}</span>
      <button class="go" data-focus="${other(e)}" title="Focus on this person">focus</button></summary><div class="in">${relCard(e)}</div></details>`;
  const secs = groups.filter(([, , g]) => g.length).map(([title, hint, g, other, txt], gi) =>
    `<div class="sm-sec" title="${esc(hint)}">${title} <s>${g.length}</s></div>` +
    g.slice(0, 5).map(([e, v, f]) => row(e, v, f, other, txt)).join("") +
    (g.length > 5 ? `<div class="rest" id="rest${gi}" hidden>${g.slice(5).map(([e, v, f]) => row(e, v, f, other, txt)).join("")}</div>
      <button class="sm-ghost" data-rest="rest${gi}">Show all ${g.length}</button>` : "")).join("");

  const struct = [p.bridge && `bridge #${p.bridge.rank}, links ${p.bridge.reach} review communities`,
    c && `review community: ${esc(c.team || "mixed")}`, p.single && `single approver for ${esc(p.single.join(", "))}`].filter(Boolean);
  const line1 = pr && pr.net ? esc(pr.net) + "." : `${fmt(p.prs)} PRs in the window${p.area ? `, mostly ${esc(p.area)}` : ""}.`;
  const stab = pr && pr.stab ? { stable: "stable rank", borderline: "borderline rank", verdict_only: "verdict-only rank" }[pr.stab] : null;
  const head = `<div class="k">Person · ${p.rank ? `rank ${p.rank}` : p.cand ? "shortlisted 20" : "team member"}</div>
    <h3>${p.rank ? `#${p.rank} ` : ""}${id}</h3>
    <div class="one">${esc((p.team || []).join(", ") || "team unknown")}${pr && pr.pos ? ` · ${esc(pr.pos)}` : p.area ? ` · mostly ${esc(p.area)}` : ""}</div>
    ${pr ? `<div class="traits">${pr.traits.map(t => `<span class="trait">${esc(t)}</span>`).join("")}${stab ? `<span class="trait muted">${stab}</span>` : ""}${pr.flags ? `<span class="trait warn">${many(pr.flags, "caveat")}</span>` : ""}</div>` : ""}`;
  const facts = pr && pr.facts.length ? `<div class="kf">${pr.facts.map(([v, l]) => `<div><b>${esc(v)}</b><span>${esc(l)}</span></div>`).join("")}</div>`
    : `<div class="sm-chips"><span class="sm-chip">PRs <b>${fmt(p.prs)}</b></span><span class="sm-chip">Major+ episodes <b>${fmt(p.majors)}</b></span><span class="sm-chip">First-pass <b>${pct(p.fpr)}</b></span></div>`;
  const links = `<div class="links"><a href="https://github.com/${encodeURIComponent(p.id)}" target="_blank" rel="noopener">GitHub profile ↗</a>` +
    (p.cand ? `<a href="${CAND_URL(p.id)}" target="_top">Dashboard detail ↗</a>` : "") + `</div>`;
  drawer(head, `<div class="sm-sec">Role in the team</div><div class="sm-sum role"><p>${line1}</p>${struct.length ? `<p>${struct.join(" · ")}</p>` : ""}</div>
    ${facts}${links}${secs || '<p class="empty" style="margin-top:20px">No drawn relations.</p>'}${howTo()}`);
}

function openEdge(e) {
  const s = P[e.s].id, t = P[e.t].id, K = KIND[e.k];
  const [tag, text] = meaning(e);
  const head = `<div class="k">Relation · ${K.name}</div>
    <h3>${esc(s)}<span class="arrow">→</span>${esc(t)}</h3>
    <div class="one"><span class="tag">${tag}</span>${text}</div>`;
  drawer(head, `<div class="rel">${counts(e.s, e.t)}</div>
    <div class="sm-sec" style="margin-top:18px">PRs behind it <s>highest impact first</s></div>
    ${prList(e) || '<p class="empty">No PR list bundled for this relation.</p>'}${moreNote(e)}
    <p class="more">${K.says(esc(s), esc(t))}</p>
    <div class="sm-chips"><button class="sm-chip" data-focus="${e.s}" style="cursor:pointer;background:none">focus ${esc(s)}</button>
    <button class="sm-chip" data-focus="${e.t}" style="cursor:pointer;background:none">focus ${esc(t)}</button></div>${howTo()}`);
}

/* insights strip: each chip highlights the people it is about */
function insightsBar() {
  const ins = D.meta.insights || [];
  $("#insights").innerHTML = ins.map((x, k) => `<button class="ins" data-ins="${k}" ${x.nodes.length ? "" : "disabled"} title="${esc(x.note)}">${esc(x.text)}</button>`).join("")
    + `<div class="insight-note" id="insight-note"></div>`;
  $("#insights").addEventListener("click", ev => {
    const b = ev.target.closest("[data-ins]");
    if (!b || b.disabled) return;
    const k = +b.dataset.ins;
    S.hi = S.hi === k ? null : k;
    if (S.focus != null) { closeDrawer(false); overview(); } else apply();
  });
}
function highlight() {
  document.querySelectorAll(".ins").forEach(b => b.classList.toggle("on", +b.dataset.ins === S.hi));
  const note = $("#insight-note");
  if (S.hi == null) { note.textContent = ""; return; }
  const x = D.meta.insights[S.hi], set = new Set(x.nodes);
  note.textContent = x.note;
  cy.nodes().not(".blob").not(".hidden").forEach(n => { n.toggleClass("hi", set.has(n.id())); n.toggleClass("lo", !set.has(n.id())); });
  cy.edges().not(".hidden").addClass("lo");
}

function howTo() {
  const m = D.meta, c = m.caps;
  return `<details class="sm-more"><summary>How this graph is built</summary><div class="in">
    <p><b>People.</b> The ${m.counts.core} people in the overview are the shortlisted 20, the top ${c.flow_top} by importance flow, the 10 strongest bridges between review communities, and each community's main reviewer (at most ${c.nodes}). Bots and unattributed AI-agent PRs never appear.</p>
    <p><b>Size</b> is importance flow: every PR's tier points go to its author, and 0.3× to each reviewer who wrote a review or requested changes. Tier points: ${m.tiers.slice(1).map((t, i) => `${t} ${m.tier_points[i + 1]}`).join(", ")}. Only PRs of the 82 recalled engineers were triaged (${fmt(m.counts.triaged_prs)} of ${fmt(m.counts.window_prs)}); untriaged PRs carry 0 points. People outside the shortlisted 20 are drawn at 80% size so the shortlist stands out.</p>
    <p><b>Colour</b> is the review community (Louvain on who reviews whom). Communities cut across org teams: the label is the most common team, often under half the members.</p>
    <p><b>Lines.</b> Review and builds-on weights are the sum of the PRs' tier points; fix/revert weight is a count. The overview draws the strongest ${c.overview_per_kind} of each type (slider up to ${c.core_edges_per_kind}). Review requests are not drawn (data covers too few PRs).</p>
    <p><b>Focus</b> shows a person's ${c.neighbors} strongest neighbours. Lines in the overview list their top ${c.edge_prs} PRs; lines that appear only in focus list their top ${c.ego_edge_prs} (fix/revert lines up to ${c.edge_prs}), highest impact first. Review relations link to the full list on GitHub.</p>
    <p>Window ${m.window[0]} → ${m.window[1]} · layout seed ${m.seed}.</p></div></details>`;
}

/* ---------- static chrome ---------- */
function header() {
  const m = D.meta;
  $("#sub").textContent = "Each dot is an engineer, sized by the importance of the PRs they wrote or substantively reviewed. " +
    "Lines are reviews, code others built on, and fixes. Click any of them to see the PRs behind it.";
  $("#readout").innerHTML = [["People", m.counts.core], ["Window", `${m.window[0].slice(5)} → ${m.window[1].slice(5)}`],
    ["Merged PRs", fmt(m.counts.window_prs)]].map(([k, v]) => `<div><span>${k}</span><b>${v}</b></div>`).join('<div class="sep"></div>');
  if (m.placeholder) {
    const b = $("#banner");
    b.hidden = false;
    b.innerHTML = `<b>Prototype</b> · final Top 5 not decided yet, so no ranks are shown; rings mark the shortlisted 20`;
  }
  $("#logins").innerHTML = P.map(p => `<option value="${esc(p.id)}">`).join("");
}
function legend() {
  const m = D.meta;
  const comms = D.communities.filter(c => P.some(p => p.core && p.comm === c.id));
  const big = comms.filter(c => c.id < PALETTE.length), small = comms.filter(c => c.id >= PALETTE.length);
  $("#legend").innerHTML = `<h4>People</h4>
    <div class="row"><span class="dot" style="width:6px;height:6px;background:#8a96b8"></span><span class="dot" style="width:14px;height:14px;background:#8a96b8"></span>size = importance flow</div>
    <div class="row"><span class="ring thick"></span>Top 5${m.placeholder ? " <s>rank pending</s>" : ""}</div>
    <div class="row"><span class="ring thin"></span>shortlisted 20 (named)</div>
    <h4>Review community · main team</h4>
    ${big.map(c => `<div class="row"><span class="dot" style="background:${PALETTE[c.id]}"></span>${esc(c.team || "mixed")}<s>${c.size} · ${pct(c.purity)}</s></div>`).join("")}
    ${small.length ? `<div class="row" title="${esc(small.map(c => `${c.team || "mixed"} (${c.size})`).join(", "))}"><span class="dot" style="background:${OTHER}"></span>${small.length} small communities<s>${small.reduce((a, c) => a + c.size, 0)} ppl</s></div>` : ""}
    <h4>Lines</h4>
    <div class="row"><span class="sw r"></span>reviewer → author <s>pts</s></div>
    <div class="row"><span class="sw c"></span>later author → original <s>pts</s></div>
    <div class="row"><span class="sw f"></span>fixer → original author <s>count</s></div>
    <p class="note">Community size · share of its members (with a known team) on the main team.</p>`;
}
function controls() {
  document.querySelectorAll("[data-kind]").forEach(b => b.addEventListener("change", () => { S.kinds[b.dataset.kind] = b.checked; apply(); }));
  $("#topn").addEventListener("input", e => { S.topN = +e.target.value; if (S.focus == null) apply(); else thresholds(); });
  $("#top20").addEventListener("change", e => { S.top20 = e.target.checked; S.focus = null; closeDrawer(false); apply(); moveTo({}, () => fitTo(visiblePeople())); });
  $("#reset").addEventListener("click", reset);
  $("#find").addEventListener("change", e => { const i = BY[e.target.value.trim()]; if (i != null) focus(i); });
  $("#zin").addEventListener("click", () => zoomBy(1.35));
  $("#zout").addEventListener("click", () => zoomBy(1 / 1.35));
  $("#zfit").addEventListener("click", overview);
  $("#insp-x").addEventListener("click", () => closeDrawer());
  $("#insp-body").addEventListener("click", e => {
    const b = e.target.closest("[data-focus]"), m = e.target.closest("[data-edge]"), r = e.target.closest("[data-rest]");
    if (b) { e.preventDefault(); focus(+b.dataset.focus); }
    if (m) { e.preventDefault(); openEdge(E[+m.dataset.edge]); }
    if (r) { $("#" + r.dataset.rest).hidden = false; r.remove(); }
  });
  addEventListener("keydown", e => {
    if (e.target.tagName === "INPUT") return;
    if (e.key === "f" || e.key === "F") overview();
    if (e.key === "Escape") { if (closeDrawer()) return; if (S.focus != null) overview(); else if (S.hi != null) { S.hi = null; apply(); } }
  });
  if (innerWidth <= 720) $("#ctl-d").open = false;
  addEventListener("resize", () => { cy.resize(); if (innerWidth > 720) $("#ctl-d").open = true; });
}
function zoomBy(f) {
  const z = Math.min(cy.maxZoom(), Math.max(cy.minZoom(), cy.zoom() * f));
  cy.animate({ zoom: { level: z, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } } }, { duration: 220, complete: () => labels() });
}

/* ---------- canvas events ---------- */
function events() {
  const tip = $("#tip");
  const place = ev => {
    const r = $("#cy").getBoundingClientRect(), x = r.left + ev.renderedPosition.x, y = r.top + ev.renderedPosition.y;
    tip.style.left = Math.min(x + 16, innerWidth - tip.offsetWidth - 10) + "px";
    tip.style.top = Math.min(y + 14, innerHeight - tip.offsetHeight - 10) + "px";
  };
  cy.on("mouseover", "node", ev => {
    const n = ev.target;
    if (n.hasClass("blob") || n.hasClass("hidden")) return;
    const p = P[n.data("i")], pr = p.prof;
    const top = `<b>${p.rank ? `#${p.rank} ` : ""}${esc(p.id)}</b> <s>${esc((p.team || []).join(", ") || "team unknown")}</s>`;
    tip.innerHTML = pr ? `${top}<div class="traits">${pr.traits.map(t => `<span class="trait">${esc(t)}</span>`).join("")}</div>
      ${pr.pos ? `<div class="pos">${esc(pr.pos)}</div>` : ""}
      <div class="nums">${pr.facts.map(([v]) => `<span><i>${esc(v)}</i></span>`).join("")}</div>`
      : `${top}${p.area ? `<div>${esc(p.area)}</div>` : ""}
      <div class="nums"><span>PRs <i>${fmt(p.prs)}</i></span><span>major+ <i>${fmt(p.majors)}</i></span><span>first-pass <i>${pct(p.fpr)}</i></span></div>`;
    tip.classList.add("on"); place(ev);
    const mine = n.connectedEdges().not(".hidden");  // emphasis: its lines full, everything else recedes
    cy.edges().not(".hidden").not(mine).addClass("dim");
    cy.nodes().not(".blob").not(".hidden").not(".faded").not(mine.connectedNodes()).addClass("dim");
    n.addClass("hl"); mine.addClass("hl");
    $("#cy").style.cursor = "pointer";
  });
  cy.on("mouseover", "edge", ev => {
    const e = E[+ev.target.id().slice(1)];
    tip.innerHTML = relCard(e, false);
    tip.classList.add("on"); place(ev);
    cy.edges().not(".hidden").not(ev.target).addClass("dim");
    cy.nodes().not(".blob").not(".hidden").not(".faded").not(ev.target.connectedNodes()).addClass("dim");
    ev.target.addClass("hl");
    $("#cy").style.cursor = "pointer";
  });
  cy.on("mousemove", "node, edge", place);
  cy.on("mouseout", "node, edge", ev => {
    tip.classList.remove("on");
    cy.elements().removeClass("hl dim");
    $("#cy").style.cursor = "";
  });
  cy.on("tap", "node", ev => { if (!ev.target.hasClass("blob")) { tip.classList.remove("on"); focus(ev.target.data("i")); } });
  cy.on("tap", "edge", ev => {
    tip.classList.remove("on");
    if (S.sel) cy.getElementById(S.sel).removeClass("sel");
    S.sel = ev.target.id(); ev.target.addClass("sel");
    openEdge(E[+S.sel.slice(1)]);
  });
  cy.on("tap", ev => { if (ev.target === cy) closeDrawer(false); });
  cy.on("dbltap", ev => { if (ev.target === cy) overview(); });
  cy.on("zoom", () => requestAnimationFrame(() => { labels(); textScale(); }));
}
})();
