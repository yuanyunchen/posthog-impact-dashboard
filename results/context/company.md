# PostHog engineering context (window 2026-08-05 → 2026-11-03)

Script-generated from merged PRs, coarse triage, the public changelog, data/team_map.json and the team event graph. ★ = one of the 20 candidates. Cite numbers by the key in backticks.

## 1. Where the work happened

`company.human_prs`=16318 · `company.people`=188 · `company.teams_active`=47 (team known for 102 of 188 authors) · `company.triaged_prs`=16318 · `company.major_episodes`=1152 · `company.changelog_entries`=141

Major+ episodes count only triaged PRs (the 60 recalled people plus the audit sample), so they show where candidates' and other active engineers' important work landed, not a census.

Key: `area[<area>].<column>`. Top 15 areas by major+ episodes, then PRs.

| area | owner team | prs | prs_share | major_episodes | major_share | changelog |
|---|---|---|---|---|---|---|
| Product: Warehouse sources | warehouse-sources | 3047 | 18.7% | 175 | 15.2% | 46 |
| Django platform (API/models/auth) | — | 720 | 4.4% | 125 | 10.9% | 9 |
| Ingestion pipeline & CDP (nodejs) | — | 553 | 3.4% | 97 | 8.4% | 0 |
| Background jobs (Temporal/Celery/Dagster) | — | 417 | 2.6% | 51 | 4.4% | 8 |
| Query engine (HogQL) | — | 298 | 1.8% | 47 | 4.1% | 1 |
| Product: Desktop | surfaces | 851 | 5.2% | 39 | 3.4% | 2 |
| Frontend scenes (core app pages) | — | 965 | 5.9% | 36 | 3.1% | 11 |
| Ingestion (rust) | — | 189 | 1.2% | 33 | 2.9% | 0 |
| Product: Tasks | agent-infrastructure | 496 | 3.0% | 31 | 2.7% | 1 |
| Repo config/CI/tooling | — | 926 | 5.7% | 25 | 2.2% | 1 |
| Persons store (personhog) | — | 154 | 0.9% | 22 | 1.9% | 0 |
| Product: Workflows | workflows | 361 | 2.2% | 21 | 1.8% | 2 |
| Product: Replay vision | replay | 395 | 2.4% | 20 | 1.7% | 4 |
| ClickHouse data layer | — | 171 | 1.0% | 20 | 1.7% | 0 |
| MCP server | — | 220 | 1.3% | 19 | 1.6% | 2 |
| other (111 areas) | — | 6555 | 40.2% | 391 | 33.9% | 92 |

## 2. Teams

Teams with ≥1 window PR by a mapped member (47; 8 mapped teams had none). A person on two teams counts for both. Key: `team[<team>].<column>`.

