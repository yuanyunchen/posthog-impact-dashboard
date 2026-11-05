"""L4 aggregation (spec §9.4/§10, review R10/R11): Borda(primary, blind second, R) → disputed boundary pairs
→ devil → gates → weight sensitivity."""
import json
import random
import sys
from pathlib import Path

from impact import config as C
from impact.contracts import validate
from impact.fine.refscore import combine, percentiles, refscore


def borda(rankings: list[list[str]]) -> dict[str, int]:
    """Rank 1 → BORDA_TOP points … rank BORDA_TOP → 1, summed over rankers."""
    scores: dict[str, int] = {}
    for ranking in rankings:
        for i, x in enumerate(ranking[:C.BORDA_TOP]):
            scores[x] = scores.get(x, 0) + C.BORDA_TOP - i
    return scores


def _above(ranking: list[str], x: str, y: str) -> bool:
    """x above y; anyone missing from a ranking sits below everyone listed."""
    n = len(ranking)
    return (ranking.index(x) if x in ranking else n) < (ranking.index(y) if y in ranking else n)


def boundary_zone(order: list[str]) -> list[str]:
    return order[C.BOUNDARY_RANKS[0] - 1:C.BOUNDARY_RANKS[1]]


def disputed_pairs(order: list[str], primary: list[str], second: list[str]) -> list[tuple[str, str]]:
    """Pairs inside consensus ranks 4–8 that the two deciders order differently — the only ones sent to pairwise."""
    zone = boundary_zone(order)
    return [(x, y) for i, x in enumerate(zone) for y in zone[i + 1:]
            if _above(primary, x, y) != _above(second, x, y)]


def boundary_resolve(order: list[str], pairwise: list[dict], agreed: list[list[str]] = ()) -> list[str]:
    """Re-order consensus ranks 4–8 by wins (Copeland). A pair's win comes from `agreed` rankings when they all
    order it the same way, otherwise from pairwise when both presentation orders agree; anything else is a tie."""
    lo = C.BOUNDARY_RANKS[0] - 1
    zone = boundary_zone(order)
    votes: dict[frozenset, dict[str, str]] = {}
    for p in pairwise:
        if p["a"] in zone and p["b"] in zone:
            votes.setdefault(frozenset((p["a"], p["b"])), {})[p["order"]] = p["winner"]
    wins = dict.fromkeys(zone, 0)
    for i, x in enumerate(zone):
        for y in zone[i + 1:]:
            if agreed and len({_above(r, x, y) for r in agreed}) == 1:
                wins[x if _above(agreed[0], x, y) else y] += 1
                continue
            v = votes.get(frozenset((x, y)), {})
            if len(v) == 2 and len(set(v.values())) == 1:  # both presentation orders asked and agree
                wins[v["ab"]] += 1
    zone = sorted(zone, key=lambda x: (-wins[x], order.index(x)))  # tie → consensus position
    return order[:lo] + zone + order[lo + len(zone):]


def kendall_tau(a: list[str], b: list[str]) -> float:
    """Tau-a over the items both rankings contain."""
    common = [x for x in a if x in b]
    pairs = [(x, y) for i, x in enumerate(common) for y in common[i + 1:]]
    if not pairs:
        return 1.0
    return sum(1 if _above(b, x, y) else -1 for x, y in pairs) / len(pairs)


def check_gates(login: str, facts: dict) -> dict:
    """facts = {login: {major, landmark, team_leverage, reverted, followup_rate, top7_share}} over all candidates."""
    f = facts[login]
    lev = f["team_leverage"] or 0
    team_top = lev > 0 and sum((facts[x]["team_leverage"] or 0) > lev for x in facts) < C.GATE_TEAM_TOP
    follow = percentiles({x: facts[x]["followup_rate"] for x in facts})
    # relative AND absolute: a worst-20% rank among near-identical 2–4% rates is not a red flag
    worst = (f["followup_rate"] or 0) >= C.GATE_FOLLOWUP_MIN_RATE and follow[login] >= C.GATE_FOLLOWUP_WORST_PCT
    return {"a": f["major"] >= C.GATE_MIN_MAJOR or f["landmark"] >= C.GATE_MIN_LANDMARK or team_top,
            "b": f["reverted"] < C.GATE_MAX_REVERTED and not worst,
            "c": f["top7_share"] >= C.GATE_TOP7_SHARE - 1e-9}


