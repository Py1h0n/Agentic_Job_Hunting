# Technical Map: The Curator Platform

This document serves as the primary reference for AI agents and developers to understand the system architecture, component relationships, and safety guidelines for the "The Curator" platform.

## 🏗️ Core Architecture

### 1. Model Standardization (Nebius AI)
We use the Nebius AI platform for all LLM operations. Configuration is centralized in the project root `.env` file.

- **Agentic Work (Scraping/Discovery)**: `NEBIUS_AGENT_MODEL` (Default: `Qwen/Qwen3-235B-A22B-Instruct-2507`). Use this for browser-based tasks requiring complex reasoning.
- **Resume Analysis & Matching**: `NEBIUS_RESUME_MODEL` (Default: `google/gemma-3-27b-it`). Optimized for structured data extraction and scoring.
- **Fast Vision**: `NEBIUS_RESUME_MODEL` can also be set to `google/gemma-3-27b-it-fast` for 2x speed.

### 2. Search Modes
- **Turbo**: Searches only `bdjobs` (vision-based scraper). Fastest, single source.
- **Standard**: Searches `skilljobs` and `jobmedia`. Balanced coverage.
- **Deep**: Searches all 6 engines (`bdjobs`, `skilljobs`, `jobmedia`, `nextjobz`, `niyog`, `atb`). Maximum coverage.

### 3. Insights Page (Career Command Center)
- **Flow**: User visits `/dashboard/insights` → sees empty state (`--`) → clicks "Analyze with AI" → gets personalized analysis
- **Analyzed Data**: Only `saved=1` jobs from user's saved jobs
- **API Endpoints**:
  - `/api/search/insights` - Basic aggregation of saved jobs (skills, salary, locations, etc.)
  - `/api/resume/insights` - Resume-based match analysis
  - `/api/search/analyze` - AI-powered career insights (via Nebius LLM)
- **Display Sections**:
  - Metrics: Total Saved, Avg Match, Top Demand
  - Skill Radar Chart: Market demand vs user skills
  - Market Clusters ("Where Do I Fit?"): Strong Match, Developing, Entry Level, High Potential
  - Bridge the Gap: Missing skills with pivot strategies

## 📊 Database Relationships (SQLite)

### Table: `jobs`
- **`id`**: Primary Key
- **`search_id`**: Links to `searches.id`
- **`user_id`**: Ownership marker
- **`saved`**: (INTEGER 0/1) Tracks if the user bookmarked the job.
- **`applied`**: (INTEGER 0/1) Tracks if the user marked it as applied.
- **Metadata**: `requirements`, `responsibilities`, `benefits`, `skills`, `match_score`.

### Table: `searches`
- **`agents`**: Comma-separated list of agents used in this search session.
- **`mode`**: `turbo`, `standard`, or `deep`.

## 🔄 Feature Connections

### Search Flow
1. **Trigger**: `job-search.html` calls `/api/search/start`.
2. **Execution**: `job_queue.py` picks up tasks; `bdjobs_scraper.py` or legacy agents run.
3. **Streaming**: Real-time progress is sent via SSE (`/api/search/stream/{sid}`).
4. **Storage**: Agents save results to `jobs` table.

### Scoring & Matching Flow
- **Resume Upload**: `resume.html` uploads to `/api/resume/upload`.
- **Analysis**: `resume.py` uses `NEBIUS_RESUME_MODEL` to extract skills/experience.
- **Matching**: `best-matches.html` calls `/api/resume/top-jobs` which performs AI-driven scoring.

### Insights Flow
- **Initial**: Page loads with empty metrics (`--`)
- **User Action**: Click "Analyze with AI" button
- **Processing**: Fetches saved jobs, runs AI analysis
- **Display**: Shows metrics, charts, market clusters based on saved job data

## 🛡️ Safety Guidelines

> [!CAUTION]
> **Database Migrations**: When adding columns, update `DB_VERSION` in `database.py` and add the SQL to the `MIGRATIONS` list.
> **Route Changes**: Dashboard routes are defined in `main.py`. Ensure any new HTML page has a corresponding `FileResponse` route.
> **Environment**: Never hardcode API keys. All model names must use `os.getenv` with the standardized keys.

## 🚀 Active Roadmap
- Save job functionality across Search and Saved Job portals.
- AI-powered career insights with visual skill gap analysis.
- Market cluster visualization (Where Do I Fit?)

## 🐛 Bug Fixes Log

### 2025-04-xx: Insights Page Fixes
1. **Empty state on load**: Page now shows `--` until user clicks "Analyze with AI" button
2. **AI analyze button**: Added proper onclick handler and analyzing animation
3. **Match score fix**: Jobs without AI match_score now get default score of 55 for cluster calculation
4. **Market clusters**: Added "High Potential" (90%+) cluster to match frontend
5. **Debug info**: Added user_id, score_count in API response for verification

### Key Files Modified
- `frontend/dashboard/insights.html` - Analyze button, showNoData(), animation
- `backend/routers/search.py` - /insights endpoint (match_score default), /analyze endpoint
- `backend/routers/resume.py` - /insights endpoint (saved=1 filter)
