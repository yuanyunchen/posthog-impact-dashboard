"""Stage outputs → site/site_data.json for the dashboard (docs/superpowers/specs/2026-11-03-dashboard-content.md).

Every artifact is read from out_dir first, then from the dev fixture dir out/; the file actually used is recorded in
meta.sources. Without final.json the page renders a "decision pending" state (meta.decision_state).
"""
import asyncio
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from impact import config as C
from impact.fine.refscore import SIGNALS, percentiles

ROOT = C.ROOT
DEV_OUT = ROOT / "out"
PR_URL = "https://github.com/PostHog/posthog/pull/{}"
IMPACT = ("Impact = durable change to PostHog's product, systems and team, traceable to specific PRs, "
          "judged by quality and importance over volume.")
ANGLES = ("delivery", "system", "quality", "team")
ANCHORS = "9–10 company-critical or benefits many teams · 7–8 core pillar of the team · 5–6 steady effective contribution · 3–4 local contribution · 1–2 marginal"

# label, formula, source for keys whose formula is not already carried by an input file
DEFS = {
    "grade.delivery": ("Delivery grade", "L3 evaluator grade 1–10: user value, criticality (outage, data correctness, security, billing), novelty. " + ANCHORS, "L3 report.angles.delivery.grade"),
    "grade.system": ("System grade", "L3 evaluator grade 1–10: abstractions, platforms, tooling, performance; whether others build on his code. " + ANCHORS, "L3 report.angles.system.grade"),
    "grade.quality": ("Quality grade", "L3 evaluator grade 1–10: reverts, fixes by others, change-request rounds, risk control. " + ANCHORS, "L3 report.angles.quality.grade"),
    "grade.team": ("Team grade", "L3 evaluator grade 1–10: reviews that catch real problems, adopted suggestions, review requests, network position. " + ANCHORS, "L3 report.angles.team.grade"),
    "grade.overall": ("Overall grade", "L3 evaluator overall grade 1–10 with confidence. " + ANCHORS, "L3 report.overall"),
    "R": ("Reference score R", "0.50·delivery + 0.20·system + 0.15·quality + 0.15·team; each angle = mean of its quant / agent / behaviour percentiles among candidates (0–100); unknown signals left out", "refscore.R"),
    "R_rank": ("Rank by R", "position when candidates are sorted by R alone", "final.top5[].R_rank"),
    "borda": ("Borda points", "sum over rankers of (11 − rank) for ranks 1–10; ties broken by pairwise wins", "final.top5[].borda"),
    "stability_freq": ("Weight robustness", f"share of {C.SENS_DRAWS} draws (each angle weight × U(0.5, 1.5), renormalized) in which he is top 5 by R; ≥{C.STABLE_MIN:.0%} stable, {C.BORDERLINE_MIN:.0%}–{C.STABLE_MIN:.0%} borderline, below = verdict only", "final.top5[].stability_freq"),
    "gate.a": ("Gate (a): substance", f"≥{C.GATE_MIN_MAJOR} major-tier PRs or ≥{C.GATE_MIN_LANDMARK} landmark, or team leverage in the candidates' top {C.GATE_TEAM_TOP}", "final.top5[].gates.a"),
    "gate.b": ("Gate (b): no quality red flag", f"reverted < {C.GATE_MAX_REVERTED} times and follow-up-fix rate not in the candidates' worst 20%", "final.top5[].gates.b"),
    "gate.c": ("Gate (c): ranker agreement", f"at least 2/3 of rankers place him in their top {C.GATE_TOP7}", "final.top5[].gates.c"),
    # refscore signals (impact/fine/refscore.py SIGNALS)
    "delivery_hat": ("Delivery estimate", "Σ over contribution episodes of (max PR points + 0.25 × the rest); deep-read P replaces tier points on sampled PRs", "refscore input / estimates.delivery_hat"),
    "changelog_weighted": ("Changelog entries (weighted)", "his PRs cited in the public PostHog changelog, weighted by entry prominence", "refscore input"),
    "issue_reactions": ("Issue reactions", "👍 reactions on issues his PRs close", "refscore input"),
    "core_share": ("Core-path share", "share of his rule-weighted lines in core areas (query engine, ingestion, data layer, platform)", "recall metrics.core_share"),
    "deepread_L": ("Deep-read leverage", "mean LLM leverage score L (0–3) over his deep-read PRs", "out/deepread.jsonl"),
    "deepread_Q": ("Deep-read quality", "mean LLM quality score Q (0–3) over his deep-read PRs", "out/deepread.jsonl"),
    "changes_requested_rounds": ("Change-request rounds", "mean CHANGES_REQUESTED reviews per PR of his (lower is better)", "team_graph"),
    "review_leverage": ("Review leverage", "human reviews given × ln(1 + distinct authors served)", "recall metrics.team_leverage"),
    "comment_line_changed_rate": ("Comments acted on", "share of his review comments whose line changed afterwards", "review_detail"),
    "downstream_authors": ("Later authors of the same files", "distinct authors who later changed, by ≥20 lines, a source file he had changed (hub files excluded); co-location, not proof of reuse", "refscore input / team_graph"),
    "quality_rate": ("Quality rate", "1 − (reverted or explicitly follow-up-fixed PRs) / mature PRs triaged substantive or above", "refscore input / coarse.q"),
    "review_requesters": ("Review requesters", "distinct humans who requested his review", "team_graph"),
    # coarse
    "tier_points": ("Tier points", ", ".join(f"{t} {p}" for t, p in C.TIER_POINTS.items()) + " (mechanical excluded)", "impact/config.py TIER_POINTS"),
    "mass": ("Importance mass", f"Σ over episodes of (max tier points + {C.EPISODE_REST_WEIGHT} × rest); an episode = his PRs within {C.EPISODE_DAYS} days sharing ≥{C.EPISODE_FILE_OVERLAP:.0%} of files", "coarse.mass"),
    "quality_factor": ("Quality factor", "max(0.5, quality rate); 1.0 when unknown", "coarse.quality_factor"),
    "team_score": ("Team score", "human reviews given × ln(1 + distinct authors served)", "coarse.team_score"),
    "coarse_score": ("Coarse score", "importance mass × quality factor", "coarse.coarse_score"),
    "episodes": ("Episodes", f"clusters of his PRs within {C.EPISODE_DAYS} days sharing ≥{C.EPISODE_FILE_OVERLAP:.0%} of files", "coarse.episodes"),
    "selected_by": ("Selected by", f"score = top {C.COARSE_TOP_SCORE} by coarse score; team = top {C.COARSE_TOP_TEAM} by team score; fill = topped up to {C.COARSE_N} in score order", "coarse.selected_by"),
    "q": ("Quality rate", "1 − (reverted or explicitly follow-up-fixed PRs) / mature PRs triaged substantive or above", "coarse.q"),
    # funnel
    "people": ("Contributors", "humans with ≥1 window PR authored or reviewed (bots and AI-agent PRs removed)", "recall_stats.people"),
    "graph_people": ("People in the review graph", "contributors with at least one collaboration edge (approval, comment, change request, review request, continued work, follow-up fix or revert) in the window", "team_graph.summary.people"),
    "eligible": ("Above activity floor", f"≥{C.ACTIVITY_MIN_PRS} merged PRs or ≥{C.ACTIVITY_MIN_REVIEWS} reviews, or exempt by changelog / critical / core-spike PR", "recall_stats.eligible"),
    "recalled": ("Recalled", "union of the recall routes below", "recall_stats.recalled"),
    "route.delivery": ("Route: delivery", f"top {C.RECALL_TOP_DELIVERY} by rule-weighted lines (path weight × area criticality)", "recall_stats.route_hits.delivery"),
    "route.team": ("Route: team", f"top {C.RECALL_TOP_TEAM} by team leverage", "recall_stats.route_hits.team"),
    "route.system": ("Route: system", f"top {C.SYSTEM_ROUTE_TOP} by core-path rule weight", "recall_stats.route_hits.system"),
    "route.changelog": ("Route: changelog", "any PR cited in the public changelog", "recall_stats.route_hits.changelog"),
    "route.critical": ("Route: critical", "any PR labelled incident / security / billing / hotfix", "recall_stats.route_hits.critical"),
    "coarse_n": ("Coarse shortlist", f"{C.COARSE_TOP_SCORE} by coarse score + {C.COARSE_TOP_TEAM} by team score, topped up to {C.COARSE_N}", "coarse.json"),
    "final_n": ("Final", "L3 evaluator per candidate → 2 independent L4 rankings → devil's advocate → gates", "final.json"),
    "audit": ("Recall audit", "random sample of PRs by unrecalled authors, triaged; any major/landmark PR flags a missed engineer", "recall_audit_sample.json"),
    "review_coverage": ("Review-detail coverage", f"review comments, threads and review requests were fetched for at most {C.REVIEW_DETAIL_AUTHORED_CAP} PRs he authored and {C.REVIEW_DETAIL_REVIEWED_CAP} PRs he reviewed (ranked by tier points, then recency) plus his deep-read sample; comment-based metrics use only those PRs", "review_coverage.json"),
    "ai_only_approved": ("AI-only approvals", "window PRs whose APPROVED reviews all came from bot reviewers / all window PRs (and / human-authored PRs)", "data/prs.jsonl reviews"),
    "audit_round": ("Audit and correction", "an independent audit re-checked every input against the raw PR data; fixes were applied and all candidates re-decided", "published.json _method"),
    "decision_agreement": ("Decision agreement", "two decision agents ranked the 20 independently (the second blind to the first); overlap of their top 5, Kendall τ over the full ranking, and pairwise re-checks asked in both presentation orders (consistent = same winner both times)", "final.json method_notes + decision/pairwise"),
    "fetch_reconciliation": ("Fetch reconciliation", "for every day in the window, merged PRs fetched = GitHub search count for that day", "validation.json fetch"),
    "quote_check": ("Quote verification", "every evidence quote an LLM cites must be a verbatim substring of the PR title, body, diff or review text; a failed quote lowers that sub-score by 1", "validation.json quote_check"),
    "llm_cost": ("LLM cost", "sum of billed DeepSeek calls across all stages, development runs included; the Claude evaluator and ranker agents are not billed per call and are not in this figure", "validation.json llm_cost_usd"),
    "bot_prs": ("Bot PRs", "author is a GitHub Bot, login contains [bot], or a known automation login (impact/config.py BOT_LOGINS)", "data/prs.jsonl author_is_bot"),
    "ai_agent_prs": ("AI-agent PRs", "author 'posthog' with posthog-self-driving-origin in body; credited to a human only when one is identifiable", "data/prs.jsonl ai_assisted"),
}
MATRIX_LABELS = {
    "delivery": "Delivery estimate", "major_episodes": "Major+ episodes", "quality_rate": "Quality rate",
    "team_leverage": "Team leverage", "requested_by": "Review requesters", "downstream_authors": "Later authors of the same files",
    "cross_team": "Teams approved for", "changelog_prs": "Changelog PRs", "ai_share": "AI co-authored share",
    "self_driving_share": "AI-agent PR share", "first_pass_rate": "First-pass rate",
    "changes_requested_rate": "Changes-requested rate", "trust_rank": "Approval-network centrality", "importance_flow": "Importance flow",
}
NETWORK_LABELS = {
    "first_pass_rate": "First-pass rate", "changes_requested_rate": "Changes-requested rate",
    "changes_rounds_mean": "Change rounds (mean)", "changes_adopted_rate": "Change-request resolution (proxy)",
    "approved_authors_n": "Authors he approved", "teams_covered_n": "Teams he approved for",
    "requested_by_n": "Requested as reviewer by", "built_on_by_n": "Later authors of the same files",
    "fixes_given": "Fixes for others", "fixes_received": "Fixed by others",
    "reverts_given": "Reverts of others", "reverts_received": "Reverted by others",
    "trust_rank": "Approval-network centrality", "importance_flow": "Importance flow",
}


