"""
main.py — FastAPI entrypoint for the Telegram Mini App Calorie Tracker.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from database import engine, Base
from routers import auth, meals, scan, profile, gamification
from routers import telegram_bot


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup (use Alembic for production migrations)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Calorie Tracker API",
    description="Telegram Mini App — calorie tracking with gamification",
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS — Telegram Mini Apps are served from https://web.telegram.org and
# the bot's own domain.  Adjust ALLOWED_ORIGINS via env in production.
# ---------------------------------------------------------------------------

import os

ALLOWED_ORIGINS: list[str] = os.getenv(
    "ALLOWED_ORIGINS",
    "https://web.telegram.org,https://k.web.telegram.org,http://localhost:3000",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(auth.router,              prefix="/auth",         tags=["Auth"])
app.include_router(meals.router,             prefix="/meals",        tags=["Meals"])
app.include_router(scan.router,              prefix="/scan",         tags=["Scan"])
app.include_router(profile.router,           prefix="/profile",      tags=["Profile"])
app.include_router(gamification.router,      prefix="/gamification", tags=["Gamification"])
app.include_router(telegram_bot.router,      tags=["Webhook"])       # /webhook/telegram


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", include_in_schema=False)
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})
