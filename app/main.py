"""Voice Diary — FastAPI application."""

import os
import logging
from contextlib import asynccontextmanager
from datetime import date, timedelta

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from app.database import engine, Base
from app.routes import health, recordings, entries

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
API_KEY = os.environ.get("API_KEY", "")
PUBLIC_PATHS = {"/api/v1/health", "/", "/favicon.ico"}

# Scheduler config
COMPILE_TIME = os.environ.get("COMPILE_TIME", "03:00")


async def scheduled_compile():
    """Compile yesterday's diary entry if there are uncompiled recordings."""
    from app.compiler import compile_diary_entry

    yesterday = date.today() - timedelta(days=1)
    logger.info("Scheduled compilation running for %s", yesterday)
    try:
        entry = await compile_diary_entry(yesterday)
        if entry:
            logger.info("Scheduled compilation complete for %s", yesterday)
        else:
            logger.info("No entries to compile for %s", yesterday)
    except Exception as e:
        logger.error("Scheduled compilation failed for %s: %s", yesterday, e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create database tables on startup and start scheduler."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ensured.")

    # Start APScheduler
    scheduler = None
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger

        hour, minute = COMPILE_TIME.split(":")
        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            scheduled_compile,
            CronTrigger(hour=int(hour), minute=int(minute)),
            id="daily_compile",
            name="Daily diary compilation",
        )
        scheduler.start()
        logger.info("Scheduler started — daily compilation at %s", COMPILE_TIME)
    except ImportError:
        logger.warning("apscheduler not installed — scheduled compilation disabled")
    except Exception as e:
        logger.error("Failed to start scheduler: %s", e)

    yield

    if scheduler:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down.")


app = FastAPI(title="Voice Diary", version="0.2.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# API Key middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    """Enforce API key auth on /api/ routes (except health)."""
    path = request.url.path

    # Only protect API routes (not static files, not health)
    if path.startswith("/api/") and path not in PUBLIC_PATHS:
        # Accept API key from header or query param (for audio streaming via <audio> element)
        key = request.headers.get("X-API-Key", "") or request.query_params.get("key", "")
        if not API_KEY:
            logger.warning("API_KEY env var not set — rejecting all authenticated requests")
            return JSONResponse(status_code=500, content={"detail": "Server misconfigured: API_KEY not set."})
        if key != API_KEY:
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key."})

    response = await call_next(request)
    return response


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
app.include_router(health.router, prefix="/api/v1")
app.include_router(recordings.router)
app.include_router(entries.router)

# Serve static files (PWA frontend)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
async def root():
    """Serve the PWA index page."""
    return FileResponse("app/static/index.html")
