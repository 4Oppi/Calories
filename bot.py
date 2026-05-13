"""
backend/bot.py

Telegram bot worker — aiogram 3.x.

Responsibilities:
  1. Send the Mini App launch button on /start.
  2. Relay achievement / level-up push notifications to users
     (called from gamification_service via an internal queue or direct call).
  3. Provide /stats and /streak slash commands as a quick summary.
  4. Run as a webhook in production (WEBHOOK_BASE_URL set) or
     long-polling in local development (no WEBHOOK_BASE_URL).

Run standalone:
    python -m backend.bot

Or via the Procfile worker dyno:
    worker: python -m backend.bot
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

BOT_TOKEN:        str = os.environ["TELEGRAM_BOT_TOKEN"]          # required
FRONTEND_URL:     str = os.getenv("FRONTEND_URL", "")             # Mini App URL
WEBHOOK_BASE_URL: str = os.getenv("WEBHOOK_BASE_URL", "").rstrip("/")
WEBHOOK_PATH:     str = "/webhook/telegram"
WEBHOOK_SECRET:   str = os.getenv("WEBHOOK_SECRET", "")           # optional header secret
WEBAPP_PORT:      int = int(os.getenv("BOT_PORT", "8001"))        # aiohttp port for webhook

# ─────────────────────────────────────────────────────────────────────────────
# Bot & Dispatcher
# ─────────────────────────────────────────────────────────────────────────────

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _app_keyboard() -> InlineKeyboardMarkup:
    """Inline keyboard with the Mini App launch button."""
    if not FRONTEND_URL:
        return InlineKeyboardMarkup(inline_keyboard=[])
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="🥗 Open NutriOS",
            web_app=WebAppInfo(url=FRONTEND_URL),
        )
    ]])


def _bold(text: str) -> str:
    return f"<b>{text}</b>"


# ─────────────────────────────────────────────────────────────────────────────
# Command handlers
# ─────────────────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """
    /start — greet the user and surface the Mini App button.
    If the Mini App URL is not configured the bot still works as a placeholder.
    """
    first = message.from_user.first_name if message.from_user else "there"

    if FRONTEND_URL:
        text = (
            f"👋 Hey {_bold(first)}! Welcome to <b>NutriOS</b> 🥗\n\n"
            "Track calories, scan food with AI, earn XP and climb the leaderboard — "
            "all without leaving Telegram.\n\n"
            "Tap the button below to open the app 👇"
        )
        await message.answer(text, reply_markup=_app_keyboard())
    else:
        await message.answer(
            f"👋 Hey {_bold(first)}! <b>NutriOS</b> is being set up.\n"
            "The Mini App will be available here soon. Stay tuned! 🚀"
        )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "<b>NutriOS Bot — Commands</b>\n\n"
        "/start  — Open the Mini App\n"
        "/stats  — View your quick stats\n"
        "/streak — Check your current streak\n"
        "/help   — Show this message"
    )


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    """
    Quick stat summary pulled from the database.
    In production this calls the API or queries the DB directly.
    Shown here as a template with placeholder values.
    """
    # TODO: replace with a real DB/API lookup keyed on message.from_user.id
    await message.answer(
        "📊 <b>Your Stats</b>\n\n"
        "Level: <b>12</b> · 3,840 XP\n"
        "Current streak: <b>🔥 7 days</b>\n"
        "Meals logged today: <b>3</b>\n"
        "Calories today: <b>1,284 / 2,100 kcal</b>\n\n"
        "Open the app for the full dashboard 👇",
        reply_markup=_app_keyboard(),
    )


@router.message(Command("streak"))
async def cmd_streak(message: Message) -> None:
    # TODO: real DB lookup
    await message.answer(
        "🔥 <b>Streak Update</b>\n\n"
        "You're on a <b>7-day streak</b>! Keep logging meals every day "
        "to keep it alive.\n\n"
        "Log your next meal 👇",
        reply_markup=_app_keyboard(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Push-notification helpers
# (called from gamification_service via asyncio.create_task)
# ─────────────────────────────────────────────────────────────────────────────

async def notify_achievement(telegram_id: int, title: str, description: str, xp: int) -> None:
    """Send an achievement-unlock push to a user."""
    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=(
                f"🏆 <b>Achievement Unlocked!</b>\n\n"
                f"<b>{title}</b>\n"
                f"{description}\n\n"
                f"⚡ You earned <b>+{xp} XP</b>!"
            ),
            reply_markup=_app_keyboard(),
        )
    except Exception as exc:
        log.warning("notify_achievement failed for %s: %s", telegram_id, exc)


async def notify_level_up(telegram_id: int, new_level: int) -> None:
    """Send a level-up congratulation message."""
    EMOJIS = {5: "🌟", 10: "⭐", 20: "💫", 30: "🔥", 40: "💎", 50: "👑"}
    emoji  = next((e for lvl, e in sorted(EMOJIS.items(), reverse=True) if new_level >= lvl), "🎉")
    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=(
                f"{emoji} <b>Level Up!</b>\n\n"
                f"You've reached <b>Level {new_level}</b>!\n"
                "Keep logging meals and crushing your goals 💪"
            ),
            reply_markup=_app_keyboard(),
        )
    except Exception as exc:
        log.warning("notify_level_up failed for %s: %s", telegram_id, exc)


async def notify_streak_broken(telegram_id: int) -> None:
    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=(
                "😔 <b>Streak Lost</b>\n\n"
                "You missed a day and your streak has reset. "
                "Don't give up — start a new one today! 💪"
            ),
            reply_markup=_app_keyboard(),
        )
    except Exception as exc:
        log.warning("notify_streak_broken failed for %s: %s", telegram_id, exc)


# ─────────────────────────────────────────────────────────────────────────────
# Startup / shutdown
# ─────────────────────────────────────────────────────────────────────────────

async def _on_startup_webhook() -> None:
    webhook_url = f"{WEBHOOK_BASE_URL}{WEBHOOK_PATH}"
    await bot.set_webhook(
        url=webhook_url,
        secret_token=WEBHOOK_SECRET or None,
        allowed_updates=dp.resolve_used_update_types(),
        drop_pending_updates=True,
    )
    log.info("Webhook set: %s", webhook_url)


async def _on_shutdown() -> None:
    log.info("Bot shutting down…")
    await bot.session.close()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )

    if WEBHOOK_BASE_URL:
        # ── Production: webhook via aiohttp ──────────────────────────────────
        log.info("Starting in WEBHOOK mode on port %d", WEBAPP_PORT)

        dp.startup.register(_on_startup_webhook)
        dp.shutdown.register(_on_shutdown)

        app = web.Application()
        handler = SimpleRequestHandler(
            dispatcher=dp,
            bot=bot,
            secret_token=WEBHOOK_SECRET or None,
        )
        handler.register(app, path=WEBHOOK_PATH)
        setup_application(app, dp, bot=bot)

        web.run_app(app, host="0.0.0.0", port=WEBAPP_PORT)

    else:
        # ── Development: long-polling ────────────────────────────────────────
        log.info("Starting in POLLING mode (no WEBHOOK_BASE_URL set)")

        async def _run_polling() -> None:
            await bot.delete_webhook(drop_pending_updates=True)
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

        try:
            asyncio.run(_run_polling())
        except KeyboardInterrupt:
            log.info("Polling stopped.")


if __name__ == "__main__":
    main()
