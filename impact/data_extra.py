"""Task 1 data completion: review detail + issue reactions (GraphQL), line lineage (git), org maps.

CLI: python -m impact.data_extra {lineage|org|reviews <numbers_file>|reactions <numbers_file>}
"""
import csv
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from impact import config as C

OWNER, NAME = C.REPO.split("/")
RATE_LIMITED = re.compile(r"secondary rate limit|rate limit exceeded|abuse", re.I)
PR_SUBJECT = re.compile(r"\(#(\d+)\)\s*$|^Merge pull request #(\d+)")
CO_AUTHOR = re.compile(r"^co-authored-by:\s*(.*?)\s*<([^>]*)>", re.I | re.M)
GENERATED = re.compile(r"^(?:generated-by:\s*(.+?)\s*$|🤖 Generated with \[([^\]]+)\])", re.I | re.M)

stats = Counter()  # GraphQL calls / cost points / waits across this process


# ---------- GraphQL ----------

def gh_graphql(query: str) -> dict:
    """One gh call; waits out rate limits. Returns the full response ({data, errors})."""
    while True:
        p = subprocess.run(["gh", "api", "graphql", "-f", f"query={query}"], capture_output=True, text=True)
        stats["calls"] += 1
        if p.returncode == 0 or p.stdout.strip().startswith("{"):
            resp = json.loads(p.stdout)
            if not RATE_LIMITED.search(json.dumps(resp.get("errors") or "")):
                stats["cost"] += ((resp.get("data") or {}).get("rateLimit") or {}).get("cost", 0)
                return resp
        elif not RATE_LIMITED.search(p.stderr):
            raise RuntimeError(p.stderr.strip()[:500])
        stats["rate_waits"] += 1
        time.sleep(C.GQL_RATE_WAIT_S)


def batch_query(kind: str, numbers: list[int], fields: str) -> str:
    aliases = "\n".join(f"n{n}: {kind}(number: {n}) {{ {fields} }}" for n in numbers)
    return f'query {{ rateLimit {{ cost remaining }} repository(owner: "{OWNER}", name: "{NAME}") {{\n{aliases}\n}} }}'


