# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""E-invoice clearance API routes.

Mounted at ``/api/v1/einvoice-clearance/``.

    GET    /meta                        - regimes, statuses and installed adapters

    GET    /profiles/                   - registrations
    POST   /profiles/                   - register an entity in a country
    GET    /profiles/{profile_id}       - one registration
    PUT    /profiles/{profile_id}       - replace a registration
    DELETE /profiles/{profile_id}       - remove one that has no documents

    GET    /documents/                  - documents on a project
    POST   /documents/                  - prepare an invoice for a platform
    GET    /documents/{document_id}     - one document
    PUT    /documents/{document_id}     - correct one that has not gone yet
    GET    /documents/{document_id}/payload - exactly what was or will be sent
    GET    /documents/{document_id}/events  - the trail
    POST   /documents/{document_id}/validate - dry run against the country rules
    POST   /documents/{document_id}/submit   - put it to the platform
    POST   /documents/{document_id}/resolve  - record by hand what a platform did
    POST   /documents/{document_id}/cancel   - withdraw a document it accepted

Documents are project-scoped and every document route runs
:func:`app.dependencies.verify_project_access`, so a cross-project id surfaces
as 404 rather than 403 and the endpoint cannot be used to ask whether an id
exists. Registrations are not project-scoped: a company's registration in
Mexico is the same registration on every job it runs there.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.core.validation.engine import RuleResult
from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.einvoice_clearance import repository, service
from app.modules.einvoice_clearance.adapters import adapter_registry
from app.modules.einvoice_clearance.models import EInvoiceDocument, EInvoiceProfile
from app.modules.einvoice_clearance.regimes import COUNTRY_REGIMES, get_country_regime, regime_as_dict
from app.modules.einvoice_clearance.schemas import (
    AdapterResponse,
    CancelRequest,
    ClearanceFinding,
    CountryRegimeResponse,
    DocumentCreateRequest,
    DocumentResponse,
    DocumentSaveResponse,
    DocumentUpdateRequest,
    EventResponse,
    MetaResponse,
    ProfileCreateRequest,
    ProfileResponse,
    ProfileUpdateRequest,
    ResolveRequest,
    SubmissionResponse,
    SubmitRequest,
)

router = APIRouter(tags=["einvoice_clearance"])


def _actor(user_id: str) -> uuid.UUID | None:
    """The calling user as a UUID, or ``None`` when it is not one.

    Never raises. The actor is provenance on an event, and refusing a
    submission because a deployment issues non-UUID subjects would trade a real
    capability for a cosmetic one.
    """
    try:
        return uuid.UUID(str(user_id))
    except (TypeError, ValueError):
        return None


def _to_findings(results: list[RuleResult]) -> list[ClearanceFinding]:
    return [
        ClearanceFinding(
            # The rule id already starts with the module name, so the key strips
            # it rather than saying it twice.
            key=f"einvoice_clearance.validation.{str(result.rule_id).split('.', 1)[-1]}",
            rule_id=result.rule_id,
            severity=str(result.severity),
            message=result.message,
            suggestion=result.suggestion or "",
            details=dict(result.details or {}),
        )
        for result in results
    ]


def _refuse(exc: service.ClearanceError) -> HTTPException:
    """Turn a domain refusal into the right HTTP answer.

    A conflict is about the state of the record - already cleared, already sent,
    a move the machine does not allow - and a 422 is about its contents. They
    read differently to a client: one is retryable after fixing the payload, the
    other never is.
    """
    detail: dict[str, Any] = {"message": exc.message}
    if exc.findings:
        detail["findings"] = [f.model_dump() for f in _to_findings(exc.findings)]
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT if exc.conflict else status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=detail,
    )


