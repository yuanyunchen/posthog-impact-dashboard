"""Full-run orchestrator: python -m impact.pipeline <recall|coarse|reviews|fine-prep|fine-reseed|all> [--prs PATH] [--force].
A stage is skipped when all its outputs are newer than all its inputs; one line per stage goes to out/run_log.jsonl."""
import argparse
import importlib
import json
import time
from pathlib import Path

from impact import config as C
from impact.normalize import load

ORDER = ["recall", "coarse", "reviews", "fine-prep"]  # `all`; fine-reseed runs alone, after the first decision round


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in open(path)] if path.exists() else []


def _selected() -> list[str]:
    return [c["login"] for c in json.loads((C.OUT / "coarse.json").read_text())]


def _recall(prs: Path) -> dict:
    from impact.recall import run
    s = run.main(prs)
    return {"counts": {k: s.get(k) for k in ("people", "recalled", "audit_sampled")}, "cost": 0, "errors": 0}


def _coarse(prs: Path) -> dict:
    from impact.coarse import run
    run.main(prs)
    tri = _jsonl(C.OUT / "triage.jsonl")
    return {"counts": {"triaged": len(tri), "selected": len(_selected())},
            "cost": round(sum(t.get("cost") or 0 for t in tri), 4), "errors": sum(bool(t["llm_error"]) for t in tri)}


def _reviews(prs: Path) -> dict:
    """Disclosed caps (GraphQL quota): per candidate his deep-read sample + top REVIEW_DETAIL_AUTHORED_CAP authored PRs
    + top REVIEW_DETAIL_REVIEWED_CAP PRs he reviewed, ranked by tier points then recency. Coverage → review_coverage.json."""
    from impact.data_extra import fetch_review_detail
    from impact.fine.sample import stratified_sample
    who, all_prs = _selected(), load(prs)
    win = [p for p in all_prs if p["in_window"]]
    tri = {t["number"]: t for t in _jsonl(C.OUT / "triage.jsonl") if not t["llm_error"]}
    rank = lambda p: (C.TIER_POINTS.get(tri.get(p["number"], {}).get("tier"), 0), p["merged_at"])  # untriaged → 0
    _, people = _people(all_prs, who)
    want, nums = {}, []
    for login in who:
        authored = [p for p in win if p.get("credited_to") == login]
        reviewed = [p for p in win if p.get("credited_to") != login and any(r["author"] == login for r in p["reviews"])]
        sample = {n for ns in stratified_sample(people[login][0]).values() for n in ns}
        a = sample | {p["number"] for p in sorted(authored, key=rank, reverse=True)[:C.REVIEW_DETAIL_AUTHORED_CAP]}
        r = {p["number"] for p in sorted(reviewed, key=rank, reverse=True)[:C.REVIEW_DETAIL_REVIEWED_CAP]}
        want[login] = (len(authored), a, len(reviewed), r)
        nums += sorted(a | r)
    res = fetch_review_detail(nums)  # serial and resumable: numbers already in the file are skipped
    have = {r["number"] for r in _jsonl(C.REVIEW_DETAIL)}
    cov = {l: {"authored_total": at, "authored_fetched": len(a & have), "reviewed_total": rt, "reviewed_fetched": len(r & have)}
           for l, (at, a, rt, r) in want.items()}
    (C.OUT / "review_coverage.json").write_text(json.dumps(cov, indent=1))
    return {"counts": {"numbers": len(set(nums)), "fetched": res["fetched"], "skipped": res["skipped"], "gh_calls": res["calls"]},
            "cost": res["cost"], "errors": len(res["missing"]), "missing": res["missing"][:50]}


def _people(all_prs: list[dict], logins: list[str]) -> tuple[list[dict], dict[str, tuple[list[dict], list[list[int]]]]]:
    """(their window PRs, login → (own non-error triage rows, episodes)); episodes on the same basis as coarse/matrix."""
    from impact.episodes import group_episodes
    tri = {t["number"]: t for t in _jsonl(C.OUT / "triage.jsonl") if not t["llm_error"]}
    mine = [p for p in all_prs if p["in_window"] and p.get("credited_to") in logins]
    out = {}
    for login in logins:
        own = [p for p in mine if p["credited_to"] == login and p["number"] in tri]
        out[login] = ([tri[p["number"]] for p in own],
                      group_episodes([p for p in own if tri[p["number"]]["tier"] != "mechanical"]))
    return mine, out


