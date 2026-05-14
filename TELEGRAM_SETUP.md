# Telegram Bot Setup Guide

Step-by-step instructions for configuring NutriOS as a Telegram Mini App.

---

## 1 — Create the Bot with BotFather

Open Telegram and start a chat with [@BotFather](https://t.me/botfather).

```
/newbot
```

Follow the prompts:
- **Name:** `NutriOS Calorie Tracker`  (displayed name — any wording)
- **Username:** `nutrios_bot`  (must end in `bot`, must be unique)

BotFather replies with your **Bot Token** — copy it now.  
Set it in your `.env`:

```env
TELEGRAM_BOT_TOKEN=123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh
```

---

## 2 — Set Bot Metadata

Still in BotFather, run each command below in order:

```
/setdescription
```
→ Select your bot → paste:
> AI-powered calorie tracker with gamification

```
/setabouttext
```
→ Select your bot → paste:
> Scan food, track calories, earn XP, compete with friends

```
/setuserpic
```
→ Upload a square logo image (512 × 512 px recommended)

---

## 3 — Register Slash Commands

```
/setcommands
```
→ Select your bot → paste the entire block below as one message:

```
start - Open Calorie Tracker
stats - View your stats
leaderboard - Weekly rankings
help - Show available commands
```

---

## 4 — Configure the Menu Button (Mini App launcher)

```
/mybots
```
→ Select your bot  
→ **Bot Settings**  
→ **Menu Button**  
→ **Edit Menu Button URL** → paste your Vercel URL:

```
https://your-app.vercel.app
```

→ **Edit Menu Button Text** → paste:

```
🥗 Track Calories
```

This button appears in the bottom-left of every chat with the bot, giving users one-tap access to the Mini App.

---

## 5 — Register the Webhook

### Option A — Automatic (recommended)

The `backend/bot.py` worker registers the webhook automatically when  
`WEBHOOK_BASE_URL` is set in your environment:

```env
WEBHOOK_BASE_URL=https://your-api.railway.app
WEBHOOK_SECRET=generate-a-random-string-here   # optional but recommended
```

Railway runs `python -m backend.bot` via the `worker` Procfile dyno, which  
calls `setWebhook` on startup.

### Option B — Manual curl

Replace the placeholders and run once in a terminal:

```bash
BOT_TOKEN="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh"
BACKEND_URL="https://your-api.railway.app"
SECRET="some-random-secret"   # must match WEBHOOK_SECRET env var

curl "https://api.telegram.org/bot${BOT_TOKEN}/setWebhook" \
  -d "url=${BACKEND_URL}/webhook/telegram" \
  -d "secret_token=${SECRET}" \
  -d "allowed_updates=[\"message\"]" \
  -d "drop_pending_updates=true"
```

Expected response:
```json
{"ok": true, "result": true, "description": "Webhook was set"}
```

### Verify webhook status

```bash
curl "https://api.telegram.org/bot${BOT_TOKEN}/getWebhookInfo"
```

Look for `"url"` matching your backend and `"pending_update_count": 0`.

### Remove webhook (switch back to polling)

```bash
curl "https://api.telegram.org/bot${BOT_TOKEN}/deleteWebhook"
```

---

## 6 — Domain Validation (HTTPS required)

Telegram requires **HTTPS** for both the Mini App URL and the webhook URL.

Add your Vercel domain to `ALLOWED_ORIGINS` on Railway:

```env
ALLOWED_ORIGINS=https://web.telegram.org,https://k.web.telegram.org,https://your-app.vercel.app
```

Telegram's CSP also requires these headers (already set in `vercel.json`):
- `X-Frame-Options: SAMEORIGIN`
- `Referrer-Policy: strict-origin-when-cross-origin`

---

## 7 — End-to-End Checklist

| Step | What to verify |
|------|----------------|
| BotFather `/start` | Bot replies with app button |
| Menu button | Tapping opens the Vercel app inside Telegram |
| Auth flow | Mini App POSTs `initData` → backend returns a JWT |
| `/stats` command | Bot fetches live DB data and responds in < 2 s |
| `/leaderboard` | Returns top-5 for the current ISO week |
| Webhook logs | Railway → Deployments → Logs shows `200 OK` for each update |
| Achievement notification | Earning an achievement sends a push message |

---

## 8 — Troubleshooting

**"Webhook not working"**  
- Check `getWebhookInfo` for `"last_error_message"`.
- Confirm the backend is live: `curl https://your-api.railway.app/health`.
- Ensure `WEBHOOK_SECRET` matches between the curl registration call and the `WEBHOOK_SECRET` env var.

**"CORS error in Mini App"**  
- Your Vercel domain must be in `ALLOWED_ORIGINS` on the Railway backend.
- The domain must be HTTPS — `http://` origins are blocked by Telegram.

**"initData validation fails"**  
- `TELEGRAM_BOT_TOKEN` must be the exact token from BotFather.
- `TELEGRAM_DATA_MAX_AGE` defaults to 86 400 s (24 h). Don't set it below 300 s in testing.

**"Bot replies but app doesn't open"**  
- Confirm `FRONTEND_URL` env var is set to the full Vercel URL (including `https://`).
- Test the URL directly in a browser — it must load without a certificate error.
