"""Every constant the spec pins (docs/superpowers/specs/2026-11-03-impact-funnel-design.md §9)."""
import math
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = next((d for d in (ROOT / "data/raw", ROOT / ".agents/task/01-impact-dashboard/task/02-repo-context/subagent/02-data-profile/data/raw") if any(d.glob("*.json"))), ROOT / "data/raw")  # scripts/fetch_prs.py output first; else the original profiling dump
DATA = ROOT / "data"
OUT = Path(os.environ.get("IMPACT_OUT", ROOT / "out"))  # full runs use IMPACT_OUT=out_full so dev runs on the fixture never overwrite them
PRS = DATA / "prs.jsonl"
FIXTURE = DATA / "fixture_prs.jsonl"
CLONE = DATA / "posthog"

REPO = "PostHog/posthog"
WINDOW_START = "2026-08-05T00:00:00Z"
WINDOW_END = "2026-11-03T23:59:59Z"
BUFFER_START = "2026-07-06T00:00:00Z"  # only for follow-up-fix and lineage lookups

BOT_LOGINS = {
    "posthog", "posthog-js-upgrader", "scheduled-actions-posthog", "releaser-posthog-cli",
    "renovate", "dependabot", "trunk-io", "github-actions", "stamphog",
    "deployment-status-posthog", "parameterai", "chatgpt-codex-connector", "hosthog",
    "inkeep", "greptile-apps", "pr-assigner-resolver-posthog",
}
AI_AGENT_LOGIN = "posthog"
AI_AGENT_MARKER = "posthog-self-driving-origin"

# Path noise weights and area criticality live in impact/paths.py (regex classifier from T01.02/S01).

TIER_POINTS = {"mechanical": 0, "trivial": 1, "routine": 2, "substantive": 4, "major": 8, "landmark": 16}
ANGLE_WEIGHTS = {"delivery": 0.50, "system": 0.20, "quality": 0.15, "team": 0.15}

RECALL_N, COARSE_N, FINAL_N = 60, 20, 5
RECALL_TOP_DELIVERY, RECALL_TOP_TEAM = 40, 15
COARSE_TOP_SCORE, COARSE_TOP_TEAM = 15, 5
ACTIVITY_MIN_PRS, ACTIVITY_MIN_REVIEWS = 5, 20

MODEL = "deepseek/deepseek-v4.1-flash"
LLM_CONCURRENCY = 128  # probe: 128 → ~22 PR/s, 0 errors (T01.03/S03)


def is_bot(login: str | None, typename: str | None = None) -> bool:
    return not login or typename == "Bot" or "[bot]" in login or login.lower() in BOT_LOGINS


def pr_points(ell: float) -> float:
    """PR impact points on the tier scale: ell 0→1, 1.5→4, 3→16."""
    return 2 ** (4 * ell / 3)


def pr_level(v: float, c: float, n: float) -> float:
    return 0.55 * v + 0.30 * c + 0.15 * (1.5 * n)


def log_lines(lines: float) -> float:
    return math.log2(1 + max(0, lines))

# --- revisions from Codex review (.agents/task/01-impact-dashboard/task/03-build-funnel/review-codex.md)
MATURE_CUTOFF = "2026-10-20T23:59:59Z"  # quality signals only for PRs with ≥14 days to fail
EPISODE_DAYS, EPISODE_FILE_OVERLAP, EPISODE_REST_WEIGHT = 7, 0.30, 0.25
SAMPLE_PER_STRATUM = {"major+landmark": 8, "substantive": 6, "routine": 3, "trivial": 2}
SEED, SEED_ALT = 7, 11
AUDIT_SAMPLE = 300
TRIAGE_MAX_PATHS, DIFF_MAX_CHARS, BODY_MAX_CHARS = 60, 24000, 6000
SYSTEM_ROUTE_TOP, EXEMPT_TOP_PCT = 10, 0.05
EVALUATOR_WAVE, CANDIDATES_PER_EVALUATOR = 4, 5

# --- Task 1 data completion (impact/data_extra.py)
ORG_DIR = next((d for d in (ROOT / "inputs/org", ROOT / ".agents/task/01-impact-dashboard/task/02-repo-context/subagent/03-org-culture") if (d / "members.csv").exists()), ROOT / "inputs/org")  # committed copy first; else the original research dump
REVIEW_DETAIL, LINEAGE, COMMIT_AUTHORS = DATA / "review_detail.jsonl", DATA / "lineage.json", DATA / "commit_authors.json"
TEAM_MAP, CHANGELOG = DATA / "team_map.json", DATA / "changelog.json"
GQL_BATCH = 25  # PRs/issues per aliased GraphQL query
GQL_REVIEWS, GQL_THREADS, GQL_THREAD_COMMENTS, GQL_REQUESTS = 50, 50, 20, 50  # page sizes; overflow flagged in `truncated`
GQL_RATE_WAIT_S = 90

