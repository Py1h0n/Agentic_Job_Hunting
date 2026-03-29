# JobScout — Setup Guide

## Project Structure
```
jobsearch/
├── backend/
│   ├── main.py              ← FastAPI app entry point
│   ├── database.py          ← SQLite + schema
│   ├── auth.py              ← JWT auth utilities
│   ├── queue.py             ← Async job queue (concurrency-limited)
│   ├── agents/
│   │   ├── __init__.py      ← Agent registry (add new agents here)
│   │   └── bdjobs_agent.py  ← BDJobs adapter (wraps agent_up.py)
│   └── routers/
│       ├── auth.py          ← /api/auth/*
│       ├── search.py        ← /api/search/*
│       └── admin.py         ← /api/admin/*
├── frontend/
│   ├── style.css            ← Shared design system
│   ├── index.html           ← Login / Signup
│   ├── dashboard.html       ← User dashboard
│   └── admin.html           ← Admin panel
├── requirements.txt
├── setup_admin.py           ← First-run admin creator
└── agent_up.py              ← YOUR existing agent (place here)
```

---

## Step 1 — Place your agent file

Copy your `agent_up.py` into the `jobsearch/` root directory (same level as `requirements.txt`).

---

## Step 2 — Create virtual environment

```bash
cd jobsearch
python -m venv venv

# Activate:
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate
```

---

## Step 3 — Install dependencies

```bash
# Site dependencies:
pip install -r requirements.txt

# Your agent dependencies (if not already installed):
pip install browser-use python-dotenv
```

---

## Step 4 — Environment variables (optional)

Create a `.env` file in the `jobsearch/` root:

```env
SECRET_KEY=your-very-long-random-secret-key-here
DB_PATH=jobsearch.db
MAX_CONCURRENT=3
OUTPUT_DIR=results

# Your agent's LLM keys:
NEBIUS_API_KEY=your_key
ZAI_BASE_URL=https://api.tokenfactory.nebius.com/v1/
ZAI_MODEL=openai/gpt-oss-20b
```

---

## Step 5 — Create admin account

```bash
python setup_admin.py
```

Enter your desired admin email and password. This only needs to run once.

---

## Step 6 — Start the server

```bash
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Open: http://localhost:8000

---

## Adding a New Agent (Microservice Pattern)

1. Create `backend/agents/mysite_agent.py`:
```python
NAME  = "mysite"
LABEL = "My Job Site"

async def run(query, location, max_jobs, search_id, user_id) -> dict:
    # your scraping logic
    return {"status": "success", "total": N, "jobs": [...]}
```

2. Register it in `backend/agents/__init__.py`:
```python
AGENTS = {
    "bdjobs": { ... },
    "mysite": { "label": "My Job Site", "module": "agents.mysite_agent" },
}
```

Done. It immediately appears in the UI dropdown. No other changes needed.

---

## API Reference

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | /api/auth/signup | — | Create account |
| POST | /api/auth/login | — | Login |
| POST | /api/auth/logout | — | Logout |
| GET | /api/search/agents | user | List available agents |
| POST | /api/search | user | Start a search |
| GET | /api/search/{id}/status | user | Poll search status |
| GET | /api/search/{id}/results | user | Get all jobs |
| GET | /api/search/history | user | Search history |
| POST | /api/search/jobs/{id}/save | user | Toggle saved |
| GET | /api/search/saved | user | Saved jobs list |
| GET | /api/admin/stats | admin | System stats |
| GET | /api/admin/users | admin | All users |
| GET | /api/admin/searches | admin | All searches |
| POST | /api/admin/users/{id}/toggle | admin | Activate/deactivate |
| POST | /api/admin/users/{id}/role | admin | Set user role |

---

## Upgrading to PostgreSQL (when ready)

Replace `database.py`'s `sqlite3` usage with `asyncpg` or `psycopg2`.
The SQL is standard — no SQLite-specific syntax is used.

Set `DATABASE_URL=postgresql://user:pass@localhost/jobsearch` in `.env`.
