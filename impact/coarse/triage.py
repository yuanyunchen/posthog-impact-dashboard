"""Flash triage: one impact tier per PR (spec §9.1); rule guardrails run after the LLM (review-codex R6)."""
import asyncio
import re
from collections import Counter
from pathlib import Path

from impact import config as C, llm, paths
from impact.contracts import TIERS, validate

SYSTEM = (Path(__file__).parent / "prompts/triage.md").read_text()
DEP_BUMP = re.compile(r"\b(bump|update|upgrade)s?\b.*\bto v?\d", re.I)
MANIFEST = re.compile(r"(^|/)(package\.json|pyproject\.toml|Cargo\.toml|go\.mod|requirements[^/]*\.txt)$")


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def prompt(pr: dict) -> tuple[str, bool]:
    """User message for one PR, and whether the path list was truncated."""
    files, body = pr["files"], pr["body"] or ""
    truncated = len(files) > C.TRIAGE_MAX_PATHS or pr.get("files_truncated", False)
    total = f"{len(files)}+ (GitHub file list truncated)" if pr.get("files_truncated") else str(len(files))
    areas = Counter()
    for f in files:
        noise = paths.noise(f["path"])[0]
        a, tier, _ = paths.area(f["path"])
        areas[f"{a} [{tier}]" if noise == "source" else f"({noise})"] += f["additions"] + f["deletions"]
    shown = files[:C.TRIAGE_MAX_PATHS]
    return "\n".join([
        f"Title: {pr['title']}",
        f"Labels: {', '.join(pr['labels']) or '-'}",
        f"Size: +{pr['additions']} -{pr['deletions']} in {total} files",
        "Changed lines by area: " + ("; ".join(f"{k} {v}" for k, v in areas.most_common()) or "-"),
        f"Files (first {len(shown)} of {total}):" if truncated else "Files:",
        *(f"  {f['path']} +{f['additions']} -{f['deletions']}" for f in shown),
        "Body:",
        body[:C.BODY_MAX_CHARS] + (f"\n[body truncated at {C.BODY_MAX_CHARS} of {len(body)} chars]" if len(body) > C.BODY_MAX_CHARS else ""),
    ]), truncated


def guardrail(pr: dict, tier: str, quote: str) -> tuple[str, str | None]:
    """Only truly mechanical changes are forced to 0; migrations/CI/tests/reverts keep the LLM tier (R6)."""
    files = pr["files"]
    cls = [paths.noise(f["path"])[0] for f in files]
    complete = files and not pr.get("files_truncated")
    if complete and all(c in paths.FORCED_MECHANICAL for c in cls):
        return "mechanical", "forced_mechanical:generated_or_lockfile"
    if complete and DEP_BUMP.search(pr["title"]) and all(
            c in paths.FORCED_MECHANICAL or MANIFEST.search(f["path"]) for c, f in zip(cls, files)):
        return "mechanical", "forced_mechanical:dependency_bump"
    real = sum(f["additions"] + f["deletions"] for c, f in zip(cls, files) if c not in paths.FORCED_MECHANICAL)
    quoted = quote and _norm(quote) in _norm(pr["title"] + "\n" + (pr["body"] or ""))
    if real < 10 and tier in ("major", "landmark") and not quoted:
        return "substantive", "downgraded:small_change_without_quote"
    return tier, None


def _record(pr: dict, out: dict, truncated: bool) -> dict:
    base = {"number": pr["number"], "author": pr.get("credited_to"), "paths_truncated": truncated,
            "n_files": len(pr["files"]), "cost": out.get("_usage")}
    tier = out.get("tier")
    if "llm_error" in out or tier not in TIERS:
        return {**base, "tier": None, "llm_error": out.get("llm_error") or f"invalid tier {tier!r}"}
    quote = str(out.get("quote") or "")
    final, rule = guardrail(pr, tier, quote)
    return validate("triage", {
        **base, "tier": final, "llm_tier": tier, "guardrail": rule,
        "work_type": str(out.get("work_type") or "unknown"), "user_facing": bool(out.get("user_facing")),
        "critical": bool(out.get("critical")), "novel": bool(out.get("novel")),
        "summary": str(out.get("summary") or ""), "quote": quote, "llm_error": None})


def triage(prs: list[dict], stage: str = "triage") -> list[dict]:
    """One record per PR, same order. Failures get one rerun under a fresh cache stage, then stay llm_error."""
    built = [prompt(p) for p in prs]
    jobs = [(str(p["number"]), SYSTEM, text) for p, (text, _) in zip(prs, built)]
    outs = asyncio.run(llm.run_all(stage, jobs))
    recs = [_record(p, o, t) for p, o, (_, t) in zip(prs, outs, built)]
    bad = [i for i, r in enumerate(recs) if r["llm_error"]]
    if bad:  # fresh stage also re-asks answers that were cached but invalid
        outs = asyncio.run(llm.run_all(f"{stage}-retry", [jobs[i] for i in bad]))
        for i, o in zip(bad, outs):
            recs[i] = _record(prs[i], o, built[i][1])
    return recs
