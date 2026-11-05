import json
from pathlib import Path

import pytest

from impact import site_network as S
from impact.fine import team_graph as TG

TIERS = ["trivial", "routine", "substantive", "major", "landmark"]


def rv(author, state="APPROVED", at="2026-08-06T00:00:00Z", is_bot=False):
    return {"author": author, "is_bot": is_bot, "state": state, "submitted_at": at, "body_len": 0}


def pr(n, author, reviews=(), merged="2026-08-10T00:00:00Z", path="posthog/api/x.py"):
    bot = TG.C.is_bot(author)
    return {"number": n, "title": f"feat: change {n}", "body": "", "author": author, "author_is_bot": bot,
            "credited_to": None if bot else author, "created_at": "2026-08-05T00:00:00Z", "merged_at": merged,
            "in_window": True, "files": [{"path": path, "additions": 30, "deletions": 0}], "reviews": list(reviews),
            "commits": 1, "review_requests": None}


def world(people=90):
    """people p00…, each authors 3 PRs reviewed by the next two; plus a bot PR and a bot reviewer."""
    names = [f"p{i:02d}" for i in range(people)]
    prs, n = [], 1000
    for i, a in enumerate(names):
        for j in range(3):
            n += 1
            prs.append(pr(n, a, [rv(names[(i + 1) % people]), rv(names[(i + 2) % people]),
                                 rv("greptile-apps", "COMMENTED", is_bot=True)],
                          merged=f"2026-08-{10 + j:02d}T00:00:00Z", path=f"posthog/api/m{i // 10}.py"))
    prs.append(pr(9999, "renovate", [rv("p00")]))
    triage = [{"number": p["number"], "tier": TIERS[p["number"] % 5], "llm_error": None} for p in prs]
    events = TG.build_events(prs)
    points, _ = S.load_points(triage)
    tg = {"summary": {"points_seeded_prs": len(points)}, "importance_flow": TG.importance_flow(prs, points, events),
          "people": TG.person_metrics(events, prs), **TG.team_structure(events, None)}
    coarse = [{"login": a, "selected_by": ["score"]} for a in names[-20:]]  # mostly outside the flow top → cap binds
    return prs, events, triage, tg, coarse


@pytest.fixture(scope="module")
def built():
    prs, events, triage, tg, coarse = world(150)
    return S.assemble(prs, events, triage, tg, coarse, None, None)


def test_node_cap():
    picked, cut = S.pick_nodes([f"c{i}" for i in range(20)], [f"f{i}" for i in range(50)],
                               [f"b{i}" for i in range(10)], [f"h{i}" for i in range(14)])
    assert len(picked) == S.NODE_CAP and picked[:20] == [f"c{i}" for i in range(20)]
    assert cut == [f"f{i}" for i in range(16, S.FLOW_TOP)]  # the cut is reported, never silent


def test_built_caps(built):
    core = [p for p in built["people"] if p["core"]]
    assert len(core) == S.NODE_CAP and built["meta"]["cut_nodes"]  # this world has more than 60 eligible
    assert all(len(ns) <= S.NEIGHBOR_CAP for ns in built["ego"].values())
    assert 3 * S.OVERVIEW_PER_KIND <= 150


def test_edge_pool_is_heaviest_per_kind(built):
    P = built["people"]
    for k in "rcf":
        core_k = [e for e in built["edges"] if e[2] == k and P[e[0]]["core"] and P[e[1]]["core"]]
        pool = [e for e in core_k if e[5]]
        assert len(pool) <= S.CORE_EDGES_PER_KIND
        if pool:
            floor = min(e[3] for e in pool)
            assert all(e[3] <= floor for e in core_k if not e[5])  # threshold: nothing heavier left out


def test_bots_never_in_graph(built):
    ids = {p["id"] for p in built["people"]}
    assert not {"renovate", "greptile-apps"} & ids
    assert not any(TG.C.is_bot(p["id"]) for p in built["people"])
    assert "9999" not in built["prs"]


def test_edge_pr_list_capped_and_sorted():
    tiers = {2000 + i: TIERS[i % 5] for i in range(15)}
    events = [{"type": "approve", "src": "bob", "dst": "alice", "pr": n, "at": f"2026-08-{10 + i:02d}T00:00:00Z"}
              for i, n in enumerate(tiers)]
    points, _ = S.load_points([{"number": n, "tier": t, "llm_error": None} for n, t in tiers.items()])
    e = S.aggregate(events, points)["bob", "alice", "review"]
    assert e["n"] == 15 and e["w"] == sum(points.values())
    assert len(e["prs"]) == S.EDGE_PRS
    pts = [points[n] for n, _, _ in e["prs"]]
    assert pts == sorted(pts, reverse=True)


def test_shipped_pr_lists(built):
    for e in built["edges"]:
        cap = S.EDGE_PRS if e[5] or e[2] == "f" else S.EGO_EDGE_PRS  # overview pool / fix: 10, focus-only: 5
        assert len(e[6]) == min(cap, e[4])
        assert all(built["prs"][ref.rstrip("ARCDVF")][0] for ref in e[6])  # every listed PR carries its title


