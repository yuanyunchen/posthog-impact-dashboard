import re

import pytest

from impact import config as C
from impact.fine import aggregate as A
from impact.fine import cards as K
from impact.fine.refscore import percentiles, refscore


def angle(g):
    return {"grade": g, "rationale": "r", "claims": [{"statement": "s", "numbers": {"prs": 3}, "evidence_ids": [1, "W1"]}]}


def report(g=5, flags=()):
    contrib = {"workstream_id": "W1", "title": "t", "what": "w", "why_it_matters": "y", "outcome": "o",
               "his_role": "主导", "evidence_prs": [1], "numbers": {"prs": 2}}
    return {"cid": "C01", "positioning": "p", "role": {"primary_role": "平台建设者", "team": "t", "how_they_create_impact": "h",
                     "network_summary": "first_pass_rate 0.9：信得过的批准人"},
            "core_contributions": [contrib, {**contrib, "workstream_id": "W2"}],
            "angles": {a: angle(g) for a in ("delivery", "system", "quality", "team")},
            "overall": {"grade": g, "confidence": "medium"}, "insights": [{"insight": "i", "evidence_ids": ["W2"]}],
            "calibration": {"ranks": {"delivery": 80.0, "quality_rate": 40.0, "team_leverage": 60.0, "trust_rank": None},
                            "note": "upper third on delivery"},
            "custom_analyses": [{"question": "q", "why": "w", "commands": [f"python -m impact.fine.query x {c}"],
                                 "finding": "f", "evidence_ids": [1], "effect": "e"} for c in ("timeline", "rank P")],
            "red_flags": [{"flag": "reverted", "evidence_ids": [n]} for n in flags], "counter_evidence": "none",
            "coverage": {"sampled_prs": 5, "missing_data": [], "diff_truncated_share": 0.0}}


def decision(order, r_dev=None):
    return {"context_summary": "Flags and ingestion drove most major work.",
            "ranking": [{"cid": c, "rank": i + 1, "context_role": "owns area X", "rationale": "r", "comparisons": [{"vs": order[i - 1 if i else 1], "why": "w"}],
                         "deviation": r_dev or ""} for i, c in enumerate(order)],
            "archetype_groups": [{"archetype": "平台建设者", "cids": order[:2], "tradeoff": "t"}],
            "top5_cases": [{"cid": c, "case": "c"} for c in order[:5]], "sixth_place_note": "n",
            "evidence_requests": [{"cid": order[0], "need": "diff of W1"}]}


def test_percentile_ties_share_mean_rank():
    p = percentiles({"a": 1, "b": 2, "c": 2, "d": 3, "e": None})
    assert p == {"a": 0, "b": 50, "c": 50, "d": 100}
    assert percentiles({"a": 5}) == {"a": 50}


def test_unknown_does_not_drag_down():
    # a and b tie on every known signal; b's behavior is unknown and must not lower its delivery score
    people = {"a": {"delivery_hat": 10, "changelog_weighted": 5, "issue_reactions": 5},
              "b": {"delivery_hat": 10, "changelog_weighted": None, "issue_reactions": None},
              "c": {"delivery_hat": 1, "changelog_weighted": 0, "issue_reactions": 0}}
    r = {x["login"]: x["angles"]["delivery"] for x in refscore(people)}
    assert r["b"]["behavior"] is None and r["b"]["coverage"] == "1/3"
    assert r["b"]["score"] == r["b"]["quant"] == 75  # agent unknown before L3 reports
    assert r["a"]["score"] == pytest.approx((75 + 100) / 2)


def test_reports_fill_agent_and_lower_is_better():
    people = {"a": {"changes_requested_rounds": 0.5}, "b": {"changes_requested_rounds": 2}}
    r = {x["login"]: x for x in refscore(people, {"a": report(8), "b": report(3)})}
    assert r["a"]["angles"]["delivery"]["agent"] == 100 and r["b"]["angles"]["delivery"]["agent"] == 0
    assert r["a"]["angles"]["quality"]["behavior"] == 100  # fewer change-request rounds is better
    assert r["a"]["R"] > r["b"]["R"]


def test_borda():
    assert A.borda([["a", "b", "c"], ["b", "a"], ["a"]]) == {"a": 29, "b": 19, "c": 8}


