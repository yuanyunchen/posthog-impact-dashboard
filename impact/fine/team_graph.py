"""Team event graph (spec §11.1): collaboration events between people → each person's position, trust and the team's shape.

Events are {type, src, dst, pr, at}; bots never appear. Metrics are {"value", "n"}: n is the sample, value is None when
n < METRIC_MIN_N, and n is None when the data source does not cover the event type (unknown, not 0).
CLI: python -m impact.fine.team_graph [prs_path] → out/team_graph.json"""
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import networkx as nx

from impact import config as C, paths
from impact.recall.features import quality_events

REVIEW = {"APPROVED": "approve", "CHANGES_REQUESTED": "changes_requested", "COMMENTED": "comment"}
REVIEW_TYPES = set(REVIEW.values())

DEFINITIONS = {
    "approve": "event reviewer → author: a human review with state APPROVED",
    "changes_requested": "event reviewer → author: state CHANGES_REQUESTED",
    "comment": "event reviewer → author: state COMMENTED with a non-empty body",
    "review_request": "event requester → requested reviewer (ReviewRequestedEvent; only PRs in review_detail are covered)",
    "revert": "event reverter → original author: revert PR that explicitly references the original (impact.recall.features)",
    "followup_fix": "event fixer → original author: fix PR that explicitly references the original within FOLLOWUP_DAYS",
    "continue": f"event later author → earlier author: a window PR changes a source file the earlier author changed by "
                f"≥{C.DOWNSTREAM_MIN_LINES} lines earlier in the window; files with ≥{C.HUB_FILE_AUTHORS} window authors excluded",
    "first_pass_rate": "his PRs with ≥1 approval: share with no change request before the first approval",
    "changes_requested_rate": "his human-reviewed PRs: share that got ≥1 change request",
    "changes_rounds_mean": "his PRs that got a change request: mean number of change-request reviews",
    "changes_adopted_rate": "(reviewer, PR) pairs where he requested changes: share where he later approved and the PR has ≥2 "
                            "commits (proxy for the author pushing a fix)",
    "approved_authors_n": "distinct authors he approved; n = PRs he approved",
    "teams_covered_n": "distinct teams (data/team_map.json) of the authors he approved; n = PRs he approved",
    "requested_by_n": "distinct people who requested his review; n = covered PRs he authored or reviewed",
    "built_on_by_n": "distinct authors who continued development on his code (continue events); n = his window PRs",
    "fixes_given / fixes_received": "follow-up fixes he made to others' PRs / others made to his; n = his window PRs",
    "reverts_given / reverts_received": "reverts he made of others' PRs / others made of his; n = his window PRs",
    "trust_rank": "weighted PageRank on the approval graph (reviewer → author, weight = approvals): an approval from someone "
                  "who is himself approved by trusted people carries more",
    "importance_flow": f"each window PR's points (deep-read P, else triage tier points) flow {C.FLOW_AUTHOR_W} to its author and "
                       f"{C.FLOW_REVIEWER_W} to each substantive reviewer (changes requested or a written review)",
    "communities": f"Louvain (seed {C.SEED}) on the undirected review graph (approve + changes_requested + comment); "
                   "purity = share of team-known members in the community's most common team; hub = most reviews inside",
    "bridges": f"top {C.BRIDGES_TOP} by betweenness on the review graph",
    "single_points": f"product area (main area of the PR by weighted lines) where one person gives ≥{C.SINGLE_POINT_SHARE:.0%} "
                     f"of ≥{C.SINGLE_POINT_MIN} approvals",
}


def _human(login: str | None) -> bool:
    return bool(login) and not C.is_bot(login) and login not in C.GRAPH_EXTRA_BOTS


def _owner(p: dict) -> str | None:
    """Human the PR counts for; bot PRs and unattributed AI-agent PRs (credited_to None) belong to nobody (R9)."""
    return p["credited_to"] if _human(p["credited_to"]) else None


