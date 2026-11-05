"""L0 comparison matrix for L4 (spec §10 rule 3): raw values + within-candidate percentiles, straight from the script."""
import json
import sys
from pathlib import Path

from impact import config as C
from impact.contracts import validate
from impact.episodes import group_episodes
from impact.fine.refscore import percentiles
from impact.fine.sample import estimate

MAJOR_UP = {"major", "landmark"}

# key → (label, definition, source, direction). direction: "higher" / "lower" is better, "neutral" = descriptive only.
# Percentiles always rank the raw value upward; read "lower" columns accordingly.
COLUMNS = {
    "delivery": ("交付估计", "Σ episode score (max P + 0.25 × rest) per contribution episode; deep-read P replaces tier points "
                 "for sampled PRs, tier points elsewhere (review-codex R5/R8)", "estimates.delivery_hat", "higher"),
    "major_episodes": ("重大及以上片段数", "episodes containing ≥1 PR triaged major or landmark", "estimates.major_episodes", "higher"),
    "quality_rate": ("质量率", "1 − (reverted or explicitly follow-up-fixed PRs) / mature PRs triaged substantive or above (R7)",
                     "coarse.q", "higher"),
    "team_leverage": ("团队杠杆", "human reviews given × ln(1 + distinct authors served)", "metrics.team_leverage", "higher"),
    "requested_by": ("被请求评审人数", "distinct humans who requested his review", "team_graph", "higher"),
    "downstream_authors": ("下游作者数", "distinct authors who later built on files he changed (hub files excluded)", "team_graph", "higher"),
    "cross_team": ("跨团队数", "distinct teams (team_map) of authors he approved", "team_graph", "higher"),
    "changelog_prs": ("changelog 数", "his window PRs cited in the public changelog", "metrics.changelog_prs", "higher"),
    "ai_share": ("AI 协作占比", "his PRs whose commits are Co-authored-by an AI assistant (data/commit_authors.json) / his PRs",
                 "metrics.ai_share", "neutral"),
    "self_driving_share": ("AI agent 代发占比", "AI-agent (self-driving) PRs credited to him / his PRs", "metrics.ai_prs / metrics.prs",
                           "neutral"),
    "first_pass_rate": ("首轮通过率", "his PRs approved with no changes requested / his reviewed PRs", "team_graph", "higher"),
    "changes_requested_rate": ("被要求修改率", "his PRs that received CHANGES_REQUESTED / his reviewed PRs", "team_graph", "lower"),
    "trust_rank": ("信任度", "PageRank on the approval graph (reviewer → author)", "team_graph.trust_rank", "higher"),
    "importance_flow": ("重要性回流", "PR points propagated over the person–PR graph to authors and substantive reviewers",
                        "team_graph.importance_flow", "higher"),
}
# column → key in his out/team_graph.json entry (roles[login]["network"], impact/fine/team_graph.py); a key the graph
# lacks shows up in matrix["unmapped_network_keys"] instead of silently reading as unknown.
NETWORK_KEYS = {"requested_by": "requested_by_n", "downstream_authors": "built_on_by_n", "cross_team": "teams_covered_n",
                "first_pass_rate": "first_pass_rate", "changes_requested_rate": "changes_requested_rate",
                "trust_rank": "trust_rank", "importance_flow": "importance_flow"}


def major_episodes(person_triage: list[dict], episodes: list[list[int]]) -> int:
    major = {t["number"] for t in person_triage if t.get("tier") in MAJOR_UP}
    return sum(bool(major & set(ep)) for ep in episodes)


def _num(x):
    """Plain number, {value, n} metric (value None below the sample floor) or importance_flow {total, …}."""
    x = x.get("value", x.get("total")) if isinstance(x, dict) else x
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _ratio(m: dict):
    return round(m["ai_prs"] / m["prs"], 3) if m.get("prs") and m.get("ai_prs") is not None else None


