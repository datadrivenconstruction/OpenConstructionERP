"""Helpers for resumable BIM CAD uploads.

The resumable upload flow stores multipart session state in BIMModel.metadata_
so the upload can be resumed from the model record without a separate table.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from app.core.storage import MultipartSession, PartInfo
from app.modules.bim_hub.models import BIMModel

UPLOAD_METADATA_KEY = "resumable_upload"
DEFAULT_CHUNK_SIZE_BYTES = 8 * 1024 * 1024


def _model_metadata(model: BIMModel) -> dict[str, Any]:
    return dict(model.metadata_ or {})


def get_manifest(model: BIMModel) -> dict[str, Any] | None:
    manifest = _model_metadata(model).get(UPLOAD_METADATA_KEY)
    return dict(manifest) if isinstance(manifest, dict) else None


def set_manifest(model: BIMModel, manifest: dict[str, Any] | None) -> None:
    metadata = _model_metadata(model)
    if manifest is None:
        metadata.pop(UPLOAD_METADATA_KEY, None)
    else:
        metadata[UPLOAD_METADATA_KEY] = manifest
    model.metadata_ = metadata


def create_manifest(*, upload_id: str, key: str, filename: str, file_size: int, chunk_size_bytes: int, content_type: str | None = None, model_format: str | None = None, project_id: str | None = None, model_id: str | None = None, name: str | None = None, discipline: str | None = None, conversion_depth: str | None = None) -> dict[str, Any]:
    return {
        "upload_id": upload_id,
        "key": key,
        "filename": filename,
        "file_size": file_size,
        "chunk_size_bytes": chunk_size_bytes,
        "content_type": content_type or "application/octet-stream",
        "model_format": model_format,
        "project_id": project_id,
        "model_id": model_id,
        "name": name,
        "discipline": discipline,
        "conversion_depth": conversion_depth,
        "started_at": datetime.now(UTC).isoformat(),
        "parts": {},
    }


def session_from_manifest(manifest: dict[str, Any]) -> MultipartSession:
    return MultipartSession(
        upload_id=str(manifest["upload_id"]),
        key=str(manifest["key"]),
        backend=str(manifest.get("backend") or "local"),
        started_at=datetime.now(UTC),
        metadata={
            k: v
            for k, v in manifest.items()
            if k not in {"upload_id", "key", "started_at", "parts"}
        },
    )


def parts_from_manifest(manifest: dict[str, Any]) -> list[PartInfo]:
    raw_parts = manifest.get("parts") or {}
    if not isinstance(raw_parts, dict):
        return []
    parts: list[PartInfo] = []
    for key, value in raw_parts.items():
        try:
            part_number = int(key)
        except (TypeError, ValueError):
            continue
        if not isinstance(value, dict):
            continue
        etag = str(value.get("etag") or "")
        if not etag:
            continue
        try:
            size_bytes = int(value.get("size_bytes") or 0)
        except (TypeError, ValueError):
            size_bytes = 0
        parts.append(PartInfo(part_number=part_number, etag=etag, size_bytes=size_bytes))
    parts.sort(key=lambda p: p.part_number)
    return parts


def uploaded_bytes(parts: Iterable[PartInfo]) -> int:
    return sum(part.size_bytes for part in parts)


def next_part_number(parts: Iterable[PartInfo]) -> int:
    max_seen = 0
    for part in parts:
        if part.part_number > max_seen:
            max_seen = part.part_number
    return max_seen + 1


def remember_part(manifest: dict[str, Any], part: PartInfo) -> dict[str, Any]:
    parts = manifest.setdefault("parts", {})
    if not isinstance(parts, dict):
        parts = {}
        manifest["parts"] = parts
    parts[str(part.part_number)] = {
        "etag": part.etag,
        "size_bytes": part.size_bytes,
        "uploaded_at": datetime.now(UTC).isoformat(),
    }
    return manifest
