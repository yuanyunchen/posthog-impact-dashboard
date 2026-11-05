"""Evidence dossier per candidate: raw metrics, tiers, PR list, deep reads, reviews given, peer behaviour.
Never contains the reference score R (review-codex R2: evaluators see only raw evidence)."""
from collections import Counter

from impact import config as C, paths
from impact.episodes import group_episodes

NO_R = {"R", "refscore", "angles"}
TIER_ORDER = ["landmark", "major", "substantive", "routine", "trivial", "mechanical"]


def reviews_given(login: str, own: set[int], review_detail: dict | None) -> list[dict] | None:
    """Substantive review bodies and thread comments on other people's PRs; led_to_change = thread later outdated."""
    if review_detail is None:
        return None
    items = []
    for num, rd in review_detail.items():
        if num in own:
            continue
        items += [{"number": num, "kind": f"review {r.get('state') or ''}".strip(), "body": r["body"], "led_to_change": None}
                  for r in rd.get("reviews") or [] if r.get("author") == login and len(r.get("body") or "") >= C.DOSSIER_REVIEW_MIN_CHARS]
        items += [{"number": num, "kind": f"comment on {t.get('path') or 'a file'}", "body": c["body"], "led_to_change": bool(t.get("is_outdated"))}
                  for t in rd.get("threads") or [] for c in t.get("comments") or []
                  if c.get("author") == login and len(c.get("body") or "") >= C.DOSSIER_REVIEW_MIN_CHARS]
    return sorted(items, key=lambda x: (x["led_to_change"] is True, len(x["body"])), reverse=True)[:C.DOSSIER_REVIEW_SAMPLES]


def downstream_authors(own: set[int], lineage: dict | None) -> int | None:
    """Distinct other human authors who later changed a source file he touched by ≥ DOWNSTREAM_MIN_LINES (by commit
    email). Non-source noise classes and hub files (≥ HUB_FILE_AUTHORS authors in the window) are shared, not built on."""
    if lineage is None:
        return None
    human = lambda e: "[bot]" not in e["author_email"]
    mine = {e["author_email"] for es in lineage.values() for e in es if e.get("number") in own}
    others = set()
    for path, es in lineage.items():
        if paths.noise(path)[0] != "source":
            continue
        if len({e["author_email"] for e in es if human(e) and C.WINDOW_START <= e["merged_at"] <= C.WINDOW_END}) >= C.HUB_FILE_AUTHORS:
            continue
        touched = [e["merged_at"] for e in es if e.get("number") in own and e["added"] + e["deleted"] >= C.DOWNSTREAM_MIN_LINES]
        if touched:
            first = min(touched)
            others |= {e["author_email"] for e in es if e["merged_at"] > first and e.get("number") not in own
                       and e["author_email"] not in mine and human(e)}
    return len(others)


def requested_by(login: str, review_detail: dict | None) -> int | None:
    if review_detail is None:
        return None
    return len({q["requester"] for rd in review_detail.values() for q in rd.get("review_requests") or []
                if q.get("reviewer") == login and q.get("requester") not in (None, login)})


