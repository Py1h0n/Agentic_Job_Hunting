#!/usr/bin/env python3
"""Run once to create the first admin account."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from database import init_db, get_db
from auth import hash_pw

def main():
    init_db()
    email = input("Admin email: ").strip()
    pw    = input("Admin password: ").strip()
    if not email or not pw:
        print("Email and password required."); sys.exit(1)
    with get_db() as db:
        exists = db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone()
        if exists:
            db.execute("UPDATE users SET role='admin', password=? WHERE email=?", (hash_pw(pw), email))
            print(f"Updated existing user {email} → admin")
        else:
            db.execute("INSERT INTO users (email,password,role) VALUES (?,?,?)", (email, hash_pw(pw), "admin"))
            print(f"Created admin: {email}")

if __name__ == "__main__":
    main()
