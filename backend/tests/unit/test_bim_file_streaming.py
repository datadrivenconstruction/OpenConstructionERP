"""BIM model files are served and copied through disk/streams, never whole in RAM."""

import pathlib

import pytest
from fastapi import FastAPI
from fastapi.responses import FileResponse
from httpx import ASGITransport, AsyncClient

from app.core.storage import LocalStorageBackend
from app.modules.bim_hub import file_storage as bim_file_storage
from app.modules.bim_hub import router as routes

PAYLOAD = b"ISO-10303-21;" + bytes(range(256)) * 40


def _no_get(*_a, **_kw):
    raise AssertionError("backend.get() loads the whole blob into memory")


async def _serve(backend, key, media_type="application/octet-stream", filename="Model.ifc"):
    app = FastAPI()

    @app.get("/dl")
    async def dl():
        return await routes._stored_blob_response(backend, key, media_type, filename)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        return await client.get("/dl")


@pytest.mark.asyncio
async def test_local_blob_is_served_by_file_response(tmp_path, monkeypatch):
    backend = LocalStorageBackend(tmp_path)
    await backend.put("bim/p/m/original.ifc", PAYLOAD)
    monkeypatch.setattr(backend, "get", _no_get)

    direct = await routes._stored_blob_response(backend, "bim/p/m/original.ifc", "application/octet-stream", "M.ifc")
    assert isinstance(direct, FileResponse)

    resp = await _serve(backend, "bim/p/m/original.ifc")
    assert resp.status_code == 200
    assert resp.content == PAYLOAD
    assert resp.headers["content-length"] == str(len(PAYLOAD))
    assert "attachment" in resp.headers["content-disposition"]
    assert "Model.ifc" in resp.headers["content-disposition"]


class _RemoteBackend:
    """An S3-like backend: no local path, chunked open_stream, size() known."""

    def __init__(self, blob: bytes) -> None:
        self.blob = blob
        self.get = _no_get

    def local_path(self, _key):
        return None

    async def size(self, _key):
        return len(self.blob)

    async def open_stream(self, _key):
        for i in range(0, len(self.blob), 1000):
            yield self.blob[i : i + 1000]


@pytest.mark.asyncio
async def test_remote_blob_is_streamed_in_chunks_with_length():
    resp = await _serve(_RemoteBackend(PAYLOAD), "k", media_type="model/gltf-binary", filename="M.glb")
    assert resp.status_code == 200
    assert resp.content == PAYLOAD
    assert resp.headers["content-length"] == str(len(PAYLOAD))
    assert resp.headers["content-type"].startswith("model/gltf-binary")


@pytest.mark.asyncio
async def test_document_copy_keeps_the_document_and_never_reads_it_whole(tmp_path, monkeypatch):
    backend = LocalStorageBackend(tmp_path / "store")
    monkeypatch.setattr(bim_file_storage, "_backend", lambda: backend)
    doc = tmp_path / "docs" / "tower.ifc"
    doc.parent.mkdir()
    doc.write_bytes(PAYLOAD)

    def no_read_bytes(self):
        raise AssertionError(f"read_bytes({self}) loads the whole CAD file")

    monkeypatch.setattr(pathlib.Path, "read_bytes", no_read_bytes)
    key = await routes._copy_document_to_original_cad(doc, "p", "m", ".ifc", len(PAYLOAD))
    monkeypatch.undo()

    # LocalStorageBackend.put_stream MOVES its source: the document must survive.
    assert doc.read_bytes() == PAYLOAD
    assert key == bim_file_storage.original_cad_key("p", "m", ".ifc")
    assert backend.local_path(key).read_bytes() == PAYLOAD