def _review_detail() -> dict | None:
    return {r["number"]: r for r in _jsonl(C.REVIEW_DETAIL)} or None


def _fine_prep(prs: Path) -> dict:
    from impact.fine.sample import stratified_sample
    logins, all_prs = _selected(), load(prs)
    mine, people = _people(all_prs, logins)
    picked = {n for own, _ in people.values() for ns in stratified_sample(own).values() for n in ns}
    rd = _review_detail()

    def deepread(m):
        recs = m.deepread([p for p in mine if p["number"] in picked], rd, C.CLONE)
        (C.OUT / "deepread.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))

    def packs(m):  # dossier markdown (with its estimate) goes into each pack; nothing else writes out/candidates
        from impact.fine.dossier import build_dossier
        from impact.fine.sample import estimate
        opt = lambda p: json.loads(p.read_text()) if p.exists() else None
        metrics = {r["login"]: r["metrics"] for r in json.loads((C.OUT / "recall.json").read_text())}
        triage, reads = _jsonl(C.OUT / "triage.jsonl"), _jsonl(C.OUT / "deepread.jsonl")
        by_pr = {r["number"]: r for r in reads}
        roles, graph = opt(C.OUT / "roles.json") or {}, opt(C.OUT / "team_graph.json")
        team_map, lineage, changelog = opt(C.TEAM_MAP), opt(C.LINEAGE), opt(C.CHANGELOG)
        window = [p for p in all_prs if p["in_window"]]
        for login, (own, eps) in people.items():
            ws = opt(C.OUT / "workstreams" / f"{login}.json")
            _, md = build_dossier(login, metrics.get(login), own, [by_pr[t["number"]] for t in own if t["number"] in by_pr],
                                  estimate(own, by_pr, eps), rd, lineage, changelog, team_map,
                                  prs=[p for p in mine if p["credited_to"] == login], workstreams=ws,
                                  role_profile=roles.get(login))
            m.build_pack(login, window, triage, reads, md, team_map, graph, ws, prs)

    # matrix computes the per-person estimate itself (same episode basis as coarse)
    steps = [("deepread", "impact.fine.deepread", deepread),
             ("team_graph", "impact.fine.team_graph", lambda m: m.main(prs)),
             ("workstreams", "impact.fine.workstreams", lambda m: m.main(logins, prs)),
             ("roles", "impact.fine.roles", lambda m: m.main(prs)),
             ("matrix", "impact.fine.matrix", lambda m: m.main(prs)),
             ("packs", "impact.fine.pack", packs)]
    missing, failed = [], []
    for name, mod, call in steps:
        try:
            m = importlib.import_module(mod)
        except ModuleNotFoundError as e:
            if e.name != mod:
                raise
            missing.append(name)
            print(f"  fine-prep: {name} skipped, {mod} not written yet")
            continue
        try:
            call(m)
        except Exception as e:  # one broken step must not sink the run; reported in errors
            failed.append(f"{name}: {type(e).__name__}: {e}"[:300])
            print(f"  fine-prep: {name} FAILED {failed[-1]}")
    reads = _jsonl(C.OUT / "deepread.jsonl")
    return {"counts": {"candidates": len(logins), "sampled": len(picked), "deepread": len(reads),
                       "deepread_llm_error": sum(bool(r.get("llm_error")) for r in reads)},
            "cost": round(sum(r.get("cost") or 0 for r in reads), 4), "errors": len(failed),
            "missing_modules": missing, "failed": failed}


def _fine_reseed(prs: Path) -> dict:
    """R11: boundary candidates (consensus ranks BOUNDARY_RANKS) re-estimated from a SEED_ALT sample."""
    from impact.fine.aggregate import boundary_zone
    from impact.fine.deepread import deepread
    from impact.fine.sample import estimate, stratified_sample
    boundary = boundary_zone(json.loads((C.OUT / "final.json").read_text())["method_notes"]["consensus"])
    mine, people = _people(load(prs), boundary)
    samples = {(l, seed): {n for ns in stratified_sample(own, seed).values() for n in ns}
               for l, (own, _) in people.items() for seed in (C.SEED, C.SEED_ALT)}
    union = set().union(*samples.values()) if samples else set()
    reads = {r["number"]: r for r in deepread([p for p in mine if p["number"] in union], _review_detail(), C.CLONE)}
    out = {}
    for login, (own, eps) in people.items():
        hat = {seed: estimate(own, {n: reads[n] for n in samples[login, seed]}, eps)["delivery_hat"]
               for seed in (C.SEED, C.SEED_ALT)}
        out[login] = {"delivery_hat_seed7": hat[C.SEED], "delivery_hat_seed11": hat[C.SEED_ALT],
                      "delta_pct": round(100 * (hat[C.SEED_ALT] - hat[C.SEED]) / hat[C.SEED], 1) if hat[C.SEED] else None}
    (C.OUT / "reseed.json").write_text(json.dumps(out, indent=1))
    return {"counts": {"boundary": len(out), "read": len(reads),
                       "new_vs_seed7": len(union - set().union(*(v for (_, s), v in samples.items() if s == C.SEED)))},
            "cost": round(sum(r.get("cost") or 0 for r in reads.values()), 4),
            "errors": sum(bool(r.get("llm_error")) for r in reads.values())}


def stages(prs: Path) -> dict:
    """name → (inputs, outputs, fn). reviews has no outputs listed: it always runs and resumes itself."""
    O, prompt = C.OUT, Path(__file__).parent / "coarse/prompts/triage.md"
    return {
        "recall": ([prs, C.DATA / "changelog.json", C.TEAM_MAP], [O / "recall.json", O / "recall_audit_sample.json"],
                   lambda: _recall(prs)),
        "coarse": ([prs, O / "recall.json", O / "recall_audit_sample.json", prompt], [O / "triage.jsonl", O / "coarse.json"],
                   lambda: _coarse(prs)),
        "reviews": ([prs, O / "coarse.json"], [], lambda: _reviews(prs)),
        "fine-prep": ([prs, O / "coarse.json", O / "triage.jsonl", C.REVIEW_DETAIL],
                      [O / "deepread.jsonl", O / "matrix.json", O / "candidates"], lambda: _fine_prep(prs)),
        "fine-reseed": ([prs, O / "final.json", O / "triage.jsonl"], [O / "reseed.json"], lambda: _fine_reseed(prs)),
    }


def fresh(inputs: list[Path], outputs: list[Path]) -> bool:
    if not outputs or not all(o.exists() for o in outputs):
        return False
    newest_in = max((i.stat().st_mtime for i in inputs if i.exists()), default=0)
    return min(o.stat().st_mtime for o in outputs) > newest_in


def run(stage: str, prs: Path = C.PRS, force: bool = False) -> list[dict]:
    table, rows = stages(prs), []
    C.OUT.mkdir(exist_ok=True)
    for name in ORDER if stage == "all" else [stage]:
        inputs, outputs, fn = table[name]
        t0 = time.time()
        row = {"stage": name, "skipped": True} if not force and fresh(inputs, outputs) else {"stage": name, "skipped": False, **fn()}
        row |= {"seconds": round(time.time() - t0, 1), "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        print(f"[{name}] {'skipped (outputs newer than inputs)' if row['skipped'] else ''}"
              f"{json.dumps({k: v for k, v in row.items() if k not in ('stage', 'skipped', 'at')})}")
        with open(C.OUT / "run_log.jsonl", "a") as f:
            f.write(json.dumps(row) + "\n")
        rows.append(row)
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=ORDER + ["fine-reseed", "all"])
    ap.add_argument("--prs", type=Path, default=C.PRS)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    run(a.stage, a.prs, a.force)
