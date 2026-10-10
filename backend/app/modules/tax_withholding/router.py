# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tax withholding API routes.

Mounted at ``/api/v1/tax-withholding/``. The loader kebab-cases the directory
name for the canonical prefix and keeps the underscore form only as a hidden
alias, so documenting the underscore here pointed every reader at the path that
is deliberately absent from the schema.

    GET    /regimes/                  - the withholding schemes on file
    POST   /regimes/                  - register a scheme
    POST   /regimes/seed              - install the shipped schemes
    GET    /regimes/{regime_id}       - one scheme
    PUT    /regimes/{regime_id}       - replace a scheme
    DELETE /regimes/{regime_id}       - remove a scheme

    GET    /party-status/             - recorded standings under a scheme
    POST   /party-status/             - record a standing
    GET    /party-status/expiring     - standings lapsing in the next N days
    GET    /party-status/{status_id}  - one standing
    PUT    /party-status/{status_id}  - replace a standing
    DELETE /party-status/{status_id}  - remove a standing

    POST   /deductions/preview        - compute a deduction without storing it
    GET    /deductions/               - deductions on one project
    POST   /deductions/               - record a deduction
    GET    /deductions/{id}           - one deduction
    PUT    /deductions/{id}           - replace a deduction
    DELETE /deductions/{id}           - remove a deduction

    GET    /reverse-charge/rules      - the shipped reverse-charge wordings
    GET    /reverse-charge/           - determinations on one project
    POST   /reverse-charge/           - decide who accounts for the VAT
    GET    /reverse-charge/{id}       - one determination
    PUT    /reverse-charge/{id}       - replace a determination
    DELETE /reverse-charge/{id}       - remove a determination

    POST   /statutory/preview                          - compute a document's taxes, store nothing
    GET    /statutory/categories                       - the categories a person can choose from
    GET    /statutory/{source_kind}/{source_id}        - the stored taxes of one document
    PUT    /statutory/{source_kind}/{source_id}        - compute and store them as a draft
    POST   /statutory/{source_kind}/{source_id}/override        - enter an amount with a reason
    DELETE /statutory/{source_kind}/{source_id}/override/{kind} - go back to the computed amount
    POST   /statutory/{source_kind}/{source_id}/confirm         - a person confirms; figures freeze
    POST   /statutory/{source_kind}/{source_id}/reopen          - back to draft, audited
    POST   /statutory/{source_kind}/{source_id}/void            - out of use, rows kept

``/regimes/seed``, ``/party-status/expiring``, ``/deductions/preview`` and
``/reverse-charge/rules`` are each declared before the ``/{id}`` route that
would otherwise swallow them. Declared the other way round the literal path is
a candidate match for the detail route and the request dies as a malformed
UUID instead of reaching its handler.

**What is project-scoped and what is not.** A deduction and a determination sit
on a project's payments, so both are behind ``verify_project_access`` and the
list endpoints require a project rather than accepting a filter - an optional
project filter is an endpoint that returns every project's figures when it is
left off. A scheme is national reference data and a party's standing under a
scheme is company-wide (a subcontractor is verified once, not once per job), so
neither is project-scoped and both are gated by permission alone.

**When validation blocks.** A draft may be as rough as its author likes. An
ERROR finding stops a deduction leaving draft and stops a determination being
applied, because that is the point where the figure becomes something the
business acts on: money remitted, an invoice issued.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Annotated, get_args

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.payment_taxes import Choice, categories
from app.core.payment_taxes.tables import OverlappingRowsError
from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.tax_withholding import repository, service
from app.modules.tax_withholding.data import REVERSE_CHARGE_RULES
from app.modules.tax_withholding.models import (
    PartyTaxStatus,
    ReverseChargeDetermination,
    StatutoryTaxCalc,
    StatutoryTaxLine,
    WithholdingDeduction,
    WithholdingRegime,
)
from app.modules.tax_withholding.schemas import (
    DeductionCreateRequest,
    DeductionPreviewRequest,
    DeductionPreviewResponse,
    DeductionResponse,
    DeductionSaveResponse,
    DeductionUpdateRequest,
    PartyStatusCreateRequest,
    PartyStatusResponse,
    PartyStatusUpdateRequest,
    RegimeCreateRequest,
    RegimeResponse,
    RegimeSeedResponse,
    RegimeUpdateRequest,
    ReverseChargeCreateRequest,
    ReverseChargeResponse,
    ReverseChargeRuleResponse,
    ReverseChargeSaveResponse,
    ReverseChargeUpdateRequest,
    StatutoryCalcResponse,
    StatutoryCategoryListResponse,
    StatutoryCategoryResponse,
    StatutoryChoice,
    StatutoryConfirmRequest,
    StatutoryFigureResponse,
    StatutoryInputsBody,
    StatutoryOverridableLiteral,
    StatutoryOverrideRequest,
    StatutoryPreviewRequest,
    StatutoryPreviewResponse,
    StatutoryReasonRequest,
    StatutoryRowKindLiteral,
    StatutorySourceKindLiteral,
    StatutoryUpsertRequest,
    WithholdingFinding,
)
from app.modules.tax_withholding.source_owners import source_belongs_to_project
from app.modules.tax_withholding.validators import blocking_findings, evaluate_record

