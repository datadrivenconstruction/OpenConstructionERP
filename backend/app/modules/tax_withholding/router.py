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

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

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
    WithholdingFinding,
)
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
