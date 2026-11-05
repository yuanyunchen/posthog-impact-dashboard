import json

import pytest

from impact import site_data as S


def _write(d, name, obj):
    p = d / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(o) for o in obj) if name.endswith(".jsonl") else json.dumps(obj))


def _report(login, grade):
    return {"cid": "C01", "positioning": f"{login} builds things", "role": {"primary_role": "Platform builder", "team": "flags"},
            "core_contributions": [{"title": "W1", "evidence_prs": [101]}],
            "angles": {a: {"grade": grade, "rationale": "r"} for a in S.ANGLES}, "overall": {"grade": grade},
            "custom_analyses": [], "calibration": {}, "insights": [], "red_flags": [], "counter_evidence": "", "coverage": {}}


@pytest.fixture
def out(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "DEV_OUT", tmp_path / "no_dev_out")  # isolate from the repo's out/
    monkeypatch.setattr(S, "candidate_tags", lambda items: {l: ["Tag one", "Tag two"] for l in items})  # no network in tests
    monkeypatch.setattr(S, "_llm_each", lambda stage, system, items: {l: {"points": ["Fixed the 3 stalls", "Did something with 99 widgets",
                                                                                 "One two three four five six seven eight nine ten"]} for l in items})
    prs = tmp_path / "prs.jsonl"
    _write(tmp_path, "prs.jsonl", [
        {"in_window": True, "author": "alice", "author_is_bot": False, "ai_assisted": False, "credited_to": "alice"},
        {"in_window": True, "author": "posthog", "author_is_bot": True, "ai_assisted": True, "credited_to": None},
        {"in_window": False, "author": "bob", "author_is_bot": False, "ai_assisted": False, "credited_to": "bob"}])
    d = tmp_path / "out"
    _write(d, "recall_stats.json", {"prs_path": str(prs), "people": 3, "eligible": 2, "recalled": 2, "over_cap": 0,
                                    "route_hits": {"delivery": 2}, "only_route": {"delivery": 1},
                                    "audit_population": 10, "audit_sampled": 5})
    _write(d, "coarse.json", [{"login": l, "tier_counts": {"major": 1, "routine": 2}, "mass": 10.0, "q": 0.9,
                               "quality_factor": 0.9, "team_score": 5.0, "coarse_score": 9.0, "selected_by": ["score"],
                               "recalled_by": ["delivery"]} for l in ("alice", "bob")])
    _write(d, "triage.jsonl", [{"number": 1, "tier": "major", "llm_error": None, "cost": 0.5},
                               {"number": 2, "tier": "routine", "llm_error": "x", "cost": 0.1}])
    _write(d, "matrix.json", {"n": 2, "columns": {"delivery": {"label": "x", "definition": "Σ episodes", "source": "e", "direction": "higher"}},
                              "rows": [{"login": "alice", "values": {"delivery": 3}, "pct": {"delivery": 100.0}}], "missing": {}})
    return d


def test_counts_and_sources(out):
    d = S.build(out)  # no final.json → pending, never invented engineers
    assert d["meta"]["decision_state"] == "pending" and d["top5"] == [] and d["meta"]["placeholder_note"]
    assert d["meta"]["coverage"]["merged_prs"] == 2
    assert d["meta"]["exclusions"] == {"bot_prs": 1, "ai_agent_prs": 1, "ai_agent_credited": 0}
    assert d["tier_distribution"]["all"] == {"major": 1}  # llm_error rows left out, not counted as a tier
    assert [s["n"] for s in d["funnel"]["stages"]] == [3, 2, 2, 2, None]
    assert d["meta"]["sources"]["coarse.json"].endswith("out/coarse.json")
    assert d["meta"]["fixture_sources"] == []
    assert {"alice", "bob"} <= set(d["candidates"])


