import sqlite3, os
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.getenv("DB_PATH", "jobsearch.db"))

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT UNIQUE NOT NULL,
    password    TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'user',
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS searches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    agent       TEXT NOT NULL DEFAULT 'bdjobs',
    query       TEXT NOT NULL,
    location    TEXT NOT NULL DEFAULT '',
    max_jobs    INTEGER NOT NULL DEFAULT 50,
    status      TEXT NOT NULL DEFAULT 'queued',
    total_found INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id   INTEGER NOT NULL REFERENCES searches(id),
    user_id     INTEGER NOT NULL REFERENCES users(id),
    title       TEXT,
    company     TEXT,
    location    TEXT,
    deadline    TEXT,
    job_type    TEXT,
    salary      TEXT,
    experience  TEXT,
    url         TEXT,
    saved       INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_searches_user ON searches(user_id);
CREATE INDEX IF NOT EXISTS idx_jobs_search   ON jobs(search_id);
CREATE INDEX IF NOT EXISTS idx_jobs_user     ON jobs(user_id);
"""

def init_db():
    with sqlite3.connect(DB_PATH) as con:
        con.executescript(SCHEMA)

@contextmanager
def get_db():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