def test_pairwise_reverses_boundary():
    order = ["a", "b", "c", "d", "e", "f", "g", "h", "i"]  # Borda d > e, but e beats d in both orders
    pw = [{"a": "d", "b": "e", "order": "ab", "winner": "e"}, {"a": "d", "b": "e", "order": "ba", "winner": "e"}]
    assert A.boundary_resolve(order, pw) == ["a", "b", "c", "e", "d", "f", "g", "h", "i"]
    # orders disagree → tie → Borda position kept; pairs outside ranks 4–8 are ignored
    pw = [{"a": "d", "b": "e", "order": "ab", "winner": "e"}, {"a": "d", "b": "e", "order": "ba", "winner": "d"},
          {"a": "a", "b": "i", "order": "ab", "winner": "i"}, {"a": "a", "b": "i", "order": "ba", "winner": "i"}]
    assert A.boundary_resolve(order, pw) == order


def facts_for(logins, **over):
    f = {x: {"major": 3, "landmark": 0, "team_leverage": 0, "reverted": 0, "followup_rate": 0, "top7_share": 1}
         for x in logins}
    for x, v in over.items():
        f[x].update(v)
    return f


def test_gates_backfill_two_consecutive_failures():
    order = list("abcdefgh")
    facts = facts_for(order, c={"major": 0}, d={"reverted": 3}, g={"major": 0})
    top, log = A.apply_gates(order, facts, {})
    assert top == ["a", "b", "e", "f", "h"]
    assert [x["login"] for x in log if x["action"] == "dropped"] == ["c", "d", "g"]
    top, _ = A.apply_gates(order, facts, {"d": "revert 是上游事故，非本人质量问题"})
    assert top == ["a", "b", "d", "e", "f"]
    assert A.apply_gates(list("abc"), facts_for("abc", b={"top7_share": 1 / 3}), {})[0] == ["a", "c"]  # exhausted


def test_gate_a_team_top3_and_followup_worst():
    logins = list("abcdef")
    facts = facts_for(logins, a={"major": 0, "team_leverage": 9}, f={"followup_rate": 0.5})
    assert A.check_gates("a", facts)["a"]  # no majors but team leverage top 3
    assert not A.check_gates("f", facts)["b"]  # worst follow-up rate
    assert A.check_gates("b", facts)["b"]  # all-zero ties are not a red flag


def test_sensitivity_deterministic():
    people = {f"p{i}": {"delivery_hat": i, "core_share": (i * 7) % 5, "quality_rate": (i * 3) % 4,
                        "review_leverage": 8 - i} for i in range(8)}
    rs = refscore(people)
    f1, f2 = A.weight_sensitivity(rs, n=200), A.weight_sensitivity(rs, n=200)
    assert f1 == f2 and sum(f1.values()) == pytest.approx(C.FINAL_N)
    assert A.stability_label(0.7) == "stable" and A.stability_label(0.4) == "borderline"
    assert A.stability_label(0.39) == "verdict_only"


def test_disputed_pairs_and_agreed_order_kept():
    order = list("abcdefgh")  # consensus; zone = d e f g h
    primary, second = list("abcdefgh"), list("abcdgfeh")  # disagree on e/f, e/g, f/g
    assert A.disputed_pairs(order, primary, second) == [("e", "f"), ("e", "g"), ("f", "g")]
    pw = [{"a": "e", "b": "g", "order": o, "winner": "g"} for o in ("ab", "ba")]
    # g beats e by pairwise; agreed pairs keep d first and h last; e/f and f/g stay tied
    assert A.boundary_resolve(order, pw, agreed=[primary, second]) == list("abcdgefh")


def test_kendall_tau():
    assert A.kendall_tau(list("abcd"), list("abcd")) == 1
    assert A.kendall_tau(list("abcd"), list("dcba")) == -1
    assert A.kendall_tau(list("abc"), list("acb")) == pytest.approx(1 / 3)


def test_finalize_consensus_over_primary_second_r():
    logins = list("abcdefgh")
    cid = {f"C{x}": x for x in logins}
    people = {x: {"delivery_hat": 10 - i} for i, x in enumerate(logins)}  # R order a..h
    rs = refscore(people)
    prim, sec = decision([f"C{x}" for x in "abcdefgh"]), decision([f"C{x}" for x in "bacdefgh"])
    f = A.finalize(rs, prim, sec, [], facts_for(logins), {}, cid, {x: report() for x in logins})
    assert [x["login"] for x in f["top5"]] == list("abcde")  # Borda a 29, b 28
    n = f["method_notes"]
    assert n["primary_vs_second"] == {"top5_overlap": 5, "kendall_tau": pytest.approx(1 - 2 / 28, abs=1e-3)}
    assert n["disputed_pairs"] == [] and f["top5"][0]["evidence"] == [1]


