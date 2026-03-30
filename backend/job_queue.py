"""
Lightweight in-process job queue.
- MAX_CONCURRENT agents run at once (default 3).
- Extra searches wait in an asyncio.Queue.
- No Redis, no Celery — just asyncio primitives.
"""

import asyncio
from database import get_db
from agents import run_agent

MAX_CONCURRENT = int(__import__("os").getenv("MAX_CONCURRENT", 3))

_semaphore: asyncio.Semaphore | None = None
_queue: asyncio.Queue | None = None

def get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    return _semaphore

def get_queue() -> asyncio.Queue:
    global _queue
    if _queue is None:
        _queue = asyncio.Queue()
    return _queue

async def enqueue(search_id: int, user_id: int, agent: str,
                  query: str, location: str, max_jobs: int):
    """Queue a search and return immediately."""
    await get_queue().put((search_id, user_id, agent, query, location, max_jobs))

async def _worker():
    """Long-running worker that processes the queue."""
    q = get_queue()
    sem = get_semaphore()
    while True:
        item = await q.get()
        search_id, user_id, agent, query, location, max_jobs = item
        asyncio.create_task(_run(sem, search_id, user_id, agent, query, location, max_jobs))
        q.task_done()

async def _run(sem, search_id, user_id, agent, query, location, max_jobs):
    async with sem:
        _set_status(search_id, "running")
        try:
            result = await run_agent(agent, query, location, max_jobs, search_id, user_id)
            _save_results(search_id, user_id, result)
        except Exception as e:
            _set_status(search_id, "failed")
            print(f"[queue] search {search_id} failed: {e}")

def _set_status(search_id: int, status: str):
    with get_db() as db:
        db.execute("UPDATE searches SET status=? WHERE id=?", (status, search_id))

def _save_results(search_id: int, user_id: int, result: dict):
    jobs  = result.get("jobs", [])
    total = len(jobs)
    status = result.get("status", "success")
    if total == 0 and status != "failed":
        status = "partial"

    with get_db() as db:
        db.execute(
            "UPDATE searches SET status=?, total_found=?, finished_at=datetime('now') WHERE id=?",
            (status, total, search_id)
        )
        if jobs:
            db.executemany(
                """INSERT INTO jobs (search_id,user_id,title,company,location,
                   deadline,job_type,salary,experience,url)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                [(search_id, user_id,
                  j.get("title",""), j.get("company",""), j.get("location",""),
                  j.get("deadline",""), j.get("job_type",""),
                  j.get("salary",""), j.get("experience",""), j.get("url",""))
                 for j in jobs]
            )

async def start_worker():
    asyncio.create_task(_worker())