# --- fine decide (T01.03/S05): ranking, boundary pairwise, gates, weight sensitivity
BORDA_TOP = 10                      # each ranker lists top 10; rank 1 → 10 points … rank 10 → 1
BOUNDARY_RANKS = (4, 8)             # Borda ranks re-ordered by pairwise Copeland (R10)
GATE_MIN_MAJOR, GATE_MIN_LANDMARK, GATE_TEAM_TOP = 2, 1, 3
GATE_MAX_REVERTED, GATE_FOLLOWUP_WORST_PCT = 3, 80  # follow-up-fix rate percentile ≥ 80 = worst 20%
GATE_FOLLOWUP_MIN_RATE = 0.08  # ...and the rate itself ≥ 8%; full-run candidates span 2–4%, so rank alone flagged noise
GATE_TOP7, GATE_TOP7_SHARE = 7, 1.0  # with two independent deciders: both must list him in their top 7, else the manager must justify
SENS_DRAWS, SENS_SPREAD = 1000, 0.5  # weights × U(1−spread, 1+spread), renormalized
STABLE_MIN, BORDERLINE_MIN = 0.7, 0.4
RANK_DEVIATION = 3                  # ranker must explain |rank − R rank| > 3

# --- fine read (T01.03/S04)
DEEPREAD_REVIEW_MAX_CHARS = 8000  # review discussion text per PR sent to deep read
DOSSIER_REVIEW_SAMPLES, DOSSIER_REVIEW_MIN_CHARS = 10, 40
DOWNSTREAM_MIN_LINES = 20  # design §9.2: files he created or changed by ≥20 lines

# --- recall track (T01.03/S02)
FOLLOWUP_DAYS = 14  # a follow-up fix counts only if merged within this many days of the original
CRITICAL_LABEL_RE = r"incident|security|vulnerab|billing|critical|outage|hotfix|sev[-_ ]?\d"  # R4 floor exemption + recall route
FOLLOWUP_EXCLUDE_RE = r"\(an unrelated|unrelated (?:change|pr|fix)|flake|already shipped|similar to|follow[- ]up to|see also"  # a ref in such a sentence is not causal
HUB_FILE_AUTHORS = 25  # files touched by ≥ this many authors in the window are shared registries, not "building on" someone

# --- fine synth (T01.03/S06): L2 workstream clusters (script only, spec §11.2), role profile, L0 comparison matrix
WS_MIN, WS_MAX = 3, 8               # workstreams per person incl. the misc bucket; overflow folds into misc (listed)
WS_TOP_PRS = 3                      # extremes passed up verbatim (spec §10 rule 2)
ROLE_TOP = 5                        # top reviewed / top reviewers listed; full distinct counts are kept alongside

# --- team event graph (T01.03/S07, spec §11.1)
METRIC_MIN_N = 5                    # per-person network metric with sample < this → None
FLOW_AUTHOR_W, FLOW_REVIEWER_W = 1.0, 0.3  # importance flow: share of a PR's points to its author / each substantive reviewer
BRIDGES_TOP = 10                    # betweenness top-N listed as bridges
SINGLE_POINT_SHARE, SINGLE_POINT_MIN = 0.8, 5  # area where one approver gives ≥ share of ≥ MIN approvals
GRAPH_EXTRA_BOTS = {"pr-assigner-resolver-posthog"}  # auto-assigner seen as review requester; not in BOT_LOGINS

# --- candidate data pack + query tool (T01.03/S04, spec §12)
ONDEMAND_DEEPREAD_CAP = 6  # on-demand Flash deep reads per candidate, tracked in out/candidates/<login>/ondemand.jsonl
QUERY_MAX_LINES = 60       # default output budget of `python -m impact.fine.query`; overflow is announced, never silent
AI_TOOL_RE = r"claude|codex|cursor|copilot|posthog desktop|anthropic\.com|openai\.com"  # co-author / Generated-By trailer → AI-assisted PR
L3_CALIBRATION_KEYS = ("delivery", "quality_rate", "team_leverage", "trust_rank")  # out/matrix.json columns the L3 analyst ranks before grading

# --- review detail caps (T01.03/S03): 20 candidates' full review detail is ~11.7k PRs ≈ 5.8k GraphQL points, over the 5,000/h quota
REVIEW_DETAIL_AUTHORED_CAP, REVIEW_DETAIL_REVIEWED_CAP = 60, 80  # per candidate, beyond his deep-read sample; coverage → out/review_coverage.json
DOSSIER_PRS_PER_WS = 15    # PR lines per workstream in dossier.md (deep-read first, then tier, newest); full list via query `prs --ws`
COARSE_TOP_MAJOR = 15  # coarse "major" route: top triaged authors by major/landmark episodes, ties included (audit-codex-final #2)