def apply_gates(order: list[str], facts: dict, justifications: dict[str, str]) -> tuple[list[str], list[dict]]:
    """Walk the order; a gate failure without a manager justification is skipped and the next one moves up."""
    top, log = [], []
    for x in order:
        if len(top) == C.FINAL_N:
            break
        g = check_gates(x, facts)
        if all(g.values()):
            action = "pass"
        elif x in justifications:
            action = "kept_by_justification"
        else:
            action = "dropped"
        log.append({"login": x, "gates": g, "action": action, "justification": justifications.get(x)})
        if action != "dropped":
            top.append(x)
    return top, log


def weight_sensitivity(refscores: list[dict], n: int = C.SENS_DRAWS, seed: int = C.SEED) -> dict[str, float]:
    """Share of draws (weights × U(0.5,1.5), renormalized) in which each person's R is top 5."""
    rng = random.Random(seed)
    angles = {r["login"]: {a: v["score"] for a, v in r["angles"].items()} for r in refscores}
    hits = dict.fromkeys(angles, 0)
    for _ in range(n):
        w = {a: b * rng.uniform(1 - C.SENS_SPREAD, 1 + C.SENS_SPREAD) for a, b in C.ANGLE_WEIGHTS.items()}
        total = sum(w.values())
        w = {a: v / total for a, v in w.items()}
        r = {p: combine(s, w) or 0 for p, s in angles.items()}
        for p in sorted(r, key=lambda p: (-r[p], p))[:C.FINAL_N]:
            hits[p] += 1
    return {p: h / n for p, h in hits.items()}


def stability_label(freq: float) -> str:
    return "stable" if freq >= C.STABLE_MIN else "borderline" if freq >= C.BORDERLINE_MIN else "verdict_only"


def apply_devil(order: list[str], devil: list[dict]) -> list[str]:
    """decision "replace" swaps the objected person with the replacement; gates are re-checked afterwards."""
    order = list(order)
    for d in devil:
        if d["decision"] == "replace":
            i, j = order.index(d["cid"]), order.index(d["replacement_cid"])
            order[i], order[j] = order[j], order[i]
    return order