def build_events(prs: list[dict], review_detail: dict | None = None, lineage: dict | None = None,
                 followups: tuple[dict, dict] | None = None) -> list[dict]:
    """Events of in-window PRs. prs may include the buffer (needed to resolve reverts/fixes); followups is a precomputed
    impact.recall.features.quality_events(prs). review_detail = {number: record}; lineage = data/lineage.json."""
    win = {p["number"]: p for p in prs if p["in_window"]}
    by_num = {p["number"]: p for p in prs}
    ev, seen = [], set()

    def add(t, src, dst, n, at):
        if _human(src) and _human(dst) and src != dst and (t != "continue" or (src, dst, n) not in seen):
            seen.add((src, dst, n))
            ev.append({"type": t, "src": src, "dst": dst, "pr": n, "at": at})

    for n, p in win.items():
        a = _owner(p)
        for r in p["reviews"]:
            t = REVIEW.get(r["state"])
            if t and not r["is_bot"] and (t != "comment" or r["body_len"] > 0):
                add(t, r["author"], a, n, r["submitted_at"])
        reqs = (review_detail or {}).get(n, {}).get("review_requests")
        for q in (p.get("review_requests") or []) if reqs is None else reqs:
            if isinstance(q, str):
                add("review_request", a, q, n, None)
            else:
                add("review_request", q.get("requester"), q.get("reviewer"), n, q.get("created_at"))

    reverted, fixed = followups or quality_events(prs)
    for t, hit in (("revert", reverted), ("followup_fix", fixed)):
        for orig, actors in hit.items():
            for y in sorted(actors):
                if y in win:
                    add(t, _owner(by_num[y]), _owner(by_num[orig]), y, by_num[y]["merged_at"])

    for path, es in (lineage or {}).items():
        if paths.noise(path)[0] != "source":
            continue
        es = sorted(((e, _owner(win[e["number"]])) for e in es if e.get("number") in win), key=lambda x: x[0]["merged_at"])
        if len({w for _, w in es if w}) >= C.HUB_FILE_AUTHORS:
            continue
        first = {}  # author → first substantial touch of this file
        for e, w in es:
            for a, t in first.items():
                if t < e["merged_at"]:
                    add("continue", w, a, e["number"], e["merged_at"])
            if w and e["added"] + e["deleted"] >= C.DOWNSTREAM_MIN_LINES:
                first.setdefault(w, e["merged_at"])
    return sorted(ev, key=lambda e: (e["at"] or "", e["pr"], e["type"], e["src"], e["dst"]))


def coverage(prs: list[dict], review_detail: dict | None = None, lineage: dict | None = None) -> dict[str, set]:
    """Window PRs whose data covers each partial event type; review/revert/fix events come with every PR."""
    win = {p["number"] for p in prs if p["in_window"]}
    req = {p["number"] for p in prs if p["in_window"] and p.get("review_requests") is not None} | (set(review_detail or {}) & win)
    return {"review_request": req, "continue": win if lineage is not None else set()}


def _m(value, n):
    return {"value": value if n is not None and n >= C.METRIC_MIN_N else None, "n": n}


