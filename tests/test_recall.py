import math

from impact import config as C
from impact.recall.features import person_metrics, pr_rule_weight, rule_metrics_for
from impact.recall.run import audit_sample, recall

N = iter(range(1000, 100000))


def pr(author="alice", files=(("posthog/api/x.py", 10),), reviews=(), title="feat: x", body="", merged="2026-08-10T00:00:00Z",
       bot=False, labels=(), credited=None, **kw):
    files = [{"path": p, "additions": n, "deletions": 0} for p, n in files]
    return {"number": next(N), "title": title, "body": body, "author": author, "author_is_bot": bot,
            "ai_assisted": kw.get("ai", False), "credited_to": credited if (bot or credited) else author,
            "created_at": "2026-08-01T00:00:00Z", "merged_at": merged, "in_window": C.WINDOW_START <= merged <= C.WINDOW_END,
            "additions": sum(f["additions"] for f in files), "deletions": 0, "files": files, "labels": list(labels),
            "reviews": [{"author": a, "is_bot": C.is_bot(a), "state": s, "submitted_at": "2026-08-02T00:00:00Z", "body_len": 0}
                        for a, s in reviews],
            "closing_issues": [], "review_requests": None}


def test_lockfile_and_migration_weights():
    assert pr_rule_weight(pr(files=[("pnpm-lock.yaml", 5000)]))[0] == 0
    w, core = pr_rule_weight(pr(files=[("products/surveys/backend/migrations/0001_x.py", 10000)]))
    assert w <= 0.3 * math.log2(1 + 10000) + 1e-9
    assert pr_rule_weight(pr(files=[("posthog/migrations/0999_x.py", 10000)]))[0] <= 0.3 * math.log2(1 + 10000) + 1e-9
    assert core is None or core == 0


def test_huge_generated_pr_does_not_top_delivery():  # Review Focus 2
    prs = [pr("gen", files=[("posthog/migrations/0999_big.py", 10000)]),
           pr("gen", files=[("frontend/src/queries/schema.json", 10000)])]
    prs += [pr("dev", files=[("products/surveys/backend/api.py", 200)]) for _ in range(2)]
    m = person_metrics(prs)
    assert m["dev"]["w_rule_sum"] > m["gen"]["w_rule_sum"]


def test_core_share():
    w, core = pr_rule_weight(pr(files=[("posthog/hogql/parser.py", 10), ("frontend/src/scenes/a.tsx", 10)]))
    assert abs(core - 1.5 / 2.5) < 1e-9 and w > 0


def test_bot_only_reviews_give_no_credit():  # Review Focus 5
    prs = [pr("renovate", bot=True, reviews=[("carol", "APPROVED")]) for _ in range(30)]
    prs.append(pr("alice", reviews=[("stamphog", "APPROVED"), ("alice", "COMMENTED")]))
    m = person_metrics(prs)
    assert "carol" not in m  # no credited activity at all → never a candidate
    assert m["alice"]["reviews_given"] == 0
    assert "renovate" not in m and "stamphog" not in m


def test_ai_pr_not_credited_but_reviews_count():  # Review Focus 1 / R9
    body = f"<!-- {C.AI_AGENT_MARKER} -->"
    prs = [pr("posthog", bot=True, ai=True, body=body, reviews=[("dave", "APPROVED")]),
           pr("posthog", bot=True, ai=True, body=body + " requested by @erin", credited="erin")]
    m = person_metrics(prs)
    assert "posthog" not in m
    assert m["dave"]["reviews_given"] == 1 and m["dave"]["prs"] == 0
    assert m["erin"]["prs"] == 1 and m["erin"]["ai_prs"] == 1


def test_pagerank_excludes_bots():
    prs = [pr("alice", reviews=[("bob", "APPROVED")]), pr("bob", reviews=[("alice", "APPROVED"), ("trunk-io", "APPROVED")]),
           pr("renovate", bot=True, reviews=[("carol", "APPROVED")])]
    m = person_metrics(prs)
    assert set(m) == {"alice", "bob"}  # trunk-io, renovate and carol (bot-PR reviews only) are not graph nodes
    assert abs(m["alice"]["pagerank"] + m["bob"]["pagerank"] - 1) < 1e-6


def test_followup_fix_needs_explicit_reference():
    a = pr("alice", merged="2026-08-06T00:00:00Z")
    b = pr("alice", merged="2026-08-06T00:00:00Z", files=[("posthog/api/y.py", 10)])
    fixes = [pr("bob", title=f"fix: repair x broken by #{a['number']}", merged="2026-08-08T00:00:00Z"),
             pr("bob", title="fix: repair y", files=[("posthog/api/y.py", 3)], merged="2026-08-08T00:00:00Z"),  # same file, no ref
             pr("alice", title=f"fix: my own #{b['number']}", merged="2026-08-08T00:00:00Z")]  # self-fix
    m = person_metrics([a, b] + fixes)
    assert m["alice"]["followup_fixed"] == 1 and m["alice"]["affected_prs"] == [a["number"]]


