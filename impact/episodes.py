"""Contribution episodes (review-codex R5): splitting one piece of work into many PRs never raises its score."""
import re
from collections import defaultdict
from datetime import datetime, timedelta
from itertools import combinations

from impact import config as C, paths

SCOPE = re.compile(r"^\w+\(([^)]+)\)")


def _info(pr: dict) -> tuple:
    m = SCOPE.match(pr["title"].strip())
    files = {f["path"] for f in pr["files"] if paths.noise(f["path"])[1] > 0}  # lockfiles etc. never link work
    return m and m.group(1).lower(), files, datetime.fromisoformat(pr["merged_at"].replace("Z", "+00:00"))


def _linked(a: tuple, b: tuple) -> bool:
    (sa, fa, _), (sb, fb, _) = a, b
    shared = len(fa & fb)
    return bool(shared) and (shared / len(fa | fb) >= C.EPISODE_FILE_OVERLAP or bool(sa and sa == sb))


def group_episodes(prs: list[dict]) -> list[list[int]]:
    """Same author + (file Jaccard ≥ overlap, or same title scope with a shared file); an episode's whole span
    (first to last merged_at) stays ≤ EPISODE_DAYS, so links never chain past it."""
    parent = list(range(len(prs)))
    info = [_info(p) for p in prs]
    span = [(t, t) for _, _, t in info]  # per root: (first, last) merged_at
    cap = timedelta(days=C.EPISODE_DAYS)

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    by_author = defaultdict(list)
    for i, p in enumerate(prs):
        by_author[p.get("credited_to") or p["author"]].append(i)
    for idx in by_author.values():
        for i, j in combinations(sorted(idx, key=lambda k: info[k][2]), 2):  # time order: deterministic greedy
            ri, rj = find(i), find(j)
            if ri == rj or not _linked(info[i], info[j]):
                continue
            lo, hi = min(span[ri][0], span[rj][0]), max(span[ri][1], span[rj][1])
            if hi - lo <= cap:
                parent[ri] = rj
                span[rj] = (lo, hi)
    groups = defaultdict(list)
    for i, p in enumerate(prs):
        groups[find(i)].append(p["number"])
    return list(groups.values())


def episode_score(points: list[float]) -> float:
    s = sorted(points, reverse=True)
    return s[0] + C.EPISODE_REST_WEIGHT * sum(s[1:]) if s else 0.0