async def _load_document(
    session: SessionDep,
    document_id: uuid.UUID,
    user_id: str,
) -> tuple[EInvoiceDocument, EInvoiceProfile]:
    """One document plus its registration, with the project guard applied."""
    document = await repository.get_document(session, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    await verify_project_access(document.project_id, user_id, session)
    profile = await repository.get_profile(session, document.profile_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The registration this document was filed under no longer exists.",
        )
    return document, profile


# ── Meta ─────────────────────────────────────────────────────────────────────


@router.get(
    "/meta",
    response_model=MetaResponse,
    dependencies=[Depends(RequirePermission("einvoice_clearance.read"))],
)
async def get_meta() -> MetaResponse:
    """The country registry and the installed adapters, for the UI to render."""
    return MetaResponse(
        countries=[
            CountryRegimeResponse(**regime_as_dict(entry))
            for entry in sorted(COUNTRY_REGIMES.values(), key=lambda e: (e.regime, e.country))
        ],
        adapters=[
            AdapterResponse(key=adapter.key, label=adapter.label, countries=list(adapter.countries))
            for adapter in adapter_registry.list_all().values()
        ],
    )


# ── Registrations ────────────────────────────────────────────────────────────


@router.get(
    "/profiles/",
    response_model=list[ProfileResponse],
    dependencies=[Depends(RequirePermission("einvoice_clearance.read"))],
)
async def list_registrations(
    session: SessionDep,
    country: str | None = Query(None, max_length=2),
    company_key: str | None = Query(None, max_length=120),
    active_only: bool = Query(False),
) -> list[ProfileResponse]:
    """Registrations this deployment holds."""
    rows = await repository.list_profiles(session, country=country, company_key=company_key, active_only=active_only)
    return [ProfileResponse.model_validate(row) for row in rows]


@router.post(
    "/profiles/",
    response_model=ProfileResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("einvoice_clearance.write"))],
)
async def create_registration(
    payload: ProfileCreateRequest,
    session: SessionDep,
) -> ProfileResponse:
    """Register a legal entity with one country's platform."""
    existing = await repository.get_profile_for(session, company_key=payload.company_key, country=payload.country)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{payload.company_key} already has a {payload.country} registration. "
                "Edit that one rather than adding a second identity for the same entity."
            ),
        )
    entry = get_country_regime(payload.country)
    if entry is None:  # pragma: no cover - the schema already rejects this
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"No e-invoicing regime is registered for country {payload.country!r}.",
        )
    profile = EInvoiceProfile(
        company_key=payload.company_key,
        country=payload.country,
        # Denormalised from the registry: the row records what was registered,
        # not what the code believes about that country today.
        regime=entry.regime,
        platform=entry.platform,
        tax_registration_id=payload.tax_registration_id,
        network_participant_id=payload.network_participant_id,
        certificate_reference=payload.certificate_reference,
        adapter_key=payload.adapter_key,
        sandbox=payload.sandbox,
        is_active=payload.is_active,
        settings=dict(payload.settings or {}),
        notes=payload.notes,
    )
    await repository.add_profile(session, profile)
    return ProfileResponse.model_validate(profile)


@router.get(
    "/profiles/{profile_id}",
    response_model=ProfileResponse,
    dependencies=[Depends(RequirePermission("einvoice_clearance.read"))],
)
async def read_registration(profile_id: uuid.UUID, session: SessionDep) -> ProfileResponse:
    """One registration."""
    profile = await repository.get_profile(session, profile_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registration not found")
    return ProfileResponse.model_validate(profile)


@router.put(
    "/profiles/{profile_id}",
    response_model=ProfileResponse,
    dependencies=[Depends(RequirePermission("einvoice_clearance.write"))],
)
async def replace_registration(
    profile_id: uuid.UUID,
    payload: ProfileUpdateRequest,
    session: SessionDep,
) -> ProfileResponse:
    """Replace a registration."""
    profile = await repository.get_profile(session, profile_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registration not found")
    entry = get_country_regime(payload.country)
    if entry is None:  # pragma: no cover - the schema already rejects this
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"No e-invoicing regime is registered for country {payload.country!r}.",
        )
    profile.company_key = payload.company_key
    profile.country = payload.country
    profile.regime = entry.regime
    profile.platform = entry.platform
    profile.tax_registration_id = payload.tax_registration_id
    profile.network_participant_id = payload.network_participant_id
    profile.certificate_reference = payload.certificate_reference
    profile.adapter_key = payload.adapter_key
    profile.sandbox = payload.sandbox
    profile.is_active = payload.is_active
    profile.settings = dict(payload.settings or {})
    profile.notes = payload.notes
    await session.flush()
    return ProfileResponse.model_validate(profile)


@router.delete(
    "/profiles/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("einvoice_clearance.write"))],
)
async def remove_registration(profile_id: uuid.UUID, session: SessionDep) -> None:
    """Remove a registration that has nothing filed under it.

    A registration with documents behind it is the only record of which
    identity those submissions were made under, so it is deactivated rather
    than deleted.
    """
    profile = await repository.get_profile(session, profile_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registration not found")
    filed = await repository.count_documents_for_profile(session, profile_id)
    if filed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{filed} document(s) were filed under this registration, and it is the only record "
                "of the identity they were sent with. Deactivate it instead."
            ),
        )
    await repository.delete_profile(session, profile)