def test_followup_needs_fix_or_revert_type():
    a = pr("alice", merged="2026-08-06T00:00:00Z")
    others = [pr("bob", title=f"feat: build on #{a['number']}", merged="2026-08-07T00:00:00Z"),
              pr("bob", title=f"chore: tidy after #{a['number']}", merged="2026-08-07T00:00:00Z"),
              pr("bob", title=f"hotfix: patch #{a['number']}", merged="2026-08-07T00:00:00Z")]
    assert person_metrics([a] + others)["alice"]["affected_prs"] == []
    rev = pr("bob", title='Revert "feat: x"', body=f"Reverts PostHog/posthog#{a['number']}", merged="2026-08-07T00:00:00Z")
    assert person_metrics([a, rev])["alice"]["reverted"] == 1


def test_followup_reference_in_excluded_sentence_ignored():
    a, b = pr("alice", merged="2026-08-06T00:00:00Z"), pr("alice", merged="2026-08-06T00:00:00Z")
    bodies = [f"Fixes the flake seen in PR #{a['number']}.", f"#{a['number']} (an unrelated change) touched this.",
              f"The API already shipped in #{a['number']}.", f"Similar to #{a['number']}.",
              f"Follow-up to #{a['number']}, which added it.", f"See also #{a['number']}."]
    fixes = [pr("bob", title="fix: x", body=t, merged="2026-08-07T00:00:00Z") for t in bodies]
    fixes.append(pr("bob", title="fix: y", body=f"Unrelated cleanup.\nThe bug came from #{b['number']}.", merged="2026-08-07T00:00:00Z"))
    assert person_metrics([a, b] + fixes)["alice"]["affected_prs"] == [b["number"]]


def test_revert_and_fix_count_once_per_pr():
    a = pr("alice", merged="2026-08-06T00:00:00Z")
    rest = [pr("bob", title=f'Revert "feat: x (#{a["number"]})"', merged="2026-08-07T00:00:00Z"),
            pr("carol", title=f"fix: after #{a['number']}", merged="2026-08-07T00:00:00Z")]
    m = person_metrics([a] + rest)["alice"]
    assert (m["reverted"], m["followup_fixed"], m["mature_prs"]) == (1, 0, 1) and m["quality_q"] == 0


def test_immature_prs_not_in_denominator():
    late = pr("alice", merged="2026-10-25T00:00:00Z")
    fix = pr("bob", title=f"fix: #{late['number']}", merged="2026-10-26T00:00:00Z")
    m = person_metrics([late, fix])["alice"]
    assert m["mature_prs"] == 0 and m["reverted"] is None and m["followup_fixed"] is None and m["quality_q"] is None
    m = person_metrics([late, fix, pr("alice", merged="2026-08-10T00:00:00Z")])["alice"]
    assert (m["mature_prs"], m["followup_fixed"], m["quality_q"]) == (1, 0, 1.0)


def test_unknown_is_none_not_zero():  # R11
    m = person_metrics([pr("alice")])["alice"]
    assert m["changelog_prs"] is None and m["review_requested_by"] is None and m["issue_reactions"] is None and m["team"] is None
    p = pr("alice", reviews=[("bob", "APPROVED")])
    p["review_requests"] = ["bob"]
    p["closing_issues"] = [{"number": 1, "reactions": 4}]
    m = person_metrics([p], changelog={}, team_map={"alice": ["team-x"]})
    assert m["alice"]["changelog_prs"] == 0 and m["alice"]["issue_reactions"] == 4 and m["alice"]["team"] == ["team-x"]
    assert m["bob"]["review_requested_by"] == 1


def test_floor_exemption_and_routes():
    prs = [pr("busy", files=[("frontend/src/scenes/a.tsx", 50)]) for _ in range(6)]
    prs += [pr("tiny", files=[("frontend/src/scenes/b.tsx", 5)])]  # below floor, no exemption
    cl = pr("shipper", files=[("frontend/src/scenes/c.tsx", 5)])  # one changelog PR → exempt + recalled
    prs.append(cl)
    prs.append(pr("oncall", labels=["incident"], files=[("frontend/src/scenes/d.tsx", 5)]))
    stats = {}
    rec = {x["login"]: x for x in recall(prs, changelog={str(cl["number"]): {"title": "x"}}, stats=stats)}
    assert "tiny" not in rec and "busy" in rec
    assert "changelog" in rec["shipper"]["recalled_by"] and "changelog" in rec["shipper"]["floor_exempt"]
    assert "critical" in rec["oncall"]["recalled_by"]
    assert stats["below_floor"] == 1 and stats["over_cap"] == 0


def test_no_silent_cut_over_cap():
    prs = [pr(f"u{i}", files=[(f"frontend/src/scenes/a{i}.tsx", 5 + i)]) for i in range(70) for _ in range(5)]
    cl = {str(p["number"]): {} for p in prs[::5]}  # everyone has a changelog PR
    stats = {}
    assert len(recall(prs, changelog=cl, stats=stats)) == 70 and stats["over_cap"] == 10