# key → (unit, one plain-English line shown under the number; the full formula stays in the tooltip)
PLAIN = {
    "delivery": ("pts", "importance-weighted points of shipped work (1–16 per PR, related PRs grouped)"),
    "delivery_hat": ("pts", "importance-weighted points of shipped work (1–16 per PR, related PRs grouped)"),
    "major_episodes": ("", "pieces of work containing at least one major or landmark PR"),
    "quality_rate": ("%", "his substantial PRs never reverted or fixed by someone else"),
    "q": ("%", "his substantial PRs never reverted or fixed by someone else"),
    "team_leverage": ("", "reviews he gave, weighted by how many different authors he served"),
    "review_leverage": ("", "reviews he gave, weighted by how many different authors he served"),
    "requested_by": ("people", "different people who asked him for a review"),
    "review_requesters": ("people", "different people who asked him for a review"),
    "downstream_authors": ("authors", "other engineers who later changed files he had changed"),
    "cross_team": ("teams", "teams whose PRs he approved"),
    "changelog_prs": ("PRs", "his PRs cited in PostHog's public changelog"),
    "ai_share": ("%", "his PRs co-written with an AI assistant"),
    "self_driving_share": ("%", "his PRs opened by PostHog's AI agent on his behalf"),
    "first_pass_rate": ("%", "his reviewed PRs approved with no change request"),
    "changes_requested_rate": ("%", "his reviewed PRs that got a change request (lower is better)"),
    "trust_rank": ("", "approval-network centrality: PageRank of who approves whom"),
    "importance_flow": ("pts", "PR importance credited to him as author or substantive reviewer"),
    "changelog_weighted": ("", "changelog mentions of his PRs, weighted by prominence"),
    "issue_reactions": ("reactions", "👍 on the issues his PRs closed"),
    "core_share": ("%", "share of his work in core systems (query engine, ingestion, data layer)"),
    "deepread_L": ("/3", "leverage of his sampled PRs as judged by a model reading the diff"),
    "deepread_Q": ("/3", "quality of his sampled PRs as judged by a model reading the diff"),
    "changes_requested_rounds": ("rounds", "change-request rounds per PR (lower is better)"),
    "comment_line_changed_rate": ("%", "his review comments whose line was changed afterwards"),
}


def _ranks(vals: dict, lower: bool) -> dict:
    """login → {rank, of}: 1 + number of people strictly better; unknown values get no rank."""
    known = [v for v in vals.values() if v is not None]
    return {l: {"rank": 1 + sum((x < v) if lower else (x > v) for x in known), "of": len(known),
                "tied": known.count(v) > 1} for l, v in vals.items() if v is not None}


class Sources:
    def __init__(self, out_dir: Path):
        self.dirs, self.used, self.fallback = [out_dir, DEV_OUT] if out_dir.resolve() != DEV_OUT.resolve() else [out_dir], {}, []

    def path(self, name: str) -> Path | None:
        for d in self.dirs:
            if (d / name).exists():
                self.used[name] = str((d / name).relative_to(ROOT)) if (d / name).is_relative_to(ROOT) else str(d / name)
                if d != self.dirs[0]:
                    self.fallback.append(name)
                return d / name
        return None

    def json(self, name: str):
        p = self.path(name)
        return json.loads(p.read_text()) if p else None

    def jsonl(self, name: str) -> list | None:
        p = self.path(name)
        return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p else None


WINDOW_WEEKS = 13  # 91-day window in 7-day bins from WINDOW_START (day 91 folds into the last bin)


