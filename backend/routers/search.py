from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, model_validator
from database import get_db
from auth import current_user
from agents import available_agents, AGENTS
import job_queue as q_module
import asyncio
import uuid
import os
from datetime import datetime


# LLM client for AI analysis
def _get_llm_client():
    try:
        from openai import OpenAI

        return OpenAI(
            base_url="https://api.tokenfactory.nebius.com/v1/",
            api_key=os.environ.get("NEBIUS_API_KEY", ""),
        )
    except Exception:
        return None


router = APIRouter(prefix="/api/search", tags=["search"])

TURBO_AGENTS = ["bdjobs"]  # Turbo = bdjobs only (vision-based scraper)
STANDARD_AGENTS = [
    "skilljobs",
    "jobmedia",
]  # 2 sources - balanced
DEEP_AGENTS = [  # All sources, slowest but most comprehensive
    "skilljobs",
    "jobmedia",
    "nextjobz",
    "niyog",
    "atb",
]


def _get_turbo_agents() -> list[str]:
    """Turbo mode: single fastest source (bdjobs)"""
    return TURBO_AGENTS.copy()


def _get_standard_agents() -> list[str]:
    """Standard mode: 3 balanced sources"""
    return STANDARD_AGENTS.copy()


def _get_deep_agents() -> list[str]:
    """Deep mode: all sources for maximum coverage"""
    return DEEP_AGENTS.copy()


class SearchReq(BaseModel):
    query: str
    location: str = ""
    max_jobs: int = 30
    agent: str | None = None
    mode: str = "turbo"  # turbo, standard, deep

    @model_validator(mode="after")
    def validate_positive(self):
        if self.max_jobs < 0:
            self.max_jobs = 0
        # Validate mode
        if self.mode not in ["turbo", "standard", "deep"]:
            self.mode = "turbo"
        return self


@router.get("/agents/status")
def get_agents_status(search_ids: str, user=Depends(current_user)):
    """Get status for multiple search agents. search_ids = comma-separated list"""
    uid = int(user["sub"])
    ids = [int(x.strip()) for x in search_ids.split(",") if x.strip()]

    agents_status = []
    with get_db() as db:
        for sid in ids:
            row = db.execute(
                "SELECT id, agent, status, total_found, created_at, finished_at "
                "FROM searches WHERE id=? AND user_id=?",
                (sid, uid),
            ).fetchone()
            if row:
                agents_status.append(
                    {
                        "search_id": row["id"],
                        "agent": row["agent"],
                        "status": row["status"],
                        "jobs_found": row["total_found"] or 0,
                        "created_at": row["created_at"],
                        "finished_at": row["finished_at"],
                    }
                )
    return {"agents": agents_status}


# ── Static routes MUST come before /{sid} routes ─────────────────────────────
# FastAPI matches top-down. If /{sid} is registered first, "history" and
# "saved" get captured by it, cast to int, fail with 422.


@router.get("/history")
def history(
    user=Depends(current_user),
    limit: int = 50,
    offset: int = 0,
    query: str = None,
):
    """Get user's search history grouped by session."""
    uid = int(user["sub"])
    with get_db() as db:
        if query:
            # Group by session_id but pick one record to represent it
            rows = db.execute(
                "SELECT session_id, query, location, mode, agents, "
                "SUM(total_found) as total_found, MIN(created_at) as created_at, "
                "MAX(finished_at) as finished_at, status "
                "FROM searches WHERE user_id=? AND is_deleted=0 AND query LIKE ? "
                "GROUP BY session_id ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (uid, f"%{query}%", limit, offset),
            ).fetchall()
            count = db.execute(
                "SELECT COUNT(DISTINCT session_id) FROM searches WHERE user_id=? AND is_deleted=0 AND query LIKE ?",
                (uid, f"%{query}%"),
            ).fetchone()[0]
        else:
            rows = db.execute(
                "SELECT COALESCE(session_id, CAST(id AS TEXT)) as session_id, query, location, mode, agents, "
                "SUM(total_found) as total_found, MIN(created_at) as created_at, "
                "MAX(finished_at) as finished_at, MAX(duration_ms) as duration_ms, "
                "MAX(CASE WHEN status='running' THEN 5 WHEN status='queued' THEN 4 WHEN status='success' THEN 3 ELSE 0 END) as status_rank "
                "FROM searches WHERE user_id=? AND is_deleted=0 "
                "GROUP BY COALESCE(session_id, CAST(id AS TEXT)) ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (uid, limit, offset),
            ).fetchall()
            count = db.execute(
                "SELECT COUNT(DISTINCT COALESCE(session_id, CAST(id AS TEXT))) FROM searches WHERE user_id=? AND is_deleted=0",
                (uid,),
            ).fetchone()[0]
    return {
        "data": [dict(r) for r in rows],
        "total": count,
        "limit": limit,
        "offset": offset,
    }


