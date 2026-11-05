"""OpenRouter JSON client with on-disk cache: reruns are free and every answer is auditable."""
import asyncio
import hashlib
import json
import os
from pathlib import Path

import httpx

from impact import config as C

URL = "https://openrouter.ai/api/v1/chat/completions"
CACHE = C.DATA / "llm_cache"


def _key() -> str:
    if k := os.environ.get("OPENROUTER_API_KEY"):
        return k
    for line in (C.ROOT / ".agents/secrets.env").read_text().splitlines():
        if line.startswith("OPENROUTER_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("OPENROUTER_API_KEY not set")


def cache_path(stage: str, key: str, prompt: str) -> Path:
    h = hashlib.sha256((C.MODEL + prompt).encode()).hexdigest()[:12]  # model in key: switching models never reuses stale answers
    return CACHE / stage / f"{key}-{h}.json"


async def complete_json(client: httpx.AsyncClient, sem: asyncio.Semaphore, stage: str, key: str,
                        system: str, prompt: str, retries: int = 3) -> dict:
    """Returns parsed JSON, or {"llm_error": msg} after retries. Cached per (stage, key, prompt)."""
    path = cache_path(stage, key, system + prompt)
    if path.exists():
        return json.loads(path.read_text())
    err = ""
    for attempt in range(retries):
        try:
            async with sem:
                r = await asyncio.wait_for(client.post(URL, headers={"Authorization": f"Bearer {_key()}"}, timeout=120, json={
                    "model": C.MODEL, "temperature": 0,
                    "response_format": {"type": "json_object"}, "reasoning": {"effort": "low"},
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                }), timeout=180)  # hard cap: a stalled stream once hung 13 min despite the read timeout
            r.raise_for_status()
            d = r.json()
            out = json.loads(d["choices"][0]["message"]["content"])
            out["_usage"] = d.get("usage", {}).get("cost")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(out))
            return out
        except Exception as e:  # network, HTTP, or malformed JSON → retry
            err = f"{type(e).__name__}: {e}"[:300]
            await asyncio.sleep(2 * (attempt + 1))
    return {"llm_error": err}


async def run_all(stage: str, jobs: list[tuple[str, str, str]]) -> list[dict]:
    """jobs = [(key, system, prompt)] → results in the same order."""
    sem = asyncio.Semaphore(C.LLM_CONCURRENCY)
    async with httpx.AsyncClient() as client:
        return await asyncio.gather(*(complete_json(client, sem, stage, k, s, p) for k, s, p in jobs))
