# Org inputs (public PostHog website data, fetched 2026-11-03)

Read by `python -m impact.data_extra org` (`impact/config.py` `ORG_DIR`) to build `data/team_map.json` and `data/changelog.json`.

| File | Content | Source |
|---|---|---|
| `members.csv` | One row per team member: team, role, start date, lead flag, GitHub handle from the profile's own `github` field (139 of 243 have one) | posthog.com Strapi API `https://better-animal-d658c56969.strapiapp.com/api/teams` (populated profiles), which backs https://posthog.com/teams |
| `changelog-since-2026-07-01.tsv` | Changelog entries since 2026-07-01: date, category, team, title, linked PR URLs, PR author and reviewers | posthog.com Strapi API `/api/roadmaps` (completed items), which backs https://posthog.com/changelog; author and reviewers from the linked GitHub PRs |
| `teams-full.md` | Human-readable team × owned `products/` directories × members table (reference only; `build_org` reads `members.csv`) | Same Strapi `/api/teams` + `products/*/product.yaml` owners in PostHog/posthog master |