def test_parse_report_extracts_json_from_prose():
    import json
    text = "好的，报告如下：\n```json\n" + json.dumps(report(7, flags=(1,)), ensure_ascii=False) + "\n```\n以上。"
    r = K.parse_report(text, "alice", known_prs={1}, known_workstreams={"W1", "W2"}, flag_prs={1})
    assert r["login"] == "alice" and r["overall"]["grade"] == 7
    with pytest.raises(ValueError, match="not in dossier"):
        K.parse_report(text, "alice", known_prs={2})
    with pytest.raises(ValueError, match="red-flag"):  # a dossier red flag must be passed up, not averaged away
        K.parse_report(json.dumps(report()), "alice", flag_prs={1})


def test_parse_report_missing_fields():
    import json
    for mutate, msg in [(lambda r: r.pop("counter_evidence"), "counter_evidence"),
                        (lambda r: r["angles"]["team"]["claims"][0].pop("evidence_ids"), "evidence_ids"),
                        (lambda r: r["angles"].pop("system"), "system"),
                        (lambda r: r["core_contributions"].pop(), "2–3"),
                        (lambda r: r["overall"].update(grade=11), "1–10"),
                        (lambda r: r["coverage"].pop("diff_truncated_share"), "coverage"),
                        (lambda r: r["role"].pop("network_summary"), "network_summary"),
                        (lambda r: r["custom_analyses"].pop(), "custom_analyses"),
                        (lambda r: r["calibration"]["ranks"].pop("trust_rank"), "trust_rank"),
                        (lambda r: r.update(key_numbers=[{"label": "x", "value": 1, "metric_key": "delivery"}]), "key_numbers"),
                        (lambda r: r["calibration"]["ranks"].update(delivery="high"), "percentiles"),
                        (lambda r: r["custom_analyses"][0].update(commands=["cat diff"]), "impact.fine.query")]:
        bad = report()
        mutate(bad)
        with pytest.raises(ValueError, match=msg):
            K.parse_report(json.dumps(bad), "a")


def test_parse_decision_and_pairwise():
    import json
    cids = ["C1", "C2", "C3", "C4", "C5", "C6"]
    d = K.parse_decision("决策：" + json.dumps(decision(cids[::-1])), "primary", cids)
    assert [e["cid"] for e in d["ranking"]] == cids[::-1] and d["judge"] == "primary"
    with pytest.raises(ValueError, match="deviation"):
        K.parse_decision(json.dumps(decision(cids)), "p", cids, r_rank={c: 7 - i for i, c in enumerate(cids)})
    with pytest.raises(ValueError, match="covering"):
        K.parse_decision(json.dumps(decision(cids[:5])), "p", cids)
    bad = decision(cids)
    bad["top5_cases"] = bad["top5_cases"][:4]
    with pytest.raises(ValueError, match="top5_cases"):
        K.parse_decision(json.dumps(bad), "p", cids)
    bad = decision(cids)
    bad["ranking"][2]["context_role"] = ""
    with pytest.raises(ValueError, match="context_role"):
        K.parse_decision(json.dumps(bad), "p", cids)
    bad = decision(cids)
    del bad["context_summary"]
    with pytest.raises(ValueError, match="context_summary"):
        K.parse_decision(json.dumps(bad), "p", cids)
    bad = decision(cids)
    bad["ranking"][0]["comparisons"] = []
    with pytest.raises(ValueError, match="comparisons"):
        K.parse_decision(json.dumps(bad), "p", cids)
    p = K.parse_pairwise('结论 {"winner": "C2", "reason": "更重大"}', "C1", "C2", "ba")
    assert p["winner"] == "C2" and p["order"] == "ba"
    with pytest.raises(ValueError):
        K.parse_pairwise('{"winner": "tie", "reason": "x"}', "C1", "C2", "ab")


