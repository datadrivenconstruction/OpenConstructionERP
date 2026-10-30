# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Service charges API routes (auto-mounted at /api/v1/service-charges).

Every handler checks access to the project that owns the association (directly or
through the budget, key or line it names) with ``verify_project_access``.

    GET    /?project_id=                          associations of a project
    POST   /                                      create an association
    POST   /demands/run                           raise demands for one period (idempotent)
    GET    /keys/{key_id}                         one key
    PATCH  /keys/{key_id}                         edit a key
    DELETE /keys/{key_id}                         delete an unused key
    GET    /budgets/{budget_id}                   one budget with lines
    PATCH  /budgets/{budget_id}                   edit a draft budget
    DELETE /budgets/{budget_id}                   delete a draft budget
    POST   /budgets/{budget_id}/approve           draft -> approved
    GET    /budgets/{budget_id}/units             yearly and per-period charge per unit
    POST   /budgets/{budget_id}/lines             add a line
    PATCH  /budget-lines/{line_id}                edit a line
    DELETE /budget-lines/{line_id}                delete a line
    GET    /budgets/{budget_id}/demands           demands of a budget
    GET    /budgets/{budget_id}/reconciliation    the reconciliation, if computed
    POST   /budgets/{budget_id}/reconciliation/compute
    POST   /budgets/{budget_id}/reconciliation/post
    GET    /{association_id}                      association
    PATCH  /{association_id}                      edit
    DELETE /{association_id}                      delete (no approved budget)
    GET    /{association_id}/keys                 keys
    POST   /{association_id}/keys                 create a key
    GET    /{association_id}/budgets              budgets
    POST   /{association_id}/budgets              create a budget
    GET    /{association_id}/validate             run the rule set
    GET    /{association_id}/export?format=       csv or json
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.service_charges.models import ChargeBudget
from app.modules.service_charges.schemas import (
    AssociationCreate,
    AssociationListResponse,
    AssociationResponse,
    AssociationUpdate,
    BudgetCreate,
    BudgetLineIn,
    BudgetLineResponse,
    BudgetLineUpdate,
    BudgetResponse,
    BudgetUnitsResponse,
    BudgetUpdate,
    DemandResponse,
    DemandRunRequest,
    DemandRunResponse,
    KeyCreate,
    KeyResponse,
    KeyUpdate,
    ReconciliationResponse,
    ValidationResponse,
)
from app.modules.service_charges.service import ServiceChargesService

router = APIRouter(tags=["service_charges"])


def _uid(user_id: str | None) -> str | None:
    return str(user_id) if user_id else None


def _budget(budget: ChargeBudget) -> BudgetResponse:
    out = BudgetResponse.model_validate(budget)
    out.total = sum((Decimal(ln.amount) for ln in budget.lines), Decimal("0"))
    return out


# ── Associations (collection) ────────────────────────────────────────────


@router.get("/", response_model=AssociationListResponse)
async def list_associations(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("service_charges.read")),
) -> AssociationListResponse:
    """Owners associations of one project."""
    await verify_project_access(project_id, user_id or "", session)
    rows = await ServiceChargesService(session).repo.associations(project_id)
    return AssociationListResponse(items=[AssociationResponse.model_validate(r) for r in rows], total=len(rows))


@router.post("/", response_model=AssociationResponse, status_code=201)
async def create_association(
    body: AssociationCreate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("service_charges.create")),
) -> AssociationResponse:
    """Create an owners association."""
    await verify_project_access(body.project_id, user_id or "", session)
    row = await ServiceChargesService(session).create_association(body, _uid(user_id))
    return AssociationResponse.model_validate(row)


@router.post("/demands/run", response_model=DemandRunResponse)
async def run_demands(
    body: DemandRunRequest,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("service_charges.bill")),
) -> DemandRunResponse:
    """Raise one demand per unit for a period as finance receivable drafts; a rerun skips raised ones."""
    service = ServiceChargesService(session)
    budget = await service.budget(body.budget_id)
    await verify_project_access(budget.project_id, user_id or "", session)
    assoc = await service.association(budget.association_id)
    result = await service.run_demands(
        assoc, budget, body.period, body.issue_date, body.payment_terms_days, _uid(user_id)
    )
    return DemandRunResponse(**result)