def build_matrix(candidates: list[str], metrics: dict, coarse: dict, estimates: dict, roles: dict) -> dict:
    """All inputs are {login: record}. A missing value stays None and is left out of that column's percentiles."""
    net = {l: (roles.get(l) or {}).get("network") for l in candidates}
    get = {
        "delivery": lambda l: (estimates.get(l) or {}).get("delivery_hat"),
        "major_episodes": lambda l: (estimates.get(l) or {}).get("major_episodes"),
        "quality_rate": lambda l: (coarse.get(l) or {}).get("q"),
        "team_leverage": lambda l: (metrics.get(l) or {}).get("team_leverage"),
        "changelog_prs": lambda l: (metrics.get(l) or {}).get("changelog_prs"),
        "ai_share": lambda l: (metrics.get(l) or {}).get("ai_share"),
        "self_driving_share": lambda l: _ratio(metrics.get(l) or {}),
        **{c: (lambda l, k=k: _num((net[l] or {}).get(k))) for c, k in NETWORK_KEYS.items()},
    }
    raw = {c: {l: get[c](l) for l in candidates} for c in COLUMNS}
    pct = {c: percentiles(v) for c, v in raw.items()}
    # every pct reads "higher = better": flip lower-is-better columns (rank/compare/L4 all consume these)
    pct = {c: ({l: 100 - x for l, x in p.items() if x is not None} if COLUMNS[c][3] == "lower" else p) for c, p in pct.items()}
    return validate("matrix", {
        "n": len(candidates),
        "columns": {c: dict(zip(("label", "definition", "source", "direction"), v)) for c, v in COLUMNS.items()},
        "percentile": "0–100 by average rank among candidates with a value (ties share the mean rank); None = unknown",
        "rows": [{"login": l, "values": {c: raw[c][l] for c in COLUMNS},
                  "pct": {c: round(pct[c][l], 1) if l in pct[c] else None for c in COLUMNS}} for l in candidates],
        "missing": {c: [l for l in candidates if raw[c][l] is None] for c in COLUMNS},
        "team_graph": "present" if any(net.values()) else "absent: network columns unknown",
        "unmapped_network_keys": sorted({k for n in net.values() if n for k in NETWORK_KEYS.values() if k not in n}),
    })


def main(prs_path: Path = C.PRS) -> None:
    from impact.normalize import load
    coarse = {c["login"]: c for c in json.loads((C.OUT / "coarse.json").read_text())}
    metrics = {r["login"]: r["metrics"] for r in json.loads((C.OUT / "recall.json").read_text())}
    roles = json.loads((C.OUT / "roles.json").read_text())
    tri = {t["number"]: t for t in map(json.loads, open(C.OUT / "triage.jsonl")) if not t.get("llm_error")}
    reads = {d["number"]: d for d in map(json.loads, open(C.OUT / "deepread.jsonl"))} if (C.OUT / "deepread.jsonl").exists() else {}
    prs = [p for p in load(prs_path) if p["in_window"] and p.get("credited_to") in coarse]
    estimates = {}
    for login in coarse:  # same episode basis as coarse: triaged, non-mechanical PRs
        mine = [tri[p["number"]] for p in prs if p["credited_to"] == login and p["number"] in tri]
        eps = group_episodes([p for p in prs if p["credited_to"] == login and tri.get(p["number"], {}).get("tier") not in (None, "mechanical")])
        estimates[login] = estimate(mine, reads, eps) | {"major_episodes": major_episodes(mine, eps)}
    m = build_matrix(list(coarse), metrics, coarse, estimates, roles)
    (C.OUT / "matrix.json").write_text(json.dumps(m, indent=1, ensure_ascii=False))
    print(f"matrix {m['n']} × {len(COLUMNS)} → out/matrix.json; missing: "
          + ", ".join(f"{c} {len(v)}" for c, v in m["missing"].items() if v))


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else C.PRS)