# ── Documents ────────────────────────────────────────────────────────────────


@router.get(
    "/documents/",
    response_model=list[DocumentResponse],
    dependencies=[Depends(RequirePermission("einvoice_clearance.read"))],
)
async def list_clearance_documents(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    country: str | None = Query(None, max_length=2),
    document_status: str | None = Query(None, max_length=24, alias="status"),
    regime: str | None = Query(None, max_length=16),
    invoice_id: uuid.UUID | None = Query(None),
) -> list[DocumentResponse]:
    """Clearance documents on one project."""
    await verify_project_access(project_id, user_id, session)
    rows = await repository.list_documents(
        session,
        project_id=project_id,
        country=country,
        status=document_status,
        regime=regime,
        invoice_id=invoice_id,
    )
    return [DocumentResponse.model_validate(row) for row in rows]


@router.post(
    "/documents/",
    response_model=DocumentSaveResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("einvoice_clearance.write"))],
)
async def create_clearance_document(
    payload: DocumentCreateRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> DocumentSaveResponse:
    """Prepare one invoice for one country's platform."""
    await verify_project_access(payload.project_id, user_id, session)
    profile = await repository.get_profile(session, payload.profile_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registration not found")
    try:
        document, findings = await service.create_document(
            session, profile=profile, body=payload, actor_id=_actor(user_id)
        )
    except service.ClearanceError as exc:
        raise _refuse(exc) from exc
    return DocumentSaveResponse(
        document=DocumentResponse.model_validate(document),
        findings=_to_findings(findings),
    )


@router.get(
    "/documents/{document_id}",
    response_model=DocumentResponse,
    dependencies=[Depends(RequirePermission("einvoice_clearance.read"))],
)
async def read_clearance_document(
    document_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> DocumentResponse:
    """One document."""
    document, _profile = await _load_document(session, document_id, user_id)
    return DocumentResponse.model_validate(document)


@router.put(
    "/documents/{document_id}",
    response_model=DocumentSaveResponse,
    dependencies=[Depends(RequirePermission("einvoice_clearance.write"))],
)
async def replace_clearance_document(
    document_id: uuid.UUID,
    payload: DocumentUpdateRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> DocumentSaveResponse:
    """Correct a document that has not been sent yet."""
    document, profile = await _load_document(session, document_id, user_id)
    try:
        updated, findings = await service.update_document(
            session, document=document, profile=profile, body=payload, actor_id=_actor(user_id)
        )
    except service.ClearanceError as exc:
        raise _refuse(exc) from exc
    return DocumentSaveResponse(
        document=DocumentResponse.model_validate(updated),
        findings=_to_findings(findings),
    )


@router.get(
    "/documents/{document_id}/payload",
    dependencies=[Depends(RequirePermission("einvoice_clearance.read"))],
)
async def read_clearance_payload(
    document_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> Response:
    """Exactly the document that was or will be sent.

    Served as the stored bytes with the stored media type. "Show me what we
    actually sent" is the first question in any dispute with an authority, and
    an answer that had been re-rendered would not be one.
    """
    document, _profile = await _load_document(session, document_id, user_id)
    return Response(
        content=(document.payload or "").encode("utf-8"),
        media_type=document.payload_media_type or "application/xml",
        headers={"Content-Disposition": (f'attachment; filename="einvoice_{document.country}_{document.id}.xml"')},
    )


@router.get(
    "/documents/{document_id}/events",
    response_model=list[EventResponse],
    dependencies=[Depends(RequirePermission("einvoice_clearance.read"))],
)
async def list_clearance_events(
    document_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> list[EventResponse]:
    """The append-only trail behind one document."""
    document, _profile = await _load_document(session, document_id, user_id)
    rows = await repository.list_events(session, document.id)
    return [EventResponse.model_validate(row) for row in rows]


@router.post(
    "/documents/{document_id}/validate",
    response_model=DocumentSaveResponse,
    dependencies=[Depends(RequirePermission("einvoice_clearance.write"))],
)
async def validate_clearance_document(
    document_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> DocumentSaveResponse:
    """Dry run against the country rules, without sending anything."""
    document, profile = await _load_document(session, document_id, user_id)
    try:
        findings = await service.validate_document(
            session, document=document, profile=profile, actor_id=_actor(user_id)
        )
    except service.ClearanceError as exc:
        raise _refuse(exc) from exc
    return DocumentSaveResponse(
        document=DocumentResponse.model_validate(document),
        findings=_to_findings(findings),
    )


@router.post(
    "/documents/{document_id}/submit",
    response_model=SubmissionResponse,
    dependencies=[Depends(RequirePermission("einvoice_clearance.submit"))],
)
async def submit_clearance_document(
    document_id: uuid.UUID,
    payload: SubmitRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> SubmissionResponse:
    """Put the document to the platform.

    A rejection is a 200 carrying the authority's code, not an HTTP error: the
    request succeeded, and what came back is a fact about the invoice that the
    caller has to store and show, not a failure of this call.
    """
    document, profile = await _load_document(session, document_id, user_id)
    try:
        updated, outcome, findings = await service.submit_document(
            session,
            document=document,
            profile=profile,
            actor_id=_actor(user_id),
            accept_warnings=payload.accept_warnings,
        )
    except service.ClearanceError as exc:
        raise _refuse(exc) from exc
    return SubmissionResponse(
        document=DocumentResponse.model_validate(updated),
        accepted=outcome.accepted,
        authority_identifier=outcome.authority_identifier,
        rejection_code=outcome.rejection_code,
        rejection_message=outcome.rejection_message,
        message=outcome.message,
        findings=_to_findings(findings),
    )


@router.post(
    "/documents/{document_id}/resolve",
    response_model=DocumentResponse,
    dependencies=[Depends(RequirePermission("einvoice_clearance.submit"))],
)
async def resolve_clearance_document(
    document_id: uuid.UUID,
    payload: ResolveRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> DocumentResponse:
    """Record by hand what the platform did with a document left in doubt.

    The way out of ``submitted`` when the adapter failed before the platform
    answered. Guarded by the submit permission rather than write, because it
    sets the same states a submission does.
    """
    document, profile = await _load_document(session, document_id, user_id)
    try:
        updated = await service.resolve_document(
            session,
            document=document,
            profile=profile,
            outcome=payload.outcome,
            note=payload.note,
            authority_identifier=payload.authority_identifier,
            rejection_code=payload.rejection_code,
            rejection_message=payload.rejection_message,
            actor_id=_actor(user_id),
        )
    except service.ClearanceError as exc:
        raise _refuse(exc) from exc
    return DocumentResponse.model_validate(updated)


@router.post(
    "/documents/{document_id}/cancel",
    response_model=SubmissionResponse,
    dependencies=[Depends(RequirePermission("einvoice_clearance.cancel"))],
)
async def cancel_clearance_document(
    document_id: uuid.UUID,
    payload: CancelRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> SubmissionResponse:
    """Withdraw a document the platform has already accepted."""
    document, profile = await _load_document(session, document_id, user_id)
    try:
        updated, outcome, findings = await service.cancel_document(
            session,
            document=document,
            profile=profile,
            reason=payload.reason,
            actor_id=_actor(user_id),
        )
    except service.ClearanceError as exc:
        raise _refuse(exc) from exc
    return SubmissionResponse(
        document=DocumentResponse.model_validate(updated),
        accepted=outcome.accepted,
        authority_identifier=outcome.authority_identifier,
        rejection_code=outcome.rejection_code,
        rejection_message=outcome.rejection_message,
        message=outcome.message,
        findings=_to_findings(findings),
    )
