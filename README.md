# The Curator - AI Executive Job Search Platform

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12+-blue?style=flat&logo=python" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-0.115+-blue?style=flat&logo=fastapi" alt="FastAPI">
  <img src="https://img.shields.io/badge/License-MIT-green?style=flat" alt="License">
</p>

An intelligent job search platform with AI-powered resume analysis, job matching, and career insights designed specifically for the Bangladesh job market and beyond.

## Table of Contents

1. [Overview](#overview)
2. [Features](#features)
3. [Technology Stack](#technology-stack)
4. [Project Structure](#project-structure)
5. [Getting Started](#getting-started)
6. [Configuration](#configuration)
7. [API Documentation](#api-documentation)
8. [Frontend Pages](#frontend-pages)
9. [Job Scraping Agents](#job-scraping-agents)
10. [AI Features](#ai-features)
11. [Database Schema](#database-schema)
12. [Deployment](#deployment)
13. [Environment Variables](#environment-variables)
14. [Troubleshooting](#troubleshooting)
15. [License](#license)

---

## Overview

**The Curator** is a full-stack job search SaaS platform that connects job seekers with opportunities in the Bangladesh market and internationally. The platform uses AI agents to scrape job listings from multiple sources, analyzes user resumes, and provides personalized career insights.

### Key Highlights

- 🚀 **Multi-Source Job Aggregation** - Scrapes jobs from 4+ Bangladesh job sites
- 🤖 **AI-Powered Resume Analysis** - Extracts skills, experience, and career level
- 📊 **Smart Job Matching** - Match percentage based on resume-job alignment
- 💡 **Career Insights** - AI-generated career guidance with salary data
- 🔒 **Secure Authentication** - JWT-based auth with bcrypt password hashing
- 📱 **Responsive Design** - Works on desktop and mobile devices

---

## Features

### For Job Seekers

| Feature | Description |
|---------|-------------|
| **Smart Job Search** | Search jobs by title, skills, location with AI-powered result ranking |
| **Multi-Mode Search** | Turbo (fast), Standard (balanced), Deep (comprehensive) search modes |
| **Resume Upload** | Upload resume (PDF, DOC, DOCX, JPG, PNG) for AI analysis |
| **Resume Parsing** | AI extracts name, email, phone, skills, experience, career level |
| **Job Matching** | Get match percentage showing how well jobs align with your resume |
| **Best Matches** | AI automatically ranks and suggests best matching jobs |
| **Career Insights** | Personalized AI insights with salary ranges in BDT |
| **Save Jobs** | Bookmark jobs for later viewing |
| **Search History** | View and manage past job searches |
| **Job Alerts** | Stay updated with new job postings |

### For Administrators

| Feature | Description |
|---------|-------------|
| **User Management** | View and manage platform users |
| **Search Monitoring** | Monitor active job searches and agent status |
| **Analytics Dashboard** | View platform statistics and usage metrics |
| **Job Queue Control** | Control concurrent job scraping tasks |

---

## Technology Stack

### Backend

| Technology | Version | Purpose |
|-------------|---------|---------|
| **Python** | 3.12+ | Core programming language |
| **FastAPI** | 0.115+ | Web framework |
| **Uvicorn** | 0.31+ | ASGI server |
| **SQLite** | - | Database (file-based) |
| **Pydantic** | 2.9+ | Data validation |
| **python-jose** | 3.3.0 | JWT token handling |
| **bcrypt** | 4.0.0+ | Password hashing |

### AI & Automation

| Technology | Version | Purpose |
|-------------|---------|---------|
| **Nebius AI** | - | LLM API (Qwen, Gemma models) |
| **browser-use** | 0.12.5 | Browser automation framework |
| **Playwright** | - | Browser driver for scraping |

### Frontend

| Technology | Purpose |
|-------------|---------|
| **HTML5** | Semantic markup |
| **Tailwind CSS** | Utility-first CSS framework |
| **Vanilla JavaScript** | Client-side logic |
| **Material Symbols** | Icon library |

---

## Project Structure

```
the-curator/
│
├── backend/
│   │
│   ├── agents/                    # AI Job Scraping Agents
│   │   ├── __init__.py           # Agent registry
│   │   ├── base_agent.py         # Base agent class
│   │   ├── bdjobs_agent.py      # bdjobs.com scraper
│   │   ├── bdtechjobs_agent.py  # bdtechjobs.com scraper
│   │   ├── skilljobs_agent.py  # skilljobs.com.bd scraper
│   │   ├── jobmedia_agent.py   # jobmedia.com scraper
│   │   ├── niyog_agent.py     # niyog.com scraper
│   │   └── schemas.py         # Agent schemas
│   │
│   ├── resumes/                  # User resume storage
│   │   └── (user resume files)
│   │
│   ├── routers/                   # API Route handlers
│   │   ├── auth.py              # Authentication endpoints
│   │   ├── search.py            # Job search endpoints
│   │   ├── resume.py            # Resume endpoints
│   │   └── admin.py             # Admin endpoints
│   │
│   ├── auth.py                   # Auth utilities (JWT, current_user)
│   ├── database.py              # Database setup & migrations
│   ├── job_queue.py            # Background job queue worker
│   ├── main.py                 # FastAPI application
│   ├── run.py                  # Server startup script
│   └── jobsearch.db            # SQLite database
│
├── frontend/
│   │
│   ├── admin/                    # Admin dashboard pages
│   │   ├── index.html          # Admin home
│   │   ├── users.html          # User management
│   │   └── searches.html       # Search monitoring
│   │
│   ├── auth/                     # Authentication pages
│   │   ├── login.html          # Login page
│   │   ├── signup.html         # Registration page
│   │   ├── forgot.html        # Password reset
│   │   └── onboarding.html    # Resume upload wizard
│   │
│   ├── components/              # Reusable components
│   │   ├── header.html         # Navigation header
│   │   ├── sidebar.html       # Dashboard sidebar
│   │   └── footer.html       # Page footer
│   │
│   ├── dashboard/               # User dashboard pages
│   │   ├── search-jobs.html    # Job search page
│   │   ├── best-matches.html  # AI-matched jobs
│   │   ├── insights.html      # Career insights
│   │   ├── resume.html        # Resume management
│   │   ├── saved-jobs.html   # Saved job listings
│   │   └── settings.html     # User settings
│   │
│   └── index.html              # Landing page
│
├── .env                        # Environment variables (local)
├── .env.example               # Environment template
├── .gitignore                 # Git ignore rules
├── railway.json               # Railway deployment config
├── requirements.txt          # Python dependencies
└── README.md                  # This file
```

---

## Getting Started

### Prerequisites

- **Python 3.12** or higher
- **Playwright** (for browser automation in AI agents)
- **pip** (Python package manager)

### Step 1: Clone and Navigate

```bash
git clone <repository-url>
cd the-curator
```

### Step 2: Create Virtual Environment

```bash
# Linux/macOS
python -m venv venv
source venv/bin/activate

# Windows
python -m venv venv
venv\Scripts\activate
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Install Playwright Browsers

```bash
playwright install chromium
```

### Step 5: Configure Environment

Copy the example environment file:

```bash
cp .env.example .env
```

Edit `.env` and add your configuration (see [Configuration](#configuration) below).

### Step 6: Run the Server

```bash
cd backend
python run.py
```

The application will start at: **http://localhost:8000**

### Step 7: Access the Platform

| Page | URL |
|------|-----|
| Landing | http://localhost:8000 |
| Login | http://localhost:8000/auth/login |
| Signup | http://localhost:8000/auth/signup |
| Dashboard | http://localhost:8000/dashboard |
| Admin | http://localhost:8000/admin |

---

## Configuration

### .env File Structure

Create a `.env` file in the project root:

```env
# ── Security ─────────────────────────────────────────────────────────────
SECRET_KEY=your-very-long-random-secret-key-change-this

# ── Database ─────────────────────────────────────────────────────────────
DB_PATH=jobsearch.db

# ── Job Queue ────────────────────────────────────────────────────────
MAX_CONCURRENT=3
OUTPUT_DIR=results

# ── AI Configuration (Nebius) ─────────────────────────────────────
NEBIUS_API_KEY=your-nebius-api-key-here

# AI Model for Job Scraping Agents
NEBIUS_AGENT_MODEL=Qwen/Qwen3-235B-A22B-Instruct-2507

# AI Model for Resume Analysis
NEBIUS_RESUME_MODEL=google/gemma-3-27b-it
```

### Generate a Secure SECRET_KEY

```bash
# Using Python
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## API Documentation

### Authentication Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register` | User registration |
| POST | `/api/auth/login` | User login (returns JWT) |
| GET | `/api/auth/me` | Get current user info |
| POST | `/api/auth/logout` | User logout |
| POST | `/api/auth/forgot` | Request password reset |
| POST | `/api/auth/reset` | Reset password |

#### Login Request
```json
{
  "email": "user@example.com",
  "password": "your-password"
}
```

#### Login Response
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "user": {
    "id": 1,
    "email": "user@example.com",
    "name": "John Doe"
  }
}
```

### Job Search Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/search` | Search jobs |
| POST | `/api/search` | Create new job search |
| GET | `/api/search/history` | Get search history |
| GET | `/api/search/saved` | Get saved jobs |
| POST | `/api/search/save` | Save a job |
| DELETE | `/api/search/unsave` | Unsave a job |
| GET | `/api/search/agents` | List available agents |
| GET | `/api/search/agents/status` | Get agent status |

#### Search Request
```json
{
  "query": "python developer",
  "location": "dhaka",
  "max_jobs": 30,
  "mode": "turbo"  // "turbo" | "standard" | "deep"
}
```

### Resume Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/resume/upload` | Upload resume file |
| GET | `/api/resume/status` | Get resume status |
| GET | `/api/resume/insights` | Get AI career insights |
| POST | `/api/resume/analyze` | Analyze resume text |
| GET | `/api/resume/match` | Get job match analysis |

### Admin Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/admin/users` | List all users |
| GET | `/api/admin/searches` | List all searches |
| GET | `/api/admin/stats` | Get platform statistics |

---

## Frontend Pages

### Landing Page (`/`)
- Hero section with value proposition
- Feature highlights
- Call-to-action buttons (Login/Signup)

### Auth Pages (`/auth/`)
- **login.html** - User login form
- **signup.html** - User registration form
- **forgot.html** - Password recovery
- **onboarding.html** - Resume upload after signup

### User Dashboard (`/dashboard/`)
- **search-jobs.html** - Job search with filters
- **best-matches.html** - AI-ranked best matching jobs
- **insights.html** - Career insights with AI
- **resume.html** - Resume upload and management
- **saved-jobs.html** - Bookmarked jobs
- **settings.html** - Account settings

### Admin Dashboard (`/admin/`)
- **index.html** - Admin overview
- **users.html** - User management
- **searches.html** - Search monitoring

---

## Job Scraping Agents

The platform uses multiple AI agents to scrape job listings from Bangladesh job sites:

### Available Agents

| Agent | Source | Mode Support |
|-------|--------|------------|
| `bdjobs` | bdjobs.com | Turbo, Standard, Deep |
| `bdtechjobs` | bdtechjobs.com | Standard, Deep |
| `skilljobs` | skilljobs.com.bd | Standard, Deep |
| `jobmedia` | jobmedia.com | Deep |
| `niyog` | niyog.com | Deep |

### Search Modes

| Mode | Agents Used | Speed | Results |
|------|-----------|-------|---------|
| **Turbo** | bdjobs only | Fastest | Limited |
| **Standard** | 3 parallel | Balanced | Good |
| **Deep** | 4 sources | Slower | Comprehensive |

### Agent Architecture

Each agent:
1. Uses Playwright to navigate the job site
2. Extracts job listings (title, company, location, salary, requirements)
3. Returns structured JSON data
4. Stores in database for user access

---

## AI Features

### Resume Analysis

The AI resume analyzer (`google/gemma-3-27b-it`) extracts:

```json
{
  "name": "Candidate Name",
  "email": "email@example.com",
  "phone": "+880-1234567890",
  "location": "Dhaka, Bangladesh",
  "title": "Software Engineer",
  "desired_role": "Senior Engineer",
  "experience": "5+ years",
  "career_level": "senior",
  "skills": ["Python", "JavaScript", "AWS"],
  "soft_skills": ["Leadership", "Communication"],
  "tools": ["Docker", "Git", "Jenkins"],
  "certifications": ["AWS Solutions Architect"],
  "companies": [...],
  "achievements": [...],
  "education": [...],
  "summary": "Professional summary..."
}
```

### Career Insights

AI generates personalized insights including:

- **Recommended Roles** - Best matching job titles
- **Strengths** - Skills that match market demand
- **Market Value** - Position in Bangladesh market
- **Growth Opportunities** - Skills to learn
- **Salary Insights** - BDT salary ranges by experience
- **Next Steps** - Actionable career advice
- **Competitive Advantages** - What makes you stand out
- **Areas for Improvement** - Skill gaps to close

### Job Matching

The AI calculates match percentage based on:
- Skills overlap between resume and job requirements
- Experience level alignment
- Career level matching

---

## Database Schema

### Key Tables

#### users
```sql
CREATE TABLE users (
  id INTEGER PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  password TEXT NOT NULL,
  name TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

#### resumes
```sql
CREATE TABLE resumes (
  id INTEGER PRIMARY KEY,
  user_id INTEGER REFERENCES users(id),
  filename TEXT,
  skills TEXT,  -- JSON array
  soft_skills TEXT,
  tools TEXT,
  experience TEXT,
  career_level TEXT,
  parsed_data TEXT,  -- JSON object
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

#### jobs
```sql
CREATE TABLE jobs (
  id INTEGER PRIMARY KEY,
  user_id INTEGER REFERENCES users(id),
  search_id INTEGER REFERENCES searches(id),
  title TEXT,
  company TEXT,
  location TEXT,
  salary TEXT,
  type TEXT,
  description TEXT,
  requirements TEXT,
  apply_link TEXT,
  skills TEXT,  -- Extracted skills
  match_score REAL,
  saved INTEGER DEFAULT 0,
  is_deleted INTEGER DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

#### searches
```sql
CREATE TABLE searches (
  id INTEGER PRIMARY KEY,
  user_id INTEGER REFERENCES users(id),
  agent TEXT,
  query TEXT,
  location TEXT,
  total_found INTEGER DEFAULT 0,
  status TEXT DEFAULT 'running',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  finished_at TEXT
);
```

---

## Deployment

### Railway (Recommended)

1. **Connect Repository**
   - Push code to GitHub
   - Connect GitHub repo to Railway

2. **Configure Environment**
   - Add variables in Railway dashboard:
     - `SECRET_KEY`
     - `NEBIUS_API_KEY`
     - `NEBIUS_AGENT_MODEL`
     - `NEBIUS_RESUME_MODEL`

3. **Deploy**
   - Railway automatically detects Python and runs `pip install -r requirements.txt`
   - Starts server using `start.sh`

### Manual Deployment

```bash
# Build
pip install -r requirements.txt
playwright install chromium

# Run
cd backend
python run.py
```

### Start Script (`start.sh`)

```bash
#!/bin/bash
cd backend
python run.py
```

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SECRET_KEY` | Yes | - | JWT signing key (generate random string) |
| `DB_PATH` | No | `jobsearch.db` | Database file path |
| `MAX_CONCURRENT` | No | 3 | Max concurrent job searches |
| `OUTPUT_DIR` | No | `results` | Job output directory |
| `NEBIUS_API_KEY` | Yes | - | Nebius AI API key |
| `NEBIUS_AGENT_MODEL` | No | `Qwen/Qwen3-235B-A22B-Instruct-2507` | Agent model |
| `NEBIUS_RESUME_MODEL` | No | `google/gemma-3-27b-it` | Resume model |
| `RESUME_DIR` | No | `backend/resumes` | Resume storage directory |

---

## Troubleshooting

### Common Issues

#### "NEBIUS_API_KEY not found"
- Add your Nebius API key to `.env` file
- Ensure `.env` is in project root

#### "Playwright browser not found"
```bash
playwright install chromium
```

#### "Database migration error"
- Delete `jobsearch.db` and restart (will auto-migrate)

#### "CORS error"
- Already configured for all origins in `main.py`

### Get Help

- Check console logs for error messages
- Verify all environment variables are set
- Ensure Python 3.12+ is used

---

## License

This project is licensed under the **MIT License**.

---

## Acknowledgments

- [Nebius AI](https://nebius.ai) - AI model provider
- [browser-use](https://github.com/browser-use/browser-use) - Browser automation
- [Tailwind CSS](https://tailwindcss.com) - CSS framework
- All Bangladesh job sites used for scraping

---

<p align="center">Built with ❤️ for the Bangladesh tech community</p>