# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Client-error sink API routes.

Endpoints:
    POST /                         - accept an anonymised client error report

The endpoint is intentionally write-only and unauthenticated so that
anonymous landing-page or marketing-site errors can still be captured.
A per-IP rate limit at 30 req/min (sliding window) keeps the surface
safe from abuse without introducing a Redis dependency.

Storage is a v4.3 follow-up - for now we forward the payload to the
standard ``logging`` pipeline at WARNING level so it shows up next to
backend errors in journald / log aggregators.

Performance note (2026-06-19)
------------------------------
FastAPI resolves all positional-body parameters *before* executing the
handler body.  The old signature ``submit_client_error(payload: ...,
request: Request)`` therefore parsed and validated the JSON body on every
request — including those that would be rejected by the rate limiter.  On
a CPU-starved 1-core VPS this meant a rate-limited client still paid the
full deserialization cost (~several ms of CPU, possible GIL contention,
and a ``logger.warning`` that drives a synchronous write to journald).

Fix: receive the raw ``Request`` only, perform the rate-limit check
first (pure in-memory, < 1 µs), and *then* decode the body.  A rejected
request now returns in < 1 ms with zero I/O.

Body-size guard: we also cap the raw body to ``_MAX_BODY_BYTES`` before
handing it to Pydantic so a large forged payload never buffers more than
8 KB in Python memory.  FastAPI's ``request.body()`` reads the already-
buffered Starlette body (no extra network I/O); the cap only affects
parsing.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import ValidationError
from starlette.requests import ClientDisconnect

from app.core.rate_limiter import RateLimiter, client_identifier
from app.modules.client_errors.schemas import ClientErrorReport

router = APIRouter(tags=["client_errors"])
logger = logging.getLogger(__name__)

# Per-IP cap. 30 req/min handles a tab that throws inside a tight render
# loop without dropping every report, while still rejecting a runaway
# client / abusive scanner. Sliding window; in-memory only - no Redis.
_client_error_limiter = RateLimiter(max_requests=30, window_seconds=60)

# Hard cap on raw body size accepted from this unauthenticated endpoint.
# The largest valid payload (2048-char message + 128 stack lines × 512 chars)
# is well under 100 KB; 8 KB is generous for a legitimate report and tight
# enough to bound memory usage under a body-flood attack.
_MAX_BODY_BYTES = 8_192


@router.post("/", status_code=status.HTTP_202_ACCEPTED)
async def submit_client_error(
    request: Request,
) -> dict[str, str]:
    """Accept an anonymised client-error report.

    Rate-limit check is performed BEFORE body deserialization so that a
    rejected request is cheap (pure in-memory, no I/O, < 1 ms).

    Returns ``202 Accepted`` on success - the client is fire-and-forget
    and never reads the response body, but the explicit status code
    documents that the report is queued/observed rather than persisted.
    """
    # ── 1. Rate-limit check (fast path, no I/O) ───────────────────────────
    client_ip = client_identifier(request)
    allowed, _ = _client_error_limiter.is_allowed(client_ip)
    if not allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Client-error reporter rate limit exceeded.",
        )

    # ── 2. Read + cap body, then validate ─────────────────────────────────
    try:
        raw = await request.body()
    except ClientDisconnect:
        # The reporter is fire-and-forget (``void fetch(...)`` in
        # errorLogger.ts) and commonly fires right as the page navigates
        # away, which aborts the in-flight request client-side before the
        # full body reaches us. Starlette surfaces that as an unhandled
        # ``ClientDisconnect`` from ``request.body()`` rather than an empty
        # read, and nothing downstream is listening for a response either
        # way, so there is nothing to log and no error to report - treat it
        # exactly like a malformed body.
        return {"status": "accepted"}
    if len(raw) > _MAX_BODY_BYTES:
        # Silently truncate oversized payloads rather than surfacing a 413 —
        # a legitimate reporter will never be this large; an attacker gets
        # dropped cleanly.
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "Client-error payload exceeds maximum allowed size.",
        )

    try:
        data = json.loads(raw)
        payload = ClientErrorReport.model_validate(data)
    except (json.JSONDecodeError, ValidationError):
        # Malformed body — discard silently from the client's perspective.
        # Return 202 so the reporter doesn't retry (it's fire-and-forget).
        return {"status": "accepted"}

    # ── 3. Log (best-effort) ──────────────────────────────────────────────
    # Cap individual stack lines so a single malformed report cannot
    # blow up the log line size budget. The Pydantic schema already
    # caps the list to 128 entries.
    capped_stack = [line[:512] for line in payload.stack_lines[:64]]

    # Put the real detail in the log message itself, not only in ``extra``.
    # The stdlib formatter configured in app.main renders only ``%(message)s``,
    # so anything passed via ``extra`` is silently dropped from the text log.
    # That is why a real upload/runtime error previously showed up as a bare
    # "client_error" with no detail. The structured ``extra`` is kept for JSON
    # sinks that do render it.
    logger.warning(
        "client_error id=%s path=%s msg=%s",
        payload.error_id,
        payload.path[:256] or "-",
        payload.message[:512] or "-",
        extra={
            "client_error_id": payload.error_id,
            "client_timestamp": payload.timestamp,
            "client_message": payload.message[:512],
            "client_stack": capped_stack,
            "client_user_agent": payload.user_agent[:256],
            "client_path": payload.path[:256],
            "client_ip": client_ip,
        },
    )
    return {"status": "accepted"}
