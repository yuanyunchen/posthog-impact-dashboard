import json
import random

import pytest

from impact import config as C
from impact.fine.deepread import fit_diff, score
from impact.fine.dossier import build_dossier
from impact.fine.sample import estimate, stratified_sample

TIERS = ["landmark", "major", "substantive", "routine", "trivial", "mechanical"]


def person(n=60, seed=1):
    rng = random.Random(seed)
    return [{"number": i, "tier": rng.choice(TIERS), "work_type": "feature", "summary": f"s{i}"} for i in range(1, n + 1)]


def read(number, P, L=1, Q=1):
    return {"number": number, "P": P, "L": L, "Q": Q, "llm_error": None}


def test_points_of_level():
    assert C.pr_points(0) == 1
    assert C.pr_points(1.5) == pytest.approx(4)
    assert C.pr_points(3) == pytest.approx(16)
    assert C.pr_level(3, 3, 2) == pytest.approx(3)


def test_quote_check_lowers_subscore():
    source = "# PR #1: Fix billing\n## Body\nFixes   double-charging of\nannual plans."
    raw = {"V": 3, "C": 3, "N": 0, "L": 2, "Q": 2,
           "evidence": {"V": "FIXES DOUBLE-CHARGING of annual plans",  # case + whitespace differ → still verified
                        "C": "invented quote", "N": "", "L": "fix billing", "Q": "not there"}}
    r = score(raw, source)
    assert r["verified"] == {"V": True, "C": False, "N": False, "L": True, "Q": False}
    assert (r["V"], r["C"], r["N"], r["L"], r["Q"]) == (3, 2, 0, 2, 1)  # −1, floor 0
    assert r["ell"] == pytest.approx(C.pr_level(3, 2, 0)) and r["P"] == pytest.approx(C.pr_points(r["ell"]))
    assert score({**raw, "V": 9}, source)["V"] == 3  # clamped to scale
    with pytest.raises(KeyError):
        score({"V": 1}, source)
    wrapped = "+    # A hung build has to end as a step failure,\n+    # not a job timeout.\n**Bold claim** here"
    ok = score({**raw, "evidence": {"V": "A hung build has to end as a step failure, not a job timeout.", "C": "Bold claim here"}}, wrapped)
    assert ok["verified"]["V"] and ok["verified"]["C"]  # diff/comment markers of wrapped lines and ** are ignored
    assert not score({**raw, "evidence": {"V": "A hung build must end as a step failure"}}, wrapped)["verified"]["V"]


def test_diff_budget_keeps_heavy_files():
    lock = "diff --git a/pnpm-lock.yaml b/pnpm-lock.yaml\n" + "+x\n" * 400
    core = "diff --git a/posthog/hogql/parser.py b/posthog/hogql/parser.py\n+def parse(): pass\n"
    text, info = fit_diff(lock + core, limit=200)
    assert info["diff_truncated"] and info["diff_files"] == 2 and info["diff_files_whole"] == 1
    assert core in text and len(text) <= 200 and "\n+diff --git" not in text  # lockfile only gets the leftover budget
    assert fit_diff(core)[1] == {"diff_truncated": False}


def test_sample_deterministic_and_sized():
    p = person()
    a, b = stratified_sample(p), stratified_sample(p)
    assert a == b and stratified_sample(p, seed=C.SEED_ALT) != a
    sizes = {s: sum(1 for t in p if t["tier"] in s.split("+")) for s in C.SAMPLE_PER_STRATUM}
    for s, cap in C.SAMPLE_PER_STRATUM.items():
        assert len(a[s]) == min(cap, sizes[s])
        assert all(next(t for t in p if t["number"] == x)["tier"] in s.split("+") for x in a[s])
    assert "mechanical" not in a
    small = [{"number": 1, "tier": "major"}, {"number": 2, "tier": "routine"}]
    assert stratified_sample(small) == {"major+landmark": [1], "routine": [2]}


def test_estimate_equals_exact_when_all_read():
    p = person(80)
    rng = random.Random(3)
    reads = {t["number"]: read(t["number"], rng.uniform(1, 16), rng.randint(0, 3), rng.randint(0, 2))
             for t in p if t["tier"] != "mechanical"}
    e = estimate(p, reads)
    assert e["delivery_stratified"] == pytest.approx(sum(r["P"] for r in reads.values()))
    assert e["delivery_hat"] == pytest.approx(sum(r["P"] for r in reads.values()))  # no episodes: each PR alone
    assert e["L"] == pytest.approx(sum(r["L"] for r in reads.values()) / len(reads))
    assert e["Q"] == pytest.approx(sum(r["Q"] for r in reads.values()) / len(reads))
    assert e["mechanical"] == sum(t["tier"] == "mechanical" for t in p)
    assert not any(r["fallback"] for r in e["strata"].values())


