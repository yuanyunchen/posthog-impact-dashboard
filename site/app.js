"use strict";
let D = null;
const $ = (s, el = document) => el.querySelector(s);
const ANGLES = ["delivery", "system", "quality", "team"];
const ANGLE_LABEL = { delivery: "Delivery", system: "System", quality: "Quality", team: "Team" };
const TIERS = ["mechanical", "trivial", "routine", "substantive", "major", "landmark"];
const TIER_COLOR = { mechanical: "#2c3654", trivial: "#43507a", routine: "#5f78b0", substantive: "#8fc6ff", major: "#c3a8ff", landmark: "#9ee493" };

/* ---------- formatting ---------- */
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
function fmt(v) {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v !== "number") return String(v);
  if (Number.isInteger(v)) return v.toLocaleString("en-US");
  const a = Math.abs(v);
  if (a >= 100) return v.toLocaleString("en-US", { maximumFractionDigits: 0 });
  if (a >= 10) return v.toFixed(1);
  if (a >= 0.1 || a === 0) return v.toFixed(2);
  return v.toPrecision(2);
}
const pctTxt = p => (p === null || p === undefined ? "" : `P${Math.round(p)}`);
const def = k => D.definitions[k] || { label: k, formula: "No definition recorded for this key.", source: "" };
/** A number whose definition, raw value and percentile show on hover / tap. */
function num(key, value, pct, text) {
  const p = pct === null || pct === undefined ? "" : ` data-p="${pct}"`;
  return `<span data-def="${esc(key)}" data-v="${esc(JSON.stringify(value ?? null))}"${p} tabindex="0">${esc(text ?? fmt(value))}</span>`;
}
const prLink = (n, ph) => ph
  ? `<span class="mono" title="Synthetic placeholder PR number, not a real PostHog PR">#${esc(n)}</span>`
  : `<a class="mono" href="https://github.com/PostHog/posthog/pull/${encodeURIComponent(n)}" target="_blank" rel="noopener">#${esc(n)}</a>`;
const ghLink = l => `<a href="https://github.com/${encodeURIComponent(l)}" target="_blank" rel="noopener">@${esc(l)}</a>`;
const list = xs => (xs && xs.length ? xs : null);
// metrics computed from fetched review text / requests, which is capped per candidate (review_coverage.json)
const REVIEW_TEXT_KEYS = new Set(["comment_line_changed_rate", "review_requesters", "m.requested_by", "n.requested_by_n", "f.requested_by"]);
function covNote(key, login, short) {
  const c = REVIEW_TEXT_KEYS.has(key) && (D.review_coverage || {})[login];
  if (!c) return "";
  const t = short ? `${fmt(c.reviewed_fetched)}/${fmt(c.reviewed_total)} rev.` : `based on ${fmt(c.reviewed_fetched)} of ${fmt(c.reviewed_total)} reviewed PRs`;
  return ` <span class="pct" data-def="review_coverage" data-v="${esc(JSON.stringify(`${c.reviewed_fetched} of ${c.reviewed_total} reviewed PRs fetched`))}" tabindex="0">${esc(t)}</span>`;
}

/* ---------- tooltip ---------- */
const tip = $("#tip");
let pinned = null;
function showTip(el) {
  const d = def(el.dataset.def);
  let v = null;
  try { v = JSON.parse(el.dataset.v); } catch (e) { v = el.dataset.v; }
  const p = el.dataset.p;
  tip.innerHTML = `<div class="t-label">${esc(d.label)}</div>`
    + `<div class="t-val">Value: <b>${esc(fmt(v))}</b>${p ? ` · percentile ${Math.round(+p)} among candidates` : ""}${v === null ? " (unknown: data missing or sample too small)" : ""}</div>`
    + `<div class="t-f">${esc(d.formula)}</div>${d.direction === "lower" ? '<div class="t-f">Lower is better.</div>' : ""}`
    + (d.source ? `<div class="t-src">${esc(d.source)}</div>` : "");
  tip.hidden = false;
  const r = el.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight;
  let x = Math.min(Math.max(8, r.left), window.innerWidth - w - 8);
  let y = r.bottom + 6;
  if (y + h > window.innerHeight - 8) y = Math.max(8, r.top - h - 6);
  tip.style.left = x + "px"; tip.style.top = y + "px";
}
function hideTip() { if (!pinned) tip.hidden = true; }
document.addEventListener("mouseover", e => { const el = e.target.closest("[data-def]"); if (el && !pinned) showTip(el); });
document.addEventListener("mouseout", e => { if (e.target.closest("[data-def]")) hideTip(); });
document.addEventListener("focusin", e => { const el = e.target.closest("[data-def]"); if (el && !pinned) showTip(el); });
document.addEventListener("focusout", e => { if (e.target.closest("[data-def]")) hideTip(); });
document.addEventListener("click", e => {
  const el = e.target.closest("[data-def]");
  if (el && !el.closest("th.sortable")) {
    e.stopPropagation(); e.preventDefault();
    if (pinned === el) { pinned = null; tip.classList.remove("pinned"); tip.hidden = true; return; }
    pinned = null; showTip(el); pinned = el; tip.classList.add("pinned"); return;
  }
  if (pinned && !e.target.closest("#tip")) { pinned = null; tip.classList.remove("pinned"); tip.hidden = true; }
}, true);
document.addEventListener("keydown", e => {
  if (e.key !== "Escape") return;
  const wasPinned = !!pinned;
  pinned = null; tip.classList.remove("pinned"); tip.hidden = true;
  if (wasPinned) return;  // first Esc unpins a tooltip, the next closes the layer
  if (drawer.classList.contains("open")) closeDrawer();
  else if (!$("#modal").hidden) closeModal();
});

/* ---------- sortable table ---------- */
function mountTable(el, cols, rows, opts = {}) {
  let sortKey = opts.sort || null, dir = opts.dir || -1;
  const val = (c, r) => (c.sortVal ? c.sortVal(r) : r[c.key]);
  function draw() {
    const rs = rows.slice();
    if (sortKey) {
      const c = cols.find(c => c.key === sortKey);
      rs.sort((a, b) => {
        const x = val(c, a), y = val(c, b);
        if (x === y) return 0;
        if (x === null || x === undefined) return 1;
        if (y === null || y === undefined) return -1;
        return (typeof x === "string" ? x.localeCompare(y) : x - y) * dir;
      });
    }
    const head = cols.map(c => {
      const lab = c.def ? `<span data-def="${esc(c.def)}" data-v="null">${esc(c.label)}</span>` : esc(c.label);
      const arrow = c.key === sortKey ? `<span class="arrow">${dir < 0 ? "▼" : "▲"}</span>` : "";
      return `<th class="${c.sortable === false ? "" : "sortable"} ${c.num ? "num" : ""} ${c.wrap ? "wrap" : ""}" data-k="${esc(c.key)}" ${c.sortable === false ? "" : 'aria-sort="none" tabindex="0"'}>${lab}${arrow}</th>`;
    }).join("");
    const body = rs.map(r => `<tr class="${opts.onRow ? "clickable" : ""}" data-login="${esc(r.login || "")}">`
      + cols.map(c => `<td class="${c.num ? "num" : ""} ${c.wrap ? "wrap" : ""}">${c.render ? c.render(r) : esc(fmt(r[c.key]))}</td>`).join("") + "</tr>").join("");
    el.innerHTML = `<div class="tbl-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body || `<tr><td colspan="${cols.length}" class="empty">No rows.</td></tr>`}</tbody></table></div>`;
  }
  el.addEventListener("click", e => {
    const th = e.target.closest("th.sortable");
    if (th) {
      const k = th.dataset.k; dir = k === sortKey ? -dir : -1; sortKey = k; draw(); return;
    }
    const tr = e.target.closest("tr.clickable");
    if (tr && opts.onRow && !e.target.closest("a,[data-def]")) opts.onRow(tr.dataset.login);
  });
  el.addEventListener("keydown", e => { if (e.key === "Enter" && e.target.matches("th.sortable")) e.target.click(); });
  draw();
}

