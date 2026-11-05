"""Four-angle reference scores (spec §9.2, review R2/R11): percentile per signal, unknown stays out of averages."""
from impact import config as C
from impact.contracts import validate

# angle → evidence class → signals. "report:<angle>" = that angle's grade in the L3 report; "-" = lower is better.
SIGNALS = {
    "delivery": {"quant": ["delivery_hat"], "agent": ["report:delivery"],
                 "behavior": ["changelog_weighted", "issue_reactions"]},
    "system": {"quant": ["core_share"], "agent": ["deepread_L", "report:system"],
               "behavior": ["downstream_authors"]},
    "quality": {"quant": ["quality_rate"], "agent": ["deepread_Q", "report:quality"],
                "behavior": ["-changes_requested_rounds"]},
    "team": {"quant": ["review_leverage"], "agent": ["report:team"],
             "behavior": ["comment_line_changed_rate", "review_requesters"]},
}


def percentiles(values: dict[str, float | None]) -> dict[str, float]:
    """0–100 by average rank among known values (ties share the mean rank); None is left out."""
    known = sorted((v, k) for k, v in values.items() if v is not None)
    n, out, i = len(known), {}, 0
    while i < n:
        j = i
        while j + 1 < n and known[j + 1][0] == known[i][0]:
            j += 1
        pct = 50.0 if n == 1 else (i + j) / 2 / (n - 1) * 100
        for _, k in known[i:j + 1]:
            out[k] = pct
        i = j + 1
    return out


def _value(person: dict, report: dict | None, signal: str):
    if signal.startswith("report:"):
        return report["angles"][signal[7:]]["grade"] if report else None
    return person.get(signal.lstrip("-"))


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def combine(angles: dict, weights: dict) -> float | None:
    """Σ w × angle score, renormalized over angles that have a score."""
    have = {a: w for a, w in weights.items() if angles[a] is not None}
    return sum(w * angles[a] for a, w in have.items()) / sum(have.values()) if have else None


def refscore(people: dict[str, dict], reports: dict | None = None) -> list[dict]:
    """people = {login: {signal: raw value or None}}; reports = {login: L3 report} or None (before L3)."""
    reports = reports or {}
    signals = {s for classes in SIGNALS.values() for ss in classes.values() for s in ss}
    raw = {s: {p: _value(people[p], reports.get(p), s) for p in people} for s in signals}
    pct = {s: percentiles(vals) for s, vals in raw.items()}
    for s in pct:
        if s.startswith("-"):
            pct[s] = {p: 100 - v for p, v in pct[s].items()}
    out = []
    for p in people:
        angles = {}
        for angle, classes in SIGNALS.items():
            cls = {c: mean(pct[s].get(p) for s in ss) for c, ss in classes.items()}
            known = [c for c, v in cls.items() if v is not None]
            angles[angle] = {**cls, "score": mean(cls.values()), "coverage": f"{len(known)}/{len(cls)}",
                             "raw": {s.lstrip("-"): raw[s][p] for ss in classes.values() for s in ss}}
        r = combine({a: v["score"] for a, v in angles.items()}, C.ANGLE_WEIGHTS)
        out.append(validate("refscore", {"login": p, "angles": angles, "R": round(r, 2) if r is not None else 0.0,
                                         "R_known": r is not None}))
    return sorted(out, key=lambda x: -x["R"])