def person_metrics(events: list[dict], prs: list[dict], team_map: dict | None = None,
                   coverage: dict[str, set] | None = None) -> dict[str, dict]:
    cov = coverage or {}
    by_pr = defaultdict(list)
    for e in events:
        by_pr[e["pr"]].append(e)
    authored = defaultdict(list)
    for p in prs:
        if p["in_window"] and (a := _owner(p)):
            authored[a].append(p)
    given, got, by_src, to = defaultdict(Counter), defaultdict(Counter), defaultdict(list), defaultdict(lambda: defaultdict(set))
    for e in events:
        given[e["src"]][e["type"]] += 1
        got[e["dst"]][e["type"]] += 1
        by_src[e["src"]].append(e)
        to[e["dst"]][e["type"]].add(e["src"])
    commits = {p["number"]: p.get("commits") or 0 for p in prs}

    out = {}
    for login in sorted(set(authored) | set(given) | set(got)):
        mine = authored[login]
        approved = reviewed = first_pass = 0
        cr_counts = []
        for p in mine:
            rv = sorted((e for e in by_pr[p["number"]] if e["dst"] == login and e["type"] in ("approve", "changes_requested")),
                        key=lambda e: e["at"])
            if not rv:
                continue
            reviewed += 1
            crs = [e for e in rv if e["type"] == "changes_requested"]
            if crs:
                cr_counts.append(len(crs))
            first_ok = next((e for e in rv if e["type"] == "approve"), None)
            if first_ok:
                approved += 1
                first_pass += not any(e["at"] < first_ok["at"] for e in crs)

        mine_ev = by_src[login]
        cr_pairs = {(e["pr"], e["at"]) for e in mine_ev if e["type"] == "changes_requested"}
        cr_first = {}
        for n, at in cr_pairs:
            cr_first[n] = min(at, cr_first.get(n, at))
        adopted = sum(any(e["src"] == login and e["type"] == "approve" and e["at"] > at for e in by_pr[n]) and commits[n] >= 2
                      for n, at in cr_first.items())
        appr = {(e["pr"], e["dst"]) for e in mine_ev if e["type"] == "approve"}
        appr_prs = len({n for n, _ in appr})
        authors = {d for _, d in appr}
        teams = None if team_map is None else {t for d in authors for t in team_map.get(d) or []}

        involved = {p["number"] for p in mine} | {e["pr"] for e in mine_ev if e["type"] in REVIEW_TYPES}
        req_n = len(involved & cov["review_request"]) if cov.get("review_request") else None
        requesters = to[login]["review_request"]
        cont_n = len(mine) if cov.get("continue") else None
        builders = to[login]["continue"]
        n = len(mine)
        out[login] = {
            "prs": n, "team": None if team_map is None else team_map.get(login),
            "first_pass_rate": _m(round(first_pass / approved, 3) if approved else None, approved),
            "changes_requested_rate": _m(round(len(cr_counts) / reviewed, 3) if reviewed else None, reviewed),
            "changes_rounds_mean": _m(round(sum(cr_counts) / len(cr_counts), 2) if cr_counts else None, len(cr_counts)),
            "changes_adopted_rate": _m(round(adopted / len(cr_first), 3) if cr_first else None, len(cr_first)),
            "approved_authors_n": _m(len(authors), appr_prs),
            "teams_covered_n": _m(None if teams is None else len(teams), None if teams is None else appr_prs),
            "requested_by_n": _m(len(requesters) if req_n is not None else None, req_n),
            "built_on_by_n": _m(len(builders) if cont_n is not None else None, cont_n),
            "fixes_given": _m(given[login]["followup_fix"], n), "fixes_received": _m(got[login]["followup_fix"], n),
            "reverts_given": _m(given[login]["revert"], n), "reverts_received": _m(got[login]["revert"], n),
            "events_given": dict(given[login]), "events_received": dict(got[login]),
        }
    return out


def trust_rank(events: list[dict]) -> dict[str, float]:
    g = nx.DiGraph()
    for e in events:
        if e["type"] == "approve":
            w = g.get_edge_data(e["src"], e["dst"], {"weight": 0})["weight"]
            g.add_edge(e["src"], e["dst"], weight=w + 1)
    pr = nx.pagerank(g, weight="weight") if g.number_of_nodes() else {}
    return {k: round(v, 6) for k, v in sorted(pr.items(), key=lambda kv: (-kv[1], kv[0]))}


def importance_flow(prs: list[dict], points: dict[int, float], events: list[dict]) -> dict[str, dict]:
    """One hop on the person–PR bipartite graph, seeded with PR points. shortcut: no iteration back through people,
    upgrade to personalized PageRank if multi-hop credit is wanted."""
    subst = defaultdict(set)
    for e in events:
        if e["type"] in ("changes_requested", "comment"):
            subst[e["pr"]].add(e["src"])
    flow = defaultdict(lambda: {"total": 0.0, "author": 0.0, "reviewer": 0.0})
    for p in prs:
        if not p["in_window"] or (pt := points.get(p["number"])) is None:
            continue
        for who, role, w in [(_owner(p), "author", C.FLOW_AUTHOR_W)] + [(r, "reviewer", C.FLOW_REVIEWER_W) for r in subst[p["number"]]]:
            if who:
                flow[who][role] += w * pt
                flow[who]["total"] += w * pt
    return {k: {r: round(v, 2) for r, v in f.items()} for k, f in sorted(flow.items(), key=lambda kv: (-kv[1]["total"], kv[0]))}


def pr_area(pr: dict) -> str | None:
    w = Counter()
    for f in pr["files"]:
        w[paths.area(f["path"])[0]] += paths.weight(f["path"]) * (f["additions"] + f["deletions"])
    a, v = w.most_common(1)[0] if w else (None, 0)
    return a if v > 0 else None


