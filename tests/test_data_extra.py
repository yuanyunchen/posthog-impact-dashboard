import json
import re

from impact import config as C
from impact import data_extra as X


def fake_pr(n):
    return {"number": n,
            "reviews": {"totalCount": 1, "nodes": [{"author": {"__typename": "Bot", "login": "copilot-pull-request-reviewer"}, "state": "APPROVED", "submittedAt": "t", "body": "lgtm"}]},
            "reviewThreads": {"totalCount": 2, "nodes": [{"path": "a.py", "line": None, "originalLine": 3, "isOutdated": True,
                              "comments": {"totalCount": 1, "nodes": [{"author": {"login": "bob"}, "body": "nit", "createdAt": "t",
                                                                       "originalCommit": {"oid": "abc"}}]}}]},
            "timelineItems": {"filteredCount": 1, "nodes": [{"createdAt": "t", "actor": {"login": "alice"},
                                                          "requestedReviewer": {"slug": "team-replay"}}]}}


def mock_gh(monkeypatch, absent=(), fail_over=None):
    queries = []

    def gh(q):
        nums = [int(x) for x in re.findall(r"n(\d+): ", q)]
        queries.append(nums)
        if fail_over and len(nums) > fail_over:
            raise RuntimeError("502")
        return {"data": {"rateLimit": {"cost": 1}, "repository": {f"n{n}": None if n in absent else fake_pr(n) for n in nums}}}
    monkeypatch.setattr(X, "gh_graphql", gh)
    return queries


def test_batch_query_aliases():
    q = X.batch_query("pullRequest", [1, 22], "number")
    assert "n1: pullRequest(number: 1) { number }" in q and "n22: pullRequest(number: 22)" in q
    assert 'repository(owner: "PostHog", name: "posthog")' in q and "rateLimit" in q


def test_review_detail_batches_missing_and_resume(monkeypatch, tmp_path):
    queries = mock_gh(monkeypatch, absent={7})
    out = tmp_path / "rd.jsonl"
    res = X.fetch_review_detail(list(range(1, 31)), out)
    assert [len(q) for q in queries] == [C.GQL_BATCH, 30 - C.GQL_BATCH]
    assert res["fetched"] == 29 and res["missing"] == [7] and res["truncated"] == {"threads": 1 * 29}
    rec = json.loads(out.read_text().splitlines()[0])
    assert rec["threads"][0] == {"path": "a.py", "line": None, "original_line": 3, "original_commit": "abc", "is_outdated": True,
                                 "comments": [{"author": "bob", "is_bot": False, "body": "nit", "created_at": "t"}], "comments_truncated": False}
    assert rec["review_requests"] == [{"requester": "alice", "reviewer": "team-replay", "reviewer_is_bot": False, "created_at": "t"}]
    assert rec["reviews"][0]["body"] == "lgtm" and rec["reviews"][0]["is_bot"]  # Bot typename, not in BOT_LOGINS
    queries.clear()
    res = X.fetch_review_detail(list(range(1, 32)), out)  # resume: only 7 (still missing) and 31 are asked
    assert queries == [[7, 31]] and res["skipped"] == 29 and res["missing"] == [7]


def test_failed_batch_is_halved(monkeypatch, tmp_path):
    queries = mock_gh(monkeypatch, fail_over=5)
    res = X.fetch_review_detail(list(range(1, 21)), tmp_path / "rd.jsonl")
    assert res["fetched"] == 20 and not res["missing"] and [len(q) for q in queries] == [20, 10, 5, 5, 10, 5, 5]


def test_issue_reactions(monkeypatch):
    monkeypatch.setattr(X, "gh_graphql", lambda q: {"data": {"repository": {
        "n5": {"number": 5, "reactions": {"totalCount": 4}}, "n6": None}}})
    assert X.fetch_issue_reactions([5, 6]) == {5: 4}


def test_pr_number_from_subject():
    assert X.pr_number("feat(replay): faster (#12345)") == 12345
    assert X.pr_number('revert: "feat(mcp) add skills (#70424)" (#73480)') == 73480  # several numbers: last one
    assert X.pr_number("fix: a (#1) (#2)  ") == 2
    assert X.pr_number("chore(cli): release v0.18.2") is None
    assert X.pr_number("see #123 for context") is None
    assert X.pr_number("Merge pull request #99 from a/b") == 99


