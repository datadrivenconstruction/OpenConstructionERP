# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠FastAPI router for the e-signature registry.

Auto-mounted at ``/api/v1/signing/``. Every endpoint is project-scoped via
:func:`app.dependencies.verify_project_access` - the same guard the credentials
and compliance-docs modules use - so a caller cannot see or mutate signing
sessions on a project they lack access to, and a cross-project id surfaces as 404
(not 403) so the endpoint can't be turned into an id-existence oracle.

No endpoint accepts a private key, a certificate file, a password or any
credential. The attest endpoint records an attestation and certificate metadata
only.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import (
    CurrentUserId,
    LangDep,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.signing import intl
from app.modules.signing.models import Signature, SigningSession
from app.modules.signing.providers import DEFAULT_PROVIDER
from app.modules.signing.schemas import (
    CAPABILITIES,
    SESSION_STATUSES,
    AttestationCreate,
    CertExpiryFlag,
    DeclineCreate,
    SignatureResponse,
    SigningSessionCreate,
    SigningSessionResponse,
    SigningSessionUpdate,
)
from app.modules.signing.service import SigningService, delta_by_hash

router = APIRouter(tags=["signing"])


def _get_service(session: SessionDep) -> SigningService:
    return SigningService(session)


def _session_to_response(
    session_row: SigningSession,
    signatures: list[Signature],
) -> SigningSessionResponse:
    """Build a session response with signature roll-ups and per-signature staleness."""
    current_hash = session_row.document_content_hash
    stale_names = delta_by_hash(signatures, current_hash)

    sig_responses: list[SignatureResponse] = []
    signed_count = 0
    declined_count = 0
    for s in signatures:
        if s.status == "signed":
            signed_count += 1
        elif s.status == "declined":
            declined_count += 1
        resp = SignatureResponse.model_validate(s)
        is_stale = s.status == "signed" and s.signatory_name in stale_names and s.content_hash != current_hash
        sig_responses.append(resp.model_copy(update={"stale": is_stale}))

    required_count = sum(1 for e in (session_row.signatory_map or []) if e.get("required", True))

    resp = SigningSessionResponse.model_validate(session_row)
    return resp.model_copy(
        update={
            "required_count": required_count,
            "signed_count": signed_count,
            "declined_count": declined_count,
            "signatures": sig_responses,
        }
    )


# ── Meta ────────────────────────────────────────────────────────────────


@router.get(
    "/meta",
    dependencies=[Depends(RequirePermission("signing.read"))],
)
async def get_meta(lang: LangDep) -> dict:
    """Expose the validated vocabularies and the default provider for the UI.

    The frontend builds its capability / status pickers from this payload so it
    never drifts from the server-side whitelists, with labels pre-translated for
    the requested locale (falling back to English).
    """
    return {
        "capabilities": [{"code": c, "label": intl.describe_capability(c, lang)} for c in CAPABILITIES],
        "statuses": [{"code": s, "label": intl.describe_status(s, lang)} for s in SESSION_STATUSES],
        "default_provider": DEFAULT_PROVIDER.describe(),
    }


# ── Sessions CRUD ─────────────────────────────────────────────────────────


@router.get(
    "/sessions/",
    response_model=list[SigningSessionResponse],
    dependencies=[Depends(RequirePermission("signing.read"))],
)
async def list_sessions(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    status_filter: str | None = Query(default=None, alias="status"),
    capability: str | None = Query(default=None),
    service: SigningService = Depends(_get_service),
) -> list[SigningSessionResponse]:
    """List signing sessions for a project, optionally filtered."""
    await verify_project_access(project_id, user_id, session)
    sessions = await service.list_sessions(project_id, status=status_filter, capability=capability)
    all_sigs = await service.repo.list_signatures_for_project(project_id)
    by_session: dict[uuid.UUID, list[Signature]] = {}
    for sig in all_sigs:
        by_session.setdefault(sig.session_id, []).append(sig)
    return [_session_to_response(s, by_session.get(s.id, [])) for s in sessions]


@router.post(
    "/sessions/",
    response_model=SigningSessionResponse,
    status_code=201,
)
async def create_session(
    data: SigningSessionCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("signing.create")),
    service: SigningService = Depends(_get_service),
) -> SigningSessionResponse:
    """Open a new signing session against a project document."""
    await verify_project_access(data.project_id, user_id, session)
    created = await service.create_session(data, user_id=user_id)
    return _session_to_response(created, [])


