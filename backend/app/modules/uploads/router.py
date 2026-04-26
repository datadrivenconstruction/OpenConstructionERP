"""Direct upload routes.

Endpoints:
    PUT  /local/{token}    — Consume an HMAC-signed token minted by
                              :meth:`LocalStorageBackend.presigned_put_url`
                              and stream the request body into the storage
                              backend (single PUT or multipart part).

The token payload is produced by
:func:`app.core.storage._sign_local_upload_token` and verified here via
:func:`app.core.storage._verify_local_upload_token`. Both helpers live in
``app.core.storage`` so this router treats them as opaque and only relies
on the documented payload shape.

Token payload shape::

    {
        "key": "<storage key>",
        "expires_at": <unix-ts>,
        "content_type": "<mime>" | "",
        # Multipart-only (W0.5):
        "upload_id": "<hex>"     ,  # optional
        "part_number": <int>     ,  # optional, 1-based
    }

When ``upload_id`` and ``part_number`` are both present the request body
is uploaded as a single multipart part. Otherwise the body is written to
``key`` via :meth:`LocalStorageBackend.put`.

This route is only valid against the local backend. When
``STORAGE_BACKEND=s3`` the S3 backend itself mints true presigned URLs
that bypass this app — calling here returns HTTP 400 to prevent
silent misroutes during operator misconfiguration.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, HTTPException, Request, status

from app.core.storage import (
    LocalStorageBackend,
    MultipartSession,
    _verify_local_upload_token,
    get_storage_backend,
)
from app.modules.uploads.schemas import LocalUploadResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Direct Uploads"])

# Bodies up to this size are read in one shot via ``await request.body()``
# (cheap, simple). Anything larger is streamed chunk-by-chunk so the
# event loop never holds the full payload in memory at once.
_INLINE_BODY_LIMIT_BYTES: int = 10 * 1024 * 1024  # 10 MiB


async def _read_body(request: Request) -> bytes:
    """Read the request body, streaming once the inline limit is exceeded.

    Small bodies (<= 10 MiB) take the fast path: a single ``await
    request.body()`` call. Larger bodies are pulled chunk-by-chunk via
    ``request.stream()`` and assembled into a ``bytes`` buffer so the
    LocalStorageBackend write API (which expects ``bytes``) can consume
    them. The streaming path keeps Starlette from buffering the whole
    request into a single ``bytes`` object before our handler ever runs.
    """
    content_length_header = request.headers.get("content-length")
    if content_length_header is not None:
        try:
            content_length = int(content_length_header)
        except ValueError:
            content_length = None
    else:
        content_length = None

    if content_length is not None and content_length <= _INLINE_BODY_LIMIT_BYTES:
        return await request.body()

    # Streaming path — also used when Content-Length is missing.
    chunks: list[bytes] = []
    async for chunk in request.stream():
        if chunk:
            chunks.append(chunk)
    return b"".join(chunks)


@router.put(
    "/local/{token}",
    response_model=LocalUploadResponse,
    status_code=status.HTTP_200_OK,
)
async def put_local_upload(token: str, request: Request) -> LocalUploadResponse:
    """Consume an HMAC-signed token and write the request body to storage.

    The signature is verified via
    :func:`app.core.storage._verify_local_upload_token`; tampered or
    expired tokens return 403. When the active backend is not a
    :class:`LocalStorageBackend`, the route returns 400 — the matching
    S3 backend mints true presigned URLs that bypass this app entirely.
    """
    backend = get_storage_backend()
    if not isinstance(backend, LocalStorageBackend):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Local upload route only valid when STORAGE_BACKEND=local. "
                "Use the backend's native presigned URL instead."
            ),
        )

    payload = _verify_local_upload_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or expired upload token",
        )

    key = payload.get("key")
    if not isinstance(key, str) or not key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Upload token is missing a valid 'key'",
        )

    body = await _read_body(request)

    upload_id = payload.get("upload_id")
    part_number = payload.get("part_number")

    if isinstance(upload_id, str) and upload_id and isinstance(part_number, int):
        # Multipart path — reconstruct a session reference and write one
        # part. The local backend's upload_part only consults
        # session.upload_id and session.backend so we don't need the
        # original started_at/metadata; "now" is a perfectly valid
        # placeholder for resumed sessions.
        session = MultipartSession(
            upload_id=upload_id,
            key=key,
            backend="local",
            started_at=datetime.now(UTC),
            metadata={},
        )
        try:
            part = await backend.upload_part(session, part_number, body)
        except ValueError as exc:
            # Bad part_number, key escape, etc.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        logger.info(
            "Local upload part written: key=%s upload_id=%s part=%d size=%d",
            key,
            upload_id,
            part_number,
            part.size_bytes,
        )
        return LocalUploadResponse(
            key=key,
            etag=part.etag,
            size_bytes=part.size_bytes,
        )

    # Single-shot PUT path — write the whole body at the canonical key.
    try:
        await backend.put(key, body)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    # The local backend's put() returns None, so we compute the etag
    # ourselves to keep the response shape stable across part-vs-whole
    # uploads. SHA-256 hex matches what upload_part returns and what
    # the multipart pipeline uses elsewhere in storage.py.
    etag = hashlib.sha256(body).hexdigest()
    size_bytes = len(body)
    logger.info(
        "Local upload object written: key=%s size=%d", key, size_bytes,
    )
    return LocalUploadResponse(
        key=cast(str, key),
        etag=etag,
        size_bytes=size_bytes,
    )