def finalize(refscores: list[dict], primary: dict, second: dict, pairwise: list[dict], facts: dict,
             justifications: dict[str, str], cid_map: dict[str, str], reports: dict | None = None,
             devil: list[dict] | None = None) -> dict:
    """primary / second (decision contract), pairwise, devil use cids (cid_map: cid → login);
    refscores, facts, reports use logins. Consensus = Borda over [primary, second]; R only breaks ties (scores are reference, agents decide)."""
    reports, devil = reports or {}, devil or []
    login = cid_map.__getitem__
    P, S = ([login(e["cid"]) for e in sorted(d["ranking"], key=lambda e: e["rank"])] for d in (primary, second))
    pw = [{**p, "a": login(p["a"]), "b": login(p["b"]), "winner": login(p["winner"])} for p in pairwise]
    dv = [{**d, "cid": login(d["cid"]), "replacement_cid": login(d["replacement_cid"])} for d in devil]
    R = {r["login"]: r["R"] for r in refscores}
    by_r = sorted(R, key=lambda p: -R[p])
    voters = [P, S]  # R is not a voter: user ruling 2026-11-03, agent judgment decides, scores are reference only
    for p in facts:  # gate (c): share of the two independent decisions listing p in their top 7
        facts[p]["top7_share"] = sum(p in v[:C.GATE_TOP7] for v in voters) / len(voters)

    b = borda(voters)
    consensus = sorted(R, key=lambda p: (-b.get(p, 0), -R[p], p))  # Borda tie → R
    resolved = boundary_resolve(consensus, pw, agreed=[P, S])
    order = apply_devil(resolved, dv)
    top, gate_log = apply_gates(order, facts, justifications)
    freq = weight_sensitivity(refscores)
    cases = {login(c["cid"]): c["case"] for c in primary["top5_cases"]}

    cid_of = {l: c for c, l in cid_map.items()}

    def entry(p, rank):
        rep = reports.get(p, {})
        prs = [n for c in rep.get("core_contributions", []) for n in c["evidence_prs"]]
        return {"login": p, "cid": cid_of.get(p), "rank": rank, "borda": b.get(p, 0), "consensus_rank": consensus.index(p) + 1,
                "primary_rank": P.index(p) + 1 if p in P else None, "second_rank": S.index(p) + 1 if p in S else None,
                "R": R[p], "R_rank": by_r.index(p) + 1, "stability": stability_label(freq[p]),
                "stability_freq": freq[p], "gates": check_gates(p, facts), "justification": justifications.get(p),
                "why": cases.get(p) or rep.get("positioning", ""), "evidence": list(dict.fromkeys(prs))[:3]}

    rest = [p for p in order if p not in top]
    return validate("final", {
        "top5": [entry(p, i + 1) for i, p in enumerate(top)],
        "next5": [entry(p, len(top) + i + 1) for i, p in enumerate(rest[:C.FINAL_N])],
        "method_notes": {
            "context_summary": {"primary": primary["context_summary"], "second": second["context_summary"]},
            "consensus_voters": ["primary", "second (blind)"],  # R breaks Borda ties only
            "gates": {"a": f"≥{C.GATE_MIN_MAJOR} major or ≥{C.GATE_MIN_LANDMARK} landmark or team leverage top {C.GATE_TEAM_TOP}",
                      "b": f"<{C.GATE_MAX_REVERTED} reverts and not (follow-up-fix rate ≥{C.GATE_FOLLOWUP_MIN_RATE:.0%} and in worst {100 - C.GATE_FOLLOWUP_WORST_PCT}%)",
                      "c": f"in the top {C.GATE_TOP7} of both independent decisions (else manager justification)"},
            "sensitivity_scope": "reference-weight sensitivity of R only; does not measure sampling, attribution or judge variance",
            "primary_vs_second": {"top5_overlap": len(set(P[:C.FINAL_N]) & set(S[:C.FINAL_N])),
                                  "kendall_tau": round(kendall_tau(P, S), 3)},
            "consensus": consensus, "disputed_pairs": disputed_pairs(consensus, P, S),
            "after_pairwise": resolved, "after_devil": order, "gate_log": gate_log, "devil": dv,
            "sixth_place_note": primary["sixth_place_note"],
            "evidence_requests": [{**r, "cid": login(r["cid"]), "by": by} for by, d in (("primary", primary),
                                  ("second", second)) for r in d["evidence_requests"]],
            "r_divergence": [{"login": p, "final_rank": i + 1, "R_rank": by_r.index(p) + 1}
                             for i, p in enumerate(top) if by_r.index(p) >= C.FINAL_N],
            "verdict_only_unjustified": [p for p in top if stability_label(freq[p]) == "verdict_only"
                                         and p not in justifications],  # spec §9.4.6: needs a manager argument
            "sensitivity": f"{C.SENS_DRAWS} draws, weights × U({1 - C.SENS_SPREAD},{1 + C.SENS_SPREAD}), seed {C.SEED}",
        },
    })


# --- CLI over an output dir (the dashboard reads these paths):
#   python -m impact.fine.aggregate prep|pairs|devil|final [OUT]   (OUT defaults to config.OUT)
# prep  : candidates/*/report.json + matrix/recall/coarse + context/company.md + team_graph.json → refscore.json, decision/cids.json, decision/{primary,second}_prompt.md
# pairs : decision/{primary,second}.json → decision/pairwise/<a>-<b>-<ab|ba>.prompt.md (replies: same name, .json)
# devil : tentative top 5 → decision/devil_prompt.md (manager writes decision/devil.json with rebuttal + decision)
# final : everything above (+ optional decision/justifications.json {login: text}) → final.json
def _j(p: Path):
    return json.loads(p.read_text())


