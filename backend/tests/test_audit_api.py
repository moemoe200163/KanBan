"""
Tests for audit log and analytics date/time filtering endpoints.

Covers:
- GET /api/v1/audit-logs — date_from, date_to, date range, keyword search, 422 on invalid dates
- GET /api/v1/audit-logs — resource_id exact-match filter
- GET /api/v1/audit-logs/stats — date range filtering
- GET /api/v1/analytics/stats — date range filtering

The fixture creates a fresh SQLite database per test and seeds AuditLog
entries with explicit timestamps so filtering assertions are deterministic.
"""

import pytest
from datetime import datetime, timezone, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

import main
from db import database as db_module
from db.models import Base, AuditLog, Issue


client = TestClient(main.app)


# ---------------------------------------------------------------------------
# Fixture — isolated DB with seeded audit log entries
# ---------------------------------------------------------------------------

def _make_ts(days_offset: int = 0, hours_offset: int = 0) -> datetime:
    """Return a deterministic UTC timestamp offset from a fixed base."""
    base = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    return base + timedelta(days=days_offset, hours=hours_offset)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Point the engine at a fresh SQLite file and seed audit log entries
    with distinct, known timestamps for deterministic filtering tests."""
    db_path = tmp_path / "test_audit_api.db"
    new_url = f"sqlite+aiosqlite:///{db_path}"

    new_engine = create_async_engine(new_url, echo=False)
    new_sessionmaker = async_sessionmaker(new_engine, class_=AsyncSession, expire_on_commit=False)

    def _set_fk_pragma(dbapi_con, con_record):
        cursor = dbapi_con.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    event.listen(new_engine.sync_engine, "connect", _set_fk_pragma)

    monkeypatch.setattr(db_module, "engine", new_engine, raising=False)
    monkeypatch.setattr(db_module, "AsyncSessionLocal", new_sessionmaker, raising=False)
    monkeypatch.setattr(db_module, "_db_initialized", False, raising=False)
    monkeypatch.setattr(db_module, "DATABASE_URL", new_url, raising=False)

    import asyncio

    async def _setup():
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

        now = datetime.now(timezone.utc)
        async with new_sessionmaker() as session:
            # Seed audit log entries at known timestamps
            session.add(AuditLog(
                id="audit_early",
                action="issue.created",
                resource="issue",
                resource_id="DEV-200",
                agent_name="alice",
                timestamp=_make_ts(days_offset=-2),  # 2026-05-30 12:00
            ))
            session.add(AuditLog(
                id="audit_mid",
                action="job.dispatched",
                resource="ecc_job",
                resource_id="job-001",
                agent_name="bob",
                timestamp=_make_ts(days_offset=0, hours_offset=-6),  # 2026-06-01 06:00
            ))
            session.add(AuditLog(
                id="audit_late",
                action="quality.gate_passed",
                resource="quality_gate",
                resource_id="qg-001",
                agent_name="carol",
                timestamp=_make_ts(days_offset=0, hours_offset=6),  # 2026-06-01 18:00
            ))
            session.add(AuditLog(
                id="audit_newest",
                action="issue.updated",
                resource="issue",
                resource_id="DEV-201",
                agent_name="alice",
                timestamp=_make_ts(days_offset=2),  # 2026-06-03 12:00
            ))

            # Seed a parent issue for analytics tests
            session.add(Issue(
                id="issue-audit-1",
                key="DEV-200",
                title="audit test issue",
                description="",
                status="backlog",
                priority="medium",
                board_id="board-default",
                created_at=_make_ts(days_offset=-2),
                updated_at=_make_ts(days_offset=-2),
            ))
            session.add(Issue(
                id="issue-audit-2",
                key="DEV-201",
                title="audit test issue 2",
                description="",
                status="in_progress",
                priority="high",
                board_id="board-default",
                created_at=_make_ts(days_offset=2),
                updated_at=_make_ts(days_offset=2),
            ))

            await session.commit()
        db_module._db_initialized = True

    asyncio.run(_setup())
    yield
    new_engine.sync_engine.dispose()


@pytest.fixture
def fresh_db_with_resource_id_rows(tmp_path, monkeypatch):
    """Point the engine at a fresh SQLite file and seed two audit log
    entries that share the same action but have different resource_id
    values. Used to exercise the resource_id exact-match filter in
    isolation from the date/keyword fixtures."""
    db_path = tmp_path / "test_audit_api_resource_id.db"
    new_url = f"sqlite+aiosqlite:///{db_path}"

    new_engine = create_async_engine(new_url, echo=False)
    new_sessionmaker = async_sessionmaker(new_engine, class_=AsyncSession, expire_on_commit=False)

    def _set_fk_pragma(dbapi_con, con_record):
        cursor = dbapi_con.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    event.listen(new_engine.sync_engine, "connect", _set_fk_pragma)

    monkeypatch.setattr(db_module, "engine", new_engine, raising=False)
    monkeypatch.setattr(db_module, "AsyncSessionLocal", new_sessionmaker, raising=False)
    monkeypatch.setattr(db_module, "_db_initialized", False, raising=False)
    monkeypatch.setattr(db_module, "DATABASE_URL", new_url, raising=False)

    import asyncio

    async def _setup():
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

        ts = datetime.now(timezone.utc)
        async with new_sessionmaker() as session:
            # Two rows: same action, different resource_id.
            session.add(AuditLog(
                id="audit_ri_a",
                action="cycle_report.review",
                resource="cycle_report",
                resource_id="cr_alpha",
                agent_name="leader",
                timestamp=ts,
            ))
            session.add(AuditLog(
                id="audit_ri_b",
                action="cycle_report.review",
                resource="cycle_report",
                resource_id="cr_beta",
                agent_name="leader",
                timestamp=ts,
            ))
            await session.commit()
        db_module._db_initialized = True

    asyncio.run(_setup())
    yield
    new_engine.sync_engine.dispose()


# ---------------------------------------------------------------------------
# GET /api/v1/audit-logs — basic listing
# ---------------------------------------------------------------------------

def test_audit_logs_no_date_returns_all(fresh_db):
    """Without date params the endpoint returns all seeded entries."""
    response = client.get("/api/v1/audit-logs")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 4
    assert len(body["entries"]) == 4


# ---------------------------------------------------------------------------
# GET /api/v1/audit-logs — date_from filtering
# ---------------------------------------------------------------------------

def test_audit_logs_date_from_filters(fresh_db):
    """date_from should exclude entries with timestamps before the cutoff."""
    # date_from = 2026-06-01T12:00:00Z (the base timestamp)
    # Should include: audit_late (18:00), audit_newest (+2d)
    # Should exclude: audit_early (-2d), audit_mid (06:00 — before cutoff)
    response = client.get(
        "/api/v1/audit-logs",
        params={"date_from": "2026-06-01T12:00:00Z"},
    )
    assert response.status_code == 200
    body = response.json()
    returned_ids = {e["id"] for e in body["entries"]}
    assert "audit_early" not in returned_ids
    assert "audit_mid" not in returned_ids
    assert "audit_late" in returned_ids
    assert "audit_newest" in returned_ids
    assert body["total"] == 2


# ---------------------------------------------------------------------------
# GET /api/v1/audit-logs — date_to filtering
# ---------------------------------------------------------------------------

def test_audit_logs_date_to_filters(fresh_db):
    """date_to should exclude entries with timestamps after the cutoff."""
    # date_to = 2026-06-01T12:00:00Z
    # Should include: audit_early (-2d), audit_mid (06:00)
    # Should exclude: audit_late (18:00), audit_newest (+2d)
    response = client.get(
        "/api/v1/audit-logs",
        params={"date_to": "2026-06-01T12:00:00Z"},
    )
    assert response.status_code == 200
    body = response.json()
    returned_ids = {e["id"] for e in body["entries"]}
    assert "audit_early" in returned_ids
    assert "audit_mid" in returned_ids
    assert "audit_late" not in returned_ids
    assert "audit_newest" not in returned_ids
    assert body["total"] == 2


# ---------------------------------------------------------------------------
# GET /api/v1/audit-logs — combined date range
# ---------------------------------------------------------------------------

def test_audit_logs_date_range(fresh_db):
    """Both date_from and date_to should narrow the result set."""
    # range: 2026-06-01T00:00 to 2026-06-02T00:00
    # Should include: audit_mid (06:00 on June 1) and audit_late (18:00 on June 1)
    # Should exclude: audit_early (-2d) and audit_newest (+2d)
    response = client.get(
        "/api/v1/audit-logs",
        params={
            "date_from": "2026-06-01T00:00:00Z",
            "date_to": "2026-06-02T00:00:00Z",
        },
    )
    assert response.status_code == 200
    body = response.json()
    returned_ids = {e["id"] for e in body["entries"]}
    assert returned_ids == {"audit_mid", "audit_late"}
    assert body["total"] == 2


# ---------------------------------------------------------------------------
# GET /api/v1/audit-logs — keyword search
# ---------------------------------------------------------------------------

def test_audit_logs_keyword_search(fresh_db):
    """The q parameter searches across action, resource, resource_id, agent_name."""
    # Search for "alice" — should match audit_early and audit_newest
    response = client.get("/api/v1/audit-logs", params={"q": "alice"})
    assert response.status_code == 200
    body = response.json()
    returned_ids = {e["id"] for e in body["entries"]}
    assert returned_ids == {"audit_early", "audit_newest"}
    assert body["total"] == 2

    # Search for "dispatched" — should match audit_mid only
    response2 = client.get("/api/v1/audit-logs", params={"q": "dispatched"})
    assert response2.status_code == 200
    body2 = response2.json()
    assert body2["total"] == 1
    assert body2["entries"][0]["id"] == "audit_mid"


# ---------------------------------------------------------------------------
# GET /api/v1/audit-logs — resource_id exact-match filter
# ---------------------------------------------------------------------------

def test_audit_logs_resource_id_filter(fresh_db_with_resource_id_rows):
    """resource_id is an exact match on the resource_id column.

    With two rows sharing the same action but different resource_id,
    filtering on one resource_id must return only that row — not the
    sibling row and not all rows.
    """
    # Filter on cr_alpha — only audit_ri_a should come back.
    response = client.get(
        "/api/v1/audit-logs",
        params={"resource_id": "cr_alpha"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert len(body["entries"]) == 1
    entry = body["entries"][0]
    assert entry["id"] == "audit_ri_a"
    assert entry["resourceId"] == "cr_alpha"
    assert entry["action"] == "cycle_report.review"

    # Filter on cr_beta — only audit_ri_b should come back.
    response_b = client.get(
        "/api/v1/audit-logs",
        params={"resource_id": "cr_beta"},
    )
    assert response_b.status_code == 200
    body_b = response_b.json()
    assert body_b["total"] == 1
    assert body_b["entries"][0]["id"] == "audit_ri_b"
    assert body_b["entries"][0]["resourceId"] == "cr_beta"

    # resource_id filter combines with action filter — a mismatched
    # action on the same resource_id should return zero rows.
    response_miss = client.get(
        "/api/v1/audit-logs",
        params={"resource_id": "cr_alpha", "action": "issue.created"},
    )
    assert response_miss.status_code == 200
    assert response_miss.json()["total"] == 0


# ---------------------------------------------------------------------------
# GET /api/v1/audit-logs — invalid date returns 422
# ---------------------------------------------------------------------------

def test_audit_logs_invalid_date_returns_422(fresh_db):
    """An invalid ISO 8601 date string should produce a 422 response."""
    response = client.get(
        "/api/v1/audit-logs",
        params={"date_from": "not-a-date"},
    )
    assert response.status_code == 422


def test_audit_logs_date_from_after_date_to_returns_422(fresh_db):
    """date_from after date_to should produce a 422 response."""
    response = client.get(
        "/api/v1/audit-logs",
        params={
            "date_from": "2026-06-10T00:00:00Z",
            "date_to": "2026-06-01T00:00:00Z",
        },
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/audit-logs — total matches entries
# ---------------------------------------------------------------------------

def test_audit_logs_total_matches_entries(fresh_db):
    """The total count must match the number of entries returned."""
    response = client.get("/api/v1/audit-logs")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == len(body["entries"])

    # With a filter that narrows results
    response2 = client.get(
        "/api/v1/audit-logs",
        params={"date_from": "2026-06-01T00:00:00Z"},
    )
    assert response2.status_code == 200
    body2 = response2.json()
    assert body2["total"] == len(body2["entries"])
    assert body2["total"] == 3


# ---------------------------------------------------------------------------
# GET /api/v1/audit-logs/stats — date range filtering
# ---------------------------------------------------------------------------

def test_audit_stats_with_date_range(fresh_db):
    """Stats endpoint should reflect date-filtered data."""
    # Full stats (no filter)
    response_all = client.get("/api/v1/audit-logs/stats")
    assert response_all.status_code == 200
    stats_all = response_all.json()
    assert stats_all["total"] == 4

    # Filtered stats — only entries on June 1
    response_filtered = client.get(
        "/api/v1/audit-logs/stats",
        params={
            "date_from": "2026-06-01T00:00:00Z",
            "date_to": "2026-06-02T00:00:00Z",
        },
    )
    assert response_filtered.status_code == 200
    stats_filtered = response_filtered.json()
    assert stats_filtered["total"] == 2

    # Verify byAction breakdown includes only the two mid-day entries
    expected_actions = {"job.dispatched": 1, "quality.gate_passed": 1}
    assert stats_filtered["byAction"] == expected_actions

    # Verify byResource breakdown
    expected_resources = {"ecc_job": 1, "quality_gate": 1}
    assert stats_filtered["byResource"] == expected_resources


# ---------------------------------------------------------------------------
# GET /api/v1/analytics/stats — date range filtering
# ---------------------------------------------------------------------------

def test_analytics_stats_with_date_range(fresh_db):
    """Analytics endpoint should reflect date-filtered data."""
    # Full stats
    response_all = client.get("/api/v1/analytics/stats")
    assert response_all.status_code == 200
    analytics_all = response_all.json()
    assert analytics_all["issues"]["total"] == 2

    # Filter to only the later issue (created on June 3)
    response_filtered = client.get(
        "/api/v1/analytics/stats",
        params={
            "date_from": "2026-06-02T00:00:00Z",
        },
    )
    assert response_filtered.status_code == 200
    analytics_filtered = response_filtered.json()
    assert analytics_filtered["issues"]["total"] == 1

    # Verify the single issue is the one created on June 3
    by_status = analytics_filtered["issues"]["byStatus"]
    assert by_status.get("in_progress") == 1
    assert analytics_filtered["issues"]["byPriority"].get("high") == 1