def _exclusions(prs_path: Path) -> tuple[dict | None, dict]:
    """(window counts, per credited login {issues: closed issue numbers, weeks: active 7-day bins})."""
    if not prs_path.exists():
        return None, {}
    c, per = Counter(), {}
    start = datetime.fromisoformat(C.WINDOW_START.replace("Z", "+00:00"))
    with prs_path.open() as f:
        for line in f:
            p = json.loads(line)
            if not p.get("in_window"):
                continue
            c["merged_prs"] += 1
            c["bot_prs"] += bool(p.get("author_is_bot"))
            ai = bool(p.get("ai_assisted"))
            c["ai_agent_prs"] += ai
            c["ai_agent_credited"] += ai and bool(p.get("credited_to"))
            ap = [r for r in p.get("reviews") or [] if r.get("state") == "APPROVED"]
            ai_only = bool(ap) and all(r.get("is_bot") for r in ap)
            c["ai_only_approved"] += ai_only
            c["human_authored"] += not p.get("author_is_bot")
            c["ai_only_approved_human_authored"] += ai_only and not p.get("author_is_bot")
            if p.get("credited_to") and p.get("merged_at"):
                d = per.setdefault(p["credited_to"], {"issues": set(), "weeks": set()})
                d["issues"].update(i["number"] for i in p.get("closing_issues") or [])
                wk = (datetime.fromisoformat(p["merged_at"].replace("Z", "+00:00")) - start).days // 7
                d["weeks"].add(min(max(wk, 0), WINDOW_WEEKS - 1))
    return dict(c), per


# Card facts (spec §H): raw, checkable counts only — never weighted scores (delivery points, leverage, PageRank).
# key: (group, trait, lower_is_better, label, definition)
FACTS = {
    "merged_prs": ("volume", "Prolific shipper", False, "merged PRs in the 90 days", "his merged PRs in the window (bots and AI-agent PRs excluded)"),
    "major_prs": ("volume", "Big-change shipper", False, "PRs rated major or landmark", "his PRs that LLM triage rated major (8 pts) or landmark (16 pts)"),
    "active_weeks": ("volume", "Steady shipper", False, "weeks with a merged PR", f"7-day bins of the window (of {WINDOW_WEEKS}) with at least one of his PRs merged"),
    "revert_rate": ("quality", "High-quality shipper", True, "his PRs that were reverted", "reverted PRs / merged PRs; a revert must explicitly reference his PR"),
    "fixed_share": ("quality", "High-quality shipper", True, "his PRs later fixed by someone else", "PRs fixed by another engineer within 14 days (explicit reference) / merged PRs"),
    "first_pass": ("quality", "High-quality shipper", False, "first-pass approval", "his reviewed PRs approved with no change request first"),
    "reviews_given": ("review", "Review backbone", False, "reviews given to other authors", "human reviews he gave on others' PRs, and the distinct authors they went to"),
    "requested_by": ("review", "Go-to reviewer", False, "people who asked for his review", "distinct humans who requested his review (fetched review requests only)"),
    "teams_covered": ("review", "Review backbone", False, "teams whose PRs he approved", "distinct teams (official team map) of the authors he approved"),
    "built_on_by": ("foundation", "Foundation builder", False, "later authors of the same files", "distinct authors who later changed, by ≥20 lines, a source file he had changed (shared hub files excluded)"),
    "changelog": ("user", "User-visible shipper", False, "PRs in the public changelog", "his window PRs cited in PostHog's public changelog"),
    "issues_closed": ("user", "Issue closer", False, "issues closed by his PRs", "distinct GitHub issues his merged PRs closed"),
}
WEIGHTED_KEYS = {"delivery", "delivery_hat", "team_leverage", "review_leverage", "trust_rank", "pagerank", "importance_flow",
                 "mass", "coarse_score", "team_score", "R"}


def _fact_values(login: str, metrics: dict, coarse_row: dict, person: dict, scan: dict) -> dict:
    """fact key → (sort value, value_text[, label]); a fact without data is left out."""
    nv = lambda k: (person.get(k) or {}).get("value")
    prs, out = metrics.get("prs"), {}
    if prs:
        out["merged_prs"] = (prs, f"{prs:,} PRs")
        if metrics.get("reverted") is not None:
            out["revert_rate"] = (metrics["reverted"] / prs, f'{metrics["reverted"]} revert{"s" * (metrics["reverted"] != 1)} in {prs:,} PRs')
        if metrics.get("followup_fixed") is not None:
            out["fixed_share"] = (metrics["followup_fixed"] / prs, f'{metrics["followup_fixed"]} fixed by others in {prs:,} PRs')
    tc = (coarse_row or {}).get("tier_counts")
    if tc:
        n = tc.get("major", 0) + tc.get("landmark", 0)
        out["major_prs"] = (n, f"{n:,} major PRs")
    if login in scan:
        w, i = len(scan[login]["weeks"]), len(scan[login]["issues"])
        out["active_weeks"] = (w, f"{w}/{WINDOW_WEEKS} weeks")
        out["issues_closed"] = (i, f"{i:,} issues closed")
    if nv("first_pass_rate") is not None:
        v = nv("first_pass_rate")
        out["first_pass"] = (v, "100% first-pass" if v == 1 else f"{v:.1%} first-pass" if v >= .99 else f"{v:.0%} first-pass")
    if metrics.get("reviews_given") is not None:
        out["reviews_given"] = (metrics["reviews_given"], f'{metrics["reviews_given"]:,} reviews',
                                f'reviews given to {metrics.get("authors_served") or 0} other authors')
    for k, src, unit in (("requested_by", "requested_by_n", "people"), ("teams_covered", "teams_covered_n", "teams"),
                         ("built_on_by", "built_on_by_n", "authors")):
        if nv(src) is not None:
            out[k] = (nv(src), f"{nv(src):,} {unit}")
    if metrics.get("changelog_prs") is not None:
        out["changelog"] = (metrics["changelog_prs"], f'{metrics["changelog_prs"]:,} changelog PRs')
    return out


def key_facts(values: dict[str, dict]) -> dict[str, list]:
    """values = {login: _fact_values(...)} over the shortlist → {login: 3 facts}: highest percentile first, at most one
    per group; a zero count is never a highlight (zero reverts is, since lower is better)."""
    pct, rank = {}, {}
    for k, (_, _, lower, _, _) in FACTS.items():
        vals = {l: v[k][0] for l, v in values.items() if k in v}
        p = percentiles(vals)
        pct[k] = {l: 100 - x if lower else x for l, x in p.items()}
        rank[k] = _ranks(vals, lower)
    out = {}
    for l, v in values.items():
        cand = sorted(((pct[k][l], -list(FACTS).index(k), k) for k in v
                       if l in pct[k] and (FACTS[k][2] or v[k][0])), reverse=True)
        picked, groups = [], set()
        # pass 1: one per group, upper half only; pass 2: fill from the rest of the upper half; pass 3: best remaining
        for ok in (lambda p, g: p >= 50 and g not in groups, lambda p, g: p >= 50, lambda p, g: True):
            for p, _, k in cand:
                g, trait, _, label, _ = FACTS[k]
                if len(picked) == 3 or any(x["metric_key"] == f"f.{k}" for x in picked) or not ok(p, g):
                    continue
                groups.add(g)
                picked.append({"metric_key": f"f.{k}", "label": v[k][2] if len(v[k]) > 2 else label, "value_text": v[k][1], "value": v[k][0],
                               "pct": round(p, 1), "trait": trait, **rank[k].get(l, {})})
        out[l] = picked
    return out


PENDING = {"top5": [], "next5": [], "method_notes": {}}


TAGS_SYSTEM = (
    "You label an engineer for a dashboard card read by an engineering leader. Return JSON {\"tags\": [...]} with 2 or 3 tags. "
    "Each tag is at most 3 words, in English, sentence case, and names something distinctive about THIS person: a system or "
    "product area they own, or a kind of work they are known for (e.g. \"Security owner\", \"CSP rollout\", \"Incident response\", "
    "\"Pipeline firefighter\", \"Storage migration\"). Never repeat the team name. Never use generic labels such as "
    "\"Platform builder\", \"Product engineer\", \"High impact\" or \"Team player\". Use only facts in the input.")


