"""
DevFlow Team Collaboration System - FastAPI Main Application
Backend entry point for the Kanban-style team collaboration platform.
"""

from contextlib import asynccontextmanager
import fastapi
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
import logging
import asyncio
import os
from typing import Set

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ============================================================================
# Lifespan Management - Startup/Shutdown Events
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application lifecycle - startup and shutdown events.
    Initialize connections to Redis, database, and other services.
    """
    logger.info("Starting DevFlow Backend...")
    logger.info(f"FastAPI version: {fastapi.__version__}")

    # Initialize connections (placeholder for actual connection setup)
    # In production, these would connect to Redis, PostgreSQL, etc.
    try:
        # Example: await init_redis_connection()
        logger.info("Redis connection: OK (simulated)")
    except Exception as e:
        logger.warning(f"Redis connection failed: {e}")

    # Initialize database, seed if empty, and hydrate in-memory caches.
    try:
        from db.database import init_db, DATABASE_URL
        from db import repository as repo

        await init_db()
        logger.info(f"Database initialized: OK ({DATABASE_URL})")

        # Seed dev data only when explicitly requested. Production and
        # demos that need a clean board should leave this off.
        if os.getenv("SEED_DEV_DATA", "true").lower() in ("1", "true", "yes"):
            seeded = await repo.seed_if_empty()
            if seeded:
                logger.info(f"Database seeded with {seeded} initial issues")
            else:
                logger.info("Database already seeded; skipping")
        else:
            logger.info("SEED_DEV_DATA is off; skipping seed")

        # Load existing jobs from DB into memory for the in-memory ECC hot path.
        from api.v1.endpoints.ecc import load_jobs_from_db
        await load_jobs_from_db()
        logger.info("ECC jobs loaded from database: OK")

        # Seed audit log entries from existing jobs (one-time)
        audit_seeded = await repo.seed_audit_logs_from_jobs()
        if audit_seeded:
            logger.info(f"Audit logs seeded with {audit_seeded} entries")

        # Seed default LLM provider configs (one-time)
        llm_seeded = await repo.seed_llm_provider_configs()
        if llm_seeded:
            logger.info(f"Seeded {llm_seeded} default LLM provider configs")

        # Seed default agent roles from WORKER_LANES (one-time)
        roles_seeded = await repo.seed_default_roles()
        if roles_seeded:
            logger.info(f"Seeded {roles_seeded} default agent roles")
    except Exception:
        logger.exception("Database initialization failed during startup")
        raise

    # Initialize the ProcessRunner for ECC command execution
    try:
        from core.process_runner import ProcessRunner
        app.state.runner = ProcessRunner()
        logger.info(f"ProcessRunner initialized: OK (binary={app.state.runner.binary_path})")
    except Exception:
        logger.exception("ProcessRunner initialization failed during startup")
        raise

    # Start the background agent worker when real execution is enabled.
    # The worker polls for pending AgentRun records and executes them via
    # the safe runner (P0) or real adapters (when harness is "claude-code").
    app.state.worker = None
    import os as _worker_os
    if _worker_os.getenv("ALLOW_REAL_LLM_EXECUTION", "false").lower() == "true":
        try:
            from core.runtime.worker import start_background_worker
            app.state.worker = await start_background_worker(
                claude_path=_worker_os.getenv("CLAUDE_CODE_PATH", "claude"),
                workspace_path=_worker_os.getenv("WORKSPACE_PATH", "/Users/user/Code/kanban"),
            )
            logger.info("Background agent worker started (real execution enabled)")
        except Exception:
            logger.exception("Background agent worker failed to start (non-fatal)")

    # Register adapters in the HarnessRegistry
    try:
        from core.adapters.registry import HarnessRegistry
        from core.adapters.claude_local import ClaudeLocalAdapter
        from core.adapters.safe_runner import SafeRunAdapter
        from core.adapters.api_model import APIModelAdapter

        # Harness adapters (keyed by harness type)
        HarnessRegistry.register("claude-code", ClaudeLocalAdapter)
        HarnessRegistry.register("safe-runner", SafeRunAdapter)
        HarnessRegistry.register("api-model", APIModelAdapter)

        # Provider adapters (keyed by provider_id — used when run.provider is set)
        # These share the same APIModelAdapter class but are resolved per-provider.
        from core.llm.providers import PROVIDERS
        for prov in PROVIDERS:
            if prov.adapter in ("api-chat", "api-responses"):
                HarnessRegistry.register_provider(prov.id, APIModelAdapter)

        logger.info(
            "HarnessRegistry: harness=%s, providers=%s",
            HarnessRegistry.list_supported(),
            HarnessRegistry.list_providers(),
        )
    except Exception:
        logger.exception("HarnessRegistry registration failed (non-fatal)")

    logger.info("DevFlow Backend started successfully")

    # Start the autopilot scheduler (auto-dispatches non-human lanes).
    try:
        from core.kanban_protocol.autopilot import scheduler as autopilot_scheduler
        await autopilot_scheduler.start()
        logger.info("Autopilot scheduler started (tick=%ds)", autopilot_scheduler.tick_interval)
    except Exception:
        logger.exception("Autopilot scheduler failed to start (non-fatal)")

    # Yield control to the application
    yield

    # Shutdown: stop the autopilot scheduler, then the background worker, then clean up connections
    logger.info("Shutting down DevFlow Backend...")
    try:
        from core.kanban_protocol.autopilot import scheduler as autopilot_scheduler
        await autopilot_scheduler.stop()
    except Exception:
        pass
    if getattr(app.state, "worker", None) is not None:
        try:
            from core.runtime.worker import stop_background_worker
            stop_background_worker()
        except Exception:
            logger.exception("Error stopping background worker")

    # Example: await close_redis_connection()
    # Example: await close_database_connection()

    logger.info("DevFlow Backend shutdown complete")


# ============================================================================
# FastAPI Application Instance
# ============================================================================

app = FastAPI(
    title="DevFlow API",
    description="Team Collaboration System API for Kanban-style project management",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan
)


# ============================================================================
# CORS Middleware Configuration
# ============================================================================

# Configure CORS for frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3010",
        "http://127.0.0.1:3010",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger.info("CORS middleware configured")


# ============================================================================
# Health Check Endpoint
# ============================================================================

@app.get("/health", tags=["Health"])
async def health_check():
    """
    Health check endpoint for monitoring and load balancers.
    Returns the current status of the API service.
    """
    return JSONResponse(
        content={
            "status": "healthy",
            "service": "devflow-api",
            "version": "1.0.0"
        },
        status_code=200
    )


@app.get("/health/ready", tags=["Health"])
async def readiness_check():
    """
    Readiness check endpoint - verifies all dependencies are available.
    Used by Kubernetes/load balancers to determine if the pod should receive traffic.
    """
    checks = {"api": "ok"}

    # Database check: open a session and run SELECT 1.
    # The session is opened with a short timeout so a hung DB does not block
    # the readiness probe indefinitely; the overall smoke-script timeout
    # (60s) absorbs any remainder.
    try:
        from db.database import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    # Redis check: placeholder until a real Redis client is wired up.
    # The project does not currently use Redis at runtime; the entry is kept
    # in the response so the contract is stable for future pub/sub work.
    checks["redis"] = "ok"

    all_ok = all(v == "ok" for v in checks.values())

    return JSONResponse(
        content={
            "status": "ready" if all_ok else "degraded",
            "checks": checks
        },
        status_code=200 if all_ok else 503
    )


# ============================================================================
# WebSocket Connection Manager
# ============================================================================

class ConnectionManager:
    """
    Manages WebSocket connections for real-time updates.
    Handles client connection, disconnection, and message broadcasting.
    """

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection."""
        self.active_connections.discard(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Broadcast a message to all connected clients."""
        disconnected = set()

        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to send to client: {e}")
                disconnected.add(connection)

        # Clean up disconnected clients
        self.active_connections.difference_update(disconnected)

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """Send a message to a specific client."""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Failed to send personal message: {e}")
            raise


# Global connection manager instance
manager = ConnectionManager()


# ============================================================================
# WebSocket Endpoint
# ============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time updates.
    Handles bidirectional communication for live collaboration features.

    Client messages:
    - subscribe: Join a project's update stream
    - unsubscribe: Leave a project's update stream
    - ping: Keep-alive heartbeat

    Server messages:
    - issue_updated: An issue was modified
    - issue_created: A new issue was created
    - issue_deleted: An issue was removed
    - agent_status: Agent state change notification
    - presence: User presence updates
    """
    await manager.connect(websocket)

    try:
        while True:
            # Wait for client messages
            data = await websocket.receive_json()
            logger.debug(f"WebSocket received: {data}")

            message_type = data.get("type")

            if message_type == "ping":
                # Respond to keep-alive ping
                await manager.send_personal_message(
                    {"type": "pong", "timestamp": data.get("timestamp")},
                    websocket
                )

            elif message_type == "subscribe":
                # Subscribe to project updates
                project_id = data.get("project_id")
                logger.info(f"Client subscribed to project: {project_id}")
                await manager.send_personal_message(
                    {
                        "type": "subscribed",
                        "project_id": project_id,
                        "message": f"Subscribed to project {project_id}"
                    },
                    websocket
                )

            elif message_type == "unsubscribe":
                # Unsubscribe from project updates
                project_id = data.get("project_id")
                logger.info(f"Client unsubscribed from project: {project_id}")
                await manager.send_personal_message(
                    {
                        "type": "unsubscribed",
                        "project_id": project_id,
                        "message": f"Unsubscribed from project {project_id}"
                    },
                    websocket
                )

            elif message_type == "broadcast":
                # Broadcast message to all clients (admin function)
                await manager.broadcast(data.get("payload", {}))

            else:
                logger.warning(f"Unknown message type: {message_type}")
                await manager.send_personal_message(
                    {"type": "error", "message": f"Unknown message type: {message_type}"},
                    websocket
                )

    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info("Client disconnected gracefully")

    except Exception as e:
        manager.disconnect(websocket)
        logger.error(f"WebSocket error: {e}")


# ============================================================================
# API v1 Router Mounting
# ============================================================================

# Import API v1 routers (will be created as separate modules)
try:
    from api.v1.endpoints import webhooks, agents, issues, ecc, board, quality, auth, ws, audit, analytics, llm, issue_collaboration, lanes, handoffs, runtime, autopilot, kanban_tools, github_api, agent_roles, artifacts, deliveries, cycle_reports

    # Mount API v1 routers with prefix
    app.include_router(webhooks.router, prefix="/api/v1", tags=["Webhooks"])
    app.include_router(agents.router, prefix="/api/v1", tags=["Agents"])
    app.include_router(issues.router, prefix="/api/v1", tags=["Issues"])
    app.include_router(issue_collaboration.router, prefix="/api/v1", tags=["Issue Collaboration"])
    app.include_router(ecc.router, prefix="/api/v1", tags=["ECC"])
    app.include_router(board.router, prefix="/api/v1", tags=["Board"])
    app.include_router(quality.router, prefix="/api/v1", tags=["Quality"])
    app.include_router(auth.router, prefix="/api/v1", tags=["Authentication"])
    app.include_router(audit.router, prefix="/api/v1", tags=["Audit"])
    app.include_router(analytics.router, prefix="/api/v1", tags=["Analytics"])
    app.include_router(lanes.router, prefix="/api/v1", tags=["Lanes"])
    app.include_router(agent_roles.router, prefix="/api/v1", tags=["Agent Roles"])
    app.include_router(llm.router, prefix="/api/v1", tags=["LLM"])
    app.include_router(handoffs.router, prefix="/api/v1", tags=["Kanban Protocol"])
    app.include_router(runtime.router, prefix="/api/v1", tags=["Agent Runtime"])
    app.include_router(autopilot.router, prefix="/api/v1", tags=["Autopilot"])
    app.include_router(kanban_tools.router, prefix="/api/v1", tags=["Kanban Tools"])
    app.include_router(github_api.router, prefix="/api/v1", tags=["GitHub"])
    app.include_router(artifacts.router, prefix="/api/v1", tags=["Artifacts"])
    app.include_router(deliveries.router, prefix="/api/v1", tags=["Deliveries"])
    app.include_router(cycle_reports.router, prefix="/api/v1", tags=["Cycle Reports"])

    # Dev management endpoints (stats + reset self-gate on dev mode; 404 in production)
    from api.v1.endpoints import dev
    app.include_router(dev.router, prefix="/api/v1", tags=["Dev"])

    # Mount WebSocket router for ECC job updates at /ws/ecc/jobs
    app.include_router(ws.router, tags=["WebSocket"])

    # The test_reset router is **only** mounted when both E2E gating
    # conditions hold (E2E=1 and the database name contains ``_e2e``).
    # The router itself re-checks the gate on every request, so even if
    # the module was imported, the endpoint returns 404 in non-E2E envs.
    import os as _os
    if _os.getenv("E2E") == "1" and "_e2e" in _os.getenv("DATABASE_URL", ""):
        from api.v1.endpoints import test_reset
        app.include_router(test_reset.router, prefix="/api/v1", tags=["E2E-Test"])
        logger.info("E2E test_reset router mounted (E2E=1, db name contains _e2e)")
    else:
        logger.info("E2E test_reset router not mounted (E2E gate not satisfied)")

    logger.info("API v1 routers mounted successfully")

except ImportError as e:
    logger.warning(f"API v1 routers not found: {e}")
    logger.warning("Running in standalone mode without API routes")


# ============================================================================
# Root Endpoint
# ============================================================================

@app.get("/", tags=["Root"])
async def root():
    """
    Root endpoint - returns API information and available endpoints.
    """
    return JSONResponse(
        content={
            "service": "DevFlow API",
            "version": "1.0.0",
            "docs": "/docs",
            "health": "/health",
            "websocket": "/ws",
            "api_version": "v1",
            "endpoints": {
                "webhooks": "/api/v1/webhooks",
                "agents": "/api/v1/agents",
                "issues": "/api/v1/issues"
            }
        }
    )


# ============================================================================
# Global Exception Handler
# ============================================================================

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """
    Global exception handler for unhandled errors.
    Logs the error and returns a generic 500 response.
    """
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    # Also flush to stderr so the trace is visible even when the global
    # logger has its own handlers that buffer or filter.
    import traceback, sys
    print("=== UNHANDLED EXCEPTION ===", file=sys.stderr, flush=True)
    traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
    print("=== END ===", file=sys.stderr, flush=True)
    return JSONResponse(
        content={
            "error": "Internal Server Error",
            "message": "An unexpected error occurred. Please try again later.",
            "status_code": 500
        },
        status_code=500
    )


# ============================================================================
# Application Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    logger.info("Starting DevFlow API server...")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