def team_structure(events: list[dict], team_map: dict | None, pr_areas: dict[int, str | None] | None = None) -> dict:
    tm = team_map or {}
    rev = [e for e in events if e["type"] in REVIEW_TYPES]
    g = nx.Graph()
    for e in rev:
        w = g.get_edge_data(e["src"], e["dst"], {"weight": 0})["weight"]
        g.add_edge(e["src"], e["dst"], weight=w + 1)
    comms = sorted(nx.community.louvain_communities(g, weight="weight", seed=C.SEED), key=lambda c: (-len(c), min(c))) if g else []
    of = {m: i for i, c in enumerate(comms) for m in c}
    inside = Counter(e["src"] for e in rev if of[e["src"]] == of[e["dst"]])
    communities = []
    for i, c in enumerate(comms):
        known = [m for m in c if tm.get(m)]
        teams = Counter(t for m in known for t in tm[m])
        main, k = teams.most_common(1)[0] if teams else (None, 0)
        hub = min(c, key=lambda m: (-inside[m], m))
        communities.append({"id": i, "size": len(c), "main_team": main, "purity": round(k / len(known), 3) if known else None,
                            "team_known": len(known), "top_teams": dict(teams.most_common(3)),
                            "hub": hub, "hub_reviews_inside": inside[hub], "members": sorted(c)})
    bc = nx.betweenness_centrality(g) if g else {}
    bridges = [{"login": m, "betweenness": round(b, 4), "community": of[m],
                "communities_reached": len({of[x] for x in g[m]} | {of[m]})}
               for m, b in sorted(bc.items(), key=lambda kv: (-kv[1], kv[0]))[:C.BRIDGES_TOP]]

    by_area = defaultdict(Counter)
    for src, n in {(e["src"], e["pr"]) for e in events if e["type"] == "approve"}:
        if a := (pr_areas or {}).get(n):
            by_area[a][src] += 1
    single = []
    for area, c in sorted(by_area.items()):
        tot, (who, k) = sum(c.values()), c.most_common(1)[0]
        if tot >= C.SINGLE_POINT_MIN and k / tot >= C.SINGLE_POINT_SHARE:
            single.append({"area": area, "approver": who, "share": round(k / tot, 3), "approvals": tot})
    return {"communities": communities, "bridges": bridges, "single_points": single}


def _points() -> dict[int, float]:
    """Deep-read P where present, else triage tier points (llm_error rows skipped)."""
    pts = {}
    tri, deep = C.OUT / "triage.jsonl", C.OUT / "deepread.jsonl"
    for t in map(json.loads, open(tri)) if tri.exists() else []:
        if t.get("tier") in C.TIER_POINTS:
            pts[t["number"]] = C.TIER_POINTS[t["tier"]]
    for d in map(json.loads, open(deep)) if deep.exists() else []:
        pts[d["number"]] = d["P"]
    return pts


def main(prs_path: Path = C.PRS) -> dict:
    from impact.normalize import load
    t0 = time.time()
    prs = load(prs_path)
    rd = {r["number"]: r for r in map(json.loads, open(C.REVIEW_DETAIL))} if C.REVIEW_DETAIL.exists() else None
    opt = lambda p: json.loads(p.read_text()) if p.exists() else None
    team_map, lineage = opt(C.TEAM_MAP), opt(C.LINEAGE)
    events = build_events(prs, rd, lineage)
    cov = coverage(prs, rd, lineage)
    win = [p for p in prs if p["in_window"]]
    points = _points()
    struct = team_structure(events, team_map, {p["number"]: pr_area(p) for p in win})
    people = person_metrics(events, prs, team_map, cov)
    of = {m: c["id"] for c in struct["communities"] for m in c["members"]}
    bridge = {b["login"]: i + 1 for i, b in enumerate(struct["bridges"])}
    for login, m in people.items():
        m["community"], m["bridge_rank"] = of.get(login), bridge.get(login)
    out = {
        "definitions": DEFINITIONS,
        "summary": {"window_prs": len(win), "events": dict(Counter(e["type"] for e in events)), "people": len(people),
                    "coverage_prs": {k: len(v) for k, v in cov.items()},
                    "points_seeded_prs": sum(p["number"] in points for p in win), "seconds": round(time.time() - t0, 1)},
        "people": people, "trust_rank": trust_rank(events), "importance_flow": importance_flow(win, points, events), **struct,
    }
    C.OUT.mkdir(exist_ok=True)
    (C.OUT / "team_graph.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(json.dumps(out["summary"]))
    return out


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else C.PRS)