router = APIRouter(tags=["tax_withholding"])


def _to_findings(results: list) -> list[WithholdingFinding]:
    return [
        WithholdingFinding(
            key=f"taxWithholding.validation.{result.rule_id}",
            rule_id=result.rule_id,
            severity=str(result.severity),
            message=result.message,
            suggestion=result.suggestion or "",
            details=dict(result.details or {}),
        )
        for result in results
    ]


def _blocked(findings: list, action: str) -> None:
    """Refuse the save when an ERROR finding contradicts what is being claimed."""
    blocking = blocking_findings(findings)
    if not blocking:
        return
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={
            "message": action,
            "findings": [finding.model_dump() for finding in _to_findings(blocking)],
        },
    )


async def _regime_or_404(session: AsyncSession, regime_id: uuid.UUID) -> WithholdingRegime:
    regime = await repository.get_regime(session, regime_id)
    if regime is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Withholding scheme not found")
    return regime


def _party_status_response(row: PartyTaxStatus, as_of: date) -> PartyStatusResponse:
    payload = PartyStatusResponse.model_validate(row)
    payload.is_expired, payload.days_to_expiry = service.expiry_view(row, as_of)
    return payload


# ── Schemes ──────────────────────────────────────────────────────────────────


@router.get(
    "/regimes/",
    response_model=list[RegimeResponse],
    dependencies=[Depends(RequirePermission("tax_withholding.read"))],
)
async def list_regimes(
    session: SessionDep,
    country_code: str | None = Query(None, min_length=2, max_length=2),
    active_only: bool = Query(False),
) -> list[RegimeResponse]:
    """The withholding schemes this deployment knows about."""
    rows = await repository.list_regimes(session, country_code=country_code, active_only=active_only)
    return [RegimeResponse.model_validate(row) for row in rows]


@router.post(
    "/regimes/",
    response_model=RegimeResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("tax_withholding.manage"))],
)
async def create_regime(payload: RegimeCreateRequest, session: SessionDep) -> RegimeResponse:
    """Register a withholding scheme."""
    existing = await repository.get_regime_by_scheme(
        session,
        country_code=payload.country_code,
        scheme_code=payload.scheme_code,
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Scheme {payload.scheme_code} already exists for {payload.country_code}.",
        )
    regime = WithholdingRegime()
    service.apply_regime_body(regime, payload)
    await repository.add_regime(session, regime)
    return RegimeResponse.model_validate(regime)


@router.post(
    "/regimes/seed",
    response_model=RegimeSeedResponse,
    dependencies=[Depends(RequirePermission("tax_withholding.manage"))],
)
async def seed_shipped_regimes(session: SessionDep) -> RegimeSeedResponse:
    """Install the shipped schemes, leaving any already present untouched."""
    created, existing, codes = await service.seed_regimes(session)
    return RegimeSeedResponse(created=created, existing=existing, schemes=codes)


@router.get(
    "/regimes/{regime_id}",
    response_model=RegimeResponse,
    dependencies=[Depends(RequirePermission("tax_withholding.read"))],
)
async def read_regime(regime_id: uuid.UUID, session: SessionDep) -> RegimeResponse:
    """One scheme."""
    return RegimeResponse.model_validate(await _regime_or_404(session, regime_id))


@router.put(
    "/regimes/{regime_id}",
    response_model=RegimeResponse,
    dependencies=[Depends(RequirePermission("tax_withholding.manage"))],
)
async def replace_regime(
    regime_id: uuid.UUID,
    payload: RegimeUpdateRequest,
    session: SessionDep,
) -> RegimeResponse:
    """Replace a scheme. Every future deduction under it picks up the new rates."""
    regime = await _regime_or_404(session, regime_id)
    service.apply_regime_body(regime, payload)
    await session.flush()
    return RegimeResponse.model_validate(regime)


@router.delete(
    "/regimes/{regime_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("tax_withholding.manage"))],
)
async def remove_regime(regime_id: uuid.UUID, session: SessionDep) -> None:
    """Remove a scheme.

    Deductions hold a restricting foreign key at it, so a scheme that has ever
    been deducted under cannot be deleted. That is the intended answer: the
    deduction has to keep pointing at what it was taken under. Retire the
    scheme with ``is_active`` instead.
    """
    regime = await _regime_or_404(session, regime_id)
    await repository.delete_regime(session, regime)


# ── Party tax status ─────────────────────────────────────────────────────────


@router.get(
    "/party-status/",
    response_model=list[PartyStatusResponse],
    dependencies=[Depends(RequirePermission("tax_withholding.read"))],
)
async def list_party_statuses(
    session: SessionDep,
    party_id: uuid.UUID | None = Query(None),
    regime_id: uuid.UUID | None = Query(None),
    # Aliased so the wire API reads ``?status=active``. The Python name has to
    # differ: ``status`` is the FastAPI module this file raises HTTP codes from.
    party_status: str | None = Query(None, alias="status", max_length=24),
) -> list[PartyStatusResponse]:
    """Recorded standings, with today's expiry state computed on the way out."""
    rows = await repository.list_party_statuses(
        session,
        party_id=party_id,
        regime_id=regime_id,
        status=party_status,
    )
    today = date.today()
    return [_party_status_response(row, today) for row in rows]


