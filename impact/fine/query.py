"""Query tool over a candidate's data pack (spec §12): `python -m impact.fine.query <login> <cmd> [args]`.
Compact text, ≤ config.QUERY_MAX_LINES lines; never prints PR bodies or diffs."""
import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from impact import config as C
from impact.fine.refscore import percentiles

RECALL_KEYS = ["prs", "w_rule_sum", "core_share", "areas", "active_weeks", "reviews_given", "authors_served",
               "team_leverage", "first_review_median_h", "quality_q", "reverted", "followup_fixed", "changelog_prs"]


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in open(p) if l.strip()] if p.exists() else []


def _fmt(x) -> str:
    return "unknown" if x is None else f"{x:.2f}".rstrip("0").rstrip(".") if isinstance(x, float) else str(x)


class Pack:
    def __init__(self, login: str, out: Path = C.OUT):
        self.login, self.out, self.dir = login, out, out / "candidates" / login
        if not (self.dir / "prs.jsonl").exists():
            raise SystemExit(f"no data pack for {login} under {self.dir}")
        self.meta = json.loads((self.dir / "meta.json").read_text())
        self.ondemand = {r["number"]: r for r in _jsonl(self.dir / "ondemand.jsonl")}
        self.prs = _jsonl(self.dir / "prs.jsonl")
        for p in self.prs:  # on-demand reads show up like sampled ones, labelled source=ondemand
            if p["deepread"] is None and (r := self.ondemand.get(p["number"])):
                p["deepread"], p["P"], p["summary"] = r, round(r["P"], 2), r.get("summary") or p["summary"]
        self.by_num = {p["number"]: p for p in self.prs}

    def json(self, name: str):
        return json.loads((self.dir / name).read_text())


def _points(p: dict) -> float:
    return p["P"] if p["P"] is not None else C.TIER_POINTS.get(p["tier"], 0)


def _line(p: dict) -> str:
    dr = p["deepread"]
    scores = f" P={p['P']:.1f} V{dr['V']}C{dr['C']}N{dr['N']}L{dr['L']}Q{dr['Q']}" if dr else ""
    return f"#{p['number']} {p['merged_at'][:10]} {p['tier']}{scores} [{p['area']}] {' '.join(str(p['summary'] or p['title']).split())[:120]}"


def cmd_prs(pk: Pack, a) -> list[str]:
    sel = [p for p in pk.prs if (not a.ws or p.get("workstream") == a.ws) and (not a.area or a.area.lower() in p["area"].lower()) and (not a.tier or p["tier"] == a.tier)
           and (not a.since or p["merged_at"][:10] >= a.since) and (not a.until or p["merged_at"][:10] <= a.until)]
    tiers = Counter(p["tier"] for p in sel)
    return [f"{len(sel)} of {len(pk.prs)} PRs · points {sum(map(_points, sel)):.1f} · " + ", ".join(f"{k} {v}" for k, v in tiers.most_common())] \
        + [_line(p) for p in sel]


def cmd_pr(pk: Pack, a) -> list[str]:
    p = pk.by_num.get(a.n)
    if not p:
        return [f"#{a.n} is not one of {pk.login}'s window PRs"]
    L = [f"#{p['number']} {p['title']}", f"merged {p['merged_at']} · area {p['area']} · tier {p['tier']} · type {p['work_type']} · lines {p['lines']}",
         f"summary: {p['summary']}"]
    if dr := p["deepread"]:
        L += [f"deep read ({dr.get('source')}): P={dr['P']:.2f} ell={dr['ell']:.2f} " + " ".join(f"{k}={dr[k]}" for k in "VCNLQ"),
              "quotes verified: " + " ".join(f"{k}={'y' if v else 'n'}" for k, v in (dr.get("verified") or {}).items())
              + f" · diff {dr.get('diff_source')}{' truncated' if dr.get('diff_truncated') else ''}"]
    else:
        L.append(f"not deep-read (use `deepread {p['number']}`; {C.ONDEMAND_DEEPREAD_CAP - len(pk.ondemand)} left)")
    return L


