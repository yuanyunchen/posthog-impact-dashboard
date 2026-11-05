import pytest

from impact import config as C
from impact.fine import workstreams as W
from impact.fine.matrix import build_matrix, major_episodes
from impact.fine.roles import role_profile


def pr(n, path, scope="x", day=1, author="alice", reviews=(), lines=50):
    return {"number": n, "title": f"feat({scope}): change {n}", "author": author, "credited_to": author, "in_window": True,
            "merged_at": f"2026-08-{day:02d}T10:00:00Z", "additions": lines, "deletions": 0,
            "files": [{"path": path, "additions": lines, "deletions": 0}],
            "reviews": [{"author": a, "is_bot": b, "state": "APPROVED"} for a, b in reviews]}


def tri(prs, tier="substantive", over=None):
    return [{"number": p["number"], "tier": (over or {}).get(p["number"], tier), "work_type": "feature", "summary": f"s{p['number']}"}
            for p in prs]


def spread(n_areas, per=2):
    """n_areas product areas, `per` PRs each, 10 days apart so episodes never bridge areas."""
    return [pr(a * 10 + i, f"products/prod{a}/backend/m{i}.py", scope=f"p{a}", day=1 + (a * per + i) % 28)
            for a in range(n_areas) for i in range(per)]


def test_cluster_count_between_min_and_max():
    for n_areas in (5, 12):
        prs = spread(n_areas)
        ws = W.cluster(prs, tri(prs))
        assert C.WS_MIN <= len(ws) <= C.WS_MAX
        assert sorted(x["number"] for w in ws for x in w["prs"]) == sorted(p["number"] for p in prs)  # nothing lost
    ws = W.cluster(spread(12), tri(spread(12)))
    misc = [w for w in ws if w["id"] == W.MISC][0]
    assert len(misc["merged_areas"]) == 12 - (C.WS_MAX - 1)  # overflow folded in and named, not dropped
    assert misc["title"] == f"杂项（含 {2 * len(misc['merged_areas'])} 条实质及以上）"


def test_same_dominant_scope_merges_across_areas():
    devex = [pr(i, p, scope="devex", day=1 + 8 * i) for i, p in
             enumerate(["posthog/api/a.py", ".github/workflows/ci.yml", "posthog/temporal/x.py", "products/feature_flags/b.py"])]
    other = [pr(10, "products/surveys/s.py", scope="surveys", day=3), pr(11, "products/mcp/m.py", scope="mcp", day=5)]
    tie = [pr(20, "products/tasks/t.py", scope="devex", day=2), pr(21, "products/tasks/u.py", scope="egress", day=20)]
    ws = W.cluster(devex + other + tie, tri(devex + other + tie))
    assert len(ws) == 3
    [d] = [w for w in ws if w["title"].endswith("· devex")]
    assert [x["number"] for x in d["prs"]] == [0, 1, 2, 3, 20, 21] and len(d["areas"]) == 5  # 1:1 tie → his usual scope


def test_cluster_splits_one_area_by_scope_and_allows_fewer_for_few_prs():
    prs = [pr(i, "products/a/x.py", scope=s, day=1 + 9 * k) for k, s in enumerate("abc") for i in (10 * k + 1, 10 * k + 2)]
    assert len(W.cluster(prs, tri(prs))) == 3
    few = spread(1, per=2)
    assert 1 <= len(W.cluster(few, tri(few))) < C.WS_MIN


def test_mechanical_goes_to_misc():
    prs = spread(4)
    mech = pr(999, "products/prod0/backend/m0.py", scope="p0", day=1)
    ws = W.cluster(prs + [mech], tri(prs + [mech], over={999: "mechanical"}))
    assert [w["id"] for w in ws if 999 in {x["number"] for x in w["prs"]}] == [W.MISC]
    assert [w["title"] for w in ws if w["id"] == W.MISC] == ["杂项维护"] and len(ws) == 5


def test_agg_and_top_prs_from_script_with_l1_summaries():
    prs = [pr(1, "products/a/x.py", day=1, reviews=[("bob", False)], lines=10),
           pr(2, "products/a/y.py", day=4, reviews=[("bob", False), ("greptile-apps", True), ("stamphog", False)], lines=20),
           pr(3, "products/a/z.py", day=5, lines=5)]
    read = {"number": 1, "P": 6.0, "L": 2, "Q": 1, "summary": "deep summary", "llm_error": None}
    failed = {"number": 3, "P": 0.0, "L": 0, "Q": 0, "llm_error": "timeout"}  # failed deep read → tier points, no averages
    [w] = W.cluster(prs, tri(prs, over={2: "routine", 3: "major"}), [read, failed])
    assert w["agg"]["points_sum"] == 16.0  # P 6 for #1 + routine 2 for #2 + major 8 for #3
    assert w["agg"]["tier_counts"] == {"substantive": 1, "routine": 1, "major": 1} and w["agg"]["deepread_n"] == 1
    assert (w["agg"]["L_mean"], w["agg"]["Q_mean"], w["agg"]["span_days"]) == (2, 1, 4)
    assert w["top_prs"] == [3, 1, 2]
    assert [(p["number"], p["P"], p["summary"]) for p in w["prs"]] == [(1, 6.0, "deep summary"), (2, None, "s2"), (3, None, "s3")]
    assert w["collaborators"] == [{"login": "bob", "prs_reviewed": 2}]  # bot reviewers excluded
    assert w["title"] == "Product: a · x" and w["area"] == "Product: a"