@router.post(
    "/party-status/",
    response_model=PartyStatusResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("tax_withholding.write"))],
)
async def create_party_status(payload: PartyStatusCreateRequest, session: SessionDep) -> PartyStatusResponse:
    """Record what a party's standing is under a scheme."""
    regime = await _regime_or_404(session, payload.regime_id)
    if payload.valid_to is not None and payload.valid_to < payload.valid_from:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A verification cannot end before it starts.",
        )
    if service.find_band(regime, payload.band_code) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Scheme {regime.scheme_code} defines no band '{payload.band_code}'.",
        )
    row = PartyTaxStatus()
    service.apply_party_status_body(row, payload)
    await repository.add_party_status(session, row)
    return _party_status_response(row, date.today())


@router.get(
    "/party-status/expiring",
    response_model=list[PartyStatusResponse],
    dependencies=[Depends(RequirePermission("tax_withholding.read"))],
)
async def list_expiring_party_statuses(
    session: SessionDep,
    within_days: int = Query(60, ge=1, le=730),
) -> list[PartyStatusResponse]:
    """Standings that run out inside the next ``within_days`` days.

    The list that has to be read *before* a payment run. Afterwards it is a
    record of deductions taken at the wrong band.
    """
    today = date.today()
    rows = await repository.expiring_party_statuses(
        session,
        from_date=today,
        through=today + timedelta(days=within_days),
    )
    return [_party_status_response(row, today) for row in rows]


@router.get(
    "/party-status/{status_id}",
    response_model=PartyStatusResponse,
    dependencies=[Depends(RequirePermission("tax_withholding.read"))],
)
async def read_party_status(status_id: uuid.UUID, session: SessionDep) -> PartyStatusResponse:
    """One recorded standing."""
    row = await repository.get_party_status(session, status_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Party tax status not found")
    return _party_status_response(row, date.today())


@router.put(
    "/party-status/{status_id}",
    response_model=PartyStatusResponse,
    dependencies=[Depends(RequirePermission("tax_withholding.write"))],
)
async def replace_party_status(
    status_id: uuid.UUID,
    payload: PartyStatusUpdateRequest,
    session: SessionDep,
) -> PartyStatusResponse:
    """Replace a standing."""
    row = await repository.get_party_status(session, status_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Party tax status not found")
    regime = await _regime_or_404(session, payload.regime_id)
    if payload.valid_to is not None and payload.valid_to < payload.valid_from:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A verification cannot end before it starts.",
        )
    if service.find_band(regime, payload.band_code) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Scheme {regime.scheme_code} defines no band '{payload.band_code}'.",
        )
    service.apply_party_status_body(row, payload)
    await session.flush()
    return _party_status_response(row, date.today())