def test_audit_sample_deterministic_and_excludes_recalled():
    prs = [pr(f"u{i % 5}") for i in range(50)]
    s1, pop = audit_sample(prs, {"u0"})
    assert pop == 40 and len(s1) == 40 and s1 == audit_sample(prs, {"u0"})[0]
    by = {p["number"]: p["credited_to"] for p in prs}
    assert "u0" not in {by[n] for n in s1}


def test_ai_coauthored_metrics():
    a = pr("alice", merged="2026-08-06T00:00:00Z")
    b, c, d = pr("alice"), pr("alice"), pr("alice")
    fix = pr("bob", title=f"fix: broken by #{a['number']}", merged="2026-08-07T00:00:00Z")
    ca = {str(a["number"]): {"co_authors": [{"name": "Claude Opus 5", "email": "noreply@anthropic.com"}], "generated_by": None},
          str(b["number"]): {"co_authors": [{"name": "Bot", "email": "cursoragent@CURSOR.com"}], "generated_by": None},
          str(c["number"]): {"co_authors": [], "generated_by": "PostHog Desktop"},
          str(d["number"]): {"co_authors": [{"name": "Bob", "email": "bob@posthog.com"}, {"name": "posthog[bot]", "email": "x"}],
                             "generated_by": None}}
    m = person_metrics([a, b, c, d, fix], commit_authors=ca)["alice"]
    assert (m["ai_coauthored_prs"], m["ai_share"], m["ai_reverted_or_fixed"]) == (3, 0.75, 1)
    m = person_metrics([a, fix])["alice"]
    assert m["ai_coauthored_prs"] is None and m["ai_share"] is None and m["ai_reverted_or_fixed"] is None


def test_rule_metrics_for_matches_person_metrics():
    prs = [pr("alice", reviews=[("bob", "APPROVED")]), pr("bob", reviews=[("alice", "APPROVED")])]
    out = rule_metrics_for(["bob", "ghost"], prs)
    assert out["bob"] == person_metrics(prs)["bob"] and out["ghost"] is None


def test_self_repair_reported_apart_from_followups():
    a, b, c = (pr("alice", merged="2026-08-06T00:00:00Z") for _ in range(3))
    late = pr("alice", merged="2026-10-25T00:00:00Z")
    rest = [pr("alice", title=f"fix: broken by #{a['number']}", merged="2026-08-08T00:00:00Z"),       # self-fix → counts
            pr("alice", title=f'Revert "x (#{b["number"]})"', merged="2026-09-30T00:00:00Z"),        # self-revert, no time limit
            pr("alice", title=f"fix: broken by #{c['number']}", merged="2026-08-30T00:00:00Z"),       # self-fix after 14 days
            pr("bob", title=f"fix: broken by #{c['number']}", merged="2026-08-07T00:00:00Z"),         # other's fix → followup only
            pr("alice", title=f"fix: broken by #{late['number']}", merged="2026-10-26T00:00:00Z")]    # immature original
    m = person_metrics([a, b, c, late] + rest)["alice"]
    assert m["self_repaired_prs"] == 2 and m["mature_prs"] == 6 and m["self_repair_rate"] == round(2 / 6, 3)
    assert (m["followup_fixed"], m["reverted"]) == (1, 1)  # unchanged definitions


def test_approval_types():
    h = pr("alice", reviews=[("stamphog", "APPROVED"), ("bob", "APPROVED")])
    ai = pr("alice", reviews=[("stamphog", "APPROVED"), ("bob", "COMMENTED")])
    no = pr("alice", reviews=[("bob", "CHANGES_REQUESTED")])
    m = person_metrics([h, ai, no])["alice"]
    assert (m["human_approved_prs"], m["ai_only_approved_prs"], m["no_approval_prs"]) == (1, 1, 1)
    assert m["human_approved_major_prs"] is None and m["no_approval_major_prs"] is None
    m = person_metrics([h, ai, no], tiers={h["number"]: "landmark", ai["number"]: "major", no["number"]: "routine"})["alice"]
    assert (m["human_approved_major_prs"], m["ai_only_approved_major_prs"], m["no_approval_major_prs"]) == (1, 1, 0)


def test_audit_entries_survive_rerun():
    prs = [pr("busy") for _ in range(6)] + [pr("late", files=[("frontend/src/scenes/z.tsx", 3)])]
    keep = [{"login": "late", "metrics": {}, "recalled_by": ["audit"]}, {"login": "busy", "metrics": {}, "recalled_by": ["audit"]},
            {"login": "gone", "metrics": {"prs": 0}, "recalled_by": ["audit"]}]
    rec = {x["login"]: x for x in recall(prs, keep=keep)}
    assert rec["late"]["recalled_by"] == ["audit"] and rec["late"]["metrics"]["prs"] == 1  # fresh metrics
    assert rec["busy"]["recalled_by"][-1] == "audit" and rec["busy"]["recalled_by"].count("audit") == 1
    assert rec["gone"]["metrics"] == {"prs": 0}  # no activity now: old metrics kept, entry not dropped