| team | members | prs | major_prs | owns (products) | where members' PRs land (top 3) | candidates |
|---|---|---|---|---|---|---|
| warehouse-sources | 3 | 2969 | 219 | Warehouse sources, Warehouse sources queue | Product: Warehouse sources 2644, Product: Data warehouse 100, Product: Desktop 27 | ★Gilbert09 |
| feature-flags | 3 | 342 | 72 | Cohorts, Early access features, Feature flags | Product: Feature flags 43, Cohorts (rust) 41, Django platform (API/models/auth) 37 | ★haacked |
| developer-experience | 3 | 1117 | 65 | — | Repo config/CI/tooling 500, Product: Engineering analytics 100, Product: PostHog Review 79 | ★gantoine, ★rnegron, ★webjunkie |
| surfaces | 6 | 975 | 53 | Canvas, Desktop, PostHog AI, Slack app, Today | Product: Desktop 310, Frontend platform (shared UI/query) 132, Product: Tasks 101 | ★puemos |
| agent-infrastructure | 4 | 644 | 49 | AI gateway, Tasks | Product: Tasks 237, Product: Desktop 217, Agent infrastructure 55 | ★tatoalo |
| security | 2 | 160 | 47 | — | Django platform (API/models/auth) 57, Repo config/CI/tooling 31, Django platform (misc) 12 | ★Piccirello |
| apm | 3 | 288 | 45 | APM, Alerts, Alerts platform, Logs, Metrics, Tracing, Uptime monitoring | Product: Metrics 94, Product: Logs 30, ClickHouse data layer 28 | ★frankh |
| blitzscale | 6 | 730 | 37 | — | Frontend platform (shared UI/query) 159, Frontend scenes (core app pages) 73, Django platform (API/models/auth) 68 | ★pauldambra |
| experiments | 3 | 459 | 36 | Experiments | Product: Experiments 203, Frontend scenes (core app pages) 96, Django platform (API/models/auth) 32 | — |
| clickhouse | 2 | 149 | 32 | Live debugger | ClickHouse data layer 47, Background jobs (Temporal/Celery/Dagster) 35, Supporting services/libs 24 | — |
| product-analytics | 4 | 702 | 31 | Actions, Annotations, Dashboards, Event definitions, Exports, Groups, Persons, Product analytics, Pulse, Subscriptions | Product: Product analytics 126, Frontend scenes (core app pages) 111, Frontend platform (shared UI/query) 88 | ★sampennington, ★thmsobrmlr |
| growth | 2 | 290 | 31 | Account audits, Demo data, Growth, Legal documents, Wizard | Django platform (API/models/auth) 47, Frontend platform (shared UI/query) 45, Frontend scenes (core app pages) 38 | ★rafaeelaudibert |
| replay | 2 | 262 | 27 | Replay, Replay vision | Product: Replay vision 191, Ingestion pipeline & CDP (nodejs) 16, Background jobs (Temporal/Celery/Dagster) 11 | ★TueHaulund |
| workflows | 2 | 265 | 26 | CDP, Messaging, Workflows | Product: Workflows 138, Ingestion pipeline & CDP (nodejs) 60, Frontend scenes (core app pages) 12 | ★dmarchuk |
| data-tools | 2 | 191 | 25 | Business intelligence, Notebooks, Streamlit apps | Frontend platform (shared UI/query) 54, Frontend scenes (core app pages) 46, Product: Business intelligence 46 | — |
| ai-research | 3 | 223 | 21 | AI training, ML inference | Ingestion pipeline & CDP (nodejs) 101, Product: Signals 34, Product: PostHog Review 28 | — |
| web-analytics | 2 | 259 | 20 | AEO, Core events, Customer analytics, Marketing analytics, Revenue analytics, Web analytics | Product: Customer analytics 133, Product: Web analytics 35, Frontend platform (shared UI/query) 17 | — |
| self-driving | 4 | 389 | 17 | Autoresearch, Mobile, Signals | Product: Signals 178, Product: Desktop 96, Product: PostHog AI 33 | — |
| context-and-mcp | 3 | 190 | 16 | Context layer, MCP servers, Skills | Product: Desktop 56, MCP server 41, Product: Tasks 27 | — |
| query-performance | 3 | 70 | 16 | — | Query engine (HogQL) 31, Django platform (API/models/auth) 7, ClickHouse data layer 6 | — |
| ai-observability | 5 | 191 | 15 | AI observability, LLM analytics (vestigial) | Product: AI observability 105, Background jobs (Temporal/Celery/Dagster) 45, Query engine (HogQL) 8 | — |
| data-modeling | 2 | 179 | 15 | Data catalog, Data modeling, Data quality, Endpoints, Warehouse suggestions | Product: Data catalog 39, Product: Data quality 36, Product: Data modeling 30 | — |
| customer-success-na-north | 4 | 109 | 15 | — | Product: Warehouse sources 77, Product: Customer analytics 7, Frontend platform (shared UI/query) 3 | — |
| support | 8 | 132 | 13 | — | Frontend scenes (core app pages) 22, Product: Warehouse sources 19, Frontend platform (shared UI/query) 15 | — |
| warehouse | 6 | 105 | 12 | — | Product: Managed warehouse 48, Query engine (HogQL) 20, Product: Warehouse sources 9 | ★fuziontech |
| customer-analytics | 1 | 170 | 10 | — | Product: Customer analytics 133, Frontend platform (shared UI/query) 13, Product: Conversations 8 | — |
| conversations | 2 | 107 | 10 | Business knowledge, Conversations, Surveys | Product: Conversations 54, Product: Business knowledge 37, Frontend platform (shared UI/query) 4 | — |
| platform-features | 1 | 62 | 10 | Access control, Approvals, Authorization, Cross-project dashboards, Links, Notifications, Platform features, Reminders, Security | Django platform (API/models/auth) 30, Frontend scenes (core app pages) 7, Frontend platform (shared UI/query) 4 | — |
| error-tracking | 2 | 100 | 8 | Error tracking | Product: Error tracking 26, Product: Replay vision 17, Supporting services/libs 15 | — |
| cloud-platform | 2 | 33 | 4 | — | Repo config/CI/tooling 18, Django platform (API/models/auth) 7, Product: Desktop 1 | — |
| gtm-engineering | 1 | 11 | 4 | — | Product: Customer analytics 6, Background jobs (Temporal/Celery/Dagster) 3, Django platform (API/models/auth) 1 | — |
| mcp-analytics | 1 | 80 | 3 | MCP analytics, MCP registry | Product: MCP analytics 41, Frontend scenes (core app pages) 13, Product: Surveys 10 | — |
| platform-ux | 1 | 161 | 2 | — | Product: Desktop 77, Frontend platform (shared UI/query) 44, Frontend tooling/design system 16 | — |
| client-libraries | 4 | 38 | 2 | — | Repo config/CI/tooling 10, Frontend platform (shared UI/query) 4, Supporting services/libs 4 | — |
| billing | 2 | 34 | 2 | Billing, Billing alerts | Frontend scenes (core app pages) 9, Django platform (API/models/auth) 8, Background jobs (Temporal/Celery/Dagster) 5 | — |
| wizard-and-docs | 4 | 17 | 2 | — | Repo config/CI/tooling 4, Django platform (misc) 3, Product: Business knowledge 2 | — |
| product-led-sales-west | 3 | 10 | 2 | — | Frontend scenes (core app pages) 3, Product: Billing alerts 3, Product: AI observability 1 | — |
| builder-relations | 4 | 3 | 1 | — | Agent infrastructure 1, Product: Warehouse sources 1, Repo config/CI/tooling 1 | — |
| developer-marketing | 5 | 21 | 0 | — | Frontend scenes (core app pages) 4, MCP server 3, Product: Desktop 3 | — |
| demand-gen | 1 | 19 | 0 | — | Frontend scenes (core app pages) 4, MCP server 3, Frontend platform (shared UI/query) 3 | — |
| sales-product-led | 2 | 4 | 0 | — | Django platform (misc) 1, Product: Customer analytics 1, Frontend platform (shared UI/query) 1 | — |
| customer-success-eu | 2 | 2 | 0 | — | Product: Warehouse sources 1, Product: Customer analytics 1 | — |
| editorial | 5 | 2 | 0 | — | Product: Tasks 1, Django platform (API/models/auth) 1 | — |
| onboarding | 3 | 2 | 0 | — | Repo config/CI/tooling 1, Product: Warehouse sources 1 | — |
| cloud-foundations | 2 | 1 | 0 | — | Product: PostHog Review 1 | — |
| forward-deployed-engineering | 3 | 1 | 0 | — | Product: Warehouse sources 1 | — |
| website | 2 | 1 | 0 | — | Repo config/CI/tooling 1 | — |

