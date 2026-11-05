"""Flash deep read of sampled PRs: V/C/N/L/Q with verbatim-quote checks (spec §9.1, review-codex R8)."""
import asyncio
import json
import re
import subprocess
from functools import lru_cache
from pathlib import Path

from impact import config as C, paths
from impact.contracts import validate
from impact.llm import cache_path, run_all

SYSTEM = (Path(__file__).parent / "prompts/deepread.md").read_text()
MAX = {"V": 3, "C": 3, "N": 2, "L": 3, "Q": 2}
SUBJECT_PR = re.compile(r"\(#(\d+)\)\s*$")
FILE_HEADER = re.compile(r"^diff --git a/.* b/(.*)$", re.M)


LINE_PREFIX = re.compile(r"(?m)^[+\- ]?\s*(?:#+|//+|/?\*+|--|>)?")  # diff marker + comment marker at line start


def _norm(s: str) -> str:
    """Ignore case, whitespace, and the diff/comment markers a quote loses when it joins wrapped lines."""
    return re.sub(r"\s+", "", LINE_PREFIX.sub("", s)).replace("**", "").lower()


def score(raw: dict, source: str) -> dict:
    """LLM answer → contract fields. A quote that is not a substring of the source costs that sub-score 1 (floor 0)."""
    src, ev = _norm(source), raw.get("evidence") or {}
    rec = {"raw": {}, "evidence": {}, "verified": {}}
    for k, hi in MAX.items():
        v = min(hi, max(0, int(raw[k])))
        q = ev.get(k) or ""
        ok = bool(_norm(q)) and _norm(q) in src
        rec["raw"][k], rec[k], rec["evidence"][k], rec["verified"][k] = v, v if ok else max(0, v - 1), q, ok
    rec["ell"] = C.pr_level(rec["V"], rec["C"], rec["N"])
    rec["P"] = C.pr_points(rec["ell"])
    return rec


def fit_diff(diff: str, limit: int = C.DIFF_MAX_CHARS) -> tuple[str, dict]:
    """Keep whole diff if it fits; else fill the budget with file hunks in descending paths.weight order."""
    if len(diff) <= limit:
        return diff, {"diff_truncated": False}
    chunks = [c for c in re.split(r"(?m)^(?=diff --git )", diff) if c]
    weight = [paths.weight(m.group(1)) if (m := FILE_HEADER.match(c)) else 0 for c in chunks]
    keep, room = {}, limit
    for i in sorted(range(len(chunks)), key=lambda i: -weight[i]):
        if room <= 0:
            break
        c = chunks[i][:room]
        keep[i] = c if len(c) == len(chunks[i]) else c[:c.rfind("\n") + 1]  # cut on a line boundary
        room -= len(c)
    return "".join(keep[i] for i in sorted(keep)), {
        "diff_truncated": True, "diff_chars": len(diff), "diff_files": len(chunks),
        "diff_files_whole": sum(len(keep[i]) == len(chunks[i]) for i in keep)}


@lru_cache
def _subject_index(clone: str) -> dict[int, str]:
    log = subprocess.run(["git", "-C", clone, "log", "--format=%H %s"], capture_output=True, text=True, check=True).stdout
    idx = {}
    for line in log.splitlines():
        sha, _, subject = line.partition(" ")
        if m := SUBJECT_PR.search(subject):
            idx.setdefault(int(m.group(1)), sha)
    return idx


def _show(clone: Path, sha: str) -> str | None:
    r = subprocess.run(["git", "-C", str(clone), "show", "--format=", "--no-color", "--diff-merges=first-parent", sha],
                       capture_output=True, text=True, errors="replace")
    return r.stdout if r.returncode == 0 and r.stdout.strip() else None


