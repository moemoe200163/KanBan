"""Tests for the global file-artifacts API (GET/POST /api/v1/artifacts).

Covers upload, list (with tag/name filter), blob download, version
chain, and delete. Auth is intentionally open in this iteration
(調研階段先快上), so no JWT header is needed.
"""
import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

import main
from db import database as db_module
from db.models import Base


client = TestClient(main.app)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Fresh SQLite DB with just the artifacts table populated."""
    db_path = tmp_path / "test_global_artifacts.db"
    new_url = f"sqlite+aiosqlite:///{db_path}"

    new_engine = create_async_engine(new_url, echo=False)
    new_sessionmaker = async_sessionmaker(new_engine, class_=AsyncSession, expire_on_commit=False)

    monkeypatch.setattr(db_module, "engine", new_engine, raising=False)
    monkeypatch.setattr(db_module, "AsyncSessionLocal", new_sessionmaker, raising=False)
    monkeypatch.setattr(db_module, "_db_initialized", False, raising=False)
    monkeypatch.setattr(db_module, "DATABASE_URL", new_url, raising=False)

    import asyncio
    async def _setup():
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(_setup())
    yield
    new_engine.sync_engine.dispose()


def _upload(file_name: str, content: bytes, tags: list = None, description: str = "", uploader: str = "tester"):
    """Helper: build a multipart POST to /api/v1/artifacts."""
    files = {"file": (file_name, io.BytesIO(content), "text/plain")}
    form = {"description": description, "uploader": uploader}
    if tags is not None:
        import json as _json
        form["tags"] = _json.dumps(tags)
    return client.post("/api/v1/artifacts", files=files, data=form)


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

def test_upload_happy_path(fresh_db):
    resp = _upload("hello.txt", b"hello world", tags=["greeting"], description="smoke")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"].startswith("art_")
    assert body["name"] == "hello.txt"
    assert body["sizeBytes"] == 11
    assert body["tags"] == ["greeting"]
    assert body["version"] == 1
    assert body["parentId"] is None


def test_upload_rejects_empty(fresh_db):
    files = {"file": ("empty.txt", io.BytesIO(b""), "text/plain")}
    resp = client.post("/api/v1/artifacts", files=files, data={})
    assert resp.status_code == 400
    assert "Empty" in resp.json()["detail"]


def test_upload_invalid_tags_json(fresh_db):
    files = {"file": ("x.txt", io.BytesIO(b"x"), "text/plain")}
    resp = client.post("/api/v1/artifacts", files=files, data={"tags": "not-json"})
    assert resp.status_code == 400
    assert "tags" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# List + filter
# ---------------------------------------------------------------------------

def test_list_empty(fresh_db):
    resp = client.get("/api/v1/artifacts")
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "count": 0}


def test_list_filter_by_tag(fresh_db):
    _upload("a.md", b"a", tags=["design"])
    _upload("b.md", b"b", tags=["design", "screenshot"])
    _upload("c.md", b"c", tags=["screenshot"])

    resp = client.get("/api/v1/artifacts?tag=design")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert {i["name"] for i in items} == {"a.md", "b.md"}

    resp2 = client.get("/api/v1/artifacts?tag=screenshot")
    assert {i["name"] for i in resp2.json()["items"]} == {"b.md", "c.md"}


def test_list_filter_by_name_substring(fresh_db):
    _upload("design-spec.md", b"d")
    _upload("design-mock.png", b"d")
    _upload("other.txt", b"o")

    resp = client.get("/api/v1/artifacts?q=design")
    items = resp.json()["items"]
    assert {i["name"] for i in items} == {"design-spec.md", "design-mock.png"}


# ---------------------------------------------------------------------------
# Blob download
# ---------------------------------------------------------------------------

def test_blob_download_roundtrip(fresh_db):
    payload = b"binary content \x00\x01\x02"
    upload = _upload("blob.bin", payload, tags=["binary"])
    art_id = upload.json()["id"]

    resp = client.get(f"/api/v1/artifacts/{art_id}/blob")
    assert resp.status_code == 200
    assert resp.content == payload
    assert resp.headers["x-artifact-id"] == art_id
    assert "attachment" in resp.headers["content-disposition"]
    assert "blob.bin" in resp.headers["content-disposition"]


def test_blob_404(fresh_db):
    resp = client.get("/api/v1/artifacts/art_nonexistent/blob")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Version chain
# ---------------------------------------------------------------------------

def test_version_chain(fresh_db):
    """Uploading with as_version_of creates a new version off the chain's
    latest row. Without as_version_of, every upload is a brand-new root
    (no silent auto-chaining on name collision)."""
    v1 = _upload("report.pdf", b"v1", tags=["v1"])
    v1_id = v1.json()["id"]

    # Upload a v2 explicitly chained off v1.
    files = {"file": ("report.pdf", io.BytesIO(b"v2 payload"), "application/pdf")}
    v2 = client.post(
        "/api/v1/artifacts",
        files=files,
        data={"as_version_of": v1_id, "description": "v2 of report"},
    ).json()
    assert v2["version"] == 2
    assert v2["parentId"] == v1_id

    chain = client.get(f"/api/v1/artifacts/{v1_id}/versions").json()
    assert chain["count"] == 2
    assert [it["version"] for it in chain["items"]] == [1, 2]


def test_version_chain_off_existing_target(fresh_db):
    """Uploading with as_version_of should chain off the existing row,
    not always create a brand new root."""
    v1 = _upload("doc.md", b"a").json()
    # Second upload is a brand new root (no as_version_of)
    v2 = _upload("doc.md", b"b").json()
    assert v2["parentId"] is None
    assert v2["version"] == 1
    # Third upload explicitly chains off v1 — should walk to the latest
    # in v1's chain (which is v1 itself, since v2 isn't chained) and
    # produce v3.
    files = {"file": ("doc.md", io.BytesIO(b"c"), "text/markdown")}
    v3 = client.post(
        "/api/v1/artifacts",
        files=files,
        data={"as_version_of": v1["id"]},
    ).json()
    assert v3["version"] == 2
    assert v3["parentId"] == v1["id"]


def test_upload_without_as_version_of_starts_new_root(fresh_db):
    """Same name + no as_version_of = independent artifact, not a version."""
    a = _upload("notes.md", b"first").json()
    b = _upload("notes.md", b"second").json()
    assert a["parentId"] is None and a["version"] == 1
    assert b["parentId"] is None and b["version"] == 1
    # Both root, neither in the other's chain
    assert client.get(f"/api/v1/artifacts/{a['id']}/versions").json()["count"] == 1
    assert client.get(f"/api/v1/artifacts/{b['id']}/versions").json()["count"] == 1


# ---------------------------------------------------------------------------
# Tags enumeration
# ---------------------------------------------------------------------------

def test_list_tags_dedup(fresh_db):
    _upload("a", b"a", tags=["x", "y"])
    _upload("b", b"b", tags=["y", "z"])
    _upload("c", b"c", tags=["z"])

    resp = client.get("/api/v1/artifacts/tags").json()
    assert resp["tags"] == ["x", "y", "z"]
    assert resp["count"] == 3


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def test_delete_artifact(fresh_db):
    art = _upload("trash.txt", b"x").json()
    resp = client.delete(f"/api/v1/artifacts/{art['id']}")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": art["id"], "ok": True}

    # Subsequent fetch is 404
    assert client.get(f"/api/v1/artifacts/{art['id']}").status_code == 404


def test_delete_404(fresh_db):
    resp = client.delete("/api/v1/artifacts/art_nonexistent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Folders
# ---------------------------------------------------------------------------

def test_upload_defaults_to_uploads_folder(fresh_db):
    resp = _upload("plain.txt", b"x")
    assert resp.json()["folderPath"] == "/Uploads"


def test_upload_with_explicit_folder(fresh_db):
    files = {"file": ("x.png", io.BytesIO(b"x"), "image/png")}
    resp = client.post("/api/v1/artifacts", files=files, data={"folder_path": "/Designs/Mockups"})
    assert resp.status_code == 200
    assert resp.json()["folderPath"] == "/Designs/Mockups"


def test_list_filter_by_folder(fresh_db):
    _upload("a.txt", b"a")  # defaults to /Uploads
    files = {"file": ("b.txt", io.BytesIO(b"b"), "text/plain")}
    client.post("/api/v1/artifacts", files=files, data={"folder_path": "/Reference"})
    files2 = {"file": ("c.txt", io.BytesIO(b"c"), "text/plain")}
    client.post("/api/v1/artifacts", files=files2, data={"folder_path": "/Reference"})

    resp = client.get("/api/v1/artifacts?folder=/Reference").json()
    assert {i["name"] for i in resp["items"]} == {"b.txt", "c.txt"}

    resp_uploads = client.get("/api/v1/artifacts?folder=/Uploads").json()
    assert {i["name"] for i in resp_uploads["items"]} == {"a.txt"}


def test_folders_endpoint_lists_distinct_paths(fresh_db):
    _upload("a", b"a")  # /Uploads
    files = {"file": ("b", io.BytesIO(b"b"), "text/plain")}
    client.post("/api/v1/artifacts", files=files, data={"folder_path": "/Designs"})
    files2 = {"file": ("c", io.BytesIO(b"c"), "text/plain")}
    client.post("/api/v1/artifacts", files=files2, data={"folder_path": "/Designs"})

    resp = client.get("/api/v1/artifacts/folders").json()
    by_path = {f["path"]: f for f in resp["folders"]}
    assert by_path["/Uploads"]["count"] == 1
    assert by_path["/Uploads"]["isDefault"] is True
    assert by_path["/Designs"]["count"] == 2
    assert by_path["/Designs"]["isDefault"] is False
    assert resp["count"] == 2


# ---------------------------------------------------------------------------
# PATCH
# ---------------------------------------------------------------------------

def test_patch_move_folder(fresh_db):
    art = _upload("x.png", b"x", tags=["design"]).json()
    resp = client.patch(
        f"/api/v1/artifacts/{art['id']}",
        data={"folder_path": "/Archive/2026"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["folderPath"] == "/Archive/2026"
    # Original tag list untouched by this patch
    assert body["tags"] == ["design"]


def test_patch_replace_tags(fresh_db):
    art = _upload("x.png", b"x", tags=["old"]).json()
    resp = client.patch(
        f"/api/v1/artifacts/{art['id']}",
        data={"tags": '["new","shiny"]'},
    )
    assert resp.status_code == 200
    assert resp.json()["tags"] == ["new", "shiny"]


def test_patch_invalid_tags_json(fresh_db):
    art = _upload("x.png", b"x").json()
    resp = client.patch(
        f"/api/v1/artifacts/{art['id']}",
        data={"tags": "not-json"},
    )
    assert resp.status_code == 400


def test_patch_404(fresh_db):
    resp = client.patch("/api/v1/artifacts/art_nonexistent", data={"folder_path": "/x"})
    assert resp.status_code == 404
