"""Path -> (area, tier, owner) and noise class for PostHog/posthog (basis: master tree 2026-11-03, T01.02/S01)."""
import csv
import re
HERE = __file__.rsplit('/', 1)[0]
PRODUCTS = {r[0]: r[1].split(' | ') for r in csv.reader(open(f'{HERE}/product_owners.tsv'), delimiter='\t')}

# noise class, weight (applied before area). First match wins.
NOISE = [
    ('generated', 0.0, r'(^|/)generated/|(^|/)generated\.[a-z]+$|(^|/)generated[-_][^/]*$|\.generated\.|_pb2(_grpc)?\.pyi?$|^posthog/schema\.py$|^frontend/src/queries/(schema\.json|schema/latest-versions\.json|validators\.js|web-analytics-validators\.js)$|^frontend/src/(products\.tsx|lib/posthog-typed\.ts)$|^frontend/src/taxonomy/core-filter-definitions-by-group\.json$|^products/warehouse_sources/sources/[^/]+/_config\.py$|/generated_configs/|/\.sqlx/.*\.json$|^common/hogql_parser/HogQL(Lexer|Parser)|^hog/test/parity/|^packages/personhog-proto/personhog/|canonical-providers\.ts$'),
    ('lockfile', 0.0, r'(^|/)(pnpm-lock\.yaml|uv\.lock|Cargo\.lock|package-lock\.json|yarn\.lock|poetry\.lock|go\.sum)$'),
    ('snapshot', 0.0, r'(^|/)__snapshots__/|\.ambr$|\.snap$'),
    ('migration_pointer', 0.0, r'max_migration\.txt$'),
    ('binary_asset', 0.0, r'\.(png|jpe?g|gif|webp|ico|svg|woff2?|ttf|mp4|lottie)$|^frontend/public/'),
    ('migration', 0.3, r'(^|/)migrations/|_migrations/|^posthog/clickhouse/migrations/'),
    ('agent_config_docs', 0.2, r'^\.(agents|claude|cursor|codex|greptile|zed|idea|vscode|interface-design|posthog-code)/|(^|/)(AGENTS|CLAUDE|CONTEXT|ARCHITECTURE|SPEC|REVIEW)\.md$|(^|/)SKILL\.md$|^docs/|\.mdx?$'),
    ('test', 0.5, r'(^|/)(tests?|__tests__|fixtures|__mocks__|mocks)/|(^|/)test_[^/]*\.py$|_test\.(py|go|rs)$|\.(test|spec)\.[jt]sx?$|^playwright/|\.stories\.tsx?$|conftest\.py$|^\.test_quarantine\.json$'),
    ('ci_build_config', 0.3, r'^\.(github|depot|semgrep|flox|husky|trunk|run|config|dagster_home|stamphog)/|^(bin|devenv|docker|terraform|patches|tools)/|(^|/)(package\.json|tsconfig[^/]*\.json|turbo\.json|pyproject\.toml|Cargo\.toml|go\.mod|Dockerfile[^/]*|docker-compose[^/]*\.yml|owners\.yaml|product\.yaml|\.gitignore)$|^[^/]+$'),
]
NOISE = [(n, w, re.compile(p)) for n, w, p in NOISE]