## 3. Changelog themes by area

`company.changelog_entries`=141 distinct entries tied to window PRs; an entry spanning PRs in two areas counts in both.

- **Product: Warehouse sources** `changelog[Product: Warehouse sources]`=46: 161 new source tables; 28 new warehouse sources; 54 new Data Warehouse sources …
- **Product: Signals** `changelog[Product: Signals]`=21: Clearer Signals scout reports; Enable more Inbox sources; Failed checks get follow-ups …
- **Product: Batch exports** `changelog[Product: Batch exports]`=14: Export events with person IDs; Long-running AWS exports; More complete session batch exports …
- **Frontend scenes (core app pages)** `changelog[Frontend scenes (core app pages)]`=11: Clearer report resolution outcomes; Find models needing attention; Refreshed toolbar launch settings …
- **Django platform (API/models/auth)** `changelog[Django platform (API/models/auth)]`=9: Export audit logs for SIEMs; Fetch prompts by label; Longer-lived MCP connections …
- **Product: AI observability** `changelog[Product: AI observability]`=9: Backfill LLM evaluations; Better Sentiment results; Bring your own OpenAI-compatible endpoint for online evals …
- **Background jobs (Temporal/Celery/Dagster)** `changelog[Background jobs (Temporal/Celery/Dagster)]`=8: Clearer view failure digests; Evaluate complete AI sessions; Get materialized view failure alerts …
- **Frontend platform (shared UI/query)** `changelog[Frontend platform (shared UI/query)]`=6: Control access to AI properties; Filter insight chart annotations by scope; Manage access control rules only via Terraform …
- **Product: Error tracking** `changelog[Product: Error tracking]`=6: Error tracking releases tab; Filter exceptions by recordings; Pause exception ingestion …
- **Product: Access control** `changelog[Product: Access control]`=4: Access control now uses the most specific rule; Inspect access with AI; Manage access rules through MCP …
- **Product: Replay vision** `changelog[Product: Replay vision]`=4: 5 new MCP tools; 21 new MCP tools; 44 new MCP tools …
- **Product: Experiments** `changelog[Product: Experiments]`=3: 16 new MCP tools; 19 new MCP tools; 21 new MCP tools
- **Frontend tooling/design system** `changelog[Frontend tooling/design system]`=2: Set trend chart y-axis ranges; SQL as scatter plots
- **MCP server** `changelog[MCP server]`=2: 44 new MCP tools; 19 new MCP tools
- **Product: Canvas** `changelog[Product: Canvas]`=2: 9 new MCP tools; 21 new MCP tools
- **Product: Conversations** `changelog[Product: Conversations]`=2: 5 new MCP tools; 44 new MCP tools
- **Product: Customer analytics** `changelog[Product: Customer analytics]`=2: 21 new MCP tools; 19 new MCP tools
- **Product: Data modeling** `changelog[Product: Data modeling]`=2: Navigate lineage search results; See what blocks view deletion
- **Product: Data quality** `changelog[Product: Data quality]`=2: 16 new MCP tools; 19 new MCP tools
- **Product: Desktop** `changelog[Product: Desktop]`=2: Charts in Slack answers; Self-driving inbox redesign
- **Product: MCP analytics** `changelog[Product: MCP analytics]`=2: Find MCP sessions with errors; 19 new MCP tools
- **Product: Workflows** `changelog[Product: Workflows]`=2: Send email broadcasts; 19 new MCP tools
- **Product: Alerts** `changelog[Product: Alerts]`=1: See alert delivery details
- **Product: Annotations** `changelog[Product: Annotations]`=1: 5 new MCP tools
- **Product: Approvals** `changelog[Product: Approvals]`=1: Turn off approval emails
- **Product: Billing alerts** `changelog[Product: Billing alerts]`=1: 19 new MCP tools
- **Product: Data catalog** `changelog[Product: Data catalog]`=1: 19 new MCP tools
- **Product: Data warehouse** `changelog[Product: Data warehouse]`=1: 21 new MCP tools
- **Product: Endpoints** `changelog[Product: Endpoints]`=1: Trace endpoint dependencies
- **Product: Logs** `changelog[Product: Logs]`=1: 9 new MCP tools
- **Product: Marketing analytics** `changelog[Product: Marketing analytics]`=1: 9 new MCP tools
- **Product: Notifications** `changelog[Product: Notifications]`=1: Archived notifications count as read
- **Product: Stamphog** `changelog[Product: Stamphog]`=1: 16 new MCP tools
- **Product: Tasks** `changelog[Product: Tasks]`=1: 9 new MCP tools
- **Product: Today** `changelog[Product: Today]`=1: 19 new MCP tools
- **Product: Visual review** `changelog[Product: Visual review]`=1: 19 new MCP tools
- **Product: Wizard** `changelog[Product: Wizard]`=1: Feature Flags setup in Wizard
- **Query engine (HogQL)** `changelog[Query engine (HogQL)]`=1: Show complete previous-period trends insights
- **Repo config/CI/tooling** `changelog[Repo config/CI/tooling]`=1: Set up Go instrumentation
- **Supporting services/libs** `changelog[Supporting services/libs]`=1: Upload Flutter source context