def test_estimate_fallback_errors_and_calibration():
    p = [{"number": 0, "tier": None}, {"number": 1, "tier": "major"}, {"number": 2, "tier": "landmark"}, {"number": 3, "tier": "routine"},
         {"number": 4, "tier": "routine"}, {"number": 5, "tier": "routine"}, {"number": 6, "tier": "mechanical"}]
    reads = {1: read(1, 4.0), 2: read(2, 99.0) | {"llm_error": "boom"}}
    e = estimate(p, reads, episodes=[[1, 2], [3, 4, 5], [6]])
    ml, r = e["strata"]["major+landmark"], e["strata"]["routine"]
    assert (ml["N"], ml["n"], ml["mean_P"], ml["tier_mean"], ml["calib_diff"]) == (2, 1, 4.0, 8, -4.0)  # errored read excluded
    assert r["fallback"] and r["mean_P"] == 2 and r["mean_L"] is None
    assert e["delivery_stratified"] == pytest.approx(2 * 4.0 + 3 * 2)
    assert e["L"] == 1 and e["llm_errors"] == 1
    assert e["points"] == {1: 4.0, 2: 16, 3: 2, 4: 2, 5: 2, 6: 0}
    assert e["delivery_hat"] == pytest.approx((16 + 0.25 * 4) + (2 + 0.25 * 4) + 0)


def test_dossier_has_no_reference_score():
    triage = [{"number": 10, "tier": "major", "work_type": "feature", "summary": "adds X"}]
    dr = [{"number": 10, "V": 2, "C": 1, "N": 1, "L": 1, "Q": 1, "ell": 1.6, "P": 4.4, "llm_error": None,
           "verified": dict.fromkeys("VCNLQ", True), "evidence": dict.fromkeys("VCNLQ", "q"), "summary": "s",
           "diff_source": "subject", "diff_truncated": False}]
    est = estimate(triage, {10: dr[0]})
    rd = {20: {"number": 20, "reviews": [{"author": "ann", "state": "COMMENTED", "body": "This drops events when the buffer is full; " * 2}],
               "threads": [{"path": "a.py", "is_outdated": True, "comments": [{"author": "ann", "body": "Race here: lock before reading the offset, please."}]}],
               "review_requests": [{"requester": "bob", "reviewer": "ann"}, {"requester": "cy", "reviewer": "ann"}]},
          10: {"number": 10, "reviews": [{"author": "ann", "state": "COMMENTED", "body": "self comment on my own PR, long enough to count"}]}}
    lineage = {"posthog/api/a.py": [{"number": 10, "author_email": "ann@x", "merged_at": "2026-08-06", "added": 30, "deleted": 0},
                        {"number": 30, "author_email": "bob@x", "merged_at": "2026-08-09", "added": 1, "deleted": 0}]}
    d, md = build_dossier("ann", {"prs": 1, "reverted": 0, "followup_fixed": None, "R": 88.0, "refscore": {}},
                          triage, dr, est, rd, lineage, {"10": [{"title": "X launched", "date": "2026-08-07"}]}, {"ann": ["Team A"]})
    blob = json.dumps(d)
    assert '"R"' not in blob and "refscore" not in blob and "88.0" not in blob and "88.0" not in md
    assert d["reviews_given"][0]["led_to_change"] is True and all(x["number"] == 20 for x in d["reviews_given"])
    assert d["peer"] == {"reverted": 0, "followup_fixed": None, "downstream_authors": 1, "requested_by": 2}
    assert d["changelog"] == [{"number": 10, "title": "X launched", "date": "2026-08-07"}]
    assert "- X launched (2026-08-07): #10" in md
    assert d["coverage"]["metrics"] == 0.67 and d["coverage"]["missing"] == ["followup_fixed"]
    assert "`metrics.prs`=1" in md and "`peer.downstream_authors`=1" in md and "`estimate.delivery_hat`=" in md
    assert "(workstreams not provided)" in md and "(role profile not provided)" in md
    d2, md2 = build_dossier("ann", None, triage, dr, est, None, None, None, None)
    assert d2["reviews_given"] is None and "review_detail missing" in md2


