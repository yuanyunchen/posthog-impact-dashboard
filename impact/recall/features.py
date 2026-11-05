"""Rule-level features for recall: per-PR rule weight and per-person metrics (plan Task 2; review-codex R7, R9, R11).

None means "data not available" (R11), never 0.
"""
import math
import re
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median

import networkx as nx

from impact import config as C, paths

# explicit reference to a PostHog/posthog PR: "#123", "PostHog/posthog#123" or a /pull/123 URL (not "posthog-js#123")
REF = re.compile(r"(?:^|[^\w/.-]|PostHog/posthog)#(\d+)|github\.com/PostHog/posthog/pull/(\d+)", re.I)
REVERT = re.compile(r"^revert\b", re.I)  # PostHog uses both `Revert "…"` and conventional `revert(scope): …`
FIX = re.compile(r"^fix\b", re.I)  # conventional-commit type fix only
EXCLUDE = re.compile(C.FOLLOWUP_EXCLUDE_RE, re.I)
SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
CRITICAL = re.compile(C.CRITICAL_LABEL_RE, re.I)
AI_TOOL = re.compile(C.AI_TOOL_RE, re.I)


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _files(pr: dict) -> tuple[float, float, float, dict]:
    """(lines, mean path weight, weighted core share or None, {area: weighted lines})."""
    raw = eff = core = 0.0
    areas = defaultdict(float)
    for f in pr["files"]:
        n = f["additions"] + f["deletions"]
        w = paths.weight(f["path"]) * n
        raw, eff = raw + n, eff + w
        a, tier, _ = paths.area(f["path"])
        areas[a] += w
        core += w if tier == "core" else 0
    lines = pr["additions"] + pr["deletions"]  # PR totals, so a truncated file list still counts every line
    return lines, (eff / raw if raw else 0.0), (core / eff if eff else None), areas


def pr_rule_weight(pr: dict) -> tuple[float, float | None]:
    """(w_rule, core_share): mean noise×criticality weight of the changed lines × log2(1 + lines)."""
    lines, w, core, _ = _files(pr)
    return w * C.log_lines(lines), core


def reviewable(pr: dict) -> bool:
    """Reviews on human PRs and AI-agent PRs earn team credit (R9); reviews on other bot PRs do not."""
    return not pr["author_is_bot"] or (pr["author"] == C.AI_AGENT_LOGIN and C.AI_AGENT_MARKER in pr["body"])


def refs(pr: dict) -> set[int]:
    """PR numbers referenced explicitly, skipping sentences that say the link is not causal."""
    sents = SENTENCE.split(pr["title"] + "\n" + pr["body"])
    return {int(a or b) for t in sents if not EXCLUDE.search(t) for a, b in REF.findall(t)} - {pr["number"]}


def ai_coauthored(entry: dict | None) -> bool:
    """commit_authors.json entry names an AI tool as co-author (name or email) or in Generated-By."""
    if not entry:
        return False
    names = [x for a in entry.get("co_authors") or [] for x in (a.get("name"), a.get("email"))] + [entry.get("generated_by")]
    return any(n and AI_TOOL.search(n) for n in names)


def _links(prs: list[dict]):
    """(original, repairing PR, is_revert, within FOLLOWUP_DAYS) for every explicit fix/revert reference (R7)."""
    by_num = {p["number"]: p for p in prs}
    for y in prs:
        is_revert, is_fix = bool(REVERT.match(y["title"])), bool(FIX.match(y["title"]))
        if not (is_revert or is_fix):
            continue
        for n in refs(y):
            x = by_num.get(n)
            if x and x["merged_at"] < y["merged_at"]:
                yield x, y, is_revert, _ts(y["merged_at"]) - _ts(x["merged_at"]) <= timedelta(days=C.FOLLOWUP_DAYS)


