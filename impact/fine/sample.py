"""Stratified random sample for deep read and the stratified delivery estimate (review-codex R8)."""
import random
from statistics import mean

from impact import config as C
from impact.episodes import episode_score

STRATUM = {"landmark": "major+landmark", "major": "major+landmark",
           "substantive": "substantive", "routine": "routine", "trivial": "trivial"}  # mechanical: never read, always 0


def _strata(person_triage: list[dict]) -> dict[str, list[dict]]:
    out = {}
    for t in person_triage:
        if s := STRATUM.get(t["tier"]):
            out.setdefault(s, []).append(t)
    return out


def stratified_sample(person_triage: list[dict], seed: int = C.SEED) -> dict[str, list[int]]:
    """Uniform random draw inside each stratum, up to SAMPLE_PER_STRATUM; one RNG per stratum so strata stay independent."""
    out = {}
    for s, members in _strata(person_triage).items():
        pool = sorted(t["number"] for t in members)
        out[s] = sorted(random.Random(f"{seed}-{s}").sample(pool, min(C.SAMPLE_PER_STRATUM[s], len(pool))))
    return out


def estimate(person_triage: list[dict], deepread_by_pr: dict[int, dict], episodes: list[list[int]] | None = None) -> dict:
    """delivery_hat (canonical, R8 last bullet) = Σ episode_score over episodes, where a read PR's P replaces its tier
    points; episodes=None means every PR is its own episode. delivery_stratified = Σ_stratum N × mean(P | sample),
    an unsampled stratum falling back to its tier points (flagged). L, Q = N-weighted mean of stratum means.
    calib_diff = mean P − mean tier points of the same sampled PRs."""
    strata, delivery, lq = {}, 0.0, {"L": [], "Q": []}
    for s, members in _strata(person_triage).items():
        read = [(t, deepread_by_pr[t["number"]]) for t in members
                if t["number"] in deepread_by_pr and not deepread_by_pr[t["number"]].get("llm_error")]
        n = len(members)
        if read:
            row = {"N": n, "n": len(read), "fallback": False,
                   "mean_P": mean(d["P"] for _, d in read),
                   "tier_mean": mean(C.TIER_POINTS[t["tier"]] for t, _ in read),
                   "mean_L": mean(d["L"] for _, d in read), "mean_Q": mean(d["Q"] for _, d in read)}
            row["calib_diff"] = row["mean_P"] - row["tier_mean"]
            for k in lq:
                lq[k].append((n, row[f"mean_{k}"]))
        else:
            row = {"N": n, "n": 0, "fallback": True, "mean_P": mean(C.TIER_POINTS[t["tier"]] for t in members),
                   "tier_mean": None, "mean_L": None, "mean_Q": None, "calib_diff": None}
        delivery += n * row["mean_P"]
        strata[s] = row
    # per-PR points for episodes (R8): a read PR's P replaces its tier points
    points = {t["number"]: (deepread_by_pr[t["number"]]["P"]
                            if t["number"] in deepread_by_pr and not deepread_by_pr[t["number"]].get("llm_error")
                            else C.TIER_POINTS[t["tier"]]) for t in person_triage if t["tier"] in C.TIER_POINTS}
    if episodes is None:
        episodes = [[n] for n in points]
    out = {"delivery_hat": sum(episode_score([points[x] for x in ep if x in points]) for ep in episodes),
           "delivery_stratified": delivery, "strata": strata,
           "mechanical": sum(t["tier"] == "mechanical" for t in person_triage),
           "llm_errors": sum(bool(deepread_by_pr.get(t["number"], {}).get("llm_error")) for t in person_triage),
           "points": points,
           **{k: (sum(n * v for n, v in w) / sum(n for n, _ in w) if w else None) for k, w in lq.items()}}
    return out