def build_dossier(login, metrics, triage, deepread, estimate, review_detail, lineage, changelog, team_map,
                  prs: list[dict] | None = None, workstreams: list[dict] | None = None,
                  role_profile: dict | None = None) -> tuple[dict, str]:
    """L3 input (spec §10). prs (his window PRs) adds titles and the episode count; workstreams (L2) and
    role_profile (L2') come from the workstream track and lead the markdown."""
    metrics = {k: v for k, v in (metrics or {}).items() if k not in NO_R}
    failed = [t["number"] for t in triage if t.get("tier") not in TIER_ORDER]  # triage llm_error
    triage = [t for t in triage if t.get("tier") in TIER_ORDER]
    by_pr = {p["number"]: p for p in prs or []}
    own = {t["number"] for t in triage} | set(by_pr)
    reads = {d["number"]: d for d in deepread}
    ws_of = {_num(n): w["id"] for w in workstreams or [] for n in w.get("prs") or []}
    tier_counts = Counter(t["tier"] for t in triage)
    pr_list = [{"number": t["number"], "url": f"https://github.com/{C.REPO}/pull/{t['number']}",
                "title": by_pr.get(t["number"], {}).get("title"), "tier": t["tier"], "work_type": t.get("work_type"),
                "summary": t.get("summary"), "workstream": ws_of.get(t["number"]),
                "merged_at": by_pr.get(t["number"], {}).get("merged_at"),
                "P": reads[t["number"]]["P"] if t["number"] in reads and not reads[t["number"]].get("llm_error") else None}
               for t in sorted(triage, key=lambda t: (TIER_ORDER.index(t["tier"]), t["number"]))]
    reviews = reviews_given(login, own, review_detail)
    cl = [{"number": n, **e} for n in sorted(own) for e in (changelog or {}).get(str(n), [])]  # {number: [entry]}
    ok_reads = [r for r in deepread if not r.get("llm_error")]
    checks = [v for r in ok_reads for v in r["verified"].values()]
    d = {
        "login": login, "team": (team_map or {}).get(login),
        "workstreams": workstreams, "role_profile": role_profile,
        "metrics": metrics,
        "coverage": {"metrics": round(sum(v is not None for v in metrics.values()) / len(metrics), 2) if metrics else 0.0,
                     "deepread_n": len(ok_reads), "deepread_errors": len(deepread) - len(ok_reads),
                     "diff_truncated_share": round(sum(bool(r.get("diff_truncated")) for r in ok_reads) / len(ok_reads), 2) if ok_reads else None,
                     "diff_missing": sum(bool(r.get("diff_missing")) for r in ok_reads),
                     "quote_fail_share": round(1 - sum(checks) / len(checks), 2) if checks else None,
                     "review_detail_prs": None if review_detail is None else len(review_detail),
                     "triage_failed": len(failed), "missing": [k for k, v in metrics.items() if v is None]},
        "tier_counts": {k: tier_counts.get(k, 0) for k in TIER_ORDER}, "triage_failed": failed,
        "episodes": len(group_episodes(prs)) if prs else None,
        "prs": pr_list,
        "deepread": [{k: r.get(k) for k in ("number", "V", "C", "N", "L", "Q", "ell", "P", "verified", "evidence",
                                             "summary", "diff_source", "diff_truncated", "llm_error")} for r in deepread],
        "estimate": {k: v for k, v in estimate.items() if k != "points"},
        "reviews_given": reviews,
        "reviews_given_note": "review_detail missing" if reviews is None else f"review_detail covers {len(review_detail)} PRs",
        "peer": {"reverted": metrics.get("reverted"), "followup_fixed": metrics.get("followup_fixed"),
                 "downstream_authors": downstream_authors(own, lineage),
                 "requested_by": requested_by(login, review_detail) if review_detail is not None
                 else metrics.get("review_requested_by")},
        "changelog": cl if changelog is not None else None,
    }
    return d, to_markdown(d)


def _v(x) -> str:
    """Plain text for any JSON value: never 'None', never a raw dict or list literal."""
    if x is None:
        return "unknown"
    if isinstance(x, float):
        return f"{x:.2f}".rstrip("0").rstrip(".")
    if isinstance(x, dict):
        return " ".join(_v(v) if k == "login" else f"{k} {_v(v)}" for k, v in x.items())
    if isinstance(x, (list, tuple)):
        return ", ".join(_v(i) for i in x) or "none"
    return str(x)


def _pairs(prefix: str, obj: dict):
    for k, v in obj.items():
        yield from _pairs(f"{prefix}{k}.", v) if isinstance(v, dict) and v else [(f"{prefix}{k}", v)]


def _kv(prefix: str, obj: dict) -> str:
    """Every number carries its key so higher layers can cite it as an evidence id (spec §10 rule 1)."""
    return " · ".join(f"`{k}`={_v(v)}" for k, v in _pairs(prefix, obj))


def _prline(p: dict, read: dict | None) -> str:
    scores = (f" `P`={read['P']:.1f} (V{read['V']} C{read['C']} N{read['N']} L{read['L']} Q{read['Q']})"
              if read and not read.get("llm_error") else "")
    return f"- #{p['number']} {_v(p.get('tier'))}{scores}: {_flat(p.get('summary') or p.get('title'))}"


def _num(pr) -> int:
    return pr["number"] if isinstance(pr, dict) else pr  # workstreams list PRs as {number, tier, P, summary}


def _collab(cs) -> str:
    return ", ".join(f"{c['login']} ({c.get('prs_reviewed')})" if isinstance(c, dict) else str(c) for c in cs or []) or "none"


def _capped(ps: list[dict], reads: dict, login: str, query: str, where: str) -> list[str]:
    """At most DOSSIER_PRS_PER_WS lines: deep-read PRs first, then highest tier, newest first within a tier."""
    ok = lambda p: p["number"] in reads and not reads[p["number"]].get("llm_error")
    tier = lambda p: TIER_ORDER.index(p["tier"]) if p.get("tier") in TIER_ORDER else len(TIER_ORDER)
    ps = sorted(ps, key=lambda p: p.get("merged_at") or "", reverse=True)  # newest first, kept by the stable sort below
    ps = sorted(ps, key=lambda p: (not ok(p), tier(p)))
    L = [_prline(p, reads.get(p["number"])) for p in ps[:C.DOSSIER_PRS_PER_WS]]
    if len(ps) > C.DOSSIER_PRS_PER_WS:
        L.append(f"- … {len(ps) - C.DOSSIER_PRS_PER_WS} more PRs {where}: `python -m impact.fine.query {login} {query}`")
    return L


def _flat(s) -> str:
    return " ".join(str(s or "").split())


