from impact import config as C, llm
from impact.coarse import triage as T
from impact.coarse.run import audit, coarse
from impact.episodes import episode_score, group_episodes

N = iter(range(1, 100000))


def pr(author="alice", title="feat: x", files=None, day=5, body="", lines=100, **kw):
    files = files if files is not None else [{"path": f"posthog/api/f{next(N)}.py", "additions": lines, "deletions": 0}]
    return {"number": next(N), "title": title, "body": body, "author": author, "credited_to": author,
            "merged_at": f"2026-08-{day:02d}T12:00:00Z", "in_window": True, "files": files, "labels": [],
            "additions": sum(f["additions"] for f in files), "deletions": 0, "files_truncated": False, **kw}


def tri(p, tier):
    return {"number": p["number"], "author": p["credited_to"], "tier": tier, "llm_error": None}


def rec(login, **m):
    return {"login": login, "metrics": m, "recalled_by": ["delivery"]}


def unrelated(author, n, start=0):  # distinct scopes, distinct files, so each PR is its own episode
    return [pr(author, title=f"feat(s{start + i}): x", day=5 + i % 20) for i in range(n)]


# --- guardrails (R6)
def f(path, lines=500):
    return {"path": path, "additions": lines, "deletions": 0}


def test_lockfile_and_snapshot_only_forced_mechanical():
    p = pr(files=[f("pnpm-lock.yaml", 9000), f("frontend/__snapshots__/a.snap", 3000)])
    assert T.guardrail(p, "major", "")[0] == "mechanical"


def test_dependency_bump_title_forced_mechanical():
    p = pr(title="chore(deps): Update posthog-js to 1.417.0", files=[f("package.json", 1), f("pnpm-lock.yaml", 40)])
    assert T.guardrail(p, "routine", "") == ("mechanical", "forced_mechanical:dependency_bump")
    code = pr(title="chore(deps): bump django to 5.2.17", files=[f("pyproject.toml", 1), f("posthog/api/x.py", 80)])
    assert T.guardrail(code, "substantive", "")[0] == "substantive"  # bump that adapts code is judged


def test_migration_ci_revert_keep_llm_tier():
    mig = pr(files=[f("posthog/migrations/0900_backfill.py", 10000)])
    ci = pr(files=[f(".github/workflows/ci-backend.yml", 80)])
    rev = pr(title='Revert "feat: ingestion v2"', body="Reverts #123, incident", files=[f("nodejs/src/a.ts", 300)])
    assert T.guardrail(mig, "major", "")[0] == "major"
    assert T.guardrail(ci, "substantive", "")[0] == "substantive"
    assert T.guardrail(rev, "substantive", "")[0] == "substantive"


def test_small_major_needs_verbatim_quote():
    body = "Fixes a billing overcharge for all  EU customers."
    p = pr(body=body, lines=4)
    assert T.guardrail(p, "major", "") == ("substantive", "downgraded:small_change_without_quote")
    assert T.guardrail(p, "major", "invented quote")[0] == "substantive"
    assert T.guardrail(p, "major", "billing overcharge for all EU customers")[0] == "major"  # whitespace-insensitive
    assert T.guardrail(pr(lines=400), "major", "")[0] == "major"


def test_prompt_truncates_paths_with_flag():
    p = pr(files=[f(f"posthog/api/m{i}.py", 1) for i in range(70)])
    text, truncated = T.prompt(p)
    assert truncated and "first 60 of 70" in text and "m59.py" in text and "m60.py" not in text