@router.get(
    "/sessions/{session_id}/",
    response_model=SigningSessionResponse,
    dependencies=[Depends(RequirePermission("signing.read"))],
)
async def get_session(
    session_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: SigningService = Depends(_get_service),
) -> SigningSessionResponse:
    """Read a single signing session with its recorded attestations."""
    session_row = await service.get_session(session_id)
    await verify_project_access(session_row.project_id, user_id, session)
    signatures = await service.list_signatures(session_id)
    return _session_to_response(session_row, signatures)


@router.patch(
    "/sessions/{session_id}/",
    response_model=SigningSessionResponse,
)
async def update_session(
    session_id: uuid.UUID,
    data: SigningSessionUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("signing.update")),
    service: SigningService = Depends(_get_service),
) -> SigningSessionResponse:
    """Patch a session. Status is re-derived from the attestations and expiry."""
    existing = await service.get_session(session_id)
    await verify_project_access(existing.project_id, user_id, session)
    updated = await service.update_session(session_id, data, user_id=user_id)
    signatures = await service.list_signatures(session_id)
    return _session_to_response(updated, signatures)


@router.delete(
    "/sessions/{session_id}/",
    status_code=204,
)
async def delete_session(
    session_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("signing.delete")),
    service: SigningService = Depends(_get_service),
) -> None:
    """Delete a signing session and its attestations."""
    existing = await service.get_session(session_id)
    await verify_project_access(existing.project_id, user_id, session)
    await service.delete_session(session_id)


# ── Attestation / decline ─────────────────────────────────────────────────


@router.post(
    "/sessions/{session_id}/attest",
    response_model=SigningSessionResponse,
    status_code=201,
)
async def attest(
    session_id: uuid.UUID,
    data: AttestationCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("signing.attest")),
    service: SigningService = Depends(_get_service),
) -> SigningSessionResponse:
    """Record a signature attestation.

    Registers who signed, in what role, at what time, against which content hash,
    with which certificate *metadata*. It never accepts a key or a password.
    """
    existing = await service.get_session(session_id)
    await verify_project_access(existing.project_id, user_id, session)
    updated = await service.record_attestation(session_id, data, user_id=user_id)
    signatures = await service.list_signatures(session_id)
    return _session_to_response(updated, signatures)


@router.post(
    "/sessions/{session_id}/decline",
    response_model=SigningSessionResponse,
    status_code=201,
)
async def decline(
    session_id: uuid.UUID,
    data: DeclineCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("signing.attest")),
    service: SigningService = Depends(_get_service),
) -> SigningSessionResponse:
    """Record that a signatory declined to sign - moves the session to declined."""
    existing = await service.get_session(session_id)
    await verify_project_access(existing.project_id, user_id, session)
    updated = await service.record_decline(session_id, data, user_id=user_id)
    signatures = await service.list_signatures(session_id)
    return _session_to_response(updated, signatures)


# ── Views ─────────────────────────────────────────────────────────────────


@router.get(
    "/sessions/{session_id}/stale",
    dependencies=[Depends(RequirePermission("signing.read"))],
)
async def get_stale(
    session_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    content_hash: str | None = Query(
        default=None,
        description="Hash to compare against. Defaults to the session's current content hash.",
    ),
    service: SigningService = Depends(_get_service),
) -> dict:
    """Delta-by-hash: which signatories must re-sign because the content moved on."""
    session_row = await service.get_session(session_id)
    await verify_project_access(session_row.project_id, user_id, session)
    stale = await service.stale_signatories(session_id, content_hash=content_hash)
    return {
        "session_id": str(session_id),
        "content_hash": content_hash or session_row.document_content_hash,
        "stale_signatories": sorted(stale),
    }


@router.get(
    "/sessions/{session_id}/manifest",
    dependencies=[Depends(RequirePermission("signing.read"))],
)
async def get_manifest(
    session_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: SigningService = Depends(_get_service),
) -> dict:
    """The issued-set hash manifest for a session and its per-signature hashes."""
    session_row = await service.get_session(session_id)
    await verify_project_access(session_row.project_id, user_id, session)
    return await service.session_manifest(session_id)


@router.get(
    "/expiring-certs",
    response_model=list[CertExpiryFlag],
    dependencies=[Depends(RequirePermission("signing.read"))],
)
async def expiring_certs(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    within_days: int = Query(default=30, ge=0, le=3650),
    service: SigningService = Depends(_get_service),
) -> list[CertExpiryFlag]:
    """Signatures whose certificate metadata is expired or expiring within N days."""
    await verify_project_access(project_id, user_id, session)
    flags = await service.expiring_certs(project_id, within_days=within_days)
    return [CertExpiryFlag(**f) for f in flags]


__all__ = ["router"]
