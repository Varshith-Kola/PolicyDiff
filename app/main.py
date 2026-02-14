"""PolicyDiff — Automated Terms of Service & Privacy Policy Change Monitor."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.database import init_db, SessionLocal
from app.config import settings
from app.routers import policies, snapshots, diffs, dashboard
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.pipeline import check_all_policies

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def scheduled_check():
    """Wrapper for the scheduler to call the pipeline with a DB session."""
    db = SessionLocal()
    try:
        await check_all_policies(db)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    # Startup
    logger.info("PolicyDiff starting up...")
    init_db()
    logger.info("Database initialized")

    start_scheduler(scheduled_check, interval_hours=settings.check_interval_hours)

    yield

    # Shutdown
    stop_scheduler()
    logger.info("PolicyDiff shut down")


app = FastAPI(
    title="PolicyDiff",
    description="Automated Terms of Service & Privacy Policy Change Monitor",
    version="1.0.0",
    lifespan=lifespan,
)

# Register API routers
app.include_router(policies.router)
app.include_router(snapshots.router)
app.include_router(diffs.router)
app.include_router(dashboard.router)

# Serve static frontend files
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
async def serve_index():
    """Serve the main SPA index page."""
    return FileResponse("app/static/index.html")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": "1.0.0"}
