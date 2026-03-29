from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, EmailStr
from database import get_db
from auth import hash_pw, verify_pw, make_token

router = APIRouter(prefix="/api/auth", tags=["auth"])

class Creds(BaseModel):
    email: EmailStr
    password: str

@router.post("/signup")
def signup(body: Creds, res: Response):
    with get_db() as db:
        if db.execute("SELECT 1 FROM users WHERE email=?", (body.email,)).fetchone():
            raise HTTPException(400, "Email already registered")
        db.execute("INSERT INTO users (email,password) VALUES (?,?)",
                   (body.email, hash_pw(body.password)))
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

@router.post("/logout")
def logout(res: Response):
    res.delete_cookie("token")
    return {"ok": True}

def _set_cookie(res: Response, user_id: int, role: str):
    res.set_cookie("token", make_token(user_id, role),
                   httponly=True, samesite="lax", max_age=604800)
