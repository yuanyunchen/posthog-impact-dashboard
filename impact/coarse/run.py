"""Coarse ranking: recall 60 → 20 by tier mass over episodes × quality factor, plus team leverage."""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from impact import config as C
from impact.coarse.triage import triage
from impact.contracts import validate
from impact.episodes import episode_score, group_episodes
from impact.normalize import load
from impact.recall import features

SUBSTANTIVE_UP = {"substantive", "major", "landmark"}
MAJOR_UP = {"major", "landmark"}


def _episodes(prs: list[dict], tri: dict) -> list[list[int]]:
    """Episodes over triaged, non-error, non-mechanical PRs (mechanical never bridges episodes)."""
    return group_episodes([p for p in prs if p["number"] in tri and not tri[p["number"]]["llm_error"]
                           and C.TIER_POINTS[tri[p["number"]]["tier"]] > 0])


def _major(episodes: list[list[int]], tri: dict) -> int:
    return sum(any(tri[n]["tier"] in MAJOR_UP for n in ep) for ep in episodes)


def quality_rate(metrics: dict, mine: list[dict], tri: dict) -> float | None:
    """R7: q = 1 − |affected ∩ eligible| / |eligible|. affected = recall's distinct reverted-or-explicitly-fixed PRs;
    eligible = mature (merged ≤ MATURE_CUTOFF) PRs triaged substantive or above. None = unknown."""
    affected = metrics.get("affected_prs")
    eligible = {p["number"] for p in mine if p["merged_at"] <= C.MATURE_CUTOFF and tri[p["number"]]["tier"] in SUBSTANTIVE_UP}
    if affected is None or not eligible:
        return None
    return 1 - len(eligible & set(affected)) / len(eligible)


def person(login: str, metrics: dict, prs: list[dict], tri: dict) -> dict:
    triaged = [p for p in prs if p["number"] in tri]
    ok = [p for p in triaged if not tri[p["number"]]["llm_error"]]
    counts = Counter(tri[p["number"]]["tier"] for p in ok)
    scored = [p for p in ok if C.TIER_POINTS[tri[p["number"]]["tier"]] > 0]
    episodes = _episodes(prs, tri)
    mass = sum(episode_score([C.TIER_POINTS[tri[n]["tier"]] for n in ep]) for ep in episodes)
    q = quality_rate(metrics, ok, tri)
    qf = 1.0 if q is None else max(0.5, q)
    return {"login": login, "tier_counts": {t: counts[t] for t in C.TIER_POINTS},
            "prs": len(prs), "untriaged": len(prs) - len(triaged), "llm_errors": len(triaged) - len(ok),
            "episodes": len(episodes), "major_episodes": _major(episodes, tri), "raw_points": sum(C.TIER_POINTS[tri[p["number"]]["tier"]] for p in scored),
            "mass": mass, "q": q, "quality_factor": qf, "quality_unknown": q is None,
            "team_score": metrics.get("team_leverage"), "coarse_score": mass * qf, "selected_by": []}


def coarse(recall: list[dict], triage: list[dict], prs: list[dict], metrics_for=None) -> list[dict]:
    """Recalled people plus the "major" route (top COARSE_TOP_MAJOR triaged authors by major/landmark episodes, ties
    included; metrics_for(logins) supplies rule metrics for those outside recall), sorted by coarse_score.
    Selected rows have non-empty selected_by; the major route may push the shortlist past COARSE_N."""
    tri = {t["number"]: t for t in triage}
    by_login = defaultdict(list)
    for p in prs:
        if p["in_window"] and p.get("credited_to"):
            by_login[p["credited_to"]].append(p)
    authors = {p["credited_to"] for p in prs if p["in_window"] and p.get("credited_to") and p["number"] in tri}
    majors = {l: _major(_episodes(by_login[l], tri), tri) for l in authors}
    ranked = sorted((n for n in majors.values() if n > 0), reverse=True)
    floor = ranked[min(C.COARSE_TOP_MAJOR, len(ranked)) - 1] if ranked else 1
    leaders = {l for l, n in majors.items() if n > 0 and n >= floor}
    recalled = {r["login"] for r in recall}
    missing = sorted(leaders - recalled)
    extra = (metrics_for(missing) if metrics_for and missing else None) or {}
    people = recall + [{"login": l, "metrics": extra.get(l) or {}, "recalled_by": ["major"]} for l in missing]
    rows = sorted(({**person(r["login"], r["metrics"], by_login[r["login"]], tri), "recalled_by": r["recalled_by"]}
                   for r in people),
                  key=lambda r: -r["coarse_score"])
    for r in rows[:C.COARSE_TOP_SCORE]:
        r["selected_by"].append("score")
    for r in sorted(rows, key=lambda r: -(r["team_score"] or 0))[:C.COARSE_TOP_TEAM]:
        if r["team_score"]:
            r["selected_by"].append("team")
    for r in rows:
        if r["login"] in leaders:
            r["selected_by"].append("major")
    for r in rows:  # R4: top up to COARSE_N in coarse_score order
        if sum(bool(x["selected_by"]) for x in rows) >= C.COARSE_N:
            break
        if not r["selected_by"]:
            r["selected_by"].append("fill")
    return rows


