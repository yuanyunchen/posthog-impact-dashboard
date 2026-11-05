"""L2 workstreams (spec §11.2): one person's episodes clustered by product area and title scope, with L1 summaries and
script aggregates. No LLM here: the L3 evaluator writes the narrative from these clusters."""
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean

from impact import config as C, paths
from impact.contracts import validate
from impact.episodes import SCOPE, group_episodes

MISC = "misc"


def _scope(pr: dict) -> str | None:
    m = SCOPE.match(pr["title"].strip())
    return m and m.group(1).lower()


def _area(prs: list[dict]) -> str:
    """Dominant area by rule-weighted changed lines; noise-only work falls back to raw lines."""
    w, raw = Counter(), Counter()
    for f in (f for p in prs for f in p.get("files") or []):
        a, lines = paths.area(f["path"])[0], f["additions"] + f["deletions"]
        w[a] += paths.weight(f["path"]) * lines
        raw[a] += lines
    best = w if any(w.values()) else raw
    return best.most_common(1)[0][0] if best else "Unknown area"


def _human_reviewers(pr: dict) -> set[str]:
    me = pr.get("credited_to") or pr.get("author")
    return {r["author"] for r in pr.get("reviews") or []
            if r.get("author") and not r.get("is_bot") and not C.is_bot(r["author"]) and r["author"] != me}


def _stream(wid: str, area: str, nums: list[int], by_num: dict, tri: dict, reads: dict, merged=()) -> dict:
    """Script-only fields. A PR's points = deep-read P when sampled, else its tier points (same scale, R8)."""
    nums = sorted(nums)
    tier = {n: (tri.get(n) or {}).get("tier") for n in nums}
    P = {n: reads[n]["P"] if n in reads else None for n in nums}
    pts = {n: P[n] if P[n] is not None else C.TIER_POINTS.get(tier[n], 0) for n in nums}
    lines = {n: (by_num[n].get("additions") or 0) + (by_num[n].get("deletions") or 0) for n in nums}
    dates = [datetime.fromisoformat(by_num[n]["merged_at"].replace("Z", "+00:00")) for n in nums]
    scopes = Counter(s for n in nums if (s := _scope(by_num[n])))
    big = sum(tier[n] in ("substantive", "major", "landmark") for n in nums)
    title = (f"杂项（含 {big} 条实质及以上）" if big else "杂项维护") if wid == MISC \
        else area + (f" · {scopes.most_common(1)[0][0]}" if scopes else "")
    collab = Counter(a for n in nums for a in _human_reviewers(by_num[n]))
    ok = [reads[n] for n in nums if n in reads]
    return {
        "id": wid, "title": title, "area": area, "merged_areas": list(merged),
        "prs": [{"number": n, "tier": tier[n], "P": None if P[n] is None else round(P[n], 2),
                 "summary": (reads[n].get("summary") if n in reads else None) or (tri.get(n) or {}).get("summary")
                 or by_num[n]["title"]} for n in nums],
        "agg": {"prs_n": len(nums), "deepread_n": len(ok),
                "tier_counts": dict(Counter(tier[n] or "untriaged" for n in nums)),
                "points_sum": round(sum(pts.values()), 2),
                "L_mean": round(mean(r["L"] for r in ok), 2) if ok else None,
                "Q_mean": round(mean(r["Q"] for r in ok), 2) if ok else None,
                "span_days": (max(dates) - min(dates)).days, "lines": sum(lines.values())},
        "top_prs": sorted((n for n in nums if pts[n] > 0),
                          key=lambda n: (-pts[n], -C.TIER_POINTS.get(tier[n], 0), -lines[n]))[:C.WS_TOP_PRS],
        "collaborators": [{"login": a, "prs_reviewed": c} for a, c in collab.most_common()],
    }


def _mass(units: list[list[int]], tri: dict) -> int:
    return sum(C.TIER_POINTS.get((tri.get(n) or {}).get("tier"), 0) for u in units for n in u)