def _llm_each(stage: str, system: str, items: dict[str, dict]) -> dict[str, dict]:
    """One cached DeepSeek Flash call per item (impact.llm, cache key = stage + login + prompt), so rebuilds are free.
    No key / no network → {} and a note on stderr; the page then renders without that element."""
    from impact import llm
    jobs = [(l, system, json.dumps(v, ensure_ascii=False)) for l, v in items.items()]
    try:
        outs = asyncio.run(llm.run_all(stage, jobs))
    except Exception as e:
        print(f"{stage}: LLM unavailable ({type(e).__name__}: {e}); rendering without it", file=sys.stderr)
        return {}
    for (l, _, _), o in zip(jobs, outs):
        if o.get("llm_error"):
            print(f"{stage}: {l}: {o['llm_error']}", file=sys.stderr)
    return {l: o for (l, _, _), o in zip(jobs, outs)}


KEYPOINTS_SYSTEM = (
    "You write the key points on an engineer's dashboard card. Input: his core contributions (title, outcome, numbers). "
    "Return JSON {\"points\": [...]} with 2 or 3 points, one per contribution, most important first. Each point is ONE "
    "complete, self-contained phrase of at most 9 words, outcome-oriented, starting with a past-tense verb, e.g. "
    "\"Fixed fleet-wide sync stalls and duplicate rows\" or \"Shipped credentials service across 21 products\". "
    "Say what changed for users, customers or other teams, not how it was scored: never mention points, pts, scores, tiers, "
    "percentiles or PR counts, and never write identifiers with underscores. Use only facts in the input; every number you "
    "write must appear in the input (a user-facing magnitude such as \"544 KB to 10 KB\" or \"21 products\" is good). "
    "No ellipsis, no PR numbers.")


def candidate_keypoints(items: dict[str, dict]) -> dict[str, list[str]]:
    """items = {login: {contributions: [{title, outcome, numbers}]}} → {login: 2–3 points ≤9 words} (stage "keypoints").
    A point over 9 words, with an ellipsis, or with a number absent from the input is dropped, never cut."""
    out = {}
    for l, o in _llm_each("keypoints", KEYPOINTS_SYSTEM, items).items():
        src_nums = set(re.findall(r"\d+(?:[.,]\d+)?", json.dumps(items[l], ensure_ascii=False)))
        ok = lambda t: (isinstance(t, str) and 0 < len(t.split()) <= 9 and "…" not in t and "..." not in t
                        and set(re.findall(r"\d+(?:[.,]\d+)?", t)) <= src_nums
                        and not re.search(r"\b(pts?|points?|scor\w*|tiers?|percentile)\b|_|#\d", t, re.I))
        out[l] = [t.strip().rstrip(".") for t in (o.get("points") or []) if ok(t)][:3]
    return out


def candidate_tags(items: dict[str, dict]) -> dict[str, list[str]]:
    """items = {login: {team, role, positioning, contribution_titles}} → {login: 2–3 tags} (stage "tags");
    tags over 3 words or repeating the team name are dropped."""
    norm = lambda t: re.sub(r"[-_\s]+", " ", (t or "").lower()).strip()
    out = {}
    for l, o in _llm_each("tags", TAGS_SYSTEM, items).items():
        team = norm(items[l].get("team"))
        tags = [t.strip() for t in (o.get("tags") or []) if isinstance(t, str) and t.strip()]
        out[l] = [t for t in tags if len(t.split()) <= 3 and not (team and (team in norm(t) or norm(t) in team))][:3]
    return out


# Approval-type and self-repair metrics from recall.json (added after the round-1 audit), shown in the drawer.
APPROVAL_KEYS = {
    "human_approved_prs": ("PRs approved by a human", "his merged PRs with at least one human APPROVED review"),
    "ai_only_approved_prs": ("PRs approved only by an AI bot", "his merged PRs whose only approvals came from bot reviewers"),
    "no_approval_prs": ("PRs merged with no approval", "his merged PRs with no APPROVED review at all"),
    "human_approved_major_prs": ("Major PRs approved by a human", "his major/landmark PRs with at least one human approval"),
    "ai_only_approved_major_prs": ("Major PRs approved only by an AI bot", "his major/landmark PRs whose only approvals came from bots"),
    "no_approval_major_prs": ("Major PRs merged with no approval", "his major/landmark PRs with no APPROVED review"),
    "self_repaired_prs": ("PRs he later repaired himself", "his PRs that a later PR of his own explicitly fixed (invisible to the follow-up-fix metric, which counts only others)"),
    "self_repair_rate": ("Self-repair rate", "self-repaired PRs / merged PRs"),
}


CID_RE = re.compile(r"\bC\d{2}\b")

# Agent texts quote internal field names ("role.team_inferred", "quality_rate", "P=16.0", "P76", "ws3"); readers see plain words.
_KEY_WORDS = {
    "quality_rate": "quality rate", "trust_rank": "approval-network centrality", "team_leverage": "team leverage", "review_leverage": "review leverage",
    "first_pass_rate": "first-pass rate", "built_on_by_n": "later authors of the same files", "built_on_by": "later authors of the same files",
    "importance_flow": "importance flow", "requested_by_n": "review requesters", "requested_by": "review requesters",
    "review_requesters": "review requesters", "changes_requested_rate": "change-request rate", "changes_requested_rounds": "change-request rounds",
    "changes_rounds_mean": "change-request rounds", "changes_adopted_rate": "change-request resolution (proxy)", "cross_team": "teams approved",
    "teams_covered_n": "teams covered", "downstream_authors": "later authors of the same files", "bridge_rank": "bridge rank",
    "major_episodes": "major episodes", "followup_fixed": "follow-up fixes", "followup_fix_rate_14d": "14-day follow-up fix rate",
    "approved_authors_n": "authors approved", "reverts_received": "reverts received", "reverts_given": "reverts of others",
    "fixes_received": "fixes by others", "fixes_given": "fixes for others", "fixes_for_others": "fixes for others",
    "fixed_by_others": "fixes by others", "ai_reverted_or_fixed": "AI-assisted PRs reverted or fixed", "ai_share": "AI co-authored share",
    "ai_coauthored_prs": "AI co-authored PRs", "self_driving_share": "AI-agent PR share", "core_share": "core-path share",
    "top_area_leader": "top-area leader", "top_area_share": "top-area share", "top_reviewers": "top reviewers", "top_reviewed": "top reviewed",
    "changelog_prs": "changelog PRs", "changelog_weighted": "weighted changelog entries", "delivery_hat": "delivery estimate",
    "comment_line_changed_rate": "comments acted on", "first_review_median_h": "median hours to first review",
    "reviews_given": "reviews given", "reviews_given_prs": "PRs reviewed", "critical_prs": "critical PRs", "issue_reactions": "issue reactions",
    "acted_on_rate": "comments acted on", "deepread_L": "deep-read leverage", "deepread_Q": "deep-read quality", "mature_prs": "mature PRs",
    "authors_served": "authors served", "quality_q": "quality rate", "prs_n": "PRs", "calib_diff": "calibration gap",
    "review_requested_by": "review requesters", "active_weeks": "active weeks", "w_rule_sum": "rule-weighted lines", "team_inferred": "inferred team",
}
def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


_PREFIX = r"(?:role|metrics|peer|estimates|matrix|network|team_graph|recall|coarse|refscore)"
_RULES = [
    (re.compile(r"\s*\([^()]*\b" + _PREFIX + r"\.[A-Za-z_]+[^()]*\)"), ""),                  # "(inferred from role.team_inferred = …)"
    (re.compile(r"\b" + _PREFIX + r"\.([A-Za-z_]+)"), lambda m: _KEY_WORDS.get(m.group(1), m.group(1).replace("_", " "))),
    (re.compile(r"\bP\s?=\s?(\d+(?:\.\d+)?)"), lambda m: f"{float(m.group(1)):g} pts"),    # PR points
    (re.compile(r"\bP (\d+\.\d+)\b"), lambda m: f"{float(m.group(1)):g} pts"),
    (re.compile(r"\bP(\d{1,3})\b"), lambda m: f"{_ordinal(int(m.group(1)))} pct"),          # percentile among the 20
    (re.compile(r"\s*\((?:ws\d+(?:,\s*)?)+\)"), ""),                                         # "(ws5)"
    (re.compile(r"\bws(\d+)\b"), r"workstream \1"),
    (re.compile(r"\b(" + "|".join(sorted(_KEY_WORDS, key=len, reverse=True)) + r")\b"), lambda m: _KEY_WORDS[m.group(1)]),
]
_KEEP_RAW = {"commands", "evidence_ids", "evidence_prs", "metric_key", "cid", "login", "workstream_id", "key", "numbers"}


