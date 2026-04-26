"""Integration: /api/v1/uploads/local/{token} PUT endpoint.

Verifies the HMAC-signed direct PUT route consumes presigned tokens minted by
:meth:`app.core.storage.LocalStorageBackend.presigned_put_url`.

Coverage:
    1. Round-trip a 50 KiB blob through a valid token.
    2. Tampered token signatures are rejected with 403.
    3. Expired tokens are rejected with 403 (verified against the same
       backend instance that minted them — i.e. same HMAC secret).
    4. Tokens carrying ``upload_id`` + ``part_number`` write into the
       multipart staging dir, not the canonical key.
    5. With STORAGE_BACKEND=s3 the route refuses with 400.

We bypass the full module loader and mount only the uploads router on a
minimal FastAPI app — keeps each test under a second on a cold cache.
"""

from __future__ import annotations

import base64
import json
import secrets
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.storage import (
    LocalStorageBackend,
    _sign_local_upload_token,
)
from app.modules.uploads.router import router as uploads_router

pytestmark = pytest.mark.integration


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def local_backend(tmp_path: Path) -> LocalStorageBackend:
    """LocalStorageBackend rooted at a per-test tmpdir."""
    return LocalStorageBackend(tmp_path)


@pytest_asyncio.fixture
async def client(
    local_backend: LocalStorageBackend, monkeypatch: pytest.MonkeyPatch,
):
    """Minimal FastAPI app with the uploads router mounted.

    ``get_storage_backend`` is monkey-patched at the router module's
    import site so the handler sees our tmp-path backend instead of
    the real cached singleton.
    """
    monkeypatch.setattr(
        "app.modules.uploads.router.get_storage_backend",
        lambda: local_backend,
    )

    app = FastAPI()
    app.include_router(uploads_router, prefix="/api/v1/uploads")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── 1. Happy-path single PUT ──────────────────────────────────────────────


async def test_local_upload_with_valid_token_writes_blob(
    client: AsyncClient, local_backend: LocalStorageBackend,
) -> None:
    """A valid presigned URL + 50 KiB body → blob lands at the keyed path."""
    key = "test/blob.bin"
    payload = secrets.token_bytes(50 * 1024)

    presigned = await local_backend.presigned_put_url(
        key=key,
        content_type="application/octet-stream",
        expires_seconds=600,
    )
    assert presigned.url.startswith("/api/v1/uploads/local/")
    token = presigned.url.rsplit("/", 1)[-1]

    resp = await client.put(
        f"/api/v1/uploads/local/{token}",
        content=payload,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["key"] == key
    assert body["size_bytes"] == len(payload)
    assert isinstance(body["etag"], str)
    assert body["etag"]

    # Round-trip: bytes survive intact.
    read_back = await local_backend.get(key)
    assert read_back == payload


# ── 2. Tampered signature → 403 ────────────────────────────────────────────


async def test_local_upload_with_tampered_token_returns_403(
    client: AsyncClient, local_backend: LocalStorageBackend,
) -> None:
    presigned = await local_backend.presigned_put_url(
        key="tampered/blob.bin", expires_seconds=600,
    )
    token = presigned.url.rsplit("/", 1)[-1]
    # Flip a byte inside the HMAC suffix.
    if token.endswith("aa"):
        bad = token[:-2] + "bb"
    else:
        bad = token[:-2] + "aa"

    resp = await client.put(
        f"/api/v1/uploads/local/{bad}",
        content=b"should never land",
    )
    assert resp.status_code == 403, resp.text
    # And the canonical key was NOT written.
    assert not await local_backend.exists("tampered/blob.bin")


# ── 3. Expired token → 403 ────────────────────────────────────────────────


async def test_local_upload_with_expired_token_returns_403(
    client: AsyncClient, local_backend: LocalStorageBackend,
) -> None:
    """``expires_seconds=-1`` mints a token whose ``expires_at`` is already
    in the past — the verifier must reject it on the same backend that
    signed it.
    """
    presigned = await local_backend.presigned_put_url(
        key="expired/blob.bin", expires_seconds=-1,
    )
    token = presigned.url.rsplit("/", 1)[-1]

    resp = await client.put(
        f"/api/v1/uploads/local/{token}",
        content=b"too late",
    )
    assert resp.status_code == 403, resp.text
    assert not await local_backend.exists("expired/blob.bin")


# ── 4. Multipart part upload via token ────────────────────────────────────


async def test_local_upload_with_part_number_writes_part(
    client: AsyncClient, local_backend: LocalStorageBackend,
) -> None:
    """A token carrying ``upload_id`` + ``part_number`` lands the body in
    the multipart staging dir, not at the canonical key.
    """
    key = "multipart/big.bin"
    session = await local_backend.initiate_multipart(key)

    # Hand-craft a token of the same shape ``presigned_put_url`` would
    # return for a part — the route doesn't care which signer minted
    # it as long as the HMAC checks out.
    payload: dict[str, object] = {
        "key": key,
        "expires_at": 9_999_999_999,  # year ~2286, plenty of headroom
        "content_type": "",
        "upload_id": session.upload_id,
        "part_number": 1,
    }
    token = _sign_local_upload_token(payload)

    chunk = b"\xab" * (4 * 1024)  # 4 KiB
    resp = await client.put(
        f"/api/v1/uploads/local/{token}", content=chunk,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["key"] == key
    assert body["size_bytes"] == len(chunk)
    assert body["etag"]

    # The part landed in the staging dir, not at the canonical key.
    staging_part = (
        local_backend.base_dir / ".multipart" / session.upload_id / "part-00001"
    )
    assert staging_part.is_file()
    assert staging_part.read_bytes() == chunk
    # Canonical key not yet written — that's complete_multipart's job.
    assert not await local_backend.exists(key)


# ── 5. S3 backend active → 400 ────────────────────────────────────────────


async def test_local_upload_route_returns_400_when_s3_backend_active(
    monkeypatch: pytest.MonkeyPatch, local_backend: LocalStorageBackend,
) -> None:
    """When the active backend is anything other than LocalStorageBackend
    the route refuses with 400 — the matching S3 backend mints true
    presigned URLs that bypass this app entirely.
    """

    # Stand in a non-local backend without requiring the optional
    # aioboto3 dependency. Anything that's-not-LocalStorageBackend is
    # enough to trip the isinstance() guard.
    class _StubS3Backend:
        pass

    monkeypatch.setattr(
        "app.modules.uploads.router.get_storage_backend",
        lambda: _StubS3Backend(),
    )

    app = FastAPI()
    app.include_router(uploads_router, prefix="/api/v1/uploads")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Token shape is irrelevant — the route must short-circuit before
        # it gets verified. Use a syntactically valid token to make sure
        # we're not just catching a ValueError on the split.
        body_b64 = (
            base64.urlsafe_b64encode(json.dumps({"key": "x"}).encode())
            .rstrip(b"=")
            .decode()
        )
        bogus_token = f"{body_b64}.deadbeef"
        resp = await ac.put(
            f"/api/v1/uploads/local/{bogus_token}",
            content=b"won't be written",
        )
    assert resp.status_code == 400, resp.text
    assert "STORAGE_BACKEND=local" in resp.json()["detail"]
