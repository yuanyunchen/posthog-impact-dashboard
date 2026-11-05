# PostHog Impact Funnel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A reproducible three-stage funnel (recall → coarse → fine) that ranks PostHog engineers by impact over 2026-08-05 → 2026-11-03, with every score traceable to data, agent judgment and peer behavior.

**Architecture:** Layered evaluation — code rules (deterministic metrics) → evaluation scripts (DeepSeek Flash per-PR triage and deep read) → per-candidate Claude evaluator subagents (evaluation cards) → main agent (ranking, devil's advocate, final call). Stages communicate only through JSON files with the schemas below, so the three stage tracks are developed in parallel against a shared fixture.

**Tech Stack:** Python 3.12+ (stdlib + httpx, networkx, pytest), gh GraphQL, git shallow clone, OpenRouter `deepseek/deepseek-v4.1-flash`.

**Spec:** `docs/superpowers/specs/2026-11-03-impact-funnel-design.md` (v3; §9 is normative for scoring).

## Global Constraints

- Window: merged_at in [2026-08-05T00:00Z, 2026-11-03T23:59Z]. Fetch buffer from 2026-07-06 is used only for "follow-up fix within 14 days" and lineage lookups.
- Bots: author `__typename == "Bot"` or login contains `[bot]`; also these logins: `posthog`, `posthog-js-upgrader`, `scheduled-actions-posthog`, `releaser-posthog-cli`, `renovate`, `dependabot`, `trunk-io`, `github-actions`, `stamphog`, `deployment-status-posthog`, `parameterai`, `chatgpt-codex-connector`, `hosthog`, `inkeep`, `greptile-apps`. `mergedBy` is never used.
- Path weights (first match wins): lockfiles / `__snapshots__` / `*.snap` / generated → 0; `.agents/`, `.claude/`, `AGENTS.md`, `SKILL.md`, `*.md` → 0.2; `**/migrations/**` → 0.3; `.github/`, CI and build config → 0.3; tests and `*.stories.*` → 0.5; everything else → 1.0 (criticality multiplier from the path map applied on top).
- Tier points: mechanical 0 (excluded), trivial 1, routine 2, substantive 4, major 8, landmark 16.
- PR level ℓ = 0.55·V + 0.30·C + 0.15·(1.5·N); P = 2^(4ℓ/3) (ℓ=0→1, 1.5→4, 3→16; same scale as tier points).
- Angle weights (reference only): delivery 0.50, system 0.20, quality 0.15, team 0.15.
- Funnel sizes: recall 60, coarse 20, final 5. Every cap is a named constant in `impact/config.py`; nothing is truncated silently — any per-PR truncation (files > 100, reviews > 50) is recorded as a flag on the record.
- LLM calls: concurrency 64, JSON output, `reasoning: {"effort": "low"}`, max 3 retries; every response cached on disk keyed by (stage, PR number, prompt hash) so reruns are free. Key read from env `OPENROUTER_API_KEY` (loaded from `.agents/secrets.env`), never written to outputs.
- AI-agent PRs (author `posthog`, body contains `posthog-self-driving-origin`): attributed to the triggering human if one is identifiable (PR assignee, `Co-authored-by`, or "requested by @x" in body), flagged `ai_assisted=true`; otherwise excluded from individual totals.
- Evidence quotes must be verbatim substrings of the PR title/body/diff/review text; failed checks lower that sub-score by 1 (floor 0).

## Review Focus

1. A PR whose author is a bot but which a human drove (AI-agent PR) — attributed per the rule above, never silently dropped or credited to the bot.
2. A huge generated/migration PR (10k lines) — must land in tier mechanical / weight ≤ 0.3, never top the delivery ranking.
3. An engineer with many tiny PRs vs one with a few major ones — the major one must win coarse ranking when tier mass is higher (test with synthetic data).
4. LLM returns malformed JSON or a quote not present in the source — retried, then the PR is marked `llm_error` and excluded from averages, and the count is reported.
5. A reviewer whose only reviews are approvals on bot PRs — gets no team-leverage credit.

---

## File Structure

```
impact/
  config.py        constants above + paths
  schema.py        TypedDicts for every JSON contract below
  normalize.py     raw day files → data/prs.jsonl (Task 0)
  llm.py           OpenRouter async client with cache (Task 0)
  recall/features.py  per-PR rule weight, per-person metrics
  recall/run.py       → out/recall.json
  coarse/triage.py    Flash triage → out/triage.jsonl
  coarse/run.py       → out/coarse.json
  fine/dossier.py     → out/dossiers/<login>.json + .md
  fine/deepread.py    Flash deep read → out/deepread.jsonl
  fine/refscore.py    four-angle reference scores → out/refscore.json
  fine/aggregate.py   Borda + pairwise + gates + robustness → out/final.json
  fine/prompts/{evaluator,ranker,pairwise,devil}.md
  data_extra.py    supplemental GraphQL fields + git lineage (Task 1)
tests/             one test file per module
data/, out/        gitignored except out/site_data.json
```

## JSON Contracts (all tracks code against these)

- `data/prs.jsonl` (one PR per line): `number, url, title, body, author, author_is_bot, ai_assisted, credited_to, created_at, merged_at, additions, deletions, files:[{path,additions,deletions}], files_truncated, labels:[str], reviews:[{author,is_bot,state,submitted_at,body_len}], review_threads:[{author,is_outdated}], review_requests:[login], closing_issues:[{number,reactions}], merge_commit, commits`.
  Fields from Task 1 (`review_threads`, `review_requests`, `merge_commit`, issue reactions) are `null` until Task 1 lands; consumers treat `null` as missing (score 50, flagged).
- `out/recall.json`: `[{login, metrics:{prs, eff_lines, w_rule_sum, core_share, areas, active_weeks, reviews_given, authors_served, first_review_median_h, review_requested_by, pagerank, reverted, followup_fixed, changelog_prs, issue_reactions}, recalled_by:[rule names]}]`
- `out/triage.jsonl`: `{number, tier, work_type, user_facing, critical, novel, summary, guardrail}`
- `out/coarse.json`: `[{login, tier_counts:{mechanical,trivial,routine,substantive,major,landmark}, mass, quality_factor, team_score, coarse_score, selected_by}]`
- `out/deepread.jsonl`: `{number, V, C, N, L, Q, evidence:{V,C,N,L,Q: quote}, verified:{...: bool}, ell, P, llm_error}`
- `out/refscore.json`: `[{login, angles:{delivery,system,quality,team: {quant, agent, behavior, score}}, R}]` (agent lens filled after evaluator cards)
- `out/cards/<login>.json`: `{login, angles:{<angle>:{grade, rationale, data_points:[str], prs:[url]}}, overall, confidence, archetype, top_evidence:[url], counter_evidence, deviations}`
- `out/final.json`: `{top5:[{login, rank, borda, stability, gates, why, evidence}], next5, method_notes}`

---

### Task 0: Scaffold, config, normalize, LLM client (main agent, before fan-out)

**Files:** Create `impact/config.py`, `impact/schema.py`, `impact/normalize.py`, `impact/llm.py`, `tests/test_normalize.py`, `tests/test_llm.py`, `pyproject.toml`, `.gitignore`.

- [ ] Test `test_bot_detection`: `is_bot("stamphog", "User") is True`, `is_bot("alice", "Bot") is True`, `is_bot("alice", "User") is False`.
- [ ] Test `test_ai_assisted_attribution`: a PR by `posthog` with body containing `posthog-self-driving-origin` and `Co-authored-by: Bob <...>` mapped via login table → `ai_assisted=True, credited_to` set or `None`.
- [ ] Test `test_window_filter`: merged 2026-08-04 excluded, 2026-08-05 included.
- [ ] Implement `normalize(raw_dir: Path, out: Path) -> dict` (returns counts by day, bots, excluded) and `llm.complete_json(stage: str, key: str, prompt: str, schema_hint: str) -> dict` with disk cache under `data/llm_cache/`.
- [ ] Run `pytest -q` → all pass; run normalize on the 40 already-fetched days → fixture `data/fixture_prs.jsonl` (2026-07-20 → 2026-08-13) for the stage tracks.
- [ ] Commit.

### Task 1: Data completion (track A, parallel)

**Files:** `impact/data_extra.py`, `tests/test_data_extra.py`.
**Produces:** fills `merge_commit`, `review_threads`, `review_requests`, `closing_issues[].reactions` in `data/prs.jsonl`; `data/lineage.json` = `{path: [{author, merged_at, number}]}` from `git log --name-only` on a `--filter=blob:none --shallow-since=2026-07-01` clone; `data/changelog.json` and `data/team_map.json` from the org-culture outputs.
- [ ] Test: batched GraphQL by PR number (aliases, 50 per query) returns every requested PR or records it in `missing`.
- [ ] Test: lineage maps a squash commit to its PR number via `(#NNNN)` in the subject.
- [ ] Verify: merged count per day equals the search `issueCount` logged by the fetcher for all 91 days; report mismatches.

### Task 2: Recall (track B, parallel) — `impact/recall/`

- [ ] Tests: `w_rule` of a PR touching only `pnpm-lock.yaml` is 0; of a migrations-only PR ≤ 0.3·log2(1+lines); bot-only reviews give `reviews_given == 0`; PageRank runs on author↔reviewer graph excluding bots.
- [ ] Implement metrics in the `recall.json` contract; recall = top 40 by `w_rule_sum` ∪ top 15 by team leverage (`reviews_given × log(1+authors_served)`) ∪ anyone with ≥1 changelog PR or a `critical`-labelled PR, capped by activity floor (≥5 merged PRs or ≥20 human reviews); if the union exceeds 60, keep the union and log the count (no silent cut).
- [ ] Small-scale run on fixture; print top 15 with the reason each was recalled.

### Task 3: Coarse (track C, parallel) — `impact/coarse/`

- [ ] Tests: guardrails (all-downweighted-paths → mechanical; <10 lines and major without quote → substantive); `mass` uses 0/1/2/4/8/16; synthetic: 3 landmark PRs (48) beat 20 routine PRs (40); 40 mechanical PRs score 0.
- [ ] Triage prompt: tier anchors from spec §9.1 verbatim, input = title, body[:6000 chars], file list (≤60 paths + counts), labels, +/-; output JSON per triage contract.
- [ ] `coarse_score = mass × quality_factor` where `quality_factor = 1 − min(0.5, (reverted + followup_fixed) / max(1, substantive+major+landmark))`; select top 15 by `coarse_score` ∪ top 5 by `team_score`.
- [ ] Small-scale run: triage 200 fixture PRs; report tier distribution, error count, cost, seconds; hand-check 10 (sample printed with summaries).

### Task 4: Fine (track D, parallel) — `impact/fine/`

- [ ] Tests: `P(ell)` = 2^(4ℓ/3) (ℓ=0→1, 1.5→4, 3→16); quote verification lowers sub-score; stratified sample = all major+landmark (cap 8) + 6 substantive + 3 routine with seed 7; `stratified_delivery` = Σ_tier count × mean P (fallback tier points when no sample); Borda (10..1 over 3 rankers); gates (a)(b)(c) from spec §9.4; robustness: 1000 draws of weights ×U(0.5,1.5) renormalized → top-5 frequency.
- [ ] Deep read input: title, body, filtered diff ≤ 24k chars (from local clone via `git show <merge_commit>` once Task 1 lands; fixture fallback = file list + body), review comment bodies; output per deepread contract.
- [ ] Dossier: all metrics, tier distribution, PR list with summaries, 10 sampled human review comments by the person, peer-behavior events (reverts, follow-up fixes, downstream authors, review requests), changelog entries, team.
- [ ] Prompts: evaluator (anchors 9–10/7–8/5–6/3–4/1–2, ≥2 data points + ≥1 PR per grade, deviation >3 must be explained), ranker (anonymized IDs, top 10 with reasons), pairwise (both orders), devil (strongest objection + likely replacement).
- [ ] Small-scale run: 3 candidates from fixture → dossiers, deep read, one evaluator card produced by a Claude subagent from the prompt; check card validates against the contract.

### Task 5: Full run and integration (main agent)

- [ ] Full data (91 days) → recall → coarse → fine; evaluator subagents 7 in parallel (3 candidates each); 3 rankers in parallel; pairwise; devil; aggregate.
- [ ] Validation report: counts per stage, LLM error rate, cost, Spearman(score, LOC), robustness labels, divergence between R-rank and final rank with reasons.

### Task 6: Report page (main agent)

- [ ] HTML for the user: core design, per-stage numbers, small-scale test results, issues found, optimization directions.