/* ---------- A: header ---------- */
function renderHead() {
  const m = D.meta, cov = m.coverage || {}, ex = m.exclusions || {};
  document.title = "PostHog Engineering Impact";
  $("#head-meta").innerHTML = [
    `<div><span>Window</span><b>${esc(m.window.start)} → ${esc(m.window.end)}</b></div>`,
    `<div><span>Merged PRs</span><b>${fmt(cov.merged_prs)}</b></div>`,
    `<div><span>Human contributors</span><b>${num("people", cov.contributors, null)}</b></div>`,
    `<div><span>Excluded</span><b>${num("bot_prs", ex.bot_prs, null)} bot PRs, incl. ${num("ai_agent_prs", ex.ai_agent_prs, null)} AI-agent</b></div>`,
  ].join("");
  const def0 = m.impact_definition.replace(/^Impact = /, "");
  $("#definition").innerHTML = `<b>Impact</b> = ${esc(def0)}`;
  if (m.placeholder) {
    const fixture = m.fixture_sources || [];
    const b = $("#banner");
    const head = m.decision_state === "pending" ? "Prototype — final ranking pending." : "Prototype — top-layer conclusions are placeholder data.";
    b.innerHTML = `<strong>${head}</strong> ${esc(m.placeholder_note)}`
      + (fixture.length ? ` Taken from the development fixture until the full run lands: ${esc(fixture.join(", "))}.` : "");
    b.hidden = false;
  }
  $("#foot").innerHTML = `Data snapshot generated ${esc(m.generated_at)} from <span class="mono">${esc(m.out_dir)}</span> by <span class="mono">python -m impact.site_data</span>. `
    + `Repository analysed: <a href="https://github.com/${esc(m.repo)}" target="_blank" rel="noopener">${esc(m.repo)}</a>. Every number on this page links to its definition in the data file.`;
}

/* ---------- B: top 5 cards ---------- */
function badges(p) {
  const out = [];
  const st = { stable: ["ok", "Stable"], borderline: ["warn", "Borderline"], verdict_only: ["warn", "Verdict only"] }[p.stability];
  const just = p.justification || ((D.decision || {}).justifications || {})[p.login];
  if (st) out.push(`<span class="badge ${st[0]}"${just ? ` title="${esc(just)}"` : ""}>${st[1]} ${num("stability_freq", p.stability_freq, null, Math.round((p.stability_freq || 0) * 100) + "%")}</span>`);
  if (p.primary_rank && p.second_rank)
    out.push(p.primary_rank <= 5 && p.second_rank <= 5
      ? `<span class="badge ok" title="Both independent decisions placed him in the top 5 (#${p.primary_rank} / #${p.second_rank})">2/2 decisions</span>`
      : `<span class="badge warn" title="Independent decisions placed him #${p.primary_rank} and #${p.second_rank}">#${p.primary_rank} / #${p.second_rank}</span>`);
  if (list(p.caveats)) out.push(`<span class="badge caveat" title="${esc(p.caveats.join("\n"))}">⚠ ${p.caveats.length} caveat${p.caveats.length > 1 ? "s" : ""}</span>`);
  return out.join("");
}
function angleBars(p) {
  if (!p.angles || !p.angles.delivery) return `<p class="empty small">No evaluator grades yet.</p>`;
  return ANGLES.map(a => {
    const g = p.angles[a].grade;
    return `<div class="angle"><span>${ANGLE_LABEL[a]}</span><span class="track"><span class="fill" style="width:${g * 10}%"></span></span><span class="g">${num("grade." + a, g, null)}</span></div>`;
  }).join("");
}
/** Value with its unit ("70 pts", "98%"); the percentile and formula stay in the tooltip. */
function withUnit(key, v) {
  const u = def(key).unit;
  if (v === null || v === undefined) return "—";
  if (u === "%") return `${Math.round(v * 100)}%`;
  return fmt(v) + (!u ? "" : u.startsWith("/") ? u : ` ${u}`);
}
const ordinalLabel = l => String(l || "").replace(/\s*\(\s*\d+(st|nd|rd|th) of \d+\s*\)/i, "");  // rank is shown separately
const rankChip = f => f.rank ? `<span class="rk">${f.tied ? "tied " : ""}#${f.rank} of ${f.of}</span>` : "";
/** Card numbers = raw, checkable facts (spec §H): value, plain label, rank among the 20. */
function factNums(p) {
  if (!list(p.facts)) return `<p class="small muted">No raw facts for this engineer.</p>`;
  return p.facts.map(f => `<div class="bignum"><div class="top"><span class="v">${num(f.metric_key, f.value, f.pct, f.value_text)}</span>${rankChip(f)}</div>
      <div class="lab-t">${esc(f.label)}${covNote(f.metric_key, p.login, true)}</div></div>`).join("");
}
function bigNums(p) {
  return (p.key_numbers || []).map(k => {
    const d = def(k.key);
    return `<div class="bignum"><div class="top"><span class="v">${num(k.key, k.value, k.pct, withUnit(k.key, k.value))}</span>${rankChip(k)}</div>
      <div class="lab-t">${esc(ordinalLabel(k.label) || d.label)}</div>${d.plain ? `<div class="plain">${esc(d.plain)}</div>` : ""}</div>`;
  }).join("") || `<p class="empty small">No key numbers.</p>`;
}
/** Key points: complete ≤9-word phrases (cached "keypoints" stage); never clipped. Full contribution text is in the drawer. */
function points(p) {
  const xs = list(p.keypoints) || (p.contributions || []).map(c => c.headline).filter(Boolean);
  return xs.length ? `<ul class="points">${xs.slice(0, 3).map(t => `<li>${esc(t)}</li>`).join("")}</ul>` : "";
}
const tags = p => list(p.tags) ? `<div class="tagrow">${p.tags.map(t => `<span class="tag">${esc(t)}</span>`).join("")}</div>` : "";
const nameRow = (p, tag = "div") => `<${tag} class="id-row"><span class="rank">#${p.rank}</span><span class="name-big${p.login.length > 12 ? " long" : ""}">@${esc(p.login)}</span></${tag}>`;
/** Name first: rank + handle (largest) · team · personal tags · key points · raw facts · grades. Uniform chips live in the drawer. */
function card(p) {
  const ov = p.overall && p.overall.grade;
  return `<div class="card" role="button" tabindex="0" data-login="${esc(p.login)}" aria-label="Open the case for ${esc(p.login)}">
      <div class="blk">${nameRow(p)}<div class="who">${esc(p.team || "team unknown")}</div>${tags(p)}</div>
      <div class="blk">${points(p)}</div>
      <div class="blk bignums">${factNums(p)}</div>
      <div class="blk"><div class="angles">${angleBars(p)}</div>
        ${ov ? `<div class="grade-row"><span class="overall">Overall ${num("grade.overall", ov, null, String(ov))}<span class="pct">/10</span></span></div>` : ""}</div>
    </div>`;
}
function renderCards() {
  if (!D.top5.length) {
    $("#cards").innerHTML = `<div class="pending"><b>Decision pending.</b> The final top 5 has not been produced yet. The shortlist, matrix and team network below are real; open <a href="#" data-open="coarse">the 20-person shortlist</a> to explore it.</div>`;
    $("#cards").querySelector("[data-open]").addEventListener("click", e => { e.preventDefault(); openModal("coarse", e.target); });
    $("#sec-b .hint").hidden = true;
    return;
  }
  $("#cards").innerHTML = D.top5.map(card).join("");
  bindOpen($("#cards"), ".card");
  const g = (D.decision || {}).agreement;
  if (g && g.top5_overlap != null) {
    const fin = new Set(D.top5.map(p => p.login)), agreed = g.both_top5.filter(l => fin.has(l)), out = g.both_top5.filter(l => !fin.has(l));
    const swapped = D.top5.filter(p => !g.both_top5.includes(p.login)).map(p => p.login);
    $("#agree").innerHTML = `<b>Two independent decisions agreed on ${agreed.length} of the final top 5</b> (${agreed.map(l => "@" + esc(l)).join(", ")}); `
      + `their own top-5 lists overlap ${g.top5_overlap}/5, ${num("decision_agreement", g.kendall_tau, null, "Kendall τ " + g.kendall_tau)} over all ${fmt(D.matrix.rows.length)}. `
      + (out.length && swapped.length ? `The last place was settled head-to-head: @${esc(swapped.join(", @"))} beat @${esc(out.join(", @"))} in both presentation orders. ` : "")
      + `Close calls were re-asked pairwise in both orders: ${g.pairwise_consistent}/${g.pairwise_total} gave the same winner.`;
  }
}
function bindOpen(root, sel) {
  root.addEventListener("click", e => { const c = e.target.closest(sel); if (c && !e.target.closest("[data-def]")) openDrawer(c.dataset.login); });
  root.addEventListener("keydown", e => { const c = e.target.closest(sel); if (c && e.target === c && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openDrawer(c.dataset.login); } });
}

