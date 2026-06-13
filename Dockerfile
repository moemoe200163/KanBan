# =============================================================================
# DevFlow Multi-Stage Dockerfile
# =============================================================================
# Builds both frontend (Nuxt) and backend (FastAPI) in separate stages,
# then combines them for production deployment.
# =============================================================================

# Frontend - Nuxt application
FROM node:20-alpine AS frontend

ARG NUXT_PUBLIC_API_BASE=http://backend:8000/api/v1
ARG NUXT_PUBLIC_E2E=0

WORKDIR /app

# Copy package files for better layer caching
COPY package*.json ./

# Install dependencies
RUN npm ci --prefer-offline

# Copy source code. The .dockerignore at the repo root prevents any
# pre-existing host-side .output / .nuxt / node_modules from being
# baked into the image — those must be regenerated inside the image,
# otherwise stale chunks from a previous local build leak into the
# production bundle.
COPY . .

# Set env for build (Nuxt evaluates this at build time)
ENV NUXT_PUBLIC_API_BASE=${NUXT_PUBLIC_API_BASE}
ENV NUXT_PUBLIC_E2E=${NUXT_PUBLIC_E2E}

# Build the Nuxt application from a clean slate.
RUN npm run build

# Expose port (Nuxt handles its own PORT via NITRO_PORT)
EXPOSE 3010

# Start Nuxt in production mode
CMD ["node", ".output/server/index.mjs"]


# -----------------------------------------------------------------------------
# Stage 2: Backend - FastAPI Application
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS backend

WORKDIR /app

# Install system dependencies for crypto operations
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source code
COPY backend/ ./backend/

# Create data directory for SQLite
RUN mkdir -p /app/data

# Expose FastAPI port
EXPOSE 8000

# Set Python path
ENV PYTHONPATH=/app

# Mark the container runtime as "alembic already handled by entrypoint".
# The lifespan in backend/db/database.py checks this and skips its own
# ``asyncio.to_thread(command.upgrade)`` call, which would otherwise
# deadlock against the async engine created in the uvicorn event loop.
ENV SKIP_LIFESPAN_ALEMBIC=1

# Start FastAPI from the backend directory
ENV PYTHONUNBUFFERED=1

# Plan J bug C-1 fix: run ``alembic upgrade head`` as a child process
# *before* exec-ing uvicorn. The child has its own event loop, so
# ``alembic``'s internal ``asyncio.run(run_async_migrations)`` never
# collides with the uvicorn loop. We deliberately do *not* run
# alembic inside the lifespan's event loop — that previously caused
# ``asyncio.to_thread + command.upgrade`` to hang on 0022→0023.
# ``exec uvicorn`` makes uvicorn PID 1 (so docker stop signals
# propagate correctly); if alembic fails the script exits with the
# alembic exit code and the container restart-loops with a visible
# error instead of silently starting a broken server.
CMD ["sh", "-c", "cd backend && alembic upgrade head && exec uvicorn main:app --host 0.0.0.0 --port 8000 --log-level info"]


# -----------------------------------------------------------------------------
# Stage 3: Development (combines both for dev workflow)
# -----------------------------------------------------------------------------
FROM node:20-alpine AS development

WORKDIR /app

# Install frontend dependencies
COPY package*.json ./
RUN npm ci

# Copy source
COPY . .

# Expose ports
EXPOSE 3010 8000

# Development command (runs both frontend and backend)
CMD ["sh", "-c", "npm run dev & python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload"]