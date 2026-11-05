"""Raw day files (GraphQL search dumps) → data/prs.jsonl in the plan's PR contract."""
import json
import re
import sys
from collections import Counter
from pathlib import Path

from impact import config as C

REQUESTER = re.compile(r"(?:requested|triggered|started|asked) by @([A-Za-z0-9-]+)", re.I)


def attribute(author: str, is_bot: bool, body: str) -> tuple[bool, str | None]:
    """(ai_assisted, credited_to). Bot PRs are credited only to an explicitly named human requester."""
    if not is_bot:
        return False, author
    if author == C.AI_AGENT_LOGIN:
        m = REQUESTER.search(body)
        return True, (m.group(1) if m and not C.is_bot(m.group(1)) else None)
    return False, None


def record(n: dict) -> dict:
    a = n.get("author") or {}
    login, is_bot = a.get("login"), C.is_bot(a.get("login"), a.get("__typename"))
    body = n.get("body") or ""
    ai, credited = attribute(login, is_bot, body)
    return {
        "number": n["number"], "url": n["url"], "title": n["title"], "body": body,
        "author": login, "author_is_bot": is_bot, "ai_assisted": ai, "credited_to": credited,
        "created_at": n["createdAt"], "merged_at": n["mergedAt"],
        "in_window": C.WINDOW_START <= n["mergedAt"] <= C.WINDOW_END,
        "additions": n["additions"], "deletions": n["deletions"],
        "files": n["files"]["nodes"], "files_truncated": n.get("filesTruncated", False),
        "labels": [l["name"] for l in n["labels"]["nodes"]],
        "reviews": [{"author": (r.get("author") or {}).get("login"),
                     "is_bot": C.is_bot((r.get("author") or {}).get("login"), (r.get("author") or {}).get("__typename")),
                     "state": r["state"], "submitted_at": r["submittedAt"], "body_len": r.get("bodyLength", 0)}
                    for r in n["reviews"]["nodes"]],
        "reviews_truncated": n.get("reviewsTruncated", False),
        "closing_issues": [{"number": i["number"], "reactions": None} for i in n["closingIssuesReferences"]["nodes"]],
        "commits": n["commits"]["totalCount"],
        # filled by data_extra (Task 1); None = not fetched yet
        "merge_commit": None, "review_threads": None, "review_requests": None,
    }


def normalize(raw_dir: Path, out: Path, since: str = C.BUFFER_START) -> dict:
    stats, seen = Counter(), set()
    with open(out, "w") as f:
        for p in sorted(raw_dir.glob("*.json")):
            day = json.loads(p.read_text())
            if day["meta"]["fetched"] != day["meta"]["issueCount"]:
                stats["incomplete_days"] += 1  # never silently accept a short day
            for n in day["prs"]:
                if n["mergedAt"] < since or n["number"] in seen:
                    continue
                seen.add(n["number"])
                r = record(n)
                stats["prs"] += 1
                stats["in_window"] += r["in_window"]
                stats["bot_prs"] += r["author_is_bot"]
                stats["ai_unattributed"] += r["ai_assisted"] and r["credited_to"] is None
                f.write(json.dumps(r) + "\n")
    return dict(stats)


def load(path: Path = C.PRS) -> list[dict]:
    return [json.loads(l) for l in open(path)]


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else C.PRS
    out.parent.mkdir(exist_ok=True)
    print(normalize(C.RAW_DIR, out))
