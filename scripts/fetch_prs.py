"""Fetch merged PRs of PostHog/posthog, one search window per UTC day (each day << 1000-result search cap).
Usage: python3 scripts/fetch_prs.py START END   (dates inclusive, YYYY-MM-DD; the run used 2026-07-06 2026-11-03).
Writes data/raw/<day>.json + log to data/fetch_log.jsonl; then `python -m impact.normalize` builds data/prs.jsonl.
Needs `gh` logged in. Re-running skips days whose raw file already matches its issueCount."""
import json, subprocess, sys, time, datetime as dt
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE.parent / "data"
RAW = DATA / "raw"  # impact/config.py RAW_DIR reads this directory once it holds day files
LOG = DATA / "fetch_log.jsonl"
QUERY = (HERE / "pr_query.graphql").read_text()
REPO = "PostHog/posthog"

def gql(q, after=None):
    args = ["gh", "api", "graphql", "-f", f"query={QUERY}", "-f", f"q={q}", "-F", "first=50"]
    if after: args += ["-f", f"after={after}"]
    for attempt in range(6):
        r = subprocess.run(args, capture_output=True, text=True)
        if r.returncode == 0:
            d = json.loads(r.stdout)
            if not d.get("errors"): return d["data"]
        # secondary rate limit (server CPU time) needs minutes, not seconds
        time.sleep(90 if "secondary rate limit" in r.stdout + r.stderr else 5 * (attempt + 1))
    raise RuntimeError(f"{q} after={after}: {r.stderr[:300]} {r.stdout[:300]}")

def slim(n):
    n["body"] = (n.get("body") or "")[:2000]
    for rv in n["reviews"]["nodes"]:
        rv["bodyLength"] = len(rv.pop("body") or "")
    n["filesTruncated"] = n["files"]["totalCount"] > len(n["files"]["nodes"])
    n["reviewsTruncated"] = n["reviews"]["totalCount"] > len(n["reviews"]["nodes"])
    return n

def fetch_day(day):
    out = RAW / f"{day}.json"
    q = f"repo:{REPO} is:pr is:merged merged:{day}"
    for attempt in range(3):
        prs, after, cost, t0 = {}, None, 0, time.time()
        while True:
            d = gql(q, after)
            s, cost = d["search"], cost + d["rateLimit"]["cost"]
            for n in s["nodes"]:
                prs[n["number"]] = slim(n)
            if not s["pageInfo"]["hasNextPage"]: break
            after = s["pageInfo"]["endCursor"]
        # search pagination can drift; accept only an exact match with issueCount
        if len(prs) == s["issueCount"]: break
    rec = {"day": day, "issueCount": s["issueCount"], "fetched": len(prs), "cost": cost,
           "seconds": round(time.time() - t0, 1), "attempts": attempt + 1,
           "remaining": d["rateLimit"]["remaining"], "fetchedAt": dt.datetime.utcnow().isoformat() + "Z"}
    RAW.mkdir(parents=True, exist_ok=True)  # not at import: an empty data/raw must not exist before a real fetch
    out.write_text(json.dumps({"meta": rec, "prs": list(prs.values())}))
    with open(LOG, "a") as f: f.write(json.dumps(rec) + "\n")
    print(rec, flush=True)
    return rec

def done(day):
    p = RAW / f"{day}.json"
    if not p.exists(): return False
    m = json.loads(p.read_text())["meta"]
    return m["fetched"] == m["issueCount"] and day != dt.datetime.utcnow().date().isoformat()

if __name__ == "__main__":
    a, b = (dt.date.fromisoformat(x) for x in sys.argv[1:3])
    days = [str(a + dt.timedelta(i)) for i in range((b - a).days + 1)]
    todo = [d for d in days if not done(d)]
    recs = [fetch_day(d) for d in todo]  # sequential: 4 parallel workers tripped the secondary (server CPU-time) limit
    bad = [r for r in recs if r["fetched"] != r["issueCount"]]
    print("days", len(todo), "cost", sum(r["cost"] for r in recs), "MISMATCH", bad)