def test_real_final_wins_and_every_key_is_defined(out):
    people = ["alice", "bob", "carol", "dan", "erin", "fay"]
    entry = lambda l, i: {"login": l, "rank": i + 1, "why": "because", "gates": {"a": True, "b": i != 5, "c": True},
                          "stability": "stable", "stability_freq": 0.9, "borda": 30 - i, "R": 80 - i, "R_rank": i + 1,
                          "evidence": [101]}
    _write(out, "final.json", {"top5": [entry(l, i) for i, l in enumerate(people[:5])], "next5": [entry("fay", 5)],
                               "method_notes": {}})
    _write(out, "decision/primary.json", {"sixth_place_note": "fay missed on quality"})
    _write(out, "decision/devil.json", {"objections": [{"cid": "alice", "objection": "thin", "decision": "keep"}]})
    _write(out, "roles.json", {"bob": {"team": None, "team_inferred": "flags"}})
    for i, l in enumerate(people):
        _write(out, f"candidates/{l}/report.json", _report(l, 8 - i))
    _write(out, "refscore.json", [{"login": l, "R": 80 - i, "angles": {
        "delivery": {"raw": {"delivery_hat": 50 - i, "report:delivery": 8}},
        "quality": {"raw": {"changes_requested_rounds": i * 0.1}}}} for i, l in enumerate(people)])
    d = S.build(out)
    assert d["meta"]["placeholder"] is False
    assert d["top5"][0]["login"] == "alice" and d["top5"][0]["role_label"] == "Platform builder"
    assert d["next5"][0]["not_top5"] == "fay missed on quality"
    assert d["decision"]["devil"][0]["objection"] == "thin"
    assert d["candidates"]["fay"]["team"] == "flags"  # report role.team wins
    assert d["meta"]["decision_state"] == "real"
    # lower-is-better signal: fewest change-request rounds gets the top percentile
    assert d["candidates"]["alice"]["signals"]["changes_requested_rounds"]["pct"] == 100.0
    keys = {k["key"] for p in d["top5"] + d["next5"] for k in p["key_numbers"]}
    keys |= {f"m.{c}" for c in d["matrix"]["columns"]} | {f"grade.{a}" for a in S.ANGLES} | {"gate.a", "gate.b", "gate.c"}
    keys |= {s["key"] for s in d["funnel"]["stages"]} | {f"route.{r}" for r in d["funnel"]["route_hits"]}
    keys |= {v["key"] for v in d["validation"] if v["key"]}
    missing = keys - set(d["definitions"])
    assert not missing, missing
    assert all(d["definitions"][k]["formula"] for k in keys)


def test_inferred_team_label(out):
    _write(out, "roles.json", {"bob": {"team": None, "team_inferred": "warehouse"}, "alice": {"team": ["flags"]}})
    d = S.build(out)
    assert d["candidates"]["bob"]["team"] == "warehouse (inferred)"
    assert d["candidates"]["alice"]["team"] == "flags"


def test_split_prs_moves_lists_out(out):
    _write(out, "workstreams/alice.json", [{"id": "ws1", "title": "Flags", "prs": [{"number": 1, "tier": "major"}] * 3}])
    d = S.build(out)
    moved = S.split_prs(d)
    assert len(moved["alice"][0]["prs"]) == 3  # nothing dropped
    c = d["candidates"]["alice"]
    assert c["workstreams"] is None and c["prs_file"] == "prs/alice.js" and c["workstreams_summary"][0]["prs_n"] == 3


def test_l3_key_numbers_link_to_matrix_with_rank(out):
    r = _report("alice", 8) | {"key_numbers": [{"label": "Delivery estimate (1st of 1)", "value": 3, "metric_key": "delivery"}]}
    _write(out, "candidates/alice/report.json", r)
    d = S.build(out)
    k = d["candidates"]["alice"]["card"]["key_numbers"][0]
    assert k["key"] == "m.delivery" and k["rank"] == 1 and k["of"] == 1 and k["pct"] == 100.0
    assert d["definitions"]["m.delivery"]["unit"] == "pts" and d["definitions"]["m.delivery"]["plain"]


def test_headline():
    assert S._headline("Shared inbound-webhook transport (posthog/ingress) and the end of silent webhook loss") == "Shared inbound-webhook transport"
    assert S._headline("Fix: a typo") == "Fix: a typo"  # prefix before ':' too short, title already fits
    h = S._headline("CI, merge-queue and runtime health for the whole monorepo and every product team")
    assert len(h) <= 50 and h.endswith("…") and not h[:-1].endswith(" ")


def test_card_facts_are_raw_not_weighted(out):
    _write(out, "recall.json", [{"login": l, "metrics": {"prs": n, "reverted": 0, "followup_fixed": 1, "reviews_given": 9,
                                                        "authors_served": 3, "changelog_prs": n % 3, "team_leverage": 99.0,
                                                        "pagerank": 0.5}} for l, n in (("alice", 40), ("bob", 12))])
    d = S.build(out)
    facts = [f for c in d["candidates"].values() for f in c.get("facts", [])]
    assert facts and all(len(c["facts"]) <= 3 for c in d["candidates"].values() if "facts" in c)
    for f in facts:
        k = f["metric_key"]
        assert k.startswith("f.") and k[2:] in S.FACTS and k[2:] not in S.WEIGHTED_KEYS
        assert f["value_text"] and f["trait"] and f["label"] and k in d["definitions"]
    alice = {f["metric_key"]: f for f in d["candidates"]["alice"]["facts"]}
    assert alice["f.merged_prs"]["value_text"] == "40 PRs" and alice["f.merged_prs"]["rank"] == 1


