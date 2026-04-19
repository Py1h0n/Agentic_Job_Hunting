import os, time
import bcrypt
from typing import Optional
from jose import jwt, JWTError
from fastapi import HTTPException, Cookie

SECRET = os.getenv("SECRET_KEY", "change-me-in-production-please")
ALGO = "HS256"
TTL = 60 * 60 * 24 * 7  # 7 days


def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_pw(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except (ValueError, TypeError):
        return False


def make_token(user_id: int, role: str) -> str:
    return jwt.encode(
        {"sub": str(user_id), "role": role, "exp": int(time.time()) + TTL},
        SECRET,
        algorithm=ALGO,
    )


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET, algorithms=[ALGO])
    except JWTError:
        raise HTTPException(401, "Invalid or expired token")


def current_user(token: Optional[str] = Cookie(None)):
    if not token:
        raise HTTPException(401, "Not authenticated")
    return decode_token(token)


def admin_only(token: Optional[str] = Cookie(None)):
    payload = current_user(token)
    if payload.get("role") != "admin":
        raise HTTPException(403, "Admins only")
    return payload