def quality_events(prs: list[dict]) -> tuple[dict, dict]:
    """({pr: {reverting PRs}}, {pr: {fixing PRs by someone else}}). Only explicit PR references count (R7)."""
    reverted, fixed = defaultdict(set), defaultdict(set)
    for x, y, is_revert, soon in _links(prs):
        if is_revert:
            reverted[x["number"]].add(y["number"])
        elif soon and (y["credited_to"] or y["author"]) != x["credited_to"]:
            fixed[x["number"]].add(y["number"])
    return reverted, fixed


def self_repairs(prs: list[dict]) -> dict:
    """{pr: {PRs by the same author that revert it, or fix it within FOLLOWUP_DAYS}} — reported apart from followups."""
    out = defaultdict(set)
    for x, y, is_revert, soon in _links(prs):
        if x["credited_to"] and y["credited_to"] == x["credited_to"] and (is_revert or soon):
            out[x["number"]].add(y["number"])
    return out


def approvals(pr: dict) -> str:
    """'human' (≥1 human APPROVED), 'ai_only' (approved only by bots such as stamphog) or 'none'."""
    ok = [r for r in pr["reviews"] if r["state"] == "APPROVED"]
    if any(not (r["is_bot"] or C.is_bot(r["author"])) for r in ok):
        return "human"
    return "ai_only" if ok else "none"


