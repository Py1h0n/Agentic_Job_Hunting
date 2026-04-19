import sqlite3, os
from contextlib import contextmanager
from pathlib import Path

# Always resolve DB path relative to this file (backend/database.py)
# so it lands in backend/jobsearch.db regardless of where you run from.
HERE = Path(__file__).parent
DB_PATH = Path(os.getenv("DB_PATH", str(HERE / "jobsearch.db")))

# Database schema version - increment when adding migrations
DB_VERSION = 11

# migrations: list of (version, sql_statements)
# Run migrations in order, safe to re-run (uses IF NOT EXISTS)
MIGRATIONS = [
    # Version 1: Initial schema
    (1, []),
    # Version 2: Add skills column to jobs (2026-04-10)
    (
        2,
        [
            "ALTER TABLE jobs ADD COLUMN skills TEXT",
        ],
    ),
    # Version 3: Add name column to users
    (
        3,
        [
            "ALTER TABLE users ADD COLUMN name TEXT",
        ],
    ),
    # Version 4: Add columns to jobs (warning: non-constant default fix in v5)
    (
        4,
        [
            "ALTER TABLE jobs ADD COLUMN match_score INTEGER DEFAULT 0",
        ],
    ),
    # Version 5: Ensure created_at exists (SQLite fix)
    (
        5,
        [
            "ALTER TABLE jobs ADD COLUMN created_at TEXT DEFAULT ''",
        ],
    ),
    # Version 6: Add detailed job metadata
    (
        6,
        [
            "ALTER TABLE jobs ADD COLUMN requirements TEXT",
            "ALTER TABLE jobs ADD COLUMN responsibilities TEXT",
            "ALTER TABLE jobs ADD COLUMN benefits TEXT",
            "ALTER TABLE jobs ADD COLUMN company_info TEXT",
            "ALTER TABLE jobs ADD COLUMN industry TEXT",
        ],
    ),
    # Version 7: Add search history columns
    (
        7,
        [
            "ALTER TABLE searches ADD COLUMN mode TEXT DEFAULT 'turbo'",
            "ALTER TABLE searches ADD COLUMN agents TEXT",
            "ALTER TABLE searches ADD COLUMN duration_ms INTEGER DEFAULT 0",
            "ALTER TABLE searches ADD COLUMN is_deleted INTEGER DEFAULT 0",
            "ALTER TABLE jobs ADD COLUMN source_agent TEXT",
            "ALTER TABLE jobs ADD COLUMN applied INTEGER DEFAULT 0",
            "ALTER TABLE jobs ADD COLUMN is_deleted INTEGER DEFAULT 0",
            "CREATE INDEX IF NOT EXISTS idx_searches_user_date ON searches(user_id, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_jobs_user_saved ON jobs(user_id, saved)",
        ],
    ),
    # Version 8: Add session_id to group multi-agent searches (2026-04-17)
    (
        8,
        [
            "ALTER TABLE searches ADD COLUMN session_id TEXT",
            "CREATE INDEX IF NOT EXISTS idx_searches_session ON searches(session_id)",
        ],
    ),
    # Version 9: Add education column to jobs (2026-04-19)
    (
        9,
        [
            "ALTER TABLE jobs ADD COLUMN education TEXT",
        ],
    ),
    # Version 10: Market pulse snapshots for WoW deltas (2026-04-19)
    (
        10,
        [
            "CREATE TABLE IF NOT EXISTS market_snapshots (id INTEGER PRIMARY KEY, period_start TEXT, period_end TEXT, created_at TEXT DEFAULT (datetime('now')))",
            "CREATE TABLE IF NOT EXISTS snapshot_items (snapshot_id INTEGER REFERENCES market_snapshots(id), item_type TEXT, item_name TEXT, job_count INTEGER, percentage REAL)",
        ],
    ),
    # Version 11: Enhanced resume structured fields (2026-04-20)
    (
        11,
        [
            "ALTER TABLE resumes ADD COLUMN title TEXT",
            "ALTER TABLE resumes ADD COLUMN companies TEXT",
            "ALTER TABLE resumes ADD COLUMN achievements TEXT",
            "ALTER TABLE resumes ADD COLUMN certifications TEXT",
            "ALTER TABLE resumes ADD COLUMN languages TEXT",
            "ALTER TABLE resumes ADD COLUMN soft_skills TEXT",
            "ALTER TABLE resumes ADD COLUMN tools TEXT",
            "ALTER TABLE resumes ADD COLUMN location TEXT",
            "ALTER TABLE resumes ADD COLUMN desired_role TEXT",
            "ALTER TABLE resumes ADD COLUMN salary_range TEXT",
            "ALTER TABLE resumes ADD COLUMN enhanced_data TEXT",
        ],
    ),
]

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
    session_id  TEXT,
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
    skills      TEXT,
    saved       INTEGER NOT NULL DEFAULT 0,
    requirements TEXT,
    responsibilities TEXT,
    benefits TEXT,
    company_info TEXT,
    industry TEXT,
    education TEXT
);