def _num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _p_weighted(reads: list[dict], k: str):
    w = [(r[k], r.get("P") or 1) for r in reads if _num(r.get(k)) is not None]
    return sum(v * p for v, p in w) / sum(p for _, p in w) if w else None


def load_people(out: Path) -> dict[str, dict]:
    """refscore signals from matrix.json, recall.json, team_graph.json people and each pack's sampled deep reads;
    anything absent → None (unknown, left out of averages)."""
    rows = {r["login"]: r["values"] for r in _j(out / "matrix.json")["rows"]}
    rec = {r["login"]: r["metrics"] for r in _j(out / "recall.json")} if (out / "recall.json").exists() else {}
    net = _j(out / "team_graph.json").get("people", {}) if (out / "team_graph.json").exists() else {}
    nv = lambda l, k: _num((net.get(l, {}).get(k) or {}).get("value"))
    people = {}
    for login, v in rows.items():
        m, f = rec.get(login, {}), out / "candidates" / login / "prs.jsonl"
        reads = [p["deepread"] for p in map(json.loads, f.read_text().splitlines()) if p.get("deepread")] if f.exists() else []
        people[login] = {
            "delivery_hat": v.get("delivery"), "changelog_weighted": v.get("changelog_prs"),
            "issue_reactions": _num(m.get("issue_reactions")), "core_share": _num(m.get("core_share")),
            "deepread_L": _p_weighted(reads, "L"), "deepread_Q": _p_weighted(reads, "Q"),
            "downstream_authors": v.get("downstream_authors"), "quality_rate": v.get("quality_rate"),
            "changes_requested_rounds": nv(login, "changes_rounds_mean"), "review_leverage": v.get("team_leverage"),
            "comment_line_changed_rate": nv(login, "changes_adopted_rate"),  # proxy: his change requests the author acted on
            "review_requesters": v.get("requested_by")}
    return people


def load_facts(out: Path, logins) -> dict[str, dict]:
    coarse = {c["login"]: c for c in _j(out / "coarse.json")}
    rec = {r["login"]: r["metrics"] for r in _j(out / "recall.json")}
    facts = {}
    for l in logins:
        tc, m = coarse.get(l, {}).get("tier_counts", {}), rec.get(l, {})
        facts[l] = {"major": tc.get("major", 0), "landmark": tc.get("landmark", 0), "team_leverage": _num(m.get("team_leverage")),
                    "reverted": _num(m.get("reverted")) or 0,
                    "followup_rate": m["followup_fixed"] / m["mature_prs"] if _num(m.get("mature_prs")) and
                    _num(m.get("followup_fixed")) is not None else None}
    return facts


def load_reports(out: Path, logins) -> dict[str, dict]:
    from impact.fine.cards import check_report
    reports, bad = {}, {}
    for l in logins:
        f = out / "candidates" / l / "report.json"
        try:
            reports[l] = check_report(_j(f)) | {"login": l}
        except (OSError, ValueError) as e:
            bad[l] = str(e)
    if bad:
        raise SystemExit("L3 reports missing or invalid:\n" + "\n".join(f"  {l}: {e}" for l, e in bad.items()))
    return reports


def _matrix_rows(out: Path) -> dict[str, dict]:
    return {r["login"]: {k: {"raw": v, "pct": r.get("pct", {}).get(k)} for k, v in r["values"].items()}
            for r in _j(out / "matrix.json")["rows"]}


def _decisions(out: Path, cid_map: dict, refscores: list[dict]) -> tuple[dict, dict]:
    from impact.fine.cards import parse_decision
    cid_of = {l: c for c, l in cid_map.items()}
    r_rank = {cid_of[r["login"]]: i + 1 for i, r in enumerate(refscores)}
    d = out / "decision"
    return tuple(parse_decision((d / f"{n}.json").read_text(), n, list(cid_map), r_rank) for n in ("primary", "second"))


def _pairwise(out: Path) -> list[dict]:
    from impact.fine.cards import parse_pairwise
    got = []
    for f in sorted((out / "decision" / "pairwise").glob("*.json")):
        a, b, o = f.stem.split("-")
        got.append(parse_pairwise(f.read_text(), a, b, o))
    return got