@router.get("/history/session/{session_id}")
def session_detail(session_id: str, user=Depends(current_user)):
    """Get all jobs from a specific search session."""
    uid = int(user["sub"])
    with get_db() as db:
        # Get session info - handle both session_id string and old integer id
        s = db.execute(
            "SELECT query, location, mode, agents, created_at, status "
            "FROM searches WHERE (session_id=? OR CAST(id AS TEXT)=?) AND user_id=? AND is_deleted=0 LIMIT 1",
            (session_id, session_id, uid),
        ).fetchone()
        if not s:
            raise HTTPException(404, "Session not found")

        # Get all jobs for all searches in this session
        jobs = db.execute(
            "SELECT j.* FROM jobs j "
            "JOIN searches s ON j.search_id = s.id "
            "WHERE (s.session_id=? OR CAST(s.id AS TEXT)=?) AND j.user_id=? AND j.is_deleted=0 ORDER BY j.id",
            (session_id, session_id, uid),
        ).fetchall()

        # Group status: if any agent is running, session is running
        # This is simplified - real production might want complex status merging
        all_searches = db.execute(
            "SELECT status, total_found FROM searches WHERE session_id=?", (session_id,)
        ).fetchall()
        total_found = sum(r["total_found"] for r in all_searches)

    return {
        "search": {**dict(s), "session_id": session_id, "total_found": total_found},
        "jobs": [dict(j) for j in jobs],
    }


@router.get("/history/{history_id}")
def history_detail(history_id: int, user=Depends(current_user)):
    """Keep for backward compatibility - redirects to session if possible."""
    uid = int(user["sub"])
    with get_db() as db:
        row = db.execute(
            "SELECT session_id FROM searches WHERE id=?", (history_id,)
        ).fetchone()
        if row and row["session_id"]:
            return session_detail(row["session_id"], user)
        # Fallback to old behavior
        s = db.execute(
            "SELECT * FROM searches WHERE id=? AND user_id=? AND is_deleted=0",
            (history_id, uid),
        ).fetchone()
        if not s:
            raise HTTPException(404, "Search not found")
        jobs = db.execute(
            "SELECT * FROM jobs WHERE search_id=? AND user_id=? AND is_deleted=0 ORDER BY id",
            (history_id, uid),
        ).fetchall()
    return {"search": dict(s), "jobs": [dict(j) for j in jobs]}


@router.delete("/history/session/{session_id}")
def delete_session(session_id: str, user=Depends(current_user)):
    """Delete an entire search session and all its jobs."""
    uid = int(user["sub"])
    with get_db() as db:
        db.execute(
            "UPDATE searches SET is_deleted=1 WHERE session_id=? AND user_id=?",
            (session_id, uid),
        )
        db.execute(
            "UPDATE jobs SET is_deleted=1 WHERE user_id=? AND search_id IN (SELECT id FROM searches WHERE session_id=?)",
            (uid, session_id),
        )
    return {"message": "Session deleted"}


