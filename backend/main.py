from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from pathlib import Path

from database import init_db
from job_queue import start_worker
from routers.auth import router as auth_router
from routers.search import router as search_router
from routers.admin import router as admin_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    await start_worker()
    yield

app = FastAPI(title="JobSearch SaaS", lifespan=lifespan)

app.include_router(auth_router)
app.include_router(search_router)
app.include_router(admin_router)

STATIC = Path(__file__).parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=STATIC), name="static")

@app.get("/")
def root(): return FileResponse(STATIC / "index.html")

@app.get("/dashboard")
def dashboard(): return FileResponse(STATIC / "dashboard.html")

@app.get("/admin")
def admin_page(): return FileResponse(STATIC / "admin.html")