def _diff(pr: dict, clone: Path | None, commit_authors: dict) -> tuple[str | None, str]:
    if not clone or not Path(clone, ".git").exists():
        return None, "missing"
    candidates = [(pr.get("merge_commit"), "pr"),
                  ((commit_authors.get(str(pr["number"])) or {}).get("merge_commit"), "commit_authors")]
    for sha, how in candidates:
        if sha and (d := _show(clone, sha)):
            return d, how
    if (sha := _subject_index(str(clone)).get(pr["number"])) and (d := _show(clone, sha)):
        return d, "subject"
    return None, "missing"


def review_text(rd: dict) -> str:
    parts = [f"[review {r.get('state')} by {r.get('author')}] {r['body']}" for r in rd.get("reviews") or [] if (r.get("body") or "").strip()]
    parts += [f"[comment by {c.get('author')} on {t.get('path')}] {c['body']}"
              for t in rd.get("threads") or [] for c in t.get("comments") or [] if (c.get("body") or "").strip()]
    return "\n".join(parts)


def build_input(pr: dict, review_detail: dict | None, clone: Path | None, commit_authors: dict) -> tuple[str, dict]:
    body = pr.get("body") or ""
    diff, how = _diff(pr, clone, commit_authors)
    meta = {"diff_source": how, "diff_missing": diff is None, "diff_truncated": False,
            "body_truncated": len(body) > C.BODY_MAX_CHARS}
    if diff:
        text, info = fit_diff(diff)
        meta |= info
        changes = f"## Diff\n{text}"
    else:
        files = "\n".join(f"{f['path']} +{f['additions']} -{f['deletions']}" for f in pr.get("files") or [])
        changes = f"## Files (diff unavailable{', list truncated' if pr.get('files_truncated') else ''})\n{files}"
    rd = (review_detail or {}).get(pr["number"])
    rev = review_text(rd) if rd else ""
    meta["review_source"] = "review_detail" if rd else "missing"
    meta["review_truncated"] = len(rev) > C.DEEPREAD_REVIEW_MAX_CHARS
    prompt = (f"# PR #{pr['number']}: {pr['title']}\n+{pr.get('additions')} -{pr.get('deletions')}, labels: {pr.get('labels')}\n\n"
              f"## Body\n{body[:C.BODY_MAX_CHARS]}\n\n{changes}\n\n"
              f"## Review discussion\n{rev[:C.DEEPREAD_REVIEW_MAX_CHARS] or '(not available)'}")
    return prompt, meta


def deepread(prs: list[dict], review_detail: dict | None, clone: Path | None = C.CLONE,
             commit_authors: dict | None = None) -> list[dict]:
    """review_detail = {number: R1 record}; commit_authors defaults to data/commit_authors.json when present."""
    if commit_authors is None:
        p = C.DATA / "commit_authors.json"
        commit_authors = json.loads(p.read_text()) if p.exists() else {}
    inputs = [build_input(pr, review_detail, clone, commit_authors) for pr in prs]
    cached = [cache_path("deepread", str(pr["number"]), SYSTEM + p).exists() for pr, (p, _) in zip(prs, inputs)]
    answers = asyncio.run(run_all("deepread", [(str(pr["number"]), SYSTEM, p) for pr, (p, _) in zip(prs, inputs)]))
    out = []
    for pr, (prompt, meta), a, hit in zip(prs, inputs, answers, cached):
        # cost = spend of this call (0 on a cache hit); cost_original = what the cached answer cost when first made
        rec = {"number": pr["number"], **meta, "summary": a.get("summary"), "cached": hit,
               "cost": 0.0 if hit else a.get("_usage"), "cost_original": a.get("_usage")}
        try:
            rec |= score(a, prompt) | {"llm_error": None}
        except (KeyError, TypeError, ValueError) as e:  # LLM failed or wrong shape → excluded from averages
            rec |= {k: 0 for k in MAX} | {"evidence": {}, "verified": {}, "ell": 0.0, "P": 0.0,
                                         "llm_error": a.get("llm_error") or f"bad shape: {e!r}"[:200]}
        out.append(validate("deepread", rec))
    return out
