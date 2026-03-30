# JobScout — Setup Guide

## Project Structure
```
jobsearch/
├── backend/
│   ├── main.py              ← FastAPI app entry point
│   ├── database.py          ← SQLite schema + connection
│   ├── auth.py              ← JWT + bcrypt utilities
│   ├── job_queue.py         ← Async job queue (concurrency-limited)
│   ├── run.py               ← Server launcher (use instead of uvicorn directly)
│   ├── agents/
│   │   ├── __init__.py      ← Agent registry (add new agents here)
│   │   └── bdjobs_agent.py  ← BDJobs agent (full isolated implementation)
│   └── routers/
│       ├── auth.py          ← /api/auth/*
│       ├── search.py        ← /api/search/*
│       └── admin.py         ← /api/admin/*
├── frontend/
│   ├── style.css            ← Shared design system
│   ├── index.html           ← Login / Signup
│   ├── dashboard.html       ← User dashboard
│   └── admin.html           ← Admin panel
├── results/                 ← Agent output JSON files (auto-created)
├── requirements.txt
└── setup_admin.py           ← Run once to create first admin account
```

---

## Step 1 — Install Python 3.12

**Python 3.12 is required.** Python 3.13+ breaks subprocess support inside uvicorn
on Windows, which prevents the browser agent from launching.

Download: https://www.python.org/downloads/release/python-3120/

Verify you are on 3.12:
```bash
python --version
# Should print: Python 3.12.x
```

---

## Step 2 — Create virtual environment

```bash
cd jobsearch
python -m venv venv

# Activate — Windows:
venv\Scripts\activate

# Activate — Mac/Linux:
source venv/bin/activate
```

---

## Step 3 — Install all dependencies

```bash
pip install -r requirements.txt
```

Then install the Chromium browser binary that the agent uses:
```bash
playwright install chromium
```

This second command is required. `pip install playwright` only installs the
Python wrapper — `playwright install chromium` downloads the actual browser.

---

## Step 4 — Create `.env` file

Create a `.env` file inside the `backend/` folder:

```env
SECRET_KEY=your-very-long-random-secret-key-here
MAX_CONCURRENT=3
OUTPUT_DIR=results

# LLM keys for the agent:
NEBIUS_API_KEY=your_key_here
ZAI_BASE_URL=https://api.tokenfactory.nebius.com/v1/
ZAI_MODEL=openai/gpt-oss-20b
```

`SECRET_KEY` — any long random string, used to sign JWT tokens.
`MAX_CONCURRENT` — max simultaneous agent runs (default 3).
`OUTPUT_DIR` — where agent saves JSON result files.

---

## Step 5 — Create admin account

Run this from the project root (not from inside backend/):
```bash
python setup_admin.py
```

Enter your admin email and password when prompted.
This only needs to run once. The DB is created automatically at `backend/jobsearch.db`.

---

## Step 6 — Start the server

```bash
cd backend
python run.py
```

Open: http://localhost:8000

**Do not use** `uvicorn main:app --reload` directly on Windows — the `--reload`
flag spawns a child process that resets the event loop to SelectorEventLoop,
which breaks the browser agent. `run.py` starts uvicorn correctly without reload.

When you change code, press Ctrl+C and run `python run.py` again.

---

## Adding a New Agent (Microservice Pattern)

1. Create `backend/agents/mysite_agent.py`:
```python
NAME  = "mysite"
LABEL = "My Job Site"

async def run(query: str, location: str, max_jobs: int,
              search_id: int, user_id: int) -> dict:
    # your scraping logic here
    return {
        "status": "success",
        "total": len(jobs),
        "jobs": jobs   # list of dicts with: title, company, location,
                       # deadline, job_type, salary, experience, url
    }
```

2. Register it in `backend/agents/__init__.py`:
```python
AGENTS = {
    "bdjobs": { "label": "BDJobs", "module": "agents.bdjobs_agent" },
    "mysite": { "label": "My Job Site", "module": "agents.mysite_agent" },
}
```

Done. It immediately appears in the UI source dropdown. No other changes needed.

---

## API Reference

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | /api/auth/signup | — | Create account |
| POST | /api/auth/login | — | Login |
| POST | /api/auth/logout | — | Logout |
| GET | /api/search/agents | user | List available agents |
| GET | /api/search/history | user | Search history |
| GET | /api/search/saved | user | Saved jobs list |
| POST | /api/search | user | Start a search |
| GET | /api/search/{id}/status | user | Poll search status |
| GET | /api/search/{id}/results | user | Get all jobs |
| POST | /api/search/jobs/{id}/save | user | Toggle saved |
| GET | /api/admin/stats | admin | System stats |
| GET | /api/admin/users | admin | All users |
| GET | /api/admin/searches | admin | All searches |
| POST | /api/admin/users/{id}/toggle | admin | Activate/deactivate user |
| POST | /api/admin/users/{id}/role | admin | Set user role |

---

## Common Problems

| Problem | Fix |
|---------|-----|
| `NotImplementedError` on search | You used `uvicorn --reload`. Use `python run.py` instead |
| `playwright` browser not found | Run `playwright install chromium` |
| Admin login fails after setup | You ran `setup_admin.py` from wrong folder — DB mismatch. Delete `jobsearch.db` and re-run from project root |
| `bcrypt` / `passlib` error | Old install. Run `pip install -r requirements.txt` again |
| `pydantic-core` Rust compile error | You are on Python 3.13+. Install Python 3.12 |

---

## Upgrading to PostgreSQL (when ready)

Replace `database.py`'s `sqlite3` with `psycopg2` or `asyncpg`.
All SQL is standard — no SQLite-specific syntax used.