CREATE TABLE IF NOT EXISTS resumes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    filename       TEXT,
    file_type      TEXT,
    file_path     TEXT,
    extracted_text TEXT,
    skills       TEXT,
    experience   TEXT,
    education    TEXT,
    summary      TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT
);

CREATE TABLE IF NOT EXISTS applied_jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    job_id      INTEGER NOT NULL REFERENCES jobs(id),
    applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS db_meta (
    key         TEXT PRIMARY KEY,
    value       TEXT
);

CREATE INDEX IF NOT EXISTS idx_resumes_user ON resumes(user_id);
CREATE INDEX IF NOT EXISTS idx_searches_user ON searches(user_id);
CREATE INDEX IF NOT EXISTS idx_jobs_search   ON jobs(search_id);
CREATE INDEX IF NOT EXISTS idx_jobs_user     ON jobs(user_id);
"""


def init_db():
    """Initialize database with schema and run migrations."""
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row  # Enable dict-like access

        # Create base schema
        con.executescript(SCHEMA)

        # Get current version
        cur = con.execute("SELECT value FROM db_meta WHERE key='version'").fetchone()
        current_version = int(cur["value"]) if cur else 0

        # Run migrations
        if current_version < DB_VERSION:
            print(f"[db] Running migrations {current_version} -> {DB_VERSION}")
            for version, sqls in MIGRATIONS:
                if version > current_version:
                    for sql in sqls:
                        try:
                            con.execute(sql)
                        except Exception as e:
                            # Ignore if column/table already exists
                            if "already exists" not in str(e).lower():
                                print(f"[db] Migration {version} warning: {e}")
                    con.execute(
                        "INSERT OR REPLACE INTO db_meta (key, value) VALUES ('version', ?)",
                        (str(version),),
                    )
            con.commit()
            print(f"[db] Migration complete: v{DB_VERSION}")


def get_column(row, key, default=None):
    """Safely get a column from a sqlite3.Row or dict."""
    if row is None:
        return default
    # sqlite3.Row supports both index and key access
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


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


def save_jobs_to_db(search_id: int, user_id: int, jobs: list[dict]):
    """
    Safely saves a list of jobs to the database incrementally.
    Handles duplicate prevention based on URL within the same search.
    """
    if not jobs:
        return 0

    added = 0
    with get_db() as db:
        # Get session_id to deduplicate across the entire search session (all agents)
        row = db.execute(
            "SELECT session_id FROM searches WHERE id=?", (search_id,)
        ).fetchone()
        session_id = row["session_id"] if row else None

        # Get existing URLs for this search session to avoid duplicates
        if session_id:
            existing_urls = {
                row["url"]
                for row in db.execute(
                    "SELECT j.url FROM jobs j JOIN searches s ON j.search_id = s.id WHERE s.session_id=?",
                    (session_id,),
                ).fetchall()
                if row["url"]
            }
        else:
            existing_urls = {
                row["url"]
                for row in db.execute(
                    "SELECT url FROM jobs WHERE search_id=?", (search_id,)
                ).fetchall()
                if row["url"]
            }

        to_insert = []
        for j in jobs:
            url = j.get("url", "")
            if url and url in existing_urls:
                continue

            # Initialize match_score to 0. Real matching happens on-demand via AI.
            score = j.get("match_score")
            if score is None:
                score = 0

            to_insert.append(
                (
                    search_id,
                    user_id,
                    j.get("title", ""),
                    j.get("company", ""),
                    j.get("location", ""),
                    j.get("deadline", ""),
                    j.get("job_type", ""),
                    j.get("salary", ""),
                    j.get("experience", ""),
                    j.get("url", ""),
                    j.get("skills", ""),
                    score,
                    j.get("requirements", ""),
                    j.get("responsibilities", ""),
                    j.get("benefits", ""),
                    j.get("company_info", ""),
                    j.get("industry", ""),
                    j.get("education", ""),
                )
            )
            if url:
                existing_urls.add(url)
            added += 1

        if to_insert:
            db.executemany(
                """INSERT INTO jobs (search_id,user_id,title,company,location,
                   deadline,job_type,salary,experience,url,skills,match_score,
                   requirements, responsibilities, benefits, company_info, industry, education)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                to_insert,
            )
            # CRITICAL: Update search status count so frontend can "showcase" immediately
            db.execute(
                "UPDATE searches SET total_found = total_found + ? WHERE id = ?",
                (added, search_id),
            )

            # Update the search total_found count
            db.execute(
                "UPDATE searches SET total_found = (SELECT COUNT(*) FROM jobs WHERE search_id=?) WHERE id=?",
                (search_id, search_id),
            )
    return added


def cleanup_broken_urls():
    """
    Delete jobs with broken URLs (search anchors, browse pages).
    This cleans up existing data from the broken URL extraction bug.
    """
    with get_db() as db:
        # Delete jobs with browse-jobs URLs or anchor links
        cursor = db.execute("""
            DELETE FROM jobs
            WHERE url LIKE '%browse-jobs%'
            OR url LIKE '%#job-%'
            OR url = '#'
            OR url = ''
        """)
        deleted = cursor.rowcount
        if deleted > 0:
            print(f"[db] Cleaned up {deleted} jobs with broken URLs")
        return deleted
