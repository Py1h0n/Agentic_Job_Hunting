from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from database import get_db
from auth import current_user
from agents import available_agents
import job_queue as q_module

router = APIRouter(prefix="/api/search", tags=["search"])

class SearchReq(BaseModel):
    query: str
    location: str = ""
    max_jobs: int = 50
    agent: str = "bdjobs"

@router.get("/agents")
def list_agents():
    return available_agents()

@router.post("")
async def create_search(body: SearchReq, user=Depends(current_user)):
    uid = int(user["sub"])
    if body.agent not in {a["key"] for a in available_agents()}:
        raise HTTPException(400, "Unknown agent")
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO searches (user_id,agent,query,location,max_jobs) VALUES (?,?,?,?,?)",
            (uid, body.agent, body.query.strip(), body.location.strip(), body.max_jobs)
        )
        sid = cur.lastrowid
    await q_module.enqueue(sid, uid, body.agent, body.query, body.location, body.max_jobs)
    return {"search_id": sid}

@router.get("/{sid}/status")
def search_status(sid: int, user=Depends(current_user)):
    uid = int(user["sub"])
    with get_db() as db:
        row = db.execute(
            "SELECT id,status,total_found,query,agent,created_at,finished_at "
            "FROM searches WHERE id=? AND user_id=?", (sid, uid)
        ).fetchone()
    if not row:
        raise HTTPException(404)
    return dict(row)

@router.get("/{sid}/results")
def search_results(sid: int, user=Depends(current_user)):
    uid = int(user["sub"])
    with get_db() as db:
        s = db.execute("SELECT * FROM searches WHERE id=? AND user_id=?", (sid, uid)).fetchone()
        if not s:
            raise HTTPException(404)
        jobs = db.execute(
            "SELECT * FROM jobs WHERE search_id=? ORDER BY id", (sid,)
        ).fetchall()
    return {"search": dict(s), "jobs": [dict(j) for j in jobs]}

@router.get("/history")
def history(user=Depends(current_user)):
    uid = int(user["sub"])
    with get_db() as db:
        rows = db.execute(
            "SELECT id,agent,query,location,status,total_found,created_at "
            "FROM searches WHERE user_id=? ORDER BY id DESC LIMIT 50", (uid,)
        ).fetchall()
    return [dict(r) for r in rows]

@router.post("/jobs/{job_id}/save")
def toggle_save(job_id: int, user=Depends(current_user)):
    uid = int(user["sub"])
    with get_db() as db:
        row = db.execute("SELECT saved FROM jobs WHERE id=? AND user_id=?", (job_id, uid)).fetchone()
        if not row:
            raise HTTPException(404)
        new = 0 if row["saved"] else 1
        db.execute("UPDATE jobs SET saved=? WHERE id=?", (new, job_id))
    return {"saved": bool(new)}

@router.get("/saved")
def saved_jobs(user=Depends(current_user)):
    uid = int(user["sub"])
    with get_db() as db:
        rows = db.execute(
            "SELECT j.*,s.query FROM jobs j JOIN searches s ON j.search_id=s.id "
            "WHERE j.user_id=? AND j.saved=1 ORDER BY j.id DESC", (uid,)
        ).fetchall()
    return [dict(r) for r in rows]