def test_dossier_v6_structures_smoke():
    """Workstreams and role profile as the fine-synth track writes them (out/workstreams/<login>.json, out/roles.json)."""
    triage = [{"number": n, "tier": t, "summary": f"sum{n}"} for n, t in [(1, "major"), (2, "routine"), (3, "trivial")]]
    dr = [{"number": 1, "V": 3, "C": 2, "N": 1, "L": 2, "Q": 2, "ell": 2.3, "P": 8.5, "llm_error": None,
           "verified": dict.fromkeys("VCNLQ", True), "evidence": dict.fromkeys("VCNLQ", "q"), "summary": "deep sum1",
           "diff_source": "commit_authors", "diff_truncated": True}]
    ws = [{"id": "ws1", "title": "Product: Feature flags · flags", "area": "Product: Feature flags", "merged_areas": [],
           "prs": [{"number": 1, "tier": "major", "P": 8.5, "summary": "deep sum1"}, {"number": 2, "tier": "routine", "P": None, "summary": "sum2"}],
           "agg": {"prs_n": 2, "deepread_n": 1, "tier_counts": {"major": 1, "routine": 1}, "points_sum": 10.5,
                   "L_mean": 2.0, "Q_mean": None, "span_days": 3, "lines": 120},
           "top_prs": [1, 2], "collaborators": [{"login": "bob", "prs_reviewed": 2}]}]
    role = {"login": "ann", "team": ["flags"], "reviewed_authors_n": 4, "top_reviewed": [{"login": "bob", "prs": 3}],
            "top_area": "Product: Feature flags", "top_area_leader": None,
            "network": {"requesters_n": 3, "first_pass_rate": 0.8, "trust_rank": None, "teams": {"flags": 2}}}
    d, md = build_dossier("ann", {"prs": 3, "affected_prs": []}, triage, dr, estimate(triage, {1: dr[0]}), None, None, None,
                          None, workstreams=ws, role_profile=role)
    assert "None" not in md and "{" not in md
    heads = [l for l in md.splitlines() if l.startswith("## ")]
    assert heads[:2] == ["## 工作流", "## 团队角色"]
    assert "`ws.ws1.agg.points_sum`=10.5" in md and "`ws.ws1.agg.tier_counts.major`=1" in md and "bob (2)" in md
    assert "### ws1 Product: Feature flags · flags\narea: Product: Feature flags\n" in md
    assert "- #1 major `P`=8.5 (V3 C2 N1 L2 Q2): sum1\n- #2 routine: sum2" in md
    assert "- `role.network.first_pass_rate`: 0.8" in md and "- `role.network.teams.flags`: 2" in md
    assert "- `role.top_reviewed`: bob prs 3" in md
    assert [p["workstream"] for p in d["prs"]] == ["ws1", "ws1", None]
    assert "not in any workstream" in md and "- #3 trivial: sum3" in md and md.count("#2 routine") == 1
    assert d["coverage"]["diff_truncated_share"] == 1.0


def test_downstream_skips_noise_and_hub_files():
    from impact.fine.dossier import downstream_authors
    e = lambda n, who, day, lines=30: {"number": n, "author_email": f"{who}@x", "merged_at": f"2026-08-{day:02d}T00:00:00Z",
                                        "added": lines, "deleted": 0}
    mine = [e(1, "ann", 6)]
    lineage = {
        "posthog/api/feature.py": mine + [e(2, "bob", 7, 1), e(3, "renovate[bot]", 8)],             # counts: bob
        "posthog/api/tests/test_feature.py": mine + [e(4, "cy", 7)],                                 # test class: skip
        "services/mcp/src/api/generated.ts": mine + [e(5, "dee", 7)],                                # generated: skip
        "frontend/src/lib/constants.tsx": mine + [e(10 + i, f"u{i}", 9) for i in range(C.HUB_FILE_AUTHORS)],  # hub: skip
        "frontend/src/lib/small.tsx": [e(1, "ann", 6, 5), e(6, "eve", 7)],                           # he changed <20 lines
    }
    assert downstream_authors({1}, lineage) == 1
    assert downstream_authors({1}, None) is None


def test_dossier_caps_prs_per_workstream():
    tiers = ["routine"] * 30 + ["major"] * 6 + ["substantive"] * 4
    triage = [{"number": n, "tier": t, "summary": f"s{n}"} for n, t in enumerate(tiers, 1)]
    prs = [{"number": n, "title": f"t{n}", "merged_at": f"2026-08-{5 + n % 20:02d}T00:00:00Z", "files": [], "author": "ann"}
           for n in range(1, 41)]
    reads = [{"number": n, "V": 1, "C": 1, "N": 0, "L": 1, "Q": 1, "ell": 0.85, "P": 2.2, "llm_error": None,
              "verified": dict.fromkeys("VCNLQ", True), "evidence": dict.fromkeys("VCNLQ", "q"), "summary": "d",
              "diff_source": "commit_authors", "diff_truncated": False} for n in (2, 3)]
    ws = [{"id": "ws1", "title": "Big", "area": "Product: X", "prs": [{"number": n} for n in range(1, 41)], "agg": {}, "top_prs": []}]
    _, md = build_dossier("ann", {}, triage, reads, estimate(triage, {r["number"]: r for r in reads}), None, None, None, None,
                          prs=prs, workstreams=ws)
    block = md.split("### ws1")[1].split("\n## ")[0]
    lines = [l for l in block.splitlines() if l.startswith("- #")]
    assert len(lines) == C.DOSSIER_PRS_PER_WS
    assert [l.split()[1] for l in lines[:2]] == ["#3", "#2"]  # deep-read first, newest first
    # then the 6 majors newest first (merged day = 5 + n % 20), then substantive
    majors = sorted(range(31, 37), key=lambda n: -(5 + n % 20))
    assert [int(l.split()[1][1:]) for l in lines[2:8]] == majors and all(" major" in l for l in lines[2:8])
    assert all(" substantive" in l for l in lines[8:12]) and " routine" in lines[12]
    assert f"- … {40 - C.DOSSIER_PRS_PER_WS} more PRs in this workstream: `python -m impact.fine.query ann prs --ws ws1`" in block