/* ---------- C: candidate drawer ---------- */
const drawer = $("#drawer"), scrim = $("#scrim");
let lastFocus = null;
/** Long text: clamped to n lines with a "more" toggle (shown only when the text actually overflows). */
const clampTxt = (t, n = 2) => t ? `<div class="clamp" style="--lines:${n}">${esc(t)}</div><button class="more" type="button" hidden>more</button>` : "";
const sec = (title, body, open, note = "") => body ? `<details class="sec"${open ? " open" : ""}><summary><h3>${esc(title)}</h3>${note ? `<span class="sum-note">${esc(note)}</span>` : ""}</summary><div class="sec-body">${body}</div></details>` : "";
function evid(ids, ph) {  // PR numbers become links; internal evidence keys are not shown
  const prs = (ids || []).filter(x => typeof x === "number");
  return prs.length ? prs.map(x => prLink(x, ph)).join(" ") : "";
}
function openDrawer(login) {
  const c = D.candidates[login];
  if (!c) return;
  lastFocus = document.activeElement;
  const p = D.top5.concat(D.next5).find(x => x.login === login);
  $("#drawer-title").innerHTML = `${p ? nameRow(p, "h2") : `<h2 class="id-row"><span class="name-big">@${esc(login)}</span></h2>`}
    <div class="who">${esc(c.team || "team unknown")}${c.role && c.role.primary_role ? " · " + esc(c.role.primary_role) : ""} · ${ghLink(login)}</div>
    ${tags(c)}${p ? `<div class="badges d-badges">${badges(p)}</div>` : ""}`;
  const facts = list(c.facts) ? `<div class="facts-row">${factNums({ facts: c.facts, login })}</div>` : "";
  const lead = (p && p.why) || c.positioning || (c.top_area ? `Main area: ${c.top_area} (${Math.round((c.top_area_share || 0) * 100)}% of his rule-weighted work).` : "");
  const summary = `<div class="summary">${c.headline ? `<p class="headline">${esc(c.headline)}</p>` : ""}${clampTxt(lead, 3)}${facts}
    ${c.key_facts_note ? `<p class="small muted">${esc(c.key_facts_note)}</p>` : ""}</div>`;
  const body = c.has_report
    ? [sec("Core contributions", contribSec(c), true), sec("Team position", teamSec(c)), sec("How the decision was made", p ? decisionSec(p) : ""),
       sec("Caveats and red flags", caveatSec(c)), sec("Evidence and all PRs", evidenceSec(c, p))]
    : [`<p class="note">The per-person evaluation for this engineer has not been produced; below is the script-level data.</p>`,
       sec("Team position", teamSec(c), true), sec("Evidence and all PRs", evidenceSec(c, p))];
  $("#drawer-body").innerHTML = summary + body.join("");
  bindPrs(c);
  drawer.classList.add("open"); drawer.setAttribute("aria-hidden", "false"); scrim.hidden = false;
  fitClamps($("#drawer-body"));
  $("#drawer-body").scrollTop = 0; $("#drawer-close").focus();
}
function fitClamps(root) {
  for (const el of root.querySelectorAll(".clamp")) {
    const b = el.nextElementSibling;
    if (b && b.classList.contains("more")) b.hidden = !(el.scrollHeight > el.clientHeight + 2) && !el.classList.contains("open");
  }
}
document.addEventListener("click", e => {
  const b = e.target.closest("button.more");
  if (!b) return;
  const el = b.previousElementSibling;
  el.classList.toggle("open"); b.textContent = el.classList.contains("open") ? "less" : "more";
});
// clamps inside a section are measured when the section is first opened
document.addEventListener("toggle", e => { if (e.target.matches && e.target.matches("details.sec") && e.target.open) fitClamps(e.target); }, true);
function closeDrawer() {
  if (!drawer.classList.contains("open")) return;
  if (location.hash.startsWith("#candidate=")) history.replaceState(null, "", location.pathname + location.search);
  drawer.classList.remove("open"); drawer.setAttribute("aria-hidden", "true"); scrim.hidden = true;
  if (lastFocus) lastFocus.focus();
}
$("#drawer-close").addEventListener("click", closeDrawer);
scrim.addEventListener("click", closeDrawer);