## 4. Collaboration structure (review graph)

`graph.people`=204 · events: `graph.events.approve`=11803 · `graph.events.review_request`=1341 · `graph.events.comment`=383 · `graph.events.changes_requested`=216 · `graph.events.continue`=37116 · `graph.events.followup_fix`=295 · `graph.events.revert`=5

Communities (Louvain on approve + changes-requested + comment). Purity = share of members with a known team who are on the main team. Key: `community[<id>].<column>`.

| id | size | main_team | purity | review hub (reviews inside) | candidates |
|---|---|---|---|---|---|
| 0 | 45 | surfaces | 0.194 | ★andrewm4894 (214) | ★andrewm4894, ★puemos, ★tatoalo |
| 1 | 30 | developer-experience | 0.176 | ★rnegron (285) | ★MattBro, ★Piccirello, ★gantoine, ★pauldambra, ★rafaeelaudibert, ★rnegron, ★webjunkie |
| 2 | 22 | client-libraries | 0.364 | ★haacked (191) | ★haacked |
| 3 | 20 | product-analytics | 0.364 | mariusandra (151) | ★sakce, ★sampennington, ★thmsobrmlr |
| 4 | 19 | apm | 0.375 | rorylshanks (82) | ★frankh |
| 5 | 15 | warehouse | 0.455 | ★fuziontech (911) | ★Gilbert09, ★danielcarletti, ★fuziontech |
| 6 | 12 | replay | 0.333 | fasyy612 (108) | ★TueHaulund |
| 7 | 11 | web-analytics | 0.333 | lricoy (86) | — |
| 8 | 8 | workflows | 0.333 | ★mayteio (181) | ★dmarchuk, ★mayteio |
| 9 | 7 | ai-observability | 1.0 | Radu-Raicea (78) | — |
| 10 | 6 | — | — | nickbest-ph (134) | ★eli-r-ph |
| 11 | 3 | — | — | tomasfarias (82) | — |
| 12 | 3 | ai-research | 1.0 | MarconLP (57) | — |
| 13 | 2 | website | 1.0 | smallbrownbike (1) | — |