def _clean(t):
    if not isinstance(t, str):
        return t
    for rx, to in _RULES:
        t = rx.sub(to, t)
    return t


def _clean_obj(x, key=None):
    if key in _KEEP_RAW:
        return x
    if isinstance(x, dict):
        return {k: _clean_obj(v, k) for k, v in x.items()}
    if isinstance(x, list):
        return [_clean_obj(v, key) for v in x]
    return _clean(x)


def _load_report(src: "Sources", login: str) -> dict | None:
    r = src.json(f"candidates/{login}/report.json")
    return _clean_obj(r) if r else None


def _top_layer(src: Sources):
    """(final, reports, refscore, state, decision). state: "real" | "pending" (no final.json yet).
    Reads final.json, candidates/<login>/report.json and decision/{primary,second,devil,justifications,cids}.json plus
    decision/pairwise/<a>-<b>-{ab,ba}.json. Agent texts use anonymous ids (C07); they are mapped back to logins."""
    final = src.json("final.json")
    if not final:
        return PENDING, {}, [], "pending", {}
    cids = src.json("decision/cids.json") or {}
    sub = lambda t: _clean(CID_RE.sub(lambda m: cids.get(m.group(), m.group()), t)) if isinstance(t, str) else t
    logins = [e["login"] for e in final["top5"] + final["next5"]]
    reports = {l: _load_report(src, l) for l in logins}
    notes = final.setdefault("method_notes", {}) if isinstance(final.get("method_notes", {}), dict) else {}
    for e in final["top5"] + final["next5"]:
        e["why"], e["justification"] = sub(e.get("why")), sub(e.get("justification"))
    just = src.json("decision/justifications.json") or {}
    devil = src.json("decision/devil.json")
    devil = (devil.get("objections", []) if isinstance(devil, dict) else devil) if devil is not None else notes.get("devil") or []
    notes["devil"] = [{**d, "cid": cids.get(d["cid"], d["cid"]), "replacement": cids.get(d.get("replacement_cid"), d.get("replacement_cid")),
                       **{k: sub(d.get(k)) for k in ("objection", "replacement_reason", "rebuttal")}} for d in devil]
    primary, second = src.json("decision/primary.json"), src.json("decision/second.json")
    notes["sixth_place_note"] = sub(notes.get("sixth_place_note") or (primary or {}).get("sixth_place_note"))
    pairs = []
    pdir = next((d / "decision/pairwise" for d in src.dirs if (d / "decision/pairwise").is_dir()), None)
    for ab in sorted(pdir.glob("*-ab.json")) if pdir else []:
        a, b = ab.name[:-len("-ab.json")].split("-")
        x, ba = json.loads(ab.read_text()), ab.with_name(ab.name.replace("-ab.json", "-ba.json"))
        y = json.loads(ba.read_text()) if ba.exists() else None
        consistent = y is not None and x.get("winner") == y.get("winner")
        pairs.append({"a": cids.get(a, a), "b": cids.get(b, b), "consistent": consistent,
                      "winner": cids.get(x.get("winner"), x.get("winner")) if consistent else None, "reason": sub(x.get("reason"))})
    if pdir:
        src.used["decision/pairwise/*.json"] = str(pdir.relative_to(ROOT)) if pdir.is_relative_to(ROOT) else str(pdir)
    rank_of = {e["login"]: e["rank"] for e in final["top5"] + final["next5"]}
    first = lambda t: (re.split(r"(?<=[a-z0-9)%])\. (?=[A-Z])", t or "", maxsplit=1)[0].rstrip(".") + ".") if t else None

    def lost_to(login: str) -> str | None:
        """One sentence on whom he ranked below and why: the closest higher-ranked person a decision compared him with."""
        r, best = rank_of[login], None
        for dec in (primary, second):
            drank = {cids.get(e["cid"], e["cid"]): e["rank"] for e in (dec or {}).get("ranking", [])}
            for e in (dec or {}).get("ranking", []):
                q = cids.get(e["cid"], e["cid"])
                for c in e.get("comparisons", []):
                    v = cids.get(c.get("vs"), c.get("vs"))
                    other = v if q == login else q if v == login else None
                    # the comparison must argue the same order as both this decision and the final ranking
                    if (other and rank_of.get(other, 99) < r and drank.get(other, 99) < drank.get(login, 99)
                            and (best is None or r - rank_of[other] < best[0])):
                        best = (r - rank_of[other], other, c.get("why"))
        if best:
            why = re.sub(r"^(Above|Below) @?[\w-]+:\s*", "", sub(first(best[2])))
            return f"Ranked below @{best[1]}: {why}"
        own = next((e for e in (primary or {}).get("ranking", []) if cids.get(e["cid"]) == login), None)
        return sub(first(own.get("rationale"))) if own else None

    for e in final["next5"]:
        e["not_top5"] = notes["sixth_place_note"] if e["rank"] == 6 and notes.get("sixth_place_note") else lost_to(e["login"])
    top = lambda d: {cids.get(e["cid"], e["cid"]) for e in (d or {}).get("ranking", []) if e["rank"] <= 5}
    pvs = notes.get("primary_vs_second") or {}
    decision = {"pairwise": pairs, "justifications": {l: sub(t) for l, t in just.items()},
                "agreement": {"top5_overlap": pvs.get("top5_overlap"), "kendall_tau": pvs.get("kendall_tau"),
                              "both_top5": sorted(top(primary) & top(second)),
                              "pairwise_consistent": sum(p["consistent"] for p in pairs), "pairwise_total": len(pairs)}}
    return final, {l: r for l, r in reports.items() if r}, src.json("refscore.json") or [], "real", decision


def _team(login: str, report: dict | None, roles: dict, people: dict) -> str | None:
    """Official team (report, roles.json or team graph); else the area-owner guess, labelled as inferred."""
    r = roles.get(login, {})
    t = r.get("team") or (people.get(login) or {}).get("team")  # official team map first; L3's free-text team last
    if t:
        return ", ".join(t) if isinstance(t, list) else t
    if r.get("team_inferred"):
        return f'{r["team_inferred"]} (inferred)'
    t = (report or {}).get("role", {}).get("team")
    return t if t and len(t) <= 30 else None  # L3 free text only when it is a short team name, never a sentence


def _signal_pcts(refscore: list[dict]) -> dict:
    """login → signal → (raw, pct) over the refscore population; '-' signals are inverted (lower is better)."""
    raw = {}
    for r in refscore:
        for a in r["angles"].values():
            for s, v in a.get("raw", {}).items():
                raw.setdefault(s, {})[r["login"]] = v
    inverted = {s.lstrip("-") for cl in SIGNALS.values() for ss in cl.values() for s in ss if s.startswith("-")}
    out = {}
    for s, vals in raw.items():
        pct, rk = percentiles(vals), _ranks(vals, s in inverted)
        for l, v in vals.items():
            p = pct.get(l)
            out.setdefault(l, {})[s] = {"value": v, "pct": None if p is None else round(100 - p if s in inverted else p, 1),
                                        **rk.get(l, {})}
    return out


