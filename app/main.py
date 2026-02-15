"""PolicyDiff — Automated Terms of Service & Privacy Policy Change Monitor.

Production-grade application setup with:
  - CORS middleware (configurable origins)
  - Request logging middleware
  - Authentication (API key / bearer token)
  - Rate limiting on expensive operations
  - Proper scheduled check with independent DB sessions
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.database import init_db
from app.config import settings
from app.routers import policies, snapshots, diffs, dashboard
from app.routers.auth import router as auth_router
from app.routers.users import router as users_router
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.pipeline import check_all_policies
from app.middleware.request_logging import RequestLoggingMiddleware

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def scheduled_check():
    """Scheduler callback — checks all due policies with independent sessions."""
    await check_all_policies()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    logger.info("PolicyDiff starting up...")
    init_db()

    if settings.api_key:
        logger.info("Authentication enabled (API_KEY is set)")
    else:
        logger.warning("Authentication DISABLED — set API_KEY in .env for production")

    start_scheduler(scheduled_check)

    yield

    stop_scheduler()
    logger.info("PolicyDiff shut down")


app = FastAPI(
    title="PolicyDiff",
    description="Automated Terms of Service & Privacy Policy Change Monitor",
    version="2.0.0",
    lifespan=lifespan,
)

# ---- Middleware (order matters: last added = first executed) ----

# Session middleware (required by authlib for OAuth state)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)

# Request logging
app.add_middleware(RequestLoggingMiddleware)

# CORS
_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# ---- API Routers ----
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(policies.router)
app.include_router(snapshots.router)
app.include_router(diffs.router)
app.include_router(dashboard.router)

# ---- Static files ----
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
async def serve_index():
    """Serve the main SPA index page."""
    return FileResponse("app/static/index.html")


@app.get("/health")
async def health_check():
    """Health check endpoint (always public, no auth required)."""
    return {
        "status": "healthy",
        "version": "2.0.0",
        "auth_enabled": bool(settings.api_key),
    }
