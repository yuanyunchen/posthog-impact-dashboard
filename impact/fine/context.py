"""Company and team context for the L4 decision agent: where the important work happened, who owns what, how people
collaborate, and where each candidate sits in that picture. Script only (no LLM); every number carries a citable key.
CLI: python -m impact.fine.context <prs_path>  →  OUT/context/company.md"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from impact import config as C
from impact.episodes import group_episodes
from impact.fine.refscore import percentiles
from impact.fine.roles import AREA_OWNER
from impact.fine.workstreams import _area

MAJOR_UP = {"major", "landmark"}
TOP_AREAS = 15  # areas past this are summed into one "other" row, never dropped
MAX_BYTES = 25_000


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def _table(head: list[str], rows: list[list]) -> list[str]:
    return ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(map(str, r)) + " |" for r in rows]


def build(prs: list[dict], triage: list[dict], changelog: dict | None, team_map: dict | None, graph: dict | None,
          candidates: list[str], roles: dict | None = None) -> str:
    """prs = all PRs (window and bots filtered here); triage = coarse triage records; graph = team_graph.json."""
    team_map, roles, cand = team_map or {}, roles or {}, set(candidates)
    star = lambda l: f"★{l}" if l in cand else l
    win = [p for p in prs if p.get("in_window") and p.get("credited_to") and not C.is_bot(p["credited_to"])]
    by_num = {p["number"]: p for p in win}
    tier = {t["number"]: t["tier"] for t in triage if t["number"] in by_num and not t.get("llm_error")}
    area_of = {n: _area([p]) for n, p in by_num.items()}
    owner = AREA_OWNER

    # major+ episodes: per author over triaged non-mechanical PRs; an episode's area is its dominant area
    by_author = defaultdict(list)
    for p in win:
        if tier.get(p["number"]) not in (None, "mechanical"):
            by_author[p["credited_to"]].append(p)
    major_eps = Counter()
    for ps in by_author.values():
        for ep in group_episodes(ps):
            if any(tier[n] in MAJOR_UP for n in ep):
                major_eps[_area([by_num[n] for n in ep])] += 1
    cl_entries = defaultdict(set)  # area → distinct (title, date)
    for n, es in (changelog or {}).items():
        if int(n) in by_num:
            cl_entries[area_of[int(n)]] |= {(e.get("title"), e.get("date")) for e in es}
    prs_by_area = Counter(area_of.values())
    n_major, n_cl = sum(major_eps.values()), len({e for s in cl_entries.values() for e in s})
    authors = {p["credited_to"] for p in win}
    teams_active = {t for a in authors for t in team_map.get(a) or []}

    L = ["# PostHog engineering context (window 2026-08-05 → 2026-11-03)", "",
         "Script-generated from merged PRs, coarse triage, the public changelog, data/team_map.json and the team event graph. "
         "★ = one of the 20 candidates. Cite numbers by the key in backticks.", "",
         "## 1. Where the work happened", "",
         f"`company.human_prs`={len(win)} · `company.people`={len(authors)} · `company.teams_active`={len(teams_active)} "
         f"(team known for {sum(a in team_map for a in authors)} of {len(authors)} authors) · "
         f"`company.triaged_prs`={len(tier)} · `company.major_episodes`={n_major} · `company.changelog_entries`={n_cl}", "",
         "Major+ episodes count only triaged PRs (the 60 recalled people plus the audit sample), so they show where "
         "candidates' and other active engineers' important work landed, not a census.", "",
         f"Key: `area[<area>].<column>`. Top {TOP_AREAS} areas by major+ episodes, then PRs.", ""]
    order = sorted(prs_by_area, key=lambda a: (-major_eps[a], -prs_by_area[a], a))
    rows = [[a, owner.get(a) or "—", prs_by_area[a], _pct(prs_by_area[a] / len(win)), major_eps[a],
             _pct(major_eps[a] / n_major) if n_major else "—", len(cl_entries[a])] for a in order[:TOP_AREAS]]
    rest = order[TOP_AREAS:]
    if rest:
        r_prs, r_maj = sum(prs_by_area[a] for a in rest), sum(major_eps[a] for a in rest)
        rows.append([f"other ({len(rest)} areas)", "—", r_prs, _pct(r_prs / len(win)), r_maj,
                     _pct(r_maj / n_major) if n_major else "—", sum(len(cl_entries[a]) for a in rest)])
    L += _table(["area", "owner team", "prs", "prs_share", "major_episodes", "major_share", "changelog"], rows)

    # 2. teams
    members = defaultdict(set)
    for login, ts in team_map.items():
        if not C.is_bot(login):
            for t in ts:
                members[t].add(login)
    t_prs, t_major, t_areas = Counter(), Counter(), defaultdict(Counter)
    for p in win:
        for t in team_map.get(p["credited_to"]) or []:
            t_prs[t] += 1
            t_major[t] += tier.get(p["number"]) in MAJOR_UP
            t_areas[t][area_of[p["number"]]] += 1
    owned = defaultdict(list)
    for a, t in owner.items():
        owned[t].append(a.removeprefix("Product: "))
    L += ["", "## 2. Teams", "",
          f"Teams with ≥1 window PR by a mapped member ({len(t_prs)}; {len(members) - len(t_prs)} mapped teams had none). "
          "A person on two teams counts for both. Key: `team[<team>].<column>`.", ""]
    rows = [[t, len(members[t]), t_prs[t], t_major[t], ", ".join(sorted(owned[t])) or "—",
             ", ".join(f"{a} {c}" for a, c in t_areas[t].most_common(3)),
             ", ".join(star(m) for m in sorted(members[t] & cand)) or "—"]
            for t in sorted(t_prs, key=lambda t: (-t_major[t], -t_prs[t], t))]
    L += _table(["team", "members", "prs", "major_prs", "owns (products)", "where members' PRs land (top 3)", "candidates"], rows)

    # 3. changelog themes
    L += ["", "## 3. Changelog themes by area", "",
          f"`company.changelog_entries`={n_cl} distinct entries tied to window PRs; an entry spanning PRs in two areas counts in both.", ""]
    spread = Counter(e for es in cl_entries.values() for e in es)  # roll-up entries ("19 new MCP tools") span many areas
    for a in sorted((a for a in cl_entries if cl_entries[a]), key=lambda a: (-len(cl_entries[a]), a)):
        titles = list(dict.fromkeys(t for t, _ in sorted(cl_entries[a], key=lambda e: (spread[e], e[0] or "")) if t))
        L.append(f"- **{a}** `changelog[{a}]`={len(cl_entries[a])}: " + "; ".join(titles[:3]) + (" …" if len(titles) > 3 else ""))

    # 4. collaboration structure
    L += ["", "## 4. Collaboration structure (review graph)", ""]
    comm_of, bridge = {}, set()
    if graph is None:
        L.append("team_graph.json missing: collaboration structure unknown.")
    else:
        s = graph.get("summary") or {}
        L += [f"`graph.people`={s.get('people')} · events: " + " · ".join(f"`graph.events.{k}`={v}" for k, v in (s.get("events") or {}).items()), "",
              "Communities (Louvain on approve + changes-requested + comment). Purity = share of members with a known team "
              "who are on the main team. Key: `community[<id>].<column>`.", ""]
        rows = []
        for c in graph.get("communities") or []:
            ms = [m for m in c["members"] if not C.is_bot(m)]
            comm_of |= {m: c["id"] for m in ms}
            rows.append([c["id"], len(ms), c.get("main_team") or "—", c.get("purity") if c.get("purity") is not None else "—",
                         f"{star(c['hub'])} ({c.get('hub_reviews_inside')})" if c.get("hub") else "—",
                         ", ".join(star(m) for m in sorted(set(ms) & cand)) or "—"])
        L += _table(["id", "size", "main_team", "purity", "review hub (reviews inside)", "candidates"], rows)
        bridges = [b for b in graph.get("bridges") or [] if not C.is_bot(b["login"])][:10]
        bridge = {b["login"] for b in bridges}
        L += ["", "Top bridges by betweenness (connect communities). Key: `bridge[<login>].<column>`.", ""]
        L += _table(["login", "betweenness", "home community", "communities reached"],
                    [[star(b["login"]), b["betweenness"], b.get("community"), b.get("communities_reached")] for b in bridges])
        sp = [x for x in graph.get("single_points") or [] if not C.is_bot(x.get("approver"))]
        L += ["", f"Single points of approval (one person gives ≥{C.SINGLE_POINT_SHARE:.0%} of an area's approvals): "
              + ("; ".join(f"{x['area']} → {star(x['approver'])} ({_pct(x['share'])} of {x['approvals']})" for x in sp) or "none found")]

    # 5. candidates
    tr = percentiles((graph or {}).get("trust_rank") or {})
    L += ["", "## 5. The candidates in this picture", "",
          "primary area = area with most of his rule-weighted changed lines; its major_share = that area's share of all "
          "major+ episodes (section 1). A team marked \"(inferred from area)\" is the owner of his primary area in "
          "product_owners.tsv, shown only when data/team_map.json has no entry for him. trust_rank percentile is among everyone in the graph. Key: `cand[<login>].<column>`.", ""]
    rows = []
    for l in candidates:
        r = roles.get(l) or {}
        a = r.get("top_area")
        inferred = r.get("team_inferred") or AREA_OWNER.get(a)
        team = ", ".join(team_map.get(l) or []) or (f"{inferred} (inferred from area)" if inferred else "unknown")
        rows.append([l, team, comm_of.get(l, "—"),
                     f"{a} ({_pct(r['top_area_share'])} of his work{', top changer' if r.get('top_area_is_top') else ''})" if a else "—",
                     _pct(major_eps[a] / n_major) if a and n_major else "—", "yes" if l in bridge else "no",
                     round(tr[l]) if l in tr else "—"])
    L += _table(["login", "team", "community", "primary area", "area major_share", "bridge", "trust_rank pct"], rows)
    return "\n".join(L) + "\n"


def main(prs_path: Path = C.PRS) -> None:
    from impact.normalize import load
    opt = lambda p: json.loads(p.read_text()) if p.exists() else None
    coarse = json.loads((C.OUT / "coarse.json").read_text())
    triage = [json.loads(l) for l in open(C.OUT / "triage.jsonl")]
    md = build(load(prs_path), triage, opt(C.CHANGELOG), opt(C.TEAM_MAP), opt(C.OUT / "team_graph.json"),
               [c["login"] for c in coarse], opt(C.OUT / "roles.json"))
    out = C.OUT / "context" / "company.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md)
    size = len(md.encode())
    print(f"{out}: {size} bytes" + (f" — OVER {MAX_BYTES}" if size > MAX_BYTES else ""))


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else C.PRS)