function contribSec(c) {
  const ph = c.placeholder;
  return (c.core_contributions || []).map((w, i) => {
    return `<div class="contrib"><div class="ttl">${esc(w.title)}</div>
      ${clampTxt(w.outcome, 1)}
      <div class="meta">${w.his_role ? `<span class="small muted">${esc(w.his_role)}</span>` : ""} ${evid(w.evidence_prs, ph)}</div>
      ${w.what || w.why_it_matters ? `<details class="mini"><summary>What and why it matters</summary><p class="small">${esc(w.what)}</p><p class="small muted">${esc(w.why_it_matters)}</p></details>` : ""}</div>`;
  }).join("") || `<p class="empty">None listed.</p>`;
}
function teamSec(c) {
  const n = c.network || {}, v = k => (n[k] || {}).value;
  const chips = [["first_pass_rate", v("first_pass_rate") != null ? Math.round(v("first_pass_rate") * 100) + "%" : null],
    ["requested_by_n", v("requested_by_n")], ["built_on_by_n", v("built_on_by_n")], ["teams_covered_n", v("teams_covered_n")],
    ["fixes_given", v("fixes_given")], ["fixes_received", v("fixes_received")]]
    .filter(([, x]) => x != null).map(([k, x]) => `<div class="mchip"><b>${num("n." + k, v(k), null, String(typeof x === "number" ? fmt(x) : x))}</b><span>${esc(def("n." + k).label)}</span></div>`).join("");
  const a = c.approvals || {};
  const ap = Object.keys(a).map(k => `<div class="mchip"><b>${num("r." + k, a[k], null, k.endsWith("rate") ? (a[k] * 100).toFixed(1) + "%" : fmt(a[k]))}</b><span>${esc(def("r." + k).label)}</span></div>`).join("");
  const txt = (c.role || {}).network_summary;
  if (!txt && !chips && !ap) return "";
  return `${clampTxt(txt, 2)}${chips ? `<div class="mrow">${chips}</div>` : ""}${ap ? `<h4>Approvals and self-repair</h4><div class="mrow">${ap}</div>` : ""}${covLine(c.login)}`;
}
function decisionSec(p) {
  const dec = D.decision || {}, rows = [];
  const row = (k, v) => v ? rows.push(`<tr><th>${esc(k)}</th><td>${v}</td></tr>`) : 0;
  row("Decision 1", `#${fmt(p.primary_rank)}`);
  row("Decision 2 (blind)", `#${fmt(p.second_rank)}`);
  row("Consensus", `#${fmt(p.rank)} · ${num("borda", p.borda, null, fmt(p.borda) + " Borda points")} · ${num("R", p.R, null, "R " + fmt(p.R))} (rank ${fmt(p.R_rank)})`);
  const pw = (dec.pairwise || []).filter(x => x.a === p.login || x.b === p.login);
  if (pw.length) row("Pairwise", pw.map(x => {
    const vs = x.a === p.login ? x.b : x.a, res = !x.consistent ? "tie (orders disagreed)" : x.winner === p.login ? "won" : "lost";
    return `<div class="pwl"><b class="${res === "won" ? "ok" : res === "lost" ? "risk" : ""}">${res}</b> vs @${esc(vs)}${x.consistent ? " · both orders" : ""}${clampTxt(x.reason, 2)}</div>`;
  }).join(""));
  if (p.why && p.why !== (D.candidates[p.login] || {}).positioning) row("Ranking case", clampTxt(p.why, 2));
  if (p.not_top5) row("Why not top 5", clampTxt(p.not_top5, 2));
  row("Justification", clampTxt(p.justification || (dec.justifications || {})[p.login], 2));
  const dv = (dec.devil || []).find(x => x.cid === p.login);
  if (dv) {
    row("Devil's objection", clampTxt(dv.objection + (dv.replacement ? ` Proposed replacement: @${dv.replacement}.` : ""), 2));
    row(`Our rebuttal (${dv.decision || "—"})`, clampTxt(dv.rebuttal, 2));
  }
  const failed = ["a", "b", "c"].filter(g => p.gates && p.gates[g] === false);
  row("Gates", failed.length ? failed.map(g => esc(def("gate." + g).label) + " — not met").join("; ") : "all three passed");
  return `<table class="dtable"><tbody>${rows.join("")}</tbody></table>`;
}
function caveatSec(c) {
  const cov = c.coverage || {}, flags = c.red_flags || [];
  return `${list(c.caveats) ? `<ul class="flags verified">${c.caveats.map(t => `<li>${esc(t)}</li>`).join("")}</ul><h4>Evaluator's counter-evidence</h4>` : ""}
    ${clampTxt(c.counter_evidence, 3)}
    ${flags.length ? `<ul class="flags">${flags.map(r => `<li>${clampTxt(typeof r === "string" ? r : r.flag, 2)}<div class="meta">${typeof r === "string" ? "" : evid(r.evidence_ids, c.placeholder)}</div></li>`).join("")}</ul>` : `<p class="small muted">No red flags raised by the evaluator.</p>`}
    <p class="small muted">Coverage: ${fmt(cov.sampled_prs)} PRs deep-read · missing data: ${esc((cov.missing_data || []).join(", ") || "none")}</p>`;
}
function evidenceSec(c, p) {
  const ph = c.placeholder, h = [];
  if (c.card && list(c.card.key_numbers)) h.push(`<h4>Evaluator's key numbers</h4><div class="bignums drawer-nums">${bigNums({ ...c.card, login: c.login })}</div>`);
  if (c.angles_detail) h.push(`<h4>Grades</h4>` + mini(["Angle", "Grade", "Rationale"], ANGLES.map(a => [ANGLE_LABEL[a], num("grade." + a, c.angles_detail[a].grade, null), clampTxt(c.angles_detail[a].rationale, 2)])));
  if (list(c.insights)) h.push(`<h4>What stands out</h4><ul class="flags">${c.insights.map(i => `<li>${clampTxt(i.insight, 2)}<div class="meta">${evid(i.evidence_ids, ph)}</div></li>`).join("")}</ul>`);
  if (list(c.custom_analyses)) h.push(`<h4>Custom analyses</h4>` + mini(["Question", "Finding", "PRs"], c.custom_analyses.map(a => [clampTxt(a.question, 2), clampTxt(a.finding, 2), evid(a.evidence_ids, ph)])));
  h.push(scriptDetail(c));
  h.push(prList(c));
  return h.join("");
}
function scriptDetail(c) {
  const h = [];
  if (list(c.top_reviewed) || list(c.top_reviewers)) h.push(`<div class="grid2"><div><h4>He reviews most</h4>${people(c.top_reviewed)}</div><div><h4>Reviews him most</h4>${people(c.top_reviewers)}</div></div>`);
  if (c.matrix) h.push(`<h4>Comparison matrix row</h4>` + mini(["Metric", "Value", "Percentile"], D.matrix.columns.map(k => [num("m." + k, c.matrix.values[k], c.matrix.pct[k], def("m." + k).label), fmt(c.matrix.values[k]) + covNote("m." + k, c.login), pctTxt(c.matrix.pct[k])])));
  if (c.coarse) {
    const r = c.coarse;
    h.push(`<h4>Coarse ranking</h4><p class="small">${num("mass", r.mass, null)} importance mass × ${num("quality_factor", r.quality_factor, null)} quality factor = ${num("coarse_score", r.coarse_score, null)} coarse score · selected by ${esc((r.selected_by || []).join(", ") || "—")}</p>` + tierStack(r.tier_counts));
  }
  return h.join("");
}
function covLine(login) {
  const c = (D.review_coverage || {})[login];
  return c ? `<p class="small muted">${num("review_coverage", `${c.reviewed_fetched}/${c.reviewed_total}`, null, "Review text coverage")}: comments and review requests were read for ${fmt(c.reviewed_fetched)} of ${fmt(c.reviewed_total)} PRs he reviewed and ${fmt(c.authored_fetched)} of ${fmt(c.authored_total)} PRs he authored.</p>` : "";
}
// full PR lists live in prs/<login>.js and load only when "All PRs" is opened
function bindPrs(c) {
  const det = $("#drawer-body details.pr-fold");
  if (!det) return;
  const filter = () => {
    const sel = $(".tier-filter", det);
    if (sel) sel.addEventListener("change", () => {
      for (const li of det.querySelectorAll(".prs li[data-tier]")) li.hidden = sel.value && li.dataset.tier !== sel.value;
    });
  };
  if (!c.prs_file) return filter();
  det.addEventListener("toggle", () => {
    if (!det.open || det.dataset.done) return;
    det.dataset.done = "1";
    const show = () => { $(".fold-body", det).innerHTML = prBody(c, window.SITE_PRS[c.login]); filter(); };
    if (window.SITE_PRS && window.SITE_PRS[c.login]) return show();
    const s = document.createElement("script");
    s.src = c.prs_file;
    s.onload = show;
    s.onerror = () => { $(".fold-body", det).innerHTML = `<p class="empty">Could not load ${esc(c.prs_file)}.</p>`; };
    document.head.appendChild(s);
  });
}
function people(xs) { return list(xs) ? `<ul class="plain">${xs.map(x => `<li>${ghLink(x.login)} — ${fmt(x.prs)} PRs</li>`).join("")}</ul>` : `<p class="empty small">None.</p>`; }
function mini(head, rows) {
  return `<div class="tbl-wrap"><table><thead><tr>${head.map(x => `<th>${esc(x)}</th>`).join("")}</tr></thead><tbody>${rows.map(r => `<tr>${r.map((x, i) => `<td class="${i === r.length - 1 && String(x).length > 40 ? "wrap" : ""}${typeof x === "string" && x.length > 60 ? " wrap" : ""}">${x}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
function prBody(c, ws) {
  const n = ws.reduce((s, w) => s + w.prs.length, 0);
  return `<p class="small">Show tier <select class="filter tier-filter" aria-label="Filter PRs by tier"><option value="">all</option>${TIERS.map(t => `<option>${t}</option>`).join("")}</select> · ${n} PRs in ${ws.length} workstreams</p>`
      + ws.map(w => `<h4>${esc(w.title)}</h4><ul class="prs">${w.prs.map(p => `<li data-tier="${esc(p.tier)}"><span class="tier ${esc(p.tier)}">${esc(p.tier || "untriaged")}</span>${prLink(p.number, c.placeholder)} ${p.P != null ? `<span class="small muted">P ${fmt(p.P)}</span> ` : ""}${esc(p.summary)}</li>`).join("")}</ul>`).join("");
}
function prList(c) {
  const ws = c.workstreams;
  let body;
  if (c.prs_file) {
    const n = c.workstreams_summary.reduce((s, w) => s + w.prs_n, 0);
    body = `<p class="small muted pr-slot">${fmt(n)} PRs in ${c.workstreams_summary.length} workstreams — loading…</p>`;
  } else if (list(ws)) {
    body = prBody(c, ws);
  } else {
    const ids = [...new Set((c.core_contributions || []).flatMap(w => w.evidence_prs || []))];
    body = ids.length ? `<p class="small muted">Only the evidence PRs of the evaluation are available for this person.</p><ul class="prs">${ids.map(n => `<li>${prLink(n, c.placeholder)}</li>`).join("")}</ul>` : `<p class="empty">No PR list in the outputs.</p>`;
  }
  return `<details class="fold pr-fold"><summary><h3>All PRs</h3><span class="sum-note">grouped by workstream</span></summary><div class="fold-body">${body}</div></details>`;
}

/* ---------- D: ranks 6–10 ---------- */
function renderNext(el) {
  if (!D.next5.length) { el.innerHTML = `<p class="empty">${D.top5.length ? "No ranks 6–10 in the outputs." : "Pending the final decision."}</p>`; return; }
  el.innerHTML = D.next5.map(p => `<div class="ncard" data-login="${esc(p.login)}" role="button" tabindex="0" aria-label="Open the case for ${esc(p.login)}">
      ${nameRow(p)}<div class="who">${esc(p.team || "team unknown")}</div>${tags(p)}
      <div class="miss" title="${esc(p.not_top5 || "")}"><b>Why not top 5</b>${esc(p.not_top5 || `Placed #${p.rank} by consensus.`)}</div></div>`).join("");
  bindOpen(el, ".ncard");
}

/* ---------- E: "how it was built" cards + modal ---------- */
const ICON = {
  method: '<path d="M3 4h18l-7 8v6l-4 2v-8z"/>',
  recall: '<circle cx="11" cy="11" r="6"/><path d="m20 20-4.5-4.5"/>',
  coarse: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  team: '<circle cx="5" cy="6" r="2.2"/><circle cx="19" cy="6" r="2.2"/><circle cx="12" cy="18" r="2.2"/><path d="M7 7l3.6 9M17 7l-3.6 9M7.2 6h9.6"/>',
  matrix: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M3 15h18M9 3v18M15 3v18"/>',
  validation: '<path d="M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6z"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
  limits: '<circle cx="12" cy="12" r="9"/><path d="M12 7v6M12 16.5v.5"/>',
  fine: '<path d="M12 3v4M12 17v4M5 12H3M21 12h-2"/><circle cx="12" cy="12" r="5"/><path d="m10 12 1.5 1.5L14.5 10"/>',
  doc: '<path d="M6 3h9l4 4v14H6z"/><path d="M14 3v5h5M9 13h7M9 17h5"/>',
};
const icon = k => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON[k]}</svg>`;
const LIMITS_N = 5;
function howCards() {
  const f = D.funnel, v = D.validation, t = D.team, cov = D.meta.coverage;
  const triaged = (v.find(x => x.label === "PRs triaged by LLM") || {}).value, errs = (v.find(x => x.label === "Triage LLM errors") || {}).value;
  const okN = v.filter(x => x.status === "ok").length;
  return [
    ["method", "How we measure", f.stages.map(s => fmt(s.n)).join(" → "), "Cheap rules on everyone, LLM reading only where it can change the answer, then judges with cited PRs."],
    ["recall", "Recall", `${fmt(f.stages[2].n)} recalled · ${Object.keys(f.route_hits || {}).length} routes`, "Overlapping routes catch delivery, review leverage, core systems, changelog and critical work."],
    ["coarse", "Coarse ranking", `${fmt(triaged)} PRs triaged · ${fmt(errs)} errors`, "Every PR of the recalled engineers gets an importance tier; mass × quality picks the shortlist."],
    ["fine", "Fine ranking & decision", `${fmt((D.fine || {}).reports)} analyst reports · 2 independent decisions`, "Each finalist gets an agentic analyst; two blind deciders rank them in company context; close calls re-asked pairwise in both orders."],
    ["team", "Team network", `${fmt(t.summary.people)} people · ${fmt(t.communities.length)} communities`, "Who reviews, builds on and fixes whose work — with the interactive graph."],
    ["matrix", "Comparison matrix", `${fmt(D.matrix.rows.length)} × ${fmt(D.matrix.columns.length)}`, "Every shortlisted engineer on every metric, raw value next to percentile, sortable."],
    ["validation", "Data and validation", D.meta.fetch ? `${fmt(D.meta.fetch.prs)} PRs · ${D.meta.fetch.days_reconciled}/${D.meta.fetch.days} days reconciled` : `${fmt(cov.merged_prs)} PRs · ${okN}/${v.length} checks available`, "Coverage, exclusions, review-fetch caps, LLM cost and where every number comes from."],
    ["limits", "Limitations", `${LIMITS_N} caveats`, "What a 90-day, GitHub-only view cannot see."],
  ];
}
function renderExplore() {
  const ex = D.meta.explainers || {};
  const cards = [[D.meta.network_page, "network.html", "team", "Team network graph", "Who reviews, builds on and fixes whose work — full page."],
    [ex.en, "method/explainer-en.html", "doc", "How the system works", "The full method, layer by layer, with the design choices."]];
  $("#explore").innerHTML = cards.map(([ok, href, ic, t, s]) => ok
    ? `<a class="xcard" href="${href}" target="_blank" rel="noopener"><span class="ic">${icon(ic)}</span><span><b>${esc(t)}</b><span class="s">${esc(s)}</span></span></a>`
    : `<div class="xcard soon" aria-disabled="true"><span class="ic">${icon(ic)}</span><span><b>${esc(t)}</b><span class="s">${esc(s)}</span></span></div>`).join("");
}
function renderHow() {
  $("#how-grid").innerHTML = howCards().map(([k, t, n, sent]) => `<button class="hcard" data-modal="${k}" aria-haspopup="dialog">
      <span class="ic">${icon(k)}</span><span class="t">${esc(t)}</span><span class="k">${esc(n)}</span><span class="s">${esc(sent)}</span><span class="more">Open details →</span></button>`).join("");
  $("#how-grid").addEventListener("click", e => { const b = e.target.closest(".hcard"); if (b && !e.target.closest("[data-def]")) openModal(b.dataset.modal, b); });
}
const MODAL_TITLE = { fine: "Fine ranking & decision", method: "How we measure", recall: "Recall: who entered the funnel", coarse: "Coarse ranking: the 20-person shortlist", team: "Team network",
  matrix: "Comparison matrix", validation: "Data and validation", limits: "Limitations" };
const modal = $("#modal"), modalCache = {};
let modalOpener = null;
function openModal(key, opener) {
  modalOpener = opener || document.activeElement;
  $("#modal-title").textContent = MODAL_TITLE[key];
  if (!modalCache[key]) {  // render once; tables keep their sort state between openings
    const el = document.createElement("div");
    try { RENDER[key](el); } catch (err) { console.error(err); el.innerHTML = `<p class="empty">This section could not be rendered: ${esc(err.message)}</p>`; }
    modalCache[key] = el;
  }
  const body = $("#modal-body");
  body.replaceChildren(modalCache[key]);
  modal.hidden = false; body.scrollTop = 0; fitClamps(body);
  document.body.style.overflow = "hidden";
  $(".close", modal).focus();
}
function closeModal() {
  if (modal.hidden) return;
  modal.hidden = true; document.body.style.overflow = "";
  if (modalOpener) modalOpener.focus();
}
modal.addEventListener("click", e => { if (e.target.closest("[data-close]")) closeModal(); });
// keep Tab inside the open dialog (the drawer, when opened from a table row, sits above it and takes over)
document.addEventListener("keydown", e => {
  if (e.key !== "Tab" || modal.hidden || drawer.classList.contains("open")) return;
  const f = [...modal.querySelectorAll('a[href], button, select, iframe, [tabindex]:not([tabindex="-1"])')].filter(x => x.offsetParent !== null);
  if (!f.length) return;
  const first = f[0], lastEl = f[f.length - 1];
  if (!modal.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
  else if (e.shiftKey && document.activeElement === first) { e.preventDefault(); lastEl.focus(); }
  else if (!e.shiftKey && document.activeElement === lastEl) { e.preventDefault(); first.focus(); }
});

/* ---------- E: folds ---------- */
function tierStack(counts, total) {
  const n = total || TIERS.reduce((s, t) => s + (counts[t] || 0), 0);
  if (!n) return `<p class="empty small">No triaged PRs.</p>`;
  return `<div class="stack" role="img" aria-label="Tier mix">${TIERS.map(t => counts[t] ? `<span style="width:${counts[t] / n * 100}%;background:${TIER_COLOR[t]}" title="${t}: ${counts[t]} (${(counts[t] / n * 100).toFixed(1)}%)"></span>` : "").join("")}</div>`
    + `<div class="legend">${TIERS.map(t => `<span><i style="background:${TIER_COLOR[t]}"></i>${num("tier." + t, counts[t] || 0, null, `${t} ${fmt(counts[t] || 0)}`)}</span>`).join("")}</div>`;
}
const STAGE_LABEL = { people: "Human contributors", eligible: "Above activity floor", recalled: "Recalled", coarse_n: "Shortlist", final_n: "Top 5" };
function renderMethod(el) {
  const f = D.funnel, max = Math.max(...f.stages.map(s => s.n || 0)) || 1;
  const fun = f.stages.map(s => `<div class="f-row"><div>${esc(STAGE_LABEL[s.key])}</div>
    <div><span class="f-bar" style="display:inline-block;width:${Math.max(3, (s.n || 0) / max * 100)}%">${num(s.key, s.n, null)}</span>
    <div class="f-crit">${esc(def(s.key).formula)}</div></div></div>`).join("");
  const tiers = mini(["Tier", "Points", "PRs among all triaged"], TIERS.map(t => [num("tier." + t, f.tier_points[t], null, t), String(f.tier_points[t]), fmt((D.tier_distribution.all || {})[t] || 0)]));
  const angles = mini(["Angle", "Reference weight", "What the evaluator grades"], ANGLES.map(a => [ANGLE_LABEL[a], `${Math.round(f.angle_weights[a] * 100)}%`, esc(def("grade." + a).formula.split(". ")[0].replace(/^L3 evaluator grade 1–10: /, ""))]));
  const v = D.meta.coverage;
  el.innerHTML = `
    <p>Five stages narrow every human contributor down to five. Cheap rules run on everyone; expensive LLM reading runs only where it can change the answer.</p>
    <div class="funnel">${fun}</div>
    ${f.over_cap ? `<p class="note">Recall target was ${f.sizes.recall}; the union of routes gave ${fmt(f.stages[2].n)} (${f.over_cap} over target). All were kept and ranked, none dropped silently.</p>` : ""}
    <div class="grid2"><div><h4>PR tiers (LLM triage, doubling scale)</h4>${tiers}<p class="note">${esc(def("episodes").formula)}; an episode scores its best PR plus a quarter of the rest, so many small PRs on one change do not add up to a major one.</p></div>
    <div><h4>Four angles</h4>${angles}<p class="note">Grade anchors: ${esc(def("grade.overall").formula.replace(/^L3 evaluator overall grade 1–10 with confidence\. /, ""))}</p></div></div>
    <h4>Decision steps</h4>
    <div class="steps"><span class="step">Evaluator per candidate: 4 angle grades with cited PRs</span><span class="arr">→</span>
      <span class="step">2 independent rankings, names hidden</span><span class="arr">→</span><span class="step">Pairwise checks where they disagree</span><span class="arr">→</span>
      <span class="step">Devil's advocate on each of the top 5</span><span class="arr">→</span><span class="step">Gates a / b / c</span><span class="arr">→</span><span class="step">Weight robustness, ${esc((D.validation.find(x => x.key === "stability_freq") || {}).value || "1000 draws")}</span></div>
    <h4>Trade-offs we made</h4>
    <ul class="plain">
      <li>LLM triage covered ${fmt(D.validation.find(x => x.label === "PRs triaged by LLM").value)} PRs by recalled engineers, not all ${fmt(v.merged_prs)}; unrecalled authors are covered by a random audit instead.</li>
      <li>Deep reads of diffs and review threads only for the ${f.sizes.coarse}-person shortlist, sampled by tier.</li>
      <li>Bot and AI-agent PRs are excluded unless a human who drove them can be identified.</li>
      <li>The reference score R informs the evaluators but does not decide the ranking; a ranking that departs from it by more than 3 places must be explained.</li>
    </ul>
    <p class="small muted">${(D.meta.explainers || {}).en ? `Full write-up: <a href="method/explainer-en.html" target="_blank" rel="noopener">How the system works</a>.` : "A full write-up of the method is coming soon."}</p>`;
}
/** The fine stage: layered tree (inline SVG), what the analyst does, decision steps with real outcomes, the two rules. */
function renderFine(el) {
  const f = D.fine || {}, g = (D.decision || {}).agreement || {}, st = f.stability || {};
  const layers = [["L0", "Rules", "metrics, matrix, team graph"], ["L1", "PR reads", "tier per PR · deep reads"], ["L2", "Workstreams · role", "PR clusters, review position"],
    ["L3", "Analyst report", `${fmt(f.reports)} reports, one agent each`], ["L4", "Decision ×2", "two blind deciders"]];
  const W = 980, bw = 172, gap = (W - 5 * bw) / 4;
  const svg = `<svg class="tree" viewBox="0 0 ${W} 118" role="img" aria-label="Five layers from rules to decision">
    <defs><marker id="ah" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0 8 4 0 8z" fill="#8fc6ff"/></marker></defs>
    ${layers.map(([id, t, s], i) => { const x = i * (bw + gap), hot = i >= 3;
      return `<rect x="${x}" y="18" width="${bw}" height="78" rx="12" fill="${hot ? "rgba(195,168,255,.12)" : "rgba(143,198,255,.08)"}" stroke="${hot ? "rgba(195,168,255,.5)" : "rgba(143,198,255,.35)"}"/>
        <text x="${x + 14}" y="42" fill="${hot ? "#c3a8ff" : "#8fc6ff"}" font-family="JetBrains Mono, monospace" font-size="12">${id}</text>
        <text x="${x + 14}" y="64" fill="#e9eefb" font-family="Space Grotesk, sans-serif" font-size="15" font-weight="600">${esc(t)}</text>
        <text x="${x + 14}" y="84" fill="#9aa7c9" font-family="Space Grotesk, sans-serif" font-size="11.5">${esc(s)}</text>`
        + (i < 4 ? `<line x1="${x + bw + 4}" y1="57" x2="${x + bw + gap - 6}" y2="57" stroke="#8fc6ff" stroke-width="1.5" marker-end="url(#ah)"/>` : "");
    }).join("")}
    <text x="0" y="112" fill="#6b789c" font-family="JetBrains Mono, monospace" font-size="10.5">scripts and Flash calls (L0–L2) produce evidence · agents (L3–L4) judge it · each layer reads only the one below</text></svg>`;
  const kpi = (v, l) => `<div class="mchip"><b>${esc(v)}</b><span>${esc(l)}</span></div>`;
  const stab = Object.entries(st).map(([k, n]) => `${n} ${k.replace("_", " ")}`).join(" · ");
  el.innerHTML = `${svg}
    <h4>What each analyst does (L3)</h4>
    <div class="kpis">${kpi(fmt(f.reports), "analyst reports")}${kpi(fmt(f.custom_analyses), "custom analyses")}${kpi(fmt(f.query_commands), "query-tool commands cited")}${kpi(fmt(f.ondemand_deepreads), "on-demand deep reads")}</div>
    <ul class="plain">
      <li>Writes the standard sections: positioning, 2–3 core contributions with PRs, four angle grades on a fixed 1–10 scale, team position, red flags and counter-evidence.</li>
      <li>Runs at least two analyses of its own choosing (e.g. "is the near-perfect first-pass rate a quality signal or a closed review loop?") through a query tool over the person's data pack.</li>
      <li>Reads summaries, scores and review metadata only, never raw diffs; it can request up to 6 extra deep reads of unsampled PRs.</li></ul>
    <h4>How the decision was made (L4)</h4>
    <div class="kpis">${kpi(`${fmt(g.both_top5 && g.both_top5.filter(l => D.top5.some(p => p.login === l)).length)} of 5`, "final top 5 both deciders had")}${kpi(`${fmt(g.top5_overlap)}/5`, "top-5 overlap")}${kpi(`τ ${g.kendall_tau ?? "—"}`, "Kendall τ over all 20")}${kpi(`${fmt(f.pairs_consistent)}/${fmt(f.pairs)}`, "pairwise checks consistent")}</div>
    <div class="steps"><span class="step">2 blind deciders rank all 20 in company context</span><span class="arr">→</span><span class="step">Borda consensus</span><span class="arr">→</span>
      <span class="step">Pairwise re-asks on disputed ranks, both orders</span><span class="arr">→</span><span class="step">Devil's advocate on each of the top 5</span><span class="arr">→</span><span class="step">Gates a / b / c</span><span class="arr">→</span><span class="step">Weight-robustness labels</span></div>
    <ul class="plain">
      <li>The devil's advocate challenged all ${fmt(f.devil_challenged)} of the top 5 and proposed a replacement for each; ${fmt(f.devil_kept)} were kept. In pairwise re-asks of a top-5 incumbent against a challenger, the incumbent won ${fmt(f.incumbents_won)} of ${fmt(f.incumbent_pairs)} in both presentation orders${f.incumbents_won < f.incumbent_pairs ? " (each exception is explained in that person's drawer)" : ""}.</li>
      <li>Weight-robustness labels for the top 5: ${esc(stab || "—")}. A "verdict only" pick carries a written justification, shown in that person's drawer.</li></ul>
    ${auditBlock()}
    <div class="rules"><div class="rule"><b>Scores are reference, agents decide.</b> The reference score R informs the deciders and only breaks ties; a ranking that departs from it by more than 3 places must say why.</div>
      <div class="rule"><b>A replacement must win in both orders.</b> A challenger replaces an incumbent only if he wins the pairwise comparison in both presentation orders; a split verdict counts as a tie.</div></div>`;
}
function auditBlock() {
  const a = D.meta.audit;
  if (!a) return "";
  return `<h4>Audit and correction</h4><p class="note"><b>Round 1 → independent audit</b> (2 missed engineers, quality-rate bug, self-repair invisible, overstated wording) <b>→ fixed → Round 2 re-decided all ${fmt(D.matrix.rows.length)}</b>.</p>
    ${clampTxt(a.story, 2)}${list(a.changes) ? mini(["Who / what", "Round 1", "Round 2", "Why"], a.changes.map(x => [esc(x.item), esc(x.round1), esc(x.round2), esc(x.reason)])) : ""}`;
}
function renderRecall(el) {
  const f = D.funnel, routes = Object.keys(f.route_hits || {});
  el.innerHTML = `<p>${num("people", f.stages[0].n, null)} contributors → ${num("eligible", f.stages[1].n, null)} above the activity floor → ${num("recalled", f.stages[2].n, null)} recalled by at least one route. Routes overlap on purpose: each catches a different kind of impact.</p><div id="t-routes"></div>
    <h4>Missed-engineer audit</h4><p>${num("audit", f.audit.sampled, null)} PRs sampled at random from ${fmt(f.audit.population)} PRs by authors no route recalled.
    ${f.audit.result ? `<b>${fmt((f.audit.result.selected_into_top20 || []).length)}</b> engineers added by the audit reached the top 20${(f.audit.result.selected_into_top20 || []).length ? ": " + esc(f.audit.result.selected_into_top20.join(", ")) : ""}.` : `<span class="empty">Audit verdict not yet in the outputs.</span>`}</p>`;
  mountTable($("#t-routes", el), [
    { key: "route", label: "Route", render: r => num("route." + r.route, r.hits, null, r.route) },
    { key: "hits", label: "Engineers recalled", num: true },
    { key: "only", label: "Recalled by this route only", num: true },
    { key: "criterion", label: "Criterion", wrap: true, sortable: false },
  ], routes.map(r => ({ route: r, hits: f.route_hits[r], only: (f.only_route || {})[r], criterion: def("route." + r).formula })), { sort: "hits" });
}
function renderCoarse(el) {
  const td = D.tier_distribution;
  el.innerHTML = `<div class="grid2"><div><h4>All triaged PRs (${fmt(Object.values(td.all).reduce((a, b) => a + b, 0))})</h4>${tierStack(td.all)}</div>
    <div><h4>PRs of the shortlisted ${D.coarse_table.filter(r => (r.selected_by || []).length).length} (${fmt(Object.values(td.candidates).reduce((a, b) => a + b, 0))})</h4>${tierStack(td.candidates)}</div></div>
    <p class="note">Coarse score = importance mass × quality factor. Click a row to open the person.</p><div id="t-coarse"></div>`;
  const tc = (r, t) => (r.tier_counts || {})[t] || 0;
  mountTable($("#t-coarse", el), [
    { key: "login", label: "Engineer", render: r => `<b>${esc(r.login)}</b>` },
    { key: "selected_by", label: "Selected by", def: "selected_by", render: r => esc((r.selected_by || []).join(", ") || "—"), sortVal: r => (r.selected_by || []).join(",") },
    { key: "prs", label: "PRs", num: true },
    { key: "episodes", label: "Episodes", def: "episodes", num: true },
    { key: "landmark", label: "Landmark", def: "tier.landmark", num: true, render: r => fmt(tc(r, "landmark")), sortVal: r => tc(r, "landmark") },
    { key: "major", label: "Major", def: "tier.major", num: true, render: r => fmt(tc(r, "major")), sortVal: r => tc(r, "major") },
    { key: "substantive", label: "Substantive", def: "tier.substantive", num: true, render: r => fmt(tc(r, "substantive")), sortVal: r => tc(r, "substantive") },
    { key: "mass", label: "Mass", def: "mass", num: true, render: r => num("mass", r.mass, null) },
    { key: "q", label: "Quality rate", def: "q", num: true, render: r => num("q", r.q, null) },
    { key: "team_score", label: "Team score", def: "team_score", num: true, render: r => num("team_score", r.team_score, null) },
    { key: "coarse_score", label: "Coarse score", def: "coarse_score", num: true, render: r => num("coarse_score", r.coarse_score, null) },
  ], D.coarse_table, { sort: "coarse_score", onRow: openDrawer });
}
function renderTeam(el) {
  const t = D.team, s = t.summary || {}, ev = s.events || {};
  el.innerHTML = `<p>${num("graph_people", s.people, null)} people with at least one collaboration edge and ${fmt(s.window_prs)} PRs form the review graph: ${fmt(ev.approve)} approvals, ${fmt(ev.changes_requested)} change requests, ${fmt(ev.comment)} substantive comments, ${fmt(ev.followup_fix)} follow-up fixes and ${fmt(ev.revert)} reverts.</p>
    <div id="net-slot"><p class="muted small">Loading the network graph…</p></div>
    <h4>${num("g.communities", t.communities.length, null, "Review communities")}</h4><div id="t-comm"></div>
    <div class="grid2"><div><h4>${num("g.bridges", t.bridges.length, null, "Bridges between communities")}</h4><div id="t-br"></div></div>
    <div><h4>${num("g.single_points", t.single_points.length, null, "Single points of approval")}</h4><div id="t-sp"></div></div></div>`;
  mountTable($("#t-comm", el), [
    { key: "id", label: "#", num: true }, { key: "size", label: "People", num: true },
    { key: "main_team", label: "Main team" }, { key: "purity", label: "Main-team share", num: true },
    { key: "hub", label: "Hub reviewer" },
    { key: "candidates", label: "Shortlisted members", wrap: true, render: r => esc((r.candidates || []).join(", ") || "—"), sortVal: r => (r.candidates || []).length },
  ], t.communities, { sort: "size" });
  mountTable($("#t-br", el), [
    { key: "login", label: "Engineer", render: r => esc(r.login) }, { key: "betweenness", label: "Betweenness", num: true },
    { key: "communities_reached", label: "Communities reached", num: true },
  ], t.bridges, { sort: "betweenness" });
  if (t.single_points.length) {
    const cols = Object.keys(t.single_points[0]).map(k => ({ key: k, label: k.replace(/_/g, " ") }));
    mountTable($("#t-sp", el), cols, t.single_points);
  } else $("#t-sp", el).innerHTML = `<p class="empty small">None found: no area where one approver gives most of the approvals.</p>`;
  // network graph is a separate page; load it only now that the panel is open
  // meta.network_page is set at build time, so a missing page never costs a 404
  (D.meta.network_page ? Promise.resolve() : Promise.reject()).then(() => {
    $("#net-slot", el).innerHTML = `<iframe class="net" src="network.html?embed=1" title="Team collaboration network"></iframe>
      <p class="small"><a href="network.html" target="_blank" rel="noopener">Open the network full screen</a></p>`;
  }).catch(() => { $("#net-slot", el).innerHTML = `<p class="empty small">The interactive network graph is not available in this build yet.</p>`; });
}
function renderMatrix(el) {
  const cols = D.matrix.columns;
  el.innerHTML = `<p class="note">Raw value with its percentile among the ${D.matrix.rows.length} shortlisted engineers; the bar under each cell is the percentile (grey = neutral metric, neither good nor bad). “—” means unknown (missing data or a sample under 5), never zero. Click a row to open the person; hover a column header for its definition.</p><div id="t-mx"></div>`;
  mountTable($("#t-mx", el), [{ key: "login", label: "Engineer", render: r => `<b>${esc(r.login)}</b>` }].concat(cols.map(k => ({
    key: k, label: def("m." + k).label, def: "m." + k, num: true, sortVal: r => r.values[k],
    render: r => `${num("m." + k, r.values[k], r.pct[k])}<span class="pct">${pctTxt(r.pct[k])}</span>${covNote("m." + k, r.login, true)}${r.pct[k] != null ? `<span class="heat ${def("m." + k).direction === "neutral" ? "neutral" : ""}" style="width:${Math.max(2, r.pct[k])}%"></span>` : ""}`,
  }))), D.matrix.rows, { sort: cols[0], onRow: openDrawer });
}
function renderValidation(el) {
  const st = { ok: '<span class="badge ok">available</span>', placeholder: '<span class="badge warn">placeholder</span>', missing: '<span class="badge">not yet produced</span>', mismatch: '<span class="badge risk">mismatch</span>' };
  el.innerHTML = `<div id="t-val"></div><h4>Data sources used for this build</h4>`
    + mini(["Artifact", "File"], Object.entries(D.meta.sources).map(([k, v]) => [`<span class="mono">${esc(k)}</span>`, `<span class="mono">${esc(v)}</span>`]));
  mountTable($("#t-val", el), [
    { key: "label", label: "Check", wrap: true },
    { key: "value", label: "Result", render: r => r.key ? num(r.key, r.value, null) : esc(fmt(r.value)), sortVal: r => String(r.value) },
    { key: "status", label: "Status", render: r => st[r.status] || esc(r.status) },
  ], D.validation);
}
function renderLimits(el) {
  el.innerHTML = `<ul class="plain">
    <li><b>90-day window.</b> Long-running work that landed before ${esc(D.meta.window.start)} is invisible, and work merged in the last two weeks has had little time to be reverted or fixed, so quality signals use only PRs at least 14 days old.</li>
    <li><b>Feature-branch PRs.</b> Work merged into feature branches and then squashed into master loses part of its lineage; “built on by” undercounts for those authors.</li>
    <li><b>PostHog rarely uses “request changes”.</b> Only ${fmt((D.team.summary.events || {}).changes_requested)} change requests against ${fmt((D.team.summary.events || {}).approve)} approvals, so review quality leans on comments and follow-up fixes instead.</li>
    <li><b>LLM judgement is uncertain.</b> Tiers and grades come from models; every grade cites PRs that can be opened, quotes are checked against the source text, and two independent rankings must agree for a stable verdict.</li>
    <li><b>GitHub only.</b> Incidents handled, design docs, mentoring and customer calls leave no trace here.</li></ul>`;
}
const RENDER = { fine: renderFine, method: renderMethod, recall: renderRecall, coarse: renderCoarse, team: renderTeam, matrix: renderMatrix, validation: renderValidation, limits: renderLimits };

function init(data) {
  D = data;
  renderHead();
  renderCards();
  // #candidate=<login> deep link (used by the network graph)
  const fromHash = () => { const m = location.hash.match(/^#candidate=(.+)$/); if (m) openDrawer(decodeURIComponent(m[1])); };
  window.addEventListener("hashchange", fromHash);
  renderNext($("#next-grid"));
  renderExplore();
  renderHow();
  fromHash();
}
function fail(msg) { $("#cards").innerHTML = `<p class="empty">${esc(msg)}</p>`; }

function loadScript() {
  // file:// cannot fetch; site_data.js carries the same JSON
  const s = document.createElement("script");
  s.src = "site_data.js";
  s.onload = () => (window.SITE_DATA ? init(window.SITE_DATA) : fail("site_data.js did not define the data."));
  s.onerror = () => fail("Could not load site_data.json. Build it with: python -m impact.site_data out_full site");
  document.head.appendChild(s);
}
if (location.protocol === "file:") loadScript();
else fetch("site_data.json").then(r => { if (!r.ok) throw new Error(r.status); return r.json(); }).then(init).catch(loadScript);