def _key_numbers(report: dict | None, sig: dict, mrow: dict | None = None) -> list[dict]:
    """L3 picks key_numbers ({label, value, metric_key}) when it provides them; a matrix metric_key is linked to its
    definition and percentile. Otherwise the 3 refscore signals with his highest percentile."""
    if report and report.get("key_numbers"):
        out = []
        for k in report["key_numbers"][:3]:
            mk = k.get("metric_key") or k.get("key")
            in_matrix = mrow is not None and mk in mrow.get("values", {})
            out.append({"key": f"m.{mk}" if in_matrix else mk, "label": k.get("label"), "value": k.get("value"),
                        "pct": mrow["pct"].get(mk) if in_matrix else k.get("pct"), "picked_by": "evaluator",
                        **(mrow.get("rank", {}).get(mk) or {} if in_matrix else {})})
        return out
    cand = sorted(((v["pct"], k) for k, v in sig.items() if not k.startswith("report:") and v["pct"] is not None
                   and v["value"] not in (None, 0)), reverse=True)
    return [{"key": k, "value": sig[k]["value"], "pct": p, "rank": sig[k].get("rank"), "of": sig[k].get("of"),
             "picked_by": "highest percentile (script)"} for p, k in cand[:3]]


def _headline(title: str | None, n: int = 50) -> str | None:
    """Card headline: the title up to its first ':' / ' — ' / '(' when that keeps ≥12 chars, then ≤n chars at a word boundary."""
    if not title:
        return title
    cuts = [i for i in (title.find(":"), title.find(" — "), title.find("(")) if i >= 0]
    t = title[:min(cuts)].strip() if cuts and min(cuts) >= 12 else title.strip()
    if len(t) <= n:
        return t
    return t[:n - 1].rsplit(" ", 1)[0].rstrip(" ,;:-—") + "…"


def _card(report: dict | None, sig: dict, mrow: dict | None) -> dict:
    """What a person card shows: role, 2–3 contribution lines, 3 key numbers, four grades."""
    r = report or {}
    angles = {a: {"grade": r["angles"][a]["grade"], "rationale": r["angles"][a].get("rationale", "")}
              for a in ANGLES if a in r.get("angles", {})}
    return {"role_label": r.get("role", {}).get("primary_role"), "positioning": r.get("positioning"),
            "angles": angles, "overall": r.get("overall"), "key_numbers": _key_numbers(report, sig, mrow),
            "contributions": [{"headline": _headline(c.get("title")), "title": c.get("title"), "outcome": c.get("outcome")}
                              for c in r.get("core_contributions", [])[:3]]}


def _person(entry: dict, report: dict | None, sig: dict, refs: dict, placeholder: bool, team: str | None,
            mrow: dict | None = None) -> dict:
    return {"login": entry["login"], "rank": entry["rank"], "team": team, **_card(report, sig, mrow),
            "why": entry.get("why"), "stability": entry.get("stability"),
            "stability_freq": entry.get("stability_freq"), "gates": entry.get("gates"),
            "justification": entry.get("justification"), "borda": entry.get("borda"), "R": entry.get("R"),
            "R_rank": entry.get("R_rank"), "primary_rank": entry.get("primary_rank"),
            "second_rank": entry.get("second_rank"), "evidence": entry.get("evidence", []),
            "angle_scores": refs.get(entry["login"], {}).get("angles"), "placeholder": placeholder}


def _workstreams(src: Sources, login: str):
    ws = src.json(f"candidates/{login}/workstreams.json") or src.json(f"workstreams/{login}.json")
    if not ws:
        return None
    return [{"id": w["id"], "title": w["title"], "area": w.get("area"), "agg": w.get("agg"),
             "prs": [{"number": p["number"], "tier": p.get("tier"), "P": p.get("P"), "summary": p.get("summary")}
                     for p in w["prs"]]} for w in ws]


def _validation_rows(val: dict) -> list[dict]:
    """Rows from out/validation.json (impact/validation.py); a missing block stays visible as "not yet produced"."""
    f, q, a, cost = val.get("fetch"), val.get("quote_check"), val.get("audit"), val.get("llm_cost_usd")
    return [
        {"label": "Daily fetch reconciled against GitHub search counts", "key": "fetch_reconciliation",
         "value": f and f'{f["days_reconciled"]}/{f["days"]} days · {f["prs"]:,} PRs vs {f["search_count"]:,} on GitHub',
         "status": "missing" if not f else "ok" if f["days_reconciled"] == f["days"] and f["prs"] == f["search_count"] else "mismatch"},
        {"label": "Evidence quotes verified against source text", "key": "quote_check",
         "value": q and f'{q["failed"]} of {q["checked"]:,} failed ({q["fail_rate"]:.1%}) · {q["deepread_prs"]} PRs deep-read, {q["deepread_errors"]} errors',
         "status": "ok" if q else "missing"},
        {"label": "Recall audit verdict", "key": "audit",
         "value": a and f'{len(a.get("selected_into_top20", []))} audit-added people reached the top 20 (sample of {a["sample"]})',
         "status": "ok" if a else "missing"},
        {"label": "Total LLM cost (DeepSeek, dev runs included)", "key": "llm_cost",
         "value": cost is not None and f"${cost:,.2f}" or None, "status": "ok" if cost is not None else "missing"},
    ]


def _fine_stats(src: "Sources", reports: dict, notes: dict, decision: dict, top5: list) -> dict:
    """Real counts for the fine-stage card: analyst reports, custom analyses, query commands, on-demand deep reads, decisions."""
    cdir = next((d / "candidates" for d in src.dirs if (d / "candidates").is_dir()), None)
    ondemand = sum(len([l for l in f.read_text().splitlines() if l.strip()]) for f in cdir.glob("*/ondemand.jsonl")) if cdir else None
    analyses = [a for r in reports.values() for a in r.get("custom_analyses") or []]
    top = {p["login"] for p in top5}
    pairs = decision.get("pairwise", [])
    devil = notes.get("devil") or []
    return {"reports": len(reports), "custom_analyses": len(analyses),
            "query_commands": sum(len(a.get("commands") or []) for a in analyses), "ondemand_deepreads": ondemand,
            "devil_challenged": len(devil), "devil_kept": sum(d.get("decision") == "keep" for d in devil),
            "pairs": len(pairs), "pairs_consistent": sum(p["consistent"] for p in pairs),
            "incumbent_pairs": sum(1 for p in pairs if len({p["a"], p["b"]} & top) == 1),
            "incumbents_won": sum(1 for p in pairs if len({p["a"], p["b"]} & top) == 1 and p["consistent"] and p["winner"] in top),
            "stability": dict(Counter(p.get("stability") for p in top5 if p.get("stability")))}


