# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Inbound capture API routes (auto-mounted at /api/v1/inbound-capture).

Two capture endpoints turn an outside message into incoming correspondence:

* ``POST /email`` - an already-parsed inbound email payload.
* ``POST /{provider}/webhook`` - a provider chat / SMS webhook delivery, whose
  signature is verified against the RAW request body before the body is trusted.

Both normalize the payload with the pure inbound engine, persist it as an
incoming ``oe_correspondence`` row, publish ``correspondence.created`` and are
idempotent on the provider's external message id.

Auth: these endpoints may be called by an external system rather than an
interactive user, but they are still NOT anonymous. The caller must present
``inbound.write`` via one of two credentials, checked by
:func:`resolve_capture_caller`:

* a JWT bearer token (interactive user or a caller that can refresh one), same
  as the rest of the platform; or
* an ``X-API-Key`` header (:func:`app.dependencies.get_user_from_api_key`) for
  a headless system that cannot reasonably hold a short-lived JWT indefinitely
  - this is the credential the module's own "external system" framing implies,
  and the mechanism already existed in ``app.dependencies`` but was not wired
  to any permission-gated route before this.

Both paths enforce the identical ``inbound.write`` check (admin bypass, then
role/permission lookup, with the same stale-JWT live-registry fallback
``RequirePermission`` uses). The target project must additionally pass
:func:`verify_project_access` - which 404s on both "missing" and "denied" so it
never leaks project existence. Webhook deliveries additionally carry a
provider HMAC signature, verified by the seam below. The desired public path
for these routes is ``/api/v1/inbound/...``; the loader derives the mount from
the package directory, so today they land under
``/api/v1/inbound-capture/...`` (see the module REPORT for the one-line tweak to
move them to ``/inbound``).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    get_optional_user_payload,
    get_user_from_api_key,
    verify_project_access,
)
from app.modules.correspondence.models import Correspondence
from app.modules.inbound_capture.normalize import (
    normalize,
    normalize_email,
)
from app.modules.inbound_capture.schemas import (
    InboundAttachmentOut,
    InboundCapturedList,
    InboundEmailRequest,
    InboundMessageOut,
    InboundWebhookRequest,
)
from app.modules.inbound_capture.service import (
    capture_message,
    list_captured,
    to_message_out_fields,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Inbound Capture"])


# --- Signature-verification seam --------------------------------------------
#
# Provider webhooks are authenticated by recomputing an HMAC-SHA256 over the RAW
# request body bytes and comparing it, in constant time, to the signature the
# provider sent. The verifying secret is supplied out of band (never stored in
# the DB) via a per-provider environment variable, so adding a provider is a
# config change, not a code change. The seam is intentionally a single small,
# well-named function: extend it per provider by branching on ``provider`` (e.g.
# a provider that signs ``timestamp.body`` instead of ``body``, or sends the
# digest base64 instead of hex) - the call site never changes.


def _provider_secret_env_name(provider: str) -> str:
    """Env var holding a provider's webhook signing secret.

    ``INBOUND_CAPTURE_SECRET__<PROVIDER>`` with the provider upper-cased and any
    non-alphanumeric character mapped to ``_`` (so ``ms-teams`` -> ``MS_TEAMS``).
    Mirrors the per-source secret convention the webhook-leads module uses.
    """
    safe = re.sub(r"[^A-Z0-9]", "_", provider.upper())
    return f"INBOUND_CAPTURE_SECRET__{safe}"


def resolve_provider_secret(provider: str) -> str | None:
    """Return the configured signing secret for ``provider`` or ``None``.

    ``None`` means the provider has no secret configured; verification then
    fails closed (the request is rejected) rather than silently trusting an
    unauthenticated body. Overridable in tests by setting the env var.
    """
    return os.environ.get(_provider_secret_env_name(provider))


def _extract_signature(headers: object) -> str | None:
    """Pull the provider signature from the common signature header names."""
    if not hasattr(headers, "get"):
        return None
    for name in ("x-inbound-signature", "x-webhook-signature", "x-hub-signature-256"):
        value = headers.get(name)
        if value:
            return value
    return None


def verify_provider_signature(provider: str, raw_body: bytes, headers: object) -> bool:
    """Verify a provider webhook's HMAC-SHA256 signature over the RAW body.

    THE signature-verification seam. Today it implements the standard scheme:
    recompute ``HMAC-SHA256(secret, raw_body)`` and compare it in constant time
    (:func:`hmac.compare_digest`) to the presented digest, tolerating a
    ``sha256=`` prefix (GitHub-style). The secret comes from
    :func:`resolve_provider_secret`; when no secret is configured for the
    provider, or no signature header is present, verification fails closed.

    To onboard a provider with a different scheme, branch on ``provider`` here -
    for example sign ``f"{timestamp}.".encode() + raw_body``, or decode a
    base64 digest - and return the boolean result. Callers stay unchanged.
    """
    secret = resolve_provider_secret(provider)
    if not secret:
        logger.warning(
            "Inbound webhook rejected: no signing secret configured for provider %r (set %s)",
            provider,
            _provider_secret_env_name(provider),
        )
        return False
    presented = _extract_signature(headers)
    if not presented:
        return False
    sig = presented.strip()
    if "=" in sig:
        algo, _, sig = sig.partition("=")
        if algo.lower() not in ("sha256", "hmac-sha256"):
            return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig.lower())