def test_layout_reproducible():
    prs, events, triage, tg, coarse = world()
    a = S.assemble(prs, events, triage, tg, coarse, None, None)
    b = S.assemble(prs, events, triage, tg, coarse, None, None)
    assert [(p["id"], p["x"], p["y"]) for p in a["people"]] == [(p["id"], p["x"], p["y"]) for p in b["people"]]


def test_ranks_only_from_final(built):
    assert built["meta"]["placeholder"] is True and not any(p["rank"] for p in built["people"])
    prs, events, triage, tg, coarse = world(40)
    d = S.assemble(prs, events, triage, tg, coarse, {"top5": [{"login": "p35", "rank": 1}]}, None)
    assert d["meta"]["placeholder"] is False
    assert [p["id"] for p in d["people"] if p["rank"]] == ["p35"]


def test_build_writes_and_enforces_size(tmp_path, monkeypatch):
    prs, events, triage, tg, coarse = world(40)
    for name in ("REVIEW_DETAIL", "LINEAGE", "TEAM_MAP"):
        monkeypatch.setattr(S.C, name, tmp_path / "absent")
    (tmp_path / "prs.jsonl").write_text("".join(json.dumps(p) + "\n" for p in prs))
    out = tmp_path / "out"
    out.mkdir()
    (out / "triage.jsonl").write_text("".join(json.dumps(t) + "\n" for t in triage))
    (out / "team_graph.json").write_text(json.dumps(tg))
    (out / "coarse.json").write_text(json.dumps(coarse))
    S.build(tmp_path / "prs.jsonl", out, tmp_path / "site")
    site = tmp_path / "site"
    assert (site / "network_data.json").stat().st_size < S.MAX_BYTES
    js = (site / "network_data.js").read_text()  # file:// copy: same data behind a global
    assert js.startswith("window.NETWORK_DATA = ") and js.rstrip().endswith(";")
    assert json.loads(js.strip()[len("window.NETWORK_DATA = "):-1]) == json.loads((site / "network_data.json").read_text())
    monkeypatch.setattr(S, "MAX_BYTES", 1000)
    with pytest.raises(ValueError):
        S.build(tmp_path / "prs.jsonl", out, tmp_path / "site2")


def test_real_output_under_budget():
    f = Path(__file__).resolve().parent.parent / "site" / "network_data.json"
    if not f.exists():
        pytest.skip("site/network_data.json not built")
    assert f.stat().st_size < S.MAX_BYTES
    js = f.with_suffix(".js")
    assert js.exists() and js.read_text().strip()[len("window.NETWORK_DATA = "):-1] == f.read_text()
    d = json.loads(f.read_text())
    assert sum(p["core"] for p in d["people"]) <= S.NODE_CAP


def test_profiles_follow_site_data_then_report():
    sd = {"top5": [{"login": "a", "rank": 1, "stability": "stable"}],
          "candidates": {"a": {"facts": [{"trait": "Prolific shipper", "value_text": "2,939 PRs", "label": "merged PRs"},
                                         {"trait": "Foundation builder", "value_text": "106 engineers", "label": "built on"}],
                               "positioning": "Owner of the warehouse. More text.", "role": {"network_summary": "Lead author. Rest."},
                               "red_flags": [{"flag": "x"}]}}}
    reports = {"b": {"positioning": "Reviewer.", "role": {"primary_role": "gatekeeper", "network_summary": "Main approver."}}}
    p = S.profiles(["a", "b"], sd, reports)
    assert p["a"]["traits"] == ["Prolific shipper", "Foundation builder"] and p["a"]["facts"][0] == ["2,939 PRs", "merged PRs"]
    assert p["a"]["pos"] == "Owner of the warehouse" and p["a"]["stab"] == "stable" and p["a"]["flags"] == 1
    assert p["b"]["traits"] == ["gatekeeper"] and p["b"]["net"] == "Main approver"  # no site_data → report role


def test_insights_counts():
    tg = {"bridges": [{"login": x} for x in "abcd"], "single_points": [],
          "communities": [{"size": 12, "purity": .2, "hub": "a"}, {"size": 30, "purity": .45, "hub": "c"},
                          {"size": 3, "purity": 1.0, "hub": "z"}]}
    ins = S.insights(tg, ["a", "b", "c"], ["a", "x"])
    assert ins[0]["text"].startswith("3 of the top 4 bridges")
    assert "20%–45%" in ins[1]["text"] and ins[1]["nodes"] == ["a", "c"]  # tiny pure community ignored
    assert ins[2]["nodes"] == [] and ins[3]["nodes"] == ["a", "x"]


def test_edge_event_counts():
    ev = [{"type": t, "src": "bob", "dst": "al", "pr": n, "at": "2026-08-10T00:00:00Z"}
          for t, n in [("approve", 1), ("approve", 2), ("comment", 2), ("changes_requested", 3)]]
    e = S.aggregate(ev, {})["bob", "al", "review"]
    assert e["n"] == 3 and e["ev"] == {"A": 2, "C": 1, "R": 1}