# ── Keys ─────────────────────────────────────────────────────────────────


@router.get("/keys/{key_id}", response_model=KeyResponse)
async def get_key(
    key_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("service_charges.read")),
) -> KeyResponse:
    """One apportionment key."""
    key = await ServiceChargesService(session).key(key_id)
    await verify_project_access(key.project_id, user_id or "", session)
    return KeyResponse.model_validate(key)


@router.patch("/keys/{key_id}", response_model=KeyResponse)
async def update_key(
    key_id: uuid.UUID,
    body: KeyUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("service_charges.update")),
) -> KeyResponse:
    """Edit a key; its shares are locked once it splits an approved budget."""
    service = ServiceChargesService(session)
    key = await service.key(key_id)
    await verify_project_access(key.project_id, user_id or "", session)
    assoc = await service.association(key.association_id)
    return KeyResponse.model_validate(await service.update_key(assoc, key, body))


@router.delete("/keys/{key_id}", status_code=204)
async def delete_key(
    key_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("service_charges.delete")),
) -> Response:
    """Delete a key no budget line uses."""
    service = ServiceChargesService(session)
    key = await service.key(key_id)
    await verify_project_access(key.project_id, user_id or "", session)
    await service.delete_key(key)
    return Response(status_code=204)


# ── Budgets ──────────────────────────────────────────────────────────────


@router.get("/budgets/{budget_id}", response_model=BudgetResponse)
async def get_budget(
    budget_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("service_charges.read")),
) -> BudgetResponse:
    """One budget with its lines."""
    budget = await ServiceChargesService(session).budget(budget_id)
    await verify_project_access(budget.project_id, user_id or "", session)
    return _budget(budget)


@router.patch("/budgets/{budget_id}", response_model=BudgetResponse)
async def update_budget(
    budget_id: uuid.UUID,
    body: BudgetUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("service_charges.update")),
) -> BudgetResponse:
    """Edit a draft budget."""
    service = ServiceChargesService(session)
    budget = await service.budget(budget_id)
    await verify_project_access(budget.project_id, user_id or "", session)
    assoc = await service.association(budget.association_id)
    return _budget(await service.update_budget(assoc, budget, body))


@router.delete("/budgets/{budget_id}", status_code=204)
async def delete_budget(
    budget_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("service_charges.delete")),
) -> Response:
    """Delete a draft budget."""
    service = ServiceChargesService(session)
    budget = await service.budget(budget_id)
    await verify_project_access(budget.project_id, user_id or "", session)
    await service.delete_budget(budget)
    return Response(status_code=204)


@router.post("/budgets/{budget_id}/approve", response_model=BudgetResponse)
async def approve_budget(
    budget_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("service_charges.approve")),
) -> BudgetResponse:
    """Approve a draft budget; the service charges rules must pass."""
    service = ServiceChargesService(session)
    budget = await service.budget(budget_id)
    await verify_project_access(budget.project_id, user_id or "", session)
    assoc = await service.association(budget.association_id)
    return _budget(await service.approve_budget(assoc, budget, _uid(user_id)))


@router.get("/budgets/{budget_id}/units", response_model=BudgetUnitsResponse)
async def budget_units(
    budget_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("service_charges.read")),
) -> BudgetUnitsResponse:
    """Yearly and per-period charge of every unit under the budget."""
    service = ServiceChargesService(session)
    budget = await service.budget(budget_id)
    await verify_project_access(budget.project_id, user_id or "", session)
    assoc = await service.association(budget.association_id)
    return BudgetUnitsResponse(**await service.unit_charges(assoc, budget))


