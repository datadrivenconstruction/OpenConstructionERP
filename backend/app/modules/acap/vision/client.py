"""Async Gemini vision client — extract floor-plan data from images.

Uses the Gemini model REST API (generativelanguage.googleapis.com/v1beta)
directly via httpx — NO google-generativeai SDK. Mirrors the pattern of
:mod:`app.modules.acap.render.client`.

SECURITY: the API key is read from ``$GOOGLE_API_KEY`` and is NEVER logged,
echoed, or placed in an exception message. Absence is a first-class, non-fatal
state (:class:`VisionNotConfiguredError`) so the endpoint can return a clean
"not configured" instead of a 500.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-2.5-flash"


PROMPT = """\
You are extracting a residential floor plan from an image (SketchUp screenshot, drawing, or photo of a plan with dimension labels).
Return ONLY JSON matching exactly this schema, all dimensions in METERS (convert from cm labels; e.g. "592,00 cm" -> 5.92):
{"kavling_width_m": float, "kavling_length_m": float,
 "levels": [{"level": int (1 = ground floor),
   "rooms": [{"name": str (Indonesian, e.g. "Kamar Tidur Utama"),
              "type": one of ["kamar_tidur_utama","kamar_tidur","kamar_mandi","dapur","ruang_tamu","ruang_keluarga","ruang_makan","carport","garasi","musholla","gudang","teras","taman","sirkulasi","other"],
              "x_m": float, "y_m": float, "width_m": float, "length_m": float}]}],
 "notes": [str]}
Coordinate system: origin at the SOUTH-WEST (bottom-left) corner of the kavling, x grows east (right), y grows north (up). x_m,y_m are the room's bottom-left corner. Rooms must not overlap and must fit inside the kavling. If a dimension is unreadable, estimate from proportions and add a note. Use "other" for unknown room types."""


class VisionServiceError(Exception):
    """A vision extraction call failed (HTTP error or unexpected response)."""


class VisionNotConfiguredError(VisionServiceError):
    """No GOOGLE_API_KEY set — the vision service is not configured."""


class VisionExtractionError(VisionServiceError):
    """The provider returned a response that could not be parsed."""


def vision_service_configured() -> bool:
    """True iff a GOOGLE_API_KEY is present (existence check only — the key
    bytes are never returned or logged)."""
    return bool(os.environ.get("GOOGLE_API_KEY"))


def _base_url() -> str:
    return os.environ.get("GOOGLE_VISION_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")


def _model() -> str:
    return os.environ.get("GOOGLE_VISION_MODEL", DEFAULT_MODEL)


def _require_api_key() -> str:
    key = os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise VisionNotConfiguredError("GOOGLE_API_KEY is not set")
    return key


async def extract_floor_plan(
    image_bytes: bytes,
    mime_type: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Submit an image to the Gemini vision model and return the parsed JSON
    extraction result.

    Args:
        image_bytes: Raw image bytes (PNG, JPEG, or WebP are supported).
        mime_type: MIME type of the image (e.g. ``image/png``).
        client: Optional shared httpx client. A short-lived client is created
            and closed when not provided.

    Returns:
        The parsed JSON dict from Gemini's ``generateContent`` response.

    Raises:
        VisionNotConfiguredError: no API key set.
        VisionServiceError: HTTP/4xx/5xx or unexpected response shape.
        VisionExtractionError: response body is not valid JSON.
    """
    key = _require_api_key()
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
    model = _model()
    url = f"{_base_url()}/models/{model}:generateContent"

    import base64

    encoded = base64.b64encode(image_bytes).decode("ascii")

    payload = {
        "contents": [
            {
                "parts": [
                    {"inline_data": {"mime_type": mime_type, "data": encoded}},
                    {"text": PROMPT},
                ]
            }
        ],
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0.1,
        },
    }

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=120.0)
    try:
        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code >= 400:
            body = ""
            try:
                body = resp.text[:300]
            except Exception:
                pass
            raise VisionServiceError(f"Gemini vision API: HTTP {resp.status_code} {body}")

        data = resp.json()
        try:
            candidates = data["candidates"]
            part = candidates[0]["content"]["parts"][0]
            text = part["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise VisionExtractionError(
                f"Unexpected Gemini response shape: {exc}"
            ) from exc

        # Parse the JSON text — with one retry on failure.
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Retry once with an appended instruction.
            payload["contents"][0]["parts"][1]["text"] = (
                PROMPT + "\n\nReturn ONLY valid JSON."
            )
            resp2 = await client.post(url, json=payload, headers=headers)
            if resp2.status_code >= 400:
                raise VisionServiceError(
                    f"Gemini vision API (retry): HTTP {resp2.status_code}"
                )
            data2 = resp2.json()
            try:
                text2 = data2["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError, TypeError) as exc:
                raise VisionExtractionError(
                    f"Unexpected Gemini response shape on retry: {exc}"
                ) from exc
            try:
                return json.loads(text2)
            except json.JSONDecodeError as exc:
                raise VisionExtractionError(
                    f"Gemini returned non-JSON after retry: {text2[:200]}"
                ) from exc
    finally:
        if owns_client:
            await client.aclose()