def _reviews(rows: list[dict], who: str, top: int, noun: str) -> list[str]:
    by_person, by_team, prs = defaultdict(set), defaultdict(set), {r["number"] for r in rows}
    for r in rows:
        by_person[r[who]].add(r["number"])
        for t in r["team"] or ["(no team)"]:
            by_team[t].add(r["number"])
    rank = lambda d: sorted(d.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    L = [f"{len(rows)} reviews on {len(prs)} PRs, {len(by_person)} {noun}",
         "by state: " + ", ".join(f"{k} {v}" for k, v in Counter(r["state"] for r in rows).most_common()),
         f"by {noun[:-1]} (PRs):"]
    L += [f"  {k}: {len(v)}" for k, v in rank(by_person)[:top]]
    L += [f"  ... {len(by_person) - top} more" ] if len(by_person) > top else []
    L += ["by team (PRs): " + ", ".join(f"{k} {len(v)}" for k, v in rank(by_team))]
    return L


def cmd_reviews_given(pk: Pack, a) -> list[str]:
    return ["reviews he gave on others' PRs:"] + _reviews(pk.json("reviews.json")["given"], "author", a.top, "authors")


def cmd_reviews_received(pk: Pack, a) -> list[str]:
    return ["reviews his PRs received:"] + _reviews(pk.json("reviews.json")["received"], "reviewer", a.top, "reviewers")


def cmd_timeline(pk: Pack, a) -> list[str]:
    weeks = defaultdict(list)
    for p in pk.prs:
        d = datetime.fromisoformat(p["merged_at"][:10])
        weeks[(d - timedelta(days=d.weekday())).date().isoformat()].append(p)
    L = ["week (Mon) | PRs | points | major+ | deep-read"]
    if weeks:  # empty weeks stay visible: gaps are evidence too
        w, last = min(weeks), max(weeks)
        while w < last:
            w = (datetime.fromisoformat(w) + timedelta(days=7)).date().isoformat()
            weeks.setdefault(w, [])
    L += [f"{w} | {len(ps)} | {sum(map(_points, ps)):.1f} | {sum(p['tier'] in ('major', 'landmark') for p in ps)} | "
          f"{sum(p['deepread'] is not None for p in ps)}" for w, ps in sorted(weeks.items())]
    return L


def _population(out: Path, key: str) -> tuple[str, dict, dict] | None:
    """(basis, {login: value}, column info) from the matrix when it has the column, else from recall metrics."""
    m = out / "matrix.json"
    if m.exists() and key in (mx := json.loads(m.read_text()))["columns"]:
        return f"matrix ({mx['n']} candidates)", {r["login"]: r["values"].get(key) for r in mx["rows"]}, mx["columns"][key]
    r = out / "recall.json"
    if r.exists():
        rows = json.loads(r.read_text())
        vals = {x["login"]: x["metrics"].get(key) for x in rows}
        if any(v is not None for v in vals.values()):
            num = {k: v if isinstance(v, (int, float)) and not isinstance(v, bool) else None for k, v in vals.items()}
            return f"recall ({len(rows)} people; matrix {'lacks this key' if m.exists() else 'absent'})", num, {}
    return None


def cmd_rank(pk: Pack, a) -> list[str]:
    pop = _population(pk.out, a.metric)
    if pop is None:
        return [f"unknown metric {a.metric!r}: not a matrix column and not a recall metric"]
    basis, vals, col = pop
    lower = col.get("direction") == "lower"
    known = sorted(((v, k) for k, v in vals.items() if v is not None), reverse=not lower)
    # percentile and position read "higher = better" for every metric, so lower-is-better columns are flipped
    pct = {k: (None if v is None else 100 - v) for k, v in percentiles(vals).items()} if lower else percentiles(vals)
    L = [f"{a.metric}{' (' + col.get('label', '') + ', ' + col.get('direction', '') + ' is better)' if col else ''} · basis: {basis}"]
    if pk.login not in vals:
        L.append(f"{pk.login} is not in this population")
    elif vals[pk.login] is None:
        L.append(f"{pk.login}: unknown (left out of percentiles)")
    else:
        pos = 1 + sum((v < vals[pk.login]) if lower else (v > vals[pk.login]) for v, _ in known)
        L.append(f"{pk.login}: {_fmt(vals[pk.login])} · percentile {pct[pk.login]:.1f} · position {pos}/{len(known)} (1 = best)")
    if known:
        L.append(f"top: " + ", ".join(f"{k} {_fmt(v)}" for v, k in known[:3]) + f" · median {_fmt(known[len(known) // 2][0])}"
                 + f" · unknown {len(vals) - len(known)}")
    return L


def cmd_compare(pk: Pack, a) -> list[str]:
    me, other = pk.login, a.other
    m = pk.out / "matrix.json"
    rows = {r["login"]: r for r in json.loads(m.read_text())["rows"]} if m.exists() else {}
    rec = {r["login"]: r["metrics"] for r in json.loads((pk.out / "recall.json").read_text())} if (pk.out / "recall.json").exists() else {}
    L = [f"key | {me} | {other}"]
    if me in rows and other in rows:
        L += [f"matrix.{k} | {_fmt(rows[me]['values'][k])} (p{_fmt(rows[me]['pct'][k])}) | {_fmt(rows[other]['values'][k])} (p{_fmt(rows[other]['pct'][k])})"
              for k in rows[me]["values"]]
    else:
        L.append(f"(matrix: {'absent' if not m.exists() else 'not both candidates'})")
    if me in rec or other in rec:
        L += [f"metrics.{k} | {_fmt((rec.get(me) or {}).get(k))} | {_fmt((rec.get(other) or {}).get(k))}" for k in RECALL_KEYS]
    od = pk.out / "candidates" / other / "prs.jsonl"
    if od.exists():
        mine_t, oth = Counter(p["tier"] for p in pk.prs), _jsonl(od)
        oth_t = Counter(p["tier"] for p in oth)
        L += [f"pack.{t} PRs | {mine_t.get(t, 0)} | {oth_t.get(t, 0)}" for t in C.TIER_POINTS]
        L.append(f"pack.points | {sum(map(_points, pk.prs)):.1f} | {sum(map(_points, oth)):.1f}")
    return L


def cmd_deepread(pk: Pack, a, runner=None) -> list[str]:
    p = pk.by_num.get(a.n)
    if not p:
        return [f"#{a.n} is not one of {pk.login}'s window PRs"]
    if p["deepread"]:
        return cmd_pr(pk, a) + ["(already deep-read; no on-demand slot used)"]
    if len(pk.ondemand) >= C.ONDEMAND_DEEPREAD_CAP:
        return [f"on-demand cap reached ({C.ONDEMAND_DEEPREAD_CAP} per candidate): " + ", ".join(f"#{n}" for n in pk.ondemand)]
    pr = next((x for x in _jsonl(Path(pk.meta["prs_path"])) if x["number"] == a.n), None)
    if pr is None:
        return [f"#{a.n} not found in {pk.meta['prs_path']}"]
    if runner is None:
        from impact.fine.deepread import deepread as runner
    rd = {r["number"]: r for r in _jsonl(C.REVIEW_DETAIL) if r["number"] == a.n} or None
    r = runner([pr], rd, C.CLONE)[0]
    if r.get("llm_error"):
        return [f"deep read of #{a.n} failed ({r['llm_error']}); no slot used"]
    keep = {k: r.get(k) for k in ("number", "V", "C", "N", "L", "Q", "ell", "P", "verified", "summary", "diff_source", "diff_truncated", "cost")}
    with open(pk.dir / "ondemand.jsonl", "a") as f:
        f.write(json.dumps(keep | {"source": "ondemand"}) + "\n")
    pk = Pack(pk.login, pk.out)
    return cmd_pr(pk, a) + [f"on-demand slots left: {C.ONDEMAND_DEEPREAD_CAP - len(pk.ondemand)} · not part of the stratified estimate"]


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m impact.fine.query")
    ap.add_argument("login")
    ap.add_argument("--max-lines", type=int, default=C.QUERY_MAX_LINES)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("prs")
    for f in ("--ws", "--area", "--tier", "--since", "--until"):
        s.add_argument(f)
    sub.add_parser("pr").add_argument("n", type=int)
    for name in ("reviews-given", "reviews-received"):
        sub.add_parser(name).add_argument("--top", type=int, default=10)
    sub.add_parser("timeline")
    sub.add_parser("rank").add_argument("metric")
    sub.add_parser("compare").add_argument("other")
    sub.add_parser("deepread").add_argument("n", type=int)
    return ap


def run(argv: list[str], out: Path = C.OUT, runner=None) -> str:
    a = parser().parse_args(argv)
    pk = Pack(a.login, out)
    fn = globals()["cmd_" + a.cmd.replace("-", "_")]
    lines = fn(pk, a, runner) if a.cmd == "deepread" else fn(pk, a)
    if len(lines) > a.max_lines:
        lines = lines[:a.max_lines - 1] + [f"... {len(lines) - a.max_lines + 1} more lines (narrow the filters or pass --max-lines)"]
    return "\n".join(lines)


if __name__ == "__main__":
    print(run(sys.argv[1:]))