def person_metrics(prs: list[dict], changelog: dict | None = None, team_map: dict | None = None,
                   commit_authors: dict | None = None, tiers: dict | None = None) -> dict[str, dict]:
    """tiers = {pr number: triage tier}; None (no triage yet) leaves the major/landmark approval counts None."""
    win = [p for p in prs if p["in_window"]]
    reverted_by, fixed_by = quality_events(prs)
    self_by = self_repairs(prs)
    changelog = None if changelog is None else {str(k) for k in changelog}
    has_requests = any(p.get("review_requests") is not None for p in win)
    has_reactions = any(i["reactions"] is not None for p in win for i in p["closing_issues"])

    authored, weeks = defaultdict(list), defaultdict(set)
    reviewed = defaultdict(dict)  # reviewer -> {pr number: (owner key, first review ts, created_at)}
    requesters = defaultdict(set)
    for p in win:
        o = p["credited_to"]  # None for bot PRs and unattributed AI-agent PRs (R9)
        if o:
            authored[o].append(p)
            weeks[o].add(_ts(p["merged_at"]).isocalendar()[:2])
        if not reviewable(p):
            continue
        okey = o or p["author"]
        for r in p["reviews"]:
            a = r["author"]
            if r["is_bot"] or C.is_bot(a) or a == okey:
                continue
            prev = reviewed[a].get(p["number"])
            if not prev or r["submitted_at"] < prev[1]:
                reviewed[a][p["number"]] = (okey, r["submitted_at"], p["created_at"])
            weeks[a].add(_ts(r["submitted_at"]).isocalendar()[:2])
        for rq in p.get("review_requests") or []:
            req, rev = (okey, rq) if isinstance(rq, str) else (rq.get("requester"), rq.get("reviewer"))
            if req and rev and req != rev and not C.is_bot(req) and not C.is_bot(rev):
                requesters[rev].add(req)

    # author -> reviewer graph; unattributed AI PRs have no human owner and stay out (bots excluded)
    g = nx.DiGraph()
    g.add_nodes_from(set(authored) | set(reviewed))
    for rev, seen in reviewed.items():
        for okey, _, _ in seen.values():
            if okey in g and okey != rev:
                w = g.get_edge_data(okey, rev, {"weight": 0})["weight"]
                g.add_edge(okey, rev, weight=w + 1)
    pagerank = nx.pagerank(g, weight="weight") if g.number_of_nodes() else {}

    out = {}
    for login in sorted(set(authored) | set(reviewed)):
        mine, rv = authored[login], reviewed[login]
        w_sum = eff = core_eff = core_w = max_core_w = 0.0
        areas = set()
        for p in mine:
            lines, w, core, ar = _files(p)
            wr = w * C.log_lines(lines)
            w_sum += wr
            eff += w * lines
            core_eff += (core or 0) * w * lines
            core_w += wr * (core or 0)
            max_core_w = max(max_core_w, wr * (core or 0))
            areas |= {a for a, v in ar.items() if v > 0}
        mature = [p["number"] for p in mine if p["merged_at"] <= C.MATURE_CUTOFF]
        rev_set = {n for n in mature if n in reverted_by}
        fix_set = {n for n in mature if n in fixed_by} - rev_set  # one affected PR is counted once
        served = {o for o, _, _ in rv.values()}
        selfrep = {n for n in mature if n in self_by}
        appr = [approvals(p) for p in mine]
        big = None if tiers is None else [approvals(p) for p in mine if tiers.get(p["number"]) in ("major", "landmark")]
        ai = None if commit_authors is None else {p["number"] for p in mine if ai_coauthored(commit_authors.get(str(p["number"])))}
        waits = [(_ts(t) - _ts(c)).total_seconds() / 3600 for _, t, c in rv.values()]
        out[login] = {
            "prs": len(mine),
            "ai_prs": sum(p["ai_assisted"] for p in mine),
            "eff_lines": round(eff, 1),
            "w_rule_sum": round(w_sum, 3),
            "core_w_rule": round(core_w, 3),
            "max_core_w_rule": round(max_core_w, 3),
            "core_share": round(core_eff / eff, 3) if eff else None,
            "areas": len(areas),
            "active_weeks": len(weeks[login]),
            "reviews_given": len(rv),
            "authors_served": len(served),
            "team_leverage": round(len(rv) * math.log(1 + len(served)), 3),
            "first_review_median_h": round(median(waits), 2) if waits else None,
            "review_requested_by": len(requesters[login]) if has_requests else None,
            "pagerank": round(pagerank.get(login, 0.0), 6),
            "mature_prs": len(mature),
            "reverted": len(rev_set) if mature else None,
            "followup_fixed": len(fix_set) if mature else None,
            "affected_prs": sorted(rev_set | fix_set),
            # rule-level q over all mature PRs; coarse recomputes with the substantive+ denominator (R7)
            "quality_q": round(1 - len(rev_set | fix_set) / len(mature), 3) if mature else None,
            "ai_coauthored_prs": None if ai is None else len(ai),
            "ai_share": round(len(ai) / len(mine), 3) if ai is not None and mine else None,
            "ai_reverted_or_fixed": None if ai is None else len(ai & (rev_set | fix_set)),
            "self_repaired_prs": len(selfrep) if mature else None,
            "self_repair_rate": round(len(selfrep) / len(mature), 3) if mature else None,
            "human_approved_prs": appr.count("human"),
            "ai_only_approved_prs": appr.count("ai_only"),
            "no_approval_prs": appr.count("none"),
            "human_approved_major_prs": None if big is None else big.count("human"),
            "ai_only_approved_major_prs": None if big is None else big.count("ai_only"),
            "no_approval_major_prs": None if big is None else big.count("none"),
            "changelog_prs": None if changelog is None else sum(str(p["number"]) in changelog for p in mine),
            "critical_prs": sum(any(CRITICAL.search(l) for l in p["labels"]) for p in mine),
            "issue_reactions": sum(i["reactions"] or 0 for p in mine for i in p["closing_issues"]) if has_reactions else None,
            "team": None if team_map is None else team_map.get(login),
        }
    return out


def rule_metrics_for(logins, prs: list[dict], changelog: dict | None = None, team_map: dict | None = None,
                     commit_authors: dict | None = None, tiers: dict | None = None) -> dict[str, dict | None]:
    """Metrics for chosen people (e.g. audit additions). Computed over all PRs because PageRank is global; None = no activity."""
    m = person_metrics(prs, changelog, team_map, commit_authors, tiers)
    return {l: m.get(l) for l in logins}
