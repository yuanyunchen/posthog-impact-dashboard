"""Agent I/O for the fine stage (spec §10): anonymized L3 input, L4 input, prompt rendering, strict reply parsing."""
import json
import re
from pathlib import Path

from impact import config as C
from impact.contracts import validate

PROMPTS = Path(__file__).parent / "prompts"
ANGLES = ("delivery", "system", "quality", "team")


def render(name: str, **fields: str) -> str:
    """Fill {placeholders} by plain replace (prompts contain literal JSON braces)."""
    text = (PROMPTS / f"{name}.md").read_text()
    for k, v in fields.items():
        text = text.replace("{" + k + "}", v)
    return text


def l3_brief(pack: str | Path) -> str:
    """The L3 analyst brief needs only the pack dir; login = its last component."""
    login = Path(pack).name
    return render("evaluator", login=login, pack=str(pack),
                  calibration_cmds="\n".join(f"- `python -m impact.fine.query {login} rank {k}`" for k in C.L3_CALIBRATION_KEYS),
                  calibration_json=", ".join(f'"{k}": {v}' for k, v in zip(C.L3_CALIBRATION_KEYS, (85.0, 40.0, 61.5, "null"))))


def anonymize(text: str, cid_of: dict[str, str], names: dict[str, tuple[str, ...]] | None = None) -> str:
    """Every candidate login (and known display names) → cid; emails and profile links dropped; PR numbers stay.
    L3 works by login; everything L4 reads goes through this."""
    names = names or {}
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "[email]", text)
    subs = sorted(((n, cid) for login, cid in cid_of.items() for n in (login, *names.get(login, ()))),
                  key=lambda x: -len(x[0]))
    for n, cid in subs:
        text = re.sub(rf"https?://github\.com/{re.escape(n)}\b", cid, text, flags=re.I)
        text = re.sub(rf"(?<![\w-])@?{re.escape(n)}(?![\w-])", cid, text, flags=re.I)
    return text


def extract_json(text: str):
    """First JSON object/array in an agent reply, tolerating prose and ``` fences around it."""
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch in "{[":
            try:
                return dec.raw_decode(text, i)[0]
            except json.JSONDecodeError:
                continue
    raise ValueError("no JSON found in reply")


def _pr(x) -> int | None:
    """PR number from 123 / "#123" / ".../pull/123"; None for other evidence ids (workstream ids, metric keys)."""
    if isinstance(x, int):
        return x
    m = re.fullmatch(r"(?:#|.*/pull/)?(\d+)", str(x).strip())
    return int(m.group(1)) if m else None


def _need(obj: dict, keys: tuple[str, ...], where: str):
    for k in keys:
        if k not in obj or obj[k] in (None, "", [], {}):
            raise ValueError(f"{where}: missing or empty {k!r}")


def _grade(x, where: str):
    if not (isinstance(x, int) and 1 <= x <= 10):
        raise ValueError(f"{where}.grade: {x!r} not an int 1–10")


def parse_report(text: str, login: str, cid: str | None = None, **checks) -> dict:
    """L3 reply or report.json text → checked report. cid, when given, is set by the caller (agents sometimes
    mangle the echo); checks go to check_report."""
    rep = extract_json(text)
    if cid:
        rep["cid"] = cid
    check_report(rep, **checks)
    rep["login"] = login
    return rep