@router.delete("/history/{history_id}")
def delete_history(history_id: int, user=Depends(current_user)):
    """Soft delete a search (GDPR)."""
    uid = int(user["sub"])
    with get_db() as db:
        # Get session_id
        row = db.execute(
            "SELECT session_id FROM searches WHERE id=? AND user_id=?",
            (history_id, uid),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Search not found")

        sid_val = row["session_id"]
        if sid_val:
            db.execute(
                "UPDATE searches SET is_deleted=1 WHERE session_id=?", (sid_val,)
            )
            db.execute(
                "UPDATE jobs SET is_deleted=1 WHERE search_id IN (SELECT id FROM searches WHERE session_id=?)",
                (sid_val,),
            )
        else:
            db.execute("UPDATE searches SET is_deleted=1 WHERE id=?", (history_id,))
            db.execute("UPDATE jobs SET is_deleted=1 WHERE search_id=?", (history_id,))
    return {"message": "Search session deleted"}


@router.delete("/history/{history_id}/hard")
def hard_delete_history(history_id: int, user=Depends(current_user)):
    """Permanently delete search and all associated jobs."""
    uid = int(user["sub"])
    with get_db() as db:
        row = db.execute(
            "SELECT id FROM searches WHERE id=? AND user_id=?", (history_id, uid)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Search not found")
        db.execute("DELETE FROM jobs WHERE search_id=?", (history_id,))
        db.execute("DELETE FROM searches WHERE id=?", (history_id,))
    return {"message": "Search permanently deleted"}


@router.delete("/history")
def delete_all_history(user=Depends(current_user)):
    """Delete all user history (GDPR compliance)."""
    uid = int(user["sub"])
    with get_db() as db:
        db.execute("UPDATE searches SET is_deleted=1 WHERE user_id=?", (uid,))
        db.execute("UPDATE jobs SET is_deleted=1 WHERE user_id=?", (uid,))
    return {"message": "All data deleted"}


@router.get("/history/export")
def export_user_data(user=Depends(current_user)):
    """Export all user data (GDPR Art. 15)."""
    uid = int(user["sub"])
    with get_db() as db:
        searches = db.execute(
            "SELECT * FROM searches WHERE user_id=? AND is_deleted=0", (uid,)
        ).fetchall()
        jobs = db.execute(
            "SELECT * FROM jobs WHERE user_id=? AND is_deleted=0", (uid,)
        ).fetchall()
    return {"searches": [dict(s) for s in searches], "jobs": [dict(j) for j in jobs]}


@router.get("/saved")
def saved_jobs(
    user=Depends(current_user),
    limit: int = 50,
    offset: int = 0,
):
    """Get user's saved jobs with pagination."""
    uid = int(user["sub"])
    with get_db() as db:
        rows = db.execute(
            "SELECT j.*,s.query FROM jobs j JOIN searches s ON j.search_id=s.id "
            "WHERE j.user_id=? AND j.saved=1 AND j.is_deleted=0 ORDER BY j.id DESC LIMIT ? OFFSET ?",
            (uid, limit, offset),
        ).fetchall()
        count = db.execute(
            "SELECT COUNT(*) FROM jobs WHERE user_id=? AND saved=1 AND is_deleted=0",
            (uid,),
        ).fetchone()[0]
    return {
        "data": [dict(r) for r in rows],
        "total": count,
        "limit": limit,
        "offset": offset,
    }


@router.get("/jobs/{job_id}")
def get_job(job_id: int, user=Depends(current_user)):
    """Get a specific job."""
    uid = int(user["sub"])
    with get_db() as db:
        row = db.execute(
            "SELECT j.*,s.query FROM jobs j JOIN searches s ON j.search_id=s.id "
            "WHERE j.id=? AND j.user_id=? AND j.is_deleted=0",
            (job_id, uid),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Job not found")
    return dict(row)


@router.post("/jobs/{job_id}/apply")
def mark_applied(job_id: int, user=Depends(current_user)):
    """Mark a job as applied."""
    uid = int(user["sub"])
    with get_db() as db:
        row = db.execute(
            "SELECT id FROM jobs WHERE id=? AND user_id=? AND is_deleted=0",
            (job_id, uid),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Job not found")
        db.execute("UPDATE jobs SET applied=1 WHERE id=?", (job_id,))
        db.execute(
            "INSERT INTO applied_jobs (user_id, job_id) VALUES (?, ?)", (uid, job_id)
        )
    return {"applied": True}


@router.delete("/jobs/{job_id}")
def delete_job(job_id: int, user=Depends(current_user)):
    """Soft delete a job."""
    uid = int(user["sub"])
    with get_db() as db:
        row = db.execute(
            "SELECT id FROM jobs WHERE id=? AND user_id=?", (job_id, uid)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Job not found")
        db.execute("UPDATE jobs SET is_deleted=1 WHERE id=?", (job_id,))
    return {"message": "Job deleted"}


@router.post("/jobs/bulk-delete")
def bulk_delete_jobs(job_ids: list[int], user=Depends(current_user)):
    """Bulk soft delete jobs."""
    uid = int(user["sub"])
    if not job_ids:
        raise HTTPException(400, "No job IDs provided")
    with get_db() as db:
        placeholders = ",".join("?" * len(job_ids))
        db.execute(
            f"UPDATE jobs SET is_deleted=1 WHERE id IN ({placeholders}) AND user_id=?",
            (*job_ids, uid),
        )
    return {"message": f"Deleted {len(job_ids)} jobs"}


@router.post("/jobs/bulk-delete-all")
def bulk_delete_all_jobs(user=Depends(current_user)):
    """Delete ALL jobs for the user (both searched and saved)."""
    uid = int(user["sub"])
    with get_db() as db:
        # Get count before delete
        count = db.execute(
            "SELECT COUNT(*) as c FROM jobs WHERE user_id=? AND is_deleted=0", (uid,)
        ).fetchone()
        deleted_count = count["c"] if count else 0

        # Soft delete all jobs
        db.execute("UPDATE jobs SET is_deleted=1 WHERE user_id=?", (uid,))

        # Also mark all searches as deleted
        db.execute("UPDATE searches SET is_deleted=1 WHERE user_id=?", (uid,))

    return {"message": f"Deleted all {deleted_count} jobs"}


@router.post("/jobs/bulk-save")
def bulk_save_jobs(job_ids: list[int], user=Depends(current_user)):
    """Bulk save jobs."""
    uid = int(user["sub"])
    if not job_ids:
        raise HTTPException(400, "No job IDs provided")
    with get_db() as db:
        placeholders = ",".join("?" * len(job_ids))
        db.execute(
            f"UPDATE jobs SET saved=1 WHERE id IN ({placeholders}) AND user_id=?",
            (*job_ids, uid),
        )
    return {"message": f"Saved {len(job_ids)} jobs"}


# ── Dynamic /{sid} routes below ───────────────────────────────────────────────


@router.post("/start")
async def create_search(body: SearchReq, user=Depends(current_user)):
    uid = int(user["sub"])

    # Determine which agents to run based on mode
    if body.mode == "deep":
        agents_to_run = _get_deep_agents()
    elif body.mode == "standard":
        agents_to_run = _get_standard_agents()
    else:
        # turbo mode (default)
        agents_to_run = [body.agent] if body.agent else _get_turbo_agents()

    all_agent_keys = {a["key"] for a in available_agents()}
    for ag in agents_to_run:
        if ag not in all_agent_keys:
            raise HTTPException(400, f"Unknown agent: {ag}")

    created_search_ids = []
    agent_ids = {}
    session_id = str(uuid.uuid4())

    for agent_key in agents_to_run:
        with get_db() as db:
            cur = db.execute(
                "INSERT INTO searches (user_id,agent,query,location,max_jobs,status,mode,agents,session_id) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    uid,
                    agent_key,
                    body.query.strip(),
                    body.location.strip(),
                    body.max_jobs,
                    "queued",
                    body.mode,
                    ",".join(agents_to_run),
                    session_id,
                ),
            )
            sid = cur.lastrowid
        await q_module.enqueue(
            sid, uid, agent_key, body.query, body.location, body.max_jobs
        )
        created_search_ids.append(sid)
        agent_ids[agent_key] = sid

    return {
        "search_ids": created_search_ids,
        "agent_ids": agent_ids,
        "session_id": session_id,
        "mode": body.mode,
        "agents": agents_to_run,
    }


@router.get("/modes")
def list_modes():
    return {
        "modes": [
            {
                "key": "turbo",
                "label": "Turbo (bdjobs only - fastest)",
                "agents": _get_turbo_agents(),
            },
            {
                "key": "standard",
                "label": "Standard (3 sources - balanced)",
                "agents": _get_standard_agents(),
            },
            {
                "key": "deep",
                "label": "Deep (all sources - most comprehensive)",
                "agents": _get_deep_agents(),
            },
        ]
    }


# ── SSE Streaming Endpoint ──────────────────────────────────────────────────


@router.get("/stream/{sid}")
async def stream_search(sid: int, user=Depends(current_user)):
    """Server-Sent Events stream for realtime search updates."""
    uid = int(user["sub"])

    # Verify ownership
    with get_db() as db:
        row = db.execute(
            "SELECT id FROM searches WHERE id=? AND user_id=?", (sid, uid)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Search not found")

    async def event_generator():
        import json

        queue = q_module.subscribe(sid)
        try:
            # Send initial connection event
            yield 'event: connected\ndata: {"status": "connected"}\n\n'

            while True:
                try:
                    # Wait for events with timeout
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {event}\n\n"

                    # Parse to check if completed
                    try:
                        data = json.loads(event)
                        if data.get("type") in ["completed", "failed"]:
                            break
                    except:
                        pass

                except asyncio.TimeoutError:
                    # Send keepalive
                    yield ": keepalive\n\n"

        except Exception as e:
            yield f'event: error\ndata: {{"error": "{str(e)}"}}\n\n'
        finally:
            q_module.unsubscribe(sid, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/{sid}/status")
def search_status(sid: int, user=Depends(current_user)):
    uid = int(user["sub"])
    with get_db() as db:
        row = db.execute(
            "SELECT id,status,total_found,query,agent,created_at,finished_at "
            "FROM searches WHERE id=? AND user_id=?",
            (sid, uid),
        ).fetchone()
    if not row:
        raise HTTPException(404)
    return dict(row)


@router.get("/stats")
def search_stats(user=Depends(current_user)):
    uid = int(user["sub"])
    with get_db() as db:
        # New Matches (last 24h)
        new_matches = db.execute(
            "SELECT COUNT(*) as count FROM jobs WHERE user_id=? AND created_at > datetime('now','-1 day')",
            (uid,),
        ).fetchone()["count"]

        # Saved Opportunities
        saved_count = db.execute(
            "SELECT COUNT(*) as count FROM jobs WHERE user_id=? AND saved=1", (uid,)
        ).fetchone()["count"]

        # Active Applications
        applied_count = db.execute(
            "SELECT COUNT(*) as count FROM applied_jobs WHERE user_id=?", (uid,)
        ).fetchone()["count"]

        # High-match count (e.g. match_score > 80)
        high_match = db.execute(
            "SELECT COUNT(*) as count FROM jobs WHERE user_id=? AND match_score >= 80",
            (uid,),
        ).fetchone()["count"]

    return {
        "new_matches": new_matches,
        "saved_count": saved_count,
        "applied_count": applied_count,
        "high_match": high_match,
        "top_skill": "Python / React",  # Placeholder for real skill analysis
    }


@router.get("/insights")
def search_insights(user=Depends(current_user)):
    """Get personalized insights from user's SAVED jobs only"""
    import re

    uid = int(user["sub"])
    with get_db() as db:
        jobs = db.execute(
            """SELECT skills, salary, location, job_type, experience, match_score, company, deadline
               FROM jobs WHERE user_id=? AND saved=1""",
            (uid,),
        ).fetchall()

        if not jobs:
            return {
                "debug": {"user_id": uid, "source": "search_insights"},
                "skills_demand": {},
                "salary_ranges": {"min": 0, "max": 0, "avg": 0, "currency": "BDT"},
                "market_clusters": {},
                "avg_match": 0,
                "total_analyzed": 0,
                "job_types": {},
                "top_locations": {},
                "experience_levels": {},
                "top_companies": [],
                "message": "No saved jobs yet. Save some jobs to get personalized insights!",
            }

        skill_counts = {}
        salary_values = []
        location_counts = {}
        job_type_counts = {}
        exp_counts = {}
        company_counts = {}
        deadline_list = []
        score_list = []

        for job in jobs:
            if job["skills"]:
                for s in [p.strip() for p in job["skills"].split(",") if p.strip()]:
                    skill_counts[s] = skill_counts.get(s, 0) + 1
            if job["salary"]:
                nums = re.findall(r"\d+", job["salary"])
                if nums:
                    salary_values.append(max([int(n) for n in nums if int(n) > 1000]))
            if job["location"]:
                location_counts[job["location"]] = (
                    location_counts.get(job["location"], 0) + 1
                )
            if job["job_type"]:
                job_type_counts[job["job_type"]] = (
                    job_type_counts.get(job["job_type"], 0) + 1
                )
            if job["experience"]:
                exp_counts[job["experience"]] = exp_counts.get(job["experience"], 0) + 1
            if job["company"]:
                company_counts[job["company"]] = (
                    company_counts.get(job["company"], 0) + 1
                )
            if job["deadline"]:
                deadline_list.append(job["deadline"])
            # Calculate match score - use existing or default based on having skills
            if job["match_score"]:
                score_list.append(job["match_score"])
            elif job["skills"]:
                # Default score for jobs with skills (they're relevant to search)
                score_list.append(55)

        avg_salary = sum(salary_values) / len(salary_values) if salary_values else 0
        avg_score = sum(score_list) / len(score_list) if score_list else 0

        return {
            "skills_demand": {
                s[0]: s[1]
                for s in sorted(skill_counts.items(), key=lambda x: x[1], reverse=True)[
                    :10
                ]
            },
            "salary_ranges": {
                "min": int(avg_salary * 0.7) if avg_salary else 0,
                "max": int(avg_salary * 1.3) if avg_salary else 0,
                "avg": int(avg_salary) if avg_salary else 0,
                "currency": "BDT",
            },
            "market_clusters": {
                "Strong Match": len([s for s in score_list if s >= 80]),
                "Developing": len([s for s in score_list if 60 <= s < 80]),
                "Entry Level": len([s for s in score_list if s < 60]),
                "High Potential": len([s for s in score_list if s >= 90]),
            },
            "avg_match": round(avg_score, 1),
            "total_analyzed": len(jobs),
            "debug": {
                "user_id": uid,
                "score_count": len(score_list),
                "salary_count": len(salary_values),
            },
            "job_types": job_type_counts,
            "top_locations": dict(
                sorted(location_counts.items(), key=lambda x: x[1], reverse=True)[:5]
            ),
            "experience_levels": exp_counts,
            "top_companies": [
                {"name": c[0], "count": c[1]}
                for c in sorted(
                    company_counts.items(), key=lambda x: x[1], reverse=True
                )[:8]
            ],
            "application_deadlines": deadline_list[:10],
            "salary_data_points": len(salary_values),
            "ai_analyzed": False,  # Not AI-analyzed yet
        }


@router.post("/analyze")
def analyze_insights(user=Depends(current_user)):
    """AI-powered analysis of saved jobs - generates meaningful insights"""
    import json

    uid = int(user["sub"])
    client = _get_llm_client()

    with get_db() as db:
        jobs = db.execute(
            """SELECT title, company, skills, salary, location, job_type, experience, requirements, responsibilities
               FROM jobs WHERE user_id=? AND saved=1""",
            (uid,),
        ).fetchall()

        if not jobs:
            return {"error": "No saved jobs to analyze", "insights": None}

        # Prepare job data for AI
        job_list = []
        for job in jobs:
            job_list.append(
                {
                    "title": job["title"] or "",
                    "company": job["company"] or "",
                    "skills": job["skills"] or "",
                    "salary": job["salary"] or "",
                    "location": job["location"] or "",
                    "job_type": job["job_type"] or "",
                    "experience": job["experience"] or "",
                    "requirements": job["requirements"] or "",
                    "responsibilities": job["responsibilities"] or "",
                }
            )

        if not client:
            # Fallback to basic aggregation if no LLM client
            return _basic_insights(job_list)

        # Format jobs for prompt
        jobs_text = json.dumps(job_list[:20], indent=2)  # Limit to 20 jobs

        system_prompt = """You are a career insights analyst. Analyze the user's saved jobs and provide meaningful insights.
Return ONLY valid JSON (no markdown, no explanation):

{
  "market_insights": {
    "top_skills_demand": ["skill1", "skill2", ...],
    "salary_insight": "Average salary is X BDT with range Y-Z",
    "experience_trend": "Most jobs require X-Y years experience",
    "job_type_trend": "X% are Full Time, Y% are Contract",
    "location_trend": "Most jobs are in Dhaka/Bangalore/Remote",
    "company_types": "X startups, Y MNCs, Z agencies"
  },
  "career_advice": {
    "strengths": ["Based on your saved jobs, your profile matches..."],
    "gaps": ["You might want to learn..."],
    "opportunities": ["There are X jobs matching your profile..."]
  },
  "matching_jobs": X,
  "ready_to_apply": Y
}"""

        try:
            response = client.chat.completions.create(
                model=os.environ.get(
                    "NEBIUS_RESUME_MODEL", "google/gemma-3-27b-it-fast"
                ),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": f"Analyze these saved jobs and provide career insights:\n{jobs_text[:3000]}",
                    },
                ],
                temperature=0.3,
                max_tokens=1500,
            )

            result_text = response.choices[0].message.content.strip()
            # Parse JSON from response
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0]
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0]

            insights = json.loads(result_text)
            return {
                "insights": insights,
                "ai_analyzed": True,
                "jobs_analyzed": len(job_list),
            }

        except Exception as e:
            print(f"[AI Analysis] Error: {e}")
            return _basic_insights(job_list)


def _basic_insights(job_list):
    """Fallback basic insights when AI is not available"""
    from collections import Counter

    skills = []
    locations = []
    job_types = []
    salaries = []

    for job in job_list:
        if job.get("skills"):
            skills.extend([s.strip() for s in job["skills"].split(",") if s.strip()])
        if job.get("location"):
            locations.append(job["location"])
        if job.get("job_type"):
            job_types.append(job["job_type"])
        if job.get("salary"):
            import re

            nums = re.findall(r"\d+", job["salary"])
            if nums:
                salaries.append(max([int(n) for n in nums if int(n) > 1000]))

    skill_counts = Counter(skills)
    location_counts = Counter(locations)
    job_type_counts = Counter(job_types)

    avg_salary = sum(salaries) / len(salaries) if salaries else 0

    return {
        "insights": {
            "market_insights": {
                "top_skills_demand": [s for s, _ in skill_counts.most_common(5)],
                "salary_insight": f"Average salary is {int(avg_salary)} BDT"
                if avg_salary
                else "Salary data not available",
                "experience_trend": "Check individual job requirements",
                "job_type_trend": ", ".join(
                    [f"{k}: {v}" for k, v in job_type_counts.most_common(3)]
                ),
                "location_trend": ", ".join(
                    [f"{k}: {v}" for k, v in location_counts.most_common(3)]
                ),
            },
            "career_advice": {
                "strengths": ["You have saved jobs matching your search criteria"],
                "gaps": ["Review job requirements for skill gaps"],
                "opportunities": [f"{len(job_list)} jobs saved and ready to apply"],
            },
        },
        "ai_analyzed": False,  # Basic analysis only
        "jobs_analyzed": len(job_list),
    }


@router.get("/{sid}/results")
def search_results(sid: int, user=Depends(current_user)):
    """Legacy endpoint for backward compatibility."""
    uid = int(user["sub"])
    with get_db() as db:
        s = db.execute(
            "SELECT * FROM searches WHERE id=? AND user_id=? AND is_deleted=0",
            (sid, uid),
        ).fetchone()
        if not s:
            raise HTTPException(404, "Search not found")
        jobs = db.execute(
            "SELECT * FROM jobs WHERE search_id=? AND is_deleted=0 ORDER BY id", (sid,)
        ).fetchall()
    return {
        "status": s["status"],
        "results": [dict(j) for j in jobs],
        "total_found": s["total_found"],
    }


@router.get("/session/{session_id}/results")
def session_results(session_id: str, user=Depends(current_user)):
    """Get results for all searches in a session."""
    uid = int(user["sub"])
    with get_db() as db:
        # Get all search IDs for this session
        searches = db.execute(
            "SELECT id, agent, status, total_found FROM searches WHERE (session_id=? OR CAST(id AS TEXT)=?) AND user_id=? AND is_deleted=0",
            (session_id, session_id, uid),
        ).fetchall()

        if not searches:
            raise HTTPException(404, "Session not found")

        # Determine overall session status
        statuses = [s["status"] for s in searches]
        if "running" in statuses:
            final_status = "running"
        elif "queued" in statuses:
            final_status = "queued"
        elif any(s in statuses for s in ["success", "partial"]):
            final_status = "completed"
        else:
            final_status = "failed"

        # Get all jobs
        search_ids = [s["id"] for s in searches]
        placeholders = ",".join("?" * len(search_ids))
        jobs = db.execute(
            f"SELECT * FROM jobs WHERE search_id IN ({placeholders}) AND is_deleted=0 ORDER BY id",
            tuple(search_ids),
        ).fetchall()

    return {
        "status": final_status,
        "agents": [dict(s) for s in searches],
        "results": [dict(j) for j in jobs],
        "total_found": len(jobs),
    }


@router.post("/jobs/{job_id}/save")
def toggle_save(job_id: int, user=Depends(current_user)):
    uid = int(user["sub"])
    with get_db() as db:
        row = db.execute(
            "SELECT saved FROM jobs WHERE id=? AND user_id=?", (job_id, uid)
        ).fetchone()
        if not row:
            raise HTTPException(404)
        new = 0 if row["saved"] else 1
        db.execute("UPDATE jobs SET saved=? WHERE id=?", (new, job_id))
    return {"saved": bool(new)}
