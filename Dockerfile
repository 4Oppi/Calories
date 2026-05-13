# ─────────────────────────────────────────────────
#  Stage 1 — dependency builder
#  Compile wheels in a full image so the final stage
#  stays slim and has no build toolchain.
# ─────────────────────────────────────────────────
FROM python:3.11-slim AS builder

# System deps needed to build asyncpg, Pillow, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY backend/requirements.txt .

RUN pip install --upgrade pip \
 && pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt


# ─────────────────────────────────────────────────
#  Stage 2 — final runtime image
# ─────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Runtime-only system libs (Pillow needs libjpeg; asyncpg needs libpq)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libjpeg62-turbo \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for security
RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

# Install pre-built wheels — no compiler needed here
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels /wheels/* \
 && rm -rf /wheels

# Copy application source
COPY backend/       ./backend/
COPY alembic/       ./alembic/
COPY alembic.ini    ./alembic.ini

# Ownership
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Healthcheck — Railway and Docker Compose use this
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Default: run migrations then start the API server
CMD ["sh", "-c", "alembic upgrade head && uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 2 --loop uvloop --http httptools"]