# --- llm_error handling (Review Focus 4)
def test_llm_error_rerun_counted_and_excluded(monkeypatch):
    calls = []

    async def fake(stage, jobs):
        calls.append((stage, [k for k, _, _ in jobs]))
        good = {"tier": "major", "work_type": "feature", "summary": "s", "quote": ""}
        return [good if k == ok_key else {"tier": "huge"} if k == bad_key else {"llm_error": "boom"} for k, _, _ in jobs]

    a, b, c = pr(), pr(), pr()
    ok_key, bad_key = str(a["number"]), str(b["number"])
    monkeypatch.setattr(llm, "run_all", fake)
    out = T.triage([a, b, c])
    assert [t["tier"] for t in out] == ["major", None, None]
    assert calls[1] == ("triage-retry", [bad_key, str(c["number"])])  # failures rerun once on a fresh stage
    row = coarse([rec("alice")], out, [a, b, c])[0]
    assert row["llm_errors"] == 2 and row["mass"] == 8


# --- episodes (R5)
def test_split_landmark_scores_lower():
    one = pr(title="feat(flags): new engine")
    core = f("posthog/flags/engine.py")  # stacked PRs: same scope, one shared file, low Jaccard
    parts = [pr(title="feat(flags): new engine part", day=5 + i,
                files=[core] + [f(f"posthog/flags/p{i}_{k}.py") for k in range(3)]) for i in range(4)]
    assert len(group_episodes(parts)) == 1
    assert episode_score([16]) == 16 and episode_score([4] * 4) == 7
    split = coarse([rec("alice")], [tri(p, "substantive") for p in parts], parts)[0]["mass"]
    whole = coarse([rec("alice")], [tri(one, "landmark")], [one])[0]["mass"]
    assert split < whole


def test_episode_links_by_file_overlap_and_window():
    shared = [f("posthog/hogql/a.py"), f("posthog/hogql/b.py")]
    a, b = pr(files=shared, day=1), pr(files=shared + [f("posthog/hogql/c.py")], day=6)
    late = pr(files=shared, day=20)
    other = pr(author="bob", files=shared, day=2)
    groups = sorted(map(sorted, group_episodes([a, b, late, other])))
    assert sorted([a["number"], b["number"]]) in groups and [late["number"]] in groups and [other["number"]] in groups


