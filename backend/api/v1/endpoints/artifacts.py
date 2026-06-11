"""
Artifacts router — shared deliverable file storage.

Provides CRUD for the Artifact model: list (with tag/name filter),
metadata fetch, raw blob download, upload (multipart/form-data),
and tag enumeration.

Auth: open in this iteration (調研階段先快上); the route prefix is
/api/v1/artifacts and is registered in main.py.
"""
import io
import json
import uuid
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from db import repository as repo
from db import database as db_module
from db.models import Artifact


router = APIRouter()


def _sessionmaker():
    """Resolve AsyncSessionLocal at call time so test monkeypatches
    on db_module.AsyncSessionLocal are honored. (Importing the symbol
    at module load would freeze the reference to whatever engine the
    process started with.)"""
    return db_module.AsyncSessionLocal


@router.get("/artifacts")
async def list_artifacts(
    tag: Optional[str] = Query(None, description="Filter by single tag (exact match)"),
    q: Optional[str] = Query(None, description="Case-insensitive name substring filter"),
    folder: Optional[str] = Query(None, description="Filter by exact folder_path (e.g. '/Uploads')"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """
    List user-uploaded artifacts (metadata only — no blob in payload).

    Default sort: newest first. Tag/folder filters use Python post-
    filtering because SQLite stores tags and folder paths as plain
    text/JSON, no DB-side containment operator.
    """
    async with _sessionmaker()() as session:
        rows = await repo.list_artifacts(session, limit=limit, offset=offset)
    items = [a.to_dict() for a in rows]
    if tag:
        items = [a for a in items if tag in (a["tags"] or [])]
    if q:
        ql = q.lower()
        items = [a for a in items if ql in a["name"].lower()]
    if folder:
        items = [a for a in items if (a.get("folderPath") or "/Uploads") == folder]
    return {"items": items, "count": len(items)}


@router.get("/artifacts/folders")
async def list_folders():
    """
    Enumerate distinct folder paths currently in use, with per-folder
    file counts. Sorted alphabetically so the front-end can render a
    stable folder tree.
    """
    async with _sessionmaker()() as session:
        rows = await repo.list_artifacts(session, limit=1000, offset=0)
    counts: dict = {}
    for a in rows:
        fp = a.folder_path or "/Uploads"
        counts[fp] = counts.get(fp, 0) + 1
    folders = [
        {"path": p, "count": c, "isDefault": p == "/Uploads"}
        for p, c in sorted(counts.items())
    ]
    return {"folders": folders, "count": len(folders)}


@router.get("/artifacts/tags")
async def list_tags():
    """Enumerate all distinct tags currently in use across artifacts.

    Returned alphabetically for a stable, predictable client experience
    — front-end tag-filter UIs rely on this order for consistency.
    """
    async with _sessionmaker()() as session:
        rows = await repo.list_artifacts(session, limit=1000, offset=0)
    seen = set()
    for a in rows:
        for t in (a.tags or []):
            seen.add(t)
    return {"tags": sorted(seen), "count": len(seen)}


@router.get("/artifacts/{artifact_id}")
async def get_artifact(artifact_id: str):
    """Fetch single artifact metadata (no blob)."""
    async with _sessionmaker()() as session:
        art = await repo.get_artifact(session, artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail=f"Artifact {artifact_id} not found")
    return art.to_dict()


@router.get("/artifacts/{artifact_id}/blob")
async def download_artifact(artifact_id: str):
    """
    Stream the raw blob with the artifact's mime type. Filename for the
    browser save dialog comes from the original upload name.
    """
    async with _sessionmaker()() as session:
        art = await repo.get_artifact(session, artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail=f"Artifact {artifact_id} not found")
    headers = {
        "Content-Disposition": f'attachment; filename="{art.name}"',
        "X-Artifact-Id": art.id,
        "X-Artifact-Version": str(art.version),
    }
    return StreamingResponse(
        io.BytesIO(art.content),
        media_type=art.mime_type or "application/octet-stream",
        headers=headers,
    )


@router.get("/artifacts/{artifact_id}/versions")
async def get_artifact_versions(artifact_id: str):
    """
    Walk the parent_id chain to return all versions of the same logical
    artifact, oldest first. The chain is rooted at the row whose own
    parent_id is None (or matches itself).
    """
    async with _sessionmaker()() as session:
        art = await repo.get_artifact(session, artifact_id)
        if not art:
            raise HTTPException(status_code=404, detail=f"Artifact {artifact_id} not found")
        root = art
        # Walk up to find the root of the version chain.
        while root.parent_id:
            parent = await repo.get_artifact(session, root.parent_id)
            if not parent or parent.id == root.id:
                break
            root = parent
        # Now collect the whole chain from the root downward.
        chain = [root.to_dict()]
        children = await repo.list_artifacts_by_parent(session, root.id)
        chain.extend(c.to_dict() for c in children)
    return {"items": chain, "count": len(chain)}


@router.post("/artifacts")
async def upload_artifact(
    file: UploadFile = File(..., description="The file to upload"),
    tags: Optional[str] = Form(None, description="JSON array of tag strings, e.g. ['design','screenshot']"),
    description: Optional[str] = Form("", description="Free-form description"),
    uploader: Optional[str] = Form(None, description="Who is uploading (display name)"),
    as_version_of: Optional[str] = Form(None, description="Existing artifact id — if set, this upload becomes a new version of that artifact"),
    folder_path: Optional[str] = Form(None, description="Virtual folder path (defaults to '/Uploads' if absent)"),
):
    """
    Upload a file. Multipart form-data with one file part plus optional
    form fields. If ``as_version_of`` is provided, the new row's parent_id
    points at that existing row and version auto-increments; otherwise a
    brand new artifact is created with version=1.
    """
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file upload")

    tag_list: List[str] = []
    if tags:
        try:
            parsed = json.loads(tags)
            if not isinstance(parsed, list):
                raise ValueError("tags must be a JSON array of strings")
            tag_list = [str(t) for t in parsed if t]
        except (ValueError, json.JSONDecodeError) as e:
            raise HTTPException(status_code=400, detail=f"Invalid tags JSON: {e}")

    new_id = f"art_{uuid.uuid4().hex[:16]}"
    new_version = 1
    parent_id = None
    if as_version_of:
        async with _sessionmaker()() as session:
            existing = await repo.get_artifact(session, as_version_of)
        if not existing:
            raise HTTPException(status_code=404, detail=f"as_version_of target {as_version_of} not found")
        # Walk to the latest in the version chain (linear chain, no
        # branching: a brand-new row's parent_id always points to the
        # previous latest, so we just follow parent_id upward).
        latest = await _walk_to_latest(existing)
        new_version = latest.version + 1
        parent_id = latest.id

    artifact = Artifact(
        id=new_id,
        name=file.filename or "untitled",
        mime_type=file.content_type or "application/octet-stream",
        size_bytes=len(content),
        content=content,
        tags=tag_list,
        description=description or "",
        uploader=uploader or None,
        version=new_version,
        parent_id=parent_id,
        folder_path=folder_path or "/Uploads",
    )
    async with _sessionmaker()() as session:
        await repo.create_artifact(session, artifact)
    return artifact.to_dict()


@router.delete("/artifacts/{artifact_id}")
async def delete_artifact(artifact_id: str):
    """
    Hard-delete a single artifact (and orphan its descendants — they
    keep their data but lose the parent link). No cascade delete in this
    iteration; users decide per-version.
    """
    async with _sessionmaker()() as session:
        art = await repo.get_artifact(session, artifact_id)
        if not art:
            raise HTTPException(status_code=404, detail=f"Artifact {artifact_id} not found")
        await repo.delete_artifact(session, artifact_id)
    return {"deleted": artifact_id, "ok": True}


@router.patch("/artifacts/{artifact_id}")
async def patch_artifact(
    artifact_id: str,
    folder_path: Optional[str] = Form(None, description="Move artifact to this virtual folder"),
    tags: Optional[str] = Form(None, description="Replace tags with this JSON array"),
    description: Optional[str] = Form(None, description="Replace description"),
):
    """
    Edit mutable metadata of a user-uploaded artifact. All fields are
    optional; only the supplied ones are updated. Pass a field with
    empty string to clear it (folder_path is the exception — it
    defaults to '/Uploads' if you set it to '').

    Blob content is intentionally not editable; re-upload with
    ``as_version_of`` to create a new version instead.
    """
    async with _sessionmaker()() as session:
        art = await repo.get_artifact(session, artifact_id)
        if not art:
            raise HTTPException(status_code=404, detail=f"Artifact {artifact_id} not found")
        if folder_path is not None:
            art.folder_path = folder_path or "/Uploads"
        if tags is not None:
            try:
                parsed = json.loads(tags)
                if not isinstance(parsed, list):
                    raise ValueError("tags must be a JSON array of strings")
                art.tags = [str(t) for t in parsed if t]
            except (ValueError, json.JSONDecodeError) as e:
                raise HTTPException(status_code=400, detail=f"Invalid tags JSON: {e}")
        if description is not None:
            art.description = description
        await session.commit()
        await session.refresh(art)
    return art.to_dict()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

async def _walk_to_latest(art: Artifact) -> Artifact:
    """Follow parent_id upward to the most recent artifact in the chain.

    Version chains are linear (one parent → one child → one grandchild).
    The latest version is the row with the highest version that has no
    children of its own.
    """
    current = art
    # Cap at a sensible depth so a corrupted chain can't loop forever.
    for _ in range(1000):
        async with _sessionmaker()() as session:
            children = await repo.list_artifacts_by_parent(session, current.id)
        if not children:
            return current
        # Linear chain assumption: pick the only child. If branching
        # ever appears, the highest-versioned child wins.
        current = max(children, key=lambda c: c.version)
    return current