# area rules: (prefix regex, area, tier). tier: core | product | support | config
AREA = [
    (r'^posthog/hogql/|^posthog/hogql_queries/|^common/hogql_parser/|^rust/hogql/', 'Query engine (HogQL)', 'core'),
    (r'^posthog/clickhouse/|^ee/clickhouse/|^clickhouse-udfs/|^funnel-udf/', 'ClickHouse data layer', 'core'),
    (r'^posthog/(api|models|auth|rbac|session|caching|query_cache|storage|kafka_client|personhog_client|security|helpers)(/|\.py)|^posthog/[^/]+\.py$|^ee/api/', 'Django platform (API/models/auth)', 'core'),
    (r'^posthog/migrations/', 'Django platform (API/models/auth)', 'core'),
    (r'^posthog/temporal/|^posthog/tasks/|^posthog/dags/|^ee/tasks/', 'Background jobs (Temporal/Celery/Dagster)', 'core'),
    (r'^posthog/session_recordings/|^common/replay-', 'Replay', 'product'),
    (r'^posthog/', 'Django platform (misc)', 'support'),
    (r'^ee/hogai/', 'PostHog AI (Max)', 'product'),
    (r'^ee/billing/', 'Billing', 'product'),
    (r'^ee/', 'Enterprise (misc)', 'support'),
    (r'^nodejs/', 'Ingestion pipeline & CDP (nodejs)', 'core'),
    (r'^rust/(capture|capture-logs|capture-apm-metrics|kafka-deduplicator|kafka-assigner|ingestion-|batch-import-worker|property-defs-rs|property-vals-rs|usage-ingestion|common)', 'Ingestion (rust)', 'core'),
    (r'^rust/(feature-flags|flags-consumer|hypercache-server|flags_read_store_migrations)', 'Feature flags service (rust)', 'core'),
    (r'^rust/personhog|^rust/persons_migrations', 'Persons store (personhog)', 'core'),
    (r'^rust/cohort|^rust/behavioral_cohorts', 'Cohorts (rust)', 'product'),
    (r'^rust/cymbal', 'Error tracking (cymbal)', 'product'),
    (r'^rust/(ai-research|embedding-worker)', 'AI research (rust)', 'product'),
    (r'^rust/(replay-anonymizer)', 'Replay', 'product'),
    (r'^rust/', 'Rust services (misc)', 'support'),
    (r'^common/hogvm/|^hog/', 'Hog language/VM', 'core'),
    (r'^frontend/src/(lib|layout|queries|models|styles|exporter|render-query|taxonomy)/|^frontend/src/[^/]+$', 'Frontend platform (shared UI/query)', 'core'),
    (r'^frontend/src/toolbar/', 'Toolbar', 'product'),
    (r'^frontend/src/scenes/', 'Frontend scenes (core app pages)', 'product'),
    (r'^frontend/|^common/(storybook|tailwind|esbuilder)/|^packages/quill/', 'Frontend tooling/design system', 'support'),
    (r'^services/mcp/', 'MCP server', 'product'),
    (r'^services/(llm-gateway|agent-proxy)/|^packages/agent/', 'Agent infrastructure', 'product'),
    (r'^packages/llm-normalizer/', 'AI observability', 'product'),
    (r'^services/|^packages/|^common/|^proto/|^cli/|^livestream/|^share/', 'Supporting services/libs', 'support'),
]
AREA = [(re.compile(p), a, t) for p, a, t in AREA]
SUPPORT_PRODUCTS = {'review_hog', 'stamphog', 'visual_review', 'engineering_analytics', 'commands', 'games', 'demo', 'skills', 'ingestion', 'inbox', 'integrations', 'support', 'session_replay', 'toolbar'}

def noise(path):
    for n, w, rx in NOISE:
        if rx.search(path):
            return n, w
    return 'source', 1.0

def area(path):
    m = re.match(r'^products/([^/]+)/', path)
    if m:
        p = m.group(1); name, owner = PRODUCTS.get(p, [p, '?'])[:2]
        return f'Product: {name}', ('support' if p in SUPPORT_PRODUCTS else 'product'), owner
    for rx, a, t in AREA:
        if rx.search(path):
            return a, t, None
    return 'Repo config/CI/tooling', 'config', None


TIER_MULT = {"core": 1.5, "product": 1.0, "support": 0.7, "config": 0.5}
FORCED_MECHANICAL = {"generated", "lockfile", "snapshot", "migration_pointer", "binary_asset"}  # review-codex R6


def weight(path):
    """Rule weight of one changed file: noise weight × area criticality."""
    n, w = noise(path)
    m = TIER_MULT[area(path)[1]]
    return w * (m if n == "source" else min(1.0, m))  # core boost only for real source, so core migrations stay ≤0.3