def test_anonymize_all_candidates():
    md = "# alice (Alice Smith)\n@alice beat bob on #123; https://github.com/alice; a@b.com; alicex stays"
    out = K.anonymize(md, {"alice": "C04", "bob": "C02"}, names={"alice": ("Alice Smith",)})
    assert out == "# C04 (C04)\nC04 beat C02 on #123; C04; [email]; alicex stays"
    brief = K.l3_brief("out/candidates/alice")
    assert not __import__("re").search(r"\{[a-z_]+\}", brief)  # every placeholder filled from the pack path alone
    assert "python -m impact.fine.query alice rank trust_rank" in brief and '"cid": "alice"' in brief
    assert '"ranks": {"delivery": 85.0,' in brief and '"trust_rank": null}' in brief


def test_contracts_cli(tmp_path):
    import json
    import subprocess
    import sys
    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    good.write_text(json.dumps(report()))
    r = report()
    del r["custom_analyses"][1]
    bad.write_text(json.dumps(r))
    run = lambda f: subprocess.run([sys.executable, "-m", "impact.contracts", "report", str(f)], capture_output=True, text=True)
    assert run(good).stdout.strip() == "OK"
    out = run(bad)
    assert out.returncode != 0 and "custom_analyses" in out.stderr


def test_cli_writes_dashboard_paths(tmp_path):
    import json
    logins = [f"u{i}" for i in range(8)]
    rows = [{"login": l, "values": {"delivery": 100 - 10 * i, "team_leverage": i, "quality_rate": 0.9},
             "pct": {"delivery": 100 - 14 * i}} for i, l in enumerate(logins)]
    (tmp_path / "matrix.json").write_text(json.dumps({"n": 8, "columns": {}, "rows": rows}))
    (tmp_path / "recall.json").write_text(json.dumps([{"login": l, "metrics": {"reverted": 0, "followup_fixed": 0,
                                                       "mature_prs": 5, "team_leverage": 1}} for l in logins]))
    (tmp_path / "coarse.json").write_text(json.dumps([{"login": l, "tier_counts": {"major": 3}} for l in logins]))
    for l in logins:
        (tmp_path / "candidates" / l).mkdir(parents=True)
        (tmp_path / "candidates" / l / "report.json").write_text(json.dumps({**report(6), "cid": l, "positioning": f"{l} builds"}))
    with pytest.raises(SystemExit, match="company.md"):  # no silent fallback without the company context
        A.cli("prep", tmp_path)
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "company.md").write_text("| candidate | team |\n|---|---|\n| u0 | flags |\n")
    (tmp_path / "team_graph.json").write_text(json.dumps({"communities": [{"id": 0, "size": 9, "hub": "u1", "members": ["zz"]}],
                                                          "bridges": [{"login": "u2"}], "single_points": []}))
    A.cli("prep", tmp_path)
    d = tmp_path / "decision"
    prompt = (d / "primary_prompt.md").read_text()
    assert "{company}" not in prompt and "| flags |" in prompt and '"members"' not in prompt
    cids = json.loads((d / "cids.json").read_text())
    assert sorted(cids.values()) == logins and not re.search(r"\bu\d\b", prompt)  # all L4 input anonymized
    by_login = {l: c for c, l in cids.items()}
    prim = [by_login[l] for l in logins]
    sec = prim[:3] + [prim[4], prim[3]] + prim[5:]  # disagree on consensus ranks 4/5
    for n, order in (("primary", prim), ("second", sec)):
        (d / f"{n}.json").write_text("Decision:\n" + json.dumps(decision(order)))
    assert A.cli("pairs", tmp_path).startswith("1 disputed")
    a, b = by_login["u3"], by_login["u4"]
    assert sorted(f.name for f in (d / "pairwise").iterdir()) == [f"{a}-{b}-ab.prompt.md", f"{a}-{b}-ba.prompt.md"]
    for o in ("ab", "ba"):
        (d / "pairwise" / f"{a}-{b}-{o}.json").write_text(json.dumps({"winner": b, "reason": "r"}))
    A.cli("final", tmp_path)
    final = json.loads((tmp_path / "final.json").read_text())
    assert [e["login"] for e in final["top5"]] == ["u0", "u1", "u2", "u4", "u3"]  # pairwise flipped the disputed pair
    assert final["method_notes"]["primary_vs_second"]["top5_overlap"] == 5
