# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Statutory checks API routes.

Endpoints:
    GET  /jurisdictions/          - codes of the jurisdictions loaded packs contribute
    GET  /jurisdictions/{code}/   - the forms and tables the UI needs for one
    POST /evaluate/               - deadlines, retention verdict, tax split and findings

Auto-mounts at ``/api/v1/statutory``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import CurrentUserId, RequirePermission
from app.modules.contracts.retention_cap import RetentionTableError
from app.modules.deadlines.notice_calendar import NoticeRuleError
from app.modules.statutory import repository
from app.modules.statutory.schemas import JurisdictionSummary, StatutoryFacts, StatutoryOutcome
from app.modules.statutory.service import UnknownJurisdictionError, evaluate_facts
from app.modules.statutory.tax_engine import TaxProfileError

router = APIRouter(tags=["statutory"])


@router.get("/jurisdictions/", response_model=list[str])
async def list_jurisdictions(
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("statutory.read")),
) -> list[str]:
    """Jurisdictions with statutory tables, as ISO 3166 codes."""
    return repository.list_codes()


@router.get("/jurisdictions/{code}/", response_model=JurisdictionSummary)
async def get_jurisdiction(
    code: str,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("statutory.read")),
) -> JurisdictionSummary:
    """The forms, tables and links for one jurisdiction; 404 when no loaded pack carries it."""
    table = repository.get_table(code)
    if table is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No statutory tables for {code!r}.")
    return JurisdictionSummary(**repository.summary(table))


@router.post("/evaluate/", response_model=StatutoryOutcome)
async def evaluate(
    facts: StatutoryFacts,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("statutory.read")),
) -> StatutoryOutcome:
    """Compute deadlines, the retention verdict and the tax split, and list the findings."""
    try:
        outcome = evaluate_facts(facts.model_dump(mode="json"))
    except UnknownJurisdictionError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"No statutory tables for {facts.jurisdiction!r}."
        ) from exc
    except (NoticeRuleError, RetentionTableError, TaxProfileError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return StatutoryOutcome(**outcome)
