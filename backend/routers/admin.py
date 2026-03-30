from fastapi import APIRouter, Depends, HTTPException
from database import get_db
from auth import admin_only

router = APIRouter(prefix="/api/admin", tags=["admin"])

@router.get("/stats")
def stats(admin=Depends(admin_only)):
    with get_db() as db:
        users   = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        searches= db.execute("SELECT COUNT(*) FROM searches").fetchone()[0]
        running = db.execute("SELECT COUNT(*) FROM searches WHERE status='running'").fetchone()[0]
        jobs    = db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    return {"users": users, "searches": searches, "running": running, "jobs": jobs}

@router.get("/users")
def list_users(admin=Depends(admin_only)):
    with get_db() as db:
        rows = db.execute(
            "SELECT u.id,u.email,u.role,u.is_active,u.created_at,"
            "(SELECT COUNT(*) FROM searches WHERE user_id=u.id) AS searches,"
            "(SELECT MAX(created_at) FROM searches WHERE user_id=u.id) AS last_search "
            "FROM users u ORDER BY u.id DESC"
        ).fetchall()
    return [dict(r) for r in rows]

@router.get("/searches")
def list_searches(admin=Depends(admin_only)):
    with get_db() as db:
        rows = db.execute(
            "SELECT s.*,u.email FROM searches s JOIN users u ON s.user_id=u.id "
            "ORDER BY s.id DESC LIMIT 100"
        ).fetchall()
    return [dict(r) for r in rows]

@router.post("/users/{uid}/toggle")
def toggle_user(uid: int, admin=Depends(admin_only)):
    with get_db() as db:
        row = db.execute("SELECT is_active,role FROM users WHERE id=?", (uid,)).fetchone()
        if not row:
            raise HTTPException(404)
        if row["role"] == "admin":
            raise HTTPException(400, "Cannot deactivate admin")
        new = 0 if row["is_active"] else 1
        db.execute("UPDATE users SET is_active=? WHERE id=?", (new, uid))
    return {"is_active": bool(new)}

@router.post("/users/{uid}/role")
def set_role(uid: int, role: str, admin=Depends(admin_only)):
    if role not in ("user", "admin"):
        raise HTTPException(400, "Invalid role")
    with get_db() as db:
        db.execute("UPDATE users SET role=? WHERE id=?", (role, uid))
    return {"ok": True}