def build(out_dir: Path) -> dict:
    out_dir = Path(out_dir)
    src = Sources(out_dir)
    stats = src.json("recall_stats.json") or {}
    coarse = src.json("coarse.json") or []
    triage = src.jsonl("triage.jsonl") or []
    graph = src.json("team_graph.json") or {}
    matrix = src.json("matrix.json") or {"columns": {}, "rows": []}
    roles = src.json("roles.json") or {}
    audit = src.json("recall_audit_sample.json")
    rcov = src.json("review_coverage.json") or {}
    val = src.json("validation.json") or {}
    final, reports, refscore, state, decision = _top_layer(src)
    placeholder = state != "real"
    people = graph.get("people", {})
    sig = _signal_pcts(refscore)
    refs = {r["login"]: r for r in refscore}

    prs_path = ROOT / stats.get("prs_path", "data/prs.jsonl")
    excl, scan = _exclusions(prs_path)
    summary = graph.get("summary", {})

    mrows = {r["login"]: r for r in matrix.get("rows", [])}
    for col, c in matrix.get("columns", {}).items():  # "#k of N" for every matrix cell, direction-aware
        for l, rk in _ranks({l: r["values"].get(col) for l, r in mrows.items()}, c.get("direction") == "lower").items():
            mrows[l].setdefault("rank", {})[col] = rk
    top5, next5 = ([_person(e, reports.get(e["login"]), sig.get(e["login"], {}), refs, placeholder,
                            _team(e["login"], reports.get(e["login"]), roles, people), mrows.get(e["login"]))
                    for e in final[k]] for k in ("top5", "next5"))
    notes = final.get("method_notes") if isinstance(final.get("method_notes"), dict) else {}
    for p, e in zip(next5, final["next5"]):
        p["not_top5"] = e.get("not_top5")

    # candidate details: every final-list person (L3 report) + every coarse/matrix person (real L0–L2 data)
    recall_m = {r["login"]: r["metrics"] for r in (src.json("recall.json") or [])}
    coarse_by = {r["login"]: r for r in coarse}
    shortlist_logins = [r["login"] for r in coarse if r.get("selected_by")] or list(mrows)
    facts = key_facts({l: _fact_values(l, recall_m.get(l, {}), coarse_by.get(l), people.get(l, {}), scan)
                       for l in shortlist_logins})
    for p in top5 + next5:
        p["facts"] = facts.get(p["login"], [])
    candidates = {}

    def report_part(login: str, r: dict | None, ph: bool) -> dict:
        r = r or {}
        return {"login": login, "placeholder": ph, "has_report": bool(r), "team": _team(login, r, roles, people),
                **{k: r.get(k) for k in ("positioning", "role", "core_contributions", "insights", "custom_analyses",
                                           "red_flags", "counter_evidence", "coverage", "calibration")},
                "angles_detail": r.get("angles"), "signals": sig.get(login),
                "card": _card(r, sig.get(login, {}), mrows.get(login)) if r else None,
                "angle_scores": refs.get(login, {}).get("angles"),
                "workstreams": None if ph else _workstreams(src, login)}

    for p in top5 + next5:
        candidates[p["login"]] = report_part(p["login"], reports.get(p["login"]), placeholder)
    script_part = lambda l, role, row: {
        "top_area": role.get("top_area"), "top_area_share": role.get("top_area_share"),
        "top_reviewed": role.get("top_reviewed"), "top_reviewers": role.get("top_reviewers"),
        "network": {k: people.get(l, {}).get(k) for k in NETWORK_LABELS} if l in people else None,
        "matrix": mrows.get(l), "coarse": row, "workstreams": _workstreams(src, l)}
    for row in coarse:
        l = row["login"]
        if l in candidates:  # final-list people get the same script-level data next to their report
            candidates[l].update({k: v for k, v in script_part(l, roles.get(l, {}), row).items() if v is not None})
            continue
        role = roles.get(l, {})
        r = _load_report(src, l)
        candidates[l] = {**(report_part(l, r, False) if r else {"login": l, "placeholder": False, "has_report": False}),
                         "team": _team(l, r, roles, people),
                         "top_area": role.get("top_area"), "top_area_share": role.get("top_area_share"),
                         "top_reviewed": role.get("top_reviewed"), "top_reviewers": role.get("top_reviewers"),
                         "network": {k: people.get(l, {}).get(k) for k in NETWORK_LABELS} if l in people else None,
                         "matrix": mrows.get(l), "coarse": row, "workstreams": _workstreams(src, l)}
    for l, fs in facts.items():
        if l in candidates:
            candidates[l]["facts"] = fs
    with_report = {l: c for l, c in candidates.items() if c.get("has_report")}
    reports_all = {l: c for l, c in with_report.items()}
    pub = {k: v for k, v in (src.json("published.json") or {}).items() if not k.startswith("_")}
    need = {l: c for l, c in with_report.items() if not (pub.get(l) or {}).get("tags")}  # Flash only where nothing is published
    tags = candidate_tags({l: {"team": c.get("team"), "role": (c.get("role") or {}).get("primary_role"),
                               "how_they_create_impact": (c.get("role") or {}).get("how_they_create_impact"),
                               "positioning": c.get("positioning"),
                               "contribution_titles": [w.get("title") for w in c.get("core_contributions") or []]}
                           for l, c in need.items()}) if need else {}
    kps = candidate_keypoints({l: {"contributions": [{k: w.get(k) for k in ("title", "outcome", "numbers")}
                                                      for w in (c.get("core_contributions") or [])[:3]]}
                                   for l, c in need.items()}) if need else {}
    # published.json (verified against the data after the audit) is the source of truth for every displayed text
    for l, c in candidates.items():
        pb = pub.get(l) or {}
        c["tags"], c["keypoints"] = pb.get("tags") or tags.get(l, []), pb.get("keypoints") or kps.get(l, [])
        c["headline"], c["caveats"], c["key_facts_note"] = pb.get("headline"), pb.get("caveats") or [], pb.get("key_facts_note")
        c["published"] = bool(pb)
        m = recall_m.get(l, {})
        c["approvals"] = {k: m.get(k) for k in APPROVAL_KEYS if m.get(k) is not None} or None
    for p in top5 + next5:
        pb, c = pub.get(p["login"]) or {}, candidates.get(p["login"], {})
        p["tags"], p["keypoints"], p["caveats"], p["headline"] = c.get("tags", []), c.get("keypoints", []), c.get("caveats", []), c.get("headline")
        if pb.get("why"):
            p["why"] = pb["why"]
        if pb.get("why_not_top5"):
            p["not_top5"] = pb["why_not_top5"]

    defs = {k: {"label": a, "formula": b, "source": c} for k, (a, b, c) in DEFS.items()}
    for k, col in matrix.get("columns", {}).items():
        defs[f"m.{k}"] = {"label": MATRIX_LABELS.get(k, col["label"]), "formula": col["definition"],
                          "source": col["source"], "direction": col["direction"]}
    gdefs = graph.get("definitions", {})
    for k, label in NETWORK_LABELS.items():
        f = gdefs.get(k) or next((v for g, v in gdefs.items() if k in g.split(" / ")), None)
        defs[f"n.{k}"] = {"label": label, "formula": f or "not defined in team_graph.json", "source": f"team_graph.people[].{k}"}
    for k in ("communities", "bridges", "single_points"):
        defs[f"g.{k}"] = {"label": k.replace("_", " ").capitalize(), "formula": gdefs.get(k, ""), "source": f"team_graph.{k}"}
    for k, (unit, plain) in PLAIN.items():
        for kk in (k, f"m.{k}"):
            if kk in defs:
                defs[kk].update(unit=unit, plain=plain)
    for k, (label, formula) in APPROVAL_KEYS.items():
        defs[f"r.{k}"] = {"label": label, "formula": formula, "source": f"recall.json metrics.{k}", **({"unit": "%"} if k.endswith("rate") else {})}
    for k, (_, trait, lower, label, formula) in FACTS.items():
        defs[f"f.{k}"] = {"label": label[0].upper() + label[1:], "formula": formula + (" (lower is better)" if lower else ""),
                          "source": "recall.json metrics / coarse.json tier_counts / team_graph people / data/prs.jsonl", "trait": trait,
                          **({"direction": "lower"} if lower else {})}
    for t, p in C.TIER_POINTS.items():
        defs[f"tier.{t}"] = {"label": t.capitalize(), "formula": f"LLM triage tier, {p} points", "source": "triage.jsonl tier"}

    all_tiers = Counter(t["tier"] for t in triage if not t.get("llm_error"))
    cand_tiers = Counter()
    for r in coarse:
        cand_tiers.update(r["tier_counts"])
    selected = [r for r in coarse if r.get("selected_by")]
    shortlist = {r["login"] for r in selected} or set(mrows)
    meth = (src.json("published.json") or {}).get("_method") or {}
    audit_meta = {"story": meth.get("story"), "changes": meth.get("changes_vs_round1") or []} if meth else None
    validation = [
        {"label": "Merged PRs in window", "value": excl and excl["merged_prs"], "key": None, "status": "ok" if excl else "missing"},
        {"label": "PRs in team graph", "value": summary.get("window_prs"), "key": None, "status": "ok" if summary else "missing"},
        {"label": "Bot PRs excluded", "value": excl and excl["bot_prs"], "key": "bot_prs", "status": "ok" if excl else "missing"},
        {"label": "AI-agent PRs (credited to a human)", "value": excl and f'{excl["ai_agent_prs"]} ({excl["ai_agent_credited"]})', "key": "ai_agent_prs", "status": "ok" if excl else "missing"},
        {"label": "PRs triaged by LLM", "value": len(triage), "key": None, "status": "ok" if triage else "missing"},
        {"label": "Triage LLM errors", "value": sum(bool(t.get("llm_error")) for t in triage), "key": None, "status": "ok" if triage else "missing"},
        {"label": "Triage cost (USD)", "value": round(sum(t.get("cost") or 0 for t in triage), 2) if triage else None, "key": None, "status": "ok" if triage else "missing"},
        {"label": "Recall audit sample", "value": f'{stats.get("audit_sampled")} of {stats.get("audit_population")} PRs', "key": "audit", "status": "ok" if stats else "missing"},
        {"label": f"Review text fetched (capped at {C.REVIEW_DETAIL_AUTHORED_CAP} authored + {C.REVIEW_DETAIL_REVIEWED_CAP} reviewed PRs per candidate, plus his deep-read sample)",
         "value": rcov and (f'{sum(v["reviewed_fetched"] for v in rcov.values()):,} of {sum(v["reviewed_total"] for v in rcov.values()):,} reviewed · '
                            f'{sum(v["authored_fetched"] for v in rcov.values()):,} of {sum(v["authored_total"] for v in rcov.values()):,} authored, {len(rcov)} candidates'),
         "key": "review_coverage", "status": "ok" if rcov else "missing"},
        {"label": "Decision agreement (two independent decisions + pairwise checks)", "key": "decision_agreement",
         "value": (lambda g: g and f'top-5 overlap {g["top5_overlap"]}/5 · Kendall τ {g["kendall_tau"]} · pairwise consistent {g["pairwise_consistent"]}/{g["pairwise_total"]}')(decision.get("agreement")),
         "status": "ok" if decision else "missing"},
        {"label": "Weight sensitivity", "value": notes.get("sensitivity"), "key": "stability_freq", "status": "ok" if state == "real" else "missing"},
        *_validation_rows(val),
        {"label": "PRs approved only by an AI bot", "key": "ai_only_approved",
         "value": excl and f'{excl["ai_only_approved"] / excl["merged_prs"]:.1%} of all PRs ({excl["ai_only_approved_human_authored"] / excl["human_authored"]:.1%} of human-authored)',
         "status": "ok" if excl else "missing"},
        {"label": "Audit and correction", "key": "audit_round",
         "value": audit_meta and "Round 1 → independent audit (2 missed engineers, quality-rate bug, self-repair invisible, overstated wording) → fixed → Round 2 re-decided all " + str(len(shortlist_logins)),
         "status": "ok" if audit_meta else "missing"},
    ]

    return {
        "meta": {"window": {"start": C.WINDOW_START[:10], "end": C.WINDOW_END[:10]},
                 "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
                 "repo": C.REPO, "impact_definition": IMPACT, "placeholder": placeholder, "decision_state": state,
                 "placeholder_note": {
                     "pending": "The final ranking has not been produced yet. Recall, coarse ranking, team network and matrix "
                                "below are real pipeline outputs."}.get(state),
                 "coverage": {"merged_prs": excl and excl["merged_prs"], "graph_prs": summary.get("window_prs"),
                              "contributors": stats.get("people"), "graph_people": summary.get("people")},
                 "exclusions": excl and {k: excl[k] for k in ("bot_prs", "ai_agent_prs", "ai_agent_credited")},
                 "audit": audit_meta, "cost": val.get("llm_cost_usd"), "fetch": val.get("fetch"), "sources": src.used, "out_dir": str(out_dir),
                 "fixture_sources": src.fallback},
        "top5": top5, "next5": next5, "candidates": candidates,
        "decision": {**{k: notes.get(k) for k in ("devil", "gate_log", "r_divergence", "verdict_only_unjustified",
                                                   "consensus_voters", "primary_vs_second", "disputed_pairs")}, **decision},
        "funnel": {"stages": [{"key": "people", "n": stats.get("people")}, {"key": "eligible", "n": stats.get("eligible")},
                              {"key": "recalled", "n": stats.get("recalled")}, {"key": "coarse_n", "n": len(selected) or None},
                              {"key": "final_n", "n": len(top5) or None}],
                   "over_cap": stats.get("over_cap"), "route_hits": stats.get("route_hits"), "only_route": stats.get("only_route"),
                   "audit": {"population": stats.get("audit_population"), "sampled": stats.get("audit_sampled"),
                             "result": val.get("audit")},
                   "tier_points": C.TIER_POINTS, "angle_weights": C.ANGLE_WEIGHTS,
                   "sizes": {"recall": C.RECALL_N, "coarse": C.COARSE_N, "final": C.FINAL_N}},
        "coarse_table": [{k: r.get(k) for k in ("login", "tier_counts", "prs", "episodes", "mass", "q", "quality_factor",
                                                 "team_score", "coarse_score", "selected_by", "recalled_by")} for r in coarse],
        "tier_distribution": {"all": dict(all_tiers), "candidates": dict(cand_tiers)},
        "team": {"summary": summary,
                 "communities": [{k: c.get(k) for k in ("id", "size", "main_team", "purity", "top_teams", "hub")}
                                 | {"candidates": [m for m in c.get("members", []) if m in shortlist]}
                                 for c in graph.get("communities", [])],
                 "bridges": graph.get("bridges", []), "single_points": graph.get("single_points", [])},
        "matrix": {"columns": list(matrix.get("columns", {})), "rows": matrix.get("rows", []),
                   "missing": matrix.get("missing", {})},
        "review_coverage": rcov, "validation": validation, "definitions": defs, "fine": _fine_stats(src, reports_all, notes, decision, top5),
    }


