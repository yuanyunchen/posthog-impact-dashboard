"""Role profile (spec §10 L2', trimmed by §11): who he reviews, who reviews him, team, primary area ownership.
Network metrics (first-pass rate, trust rank, communities…) live in impact/fine/team_graph.py and are merged in
under `network` when out/team_graph.json exists. Every value sits under a key so L3/L4 can cite `role.<key>`."""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from impact import config as C, paths
from impact.contracts import validate


def _human(login: str | None, is_bot: bool | None = None) -> bool:
    return bool(login) and not is_bot and not C.is_bot(login)


def _credited(pr: dict) -> str | None:
    """Human the PR counts for; uncredited AI-agent PRs (credited_to None) belong to nobody."""
    a = pr["credited_to"] if "credited_to" in pr else pr.get("author")
    return a if _human(a) else None


AREA_OWNER = {f"Product: {name}": o.removeprefix("team-") for name, o, *_ in paths.PRODUCTS.values() if o and o != "?"}


def _top(c: Counter) -> list[dict]:
    return [{"login": k, "prs": v} for k, v in c.most_common(C.ROLE_TOP)]


def network_entry(login: str, team_graph: dict | None) -> dict | None:
    """His row of out/team_graph.json people + his trust_rank / importance_flow; None when the graph is absent."""
    if team_graph is None:
        return None
    return {**(team_graph.get("people") or {}).get(login, {}),
            **{k: (team_graph.get(k) or {}).get(login) for k in ("trust_rank", "importance_flow")}}


def role_profile(login: str, prs: list[dict], team_map: dict | None, team_graph: dict | None = None) -> dict:
    """prs = ALL window PRs (others' PRs are needed for reviews given and the area ranking).
    Review counts are distinct PRs; bots, bot-authored PRs and self-reviews never count."""
    gave, got = Counter(), Counter()  # author he reviewed → PRs; reviewer of his PRs → PRs
    area_lines = defaultdict(Counter)  # area → author → rule-weighted changed lines
    for p in prs:
        if not p.get("in_window", True) or not (a := _credited(p)):
            continue
        reviewers = {r["author"] for r in p.get("reviews") or [] if _human(r.get("author"), r.get("is_bot"))} - {a}
        if a == login:
            got.update(reviewers)
        elif login in reviewers:
            gave[a] += 1
        for f in p.get("files") or []:
            area_lines[paths.area(f["path"])[0]][a] += paths.weight(f["path"]) * (f["additions"] + f["deletions"])
    mine = Counter({ar: c[login] for ar, c in area_lines.items() if c[login] > 0})
    top_area, top_lines = mine.most_common(1)[0] if mine else (None, 0)
    ranking = [a for a, _ in area_lines[top_area].most_common()] if top_area else []
    return validate("role", {
        "login": login, "team": (team_map or {}).get(login),
        # no official team → owner of his primary area (product_owners.tsv); never shown as the official team
        "team_inferred": None if (team_map or {}).get(login) else AREA_OWNER.get(top_area),
        "reviewed_authors_n": len(gave), "reviews_given_prs": sum(gave.values()), "top_reviewed": _top(gave),
        "reviewers_n": len(got), "reviews_received_prs": sum(got.values()), "top_reviewers": _top(got),
        "top_area": top_area, "top_area_share": round(top_lines / sum(mine.values()), 3) if mine else None,
        "top_area_rank": ranking.index(login) + 1 if top_area else None,
        "top_area_is_top": ranking[:1] == [login] if top_area else None,
        "top_area_leader": ranking[0] if ranking else None, "top_area_authors_n": len(ranking),
        "network": network_entry(login, team_graph),
    })


def main(prs_path: Path = C.PRS) -> None:
    from impact.normalize import load
    prs = load(prs_path)
    logins = [c["login"] for c in json.loads((C.OUT / "coarse.json").read_text())]
    opt = lambda p: json.loads(p.read_text()) if p.exists() else None
    team_map, graph = opt(C.TEAM_MAP), opt(C.OUT / "team_graph.json")
    roles = {l: role_profile(l, prs, team_map, graph) for l in logins}
    (C.OUT / "roles.json").write_text(json.dumps(roles, indent=1))
    print(f"roles for {len(roles)} candidates → {C.OUT / 'roles.json'}; team_graph {'merged' if graph else 'absent (network=None)'}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else C.PRS)