def cli(step: str, out: Path = C.OUT) -> str:
    from impact.fine import cards as K
    d = out / "decision"
    d.mkdir(parents=True, exist_ok=True)
    if step == "prep":
        people = load_people(out)
        reports = load_reports(out, people)
        rs = refscore(people, reports)
        (out / "refscore.json").write_text(json.dumps(rs, indent=1, ensure_ascii=False))
        logins = sorted(people)
        random.Random(C.SEED).shuffle(logins)
        cid_map = {f"C{i + 1:02d}": l for i, l in enumerate(logins)}
        (d / "cids.json").write_text(json.dumps(cid_map, indent=1))
        cid_of, mx = {l: c for c, l in cid_map.items()}, _matrix_rows(out)
        missing = [f for f in (out / "context" / "company.md", out / "team_graph.json") if not f.exists()]
        if missing:  # the decider must read the company context first (spec, L4 step A)
            raise SystemExit(f"L4 inputs missing: {[str(f) for f in missing]}")
        company = K.anonymize((out / "context" / "company.md").read_text(), cid_of)
        graph = K.anonymize(K.graph_excerpt(_j(out / "team_graph.json")), cid_of)
        for name, seed in (("primary", C.SEED), ("second", C.SEED_ALT)):  # blind second: different candidate order
            order = sorted(people)
            random.Random(seed + 1).shuffle(order)
            (d / f"{name}_prompt.md").write_text(K.render(
                "ranker", n=str(len(order)), k=str(min(C.BORDA_TOP, len(order))), company=company, graph=graph,
                candidates=K.decision_input(reports, mx, rs, cid_of, order)))
        return f"refscore + cids + primary/second prompts for {len(people)} candidates → {d}"
    rs, cid_map = _j(out / "refscore.json"), _j(d / "cids.json")
    people = [r["login"] for r in rs]
    reports, facts = load_reports(out, people), load_facts(out, people)
    primary, second = _decisions(out, cid_map, rs)
    pw = _pairwise(out) if (d / "pairwise").exists() else []
    just = _j(d / "justifications.json") if (d / "justifications.json").exists() else {}
    R = {r["login"]: r["R"] for r in rs}
    by_r = sorted(R, key=lambda p: -R[p])
    cid_of, mx = {l: c for c, l in cid_map.items()}, _matrix_rows(out)
    blk = lambda l: K.candidate_block(l, reports[l], mx.get(l, {}), R[l], by_r.index(l) + 1, cid_of)
    if step == "pairs":
        pairs = finalize(rs, primary, second, [], facts, just, cid_map, reports)["method_notes"]["disputed_pairs"]
        (d / "pairwise").mkdir(exist_ok=True)
        for x, y in pairs:
            for o, (first, nxt) in (("ab", (x, y)), ("ba", (y, x))):
                (d / "pairwise" / f"{cid_of[x]}-{cid_of[y]}-{o}.prompt.md").write_text(
                    K.render("pairwise", first=blk(first), second=blk(nxt)))
        return f"{len(pairs)} disputed boundary pairs → {2 * len(pairs)} prompts in {d / 'pairwise'}"
    if step == "devil":
        top = [e["login"] for e in finalize(rs, primary, second, pw, facts, just, cid_map, reports)["top5"]]
        (d / "devil_prompt.md").write_text(K.render("devil", top5="\n\n".join(map(blk, top)),
                                                    rest="\n\n".join(blk(l) for l in by_r if l not in top)))
        return f"tentative top 5 {[cid_of[l] for l in top]} → {d / 'devil_prompt.md'}"
    if step == "final":
        devil = _j(d / "devil.json") if (d / "devil.json").exists() else []
        final = finalize(rs, primary, second, pw, facts, just, cid_map, reports, devil)
        (out / "final.json").write_text(json.dumps(final, indent=1, ensure_ascii=False))
        return f"final top 5 {[e['login'] for e in final['top5']]} → {out / 'final.json'}"
    raise SystemExit(f"unknown step {step!r}: prep | pairs | devil | final")


if __name__ == "__main__":
    print(cli(sys.argv[1], Path(sys.argv[2]) if len(sys.argv) > 2 else C.OUT))