@router.post("/budgets/{budget_id}/lines", response_model=BudgetLineResponse, status_code=201)
async def add_budget_line(
    budget_id: uuid.UUID,
    body: BudgetLineIn,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("service_charges.update")),
) -> BudgetLineResponse:
    """Add a cost category line to a draft budget."""
    service = ServiceChargesService(session)
    budget = await service.budget(budget_id)
    await verify_project_access(budget.project_id, user_id or "", session)
    assoc = await service.association(budget.association_id)
    return BudgetLineResponse.model_validate(await service.add_line(assoc, budget, body))


@router.patch("/budget-lines/{line_id}", response_model=BudgetLineResponse)
async def update_budget_line(
    line_id: uuid.UUID,
    body: BudgetLineUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("service_charges.update")),
) -> BudgetLineResponse:
    """Edit a line of a draft budget."""
    service = ServiceChargesService(session)
    line = await service.budget_line(line_id)
    budget = await service.budget(line.budget_id)
    await verify_project_access(budget.project_id, user_id or "", session)
    assoc = await service.association(budget.association_id)
    return BudgetLineResponse.model_validate(await service.update_line(assoc, budget, line, body))


@router.delete("/budget-lines/{line_id}", status_code=204)
async def delete_budget_line(
    line_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("service_charges.update")),
) -> Response:
    """Delete a line of a draft budget."""
    service = ServiceChargesService(session)
    line = await service.budget_line(line_id)
    budget = await service.budget(line.budget_id)
    await verify_project_access(budget.project_id, user_id or "", session)
    await service.delete_line(budget, line)
    return Response(status_code=204)


@router.get("/budgets/{budget_id}/demands", response_model=list[DemandResponse])
async def list_demands(
    budget_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("service_charges.read")),
) -> list[DemandResponse]:
    """Demands raised under a budget."""
    service = ServiceChargesService(session)
    budget = await service.budget(budget_id)
    await verify_project_access(budget.project_id, user_id or "", session)
    return [DemandResponse.model_validate(d) for d in await service.repo.demands(budget.id)]


@router.get("/budgets/{budget_id}/reconciliation", response_model=ReconciliationResponse | None)
async def get_reconciliation(
    budget_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("service_charges.read")),
) -> ReconciliationResponse | None:
    """The year-end reconciliation of a budget, or null before it is computed."""
    service = ServiceChargesService(session)
    budget = await service.budget(budget_id)
    await verify_project_access(budget.project_id, user_id or "", session)
    rec = await service.repo.reconciliation(budget.id)
    return None if rec is None else ReconciliationResponse.model_validate(rec)


@router.post("/budgets/{budget_id}/reconciliation/compute", response_model=ReconciliationResponse)
async def compute_reconciliation(
    budget_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("service_charges.update")),
) -> ReconciliationResponse:
    """Read actual costs and compute every unit's balance; recomputable until posted."""
    service = ServiceChargesService(session)
    budget = await service.budget(budget_id)
    await verify_project_access(budget.project_id, user_id or "", session)
    assoc = await service.association(budget.association_id)
    return ReconciliationResponse.model_validate(await service.compute_reconciliation(assoc, budget))


@router.post("/budgets/{budget_id}/reconciliation/post", response_model=ReconciliationResponse)
async def post_reconciliation(
    budget_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("service_charges.bill")),
) -> ReconciliationResponse:
    """Raise balancing charges and credits through finance and close the budget."""
    service = ServiceChargesService(session)
    budget = await service.budget(budget_id)
    await verify_project_access(budget.project_id, user_id or "", session)
    assoc = await service.association(budget.association_id)
    return ReconciliationResponse.model_validate(await service.post_reconciliation(assoc, budget, _uid(user_id)))


# ── Association (object) ─────────────────────────────────────────────────


@router.get("/{association_id}", response_model=AssociationResponse)
async def get_association(
    association_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("service_charges.read")),
) -> AssociationResponse:
    """One owners association."""
    assoc = await ServiceChargesService(session).association(association_id)
    await verify_project_access(assoc.project_id, user_id or "", session)
    return AssociationResponse.model_validate(assoc)