# --- Auth seam: JWT (interactive) or API key (machine caller) ---------------


def _check_inbound_write(role: str, permissions: list[str], user_id: str) -> None:
    """Enforce ``inbound.write`` for a resolved role, whatever the credential.

    Mirrors :class:`app.dependencies.RequirePermission` exactly (admin bypass,
    then membership in ``permissions``, then a live-registry fallback for a
    permissions list that predates a role change) so a caller sees identical
    behaviour regardless of whether it authenticated via JWT or API key.
    """
    if role == "admin":
        return
    if "inbound.write" in permissions:
        return
    from app.core.permissions import permission_registry

    if permission_registry.role_has_permission(role, "inbound.write"):
        return
    logger.debug(
        "Inbound capture permission denied: permission=inbound.write user=%s role=%s",
        user_id,
        role,
    )
    raise HTTPException(status_code=403, detail="Missing permission: inbound.write")


async def resolve_capture_caller(
    request: Request,
    payload: Any = Depends(get_optional_user_payload),
) -> str:
    """Authorize a capture-endpoint caller and return their user id.

    Tries the platform JWT first (``payload`` is non-``None`` when a valid
    bearer token was presented - re-hydrated from the DB the same way every
    other authenticated route sees it). When no JWT was presented, falls back
    to an ``X-API-Key`` header: the module's own docstring already documents
    that these endpoints "may be called by an external system rather than an
    interactive user", and a headless system cannot reasonably keep a
    short-lived JWT refreshed indefinitely. Either path enforces the same
    ``inbound.write`` permission before the caller's id is trusted.
    """
    if payload is not None:
        _check_inbound_write(
            payload.get("role", ""), payload.get("permissions", []), str(payload.get("sub", "unknown"))
        )
        return str(payload["sub"])

    if not request.headers.get("x-api-key"):
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await get_user_from_api_key(request)
    from app.core.permissions import permission_registry

    _check_inbound_write(user.role, permission_registry.get_role_permissions(user.role), str(user.id))
    return str(user.id)


# --- Serialization ----------------------------------------------------------


def _serialize(row: Correspondence, *, deduplicated: bool) -> InboundMessageOut:
    """Render a captured correspondence row as the inbound read shape."""
    fields = to_message_out_fields(row)
    attachments = [
        InboundAttachmentOut(
            filename=str(a.get("filename", "") or ""),
            content_type=str(a.get("content_type", "") or ""),
            size_bytes=int(a.get("size_bytes", 0) or 0),
            storage_hint=(a.get("storage_hint") or None),
        )
        for a in fields["attachments"]  # type: ignore[union-attr]
    ]
    return InboundMessageOut(
        correspondence_id=str(fields["correspondence_id"]),
        project_id=str(fields["project_id"]),
        reference_number=str(fields["reference_number"]),
        channel=str(fields["channel"]),
        external_message_id=str(fields["external_message_id"]),
        idempotency_key=str(fields["idempotency_key"]),
        direction=str(fields["direction"]),
        sender=str(fields["sender"]),
        recipients=list(fields["recipients"]),  # type: ignore[arg-type]
        sent_at=str(fields["sent_at"]),
        subject=str(fields["subject"]),
        body=str(fields["body"]),
        in_reply_to=(fields["in_reply_to"] or None),  # type: ignore[arg-type]
        attachments=attachments,
        raw_refs=list(fields["raw_refs"]),  # type: ignore[arg-type]
        deduplicated=deduplicated,
    )


