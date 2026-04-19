from fastapi import APIRouter, HTTPException, Response, Depends
from pydantic import BaseModel, EmailStr
from database import get_db
from auth import hash_pw, verify_pw, make_token, current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Creds(BaseModel):
    email: EmailStr
    password: str
    name: str | None = None


@router.post("/signup")
def signup(body: Creds, res: Response):
    with get_db() as db:
        if db.execute("SELECT 1 FROM users WHERE email=?", (body.email,)).fetchone():
            raise HTTPException(400, "Email already registered")
        db.execute(
            "INSERT INTO users (email,password,name) VALUES (?,?,?)",
            (body.email, hash_pw(body.password), body.name),
        )
        user = db.execute("SELECT * FROM users WHERE email=?", (body.email,)).fetchone()
    _set_cookie(res, user["id"], user["role"])
    return {"ok": True, "role": user["role"]}


@router.post("/login")
def login(body: Creds, res: Response):
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE email=?", (body.email,)).fetchone()
    if not user or not verify_pw(body.password, user["password"]):
        raise HTTPException(401, "Invalid credentials")
    if not user["is_active"]:
        raise HTTPException(403, "Account deactivated")
    _set_cookie(res, user["id"], user["role"])
    return {"ok": True, "role": user["role"]}


@router.get("/me")
def get_me(user=Depends(current_user)):
    with get_db() as db:
        uid = int(user["sub"])
        row = db.execute(
            "SELECT id, email, name, role FROM users WHERE id=?", (uid,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "User not found")
    # Derive plan from role
    role = row["role"] or "user"
    plan = "Pro" if role in ("admin", "pro") else "Free"
    return {
        "id": row["id"],
        "email": row["email"],
        "name": row["name"] or "",
        "plan": plan,
        "role": role,
    }


@router.post("/logout")
def logout(res: Response):
    res.delete_cookie("token")
    return {"ok": True}


@router.post("/forgot")
def forgot_password(body: Creds):
    with get_db() as db:
        user = db.execute(
            "SELECT id FROM users WHERE email=?", (body.email,)
        ).fetchone()
    if user:
        return {
            "ok": True,
            "message": "If the email exists, a reset link has been sent",
        }
    return {"ok": True, "message": "If the email exists, a reset link has been sent"}


def _set_cookie(res: Response, user_id: int, role: str):
    res.set_cookie(
        "token",
        make_token(user_id, role),
        httponly=True,
        samesite="lax",
        max_age=604800,
    )
