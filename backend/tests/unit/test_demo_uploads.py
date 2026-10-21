"""Public demo upload block: multipart and octet-stream bodies answer 403."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.middleware.demo_uploads import DEMO_UPLOADS_ERROR, DemoUploadBlockMiddleware


def _client(*, enabled: bool) -> TestClient:
    app = FastAPI()

    @app.post("/echo")
    async def echo(request: Request) -> dict[str, int]:
        return {"bytes": len(await request.body())}

    @app.get("/read")
    async def read() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(DemoUploadBlockMiddleware, enabled=enabled)
    return TestClient(app)


def test_multipart_refused_when_enabled() -> None:
    res = _client(enabled=True).post("/echo", files={"file": ("a.dwg", b"x" * 10)})
    assert res.status_code == 403
    assert res.json()["detail"]["error"] == DEMO_UPLOADS_ERROR


def test_octet_stream_refused_when_enabled() -> None:
    res = _client(enabled=True).post("/echo", content=b"abc", headers={"content-type": "application/octet-stream"})
    assert res.status_code == 403


@pytest.mark.parametrize("enabled", [True, False])
def test_json_and_reads_pass(enabled: bool) -> None:
    client = _client(enabled=enabled)
    assert client.post("/echo", json={"a": 1}).status_code == 200
    assert client.get("/read").status_code == 200


def test_multipart_passes_when_disabled() -> None:
    res = _client(enabled=False).post("/echo", files={"file": ("a.dwg", b"x" * 10)})
    assert res.status_code == 200