Top bridges by betweenness (connect communities). Key: `bridge[<login>].<column>`.

| login | betweenness | home community | communities reached |
|---|---|---|---|
| ★rafaeelaudibert | 0.0792 | 1 | 12 |
| ★gantoine | 0.0776 | 1 | 13 |
| ★Gilbert09 | 0.0746 | 5 | 11 |
| ★andrewm4894 | 0.0629 | 0 | 11 |
| ★pauldambra | 0.0556 | 1 | 12 |
| ★sampennington | 0.0436 | 3 | 11 |
| ★TueHaulund | 0.0425 | 6 | 10 |
| ★rnegron | 0.0418 | 1 | 12 |
| ★haacked | 0.0398 | 2 | 11 |
| carlos-marchal-ph | 0.0362 | 9 | 10 |

Single points of approval (one person gives ≥80% of an area's approvals): none found

## 5. The candidates in this picture

primary area = area with most of his rule-weighted changed lines; its major_share = that area's share of all major+ episodes (section 1). A team marked "(inferred from area)" is the owner of his primary area in product_owners.tsv, shown only when data/team_map.json has no entry for him. trust_rank percentile is among everyone in the graph. Key: `cand[<login>].<column>`.

| login | team | community | primary area | area major_share | bridge | trust_rank pct |
|---|---|---|---|---|---|---|
| Gilbert09 | warehouse-sources | 5 | Product: Warehouse sources (87.7% of his work, top changer) | 15.2% | yes | 96 |
| pauldambra | blitzscale | 1 | Frontend platform (shared UI/query) (33.5% of his work, top changer) | 1.3% | yes | 99 |
| webjunkie | developer-experience | 1 | Repo config/CI/tooling (24.1% of his work, top changer) | 2.2% | no | 100 |
| puemos | surfaces | 0 | Product: Desktop (54.5% of his work, top changer) | 3.4% | no | 95 |
| rnegron | developer-experience | 1 | Product: Engineering analytics (42.6% of his work, top changer) | 0.5% | yes | 98 |
| tatoalo | agent-infrastructure | 0 | Product: Tasks (55.4% of his work, top changer) | 2.7% | no | 99 |
| mayteio | workflows (inferred from area) | 8 | Product: Workflows (38.9% of his work) | 1.8% | no | 97 |
| haacked | feature-flags | 2 | Product: Feature flags (13.4% of his work) | 1.0% | yes | 93 |
| rafaeelaudibert | growth | 1 | Hog language/VM (16.0% of his work, top changer) | 0.3% | yes | 98 |
| danielcarletti | warehouse-sources (inferred from area) | 5 | Product: Warehouse sources (93.8% of his work) | 15.2% | no | 69 |
| dmarchuk | workflows | 8 | Product: Workflows (66.1% of his work, top changer) | 1.8% | no | 78 |
| thmsobrmlr | product-analytics | 3 | Frontend scenes (core app pages) (22.4% of his work) | 3.1% | no | 88 |
| sakce | data-modeling (inferred from area) | 3 | Product: Data modeling (26.5% of his work, top changer) | 0.6% | no | 87 |
| Piccirello | security | 1 | Django platform (API/models/auth) (43.9% of his work) | 10.9% | no | 76 |
| sampennington | product-analytics | 3 | Product: Product analytics (38.8% of his work, top changer) | 0.5% | yes | 87 |
| TueHaulund | replay | 6 | Product: Replay vision (76.2% of his work, top changer) | 1.7% | yes | 80 |
| frankh | apm | 4 | ClickHouse data layer (42.1% of his work) | 1.7% | no | 96 |
| eli-r-ph | unknown | 10 | Ingestion (rust) (27.3% of his work) | 2.9% | no | 97 |
| gantoine | developer-experience | 1 | Repo config/CI/tooling (32.3% of his work) | 2.2% | yes | 95 |
| andrewm4894 | self-driving (inferred from area) | 0 | Product: Autoresearch (39.4% of his work, top changer) | 0.3% | yes | 70 |
| MattBro | growth (inferred from area) | 1 | Product: Growth (48.5% of his work, top changer) | 0.3% | no | 94 |
| fuziontech | warehouse | 5 | Product: Warehouse sources (44.2% of his work) | 15.2% | no | 31 |
