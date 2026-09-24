# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The backup and the project bundle are built on disk, not in one piece in memory.

The core runs on a server with 3 GB for the application, its database and
everything else. A backup was already spooled to disk past 16 MiB, and then its
finishing step read the spool back whole to hash it and rewrite the manifest:
the entire archive in RAM, plus a second copy for the zip reader over it. The
project bundle never spooled at all. It was built in a ``BytesIO`` and handed to
the response as bytes, so a full scope with its models and drawings sat in
memory twice for the length of the download.

Both now go through files and fixed-size chunks. The tests below measure the
largest single read taken from the backup spool, which is the whole archive
before the change and one chunk after it, and check that the bundle route sends
a file from disk and deletes it once sent.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
import zipfile
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

_MEMBER = os.urandom(3 * 1024 * 1024)


class _MeasuredSpool(tempfile.SpooledTemporaryFile):
    """A spool that remembers the largest block any single read took from it."""

    largest_read = 0

    def read(self, *args: Any) -> bytes:
        data = super().read(*args)
        self.largest_read = max(self.largest_read, len(data))
        return data


def _backup_spool() -> _MeasuredSpool:
    spool = _MeasuredSpool(max_size=1024, mode="w+b", suffix=".zip")
    with zipfile.ZipFile(spool, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("data/projects.json", json.dumps([{"id": "p1"}]))
        zf.writestr("files/documents/model.glb", _MEMBER)
        zf.writestr("manifest.json", json.dumps({"format": "backup"}))
    return spool


def test_finishing_a_backup_reads_the_spool_in_chunks_and_keeps_every_member() -> None:
    from app.modules.backup.service import _STREAM_CHUNK_BYTES, _finalize_archive

    spool = _backup_spool()
    spool.seek(0)
    original = b"".join(iter(lambda: spool.read(_STREAM_CHUNK_BYTES), b""))
    spool.largest_read = 0
    manifest: dict[str, Any] = {"format": "backup"}

    size = _finalize_archive(spool, manifest, zipfile.ZIP_DEFLATED, 6)

    assert spool.largest_read <= _STREAM_CHUNK_BYTES, (
        f"a single read took {spool.largest_read} bytes from a {len(original)}-byte archive"
    )
    assert manifest["checksum"] == hashlib.sha256(original).hexdigest()
    spool.seek(0)
    with zipfile.ZipFile(spool) as zf:
        assert zf.testzip() is None
        assert zf.read("files/documents/model.glb") == _MEMBER
        assert json.loads(zf.read("data/projects.json")) == [{"id": "p1"}]
        assert json.loads(zf.read("manifest.json"))["checksum"] == manifest["checksum"]
        assert zf.namelist() == ["data/projects.json", "files/documents/model.glb", "manifest.json"]
    spool.seek(0, os.SEEK_END)
    assert spool.tell() == size
    spool.close()


def _stub_bundle_sources(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    from app.modules.projects import bundle_export

    async def rows_for_table(_session: Any, project_id: str, key: str, *_: Any) -> list[dict[str, Any]]:
        return [{"id": project_id, "name": "Riverside Block C"}] if key == "projects" else []

    drawing = tmp_path / "site-plan.pdf"
    drawing.write_bytes(b"%PDF-1.4 site plan")
    monkeypatch.setattr(bundle_export, "_rows_for_table", rows_for_table)
    monkeypatch.setattr(
        bundle_export,
        "_collect_attachment_paths",
        AsyncMock(return_value=[("attachments/documents/d1/site-plan.pdf", "fs", str(drawing))]),
    )


@pytest.fixture
def bundle_tempdir(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Any:
    target = tmp_path / "spool"
    target.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(target))
    return target


@pytest.mark.asyncio
async def test_the_bundle_is_written_to_a_file_on_disk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, bundle_tempdir: Any
) -> None:
    from app.modules.projects import bundle_export
    from app.modules.projects.file_manager_schemas import ExportOptions

    _stub_bundle_sources(monkeypatch, tmp_path)

    path = await bundle_export.export_bundle_to_file(
        MagicMock(), "p1", "Riverside Block C", "EUR", None, ExportOptions(scope="full")
    )

    assert os.path.dirname(path) == str(bundle_tempdir)
    with zipfile.ZipFile(path) as zf:
        assert zf.testzip() is None
        assert zf.read("attachments/documents/d1/site-plan.pdf") == b"%PDF-1.4 site plan"
        assert json.loads(zf.read("tables/projects.json"))[0]["name"] == "Riverside Block C"
    bundle_export.remove_bundle_file(path)
    assert list(bundle_tempdir.iterdir()) == []


@pytest.mark.asyncio
async def test_a_bundle_that_fails_half_way_leaves_no_file_behind(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, bundle_tempdir: Any
) -> None:
    from app.modules.projects import bundle_export
    from app.modules.projects.file_manager_schemas import ExportOptions

    _stub_bundle_sources(monkeypatch, tmp_path)
    monkeypatch.setattr(bundle_export, "_write_table", MagicMock(side_effect=RuntimeError("disk full")))

    with pytest.raises(RuntimeError, match="disk full"):
        await bundle_export.export_bundle_to_file(
            MagicMock(), "p1", "Riverside Block C", "EUR", None, ExportOptions(scope="full")
        )

    assert list(bundle_tempdir.iterdir()) == []


@pytest.mark.asyncio
async def test_the_bundle_route_sends_the_file_and_deletes_it_afterwards(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, bundle_tempdir: Any
) -> None:
    from fastapi.responses import FileResponse

    from app.modules.projects import router
    from app.modules.projects.file_manager_schemas import ExportOptions

    _stub_bundle_sources(monkeypatch, tmp_path)
    monkeypatch.setattr(
        router,
        "_verify_project_owner",
        AsyncMock(return_value=SimpleNamespace(name="Riverside Block C", currency="EUR")),
    )

    response = await router.post_export_bundle(
        project_id=uuid.uuid4(),
        options=ExportOptions(scope="full"),
        user_id="u1",
        payload={"email": "estimator@example.com"},
        session=MagicMock(),
        service=MagicMock(),
    )

    assert isinstance(response, FileResponse)
    assert response.headers["X-Bundle-Format"] == "ocep"
    assert os.path.exists(response.path)
    with zipfile.ZipFile(response.path) as zf:
        assert "manifest.json" in zf.namelist()

    await response.background()

    assert list(bundle_tempdir.iterdir()) == []
