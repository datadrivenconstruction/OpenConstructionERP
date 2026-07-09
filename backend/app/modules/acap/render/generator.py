"""Render orchestration: floor-plan -> prompt -> GeminiGen -> object storage.

Persists an :class:`~app.modules.acap.models.render.RenderRecord` per attempt.
On a provider failure the record is marked ``failed`` (with the error) and
returned — never raised past this layer — so the audit row survives the
request's commit. A MISSING API key is the caller's gate (checked before this
runs), not this function's concern.

The generated image is downloaded and re-uploaded to the fork's own object
storage (local / MinIO) via :func:`app.core.storage.get_storage_backend`, so
the durable URL is ours, not the provider's expiring one.
"""

from __future__ import annotations

import uuid as _uuid

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.acap.layout.schema import FloorPlan
from app.modules.acap.models.render import RenderRecord
from app.modules.acap.render.client import (
    DEFAULT_MODEL,
    RenderServiceError,
    generate_render_image,
)
from app.modules.acap.render.prompt import build_render_prompt

_STORAGE_PREFIX = "acap/renders"
_DOWNLOAD_MIN_BYTES = 1024  # smaller bodies are treated as truncated/empty


async def _download_image(media_url: str, client: httpx.AsyncClient) -> bytes:
    resp = await client.get(media_url)
    if resp.status_code >= 400:
        raise RenderServiceError(f"download: HTTP {resp.status_code} fetching image")
    content = resp.content
    if len(content) < _DOWNLOAD_MIN_BYTES:
        raise RenderServiceError(f"download: image body too small ({len(content)} bytes)")
    return content


async def generate_render(
    session: AsyncSession,
    project_id: _uuid.UUID,
    plan: FloorPlan,
    floor_plan_version: int,
    *,
    client: httpx.AsyncClient | None = None,
    storage: object | None = None,
) -> RenderRecord:
    """Render *plan* to an image, persist it to storage, and record the result.

    Always returns a persisted :class:`RenderRecord`; ``record.status`` is
    ``completed`` (with ``storage_key``/``source_url``) or ``failed`` (with
    ``error_message``). Caller must have verified the service is configured.
    """
    prompt = build_render_prompt(plan)
    record = RenderRecord(
        project_id=project_id,
        floor_plan_version=floor_plan_version,
        prompt=prompt,
        model=DEFAULT_MODEL,
        status="pending",
    )
    session.add(record)
    await session.flush()

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=60.0)
    try:
        result = await generate_render_image(prompt, client=client)
        media_url = result.get("media_url")
        if not media_url:
            raise RenderServiceError("provider returned no media URL")

        image_bytes = await _download_image(media_url, client)

        if storage is None:
            from app.core.storage import get_storage_backend

            storage = get_storage_backend()
        key = f"{_STORAGE_PREFIX}/{project_id}/{result.get('uuid') or record.id}.png"
        await storage.put(key, image_bytes)  # type: ignore[attr-defined]

        record.provider_uuid = result.get("uuid")
        record.source_url = media_url
        record.storage_key = key
        record.status = "completed"
    except RenderServiceError as exc:
        record.status = "failed"
        record.error_message = str(exc)[:500]
    finally:
        if owns_client:
            await client.aclose()

    await session.flush()
    return record