@router.delete(
    "/party-status/{status_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("tax_withholding.manage"))],
)
async def remove_party_status(status_id: uuid.UUID, session: SessionDep) -> None:
    """Remove a standing. Deductions that quoted it keep their own band and rate."""
    row = await repository.get_party_status(session, status_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Party tax status not found")
    await repository.delete_party_status(session, row)


# ── Deductions ───────────────────────────────────────────────────────────────


@router.post(
    "/deductions/preview",
    response_model=DeductionPreviewResponse,
    dependencies=[Depends(RequirePermission("tax_withholding.read"))],
)
async def preview_deduction(payload: DeductionPreviewRequest, session: SessionDep) -> DeductionPreviewResponse:
    """What would be withheld from this payment, and why.

    Answers the question before the payment is agreed rather than after, and
    reports the band it landed on - including when an expired verification
    moved the party to a higher one.
    """
    regime = await _regime_or_404(session, payload.regime_id)
    party_status = None
    if payload.party_status_id is not None:
        party_status = await repository.get_party_status(session, payload.party_status_id)
        if party_status is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Party tax status not found")
    figures = service.compute_deduction(
        regime,
        gross_amount=payload.gross_amount,
        currency_code=payload.currency_code,
        qualifying_materials=payload.qualifying_materials,
        vat_amount=payload.vat_amount,
        requested_band=payload.band_code,
        party_status=party_status,
        as_of=payload.as_of,
    )
    return DeductionPreviewResponse(
        regime_id=regime.id,
        scheme_code=regime.scheme_code,
        band_code=figures.band_code,
        rate_pct=figures.rate_pct,
        gross_amount=figures.gross_amount,
        qualifying_materials=figures.qualifying_materials,
        vat_amount=figures.vat_amount,
        taxable_base=figures.taxable_base,
        tax_withheld=figures.tax_withheld,
        net_payable=figures.net_payable,
        currency_code=payload.currency_code,
        below_threshold=figures.below_threshold,
        band_downgraded_from=figures.downgraded_from,
        reasons=figures.reasons,
    )


@router.get(
    "/deductions/",
    response_model=list[DeductionResponse],
    dependencies=[Depends(RequirePermission("tax_withholding.read"))],
)
async def list_deductions(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    regime_id: uuid.UUID | None = Query(None),
    deduction_status: str | None = Query(None, alias="status", max_length=24),
    period_start: date | None = Query(None),
    period_end: date | None = Query(None),
) -> list[DeductionResponse]:
    """Deductions on one project. The project is required, not a filter."""
    await verify_project_access(project_id, user_id, session)
    rows = await repository.list_deductions(
        session,
        project_id=project_id,
        regime_id=regime_id,
        status=deduction_status,
        period_start=period_start,
        period_end=period_end,
    )
    return [DeductionResponse.model_validate(row) for row in rows]


@router.post(
    "/deductions/",
    response_model=DeductionSaveResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("tax_withholding.write"))],
)
async def create_deduction(
    payload: DeductionCreateRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> DeductionSaveResponse:
    """Record tax withheld from one payment."""
    await verify_project_access(payload.project_id, user_id, session)
    row, findings = await _save_deduction(session, WithholdingDeduction(), payload)
    return DeductionSaveResponse(
        deduction=DeductionResponse.model_validate(row),
        findings=_to_findings(findings),
    )


@router.get(
    "/deductions/{deduction_id}",
    response_model=DeductionResponse,
    dependencies=[Depends(RequirePermission("tax_withholding.read"))],
)
async def read_deduction(
    deduction_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> DeductionResponse:
    """One deduction."""
    row = await repository.get_deduction(session, deduction_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deduction not found")
    await verify_project_access(row.project_id, user_id, session)
    return DeductionResponse.model_validate(row)


@router.put(
    "/deductions/{deduction_id}",
    response_model=DeductionSaveResponse,
    dependencies=[Depends(RequirePermission("tax_withholding.write"))],
)
async def replace_deduction(
    deduction_id: uuid.UUID,
    payload: DeductionUpdateRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> DeductionSaveResponse:
    """Replace a deduction."""
    row = await repository.get_deduction(session, deduction_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deduction not found")
    await verify_project_access(row.project_id, user_id, session)
    await verify_project_access(payload.project_id, user_id, session)
    updated, findings = await _save_deduction(session, row, payload)
    return DeductionSaveResponse(
        deduction=DeductionResponse.model_validate(updated),
        findings=_to_findings(findings),
    )


@router.delete(
    "/deductions/{deduction_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("tax_withholding.manage"))],
)
async def remove_deduction(
    deduction_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> None:
    """Remove a deduction. MANAGER only: it is the evidence behind a remittance."""
    row = await repository.get_deduction(session, deduction_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deduction not found")
    await verify_project_access(row.project_id, user_id, session)
    await repository.delete_deduction(session, row)


async def _save_deduction(
    session: AsyncSession,
    row: WithholdingDeduction,
    payload: DeductionCreateRequest | DeductionUpdateRequest,
) -> tuple[WithholdingDeduction, list]:
    """Compute what was left out, validate, and store - in that order.

    Validation runs on the figures that are about to be written, not on the
    ones already in the database, so a save that would break an invariant never
    happens rather than being reported after the fact.
    """
    if payload.period_end < payload.period_start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A return period cannot end before it starts.",
        )
    regime, party_status = await service.load_deduction_context(
        session,
        regime_id=payload.regime_id,
        party_status_id=payload.party_status_id,
    )
    if regime is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Withholding scheme not found")
    if payload.party_status_id is not None and party_status is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Party tax status not found")

    figures = service.compute_deduction(
        regime,
        gross_amount=payload.gross_amount,
        currency_code=payload.currency_code,
        qualifying_materials=payload.qualifying_materials,
        vat_amount=payload.vat_amount,
        requested_band=payload.band_code,
        party_status=party_status,
        as_of=payload.period_start,
    )
    findings = await evaluate_record(
        service.deduction_payload(payload, regime=regime, party_status=party_status, figures=figures)
    )
    if payload.status != "draft":
        _blocked(
            findings,
            "This deduction cannot leave draft until its errors are fixed; the figures would be remitted as they stand.",
        )
    service.apply_deduction_body(row, payload, figures)
    if row.id is None:
        await repository.add_deduction(session, row)
    else:
        await session.flush()
    return row, findings


# ── Reverse charge ───────────────────────────────────────────────────────────


@router.get(
    "/reverse-charge/rules",
    response_model=list[ReverseChargeRuleResponse],
    dependencies=[Depends(RequirePermission("tax_withholding.read"))],
)
async def list_reverse_charge_rules(
    country_code: str | None = Query(None, min_length=2, max_length=2),
) -> list[ReverseChargeRuleResponse]:
    """The shipped reverse-charge rules: the statute and the wording to print."""
    wanted = country_code.upper() if country_code else ""
    return [
        ReverseChargeRuleResponse(**rule)
        for rule in REVERSE_CHARGE_RULES
        if not wanted or rule["country_code"] == wanted
    ]


@router.get(
    "/reverse-charge/",
    response_model=list[ReverseChargeResponse],
    dependencies=[Depends(RequirePermission("tax_withholding.read"))],
)
async def list_determinations(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    country_code: str | None = Query(None, min_length=2, max_length=2),
    determination_status: str | None = Query(None, alias="status", max_length=24),
) -> list[ReverseChargeResponse]:
    """Reverse-charge determinations on one project."""
    await verify_project_access(project_id, user_id, session)
    rows = await repository.list_determinations(
        session,
        project_id=project_id,
        country_code=country_code,
        status=determination_status,
    )
    return [ReverseChargeResponse.model_validate(row) for row in rows]


@router.post(
    "/reverse-charge/",
    response_model=ReverseChargeSaveResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("tax_withholding.write"))],
)
async def create_determination(
    payload: ReverseChargeCreateRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> ReverseChargeSaveResponse:
    """Decide who accounts for the VAT on one invoice."""
    await verify_project_access(payload.project_id, user_id, session)
    existing = await repository.get_determination_for_invoice(
        session,
        project_id=payload.project_id,
        invoice_reference=payload.invoice_reference,
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Invoice {payload.invoice_reference} already has a determination on this project. "
                "Supersede it rather than deciding twice."
            ),
        )
    row, findings = await _save_determination(session, ReverseChargeDetermination(), payload)
    return ReverseChargeSaveResponse(
        determination=ReverseChargeResponse.model_validate(row),
        findings=_to_findings(findings),
    )


@router.get(
    "/reverse-charge/{determination_id}",
    response_model=ReverseChargeResponse,
    dependencies=[Depends(RequirePermission("tax_withholding.read"))],
)
async def read_determination(
    determination_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> ReverseChargeResponse:
    """One determination."""
    row = await repository.get_determination(session, determination_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Determination not found")
    await verify_project_access(row.project_id, user_id, session)
    return ReverseChargeResponse.model_validate(row)


@router.put(
    "/reverse-charge/{determination_id}",
    response_model=ReverseChargeSaveResponse,
    dependencies=[Depends(RequirePermission("tax_withholding.write"))],
)
async def replace_determination(
    determination_id: uuid.UUID,
    payload: ReverseChargeUpdateRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> ReverseChargeSaveResponse:
    """Replace a determination."""
    row = await repository.get_determination(session, determination_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Determination not found")
    await verify_project_access(row.project_id, user_id, session)
    await verify_project_access(payload.project_id, user_id, session)
    updated, findings = await _save_determination(session, row, payload)
    return ReverseChargeSaveResponse(
        determination=ReverseChargeResponse.model_validate(updated),
        findings=_to_findings(findings),
    )


@router.delete(
    "/reverse-charge/{determination_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("tax_withholding.manage"))],
)
async def remove_determination(
    determination_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> None:
    """Remove a determination. MANAGER only: a filed VAT return rests on it."""
    row = await repository.get_determination(session, determination_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Determination not found")
    await verify_project_access(row.project_id, user_id, session)
    await repository.delete_determination(session, row)


async def _save_determination(
    session: AsyncSession,
    row: ReverseChargeDetermination,
    payload: ReverseChargeCreateRequest | ReverseChargeUpdateRequest,
) -> tuple[ReverseChargeDetermination, list]:
    """Validate and store a determination.

    ``applied`` is the state the invoice is issued on, so that is where an
    ERROR finding stops. A draft may be incomplete while somebody works out
    whether the buyer accounts for the VAT at all.
    """
    findings = await evaluate_record(service.determination_payload(payload))
    if payload.status == "applied":
        _blocked(
            findings,
            "This determination cannot be applied until its errors are fixed; the invoice would go out wrong.",
        )
    service.apply_determination_body(row, payload)
    if row.id is None:
        await repository.add_determination(session, row)
    else:
        await session.flush()
    return row, findings


# ── Statutory tax lines on a payment document ────────────────────────────────
#
# The source document (a progress claim, a subcontractor payment application,
# an invoice) lives in another module and is named by kind and id. It belongs
# to a project, the caller states which, and two checks follow from that on
# every route: the caller may reach that project, and the stored set is filed
# under that same project. A set filed under another project answers exactly
# like a document with nothing stored, so the answer never tells a caller that
# somebody else's document exists.


def statutory_row_source() -> service.RowSource:
    """Where the statutory rate rows come from. Overridden in tests."""
    return service.shipped_rows


RowSourceDep = Annotated[service.RowSource, Depends(statutory_row_source)]

_STATUTORY_NOT_FOUND = "Statutory tax lines not found"


def _refused(refusal: service.StatutoryRefusal) -> HTTPException:
    """Turn a service refusal into the response the screen translates."""
    if refusal.http_status == status.HTTP_404_NOT_FOUND:
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=refusal.message)
    return HTTPException(
        status_code=refusal.http_status,
        detail={
            "key": f"taxWithholding.statutory.error.{refusal.code}",
            "code": refusal.code,
            "message": refusal.message,
            "details": refusal.details,
            "findings": [finding.model_dump() for finding in _to_findings(refusal.findings)],
        },
    )


def _statutory_inputs(payload: StatutoryInputsBody) -> service.StatutoryInputs:
    """A validated request as the plain values the service computes from."""

    def choice(body: StatutoryChoice) -> Choice:
        return Choice(state=body.state, code=body.code, reason=body.reason)

    return service.StatutoryInputs(
        country_code=payload.country_code,
        currency_code=payload.currency_code,
        document_date=payload.document_date,
        net_amount=payload.net_amount,
        vat_rate_pct=payload.vat_rate_pct,
        buyer_is_designated=payload.buyer_is_designated,
        work_value_incl_vat=payload.work_value_incl_vat,
        work_value_note=payload.work_value_note,
        stamp_duty_base=payload.stamp_duty_base,
        stamp_duty_base_same_as_net=payload.stamp_duty_base_same_as_net,
        vat_withholding=choice(payload.vat_withholding),
        income_withholding=choice(payload.income_withholding),
        stamp_duty=choice(payload.stamp_duty),
    )


def _inputs_body(inputs: service.StatutoryInputs) -> StatutoryInputsBody:
    def choice(value: Choice) -> StatutoryChoice:
        return StatutoryChoice(state=value.state, code=value.code, reason=value.reason)

    return StatutoryInputsBody(
        country_code=inputs.country_code,
        currency_code=inputs.currency_code,
        document_date=inputs.document_date,
        net_amount=inputs.net_amount,
        vat_rate_pct=inputs.vat_rate_pct,
        buyer_is_designated=inputs.buyer_is_designated,
        work_value_incl_vat=inputs.work_value_incl_vat,
        work_value_note=inputs.work_value_note,
        stamp_duty_base=inputs.stamp_duty_base,
        stamp_duty_base_same_as_net=inputs.stamp_duty_base_same_as_net,
        vat_withholding=choice(inputs.vat_withholding),
        income_withholding=choice(inputs.income_withholding),
        stamp_duty=choice(inputs.stamp_duty),
    )


def _figure_response(values: dict) -> StatutoryFigureResponse:
    """One line's values as the figure the reader receives."""
    currency = values["currency_code"]
    rate = values["rate_pct"]
    return StatutoryFigureResponse(
        kind=values["kind"],
        status=values["calc_status"],
        amount=service.money_as_stored(values["tax_amount"], currency),
        base=service.money_as_stored(values["base_amount"], currency),
        rate_pct=service.plain_decimal(rate) if rate is not None else None,
        numerator=values["numerator"],
        denominator=values["denominator"],
        code=values["code"],
        currency_code=currency,
        legal_reference=values["legal_reference"],
        source_url=values["source_url"],
        effective_from=values["rate_effective_from"],
        effective_to=values["rate_effective_to"],
        review_status=values["review_status"],
        overridden=values["overridden"],
        reason_key=values["reason_key"],
        reason_params=values["reason_params"],
        choice_state=values.get("choice_state", ""),
        choice_code=values.get("choice_code", ""),
        choice_reason=values.get("choice_reason", ""),
        override_amount=values.get("override_amount"),
        override_reason=values.get("override_reason", ""),
        overridden_by=values.get("overridden_by"),
        overridden_at=values.get("overridden_at"),
    )


async def _statutory_response(
    calc: StatutoryTaxCalc,
    lines: list[StatutoryTaxLine],
    findings: list | None = None,
) -> StatutoryCalcResponse:
    """A stored set as the reader receives it, with what validation makes of it."""
    try:
        values = [service.stored_line_values(line) for line in lines]
        inputs = service.inputs_from_stored(calc, lines)
    except service.StatutoryDataError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "key": "taxWithholding.statutory.error.statutory_data_unreadable",
                "code": "statutory_data_unreadable",
                "message": str(exc),
            },
        ) from exc
    if findings is None:
        findings = await evaluate_record(
            service.statutory_payload(
                values,
                currency_code=calc.currency_code,
                document_date=calc.document_date,
                source_reference=calc.source_reference,
            ),
            record_id=str(calc.id),
        )
    return StatutoryCalcResponse(
        id=calc.id,
        project_id=calc.project_id,
        source_kind=calc.source_kind,
        source_id=calc.source_id,
        source_reference=calc.source_reference,
        direction=calc.direction,
        status=calc.status,
        inputs=_inputs_body(inputs),
        figures=[_figure_response(line) for line in values],
        complete=not service.held_kinds(values),
        uses_unconfirmed_rates=bool(service.unconfirmed_codes(values)),
        confirmed_by=calc.confirmed_by,
        confirmed_at=calc.confirmed_at,
        unconfirmed_rates_acknowledged_by=calc.unconfirmed_rates_acknowledged_by,
        unconfirmed_rates_acknowledged_at=calc.unconfirmed_rates_acknowledged_at,
        reopened_by=calc.reopened_by,
        reopened_at=calc.reopened_at,
        reopen_reason=calc.reopen_reason,
        voided_by=calc.voided_by,
        voided_at=calc.voided_at,
        void_reason=calc.void_reason,
        created_at=calc.created_at,
        updated_at=calc.updated_at,
        findings=_to_findings(findings),
    )


async def _require_owned_source(
    session: AsyncSession,
    *,
    source_kind: str,
    source_id: uuid.UUID,
    project_id: uuid.UUID,
) -> None:
    """Refuse a document its owning module does not place in ``project_id``.

    The answer is the 404 a stored set under a foreign project gets, so a
    caller cannot tell an id nobody has from an id that belongs to someone
    else. See :mod:`app.modules.tax_withholding.source_owners`.
    """
    if not await source_belongs_to_project(
        session, source_kind=source_kind, source_id=source_id, project_id=project_id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_STATUTORY_NOT_FOUND)


async def _statutory_or_404(
    session: AsyncSession,
    *,
    source_kind: str,
    source_id: uuid.UUID,
    project_id: uuid.UUID,
    user_id: str,
) -> tuple[StatutoryTaxCalc, list[StatutoryTaxLine]]:
    """The stored set of one document, for a caller who may reach its project.

    Three refusals, all 404. The caller cannot reach the project they named;
    the module that owns the document does not know it under that project (or
    no module owns that kind of document on this install); or the set is filed
    under a different project than the one they named.
    """
    await verify_project_access(project_id, user_id, session)
    await _require_owned_source(session, source_kind=source_kind, source_id=source_id, project_id=project_id)
    stored = await service.get_statutory(session, source_kind=source_kind, source_id=source_id)
    if stored is None or stored[0].project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_STATUTORY_NOT_FOUND)
    return stored


@router.post(
    "/statutory/preview",
    response_model=StatutoryPreviewResponse,
    dependencies=[Depends(RequirePermission("tax_withholding.statutory_view"))],
)
async def preview_statutory_taxes(
    payload: StatutoryPreviewRequest,
    row_source: RowSourceDep,
) -> StatutoryPreviewResponse:
    """What the five figures would be for these inputs. Nothing is stored."""
    inputs = _statutory_inputs(payload)
    rows = row_source(inputs.country_code)
    try:
        result = service.preview_statutory(inputs, rows)
        values = service.result_line_values(result, inputs, rows)
    except service.StatutoryRefusal as refusal:
        raise _refused(refusal) from refusal
    findings = await evaluate_record(
        service.statutory_payload(
            values,
            currency_code=inputs.currency_code,
            document_date=inputs.document_date,
        )
    )
    return StatutoryPreviewResponse(
        inputs=_inputs_body(inputs),
        figures=[_figure_response(line) for line in values],
        complete=result.complete,
        uses_unconfirmed_rates=bool(service.unconfirmed_codes(values)),
        findings=_to_findings(findings),
    )


@router.get(
    "/statutory/categories",
    response_model=StatutoryCategoryListResponse,
    dependencies=[Depends(RequirePermission("tax_withholding.statutory_view"))],
)
async def list_statutory_categories(
    row_source: RowSourceDep,
    country: str = Query(..., min_length=2, max_length=2),
    on: date = Query(...),
    kind: StatutoryRowKindLiteral | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
) -> StatutoryCategoryListResponse:
    """The categories a person can choose from on one date, with their legal basis.

    The date is required. A picker filled for today would offer this year's
    fraction for last year's document.

    Answered as a page: ``total`` is every category that matched, so a caller
    holding fewer ``items`` can tell, and ask for the rest with ``offset``.
    """
    rows = row_source(country)
    wanted = (kind,) if kind else get_args(StatutoryRowKindLiteral)
    found = []
    try:
        for row_kind in wanted:
            found.extend(categories(rows, country=country, kind=row_kind, on=on))
    except OverlappingRowsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "key": "taxWithholding.statutory.error.rate_table_ambiguous",
                "code": "rate_table_ambiguous",
                "message": str(exc),
            },
        ) from exc
    items = [
        StatutoryCategoryResponse(
            country_code=row.country_code,
            kind=row.kind,
            code=row.code,
            labels=dict(row.labels),
            base=row.base,
            rate_pct=row.rate_pct,
            numerator=row.numerator,
            denominator=row.denominator,
            threshold_amount=row.threshold_amount,
            threshold_currency=row.threshold_currency,
            threshold_scope=row.threshold_scope,
            threshold_measure=row.threshold_measure,
            cap_amount=row.cap_amount,
            buyer_scope=row.buyer_scope,
            work_value_threshold=row.work_value_threshold,
            conditions=dict(row.conditions),
            effective_from=row.effective_from,
            effective_to=row.effective_to,
            legal_reference=row.legal_reference,
            source_url=row.source_url,
            read_date=row.read_date,
            review_status=row.review_status,
        )
        for row in found[offset : offset + limit]
    ]
    return StatutoryCategoryListResponse(items=items, total=len(found), offset=offset, limit=limit)


@router.get(
    "/statutory/{source_kind}/{source_id}",
    response_model=StatutoryCalcResponse,
    dependencies=[Depends(RequirePermission("tax_withholding.statutory_view"))],
)
async def read_statutory_taxes(
    source_kind: StatutorySourceKindLiteral,
    source_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
) -> StatutoryCalcResponse:
    """The stored statutory taxes of one source document."""
    calc, lines = await _statutory_or_404(
        session, source_kind=source_kind, source_id=source_id, project_id=project_id, user_id=user_id
    )
    return await _statutory_response(calc, lines)


@router.put(
    "/statutory/{source_kind}/{source_id}",
    response_model=StatutoryCalcResponse,
    dependencies=[Depends(RequirePermission("tax_withholding.statutory_edit"))],
)
async def save_statutory_taxes(
    source_kind: StatutorySourceKindLiteral,
    source_id: uuid.UUID,
    payload: StatutoryUpsertRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    row_source: RowSourceDep,
) -> StatutoryCalcResponse:
    """Compute a document's statutory taxes and store them as a draft.

    Saving the same body twice stores the same rows. A confirmed set is not
    recalculated: reopen it with a reason first.
    """
    await verify_project_access(payload.project_id, user_id, session)
    await _require_owned_source(session, source_kind=source_kind, source_id=source_id, project_id=payload.project_id)
    try:
        calc, lines = await service.upsert_statutory(
            session,
            project_id=payload.project_id,
            source_kind=source_kind,
            source_id=source_id,
            inputs=_statutory_inputs(payload),
            direction=payload.direction,
            user_id=user_id,
            source_reference=payload.source_reference,
            row_source=row_source,
        )
    except service.StatutoryRefusal as refusal:
        raise _refused(refusal) from refusal
    return await _statutory_response(calc, lines)


@router.post(
    "/statutory/{source_kind}/{source_id}/override",
    response_model=StatutoryCalcResponse,
    dependencies=[Depends(RequirePermission("tax_withholding.statutory_edit"))],
)
async def override_statutory_tax(
    source_kind: StatutorySourceKindLiteral,
    source_id: uuid.UUID,
    payload: StatutoryOverrideRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    row_source: RowSourceDep,
) -> StatutoryCalcResponse:
    """Enter an amount in place of one computed figure, with the reason."""
    calc, _ = await _statutory_or_404(
        session, source_kind=source_kind, source_id=source_id, project_id=payload.project_id, user_id=user_id
    )
    try:
        lines = await service.override_statutory(
            session,
            calc=calc,
            kind=payload.kind,
            amount=payload.amount,
            reason=payload.reason,
            user_id=user_id,
            row_source=row_source,
        )
    except service.StatutoryRefusal as refusal:
        raise _refused(refusal) from refusal
    return await _statutory_response(calc, lines)


@router.delete(
    "/statutory/{source_kind}/{source_id}/override/{kind}",
    response_model=StatutoryCalcResponse,
    dependencies=[Depends(RequirePermission("tax_withholding.statutory_edit"))],
)
async def clear_statutory_tax_override(
    source_kind: StatutorySourceKindLiteral,
    source_id: uuid.UUID,
    kind: StatutoryOverridableLiteral,
    session: SessionDep,
    user_id: CurrentUserId,
    row_source: RowSourceDep,
    project_id: uuid.UUID = Query(...),
) -> StatutoryCalcResponse:
    """Remove an entered amount and go back to the computed figure."""
    calc, _ = await _statutory_or_404(
        session, source_kind=source_kind, source_id=source_id, project_id=project_id, user_id=user_id
    )
    try:
        lines = await service.clear_statutory_override(
            session, calc=calc, kind=kind, user_id=user_id, row_source=row_source
        )
    except service.StatutoryRefusal as refusal:
        raise _refused(refusal) from refusal
    return await _statutory_response(calc, lines)


@router.post(
    "/statutory/{source_kind}/{source_id}/confirm",
    response_model=StatutoryCalcResponse,
    dependencies=[Depends(RequirePermission("tax_withholding.statutory_confirm"))],
)
async def confirm_statutory_taxes(
    source_kind: StatutorySourceKindLiteral,
    source_id: uuid.UUID,
    payload: StatutoryConfirmRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> StatutoryCalcResponse:
    """Confirm the stored figures. From here on they are frozen.

    Refused while a figure is held, and while a rate behind a figure has not
    been confirmed against its source unless the caller acknowledges having
    checked it. The acknowledgement is stored with the user and the time.
    """
    calc, _ = await _statutory_or_404(
        session, source_kind=source_kind, source_id=source_id, project_id=payload.project_id, user_id=user_id
    )
    try:
        lines, findings = await service.confirm_statutory(
            session,
            calc=calc,
            user_id=user_id,
            acknowledge_unconfirmed_rates=payload.acknowledge_unconfirmed_rates,
        )
    except service.StatutoryRefusal as refusal:
        raise _refused(refusal) from refusal
    return await _statutory_response(calc, lines, findings)


@router.post(
    "/statutory/{source_kind}/{source_id}/reopen",
    response_model=StatutoryCalcResponse,
    dependencies=[Depends(RequirePermission("tax_withholding.statutory_confirm"))],
)
async def reopen_statutory_taxes(
    source_kind: StatutorySourceKindLiteral,
    source_id: uuid.UUID,
    payload: StatutoryReasonRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> StatutoryCalcResponse:
    """Take confirmed or void figures back to draft. Written to the audit log."""
    calc, _ = await _statutory_or_404(
        session, source_kind=source_kind, source_id=source_id, project_id=payload.project_id, user_id=user_id
    )
    try:
        lines = await service.reopen_statutory(session, calc=calc, user_id=user_id, reason=payload.reason)
    except service.StatutoryRefusal as refusal:
        raise _refused(refusal) from refusal
    return await _statutory_response(calc, lines)


@router.post(
    "/statutory/{source_kind}/{source_id}/void",
    response_model=StatutoryCalcResponse,
    dependencies=[Depends(RequirePermission("tax_withholding.statutory_confirm"))],
)
async def void_statutory_taxes(
    source_kind: StatutorySourceKindLiteral,
    source_id: uuid.UUID,
    payload: StatutoryReasonRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> StatutoryCalcResponse:
    """Take a set of figures out of use, keeping its rows as evidence."""
    calc, _ = await _statutory_or_404(
        session, source_kind=source_kind, source_id=source_id, project_id=payload.project_id, user_id=user_id
    )
    try:
        lines = await service.void_statutory(session, calc=calc, user_id=user_id, reason=payload.reason)
    except service.StatutoryRefusal as refusal:
        raise _refused(refusal) from refusal
    return await _statutory_response(calc, lines)