def test_same_scope_disjoint_files_stay_separate():
    prs = [pr(title="feat(data-warehouse): source", day=5 + i // 2) for i in range(10)]  # 5 days, own files
    assert len(group_episodes(prs)) == 10


def test_overlap_chain_splits_at_span_cap():
    days = range(1, 21, 2)  # 10 PRs over 20 days, each sharing one of three files with its neighbour
    chain = [pr(files=[f(f"posthog/x/{i}.py"), f(f"posthog/x/{i + 1}.py")], day=d) for i, d in enumerate(days)]
    merged = {p["number"]: p["merged_at"] for p in chain}
    eps = group_episodes(chain)
    assert 1 < len(eps) < 10
    for ep in eps:
        ts = sorted(merged[n] for n in ep)
        assert int(ts[-1][8:10]) - int(ts[0][8:10]) <= C.EPISODE_DAYS


def test_unrelated_routine_prs_not_collapsed():
    many = unrelated("alice", 80)
    assert coarse([rec("alice")], [tri(p, "routine") for p in many], many)[0]["mass"] == 160


# --- mass, quality, selection
def test_mass_tier_points_and_major_beats_many_small():
    big, small = unrelated("big", 3), unrelated("small", 20, 100)
    junk = unrelated("junk", 40, 200)
    triage = [tri(p, "landmark") for p in big] + [tri(p, "routine") for p in small] + [tri(p, "mechanical") for p in junk]
    rows = {r["login"]: r for r in coarse([rec("big"), rec("small"), rec("junk")], triage, big + small + junk)}
    assert rows["big"]["mass"] == 48 and rows["small"]["mass"] == 40 and rows["junk"]["mass"] == 0
    assert rows["big"]["coarse_score"] > rows["small"]["coarse_score"]
    assert rows["junk"]["tier_counts"]["mechanical"] == 40


def test_many_trivial_lose_to_few_major():
    few, many = unrelated("few", 3), unrelated("many", 20, 100)
    triage = [tri(p, "major") for p in few] + [tri(p, "trivial") for p in many]
    rows = coarse([rec("many"), rec("few")], triage, few + many)
    assert [r["login"] for r in rows] == ["few", "many"]


def test_quality_factor_floor_and_unknown():
    prs = unrelated("alice", 4)
    t = [tri(p, "substantive") for p in prs]
    bad = coarse([rec("alice", affected_prs=[p["number"] for p in prs])], t, prs)[0]
    ok = coarse([rec("alice", affected_prs=[prs[0]["number"]])], t, prs)[0]
    unk = coarse([rec("alice", affected_prs=None)], t, prs)[0]
    assert bad["quality_factor"] == 0.5 and ok["quality_factor"] == 0.75
    assert unk["quality_factor"] == 1.0 and unk["quality_unknown"]
    late = [pr(day=28, title="feat(late): x")]
    late[0]["merged_at"] = "2026-10-30T00:00:00Z"  # outside mature cohort → no denominator → unknown
    assert coarse([rec("alice", affected_prs=[])], [tri(late[0], "major")], late)[0]["quality_unknown"]


def test_selection_score_union_team_then_fill():
    logins = [f"u{i}" for i in range(30)]
    prs, t, recall = [], [], []
    for i, login in enumerate(logins):
        mine = unrelated(login, 30 - i, 1000 * i)
        prs += mine
        t += [tri(p, "routine") for p in mine]
        recall.append(rec(login, team_leverage=230.0 if login == "u29" else 0))
    rows = {r["login"]: r for r in coarse(recall, t, prs)}
    chosen = [l for l, r in rows.items() if r["selected_by"]]
    assert len(chosen) == C.COARSE_N
    assert rows["u0"]["selected_by"] == ["score"] and rows["u29"]["selected_by"] == ["team"]
    assert rows["u15"]["selected_by"] == ["fill"] and not rows["u28"]["selected_by"]


def test_audit_finds_unrecalled_major_authors():
    t = [{"number": 1, "author": "carol", "tier": "major"}, {"number": 2, "author": "alice", "tier": "landmark"},
         {"number": 3, "author": "dave", "tier": "routine"}, {"number": 4, "author": "erin", "tier": None}]
    assert audit(t, [rec("alice")]) == ["carol"]


def test_routine_affected_pr_does_not_lower_q():
    prs = unrelated("alice", 4)
    t = [tri(p, "substantive") for p in prs[:3]] + [tri(prs[3], "routine")]
    row = coarse([rec("alice", affected_prs=[prs[3]["number"]])], t, prs)[0]
    assert row["q"] == 1.0
    assert coarse([rec("alice", affected_prs=[prs[0]["number"]])], t, prs)[0]["q"] == 1 - 1 / 3


def test_major_route_adds_unrecalled_and_keeps_ties(monkeypatch):
    monkeypatch.setattr(C, "COARSE_TOP_MAJOR", 2)
    prs, t = [], []
    for login, n in [("a", 3), ("b", 2), ("c", 2), ("d", 1)]:
        mine = unrelated(login, n, 100 * len(prs))
        prs += mine
        t += [tri(p, "major") for p in mine]
    filler = unrelated("big", 30, 5000)  # outscores everyone on mass
    prs += filler
    t += [tri(p, "substantive") for p in filler]
    asked = []
    rows = {r["login"]: r for r in coarse([rec("big"), rec("d")], t, prs,
                                          lambda ls: asked.extend(ls) or {l: {"team_leverage": 1.0} for l in ls})}
    assert asked == ["a", "b", "c"]  # big has no major episodes; d (1) is below the tie at 2
    assert all("major" in rows[l]["selected_by"] for l in "abc") and rows["a"]["team_score"] == 1.0
    assert "major" not in rows["d"]["selected_by"] and rows["b"]["recalled_by"] == ["major"]
