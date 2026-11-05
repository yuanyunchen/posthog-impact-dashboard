import json

from impact import config as C
from impact.fine.pack import build_pack
from impact.fine.query import run

BODY = "SECRET-BODY-SENTENCE the raw description must never reach the pack"


def pr(n, author, day, tier_files=("posthog/api/flags.py",), reviews=()):
    return {"number": n, "title": f"feat(flags): change {n}", "body": BODY, "author": author, "credited_to": author,
            "author_is_bot": False, "in_window": True, "merged_at": f"2026-08-{day:02d}T10:00:00Z", "additions": 30, "deletions": 5,
            "files": [{"path": p, "additions": 30, "deletions": 5} for p in tier_files], "labels": [],
            "reviews": [{"author": a, "is_bot": False, "state": s, "submitted_at": f"2026-08-{day:02d}T12:00:00Z", "body_len": 9}
                        for a, s in reviews]}


def setup(tmp_path, n_prs=10):
    prs = [pr(i, "ann", 5 + i, reviews=[("bob", "APPROVED")]) for i in range(1, n_prs + 1)]
    prs += [pr(100, "bob", 6, ("frontend/src/scenes/x.tsx",), reviews=[("ann", "CHANGES_REQUESTED"), ("ann", "APPROVED")]),
            pr(101, "renovate", 7, reviews=[("ann", "APPROVED")]) | {"credited_to": None, "author_is_bot": True}]
    triage = [{"number": i, "tier": t, "work_type": "feature", "summary": f"summary {i}"}
              for i, t in zip(range(1, n_prs + 1), ["major", "substantive", "routine", "trivial", "mechanical"] * 4)]
    reads = [{"number": 1, "V": 3, "C": 2, "N": 1, "L": 2, "Q": 2, "ell": 2.4, "P": 9.1, "verified": dict.fromkeys("VCNLQ", True),
              "evidence": dict.fromkeys("VCNLQ", BODY), "summary": "deep summary 1", "diff_source": "commit_authors",
              "diff_truncated": False, "llm_error": None}]
    path = tmp_path / "prs.jsonl"
    path.write_text("".join(json.dumps(p) + "\n" for p in prs))
    d = build_pack("ann", prs, triage, reads, "# dossier\n", team_map={"bob": ["flags"]}, prs_path=path, out=tmp_path)
    return d, prs


def test_pack_has_no_raw_text(tmp_path):
    d, _ = setup(tmp_path)
    assert {f.name for f in d.iterdir()} >= {"dossier.md", "workstreams.json", "network.json", "prs.jsonl", "reviews.json", "README.md"}
    for f in d.iterdir():
        text = f.read_text()
        assert "SECRET-BODY" not in text and "diff --git" not in text, f.name
    rows = [json.loads(l) for l in open(d / "prs.jsonl")]
    assert len(rows) == 10 and rows[0]["P"] == 9.1 and rows[0]["deepread"]["source"] == "sample" and rows[1]["P"] is None
    assert json.loads((d / "network.json").read_text()) == {}
    rv = json.loads((d / "reviews.json").read_text())
    assert [r["number"] for r in rv["given"]] == [100, 100]  # bot PR 101 never counts
    assert len(rv["received"]) == 10 and rv["received"][0]["team"] == ["flags"]


def test_filters(tmp_path):
    setup(tmp_path)
    out = run(["ann", "prs", "--tier", "major"], out=tmp_path).splitlines()
    assert out[0].startswith("2 of 10 PRs") and all(" major" in l for l in out[1:]) and len(out) == 3
    out = run(["ann", "prs", "--since", "2026-08-08", "--until", "2026-08-10"], out=tmp_path).splitlines()
    assert out[0].startswith("3 of 10") and [l.split()[0] for l in out[1:]] == ["#3", "#4", "#5"]
    assert run(["ann", "prs", "--area", "no-such-area"], out=tmp_path).startswith("0 of 10")
    ws = json.loads((tmp_path / "candidates/ann/workstreams.json").read_text())
    n_ws1 = len(ws[0]["prs"])
    assert run(["ann", "prs", "--ws", ws[0]["id"]], out=tmp_path).startswith(f"{n_ws1} of 10")
    assert len(run(["ann", "--max-lines", "4", "prs"], out=tmp_path).splitlines()) == 4  # overflow announced
    assert "more lines" in run(["ann", "--max-lines", "4", "prs"], out=tmp_path)
    assert "CHANGES_REQUESTED 1" in run(["ann", "reviews-given"], out=tmp_path)
    assert "flags 10" in run(["ann", "reviews-received"], out=tmp_path)
    tl = run(["ann", "timeline"], out=tmp_path).splitlines()
    assert tl[1].startswith("2026-08-03 | 4 |") and tl[2].startswith("2026-08-10 | 6 |") and len(tl) == 3


def test_rank_without_matrix(tmp_path):
    setup(tmp_path)
    assert "unknown metric" in run(["ann", "rank", "team_leverage"], out=tmp_path)  # neither matrix nor recall
    (tmp_path / "recall.json").write_text(json.dumps([{"login": l, "metrics": {"team_leverage": v}}
                                                      for l, v in [("ann", 5.0), ("bob", 9.0), ("cy", None)]]))
    out = run(["ann", "rank", "team_leverage"], out=tmp_path)
    assert "basis: recall (3 people; matrix absent)" in out and "percentile 0.0 · position 2/2" in out
    (tmp_path / "matrix.json").write_text(json.dumps({"n": 2, "columns": {"delivery": {"label": "交付估计", "direction": "higher"}},
                                                      "rows": [{"login": "ann", "values": {"delivery": 50}}, {"login": "bob", "values": {"delivery": 10}}]}))
    assert "basis: matrix (2 candidates)" in run(["ann", "rank", "delivery"], out=tmp_path)
    assert "matrix lacks this key" in run(["ann", "rank", "team_leverage"], out=tmp_path)


def test_ondemand_cap(tmp_path):
    setup(tmp_path, n_prs=10)
    calls = []

    def fake(prs, rd, clone):
        calls.append(prs[0]["number"])
        return [{"number": prs[0]["number"], "V": 1, "C": 1, "N": 0, "L": 1, "Q": 1, "ell": 0.85, "P": 2.2,
                 "verified": dict.fromkeys("VCNLQ", True), "summary": "od", "llm_error": None}]

    assert "already deep-read" in run(["ann", "deepread", "1"], out=tmp_path, runner=fake) and not calls
    for n in range(2, 2 + C.ONDEMAND_DEEPREAD_CAP):
        assert "slots left" in run(["ann", "deepread", str(n)], out=tmp_path, runner=fake)
    out = run(["ann", "deepread", "9"], out=tmp_path, runner=fake)
    assert "cap reached" in out and len(calls) == C.ONDEMAND_DEEPREAD_CAP
    assert "deep read (ondemand): P=2.20" in run(["ann", "pr", "2"], out=tmp_path)
    assert "not one of ann's" in run(["ann", "deepread", "100"], out=tmp_path, runner=fake)
    # rebuilding the pack keeps the on-demand log, so the cap cannot be reset by a rebuild
    setup(tmp_path, n_prs=10)
    assert "cap reached" in run(["ann", "deepread", "9"], out=tmp_path, runner=fake)
