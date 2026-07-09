"""Async GeminiGen (snapgen.ai) image client — submit -> poll -> media URL.

Ports the proven ``scripts.geminigen_client`` submit/poll/extract contract to
async httpx for server-side use. The provider is reached over plain HTTP:

    POST {BASE_URL}/generate_image   (multipart, header x-api-key)  -> {uuid, status}
    GET  {BASE_URL}/history/{uuid}   (header x-api-key)             -> {status, ...}
        status: 1=processing, 2=completed, 3=failed

SECURITY: the API key is read from ``$GEMINIGEN_API_KEY`` and is NEVER logged,
echoed, or placed in an exception message. Absence is a first-class, non-fatal
state (:class:`RenderNotConfiguredError`) so the endpoint can return a clean
"not configured" instead of a 500 — mirrors the Phase 3 LLM key-gate.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx

_DEFAULT_BASE_URL = "https://api.snapgen.ai/uapi/v1"
DEFAULT_MODEL = "nano-banana-pro"  # generate_image family
# History API path is not in the provider's PDF docs; probe these in order.
_HISTORY_PATH_CANDIDATES = ("history/{uuid}", "generations/{uuid}")

_STATUS_COMPLETED = 2
_STATUS_FAILED = 3


class RenderServiceError(Exception):
    """A render call failed (submit/poll/HTTP error). Message never holds the key."""


class RenderNotConfiguredError(RenderServiceError):
    """No GEMINIGEN_API_KEY set — the render service is not configured."""


class RenderTimeoutError(RenderServiceError):
    """The job did not reach a terminal status within the polling budget."""


def render_service_configured() -> bool:
    """True iff a GeminiGen API key is present (existence check only — the key
    bytes are never returned or logged)."""
    return bool(os.environ.get("GEMINIGEN_API_KEY"))


def _base_url() -> str:
    return os.environ.get("GEMINIGEN_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")


def _require_api_key() -> str:
    key = os.environ.get("GEMINIGEN_API_KEY")
    if not key:
        raise RenderNotConfiguredError("GEMINIGEN_API_KEY is not set")
    return key


def extract_media_url(result: dict[str, Any]) -> str | None:
    """Pull the image URL out of a completed submit/history payload, tolerating
    both provider result shapes. Returns None when no URL is present yet."""
    url = result.get("generate_result")
    if url:
        return url
    data = result.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0].get("image_url") or data[0].get("file_download_url")
    return None


def _image_fields(prompt: str, model: str, aspect: str, resolution: str, output_format: str) -> dict[str, str]:
    fields = {"prompt": prompt, "resolution": resolution, "aspect_ratio": aspect}
    if model:  # generate_image family sends the model field
        fields["model"] = model
    if output_format:
        fields["output_format"] = output_format
    return fields


def _multipart_parts(fields: dict[str, str], refs: list[str]) -> list[tuple[str, tuple[None, str]]]:
    # Force multipart for ALL parts (incl. plain fields) — urlencoding mangles
    # values like "9:16" and the provider rejects the wire shape. httpx sends
    # multipart when `files=` is used; (None, value) makes each part a form field.
    parts: list[tuple[str, tuple[None, str]]] = [(k, (None, v)) for k, v in fields.items()]
    parts.extend(("file_urls", (None, ref)) for ref in refs)
    return parts


def _raise_for_status(resp: httpx.Response, what: str) -> None:
    if resp.status_code < 400:
        return
    body_msg = ""
    try:
        body = resp.json()
        body_msg = body.get("error_message", "") or body.get("message", "")
    except (ValueError, KeyError):
        body_msg = resp.text[:200]
    raise RenderServiceError(f"{what}: HTTP {resp.status_code} {body_msg}".strip())


async def _discover_history_template(client: httpx.AsyncClient, uuid: str, headers: dict[str, str]) -> str:
    last: int | None = None
    for candidate in _HISTORY_PATH_CANDIDATES:
        url = f"{_base_url()}/{candidate.format(uuid=uuid)}"
        try:
            resp = await client.get(url, headers=headers)
        except httpx.HTTPError:
            last = -1
            continue
        if resp.status_code < 400:
            return candidate
        last = resp.status_code
    raise RenderServiceError(
        f"Could not find GeminiGen History API endpoint (tried {list(_HISTORY_PATH_CANDIDATES)}, last {last})"
    )


async def generate_render_image(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    aspect: str = "4:3",
    resolution: str = "2K",
    output_format: str = "png",
    refs: list[str] | None = None,
    poll_timeout: float = 420.0,
    poll_interval: float = 6.0,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Submit a render, poll to completion, return ``{uuid, media_url, raw}``.

    Raises:
        RenderNotConfiguredError: no API key set (caller should 400, not 500).
        RenderServiceError: provider HTTP/4xx/5xx error or a failed (status=3) job.
        RenderTimeoutError: no terminal status within *poll_timeout* seconds.
    """
    key = _require_api_key()
    headers = {"x-api-key": key}
    refs = refs or []
    fields = _image_fields(prompt, model, aspect, resolution, output_format)
    parts = _multipart_parts(fields, refs)

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=60.0)
    try:
        resp = await client.post(f"{_base_url()}/generate_image", files=parts, headers=headers)
        _raise_for_status(resp, "submit")
        try:
            submission = resp.json()
        except ValueError as exc:
            raise RenderServiceError(f"submit: non-JSON body {resp.text[:200]}") from exc

        uuid = submission.get("uuid")
        # Fast path: already completed on submit.
        if submission.get("status") == _STATUS_COMPLETED and extract_media_url(submission):
            return {"uuid": uuid, "media_url": extract_media_url(submission), "raw": submission}
        if not uuid:
            raise RenderServiceError("submit: response missing uuid")

        template = await _discover_history_template(client, uuid, headers)
        poll_url = f"{_base_url()}/{template.format(uuid=uuid)}"
        deadline = time.monotonic() + poll_timeout
        while True:
            resp = await client.get(poll_url, headers=headers)
            _raise_for_status(resp, "poll")
            body = resp.json()
            status = body.get("status")
            if status == _STATUS_COMPLETED:
                return {"uuid": uuid, "media_url": extract_media_url(body), "raw": body}
            if status == _STATUS_FAILED:
                err = body.get("error_message") or body.get("error_code") or "unknown"
                raise RenderServiceError(f"job {uuid} failed: {err}")
            if time.monotonic() >= deadline:
                raise RenderTimeoutError(f"job {uuid} did not complete within {poll_timeout}s (last status={status})")
            if poll_interval > 0:
                await asyncio.sleep(poll_interval)
    finally:
        if owns_client:
            await client.aclose()
