"""
Lightweight in-process job queue.
- MAX_CONCURRENT agents run at once (default 3).
- Extra searches wait in an asyncio.Queue.
- No Redis, no Celery — just asyncio primitives.
- SSE events for realtime streaming.
"""

import asyncio
import json
from database import get_db
from agents import run_agent

MAX_CONCURRENT = int(__import__("os").getenv("MAX_CONCURRENT", 3))

_semaphore: asyncio.Semaphore | None = None
_queue: asyncio.Queue | None = None

# SSE event system for realtime streaming
_event_queue: asyncio.Queue | None = None
_listeners: dict = {}  # search_id -> list of asyncio.Queue


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


# ── SSE Event System ────────────────────────────────────────────────────────────


def get_event_queue() -> asyncio.Queue:
    """Get the global event queue for SSE."""
    global _event_queue
    if _event_queue is None:
        _event_queue = asyncio.Queue()
    return _event_queue


def subscribe(search_id: int) -> asyncio.Queue:
    """Subscribe to events for a specific search."""
    global _listeners
    if search_id not in _listeners:
        _listeners[search_id] = []
    # Create a new queue for this listener
    q = asyncio.Queue(maxsize=100)
    _listeners[search_id].append(q)
    return q


def unsubscribe(search_id: int, q: asyncio.Queue):
    """Unsubscribe from events."""
    global _listeners
    if search_id in _listeners and q in _listeners[search_id]:
        _listeners[search_id].remove(q)


async def emit_event(search_id: int, event_type: str, data: dict):
    """Emit an event to all subscribers of a search."""
    global _listeners
    event = json.dumps({"type": event_type, "search_id": search_id, **data})

    if search_id in _listeners:
        # Remove dead queues
        _listeners[search_id] = [q for q in _listeners[search_id] if not q.full()]
        for q in _listeners[search_id]:
            try:
                await q.put(event)
            except asyncio.QueueFull:
                pass  # Listener buffer full, skip

    # Also put in global queue for SSE endpoint
    await get_event_queue().put(event)


async def enqueue(
    search_id: int, user_id: int, agent: str, query: str, location: str, max_jobs: int
):
    """Queue a search and return immediately."""
    await get_queue().put((search_id, user_id, agent, query, location, max_jobs))


async def _worker():
    """Long-running worker that processes the queue."""
    q = get_queue()
    sem = get_semaphore()
    while True:
        item = await q.get()
        search_id, user_id, agent, query, location, max_jobs = item
        asyncio.create_task(
            _run(sem, search_id, user_id, agent, query, location, max_jobs)
        )
        q.task_done()


async def _run(sem, search_id, user_id, agent, query, location, max_jobs):
    async with sem:
        _set_status(search_id, "running")
        # Emit start event
        await emit_event(
            search_id,
            "started",
            {"status": "running", "message": f"Starting {agent} search..."},
        )

        try:
            result = await run_agent(
                agent, query, location, max_jobs, search_id, user_id
            )
            _save_results(search_id, user_id, result)

            # Emit complete event
            total = result.get("total", 0)
            status = result.get("status", "success")
            await emit_event(
                search_id,
                "completed",
                {"status": status, "total": total, "message": f"Found {total} jobs"},
            )
        except Exception as e:
            _set_status(search_id, "failed")
            await emit_event(search_id, "failed", {"error": str(e)})
            print(f"[queue] search {search_id} failed: {e}")


def _set_status(search_id: int, status: str):
    with get_db() as db:
        db.execute("UPDATE searches SET status=? WHERE id=?", (status, search_id))


def _save_results(search_id: int, user_id: int, result: dict):
    jobs = result.get("jobs", [])
    status = result.get("status", "success")

    # If the agent already saved jobs incrementally, total_found in DB might be > 0
    # but the 'jobs' list returned by run_agent might contain them again.
    # We call save_jobs_to_db again which handles duplicate URLs.
    from database import save_jobs_to_db

    total = save_jobs_to_db(search_id, user_id, jobs)

    with get_db() as db:
        # Get final total from DB (including incremental ones)
        row = db.execute(
            "SELECT COUNT(*) as cnt FROM jobs WHERE search_id=?", (search_id,)
        ).fetchone()
        real_total = row["cnt"] if row else 0

        if real_total == 0 and status != "failed":
            status = "partial"

        db.execute(
            "UPDATE searches SET status=?, total_found=?, finished_at=datetime('now') WHERE id=?",
            (status, real_total, search_id),
        )


async def start_worker():
    asyncio.create_task(_worker())


# Helper for agents to emit incremental job events
async def on_jobs_found(search_id: int, count: int, jobs: list):
    """Called by agents when they find new jobs."""
    # Get preview of first few jobs
    preview = []
    for job in jobs[:3]:
        preview.append(
            {
                "title": job.get("title", "")[:50],
                "company": job.get("company", ""),
                "location": job.get("location", ""),
            }
        )

    await emit_event(
        search_id,
        "jobs_found",
        {"count": count, "total_so_far": count, "preview": preview},
    )