def audit(audit_triage: list[dict], recall: list[dict]) -> list[str]:
    """R4: unrecalled authors with a major/landmark PR in the random audit sample."""
    recalled = {r["login"] for r in recall}
    return sorted({t["author"] for t in audit_triage
                   if t["tier"] in ("major", "landmark") and t["author"] and t["author"] not in recalled})


def rule_metrics(logins: list[str], prs: list[dict]) -> dict:
    """Recall's rule metrics (q inputs, team_leverage) for people added outside recall."""
    opt = lambda p: json.loads(p.read_text()) if p.exists() else None
    return features.rule_metrics_for(logins, prs, opt(C.CHANGELOG), opt(C.TEAM_MAP), opt(C.COMMIT_AUTHORS))


def main(prs_path: Path = C.PRS) -> None:
    prs = load(prs_path)
    recall = json.loads((C.OUT / "recall.json").read_text())
    sample_path = C.OUT / "recall_audit_sample.json"
    sample = set(json.loads(sample_path.read_text())) if sample_path.exists() else set()
    window = [p for p in prs if p["in_window"] and p.get("credited_to")]
    logins = {r["login"] for r in recall}
    tri = triage(window)  # every human window PR (~$5.6, cached): the "major" route must see all authors (audit finding 1)
    found = audit([t for t in tri if t["number"] in sample], recall)
    if found:
        done = {t["number"] for t in tri}
        tri += triage([p for p in window if p["credited_to"] in found and p["number"] not in done])
        extra = rule_metrics(found, prs)
        recall = recall + [{"login": l, "metrics": extra.get(l) or {}, "recalled_by": ["audit"]} for l in found]
    rows = coarse(recall, tri, prs, lambda logins: rule_metrics(logins, prs))
    with open(C.OUT / "triage.jsonl", "w") as f:
        f.writelines(json.dumps(t) + "\n" for t in tri)
    selected = [validate("coarse", r) for r in rows if r["selected_by"]]
    (C.OUT / "coarse.json").write_text(json.dumps(selected, indent=1))
    errors = sum(bool(t["llm_error"]) for t in tri)
    print(f"triaged {len(tri)}, llm_error {errors} ({errors / max(1, len(tri)):.1%}), "
          f"cost ${sum(t['cost'] or 0 for t in tri):.3f}; audit-recalled {found or 'none'}")
    major_added = [r["login"] for r in rows if "major" in r["recalled_by"]]
    print(f"major route: {sum('major' in r['selected_by'] for r in rows)} people (ties included), "
          f"from outside recall {major_added or 'none'}; shortlist {len(selected)} (COARSE_N {C.COARSE_N})")
    print(f"selected {len(selected)} of {len(rows)}; cut {len(rows) - len(selected)}, next below cut: "
          + ", ".join(f"{r['login']} {r['coarse_score']:.1f}" for r in rows if not r["selected_by"])[:400])
    for r in selected:
        print(f"  {r['login']:<24} score {r['coarse_score']:6.1f} mass {r['mass']:6.1f} major {r['major_episodes']:3} q {r['q']} "
              f"team {r['team_score'] and round(r['team_score'], 1)} {r['selected_by']}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else C.PRS)