def _merge_by_scope(groups: list[tuple], by_num: dict, tri: dict) -> list[tuple]:
    """Area groups sharing a dominant title scope are one piece of work split across code areas (e.g. `devex` touching
    Django, CI and API): merge them under the heaviest group's area."""
    overall = Counter(sc for g in groups for u in g[1] for n in u if (sc := _scope(by_num[n])))
    by_scope, out = defaultdict(list), []
    for g in groups:
        c = Counter(sc for u in g[1] for n in u if (sc := _scope(by_num[n])))
        if c:  # tie inside a group → the person's more frequent scope
            by_scope[max(c, key=lambda sc: (c[sc], overall[sc], sc))].append(g)
        else:
            out.append(g)
    for gs in by_scope.values():
        gs.sort(key=lambda g: -_mass(g[1], tri))
        out.append((gs[0][0], [u for g in gs for u in g[1]]))
    return out


def cluster(person_prs: list[dict], triage: list[dict], deepread: list[dict] = (),
            episodes: list[list[int]] | None = None) -> list[dict]:
    """Episodes → groups by dominant area; < WS_MIN groups → split the largest by title scope; > WS_MAX → the
    lowest-points groups fold into misc (named in merged_areas). Groups sharing a dominant scope merge first.
    Mechanical PRs never form a stream: always misc."""
    tri = {t["number"]: t for t in triage if not t.get("llm_error")}  # failed triage → tier None ("untriaged")
    reads = {d["number"]: d for d in deepread if not d.get("llm_error")}
    by_num = {p["number"]: p for p in person_prs}
    mech = {n for n in by_num if (tri.get(n) or {}).get("tier") == "mechanical"}
    if episodes is None:
        episodes = group_episodes([p for n, p in by_num.items() if n not in mech])
    units = [u for ep in episodes if (u := sorted(n for n in ep if n in by_num and n not in mech))]
    seen = {n for u in units for n in u}
    units += [[n] for n in sorted(by_num) if n not in seen and n not in mech]  # PRs the caller's episodes missed

    groups = defaultdict(list)
    for u in units:
        groups[_area([by_num[n] for n in u])].append(u)
    groups = _merge_by_scope(list(groups.items()), by_num, tri)
    while len(groups) < C.WS_MIN:
        splittable = [g for g in groups if len({_scope(by_num[u[0]]) for u in g[1]}) > 1]
        if not splittable:
            break
        g = max(splittable, key=lambda g: len(g[1]))
        parts = defaultdict(list)
        for u in g[1]:
            parts[_scope(by_num[u[0]])].append(u)
        groups.remove(g)
        groups += [(g[0], us) for us in parts.values()]
    groups.sort(key=lambda g: (-_mass(g[1], tri), g[0]))
    tail = []
    if len(groups) + bool(mech) > C.WS_MAX:
        groups, tail = groups[:C.WS_MAX - 1], groups[C.WS_MAX - 1:]
    out = [_stream(f"ws{i}", area, [n for u in us for n in u], by_num, tri, reads) for i, (area, us) in enumerate(groups, 1)]
    for w, (_, us) in zip(out, groups):  # areas actually touched, so a scope-merged stream shows its spread
        w["areas"] = sorted({_area([by_num[n] for n in u]) for u in us})
    if mech or tail:
        out.append(_stream(MISC, "mixed", sorted(mech) + [n for _, us in tail for u in us for n in u], by_num, tri, reads,
                           sorted({a for a, _ in tail})))
    return [validate("workstream", w) for w in out]


def main(logins: list[str], prs_path: Path = C.PRS) -> None:
    from impact.normalize import load
    prs = [p for p in load(prs_path) if p["in_window"] and p.get("credited_to") in logins]
    triage = [json.loads(l) for l in open(C.OUT / "triage.jsonl")]
    path = C.OUT / "deepread.jsonl"
    deepread = [json.loads(l) for l in open(path)] if path.exists() else []
    (C.OUT / "workstreams").mkdir(parents=True, exist_ok=True)
    for login in logins:
        mine = [p for p in prs if p["credited_to"] == login]
        ws = cluster(mine, triage, deepread)
        (C.OUT / "workstreams" / f"{login}.json").write_text(json.dumps(ws, indent=1, ensure_ascii=False))
        print(f"{login}: {len(mine)} PRs → {len(ws)} workstreams " + ", ".join(f"{w['id']} {w['agg']['prs_n']}" for w in ws))


if __name__ == "__main__":
    main(sys.argv[2:], Path(sys.argv[1]))
