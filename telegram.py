"""
services/telegram.py — Telegram WebApp initData validation + JWT issuance.

Validation algorithm:
  1. Parse URL-encoded initData into key=value pairs.
  2. Remove the `hash` field; sort the rest alphabetically; join with '\\n'.
  3. Compute HMAC-SHA256 of that string using
       key = HMAC-SHA256("WebAppData", BOT_TOKEN)
  4. Compare with the `hash` field (constant-time).

Ref: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from urllib.parse import parse_qsl

import jwt
from fastapi import HTTPException, status

from backend.deps import JWT_ALGORITHM, JWT_SECRET

BOT_TOKEN:    str = os.getenv("TELEGRAM_BOT_TOKEN", "")
MAX_AGE_SECS: int = int(os.getenv("TELEGRAM_DATA_MAX_AGE", "86400"))  # 24 h


# ---------------------------------------------------------------------------
# Validate initData
# ---------------------------------------------------------------------------

def validate_init_data(init_data: str) -> dict:
    """
    Parse and validate Telegram WebApp initData.
    Returns the parsed payload dict on success.
    Raises HTTP 401 on any failure.
    """
    if not BOT_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Bot token not configured",
        )

    params = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = params.pop("hash", None)
    if not received_hash:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing hash")

    # Build check string
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))

    # Derive secret key
    secret_key = hmac.new(
        b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256
    ).digest()

    expected = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, received_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid initData signature")

    # Freshness check
    auth_date = int(params.get("auth_date", 0))
    if time.time() - auth_date > MAX_AGE_SECS:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="initData expired")

    # Parse user JSON
    raw_user = params.get("user")
    if not raw_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing user in initData")

    try:
        user_data = json.loads(raw_user)
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed user data")

    return user_data


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def create_access_token(user_id: int, expires_in: int = 60 * 60 * 24 * 30) -> str:
    """Create a JWT that expires in `expires_in` seconds (default 30 days)."""
    payload = {
        "sub": str(user_id),
        "iat": int(time.time()),
        "exp": int(time.time()) + expires_in,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