def check_report(rep: dict, known_prs: set[int] | None = None, known_workstreams: set[str] | None = None,
                 flag_prs: set[int] = frozenset()) -> dict:
    """Full L3 report check (also behind `python -m impact.contracts report <path>`). flag_prs = red-flag PRs
    from the dossier (e.g. reverted); each must surface in red_flags."""
    validate("report", rep)
    _need(rep["role"], ("primary_role", "team", "how_they_create_impact", "network_summary"), "report.role")
    if not 2 <= len(rep["core_contributions"]) <= 3:
        raise ValueError("report.core_contributions: need 2–3")
    cited = []
    for i, c in enumerate(rep["core_contributions"]):
        _need(c, ("workstream_id", "title", "what", "why_it_matters", "outcome", "his_role", "evidence_prs", "numbers"),
              f"report.core_contributions[{i}]")
        if known_workstreams is not None and c["workstream_id"] not in known_workstreams:
            raise ValueError(f"report cites unknown workstream {c['workstream_id']!r}")
        cited += c["evidence_prs"]
    for a in ANGLES:
        if a not in rep["angles"]:
            raise ValueError(f"report.angles: missing {a!r}")
        d = rep["angles"][a]
        _need(d, ("grade", "rationale", "claims"), f"report.angles.{a}")
        _grade(d["grade"], f"report.angles.{a}")
        for j, cl in enumerate(d["claims"]):
            _need(cl, ("statement", "numbers", "evidence_ids"), f"report.angles.{a}.claims[{j}]")
            cited += cl["evidence_ids"]
    _need(rep["overall"], ("grade", "confidence"), "report.overall")
    _grade(rep["overall"]["grade"], "report.overall")
    if rep["overall"]["confidence"] not in ("high", "medium", "low"):
        raise ValueError(f"report.overall.confidence: {rep['overall']['confidence']!r}")
    for k, field in (("insights", "insight"), ("red_flags", "flag")):
        for j, x in enumerate(rep[k]):
            _need(x, (field, "evidence_ids"), f"report.{k}[{j}]")
            cited += x["evidence_ids"]
    if not rep["insights"]:
        raise ValueError("report.insights: need ≥1")
    if "key_numbers" in rep:  # optional; the dashboard cards use it when present
        if len(rep["key_numbers"]) != 3:
            raise ValueError("report.key_numbers: need exactly 3 when present")
        for j, x in enumerate(rep["key_numbers"]):
            if miss := {"label", "value", "metric_key"} - x.keys():
                raise ValueError(f"report.key_numbers[{j}]: missing {sorted(miss)}")
    cal = rep["calibration"]
    _need(cal, ("ranks", "note"), "report.calibration")
    if miss := set(C.L3_CALIBRATION_KEYS) - cal["ranks"].keys():
        raise ValueError(f"report.calibration.ranks: missing {sorted(miss)} (null if unknown)")
    if bad := [k for k in C.L3_CALIBRATION_KEYS if not isinstance(cal["ranks"][k], (int, float, type(None)))]:
        raise ValueError(f"report.calibration.ranks: {bad} must be percentiles 0–100 or null")
    if len(rep["custom_analyses"]) < 2:
        raise ValueError("report.custom_analyses: need ≥2")
    for j, x in enumerate(rep["custom_analyses"]):
        _need(x, ("question", "why", "commands", "finding", "evidence_ids", "effect"), f"report.custom_analyses[{j}]")
        if not all("impact.fine.query" in c for c in x["commands"]):
            raise ValueError(f"report.custom_analyses[{j}].commands: must be impact.fine.query calls")
        cited += x["evidence_ids"]
    if miss := {"sampled_prs", "missing_data", "diff_truncated_share"} - rep["coverage"].keys():
        raise ValueError(f"report.coverage: missing {sorted(miss)}")
    prs = {n for n in map(_pr, cited) if n is not None}
    if known_prs is not None and (bad := prs - known_prs):
        raise ValueError(f"report cites PRs not in dossier: {sorted(bad)}")
    flagged = {_pr(e) for f in rep["red_flags"] for e in f["evidence_ids"]}
    if missing := set(flag_prs) - flagged:  # extremes are passed up, never averaged away
        raise ValueError(f"report.red_flags omits dossier red-flag PRs {sorted(missing)}")
    return rep


