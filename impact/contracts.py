"""Required keys per JSON contract (plan §JSON Contracts + review-codex R1). Checks presence and type only."""

REQUIRED = {
    "pr": {"number": int, "author": (str, type(None)), "merged_at": str, "in_window": bool, "files": list, "reviews": list},
    "recall": {"login": str, "metrics": dict, "recalled_by": list},
    "triage": {"number": int, "tier": str, "work_type": str, "summary": str},
    "coarse": {"login": str, "tier_counts": dict, "mass": (int, float), "quality_factor": (int, float), "coarse_score": (int, float), "selected_by": list},
    "deepread": {"number": int, "V": (int, float), "C": (int, float), "N": (int, float), "L": (int, float), "Q": (int, float), "evidence": dict, "verified": dict, "ell": (int, float), "P": (int, float)},
    "refscore": {"login": str, "angles": dict, "R": (int, float)},
    "pairwise": {"a": str, "b": str, "order": str, "winner": str, "reason": str},
    "final": {"top5": list, "next5": list, "method_notes": (str, dict, list)},
    "report": {"cid": str, "positioning": str, "role": dict, "core_contributions": list, "angles": dict, "overall": dict,
               "custom_analyses": list, "calibration": dict, "insights": list, "red_flags": list, "counter_evidence": str, "coverage": dict},
    "decision": {"context_summary": str, "ranking": list, "archetype_groups": list, "top5_cases": list, "sixth_place_note": str,
                 "evidence_requests": list},
    "workstream": {"id": str, "title": str, "area": str, "prs": list, "agg": dict, "top_prs": list, "collaborators": list},
    "role": {"login": str, "top_reviewed": list, "top_reviewers": list, "top_area": (str, type(None)),
             "top_area_share": (int, float, type(None)), "top_area_is_top": (bool, type(None))},
    "matrix": {"n": int, "columns": dict, "rows": list, "missing": dict},
}
TIERS = {"mechanical", "trivial", "routine", "substantive", "major", "landmark"}


def validate(kind: str, obj: dict) -> dict:
    for k, t in REQUIRED[kind].items():
        if k not in obj:
            raise ValueError(f"{kind}: missing {k!r}")
        if not isinstance(obj[k], t):
            raise ValueError(f"{kind}.{k}: expected {t}, got {type(obj[k]).__name__}")
    if kind == "triage" and obj["tier"] not in TIERS:
        raise ValueError(f"triage.tier: {obj['tier']!r}")
    return obj


if __name__ == "__main__":  # python -m impact.contracts <kind> <path.json>: prints OK or the first violation
    import json
    import sys
    kind, path = sys.argv[1:3]
    obj = json.loads(open(path).read())
    try:
        if kind == "report":
            from impact.fine.cards import check_report  # full nested check, not just top-level keys
            check_report(obj)
        else:
            validate(kind, obj)
    except ValueError as e:
        sys.exit(f"INVALID {e}")
    print("OK")

