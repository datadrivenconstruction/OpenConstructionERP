"""‌⁠‍Contracts API routes.

Mounted at ``/api/v1/contracts/`` by the module loader.

Endpoint groups:
    /contracts                  — CRUD + status transitions
    /contracts/{id}/lines       — SoV line CRUD + bulk insert
    /type-configurations        — read-only type catalog
    /retention-schedules        — CRUD
    /fee-structures             — CRUD
    /gainshare-configurations   — CRUD
    /ld-clauses                 — CRUD
    /progress-claims            — CRUD + state transitions + auto-generate
    /progress-claim-lines       — CRUD
    /final-accounts             — CRUD + /contracts/{id}/close shortcut

Every project-scoped endpoint enforces :func:`verify_project_access` so users
cannot read/mutate contracts of projects they don't own. The catalog endpoint
``/type-configurations/`` is intentionally tenant-wide (read-only metadata).
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.i18n import get_locale
from app.core.validation.messages import translate
from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.contracts.models import (
    Contract,
    ContractLine,
    FeeStructure,
    FinalAccount,
    GainshareConfiguration,
    LDClause,
    ProgressClaim,
    ProgressClaimLine,
    RetentionSchedule,
)
from app.modules.contracts.repository import (
    ContractTypeConfigurationRepository,
    FeeStructureRepository,
    FinalAccountRepository,
    GainshareConfigurationRepository,
    LDClauseRepository,
    ProgressClaimLineRepository,
    RetentionScheduleRepository,
)
from app.modules.contracts.schemas import (
    AutoGenerateClaimRequest,
    ContractCloneRequest,
    ContractCreate,
    ContractDashboardResponse,
    ContractLineBulkCreate,
    ContractLineCreate,
    ContractLineResponse,
    ContractLineUpdate,
    ContractResponse,
    ContractTypeConfigurationResponse,
    ContractUpdate,
    FeeStructureCreate,
    FeeStructureResponse,
    FeeStructureUpdate,
    FinalAccountCreate,
    FinalAccountResponse,
    FinalAccountUpdate,
    GainshareCalculation,
    GainshareConfigurationCreate,
    GainshareConfigurationResponse,
    GainshareConfigurationUpdate,
    LDClauseCreate,
    LDClauseResponse,
    LDClauseUpdate,
    ProgressClaimCreate,
    ProgressClaimLineCreate,
    ProgressClaimLineResponse,
    ProgressClaimLineUpdate,
    ProgressClaimResponse,
    ProgressClaimUpdate,
    RetentionScheduleCreate,
    RetentionScheduleResponse,
    RetentionScheduleUpdate,
)
from app.modules.contracts.service import ContractsService

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> ContractsService:
    return ContractsService(session)


# ── helpers ──────────────────────────────────────────────────────────────


async def _load_contract_or_404(session, contract_id: uuid.UUID) -> Contract:
    obj = await session.get(Contract, contract_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Contract not found")
    return obj


async def _load_claim_or_404(session, claim_id: uuid.UUID) -> ProgressClaim:
    obj = await session.get(ProgressClaim, claim_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=translate("errors.claim_not_found", locale=get_locale()))
    return obj


async def _verify_contract_access(
    session,
    contract_id: uuid.UUID,
    user_id: str,
) -> Contract:
    contract = await _load_contract_or_404(session, contract_id)
    await verify_project_access(contract.project_id, user_id, session)
    return contract


async def _verify_claim_access(
    session,
    claim_id: uuid.UUID,
    user_id: str,
) -> ProgressClaim:
    claim = await _load_claim_or_404(session, claim_id)
    contract = await _load_contract_or_404(session, claim.contract_id)
    await verify_project_access(contract.project_id, user_id, session)
    return claim


def _contract_to_response(item: Contract) -> ContractResponse:
    return ContractResponse(
        id=item.id,
        code=item.code,
        title=item.title,
        contract_type=item.contract_type,
        counterparty_type=item.counterparty_type,
        counterparty_id=item.counterparty_id,
        project_id=item.project_id,
        parent_contract_id=item.parent_contract_id,
        start_date=item.start_date,
        end_date=item.end_date,
        total_value=item.total_value,
        currency=item.currency,
        retention_percent=item.retention_percent,
        retention_release_event=item.retention_release_event,
        status=item.status,
        signed_at=item.signed_at,
        terms=item.terms or {},
        created_by=item.created_by,
        metadata=getattr(item, "metadata_", {}) or {},
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _line_to_response(item: ContractLine) -> ContractLineResponse:
    return ContractLineResponse(
        id=item.id,
        contract_id=item.contract_id,
        parent_line_id=item.parent_line_id,
        code=item.code,
        description=item.description,
        scope_section=item.scope_section,
        line_type=item.line_type,
        unit=item.unit,
        quantity=item.quantity,
        unit_rate=item.unit_rate,
        total_value=item.total_value,
        order_index=item.order_index,
        metadata=getattr(item, "metadata_", {}) or {},
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _claim_to_response(item: ProgressClaim) -> ProgressClaimResponse:
    return ProgressClaimResponse(
        id=item.id,
        contract_id=item.contract_id,
        claim_number=item.claim_number,
        period_start=item.period_start,
        period_end=item.period_end,
        claim_date=item.claim_date,
        gross_amount=item.gross_amount,
        retention_amount=item.retention_amount,
        prior_claims_total=item.prior_claims_total,
        net_due=item.net_due,
        status=item.status,
        submitted_at=item.submitted_at,
        approved_at=item.approved_at,
        paid_at=item.paid_at,
        currency=item.currency,
        metadata=getattr(item, "metadata_", {}) or {},
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


# ── Contracts ────────────────────────────────────────────────────────────


@router.get("/contracts/", response_model=list[ContractResponse])
async def list_contracts(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    status: str | None = Query(default=None),
    counterparty_type: str | None = Query(default=None),
    contract_type: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> list[ContractResponse]:
    """‌⁠‍List contracts for a project."""
    await verify_project_access(project_id, user_id, session)
    service = ContractsService(session)
    items, _total = await service.contract_repo.list_for_project(
        project_id,
        offset=offset,
        limit=limit,
        status=status,
        counterparty_type=counterparty_type,
        contract_type=contract_type,
    )
    return [_contract_to_response(i) for i in items]


@router.post("/contracts/", response_model=ContractResponse, status_code=201)
async def create_contract(
    data: ContractCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("contracts.create")),
) -> ContractResponse:
    await verify_project_access(data.project_id, user_id, session)
    service = ContractsService(session)
    contract = await service.create_contract(data, user_id=user_id)
    return _contract_to_response(contract)


@router.get("/contracts/{contract_id}", response_model=ContractResponse)
async def get_contract(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> ContractResponse:
    contract = await _verify_contract_access(session, contract_id, user_id)
    return _contract_to_response(contract)


@router.patch("/contracts/{contract_id}", response_model=ContractResponse)
async def update_contract(
    contract_id: uuid.UUID,
    data: ContractUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.update")),
) -> ContractResponse:
    await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    contract = await service.update_contract(contract_id, data)
    return _contract_to_response(contract)


@router.delete("/contracts/{contract_id}", status_code=204)
async def delete_contract(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.delete")),
) -> None:
    await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    await service.delete_contract(contract_id)


@router.post("/contracts/{contract_id}/sign", response_model=ContractResponse)
async def sign_contract(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.sign")),
) -> ContractResponse:
    await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    contract = await service.transition_contract(contract_id, "active", user_id)
    return _contract_to_response(contract)


@router.post("/contracts/{contract_id}/suspend", response_model=ContractResponse)
async def suspend_contract(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.update")),
) -> ContractResponse:
    await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    contract = await service.transition_contract(contract_id, "suspended", user_id)
    return _contract_to_response(contract)


@router.post("/contracts/{contract_id}/resume", response_model=ContractResponse)
async def resume_contract(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.update")),
) -> ContractResponse:
    await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    contract = await service.transition_contract(contract_id, "active", user_id)
    return _contract_to_response(contract)


@router.post("/contracts/{contract_id}/terminate", response_model=ContractResponse)
async def terminate_contract(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.terminate")),
) -> ContractResponse:
    await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    contract = await service.transition_contract(contract_id, "terminated", user_id)
    return _contract_to_response(contract)


@router.post(
    "/contracts/{contract_id}/clone",
    response_model=ContractResponse,
    status_code=201,
)
async def clone_contract(
    contract_id: uuid.UUID,
    payload: ContractCloneRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.clone")),
) -> ContractResponse:
    """Deep-clone a contract.

    Cross-tenant safety (R7):
        1. The caller must have project-level access on the **source**
           contract — enforced via ``_verify_contract_access``.
        2. If ``payload.target_project_id`` is given, the caller must
           ALSO have project-level access on the **destination** —
           enforced via a second ``verify_project_access`` call.
           Without this gate, IDOR turns into cross-tenant data
           exfiltration: a manager on project A could clone project A's
           confidential commercial terms into project B (which they own)
           and walk away with them.
        3. The route requires the ``contracts.clone`` permission
           (manager-or-higher).
    """
    source = await _verify_contract_access(session, contract_id, user_id)
    if payload.target_project_id is not None and payload.target_project_id != source.project_id:
        await verify_project_access(payload.target_project_id, user_id, session)
    service = ContractsService(session)
    clone = await service.clone_contract(
        contract_id,
        new_code=payload.new_code,
        target_project_id=payload.target_project_id,
        new_title=payload.new_title,
        include_lines=payload.include_lines,
        copy_subconfigs=payload.copy_subconfigs,
        user_id=user_id,
    )
    return _contract_to_response(clone)


# ── ContractLines ────────────────────────────────────────────────────────


@router.get(
    "/contracts/{contract_id}/lines",
    response_model=list[ContractLineResponse],
)
async def list_contract_lines(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> list[ContractLineResponse]:
    await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    lines = await service.line_repo.list_for_contract(contract_id)
    return [_line_to_response(ln) for ln in lines]


@router.post(
    "/contracts/{contract_id}/lines",
    response_model=ContractLineResponse,
    status_code=201,
)
async def create_contract_line(
    contract_id: uuid.UUID,
    data: ContractLineCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.create")),
) -> ContractLineResponse:
    if data.contract_id != contract_id:
        raise HTTPException(
            status_code=400,
            detail="contract_id mismatch between URL and body",
        )
    await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    await service.get_contract(contract_id)
    line = await service.create_line(data)
    return _line_to_response(line)


@router.post(
    "/contracts/{contract_id}/lines/bulk",
    response_model=list[ContractLineResponse],
    status_code=201,
)
async def bulk_create_contract_lines(
    contract_id: uuid.UUID,
    payload: ContractLineBulkCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.create")),
) -> list[ContractLineResponse]:
    await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    items = [it for it in payload.lines if it.contract_id == contract_id]
    if len(items) != len(payload.lines):
        raise HTTPException(
            status_code=400,
            detail="All bulk lines must share the URL contract_id",
        )
    lines = await service.bulk_create_lines(contract_id, items)
    return [_line_to_response(ln) for ln in lines]


@router.patch(
    "/contracts/lines/{line_id}",
    response_model=ContractLineResponse,
)
async def update_contract_line(
    line_id: uuid.UUID,
    data: ContractLineUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.update")),
) -> ContractLineResponse:
    existing = await session.get(ContractLine, line_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Contract line not found")
    await _verify_contract_access(session, existing.contract_id, user_id)
    service = ContractsService(session)
    line = await service.update_line(line_id, data)
    return _line_to_response(line)


@router.delete(
    "/contracts/lines/{line_id}",
    status_code=204,
)
async def delete_contract_line(
    line_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.delete")),
) -> None:
    existing = await session.get(ContractLine, line_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Contract line not found")
    await _verify_contract_access(session, existing.contract_id, user_id)
    service = ContractsService(session)
    await service.delete_line(line_id)


# ── Type configurations (read-only catalog) ──────────────────────────────


@router.get(
    "/type-configurations/",
    response_model=list[ContractTypeConfigurationResponse],
)
async def list_type_configurations(
    session: SessionDep,
    _user: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> list[ContractTypeConfigurationResponse]:
    """‌⁠‍Read-only catalog — tenant-wide metadata, no per-project access check."""
    repo = ContractTypeConfigurationRepository(session)
    items = await repo.list_all()
    return [ContractTypeConfigurationResponse.model_validate(it) for it in items]


# ── RetentionSchedule ────────────────────────────────────────────────────


@router.post(
    "/retention-schedules/",
    response_model=RetentionScheduleResponse,
    status_code=201,
)
async def create_retention_schedule(
    data: RetentionScheduleCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.create")),
) -> RetentionScheduleResponse:
    await _verify_contract_access(session, data.contract_id, user_id)
    repo = RetentionScheduleRepository(session)
    obj = RetentionSchedule(**data.model_dump())
    obj = await repo.create(obj)
    return RetentionScheduleResponse.model_validate(obj)


@router.get(
    "/retention-schedules/{schedule_id}",
    response_model=RetentionScheduleResponse,
)
async def get_retention_schedule(
    schedule_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> RetentionScheduleResponse:
    repo = RetentionScheduleRepository(session)
    obj = await repo.get_by_id(schedule_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Retention schedule not found")
    await _verify_contract_access(session, obj.contract_id, user_id)
    return RetentionScheduleResponse.model_validate(obj)


@router.patch(
    "/retention-schedules/{schedule_id}",
    response_model=RetentionScheduleResponse,
)
async def update_retention_schedule(
    schedule_id: uuid.UUID,
    data: RetentionScheduleUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.update")),
) -> RetentionScheduleResponse:
    repo = RetentionScheduleRepository(session)
    obj = await repo.get_by_id(schedule_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Retention schedule not found")
    await _verify_contract_access(session, obj.contract_id, user_id)
    fields = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    if fields:
        await repo.update_fields(schedule_id, **fields)
        await session.refresh(obj)
    return RetentionScheduleResponse.model_validate(obj)


@router.delete(
    "/retention-schedules/{schedule_id}",
    status_code=204,
)
async def delete_retention_schedule(
    schedule_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.delete")),
) -> None:
    repo = RetentionScheduleRepository(session)
    obj = await repo.get_by_id(schedule_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Retention schedule not found")
    await _verify_contract_access(session, obj.contract_id, user_id)
    await repo.delete(schedule_id)


# ── FeeStructure ─────────────────────────────────────────────────────────


@router.post(
    "/fee-structures/",
    response_model=FeeStructureResponse,
    status_code=201,
)
async def create_fee_structure(
    data: FeeStructureCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.create")),
) -> FeeStructureResponse:
    await _verify_contract_access(session, data.contract_id, user_id)
    repo = FeeStructureRepository(session)
    obj = FeeStructure(**data.model_dump())
    obj = await repo.create(obj)
    return FeeStructureResponse.model_validate(obj)


@router.get("/fee-structures/{fee_id}", response_model=FeeStructureResponse)
async def get_fee_structure(
    fee_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> FeeStructureResponse:
    repo = FeeStructureRepository(session)
    obj = await repo.get_by_id(fee_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Fee structure not found")
    await _verify_contract_access(session, obj.contract_id, user_id)
    return FeeStructureResponse.model_validate(obj)


@router.patch("/fee-structures/{fee_id}", response_model=FeeStructureResponse)
async def update_fee_structure(
    fee_id: uuid.UUID,
    data: FeeStructureUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.update")),
) -> FeeStructureResponse:
    repo = FeeStructureRepository(session)
    obj = await repo.get_by_id(fee_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Fee structure not found")
    await _verify_contract_access(session, obj.contract_id, user_id)
    fields = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    if fields:
        await repo.update_fields(fee_id, **fields)
        await session.refresh(obj)
    return FeeStructureResponse.model_validate(obj)


@router.delete("/fee-structures/{fee_id}", status_code=204)
async def delete_fee_structure(
    fee_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.delete")),
) -> None:
    repo = FeeStructureRepository(session)
    obj = await repo.get_by_id(fee_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Fee structure not found")
    await _verify_contract_access(session, obj.contract_id, user_id)
    await repo.delete(fee_id)


# ── GainshareConfiguration ───────────────────────────────────────────────


@router.post(
    "/gainshare-configurations/",
    response_model=GainshareConfigurationResponse,
    status_code=201,
)
async def create_gainshare_config(
    data: GainshareConfigurationCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.create")),
) -> GainshareConfigurationResponse:
    await _verify_contract_access(session, data.contract_id, user_id)
    repo = GainshareConfigurationRepository(session)
    obj = GainshareConfiguration(**data.model_dump())
    obj = await repo.create(obj)
    return GainshareConfigurationResponse.model_validate(obj)


@router.get(
    "/gainshare-configurations/{config_id}",
    response_model=GainshareConfigurationResponse,
)
async def get_gainshare_config(
    config_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> GainshareConfigurationResponse:
    repo = GainshareConfigurationRepository(session)
    obj = await repo.get_by_id(config_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Gainshare config not found")
    await _verify_contract_access(session, obj.contract_id, user_id)
    return GainshareConfigurationResponse.model_validate(obj)


@router.patch(
    "/gainshare-configurations/{config_id}",
    response_model=GainshareConfigurationResponse,
)
async def update_gainshare_config(
    config_id: uuid.UUID,
    data: GainshareConfigurationUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.update")),
) -> GainshareConfigurationResponse:
    repo = GainshareConfigurationRepository(session)
    obj = await repo.get_by_id(config_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Gainshare config not found")
    await _verify_contract_access(session, obj.contract_id, user_id)
    fields = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    if fields:
        await repo.update_fields(config_id, **fields)
        await session.refresh(obj)
    return GainshareConfigurationResponse.model_validate(obj)


@router.delete(
    "/gainshare-configurations/{config_id}",
    status_code=204,
)
async def delete_gainshare_config(
    config_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.delete")),
) -> None:
    repo = GainshareConfigurationRepository(session)
    obj = await repo.get_by_id(config_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Gainshare config not found")
    await _verify_contract_access(session, obj.contract_id, user_id)
    await repo.delete(config_id)


# ── LDClause ─────────────────────────────────────────────────────────────


@router.post(
    "/ld-clauses/",
    response_model=LDClauseResponse,
    status_code=201,
)
async def create_ld_clause(
    data: LDClauseCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.create")),
) -> LDClauseResponse:
    await _verify_contract_access(session, data.contract_id, user_id)
    repo = LDClauseRepository(session)
    obj = LDClause(**data.model_dump())
    obj = await repo.create(obj)
    return LDClauseResponse.model_validate(obj)


@router.get("/ld-clauses/{ld_id}", response_model=LDClauseResponse)
async def get_ld_clause(
    ld_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> LDClauseResponse:
    repo = LDClauseRepository(session)
    obj = await repo.get_by_id(ld_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="LD clause not found")
    await _verify_contract_access(session, obj.contract_id, user_id)
    return LDClauseResponse.model_validate(obj)


@router.patch("/ld-clauses/{ld_id}", response_model=LDClauseResponse)
async def update_ld_clause(
    ld_id: uuid.UUID,
    data: LDClauseUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.update")),
) -> LDClauseResponse:
    repo = LDClauseRepository(session)
    obj = await repo.get_by_id(ld_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="LD clause not found")
    await _verify_contract_access(session, obj.contract_id, user_id)
    fields = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    if fields:
        await repo.update_fields(ld_id, **fields)
        await session.refresh(obj)
    return LDClauseResponse.model_validate(obj)


@router.delete("/ld-clauses/{ld_id}", status_code=204)
async def delete_ld_clause(
    ld_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.delete")),
) -> None:
    repo = LDClauseRepository(session)
    obj = await repo.get_by_id(ld_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="LD clause not found")
    await _verify_contract_access(session, obj.contract_id, user_id)
    await repo.delete(ld_id)


# ── ProgressClaims ───────────────────────────────────────────────────────


@router.get(
    "/progress-claims/",
    response_model=list[ProgressClaimResponse],
)
async def list_progress_claims(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    status: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> list[ProgressClaimResponse]:
    await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    items, _total = await service.claim_repo.claims_for_contract(
        contract_id,
        offset=offset,
        limit=limit,
        status=status,
    )
    return [_claim_to_response(it) for it in items]


@router.post(
    "/progress-claims/",
    response_model=ProgressClaimResponse,
    status_code=201,
)
async def create_progress_claim(
    data: ProgressClaimCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.submit_claim")),
) -> ProgressClaimResponse:
    await _verify_contract_access(session, data.contract_id, user_id)
    service = ContractsService(session)
    claim = await service.create_progress_claim(data)
    return _claim_to_response(claim)


@router.get(
    "/progress-claims/{claim_id}",
    response_model=ProgressClaimResponse,
)
async def get_progress_claim(
    claim_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> ProgressClaimResponse:
    claim = await _verify_claim_access(session, claim_id, user_id)
    return _claim_to_response(claim)


@router.patch(
    "/progress-claims/{claim_id}",
    response_model=ProgressClaimResponse,
)
async def update_progress_claim(
    claim_id: uuid.UUID,
    data: ProgressClaimUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.update")),
) -> ProgressClaimResponse:
    obj = await _verify_claim_access(session, claim_id, user_id)
    service = ContractsService(session)
    fields = data.model_dump(exclude_unset=True)
    if "metadata" in fields:
        fields["metadata_"] = fields.pop("metadata")
    if fields:
        await service.claim_repo.update_fields(claim_id, **fields)
        await session.refresh(obj)
    return _claim_to_response(obj)


@router.delete(
    "/progress-claims/{claim_id}",
    status_code=204,
)
async def delete_progress_claim(
    claim_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.delete")),
) -> None:
    await _verify_claim_access(session, claim_id, user_id)
    service = ContractsService(session)
    await service.claim_repo.delete(claim_id)


@router.post(
    "/progress-claims/{claim_id}/submit",
    response_model=ProgressClaimResponse,
)
async def submit_claim(
    claim_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.submit_claim")),
) -> ProgressClaimResponse:
    await _verify_claim_access(session, claim_id, user_id)
    service = ContractsService(session)
    claim = await service.transition_claim(claim_id, "submitted", user_id)
    return _claim_to_response(claim)


@router.post(
    "/progress-claims/{claim_id}/approve",
    response_model=ProgressClaimResponse,
)
async def approve_claim(
    claim_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.approve_claim")),
) -> ProgressClaimResponse:
    await _verify_claim_access(session, claim_id, user_id)
    service = ContractsService(session)
    claim = await service.transition_claim(claim_id, "approved", user_id)
    return _claim_to_response(claim)


@router.post(
    "/progress-claims/{claim_id}/certify",
    response_model=ProgressClaimResponse,
)
async def certify_claim(
    claim_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.certify_claim")),
) -> ProgressClaimResponse:
    await _verify_claim_access(session, claim_id, user_id)
    service = ContractsService(session)
    claim = await service.transition_claim(claim_id, "certified", user_id)
    return _claim_to_response(claim)


@router.post(
    "/progress-claims/{claim_id}/reject",
    response_model=ProgressClaimResponse,
)
async def reject_claim(
    claim_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.approve_claim")),
) -> ProgressClaimResponse:
    await _verify_claim_access(session, claim_id, user_id)
    service = ContractsService(session)
    claim = await service.transition_claim(claim_id, "rejected", user_id)
    return _claim_to_response(claim)


@router.post(
    "/progress-claims/{claim_id}/mark-paid",
    response_model=ProgressClaimResponse,
)
async def mark_claim_paid(
    claim_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.mark_paid")),
) -> ProgressClaimResponse:
    await _verify_claim_access(session, claim_id, user_id)
    service = ContractsService(session)
    claim = await service.transition_claim(claim_id, "paid", user_id)
    return _claim_to_response(claim)


@router.post(
    "/progress-claims/{claim_id}/auto-generate",
    response_model=ProgressClaimResponse,
)
async def auto_generate_claim(
    claim_id: uuid.UUID,
    payload: AutoGenerateClaimRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.update")),
) -> ProgressClaimResponse:
    await _verify_claim_access(session, claim_id, user_id)
    service = ContractsService(session)
    claim = await service.auto_generate_claim_lines(claim_id, payload)
    return _claim_to_response(claim)


# ── ProgressClaimLines ───────────────────────────────────────────────────


@router.get(
    "/progress-claims/{claim_id}/lines",
    response_model=list[ProgressClaimLineResponse],
)
async def list_claim_lines(
    claim_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> list[ProgressClaimLineResponse]:
    await _verify_claim_access(session, claim_id, user_id)
    repo = ProgressClaimLineRepository(session)
    items = await repo.list_for_claim(claim_id)
    return [ProgressClaimLineResponse.model_validate(it) for it in items]


@router.post(
    "/progress-claim-lines/",
    response_model=ProgressClaimLineResponse,
    status_code=201,
)
async def create_claim_line(
    data: ProgressClaimLineCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.update")),
) -> ProgressClaimLineResponse:
    await _verify_claim_access(session, data.progress_claim_id, user_id)
    repo = ProgressClaimLineRepository(session)
    obj = ProgressClaimLine(**data.model_dump())
    obj = await repo.create(obj)
    return ProgressClaimLineResponse.model_validate(obj)


@router.patch(
    "/progress-claim-lines/{line_id}",
    response_model=ProgressClaimLineResponse,
)
async def update_claim_line(
    line_id: uuid.UUID,
    data: ProgressClaimLineUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.update")),
) -> ProgressClaimLineResponse:
    repo = ProgressClaimLineRepository(session)
    obj = await repo.get_by_id(line_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Claim line not found")
    await _verify_claim_access(session, obj.progress_claim_id, user_id)
    fields = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    if fields:
        await repo.update_fields(line_id, **fields)
        await session.refresh(obj)
    return ProgressClaimLineResponse.model_validate(obj)


@router.delete(
    "/progress-claim-lines/{line_id}",
    status_code=204,
)
async def delete_claim_line(
    line_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.delete")),
) -> None:
    repo = ProgressClaimLineRepository(session)
    obj = await repo.get_by_id(line_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Claim line not found")
    await _verify_claim_access(session, obj.progress_claim_id, user_id)
    await repo.delete(line_id)


# ── FinalAccount ─────────────────────────────────────────────────────────


@router.post(
    "/final-accounts/",
    response_model=FinalAccountResponse,
    status_code=201,
)
async def create_final_account(
    data: FinalAccountCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.close")),
) -> FinalAccountResponse:
    await _verify_contract_access(session, data.contract_id, user_id)
    repo = FinalAccountRepository(session)
    obj = FinalAccount(**data.model_dump())
    obj = await repo.create(obj)
    return FinalAccountResponse.model_validate(obj)


@router.get(
    "/final-accounts/{account_id}",
    response_model=FinalAccountResponse,
)
async def get_final_account(
    account_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> FinalAccountResponse:
    repo = FinalAccountRepository(session)
    obj = await repo.get_by_id(account_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=translate("errors.final_account_not_found", locale=get_locale()))
    await _verify_contract_access(session, obj.contract_id, user_id)
    return FinalAccountResponse.model_validate(obj)


@router.patch(
    "/final-accounts/{account_id}",
    response_model=FinalAccountResponse,
)
async def update_final_account(
    account_id: uuid.UUID,
    data: FinalAccountUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.update")),
) -> FinalAccountResponse:
    repo = FinalAccountRepository(session)
    obj = await repo.get_by_id(account_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=translate("errors.final_account_not_found", locale=get_locale()))
    await _verify_contract_access(session, obj.contract_id, user_id)
    fields = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    if fields:
        await repo.update_fields(account_id, **fields)
        await session.refresh(obj)
    return FinalAccountResponse.model_validate(obj)


@router.delete(
    "/final-accounts/{account_id}",
    status_code=204,
)
async def delete_final_account(
    account_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.delete")),
) -> None:
    repo = FinalAccountRepository(session)
    obj = await repo.get_by_id(account_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=translate("errors.final_account_not_found", locale=get_locale()))
    await _verify_contract_access(session, obj.contract_id, user_id)
    await repo.delete(account_id)


@router.post(
    "/contracts/{contract_id}/close",
    response_model=FinalAccountResponse,
)
async def close_contract(
    contract_id: uuid.UUID,
    payload: FinalAccountCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.close")),
) -> FinalAccountResponse:
    if payload.contract_id != contract_id:
        raise HTTPException(
            status_code=400,
            detail="contract_id mismatch between URL and body",
        )
    await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    final = await service.close_contract(contract_id, payload, user_id)
    return FinalAccountResponse.model_validate(final)


# ── Dashboard / preview ──────────────────────────────────────────────────


@router.get(
    "/contracts/{contract_id}/dashboard",
    response_model=ContractDashboardResponse,
)
async def contract_dashboard(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> ContractDashboardResponse:
    await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    dash = await service.contract_dashboard(contract_id)
    return ContractDashboardResponse(**dash)


@router.get(
    "/contracts/{contract_id}/gainshare-preview",
    response_model=GainshareCalculation,
)
async def gainshare_preview(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    actual_cost: Decimal = Query(...),
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> GainshareCalculation:
    await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    payload = await service.gainshare_preview(contract_id, actual_cost)
    return GainshareCalculation(**payload)


# ── Schedule of Values status ────────────────────────────────────────────


@router.get("/contracts/{contract_id}/sov-status")
async def sov_status(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> dict:
    """Per-line SoV status: scheduled vs billed vs earned vs paid + totals."""
    await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    result = await service.sov_status(contract_id)
    # Coerce Decimals to strings for JSON encoding
    return {
        "by_line": {
            lid: {k: str(v) if hasattr(v, "as_tuple") else v for k, v in row.items()}
            for lid, row in result["by_line"].items()
        },
        "totals": {k: str(v) if hasattr(v, "as_tuple") else v for k, v in result["totals"].items()},
    }


# ── Retention release ────────────────────────────────────────────────────


@router.post("/contracts/{contract_id}/retention/release")
async def release_retention(
    contract_id: uuid.UUID,
    payload: dict,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.update")),
) -> dict:
    """Release retention for a contract for the given event.

    Body:
        event: str — e.g. "substantial_completion" / "punch_list_complete" /
            "defects_liability_end" or a key from custom_schedule.
        custom_schedule: dict[event_name → percent] — optional override.
    """
    await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    event_name = payload.get("event")
    if not event_name or not isinstance(event_name, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="event is required",
        )
    custom = payload.get("custom_schedule")
    if custom is not None and not isinstance(custom, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="custom_schedule must be a dict",
        )
    return await service.release_retention(
        contract_id,
        event_name,
        custom_schedule=custom,
        actor_id=user_id,
    )


# ── Lien waivers ─────────────────────────────────────────────────────────


@router.post("/progress-claims/{claim_id}/lien-waivers")
async def attach_lien_waiver(
    claim_id: uuid.UUID,
    payload: dict,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.update")),
) -> dict:
    """Attach a lien waiver record (conditional/unconditional × partial/final)."""
    # Object-level scoping: a lien waiver carries dollar value and legal
    # weight — only someone with access to the owning project may attach it.
    await _verify_claim_access(session, claim_id, user_id)
    service = ContractsService(session)
    return await service.attach_lien_waiver(claim_id, payload, actor_id=user_id)


@router.get("/progress-claims/{claim_id}/lien-waivers")
async def list_lien_waivers(
    claim_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> list[dict]:
    await _verify_claim_access(session, claim_id, user_id)
    service = ContractsService(session)
    return await service.list_lien_waivers(claim_id)


# ── Contract clause templates (FIDIC / JCT / NEC / AIA / ConsensusDocs) ──


@router.get("/contract-templates/")
async def list_clause_templates(
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> list[dict]:
    from app.modules.contracts.service import list_contract_templates

    return list_contract_templates()


@router.get("/contract-templates/{template_code}")
async def get_clause_template(
    template_code: str,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> dict:
    from app.modules.contracts.service import get_contract_template

    try:
        return get_contract_template(template_code)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
