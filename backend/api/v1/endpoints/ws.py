"""
DevFlow Backend - WebSocket Endpoints

Real-time WebSocket communication for ECC job updates.
Supports JWT authentication via query parameter.
"""

import os
from typing import Dict, Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
import jwt
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


def get_jwt_secret() -> str:
    """Get JWT secret from environment variable."""
    return os.getenv("JWT_SECRET", "devflow-jwt-secret-change-in-production")


def get_jwt_algorithm() -> str:
    """Get JWT algorithm (default HS256)."""
    return os.getenv("JWT_ALGORITHM", "HS256")


def _ws_anon_allowed() -> bool:
    """True when the dev-friendly anonymous-WS gate is on.

    Mirrors ALLOW_ANONYMOUS_DISPATCH. Defaults to true so the dev
    frontend can connect without a token. Production deployments MUST
    set ALLOW_ANONYMOUS_WS=false.
    """
    return os.getenv("ALLOW_ANONYMOUS_WS", "true").lower() == "true"


class JobConnectionManager:
    """
    Manages WebSocket connections per job for targeted broadcasts.
    Each job_id has its own set of subscriber connections.
    """

    def __init__(self):
        # Map of job_id -> set of WebSocket connections
        self._job_connections: Dict[str, Set[WebSocket]] = {}
        # Map of WebSocket -> job_id (for cleanup on disconnect)
        self._connection_job: Dict[WebSocket, str] = {}

    async def connect(self, websocket: WebSocket, job_id: str):
        """Subscribe a WebSocket connection to a job. The caller must have already accepted the WebSocket; this method only tracks the subscription."""

        if job_id not in self._job_connections:
            self._job_connections[job_id] = set()
        self._job_connections[job_id].add(websocket)
        self._connection_job[websocket] = job_id
        
        logger.info(f"WebSocket connected for job {job_id}. Total subscribers: {len(self._job_connections[job_id])}")

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection and clean up subscriptions."""
        job_id = self._connection_job.pop(websocket, None)
        if job_id and job_id in self._job_connections:
            self._job_connections[job_id].discard(websocket)
            if not self._job_connections[job_id]:
                del self._job_connections[job_id]
        logger.info(f"WebSocket disconnected from job {job_id}")

    async def broadcast_to_job(self, job_id: str, message: dict):
        """Broadcast a message to all subscribers of a specific job."""
        if job_id not in self._job_connections:
            return
        
        disconnected = set()
        for connection in self._job_connections[job_id]:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to send to client: {e}")
                disconnected.add(connection)

        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)

    def get_subscriber_count(self, job_id: str) -> int:
        """Get the number of subscribers for a job."""
        return len(self._job_connections.get(job_id, set()))


# Global job connection manager instance
job_manager = JobConnectionManager()


def verify_ws_token(token: str) -> dict:
    """
    Verify JWT token for WebSocket authentication.

    Returns:
        dict with user_id and username

    Raises:
        Exception if token is invalid
    """
    secret = get_jwt_secret()
    algorithm = get_jwt_algorithm()

    try:
        payload = jwt.decode(token, secret, algorithms=[algorithm])
        return {
            "user_id": payload.get("sub"),
            "username": payload.get("username"),
        }
    except jwt.exceptions.InvalidTokenError as e:
        raise Exception(f"Invalid token: {str(e)}")


@router.websocket("/ws/ecc/jobs")
async def websocket_ecc_jobs(
    websocket: WebSocket,
    token: str = Query(..., description="JWT authentication token")
):
    """
    WebSocket endpoint for real-time ECC job status updates.
    
    Authentication:
        - JWT token passed via ?token=xxx query parameter
        
    Client Messages:
        - {"action": "subscribe", "job_id": "xxx"} - Subscribe to job updates
        - {"action": "unsubscribe", "job_id": "xxx"} - Unsubscribe from job updates
        - {"action": "ping"} - Keep-alive heartbeat
        
    Server Messages:
        - {"type": "job_update", "job": {...}} - Job status changed
        - {"type": "subscribed", "job_id": "xxx"} - Successfully subscribed
        - {"type": "unsubscribed", "job_id": "xxx"} - Successfully unsubscribed
        - {"type": "pong", "timestamp": "..."} - Heartbeat response
        - {"type": "error", "message": "..."} - Error message
    """
    # Authenticate via JWT token
    if _ws_anon_allowed():
        user = {"user_id": "anonymous", "username": "anonymous"}
        logger.info("WebSocket connected anonymously (ALLOW_ANONYMOUS_WS=true)")
    else:
        try:
            user = verify_ws_token(token)
            logger.info(f"WebSocket authenticated for user: {user.get('username')}")
        except Exception as e:
            logger.warning(f"WebSocket auth failed: {e}")
            await websocket.close(code=4001, reason=str(e))
            return

    await websocket.accept()
    logger.info(f"WebSocket connection accepted for user: {user.get('username')}")

    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")

            if action == "subscribe":
                job_id = data.get("job_id")
                if not job_id:
                    await websocket.send_json({
                        "type": "error",
                        "message": "job_id is required for subscribe action"
                    })
                    continue

                await job_manager.connect(websocket, job_id)
                await websocket.send_json({
                    "type": "subscribed",
                    "job_id": job_id,
                    "message": f"Subscribed to job {job_id}"
                })
                logger.info(f"Client subscribed to job: {job_id}")

            elif action == "unsubscribe":
                job_id = data.get("job_id")
                if not job_id:
                    await websocket.send_json({
                        "type": "error",
                        "message": "job_id is required for unsubscribe action"
                    })
                    continue

                job_manager.disconnect(websocket)
                await websocket.send_json({
                    "type": "unsubscribed",
                    "job_id": job_id,
                    "message": f"Unsubscribed from job {job_id}"
                })
                logger.info(f"Client unsubscribed from job: {job_id}")

            elif action == "ping":
                await websocket.send_json({
                    "type": "pong",
                    "timestamp": data.get("timestamp")
                })

            else:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Unknown action: {action}"
                })

    except WebSocketDisconnect:
        job_manager.disconnect(websocket)
        logger.info("Client disconnected gracefully")

    except Exception as e:
        job_manager.disconnect(websocket)
        logger.error(f"WebSocket error: {e}")


# Helper function to broadcast job updates from other parts of the application
async def broadcast_job_update(job_id: str, job_data: dict):
    """
    Broadcast a job status update to all subscribers.
    
    This function should be called whenever a job's status changes,
    typically from the ECC endpoints or background tasks.
    """
    await job_manager.broadcast_to_job(job_id, {
        "type": "job_update",
        "job": job_data
    })