def test_decision_context_maps_cids_and_pairwise(out):
    entry = lambda l, i: {"login": l, "rank": i + 1, "why": f"{l} beat C02", "gates": {}, "primary_rank": i + 1, "second_rank": i + 1}
    _write(out, "final.json", {"top5": [entry("alice", 0)], "next5": [entry("bob", 5), entry("carol", 6)],
                               "method_notes": {"primary_vs_second": {"top5_overlap": 4, "kendall_tau": 0.85}, "sixth_place_note": "C02 nearly"}})
    _write(out, "decision/cids.json", {"C01": "alice", "C02": "bob", "C03": "carol"})
    _write(out, "decision/devil.json", [{"cid": "C01", "objection": "thin vs C02", "replacement_cid": "C02", "rebuttal": "kept", "decision": "keep"}])
    _write(out, "decision/pairwise/C01-C02-ab.json", {"winner": "C01", "reason": "C01 has more majors than C02"})
    _write(out, "decision/pairwise/C01-C02-ba.json", {"winner": "C01", "reason": "same"})
    _write(out, "decision/primary.json", {"ranking": [{"cid": "C01", "rank": 1}, {"cid": "C02", "rank": 2},
        {"cid": "C03", "rank": 3, "comparisons": [{"vs": "C02", "why": "Above C03: C02 has more majors. More text."}]}]})
    _write(out, "decision/second.json", {"ranking": [{"cid": "C01", "rank": 1}, {"cid": "C02", "rank": 6}]})
    d = S.build(out)
    assert d["top5"][0]["why"] == "alice beat bob" and d["next5"][0]["not_top5"] == "bob nearly"
    assert d["next5"][1]["not_top5"] == "Ranked below @bob: bob has more majors."  # no gate text, first sentence only
    dv = d["decision"]["devil"][0]
    assert dv["cid"] == "alice" and dv["replacement"] == "bob" and dv["objection"] == "thin vs bob"
    pw = d["decision"]["pairwise"][0]
    assert pw == {"a": "alice", "b": "bob", "consistent": True, "winner": "alice", "reason": "alice has more majors than bob"}
    g = d["decision"]["agreement"]
    assert g["both_top5"] == ["alice"] and g["pairwise_consistent"] == 1 and g["top5_overlap"] == 4


def test_clean_removes_internal_keys():
    t = S._clean("workflows (inferred from role.team_inferred = workflows; official team mapping is missing), "
                 "#114423, P=16.0, quality_rate 0.95 (P76), peer.followup_fixed 3, ws3 holds 9 PRs")
    assert t == ("workflows, #114423, 16 pts, quality rate 0.95 (76th pct), follow-up fixes 3, workstream 3 holds 9 PRs")


def test_keypoints_are_short_complete_and_use_only_input_numbers(out):
    got = S.candidate_keypoints({"alice": {"contributions": [{"title": "Sync fixes", "outcome": "3 stalls fixed", "numbers": {}}]}})
    assert got == {"alice": ["Fixed the 3 stalls"]}  # invented 99 and the 10-word point are dropped, never cut


def test_published_texts_win_over_final_and_llm(out, monkeypatch):
    _write(out, "final.json", {"top5": [{"login": "alice", "rank": 1, "why": "final.json why", "gates": {}}], "next5": [
        {"login": "bob", "rank": 6, "why": "b", "gates": {"c": False}}], "method_notes": {}})
    for l in ("alice", "bob"):
        _write(out, f"candidates/{l}/report.json", _report(l, 7))
    _write(out, "published.json", {"_method": {"story": "Round one …", "changes_vs_round1": [{"item": "bob", "round1": "5th", "round2": "6th", "reason": "lost"}]},
                                   "alice": {"why": "verified why", "tags": ["Data pipeline"], "keypoints": ["Fixed the loader stall"],
                                             "caveats": ["One caveat"], "headline": "Owner of X"},
                                   "bob": {"why_not_top5": "Ranked 6th behind alice."}})
    asked = []
    monkeypatch.setattr(S, "candidate_tags", lambda items: asked.extend(items) or {})
    d = S.build(out)
    a = d["top5"][0]
    assert a["why"] == "verified why" and a["tags"] == ["Data pipeline"] and a["keypoints"] == ["Fixed the loader stall"]
    assert a["caveats"] == ["One caveat"] and d["candidates"]["alice"]["headline"] == "Owner of X"
    assert d["next5"][0]["not_top5"] == "Ranked 6th behind alice."
    assert "alice" not in asked  # no Flash call where published tags exist
    assert d["meta"]["audit"]["changes"][0]["item"] == "bob"