def split_prs(data: dict) -> dict[str, list]:
    """Move each candidate's full PR list out of site_data (one prolific author alone is ~0.6 MB) into a lazy file;
    the drawer keeps a per-workstream summary and loads prs/<login>.js when "All PRs" is opened."""
    out = {}
    for login, c in data["candidates"].items():
        ws = c.get("workstreams")
        if ws:
            out[login] = ws
            c["workstreams"] = None
            c["prs_file"] = f"prs/{login}.js"
            c["workstreams_summary"] = [{"title": w["title"], "prs_n": len(w["prs"])} for w in ws]
    return out


def main(argv: list[str]) -> None:
    out_dir, site_dir = Path(argv[0]), Path(argv[1])
    data = build(out_dir)
    data["meta"]["network_page"] = (site_dir / "network.html").exists()  # separate page (spec §F); rebuild once it lands
    data["meta"]["explainers"] = {k: (site_dir / f"method/explainer-{k}.html").exists() for k in ("en",)}
    site_dir.mkdir(parents=True, exist_ok=True)
    prs_dir = site_dir / "prs"
    prs_dir.mkdir(exist_ok=True)
    for old in prs_dir.glob("*.js"):
        old.unlink()
    for login, ws in split_prs(data).items():  # script files, not fetch, so file:// works too
        (prs_dir / f"{login}.js").write_text(
            f"(window.SITE_PRS=window.SITE_PRS||{{}})[{json.dumps(login)}]={json.dumps(ws, ensure_ascii=False, separators=(',', ':'))};\n")
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    (site_dir / "site_data.json").write_text(text)
    (site_dir / "site_data.js").write_text(f"window.SITE_DATA={text};\n")  # fallback when index.html is opened via file://
    print(f"{site_dir / 'site_data.json'}: {(site_dir / 'site_data.json').stat().st_size / 1e6:.2f} MB, "
          f"placeholder={data['meta']['placeholder']}, sources={len(data['meta']['sources'])}")


if __name__ == "__main__":
    main(sys.argv[1:])
