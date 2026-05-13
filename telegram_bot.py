"""
routers/telegram_bot.py

Webhook endpoint for incoming Telegram Bot API updates.

Telegram delivers POST requests to /webhook/telegram whenever a user
sends a message or taps a command.  This router handles:

  /start   → welcome message + Mini App launch button
  /stats   → quick XP / streak / calorie summary
  /leaderboard → top-5 weekly leaderboard snippet

Security:
  Every request is validated against the X-Telegram-Bot-Api-Secret-Token
  header (set via the WEBHOOK_SECRET env var when registering the webhook).
  Requests that fail the check return 200 OK (Telegram expects 200 on all
  deliveries; returning 4xx causes unnecessary retries).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Header, Request, Response
from sqlalchemy import desc, select

from backend.database import AsyncSessionLocal
from backend.models import (
    DailyLog,
    Leaderboard,
    User,
    UserStats,
)

log = logging.getLogger(__name__)
router = APIRouter()

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

BOT_TOKEN:      str = os.getenv("TELEGRAM_BOT_TOKEN", "")
WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "")
FRONTEND_URL:   str = os.getenv("FRONTEND_URL", "").rstrip("/")

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ─────────────────────────────────────────────────────────────────────────────
# Telegram API helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _send(chat_id: int, text: str, reply_markup: Optional[dict] = None) -> None:
    """Fire-and-forget message to a Telegram chat."""
    if not BOT_TOKEN:
        log.warning("BOT_TOKEN not set — skipping Telegram send")
        return
    payload: dict[str, Any] = {
        "chat_id":    chat_id,
        "text":       text,
        "parse_mode": "HTML",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(f"{TG_API}/sendMessage", json=payload)
            if resp.status_code != 200:
                log.warning("sendMessage failed: %s %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        log.warning("sendMessage exception: %s", exc)


def _app_button(label: str = "🥗 Open Calorie Tracker") -> dict:
    """Inline keyboard with the Mini App web_app button."""
    if not FRONTEND_URL:
        return {}
    return {
        "inline_keyboard": [[
            {"text": label, "web_app": {"url": FRONTEND_URL}}
        ]]
    }


def _inline_button(text: str, url: str) -> dict:
    return {"inline_keyboard": [[{"text": text, "url": url}]]}


# ─────────────────────────────────────────────────────────────────────────────
# Security
# ─────────────────────────────────────────────────────────────────────────────

def _validate_secret(header_value: Optional[str]) -> bool:
    """
    Constant-time comparison of the X-Telegram-Bot-Api-Secret-Token header.
    Returns True if WEBHOOK_SECRET is not configured (open endpoint — dev only).
    """
    if not WEBHOOK_SECRET:
        return True
    if not header_value:
        return False
    return hmac.compare_digest(
        header_value.encode(),
        WEBHOOK_SECRET.encode(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Command handlers
# ─────────────────────────────────────────────────────────────────────────────

async def _handle_start(chat_id: int, first_name: str, tg_user_id: int) -> None:
    text = (
        f"👋 Hey <b>{first_name}</b>! Welcome to <b>NutriOS</b> 🥗\n\n"
        "Track calories, scan food with AI, earn XP, and compete with friends — "
        "all inside Telegram.\n\n"
        "🎯 Log meals  ·  📸 Scan food  ·  🏆 Earn XP\n\n"
        "Tap below to open the app 👇"
    )
    await _send(chat_id, text, _app_button())


async def _handle_stats(chat_id: int, tg_user_id: int) -> None:
    """Fetch live stats from the DB and send a summary."""
    async with AsyncSessionLocal() as db:
        # Look up user by Telegram ID
        user_row = (await db.execute(
            select(User).where(User.telegram_id == tg_user_id)
        )).scalar_one_or_none()

        if user_row is None:
            await _send(
                chat_id,
                "You don't have an account yet! Open the app to get started 👇",
                _app_button("🥗 Open NutriOS"),
            )
            return

        # UserStats
        stats = (await db.execute(
            select(UserStats).where(UserStats.user_id == user_row.id)
        )).scalar_one_or_none()

        # Today's DailyLog
        today = datetime.now(timezone.utc).date()
        log_row = (await db.execute(
            select(DailyLog).where(
                DailyLog.user_id  == user_row.id,
                DailyLog.log_date == today,
            )
        )).scalar_one_or_none()

    # Build message
    if stats:
        xp_str     = f"{stats.total_xp:,}"
        level_str  = str(stats.current_level)
        streak_str = f"🔥 {stats.current_streak} day{'s' if stats.current_streak != 1 else ''}"
    else:
        xp_str = level_str = streak_str = "—"

    if log_row:
        cal_str  = f"{int(log_row.total_calories or 0):,}"
        goal_str = f"{user_row.calorie_goal or '?'}"
        meals_str = str(log_row.meal_count)
    else:
        cal_str = meals_str = "0"
        goal_str = str(user_row.calorie_goal or "?") if user_row else "?"

    text = (
        f"📊 <b>Your Stats</b>\n\n"
        f"Level:    <b>{level_str}</b> · {xp_str} XP\n"
        f"Streak:   <b>{streak_str}</b>\n"
        f"─────────────────\n"
        f"Today:    <b>{meals_str} meal{'s' if meals_str != '1' else ''} logged</b>\n"
        f"Calories: <b>{cal_str} / {goal_str} kcal</b>\n"
    )
    await _send(chat_id, text, _app_button("📱 Open Full Dashboard"))


async def _handle_leaderboard(chat_id: int, tg_user_id: int) -> None:
    """Send the top-5 weekly leaderboard snippet."""
    from datetime import date
    today      = date.today()
    iso        = today.isocalendar()
    period_key = f"{iso.year}-W{iso.week:02d}"

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Leaderboard, User)
            .join(User, Leaderboard.user_id == User.id)
            .where(
                Leaderboard.period     == "weekly",
                Leaderboard.period_key == period_key,
            )
            .order_by(desc(Leaderboard.xp_earned))
            .limit(5)
        )).all()

    if not rows:
        await _send(
            chat_id,
            "📭 No leaderboard data yet this week. Log meals to get on the board!",
            _app_button(),
        )
        return

    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    lines  = ["🏆 <b>Weekly Leaderboard</b>\n"]
    for rank, (lb, u) in enumerate(rows):
        name   = u.display_name or u.telegram_username or f"User {u.id}"
        marker = " ← you" if u.telegram_id == tg_user_id else ""
        lines.append(f"{medals[rank]}  <b>{name}</b>  —  {lb.xp_earned:,} XP{marker}")

    await _send(chat_id, "\n".join(lines), _app_button("🏆 Full Leaderboard"))


async def _handle_unknown(chat_id: int) -> None:
    await _send(
        chat_id,
        "I didn't understand that. Use /start to open the app or /help for commands.",
        _app_button(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Webhook dispatcher
# ─────────────────────────────────────────────────────────────────────────────

async def _dispatch(update: dict) -> None:
    """Route a single Telegram Update to the right handler."""
    message = update.get("message") or update.get("edited_message")
    if not message:
        # Ignore channel posts, callback queries, etc. for now
        return

    chat_id      = message["chat"]["id"]
    tg_user_id   = message.get("from", {}).get("id", 0)
    first_name   = message.get("from", {}).get("first_name", "friend")
    text: str    = message.get("text", "").strip()
    command      = text.split("@")[0].split()[0].lstrip("/").lower() if text.startswith("/") else ""

    log.info("Update from tg_user=%s command=%r", tg_user_id, command or text[:30])

    if command == "start":
        await _handle_start(chat_id, first_name, tg_user_id)
    elif command == "stats":
        await _handle_stats(chat_id, tg_user_id)
    elif command in ("leaderboard", "top"):
        await _handle_leaderboard(chat_id, tg_user_id)
    elif command == "help":
        await _send(
            chat_id,
            "<b>NutriOS Commands</b>\n\n"
            "/start       — Open the Mini App\n"
            "/stats       — Your XP, level & today's calories\n"
            "/leaderboard — Weekly top-5 rankings\n"
            "/help        — Show this message",
        )
    elif text:
        await _handle_unknown(chat_id)


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI route
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/webhook/telegram",
    include_in_schema=False,   # hide from Swagger — it's a Telegram internal endpoint
)
async def telegram_webhook(
    request:         Request,
    background:      BackgroundTasks,
    x_telegram_bot_api_secret_token: Optional[str] = Header(default=None),
) -> Response:
    """
    Receive an Update from Telegram.

    Always returns 200 OK immediately (even on validation failure) to prevent
    Telegram from retrying.  The actual handling runs as a background task so
    the response is never blocked by DB or Telegram API calls.
    """
    if not _validate_secret(x_telegram_bot_api_secret_token):
        log.warning("Webhook received with invalid secret — ignoring")
        return Response(status_code=200)

    try:
        update = await request.json()
    except Exception:
        log.warning("Webhook body is not valid JSON")
        return Response(status_code=200)

    # Hand off to background so the HTTP response returns instantly
    background.add_task(_dispatch, update)
    return Response(status_code=200)


# ─────────────────────────────────────────────────────────────────────────────
# Webhook registration helper  (call once at deploy time)
# ─────────────────────────────────────────────────────────────────────────────

async def register_webhook(base_url: str) -> dict:
    """
    Tell Telegram where to deliver updates.

    Usage (e.g. from a startup script or admin endpoint):
        from backend.routers.telegram_bot import register_webhook
        result = await register_webhook("https://your-api.railway.app")
    """
    webhook_url = f"{base_url.rstrip('/')}/webhook/telegram"
    payload: dict[str, Any] = {
        "url":              webhook_url,
        "allowed_updates":  ["message"],
        "drop_pending_updates": True,
    }
    if WEBHOOK_SECRET:
        payload["secret_token"] = WEBHOOK_SECRET

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(f"{TG_API}/setWebhook", json=payload)
        data = resp.json()

    if data.get("ok"):
        log.info("Webhook registered: %s", webhook_url)
    else:
        log.error("Webhook registration failed: %s", data)

    return data