def fetch_batches(kind: str, numbers: list[int], fields: str) -> tuple[dict[int, dict], list[int]]:
    """{number: node} for every number GitHub returned, plus the missing ones. Failed batches are halved and retried."""
    got, missing = {}, []
    todo = [numbers[i:i + C.GQL_BATCH] for i in range(0, len(numbers), C.GQL_BATCH)]
    while todo:
        chunk = todo.pop(0)
        try:
            repo = (gh_graphql(batch_query(kind, chunk, fields)).get("data") or {}).get("repository") or {}
        except RuntimeError:  # e.g. 502 on a heavy batch
            if len(chunk) > 1:
                todo[:0] = [chunk[:len(chunk) // 2], chunk[len(chunk) // 2:]]
            else:
                missing += chunk
            continue
        for n in chunk:
            if repo.get(f"n{n}"):
                got[n] = repo[f"n{n}"]
            else:
                missing.append(n)
    return got, missing


def login(actor: dict | None) -> str | None:
    return (actor or {}).get("login") or (actor or {}).get("slug")


def is_bot(actor: dict | None) -> bool:
    return C.is_bot(login(actor), (actor or {}).get("__typename"))


REVIEW_FIELDS = f"""number
reviews(first: {C.GQL_REVIEWS}) {{ totalCount nodes {{ author {{ __typename login }} state submittedAt body }} }}
reviewThreads(first: {C.GQL_THREADS}) {{ totalCount nodes {{ path line originalLine isOutdated
  comments(first: {C.GQL_THREAD_COMMENTS}) {{ totalCount nodes {{ author {{ __typename login }} body createdAt originalCommit {{ oid }} }} }} }} }}
timelineItems(first: {C.GQL_REQUESTS}, itemTypes: [REVIEW_REQUESTED_EVENT]) {{ filteredCount nodes {{ ... on ReviewRequestedEvent {{
  createdAt actor {{ login }} requestedReviewer {{ __typename ... on User {{ login }} ... on Bot {{ login }} ... on Team {{ slug }} ... on Mannequin {{ login }} }} }} }} }}"""


def review_record(pr: dict) -> dict:
    rv, th, tl = pr["reviews"], pr["reviewThreads"], pr["timelineItems"]
    threads = []
    for t in th["nodes"]:
        cs = t["comments"]["nodes"]
        threads.append({
            "path": t["path"], "line": t["line"], "original_line": t["originalLine"],
            "original_commit": ((cs[0] if cs else {}).get("originalCommit") or {}).get("oid"),
            "is_outdated": t["isOutdated"],
            "comments": [{"author": login(c["author"]), "is_bot": is_bot(c["author"]), "body": c["body"], "created_at": c["createdAt"]} for c in cs],
            "comments_truncated": t["comments"]["totalCount"] > len(cs),
        })
    return {
        "number": pr["number"],
        "reviews": [{"author": login(r["author"]), "is_bot": is_bot(r["author"]), "state": r["state"], "submitted_at": r["submittedAt"], "body": r["body"]}
                    for r in rv["nodes"]],
        "threads": threads,
        "review_requests": [{"requester": login(e.get("actor")), "reviewer": login(e.get("requestedReviewer")),
                             "reviewer_is_bot": is_bot(e.get("requestedReviewer")) if e.get("requestedReviewer") else None,
                             "created_at": e.get("createdAt")} for e in tl["nodes"]],
        "truncated": {"reviews": rv["totalCount"] > len(rv["nodes"]), "threads": th["totalCount"] > len(th["nodes"]),
                      "review_requests": tl["filteredCount"] > len(tl["nodes"])},
    }


def fetch_review_detail(numbers: list[int], out: Path = C.REVIEW_DETAIL) -> dict:
    """Append review detail for numbers not yet in `out` (resumable). Returns {fetched, skipped, missing, truncated, calls, cost}."""
    done = {json.loads(l)["number"] for l in open(out)} if out.exists() else set()
    todo = [n for n in dict.fromkeys(numbers) if n not in done]
    got, missing = fetch_batches("pullRequest", todo, REVIEW_FIELDS)
    trunc = Counter()
    with open(out, "a") as f:
        for n in todo:
            if n in got:
                r = review_record(got[n])
                trunc.update(k for k, v in r["truncated"].items() if v)
                trunc.update("thread_comments" for t in r["threads"] if t["comments_truncated"])
                f.write(json.dumps(r) + "\n")
    return {"fetched": len(got), "skipped": len(numbers) - len(todo), "missing": missing,
            "truncated": dict(trunc), "calls": stats["calls"], "cost": stats["cost"]}


def fetch_issue_reactions(issue_numbers: list[int]) -> dict[int, int]:
    """Total reactions per issue; numbers GitHub does not return as an issue are absent from the result."""
    got, _ = fetch_batches("issue", list(dict.fromkeys(issue_numbers)), "number reactions { totalCount }")
    return {n: node["reactions"]["totalCount"] for n, node in got.items()}


# ---------- git lineage ----------

def pr_number(subject: str) -> int | None:
    """Squash subject ends with (#N); the last one wins (reverts quote the original PR earlier in the subject)."""
    m = PR_SUBJECT.search(subject)
    return int(m.group(1) or m.group(2)) if m else None


def trailers(body: str) -> dict:
    gen = GENERATED.search(body)
    return {"co_authors": [{"name": n, "email": e} for n, e in CO_AUTHOR.findall(body)],
            "generated_by": (gen.group(1) or gen.group(2)) if gen else None}


def rename_paths(spec: str) -> tuple[str | None, str]:
    """numstat path → (old, new). Handles `a => b` and `dir/{a => b}/f`; old is None when not a rename."""
    if " => " not in spec:
        return None, spec
    m = re.match(r"(.*)\{(.*) => (.*)\}(.*)", spec)
    if m:
        pre, a, b, post = m.groups()
        return re.sub("//+", "/", pre + a + post), re.sub("//+", "/", pre + b + post)
    a, b = spec.split(" => ")
    return a, b


LOG_FORMAT = "%x1e%H%x1f%ae%x1f%cd%x1f%s%x1f%B%x1f"  # %cd in UTC via --date below


def parse_log(text: str, skip: set[str] = frozenset()) -> tuple[dict, dict, Counter, list]:
    """git log (newest first) → (lineage, commit_authors, counts, unmapped commits).
    Older history of a renamed file is keyed by its newest name."""
    lineage, authors, counts, unmapped = defaultdict(list), {}, Counter(), []
    alias = {}  # old path → newest name, learned walking back in time
    for chunk in text.split("\x1e")[1:]:
        sha, email, date, subject, body, numstat = chunk.split("\x1f")
        counts["commits"] += 1
        if sha in skip:  # shallow boundary: diffed against nothing, would list the whole tree as added
            counts["shallow_boundary"] += 1
            continue
        n = pr_number(subject)
        if n is None:
            unmapped.append(f"{sha[:10]} {subject}")
        elif str(n) in authors:  # newest commit for a PR number wins
            counts["duplicate_pr_commits"] += 1
        else:
            authors[str(n)] = {"merge_commit": sha, **trailers(body)}
        for line in numstat.strip("\n").splitlines():
            added, deleted, spec = line.split("\t", 2)
            old, new = rename_paths(spec)
            key = alias.get(new, new)
            if old:
                alias[old] = key
                counts["renames"] += 1
            lineage[key].append({"number": n, "sha": sha, "author_email": email, "merged_at": date,
                                 "added": int(added) if added != "-" else 0, "deleted": int(deleted) if deleted != "-" else 0})
    return dict(lineage), authors, counts, unmapped


def build_lineage(clone: Path = C.CLONE, out: Path = C.LINEAGE, authors_out: Path = C.COMMIT_AUTHORS) -> dict:
    log = subprocess.run(["git", "-C", str(clone), "log", "--numstat", "--find-renames", f"--format={LOG_FORMAT}",
                          "--date=format-local:%Y-%m-%dT%H:%M:%SZ", "HEAD"],
                         capture_output=True, text=True, check=True, env={**os.environ, "TZ": "UTC"}).stdout
    shallow = clone / ".git/shallow"
    lineage, authors, counts, unmapped = parse_log(log, set(shallow.read_text().split()) if shallow.exists() else set())
    out.write_text(json.dumps(lineage))
    authors_out.write_text(json.dumps(authors))
    return {**counts, "paths": len(lineage), "prs": len(authors), "unmapped": len(unmapped), "unmapped_commits": unmapped,
            "with_co_authors": sum(bool(a["co_authors"]) for a in authors.values()),
            "with_generated_by": sum(bool(a["generated_by"]) for a in authors.values())}


# ---------- org ----------

def observed_logins(prs: Path) -> dict[str, str]:
    """lowercase → GitHub casing, from PR authors and reviewers."""
    seen = {}
    for l in open(prs):
        p = json.loads(l)
        for x in [p["author"], *(r["author"] for r in p["reviews"])]:
            if x:
                seen.setdefault(x.lower(), x)
    return seen


def build_org(out_dir: Path = C.DATA, org: Path = C.ORG_DIR, prs: Path | None = None) -> dict:
    """team_map.json {login: [team]} and changelog.json {pr_number: [{title, date}]} from the org-culture outputs."""
    prs = prs or (C.PRS if C.PRS.exists() else C.FIXTURE)
    seen = observed_logins(prs)
    team_map, no_handle, unseen = defaultdict(list), 0, set()
    # teams-full.md lists the same profiles' handles as members.csv (a strict subset), so members.csv alone is read.
    for r in csv.DictReader(open(org / "members.csv")):
        h = r["handle"].strip()
        if not re.fullmatch(r"[A-Za-z0-9-]+", h):  # empty, or a non-GitHub URL pasted into the profile
            no_handle += 1
            continue
        if h.lower() not in seen:
            unseen.add(h)
        login_ = seen.get(h.lower(), h)
        if r["team"] not in team_map[login_]:
            team_map[login_].append(r["team"])
    changelog, rows, rows_no_pr = defaultdict(list), 0, 0
    for r in csv.DictReader(open(org / "changelog-since-2026-07-01.tsv"), delimiter="\t"):
        rows += 1
        nums = re.findall(r"github\.com/PostHog/posthog/pull/(\d+)", r["githubUrls"], re.I)
        rows_no_pr += not nums
        for n in dict.fromkeys(nums):
            changelog[n].append({"title": r["title"], "date": r["dateCompleted"]})
    (out_dir / "team_map.json").write_text(json.dumps(team_map, indent=1))
    (out_dir / "changelog.json").write_text(json.dumps(changelog, indent=1))
    return {"logins": len(team_map), "members_without_handle": no_handle, "handles_not_in_pr_data": sorted(unseen),
            "multi_team": sum(len(v) > 1 for v in team_map.values()), "changelog_rows": rows,
            "changelog_rows_without_posthog_pr": rows_no_pr, "changelog_prs": len(changelog),
            "prs_in_multiple_entries": sum(len(v) > 1 for v in changelog.values())}


def read_numbers(path: str) -> list[int]:
    return [int(x) for x in re.findall(r"\d+", Path(path).read_text())]


if __name__ == "__main__":
    cmd, t0 = sys.argv[1], time.time()
    if cmd == "lineage":
        res = build_lineage()
    elif cmd == "org":
        res = build_org()
    elif cmd == "reviews":
        res = fetch_review_detail(read_numbers(sys.argv[2]))
    elif cmd == "reactions":
        res = {"reactions": fetch_issue_reactions(read_numbers(sys.argv[2])), "calls": stats["calls"], "cost": stats["cost"]}
    else:
        sys.exit(__doc__)
    print(json.dumps({**res, "seconds": round(time.time() - t0, 1)}))