@router.patch("/{association_id}", response_model=AssociationResponse)
async def update_association(
    association_id: uuid.UUID,
    body: AssociationUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("service_charges.update")),
) -> AssociationResponse:
    """Edit an association; the currency is fixed once a budget is approved."""
    service = ServiceChargesService(session)
    assoc = await service.association(association_id)
    await verify_project_access(assoc.project_id, user_id or "", session)
    return AssociationResponse.model_validate(await service.update_association(assoc, body))


@router.delete("/{association_id}", status_code=204)
async def delete_association(
    association_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("service_charges.delete")),
) -> Response:
    """Delete an association that has no approved budget."""
    service = ServiceChargesService(session)
    assoc = await service.association(association_id)
    await verify_project_access(assoc.project_id, user_id or "", session)
    await service.delete_association(assoc)
    return Response(status_code=204)


@router.get("/{association_id}/keys", response_model=list[KeyResponse])
async def list_keys(
    association_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("service_charges.read")),
) -> list[KeyResponse]:
    """Apportionment keys of an association."""
    service = ServiceChargesService(session)
    assoc = await service.association(association_id)
    await verify_project_access(assoc.project_id, user_id or "", session)
    return [KeyResponse.model_validate(k) for k in await service.repo.keys(assoc.id)]


@router.post("/{association_id}/keys", response_model=KeyResponse, status_code=201)
async def create_key(
    association_id: uuid.UUID,
    body: KeyCreate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("service_charges.create")),
) -> KeyResponse:
    """Create an apportionment key; its shares must add up exactly."""
    service = ServiceChargesService(session)
    assoc = await service.association(association_id)
    await verify_project_access(assoc.project_id, user_id or "", session)
    return KeyResponse.model_validate(await service.create_key(assoc, body))


@router.get("/{association_id}/budgets", response_model=list[BudgetResponse])
async def list_budgets(
    association_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("service_charges.read")),
) -> list[BudgetResponse]:
    """Budgets of an association, newest year first."""
    service = ServiceChargesService(session)
    assoc = await service.association(association_id)
    await verify_project_access(assoc.project_id, user_id or "", session)
    return [_budget(b) for b in await service.repo.budgets(assoc.id)]


@router.post("/{association_id}/budgets", response_model=BudgetResponse, status_code=201)
async def create_budget(
    association_id: uuid.UUID,
    body: BudgetCreate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("service_charges.create")),
) -> BudgetResponse:
    """Create a draft budget; one per association and year."""
    service = ServiceChargesService(session)
    assoc = await service.association(association_id)
    await verify_project_access(assoc.project_id, user_id or "", session)
    return _budget(await service.create_budget(assoc, body))


@router.get("/{association_id}/validate", response_model=ValidationResponse)
async def validate_association(
    association_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("service_charges.read")),
) -> ValidationResponse:
    """Run the service charges rule set over the association and its keys."""
    service = ServiceChargesService(session)
    assoc = await service.association(association_id)
    await verify_project_access(assoc.project_id, user_id or "", session)
    data = await service.validation_payload(assoc)
    return ValidationResponse(**await service.validate(data, str(assoc.id), assoc.project_id))


@router.get("/{association_id}/export", response_model=None)
async def export_association(
    association_id: uuid.UUID,
    session: SessionDep,
    format: str = Query(default="json", pattern="^(json|csv)$"),  # noqa: A002 - public query name
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("service_charges.read")),
) -> Response:
    """Keys, budgets, demands and reconciliations as JSON, or the demands as CSV."""
    service = ServiceChargesService(session)
    assoc = await service.association(association_id)
    await verify_project_access(assoc.project_id, user_id or "", session)
    body, media_type, ext = await service.export(assoc, format)
    if not body:
        raise HTTPException(status_code=404, detail="Nothing to export")
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="service-charges.{ext}"'},
    )