def test_trailers():
    body = "feat: x\n\nbody\n\nCo-authored-by: Bob B <bob@x.com>\nco-authored-by: Claude <noreply@anthropic.com>\nGenerated-By: PostHog Code\n"
    assert X.trailers(body) == {"co_authors": [{"name": "Bob B", "email": "bob@x.com"}, {"name": "Claude", "email": "noreply@anthropic.com"}],
                                "generated_by": "PostHog Code"}
    assert X.trailers("x\n\n🤖 Generated with [Claude Code](https://claude.com)")["generated_by"] == "Claude Code"
    assert X.trailers("plain") == {"co_authors": [], "generated_by": None}


def test_rename_paths():
    assert X.rename_paths("a/b.py") == (None, "a/b.py")
    assert X.rename_paths("old.py => new.py") == ("old.py", "new.py")
    assert X.rename_paths("src/{lib => core}/x.py") == ("src/lib/x.py", "src/core/x.py")
    assert X.rename_paths("src/{ => sub}/x.py") == ("src/x.py", "src/sub/x.py")


def commit(sha, subject, numstat, body=""):
    return f"\x1e{sha}\x1fa@x\x1f2026-08-0{sha[-1]}T00:00:00Z\x1f{subject}\x1f{subject}\n\n{body}\x1f\n" + "".join(f"{l}\n" for l in numstat)


def test_lineage_merges_renames_and_skips_boundary():
    log = (commit("c3", "edit (#3)", ["1\t1\tsrc/core/x.py"])
           + commit("c2", "move (#2)", ["0\t0\tsrc/{lib => core}/x.py", "-\t-\timg.png"], "Co-authored-by: Bob <b@x>")
           + commit("c1", "direct push", ["5\t0\tsrc/lib/x.py"])
           + commit("c0", "boundary (#0)", ["9000\t0\tsrc/lib/x.py"]))
    lineage, authors, counts, unmapped = X.parse_log(log, skip={"c0"})
    assert [e["number"] for e in lineage["src/core/x.py"]] == [3, 2, None]  # pre-rename history kept under the new name
    assert "src/lib/x.py" not in lineage
    assert lineage["img.png"][0]["added"] == 0
    assert authors["2"] == {"merge_commit": "c2", "co_authors": [{"name": "Bob", "email": "b@x"}], "generated_by": None}
    assert counts["shallow_boundary"] == 1 and counts["renames"] == 1 and unmapped == ["c1 direct push"]


def test_build_org(tmp_path):
    org = tmp_path / "org"
    org.mkdir()
    (org / "members.csv").write_text("team,handle\nreplay,tuehaulund\nsupport,simfish85\nonboarding,simfish85\nreplay,\n")
    (org / "changelog-since-2026-07-01.tsv").write_text(
        "dateCompleted\ttitle\tgithubUrls\n"
        "2026-10-01\tFaster replay\thttps://github.com/PostHog/posthog/pull/11 https://github.com/PostHog/posthog-js/pull/5\n"
        "2026-10-02\tMore replay\thttps://github.com/PostHog/posthog/pull/11\n"
        "2026-10-03\tSDK only\thttps://github.com/PostHog/posthog-js/pull/6\n")
    prs = tmp_path / "prs.jsonl"
    prs.write_text(json.dumps({"author": "TueHaulund", "reviews": [{"author": "x"}]}) + "\n")
    res = X.build_org(tmp_path, org, prs)
    assert json.loads((tmp_path / "team_map.json").read_text()) == {"TueHaulund": ["replay"], "simfish85": ["support", "onboarding"]}
    assert json.loads((tmp_path / "changelog.json").read_text()) == {
        "11": [{"title": "Faster replay", "date": "2026-10-01"}, {"title": "More replay", "date": "2026-10-02"}]}
    assert res["members_without_handle"] == 1 and res["handles_not_in_pr_data"] == ["simfish85"]
    assert res["changelog_rows_without_posthog_pr"] == 1 and res["prs_in_multiple_entries"] == 1