def parse_decision(text: str, judge: str, cids: list[str], r_rank: dict[str, int] | None = None) -> dict:
    """L4 decision over all candidates; r_rank enforces the >3-place deviation note (review R2)."""
    obj = validate("decision", extract_json(text))
    obj["judge"] = judge
    if not obj["context_summary"].strip():
        raise ValueError("decision.context_summary: empty")
    n, known = len(cids), set(cids)
    ranking = sorted(obj["ranking"], key=lambda e: e["rank"])
    if [e["rank"] for e in ranking] != list(range(1, n + 1)) or {e["cid"] for e in ranking} != known:
        raise ValueError(f"decision: need ranks 1..{n} covering every candidate once")
    for e in ranking:
        _need(e, ("context_role", "rationale"), f"decision.ranking[{e['cid']}]")
        comps = e.get("comparisons") or []
        if e["rank"] <= C.BORDA_TOP and not comps:
            raise ValueError(f"decision: {e['cid']} (rank {e['rank']}) has no comparisons")
        for c in comps:
            _need(c, ("vs", "why"), f"decision.ranking[{e['cid']}].comparisons")
            if c["vs"] not in known - {e["cid"]}:
                raise ValueError(f"decision: {e['cid']} compared with unknown {c['vs']!r}")
        if r_rank and abs(e["rank"] - r_rank[e["cid"]]) > C.RANK_DEVIATION and not e.get("deviation"):
            raise ValueError(f"decision: {e['cid']} is {e['rank']} vs R rank {r_rank[e['cid']]} without deviation note")
    k = min(C.FINAL_N, n)
    if {c.get("cid") for c in obj["top5_cases"]} != {e["cid"] for e in ranking[:k]}:
        raise ValueError("decision.top5_cases must cover exactly the ranking's top 5")
    for c in obj["top5_cases"]:
        _need(c, ("cid", "case"), "decision.top5_cases")
    for g in obj["archetype_groups"]:
        _need(g, ("archetype", "cids", "tradeoff"), "decision.archetype_groups")
        if set(g["cids"]) - known:
            raise ValueError(f"decision.archetype_groups: unknown cids {set(g['cids']) - known}")
    for r in obj["evidence_requests"]:
        _need(r, ("cid", "need"), "decision.evidence_requests")
        if r["cid"] not in known:
            raise ValueError(f"decision.evidence_requests: unknown cid {r['cid']!r}")
    obj["ranking"] = ranking
    return obj


def parse_pairwise(text: str, a: str, b: str, order: str) -> dict:
    """order "ab" = a was shown first. The agent must pick a or b."""
    obj = extract_json(text)
    obj = validate("pairwise", {"a": a, "b": b, "order": order, "reason": obj.get("reason"), "winner": obj.get("winner")})
    if obj["winner"] not in (a, b):
        raise ValueError(f"pairwise: winner {obj['winner']!r} not in ({a}, {b})")
    return obj


def graph_excerpt(team_graph: dict) -> str:
    """Compact team-graph summary for L4: every community (without member lists), bridge and single point; no events."""
    comm = [{k: c.get(k) for k in ("id", "size", "main_team", "top_teams", "purity", "hub")} for c in team_graph.get("communities", [])]
    return "\n".join([f"communities: {json.dumps(comm, ensure_ascii=False)}",
                      f"bridges: {json.dumps(team_graph.get('bridges', []), ensure_ascii=False)}",
                      f"single_points: {json.dumps(team_graph.get('single_points', []), ensure_ascii=False)}"])


def candidate_block(login: str, report: dict, matrix_row: dict, R: float, r_rank: int, cid_of: dict[str, str]) -> str:
    """One candidate for L4 prompts: script numbers (matrix row: metric → {raw, pct}) + the anonymized L3 report."""
    nums = "；".join(f"{m} {v['raw']}（P{round(v['pct'])}）" if v.get("pct") is not None else f"{m} {v['raw']}"
                    for m, v in matrix_row.items())
    rep = {k: v for k, v in report.items() if k != "login"}
    return anonymize(f"### {cid_of[login]}\nR = {R:.1f}（R 名次 {r_rank}）\n矩阵：{nums}\n"
                     f"报告：{json.dumps(rep, ensure_ascii=False)}", cid_of)


def decision_input(reports: dict[str, dict], matrix: dict[str, dict], refscores: list[dict],
                   cid_of: dict[str, str], order: list[str]) -> str:
    """All candidates in `order` (logins; the blind second run gets a different order). matrix: login → row."""
    R = {r["login"]: r["R"] for r in refscores}
    r_rank = {p: i + 1 for i, p in enumerate(sorted(R, key=lambda p: -R[p]))}
    return "\n\n".join(candidate_block(p, reports[p], matrix.get(p, {}), R[p], r_rank[p], cid_of) for p in order)
