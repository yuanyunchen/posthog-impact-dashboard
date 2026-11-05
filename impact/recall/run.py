"""Recall: rules only, err on the side of recalling (plan Task 2 + review-codex R4) → out/recall.json."""
import json
import random
import sys
from pathlib import Path

from impact import config as C
from impact.contracts import validate
from impact.normalize import load
from impact.recall.features import pr_rule_weight, person_metrics

ROUTES = [  # (route, metric, top n)
    ("delivery", "w_rule_sum", C.RECALL_TOP_DELIVERY),
    ("team", "team_leverage", C.RECALL_TOP_TEAM),
    ("system", "core_w_rule", C.SYSTEM_ROUTE_TOP),
]


def core_spike_threshold(prs: list[dict]) -> float:
    """Single-PR core-path w_rule at the top EXEMPT_TOP_PCT of all credited window PRs."""
    vals = sorted(w * (s or 0) for p in prs if p["in_window"] and p["credited_to"] for w, s in [pr_rule_weight(p)])
    return vals[int(len(vals) * (1 - C.EXEMPT_TOP_PCT))] if vals else float("inf")


def recall(prs: list[dict], changelog: dict | None = None, team_map: dict | None = None, stats: dict | None = None,
           commit_authors: dict | None = None, tiers: dict | None = None, keep: list[dict] = ()) -> list[dict]:
    """keep = earlier entries recalled by "audit" (added by coarse); merged back with fresh metrics, never dropped."""
    m = person_metrics(prs, changelog, team_map, commit_authors, tiers)
    spike = core_spike_threshold(prs)
    exempt = {
        login: [r for r, ok in [("changelog", x["changelog_prs"]), ("critical", x["critical_prs"]),
                                ("core_spike", x["max_core_w_rule"] >= spike > 0)] if ok]
        for login, x in m.items()
    }
    eligible = [l for l, x in m.items()
                if x["prs"] >= C.ACTIVITY_MIN_PRS or x["reviews_given"] >= C.ACTIVITY_MIN_REVIEWS or exempt[l]]
    by = {l: [] for l in eligible}
    for route, key, n in ROUTES:
        for l in sorted((l for l in eligible if m[l][key] > 0), key=lambda l: (-m[l][key], l))[:n]:
            by[l].append(route)
    for l in eligible:
        by[l] += [r for r in ("changelog", "critical") if r in exempt[l]]
    out = [validate("recall", {"login": l, "metrics": m[l], "recalled_by": r, "floor_exempt": exempt[l]})
           for l, r in by.items() if r]
    have = {x["login"]: x for x in out}
    for k in keep:
        if k["login"] in have:
            have[k["login"]]["recalled_by"] += [r for r in k["recalled_by"] if r not in have[k["login"]]["recalled_by"]]
        else:
            out.append(validate("recall", {"login": k["login"], "metrics": m.get(k["login"]) or k["metrics"],
                                           "recalled_by": k["recalled_by"], "floor_exempt": exempt.get(k["login"], [])}))
    out.sort(key=lambda x: -x["metrics"].get("w_rule_sum", 0))
    if stats is not None:
        stats.update({
            "people": len(m), "eligible": len(eligible), "below_floor": len(m) - len(eligible),
            "core_spike_threshold": round(spike, 3), "recalled": len(out),
            "carried_over_audit": len(keep),
            "over_cap": max(0, len(out) - C.RECALL_N),  # kept, not cut (R4)
            "route_hits": {r: sum(r in x["recalled_by"] for x in out) for r in [r for r, _, _ in ROUTES] + ["changelog", "critical"]},
            "only_route": {r: sum(x["recalled_by"] == [r] for x in out) for r in [r for r, _, _ in ROUTES] + ["changelog", "critical"]},
        })
    return out


def audit_sample(prs: list[dict], recalled: set[str]) -> tuple[list[int], int]:
    """R4 miss audit: AUDIT_SAMPLE random window PRs (seed SEED) by humans who were not recalled."""
    pop = sorted(p["number"] for p in prs if p["in_window"] and p["credited_to"] and p["credited_to"] not in recalled)
    return sorted(random.Random(C.SEED).sample(pop, min(C.AUDIT_SAMPLE, len(pop)))), len(pop)


def _opt_json(path: Path):
    return json.loads(path.read_text()) if path.exists() else None


def main(prs_path: Path = C.PRS) -> dict:
    prs = load(prs_path)
    changelog, team_map = _opt_json(C.DATA / "changelog.json"), _opt_json(C.DATA / "team_map.json")
    commit_authors = _opt_json(C.DATA / "commit_authors.json")
    stats = {"prs_path": str(prs_path), "changelog_loaded": changelog is not None, "team_map_loaded": team_map is not None,
             "commit_authors_loaded": commit_authors is not None}
    tri = next((p for p in (C.OUT / "triage.jsonl", C.ROOT / "out_full/triage.jsonl") if p.exists()), None)
    tiers = {t["number"]: t["tier"] for t in map(json.loads, open(tri))} if tri else None
    prev = _opt_json(C.OUT / "recall.json") or []
    keep = [x for x in prev if "audit" in x["recalled_by"]]
    stats["triage_for_tiers"] = str(tri) if tri else None
    rec = recall(prs, changelog, team_map, stats, commit_authors, tiers, keep)
    # sample from route recalls only, so carried-over audit entries do not change the audit population
    sample, pop = audit_sample(prs, {x["login"] for x in rec if set(x["recalled_by"]) - {"audit"}})
    stats.update({"audit_population": pop, "audit_sampled": len(sample)})
    C.OUT.mkdir(exist_ok=True)
    (C.OUT / "recall.json").write_text(json.dumps(rec, indent=1))
    (C.OUT / "recall_audit_sample.json").write_text(json.dumps(sample))
    (C.OUT / "recall_stats.json").write_text(json.dumps(stats, indent=1))
    return stats


if __name__ == "__main__":
    print(json.dumps(main(Path(sys.argv[1]) if len(sys.argv) > 1 else C.PRS), indent=1))