def _parse_project_id(value: str) -> uuid.UUID:
    """Coerce a project-id string to a UUID, 422 on a malformed value."""
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="project_id is not a valid UUID") from exc


# --- Endpoints --------------------------------------------------------------


@router.post(
    "/email",
    response_model=InboundMessageOut,
)
async def capture_inbound_email(
    payload: InboundEmailRequest,
    session: SessionDep,
    user_id: str = Depends(resolve_capture_caller),
) -> InboundMessageOut:
    """Capture an already-parsed inbound email as incoming correspondence.

    The email payload is normalized to the canonical inbound shape, persisted as
    an incoming ``oe_correspondence`` row and announced via
    ``correspondence.created``. Capturing the same email again (same message id)
    returns the existing row with ``deduplicated=true`` instead of creating a
    duplicate.
    """
    project_id = _parse_project_id(payload.project_id)
    await verify_project_access(project_id, user_id or "", session)
    message = normalize_email(payload.payload)
    row, deduplicated = await capture_message(session, project_id, message, created_by=user_id)
    return _serialize(row, deduplicated=deduplicated)


@router.post(
    "/{provider}/webhook",
    response_model=InboundMessageOut,
)
async def capture_inbound_webhook(
    provider: str,
    request: Request,
    session: SessionDep,
    user_id: str = Depends(resolve_capture_caller),
) -> InboundMessageOut:
    """Capture a provider chat / SMS webhook delivery as incoming correspondence.

    The provider's HMAC signature is verified against the RAW request body
    before the body is parsed or trusted (see :func:`verify_provider_signature`);
    a bad or missing signature is a 401. The verified JSON body is then read as
    an :class:`InboundWebhookRequest`, normalized for the channel (the body's
    ``channel`` hint, else inferred from ``{provider}``), persisted as incoming
    correspondence and announced via ``correspondence.created``, idempotent on
    the provider's external message id.

    The signature is over the exact bytes sent, so this handler reads
    ``request.body()`` itself rather than taking a parsed model parameter -
    re-serializing a parsed body would change the bytes and break verification.
    """
    raw_body = await request.body()
    if not verify_provider_signature(provider, raw_body, request.headers):
        raise HTTPException(status_code=401, detail="Invalid or missing webhook signature")

    try:
        parsed = json.loads(raw_body or b"{}")
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="Request body is not valid JSON") from exc
    try:
        body = InboundWebhookRequest.model_validate(parsed)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid inbound webhook body") from exc

    project_id = _parse_project_id(body.project_id)
    await verify_project_access(project_id, user_id or "", session)

    # Channel: the explicit body hint wins; otherwise the engine infers from the
    # provider path segment (a known channel constant such as "sms" routes to its
    # normalizer, anything else uses the permissive webhook shape but keeps the
    # provider label as the stored channel).
    channel = (body.channel or provider or "").strip()
    message = normalize(channel, body.payload)
    row, deduplicated = await capture_message(session, project_id, message, created_by=user_id)
    return _serialize(row, deduplicated=deduplicated)


@router.get(
    "/projects/{project_id}/captured",
    response_model=InboundCapturedList,
    dependencies=[Depends(RequirePermission("inbound.read"))],
)
async def list_captured_messages(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(0, ge=0, description="Rows to skip (paging)"),
    limit: int = Query(50, ge=1, le=200, description="Max rows to return"),
) -> InboundCapturedList:
    """List the inbound messages captured for a project (newest first).

    Returns only correspondence this gateway created (rows carrying the inbound
    envelope), so the admin view shows exactly what arrived through the capture
    endpoints rather than every incoming letter. Requires ``inbound.read`` and
    access to the project (404 on missing or denied, so existence never leaks).
    """
    await verify_project_access(project_id, user_id or "", session)
    rows, total = await list_captured(session, project_id, offset=offset, limit=limit)
    return InboundCapturedList(
        items=[_serialize(row, deduplicated=False) for row in rows],
        total=total,
    )