def to_markdown(d: dict) -> str:
    L = [f"# Evidence dossier: {d['login']}", "", f"Team: {_v(d['team'])}", "", "## 工作流", ""]
    if d["workstreams"] is None:
        L += ["(workstreams not provided)", ""]
    reads, by_num = {r["number"]: r for r in d["deepread"]}, {p["number"]: p for p in d["prs"]}
    for w in d["workstreams"] or []:
        L += [f"### {w['id']} {_flat(w.get('title'))}", f"area: {_v(w.get('area'))}"
              + (f" (merged: {_v(w['merged_areas'])})" if w.get("merged_areas") else ""),
              _kv(f"ws.{w['id']}.agg.", w.get("agg") or {}),
              f"top PRs: {' '.join(f'#{n}' for n in w.get('top_prs') or []) or 'none'} · collaborators: {_collab(w.get('collaborators'))}"]
        ps = [by_num.get(_num(x)) or (x if isinstance(x, dict) else {"number": x}) for x in w.get("prs") or []]
        L += _capped(ps, reads, d["login"], f"prs --ws {w['id']}", "in this workstream") + [""]
    L += ["## 团队角色", ""]
    rp = d["role_profile"]
    L += [f"- `{k}`: {_v(v)}" for k, v in _pairs("role.", {k: v for k, v in rp.items() if k != "login"})] if rp else ["(role profile not provided)"]
    c = d["coverage"]
    L += ["", "## Coverage", "", _kv("coverage.", {k: v for k, v in c.items() if k != "missing"}),
          f"missing metrics: {', '.join(c['missing']) or 'none'}", "",
          "## Quantitative metrics (L0)", "", _kv("metrics.", {k: v for k, v in d["metrics"].items() if k != "team"}), "",
          f"## Tiers and stratified estimate (`episodes`={_v(d['episodes'])})", "", _kv("tier_counts.", d["tier_counts"]), ""]
    e = d["estimate"]
    L.append(_kv("estimate.", {k: e.get(k) for k in ("delivery_hat", "delivery_stratified", "L", "Q", "mechanical", "llm_errors") if k in e}))
    L += [f"- {_kv(f'estimate.strata.{s}.', r)}" for s, r in e.get("strata", {}).items()]
    flags = [f"`peer.{k}`={d['peer'][k]}" for k in ("reverted", "followup_fixed") if d["peer"][k]]
    flags += [f"#{r['number']} quote not found for {', '.join(k for k, ok in r['verified'].items() if not ok)}"
              for r in d["deepread"] if not r["llm_error"] and not all(r["verified"].values())]
    flags += [f"#{r['number']} deep read failed" for r in d["deepread"] if r["llm_error"]]
    L += ["", "## Red flags", ""] + ([f"- {f}" for f in flags] or ["none"])
    top = sorted((r for r in d["deepread"] if not r["llm_error"]), key=lambda r: -r["P"])[:3]
    L += ["", "## L1 samples (top 3 deep reads by P)", ""]
    for r in top:
        L.append(f"- #{r['number']} `P`={r['P']:.1f} V{r['V']} C{r['C']} N{r['N']} L{r['L']} Q{r['Q']}: {_flat(r['summary'])}")
        L += [f"  - {k}{'' if r['verified'][k] else ' (NOT found, -1)'}: \"{_flat(r['evidence'][k])[:160]}\"" for k in "VCNLQ"]
    rest = [p for p in d["prs"] if d["workstreams"] is None or p["workstream"] is None]
    L += ["", "## PRs (one line each: tier, P if deep-read, summary)"
          + (" not in any workstream (the rest are listed under 工作流)" if d["workstreams"] is not None else ""), ""]
    L += _capped(rest, reads, d["login"], "prs", "(the query lists all his PRs)") or ["none"]
    L += ["", f"## Reviews given to others ({d['reviews_given_note']})", ""]
    if d["reviews_given"] is None:
        L.append("review text not available.")
    else:
        L += [f"- #{x['number']} {_v(x['kind'])}{' (line changed afterwards)' if x['led_to_change'] else ''}: "
              f"{_flat(x['body'])[:400]}" for x in d["reviews_given"]] or ["(none found)"]
    L += ["", "## Peer behaviour", "", _kv("peer.", d["peer"]),
          f"(downstream_authors: other human authors who later changed a file he touched by ≥{C.DOWNSTREAM_MIN_LINES} lines; "
          f"requested_by: {d['reviews_given_note']})", "", "## Changelog entries", ""]
    if d["changelog"] is None:
        L.append("changelog data missing.")
    else:
        entries = {}  # one line per changelog entry; a release note often cites many of his PRs
        for c in d["changelog"]:
            entries.setdefault((_v(c.get("title")), _v(c.get("date"))), []).append(c["number"])
        L += [f"- {t} ({dt}): {' '.join(f'#{n}' for n in ns)}" for (t, dt), ns in entries.items()] or ["(none)"]
    return "\n".join(L) + "\n"