def test_role_profile_excludes_bots_and_merges_network():
    prs = [pr(1, "products/a/x.py", author="alice", reviews=[("bob", False), ("greptile-apps", True), ("stamphog", False)]),
           pr(2, "products/a/y.py", author="bob", reviews=[("alice", False)]),
           pr(3, "products/a/z.py", author="carol", reviews=[("alice", False), ("alice", False)]),
           {**pr(4, "products/a/w.py", author="posthog", reviews=[("alice", False)]), "credited_to": None, "author_is_bot": True},
           pr(5, "products/b/q.py", author="renovate", reviews=[("alice", False)])]
    r = role_profile("alice", prs, {"alice": ["t1"]})
    assert r["top_reviewed"] == [{"login": "bob", "prs": 1}, {"login": "carol", "prs": 1}]  # distinct PRs, no bot authors
    assert r["top_reviewers"] == [{"login": "bob", "prs": 1}] and r["reviewers_n"] == 1
    assert r["team"] == ["t1"] and r["network"] is None  # no team graph → unknown, not zeros
    assert r["top_area"] == "Product: a" and r["top_area_share"] == 1.0 and r["top_area_authors_n"] == 3
    assert r["team_inferred"] is None  # official team wins
    assert role_profile("alice", prs, {})["team_inferred"] is None  # "Product: a" has no owner row
    flags = [pr(7, "products/feature_flags/backend/x.py", author="dana")]
    assert role_profile("dana", flags, {})["team_inferred"] == "feature-flags"  # owner from product_owners.tsv
    graph = {"people": {"alice": {"first_pass_rate": 0.8}}, "trust_rank": {"alice": 0.1}, "importance_flow": {}}
    assert role_profile("alice", prs, None, graph)["network"] == {"first_pass_rate": 0.8, "trust_rank": 0.1, "importance_flow": None}


def test_matrix_percentile_ties_take_mean_rank():
    logins = ["a", "b", "c", "d", "e"]
    est = {"a": {"delivery_hat": 1}, "b": {"delivery_hat": 2}, "c": {"delivery_hat": 2},
           "d": {"delivery_hat": 3}, "e": {}}
    m = build_matrix(logins, {l: {"prs": 10, "ai_prs": 1, "ai_share": 0.3} for l in logins}, {}, est, {})
    pct = {r["login"]: r["pct"]["delivery"] for r in m["rows"]}
    assert pct == {"a": 0.0, "b": 50.0, "c": 50.0, "d": 100.0, "e": None}
    assert m["missing"]["delivery"] == ["e"] and m["missing"]["quality_rate"] == logins
    assert (m["rows"][0]["values"]["ai_share"], m["rows"][0]["values"]["self_driving_share"]) == (0.3, 0.1) and set(m["columns"]) == set(m["rows"][0]["values"])
    assert all(c["definition"] for c in m["columns"].values())
    assert m["missing"]["trust_rank"] == logins and m["team_graph"].startswith("absent")  # no graph → unknown


def test_matrix_reads_network_columns():
    net = {"a": {"first_pass_rate": {"value": 0.5, "n": 9}, "trust_rank": 0.2, "importance_flow": {"total": 3.0, "author": 3.0}},
           "b": {"first_pass_rate": None, "trust_rank": 0.1}}
    m = build_matrix(["a", "b"], {}, {}, {}, {l: {"network": n} for l, n in net.items()})
    rows = {r["login"]: r for r in m["rows"]}
    assert rows["a"]["values"]["first_pass_rate"] == 0.5 and rows["b"]["values"]["first_pass_rate"] is None  # small sample → None
    assert (rows["a"]["pct"]["trust_rank"], rows["b"]["pct"]["trust_rank"]) == (100.0, 0.0)
    assert rows["a"]["values"]["importance_flow"] == 3.0
    assert "importance_flow" in m["unmapped_network_keys"]  # key-name mismatch surfaces instead of silently missing


def test_major_episodes_counts_episodes_not_prs():
    t = [{"number": 1, "tier": "major"}, {"number": 2, "tier": "major"}, {"number": 3, "tier": "routine"},
         {"number": 4, "tier": "landmark"}]
    assert major_episodes(t, [[1, 2], [3], [4]]) == 2
