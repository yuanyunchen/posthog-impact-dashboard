"""Validation facts for the dashboard: fetch reconciliation, quote checks, audit verdict, LLM cost."""
import json
import sys
from pathlib import Path

from impact import config as C


def build(out: Path) -> dict:
    days = [json.loads(p.read_text())["meta"] for p in sorted(C.RAW_DIR.glob("*.json"))]
    win = [d for d in days if C.WINDOW_START[:10] <= d["day"] <= C.WINDOW_END[:10]]
    dr = [json.loads(l) for l in open(out / "deepread.jsonl")] if (out / "deepread.jsonl").exists() else []
    checks = [v for r in dr if not r.get("llm_error") for v in (r.get("verified") or {}).values()]
    cost = 0.0
    for p in (C.DATA / "llm_cache").rglob("*.json"):
        try:
            cost += json.loads(p.read_text()).get("_usage") or 0
        except (json.JSONDecodeError, AttributeError):
            pass
    coarse = json.loads((out / "coarse.json").read_text())
    audited = {r["login"] for r in json.loads((out / "recall.json").read_text()) if r.get("recalled_by") == ["audit"]}
    audit = [c["login"] for c in coarse if c["login"] in audited]  # entered via the miss audit, then won a shortlist seat
    return {
        "fetch": {"days": len(win), "days_reconciled": sum(d["fetched"] == d["issueCount"] for d in win),
                  "prs": sum(d["fetched"] for d in win), "search_count": sum(d["issueCount"] for d in win)},
        "quote_check": {"checked": len(checks), "failed": checks.count(False),
                        "fail_rate": round(checks.count(False) / max(1, len(checks)), 4),
                        "deepread_prs": len(dr), "deepread_errors": sum(bool(r.get("llm_error")) for r in dr)},
        "audit": {"sample": C.AUDIT_SAMPLE, "selected_into_top20": audit},
        "llm_cost_usd": round(cost, 2),  # all DeepSeek calls ever cached (incl. dev runs); Claude agents not billed per call
    }


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else C.OUT
    v = build(out)
    (out / "validation.json").write_text(json.dumps(v, indent=1))
    print(json.dumps(v))
