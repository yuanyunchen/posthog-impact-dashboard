import json
import os

from impact import config as C, pipeline


def test_order_skip_and_force(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "OUT", tmp_path)
    calls = []
    files = {n: tmp_path / f"{n}.out" for n in pipeline.ORDER}
    src = tmp_path / "prs.jsonl"
    src.write_text("")

    def stage(name):
        def fn():
            calls.append(name)
            if name != "reviews" or not files[name].exists():  # resumable fetch with nothing new leaves the file untouched
                files[name].write_text("x")
            return {"counts": {}, "cost": 0.01, "errors": 0}
        return fn

    def fake(prs):  # each stage consumes the previous stage's output; reviews lists no outputs
        prev = [src] + [files[n] for n in pipeline.ORDER]
        return {n: ([prev[i]], [] if n == "reviews" else [files[n]], stage(n)) for i, n in enumerate(pipeline.ORDER)}

    monkeypatch.setattr(pipeline, "stages", fake)
    pipeline.run("all", src)
    assert calls == pipeline.ORDER
    calls.clear()
    rows = pipeline.run("all", src)
    assert calls == ["reviews"] and [r["skipped"] for r in rows] == [True, True, False, True]
    calls.clear()
    t = files["recall"].stat().st_mtime
    os.utime(src, (t + 10, t + 10))  # newer input → recall reruns, and its fresh output makes coarse stale
    pipeline.run("coarse", src)
    assert calls == []  # coarse alone: its input (recall output) is still older than its output
    pipeline.run("recall", src)
    pipeline.run("coarse", src)
    assert calls == ["recall", "coarse"]
    calls.clear()
    pipeline.run("fine-prep", src, force=True)
    assert calls == ["fine-prep"]
    log = [json.loads(l) for l in open(tmp_path / "run_log.jsonl")]
    assert len(log) == 12 and {"stage", "skipped", "seconds"} <= log[0].keys()


def test_review_caps_and_coverage(tmp_path, monkeypatch):
    import impact.data_extra as D
    monkeypatch.setattr(C, "OUT", tmp_path)
    monkeypatch.setattr(C, "REVIEW_DETAIL", tmp_path / "rd.jsonl")
    monkeypatch.setattr(C, "REVIEW_DETAIL_AUTHORED_CAP", 2)
    monkeypatch.setattr(C, "REVIEW_DETAIL_REVIEWED_CAP", 1)
    tiers = ["major", "routine", "trivial", "substantive"]
    prs = [{"number": i, "title": f"feat(s{i}): x", "credited_to": "ann", "author": "ann", "in_window": True,
            "merged_at": f"2026-08-1{i}T00:00:00Z", "files": [], "reviews": []} for i in range(4)]
    prs += [{"number": 10 + i, "title": "x", "credited_to": "bob", "author": "bob", "in_window": True,
             "merged_at": f"2026-08-1{i}T00:00:00Z", "files": [], "reviews": [{"author": "ann"}]} for i in range(3)]
    path = tmp_path / "prs.jsonl"
    path.write_text("".join(json.dumps(p) + "\n" for p in prs))
    (tmp_path / "coarse.json").write_text(json.dumps([{"login": "ann"}]))
    (tmp_path / "triage.jsonl").write_text("".join(json.dumps({"number": i, "tier": t, "llm_error": None}) + "\n"
                                                    for i, t in enumerate(tiers)))
    asked = []

    def fetch(nums):
        asked.extend(nums)
        (tmp_path / "rd.jsonl").write_text("".join(json.dumps({"number": n}) + "\n" for n in nums))
        return {"fetched": len(nums), "skipped": 0, "missing": [], "calls": 1, "cost": 1}

    monkeypatch.setattr(D, "fetch_review_detail", fetch)
    pipeline._reviews(path)
    # sample (≤ per-stratum caps) ∪ top-2 authored by points (major, substantive); reviewed: most recent of three 0-point PRs
    assert {0, 3} <= set(asked) and 12 in asked and not {10, 11} & set(asked)
    cov = json.loads((tmp_path / "review_coverage.json").read_text())["ann"]
    assert cov == {"authored_total": 4, "authored_fetched": 4, "reviewed_total": 3, "reviewed_fetched": 1}
