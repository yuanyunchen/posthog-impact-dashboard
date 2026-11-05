from impact.fine import team_graph as T


def rv(author, state, at="2026-08-06T00:00:00Z", body_len=0, is_bot=False):
    return {"author": author, "is_bot": is_bot, "state": state, "submitted_at": at, "body_len": body_len}


def pr(n, author, reviews=(), merged="2026-08-10T00:00:00Z", title="feat: x", body="", files=None, commits=1):
    return {"number": n, "title": title, "body": body, "author": author, "author_is_bot": T.C.is_bot(author),
            "credited_to": None if T.C.is_bot(author) else author, "created_at": "2026-08-05T00:00:00Z",
            "merged_at": merged, "in_window": True, "files": files or [{"path": "posthog/api/x.py", "additions": 10, "deletions": 0}],
            "reviews": list(reviews), "commits": commits, "review_requests": None}


def test_bots_dropped():
    prs = [pr(1, "alice", [rv("greptile-apps", "COMMENTED", body_len=50, is_bot=True), rv("bob", "APPROVED")]),
           pr(2, "renovate", [rv("bob", "APPROVED")])]
    ev = T.build_events(prs)
    assert [(e["type"], e["src"], e["dst"]) for e in ev] == [("approve", "bob", "alice")]


def test_uncovered_is_not_zero():
    prs = [pr(i, "alice", [rv("bob", "APPROVED")]) for i in range(1, 8)]
    ev = T.build_events(prs)  # no review_detail, no lineage
    cov = T.coverage(prs, None, None)
    m = T.person_metrics(ev, prs, coverage=cov)
    assert m["bob"]["requested_by_n"] == {"value": None, "n": None}
    assert m["alice"]["built_on_by_n"] == {"value": None, "n": None}
    # covered but nobody asked bob → a real 0
    rd = {i: {"review_requests": []} for i in range(1, 8)}
    m = T.person_metrics(T.build_events(prs, rd), prs, coverage=T.coverage(prs, rd, None))
    assert m["bob"]["requested_by_n"] == {"value": 0, "n": 7}


def test_first_pass_rate():
    prs = [pr(i, "alice", [rv("bob", "APPROVED")]) for i in range(1, 5)]
    prs += [pr(5, "alice", [rv("bob", "CHANGES_REQUESTED", "2026-08-06T00:00:00Z"), rv("bob", "APPROVED", "2026-08-07T00:00:00Z")], commits=3)]
    prs += [pr(6, "alice", [rv("bob", "APPROVED", "2026-08-06T00:00:00Z"), rv("carol", "CHANGES_REQUESTED", "2026-08-07T00:00:00Z")])]
    m = T.person_metrics(T.build_events(prs), prs)
    assert m["alice"]["first_pass_rate"] == {"value": round(5 / 6, 3), "n": 6}  # #6 was approved before the change request
    assert m["alice"]["changes_requested_rate"] == {"value": round(2 / 6, 3), "n": 6}
    assert m["bob"]["changes_adopted_rate"]["n"] == 1  # below the sample floor → None
    assert m["bob"]["changes_adopted_rate"]["value"] is None


def test_trust_weighted_approval():
    # many people approve hi; nobody approves lo. hi approves x once, lo approves y once.
    ev = [{"type": "approve", "src": s, "dst": "hi", "pr": i, "at": ""} for i, s in enumerate("abcdef")]
    ev += [{"type": "approve", "src": "hi", "dst": "x", "pr": 10, "at": ""},
           {"type": "approve", "src": "lo", "dst": "y", "pr": 11, "at": ""}]
    r = T.trust_rank(ev)
    assert r["x"] > r["y"]


def test_hub_files_excluded():
    hub = "posthog/api/hub.py"
    n = T.C.HUB_FILE_AUTHORS
    prs = [pr(i, f"u{i}", merged=f"2026-08-{6 + i % 3:02d}T{i % 24:02d}:00:00Z") for i in range(n)]
    lineage = {hub: [{"number": i, "added": 30, "deleted": 0, "merged_at": p["merged_at"]} for i, p in enumerate(prs)],
               "posthog/api/small.py": [{"number": 0, "added": 30, "deleted": 0, "merged_at": "2026-08-01T00:00:00Z"},
                                        {"number": 1, "added": 1, "deleted": 0, "merged_at": "2026-08-09T00:00:00Z"}],
               "docs/readme.md": [{"number": 0, "added": 30, "deleted": 0, "merged_at": "2026-08-01T00:00:00Z"},
                                  {"number": 2, "added": 5, "deleted": 0, "merged_at": "2026-08-09T00:00:00Z"}]}
    ev = [e for e in T.build_events(prs, lineage=lineage) if e["type"] == "continue"]
    assert [(e["src"], e["dst"]) for e in ev] == [("u1", "u0")]


def test_communities_reproducible():
    ev = [{"type": "approve", "src": a, "dst": b, "pr": i, "at": ""}
          for i, (a, b) in enumerate([("a", "b"), ("b", "c"), ("c", "a"), ("d", "e"), ("e", "f"), ("f", "d"), ("c", "d")])]
    tm = {"a": ["t1"], "b": ["t1"], "c": ["t1"], "d": ["t2"], "e": ["t2"], "f": ["t3"]}
    s1, s2 = T.team_structure(ev, tm), T.team_structure(ev, tm)
    assert s1 == s2
    assert sorted(sorted(c["members"]) for c in s1["communities"]) == [["a", "b", "c"], ["d", "e", "f"]]
    assert {c["main_team"]: c["purity"] for c in s1["communities"]} == {"t1": 1.0, "t2": round(2 / 3, 3)}


def test_single_point_area():
    ev = [{"type": "approve", "src": "bob", "dst": f"u{i}", "pr": i, "at": ""} for i in range(5)]
    ev += [{"type": "approve", "src": "carol", "dst": "u9", "pr": 9, "at": ""}]
    s = T.team_structure(ev, {}, {i: "Billing" for i in [*range(5), 9]})
    assert s["single_points"] == [{"area": "Billing", "approver": "bob", "share": round(5 / 6, 3), "approvals": 6}]


def test_revert_event_uses_recall_rule():
    prs = [pr(1, "alice", merged="2026-08-06T00:00:00Z"),
           pr(2, "bob", title='Revert "feat: x"', body="Reverts #1", merged="2026-08-07T00:00:00Z")]
    ev = T.build_events(prs)
    assert [(e["type"], e["src"], e["dst"], e["pr"]) for e in ev] == [("revert", "bob", "alice", 2)]
