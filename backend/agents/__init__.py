"""
Agent registry — microservice pattern.
To add a new agent:
  1. Drop a .py file in agents/ that exposes:
       async def run(query, location, max_jobs, search_id, user_id) -> dict
       NAME = "my_agent"          # used as the registry key
       LABEL = "My Site"          # shown in UI
  2. Add it to AGENTS dict below.

The agent is run as an isolated asyncio subprocess so crashes never
affect the API server or other agents.
"""

import asyncio, json, importlib, sys
from pathlib import Path

# ── built-in agent shim ───────────────────────────────────────────────────────
# We call agent_up.py via subprocess to keep it fully isolated.
# Each agent module can do the same or run in-process — your choice.

AGENTS: dict[str, dict] = {
    "bdjobs": {
        "label": "BDJobs",
        "script": None,
        "module": "agents.bdjobs_scraper",  # Vision-based scraper
    },
    "skilljobs": {
        "label": "Skill.jobs",
        "script": None,
        "module": "agents.skilljobs_agent",
    },
    "jobmedia": {
        "label": "Job Media",
        "script": None,
        "module": "agents.jobmedia_agent",
    },
    "nextjobz": {
        "label": "NextJobz",
        "script": None,
        "module": "agents.nextjobz_agent",
    },
    "niyog": {
        "label": "Niyog",
        "script": None,
        "module": "agents.niyog_agent",
    },
    "atb": {
        "label": "ATB Jobs",
        "script": None,
        "module": "agents.atbjobs_agent",
    },
}


def available_agents() -> list[dict]:
    return [{"key": k, "label": v["label"]} for k, v in AGENTS.items()]


async def run_agent(
    agent_key: str,
    query: str,
    location: str,
    max_jobs: int,
    search_id: int,
    user_id: int,
) -> dict:
    cfg = AGENTS.get(agent_key)
    if not cfg:
        return {"status": "failed", "total": 0, "jobs": []}

    # ── subprocess path (isolates heavy browser process) ─────────────────────
    if cfg.get("script"):
        return await _run_subprocess(
            cfg["script"], query, location, max_jobs, search_id, user_id
        )

    # ── in-process module path ────────────────────────────────────────────────
    mod = importlib.import_module(cfg["module"])
    return await mod.run(
        query=query,
        location=location,
        max_jobs=max_jobs,
        search_id=search_id,
        user_id=user_id,
    )


async def _run_subprocess(
    script: Path, query, location, max_jobs, search_id, user_id
) -> dict:
    args = [
        sys.executable,
        str(script),
        "--query",
        query,
        "--location",
        location or "",
        "--max-jobs",
        str(max_jobs),
        "--search-id",
        str(search_id),
        "--user-id",
        str(user_id),
    ]
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
    try:
        return json.loads(stdout.decode())
    except Exception:
        return {
            "status": "failed",
            "total": 0,
            "jobs": [],
            "error": stderr.decode()[:500],
        }
