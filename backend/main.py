from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv
import json
from datetime import datetime

# Load environment variables from .env in the root project directory
load_dotenv(Path(__file__).parent.parent / ".env")

from database import init_db
from job_queue import start_worker
from routers.auth import router as auth_router
from routers.search import router as search_router
from routers.resume import router as resume_router
from routers.admin import router as admin_router

# Audit logging setup
AUDIT_LOG = Path(__file__).parent / "audit.log"


def log_audit(user_id: int, action: str, resource: str, details: dict | None = None):
    """Log user actions to audit log for security tracking."""
    try:
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "user_id": user_id,
            "action": action,
            "resource": resource,
            "details": details or {},
        }
        with open(AUDIT_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # Never let audit logging break the app


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    await start_worker()
    yield


app = FastAPI(title="JobSearch SaaS", lifespan=lifespan)

# Add CORS for SSE streaming support
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Add security headers to all responses."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains"
    )
    return response


app.include_router(auth_router)
app.include_router(search_router)
app.include_router(resume_router)
app.include_router(admin_router)

STATIC = Path(__file__).parent.parent / "frontend"


# Define ALL page routes BEFORE static mount
@app.get("/")
def root():
    return FileResponse(STATIC / "index.html")


# Auth routes
@app.get("/auth/login")
def login_page():
    return FileResponse(STATIC / "auth/login.html")


@app.get("/auth/signup")
def signup_page():
    return FileResponse(STATIC / "auth/signup.html")


@app.get("/auth/forgot")
def forgot_page():
    return FileResponse(STATIC / "auth/forgot.html")


@app.get("/auth/onboarding")
def onboarding_page():
    return FileResponse(STATIC / "auth/onboarding.html")


# User dashboard routes - search-jobs renamed from job-search
@app.get("/dashboard")
def dashboard():
    return FileResponse(STATIC / "dashboard/search-jobs.html")


@app.get("/dashboard/job-search")
def job_search_redirect():
    return RedirectResponse(url="/dashboard/search-jobs", status_code=301)


@app.get("/dashboard/search-jobs")
def search_jobs_page():
    return FileResponse(STATIC / "dashboard/search-jobs.html")


@app.get("/dashboard/resume")
def resume_page():
    return FileResponse(STATIC / "dashboard/resume.html")


@app.get("/dashboard/best-matches")
def best_matches_page():
    return FileResponse(STATIC / "dashboard/best-matches.html")


@app.get("/dashboard/insights")
def insights_page():
    return FileResponse(STATIC / "dashboard/insights.html")


@app.get("/dashboard/saved-jobs")
def saved_jobs_page():
    return FileResponse(STATIC / "dashboard/saved-jobs.html")


@app.get("/dashboard/settings")
def settings_page():
    return FileResponse(STATIC / "dashboard/settings.html")


# Admin routes
@app.get("/admin")
def admin_page():
    return FileResponse(STATIC / "admin/index.html")


@app.get("/admin/users")
def admin_users():
    return FileResponse(STATIC / "admin/users.html")


@app.get("/admin/searches")
def admin_searches():
    return FileResponse(STATIC / "admin/searches.html")


app.mount("/auth", StaticFiles(directory=STATIC / "auth", html=True), name="auth")
app.mount(
    "/dashboard",
    StaticFiles(directory=STATIC / "dashboard", html=True),
    name="dashboard",
)
app.mount(
    "/components",
    StaticFiles(directory=STATIC / "components", html=True),
    name="components",
)
app.mount("/admin", StaticFiles(directory=STATIC / "admin", html=True), name="admin")


# Catch-all routes for paths that don't exist - return 404 instead of index.html
# This fixes the issue where /jobs/, /job/, /browse-jobs were returning the dashboard


@app.get("/jobs/{job_path:path}")
def jobs_catch_all(job_path: str):
    from fastapi import HTTPException

    raise HTTPException(status_code=404, detail="Job page not found")


@app.get("/job/{job_path:path}")
def job_catch_all(job_path: str):
    from fastapi import HTTPException

    raise HTTPException(status_code=404, detail="Job page not found")


@app.get("/browse-jobs")
def browse_jobs_redirect():
    from fastapi import HTTPException

    raise HTTPException(status_code=404, detail="Browse jobs page not found")
