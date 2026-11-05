"""Per-candidate data pack for the L3 agentic analyst (spec §12): L1 summaries and scores only, never PR bodies or diffs."""
import json
from pathlib import Path

from impact import config as C
from impact.fine import workstreams as W
from impact.fine.roles import _credited, _human, network_entry

SCORES = ("V", "C", "N", "L", "Q", "ell", "P", "verified", "diff_source", "diff_truncated")

README = """# Data pack: {login}

Built from `{prs_path}`. Summaries and scores only: no PR bodies, no diffs.

| file | content |
|---|---|
| dossier.md | evidence dossier (L0 metrics, tiers, estimate, red flags, L1 samples, reviews given, peer behaviour); every number carries its key |
| workstreams.json | L2 workstreams: PR clusters with aggregates, top PRs, collaborators |
| network.json | his entry of out/team_graph.json ({{}} when the graph is absent) |
| prs.jsonl | every window PR of his: number, title, merged_at, area, workstream, tier, P (null unless deep-read), summary, deepread scores |
| reviews.json | reviews he gave on others' PRs and received on his (person, state, team, time; no text) |
| ondemand.jsonl | on-demand deep reads made through the query tool (cap {cap}) |

Query (`python -m impact.fine.query {login} <cmd>`, output ≤ {lines} lines):
- `prs [--ws ID] [--area A] [--tier T] [--since YYYY-MM-DD] [--until YYYY-MM-DD]` filter his PRs (dossier.md shows at most {per_ws} per workstream)
- `pr <n>` L1 detail of one PR
- `reviews-given [--top N]` / `reviews-received [--top N]` counts by person, state, team
- `timeline` weekly PR counts and points
- `rank <metric_key>` his percentile among the candidates (out/matrix.json), else among recall
- `compare <other_login>` key metrics side by side
- `deepread <n>` on-demand Flash deep read of an unsampled PR: summary + scores only, {cap} per candidate,
  not part of the stratified estimate
"""


def pr_record(pr: dict, tri: dict | None, read: dict | None, ws: str | None = None) -> dict:
    ok = read is not None and not read.get("llm_error")
    return {"number": pr["number"], "title": pr["title"], "merged_at": pr["merged_at"], "area": W._area([pr]), "workstream": ws,
            "tier": (tri or {}).get("tier"), "work_type": (tri or {}).get("work_type"),
            "lines": (pr.get("additions") or 0) + (pr.get("deletions") or 0),
            "P": round(read["P"], 2) if ok else None,
            "summary": (read.get("summary") if ok else None) or (tri or {}).get("summary"),
            "deepread": ({k: read.get(k) for k in SCORES} | {"source": "sample"}) if ok else None}


def reviews(login: str, prs: list[dict], team_map: dict | None) -> dict:
    """Human reviews only; PRs credited to nobody (bots, unattributed AI PRs) and self-reviews are left out."""
    team = lambda l: (team_map or {}).get(l)
    given, received = [], []
    for p in prs:
        if not p.get("in_window", True) or not (owner := _credited(p)):
            continue
        for r in p.get("reviews") or []:
            who = r.get("author")
            if not _human(who, r.get("is_bot")) or who == owner:
                continue
            row = {"number": p["number"], "state": r.get("state"), "submitted_at": r.get("submitted_at")}
            if who == login:
                given.append(row | {"author": owner, "team": team(owner)})
            elif owner == login:
                received.append(row | {"reviewer": who, "team": team(who)})
    return {"given": given, "received": received}


def build_pack(login: str, prs: list[dict], triage: list[dict], deepread: list[dict], dossier_md: str,
               team_map: dict | None = None, team_graph: dict | None = None, workstreams: list[dict] | None = None,
               prs_path: Path = C.PRS, out: Path = C.OUT) -> Path:
    """prs = ALL window PRs (reviews given need others' PRs). workstreams default: impact.fine.workstreams.cluster."""
    d = out / "candidates" / login
    d.mkdir(parents=True, exist_ok=True)
    mine = [p for p in prs if p.get("in_window", True) and p.get("credited_to") == login]
    tri = {t["number"]: t for t in triage}
    reads = {r["number"]: r for r in deepread}
    if workstreams is None:
        workstreams = W.cluster(mine, triage, [r for r in deepread if not r.get("llm_error")])
    ws_of = {(x["number"] if isinstance(x, dict) else x): w["id"] for w in workstreams for x in w.get("prs") or []}
    files = {
        "dossier.md": dossier_md,
        "workstreams.json": json.dumps(workstreams, indent=1, ensure_ascii=False),
        "network.json": json.dumps(network_entry(login, team_graph) or {}, indent=1),
        "prs.jsonl": "".join(json.dumps(pr_record(p, tri.get(p["number"]), reads.get(p["number"]), ws_of.get(p["number"])),
                                        ensure_ascii=False) + "\n"
                             for p in sorted(mine, key=lambda p: p["merged_at"])),
        "reviews.json": json.dumps(reviews(login, prs, team_map), indent=1),
        "meta.json": json.dumps({"login": login, "prs_path": str(prs_path), "ondemand_cap": C.ONDEMAND_DEEPREAD_CAP}),
        "README.md": README.format(login=login, prs_path=prs_path, cap=C.ONDEMAND_DEEPREAD_CAP, lines=C.QUERY_MAX_LINES,
                                    per_ws=C.DOSSIER_PRS_PER_WS),
    }
    for name, text in files.items():
        (d / name).write_text(text)
    (d / "ondemand.jsonl").touch()  # kept across rebuilds: the cap counts every on-demand read ever made
    return d
