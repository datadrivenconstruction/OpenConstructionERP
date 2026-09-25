# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Contracts API routes.

Mounted at ``/api/v1/contracts/`` by the module loader.

Endpoint groups:
    /contracts                  - CRUD + status transitions
    /contracts/{id}/lines       - SoV line CRUD + bulk insert
    /type-configurations        - read-only type catalog
    /retention-schedules        - CRUD
    /fee-structures             - CRUD
    /gainshare-configurations   - CRUD
    /ld-clauses                 - CRUD
    /progress-claims            - CRUD + state transitions + auto-generate
    /progress-claim-lines       - CRUD
    /final-accounts             - CRUD + /contracts/{id}/close shortcut

Every project-scoped endpoint enforces :func:`verify_project_access` so users
cannot read/mutate contracts of projects they don't own. The catalog endpoint
``/type-configurations/`` is intentionally tenant-wide (read-only metadata).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.core.content_disposition import attachment_disposition
from app.core.i18n import get_locale
from app.core.json_merge import merge_metadata
from app.core.validation.messages import translate
from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.contracts.compliance_packs import list_rule_packs
from app.modules.contracts.models import (
    Contract,
    ContractDocument,
    ContractLine,
    ContractMilestone,
    ContractParty,
    ContractSecurity,
    EOTClaim,
    FeeStructure,
    GainshareConfiguration,
    LDClause,
    ProgressClaim,
    ProgressClaimLine,
)
from app.modules.contracts.repository import (
    ContractDocumentRepository,
    ContractMilestoneRepository,
    ContractSecurityRepository,
    ContractTypeConfigurationRepository,
    EOTClaimRepository,
    FeeStructureRepository,
    FinalAccountRepository,
    GainshareConfigurationRepository,
    LDClauseRepository,
    ProgressClaimLineRepository,
    RetentionReleaseRepository,
    RetentionScheduleRepository,
)
from app.modules.contracts.schemas import (
    AIAApplicationResponse,
    AutoGenerateClaimRequest,
    ContractCloneRequest,
    ContractCreate,
    ContractDashboardResponse,
    ContractDocumentCreate,
    ContractDocumentResponse,
    ContractDocumentUpdate,
    ContractLineBulkCreate,
    ContractLineCreate,
    ContractLineResponse,
    ContractLineUpdate,
    ContractListResponse,
    ContractMilestoneCreate,
    ContractMilestoneResponse,
    ContractMilestoneUpdate,
    ContractPartyCreate,
    ContractPartyResponse,
    ContractPartyUpdate,
    ContractResponse,
    ContractSecurityCreate,
    ContractSecurityResponse,
    ContractSecurityUpdate,
    ContractSigningSessionOpen,
    ContractSigningSessionResponse,
    ContractTemplateCreate,
    ContractTemplateForkRequest,
    ContractTemplateResponse,
    ContractTemplateUpdate,
    ContractTypeConfigurationResponse,
    ContractUpdate,
    EOTClaimCreate,
    EOTClaimResponse,
    EOTClaimUpdate,
    EOTDecisionRequest,
    FeeStructureCreate,
    FeeStructureResponse,
    FeeStructureUpdate,
    FinalAccountChecklistResponse,
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
    ProgressClaimCommitRequest,
    ProgressClaimCreate,
    ProgressClaimLineCreate,
    ProgressClaimLineResponse,
    ProgressClaimLineUpdate,
    ProgressClaimListResponse,
    ProgressClaimPopulatePreviewResponse,
    ProgressClaimResponse,
    ProgressClaimUpdate,
    RetentionPolicyResponse,
    RetentionPolicyUpdate,
    RetentionReleaseApprove,
    RetentionReleaseBill,
    RetentionReleaseCreate,
    RetentionReleasePreviewRequest,
    RetentionReleasePreviewResponse,
    RetentionReleaseResponse,
    RetentionScheduleCreate,
    RetentionScheduleResponse,
    RetentionScheduleUpdate,
    RetentionSummaryResponse,
    SovReconcileConfirm,
    TemplateCatalogueEntry,
    TemplateClauseSetRequest,
)
from app.modules.contracts.service import PERCENT_REGRESSED_META_KEY, ContractsService

router = APIRouter(tags=["contracts"])
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


def _line_to_response(item: ContractLine, *, billed: bool = False) -> ContractLineResponse:
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
        billed=billed,
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
        milestone_id=item.milestone_id,
        period_from=item.period_from,
        period_to=item.period_to,
        application_date=item.application_date,
        completed_stored_to_date=getattr(item, "completed_stored_to_date", None),
        retention_held_to_date=getattr(item, "retention_held_to_date", None),
        metadata=getattr(item, "metadata_", {}) or {},
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _party_to_response(item: ContractParty, resolved_name: str | None) -> ContractPartyResponse:
    resp = ContractPartyResponse.model_validate(item)
    resp.resolved_name = resolved_name
    return resp


# ── Contracts ────────────────────────────────────────────────────────────


@router.get("/contracts/", response_model=ContractListResponse)
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
) -> ContractListResponse:
    """List one page of contracts for a project.

    The repository has counted the whole matching set since it was written and
    the count was discarded here, so the reader was handed at most `limit` rows
    with nothing to say whether that was the register or the start of it.
    """
    await verify_project_access(project_id, user_id, session)
    service = ContractsService(session)
    items, total = await service.contract_repo.list_for_project(
        project_id,
        offset=offset,
        limit=limit,
        status=status,
        counterparty_type=counterparty_type,
        contract_type=contract_type,
    )
    return ContractListResponse(
        items=[_contract_to_response(i) for i in items],
        total=total,
        offset=offset,
        limit=limit,
    )


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
    """Execute a contract directly, without collecting attestations.

    This is the one-actor path: the user with ``contracts.sign`` records that
    the contract is executed and it moves to active, gated by compliance. It
    stays because plenty of contracts are signed on paper and entered here
    afterwards. For a contract that has to collect signatures from several
    parties, open a signing session instead.
    """
    await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    contract = await service.transition_contract(contract_id, "active", user_id)
    return _contract_to_response(contract)


@router.post(
    "/contracts/{contract_id}/signing-session",
    response_model=ContractSigningSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def open_contract_signing_session(
    contract_id: uuid.UUID,
    data: ContractSigningSessionOpen,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.sign")),
) -> ContractSigningSessionResponse:
    """Put a draft contract up for signature by its parties.

    Runs the compliance gate before the session exists, so a contract that
    cannot be executed is refused with 422 while there is still something a
    person can do about it. The same gate runs again on the transition to
    active, which is what protects the direct sign endpoint above.
    """
    contract = await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    row = await service.open_signing_session(
        contract_id,
        provider_capability=data.provider_capability,
        expires_at=data.expires_at,
        signatories=([s.model_dump() for s in data.signatories] if data.signatories else None),
        actor_id=user_id,
    )
    return ContractSigningSessionResponse(**await service.signing_session_view(contract, row))


@router.get(
    "/contracts/{contract_id}/signing-sessions",
    response_model=list[ContractSigningSessionResponse],
)
async def list_contract_signing_sessions(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> list[ContractSigningSessionResponse]:
    """Every signing session opened against this contract, newest first."""
    contract = await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    rows = await service.list_signing_sessions(contract_id)
    return [ContractSigningSessionResponse(**await service.signing_session_view(contract, r)) for r in rows]


@router.post("/contracts/{contract_id}/signing-session/sync", response_model=ContractResponse)
async def sync_contract_from_signing(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.sign")),
) -> ContractResponse:
    """Move the contract to active once its session is fully signed.

    Idempotent and safe to call on a contract nobody has finished signing: it
    returns the contract unchanged unless a session actually reached
    ``fully_signed``. It is a POST rather than a side effect of the GET above
    because it changes the contract, and a read that quietly executes paper is
    not something a reviewer can reason about.
    """
    await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    contract = await service.sync_contract_from_signing(contract_id, user_id)
    return _contract_to_response(contract)


@router.get("/contracts/{contract_id}/compliance-gate")
async def preview_compliance_gate(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> dict:
    """Read-only preview of the compliance gate for a contract.

    Runs the same validation the ``draft → active`` (sign) transition runs,
    without mutating anything, so the ComplianceGate UI can show the user
    whether signing will be blocked and exactly which rules fail. Returns the
    resolved rule packs/sets, the overall status/score, and the grouped
    error / warning lists.
    """
    contract = await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    report, pack_ids = await service.run_compliance_gate(contract)

    def _serialise(r: object) -> dict:
        return {
            "rule_id": r.rule_id,
            "rule_name": r.rule_name,
            "severity": r.severity.value,
            "message": r.message,
            "element_ref": r.element_ref,
            "suggestion": r.suggestion,
        }

    return {
        "contract_id": str(contract.id),
        "contract_status": contract.status,
        "rule_packs": pack_ids,
        "rule_sets": report.rule_sets_applied,
        "status": report.status.value,
        "score": report.score,
        "blocked": report.has_errors,
        "counts": {
            "errors": len(report.errors),
            "warnings": len(report.warnings),
            "passed": len(report.passed_rules),
        },
        "errors": [_serialise(r) for r in report.errors],
        "warnings": [_serialise(r) for r in report.warnings],
    }


@router.get("/compliance-rule-packs/")
async def list_compliance_rule_packs(
    _user: CurrentUserId,
) -> list[dict]:
    """List the available jurisdiction compliance rule packs.

    Tenant-wide read-only catalogue metadata (id, name, description,
    jurisdiction, the workflow gates they enforce and the validation rule
    sets they bundle). The projects settings UI uses this to let a user pick
    which packs a project enforces at the contract-signature gate.
    """
    return list_rule_packs()


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
           contract - enforced via ``_verify_contract_access``.
        2. If ``payload.target_project_id`` is given, the caller must
           ALSO have project-level access on the **destination** -
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
    # The same query the service's refusal runs, so a line the screen shows
    # as editable is one the server will let it edit.
    billed = await service.claim_line_repo.claims_billing_lines([ln.id for ln in lines])
    return [_line_to_response(ln, billed=ln.id in billed) for ln in lines]


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
    """Read-only catalog - tenant-wide metadata, no per-project access check."""
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
    # A schedule's accrual rule is the ladder the engine reads, so the service
    # holds it to the accrual lock the retention policy editor keeps.
    obj = await ContractsService(session).create_retention_schedule(data)
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
    obj = await ContractsService(session).update_retention_schedule(schedule_id, data)
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
    await ContractsService(session).delete_retention_schedule(schedule_id)


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
    response_model=ProgressClaimListResponse,
)
async def list_progress_claims(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    status: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> ProgressClaimListResponse:
    """List one page of progress claims on a contract."""
    await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    items, total = await service.claim_repo.claims_for_contract(
        contract_id,
        offset=offset,
        limit=limit,
        status=status,
    )
    return ProgressClaimListResponse(
        items=[_claim_to_response(it) for it in items],
        total=total,
        offset=offset,
        limit=limit,
    )


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
        _incoming = fields.pop("metadata")
        fields["metadata_"] = (
            merge_metadata(getattr(obj, "metadata_", None), _incoming) if isinstance(_incoming, dict) else _incoming
        )
    # Status changes must go through the lifecycle transition endpoints
    # (submit / approve / certify / reject / mark-paid). They enforce the
    # claim FSM and emit the events finance / dashboards subscribe to; a raw
    # PATCH would skip both and could perform illegal jumps (e.g. submitted →
    # paid), corrupting the audit trail.
    if "status" in fields and fields["status"] != obj.status:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "status_not_directly_editable",
                "message": (
                    "Use the submit / approve / certify / reject / mark-paid endpoints to change progress claim status"
                ),
            },
        )
    fields.pop("status", None)
    # Through the service, so a corrected period string moves its date too.
    await service.update_progress_claim_fields(obj, fields)
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
    # Through the service, which refuses a claim past draft: its lines go
    # with it, and the claim line routes already refuse exactly that.
    await service.delete_progress_claim(claim_id)


@router.get("/progress-claims/{claim_id}/validation")
async def progress_claim_validation(
    claim_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> dict:
    """Run the payment application rules over one progress claim.

    Returns the report status, score and the grouped error and warning lists
    for a traffic-light panel. It is the same report the submit action blocks
    on, built by the same method, so what the panel shows is what submitting
    will do.
    """
    await _verify_claim_access(session, claim_id, user_id)
    service = ContractsService(session)
    return await service.validate_claim(claim_id)


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


# ── Progress bridge (Gap I): populate claim from progress observations ────


@router.get(
    "/progress-claims/{claim_id}/populate-from-progress",
    response_model=ProgressClaimPopulatePreviewResponse,
)
async def populate_claim_from_progress(
    claim_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    boq_position_ids: list[uuid.UUID] | None = Query(default=None),
    _perm: None = Depends(RequirePermission("contracts.update")),
) -> ProgressClaimPopulatePreviewResponse:
    """Preview claim lines derived from the latest progress observations.

    Read-only: returns the line breakdown the claim WOULD get if committed, so
    the UI can let the user deselect / tweak before saving. SoV lines that link
    to a BOQ position with at least one progress observation are included; lines
    that are unlinked, have no observation yet, or carry a different currency
    than the claim are skipped and counted (so the UI can hint why). Requires
    ``contracts.update`` and project-level access on the owning project.
    """
    await _verify_claim_access(session, claim_id, user_id)
    service = ContractsService(session)
    preview = await service.populate_claim_from_progress(
        claim_id,
        boq_position_ids=boq_position_ids,
    )
    return ProgressClaimPopulatePreviewResponse.model_validate(preview)


@router.put(
    "/progress-claims/{claim_id}/commit-populated-lines",
    response_model=ProgressClaimResponse,
)
async def commit_populated_claim_lines(
    claim_id: uuid.UUID,
    payload: ProgressClaimCommitRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.update")),
) -> ProgressClaimResponse:
    """Persist the ticked rows of a populate preview and roll up totals.

    Idempotent: the claim's lines on the ticked SoV lines are replaced, and its
    lines on every other SoV line are left as they are. Values are recomputed
    server-side (so a tampered total cannot inflate the claim), the claim's
    gross / retention / prior / net are re-rolled over all its lines, and
    ``contracts.claim.populated`` is emitted. Only valid on a draft claim.
    Requires ``contracts.update`` and project-level access.
    """
    await _verify_claim_access(session, claim_id, user_id)
    service = ContractsService(session)
    claim = await service.commit_preview_to_claim(
        claim_id,
        payload.lines,
        actor_id=user_id,
    )
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
    claim = await _verify_claim_access(session, data.progress_claim_id, user_id)
    # The line breakdown is part of the record once the claim leaves draft.
    # Mirror the PATCH / auto-generate guard so a raw POST cannot append (and
    # thereby alter) lines on a claim that is already with the payer.
    service = ContractsService(session)
    service._assert_claim_editable(claim)
    repo = ProgressClaimLineRepository(session)
    fields = data.model_dump()
    # Column D and the running total are derived, never client-authored: the
    # same "claims before this one" the generators use, plus this period.
    fields.update(await service.claim_line_running_totals(claim, data.contract_line_id, data.period_completed_value))
    obj = ProgressClaimLine(**fields)
    obj = await repo.create(obj)
    # Totals and retention follow the lines, so a hand-added line bills.
    await service.roll_claim_retention(claim.id, gross_follows_lines=True)
    await session.refresh(obj)
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
    claim = await _verify_claim_access(session, obj.progress_claim_id, user_id)
    # The claim line breakdown is part of the record once the parent claim
    # leaves draft. Mirror the service guard used by the auto-generate and
    # populate paths so a raw PATCH cannot rewrite a line the payer is reading.
    service = ContractsService(session)
    service._assert_claim_editable(claim)
    fields = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    if fields:
        # cumulative_completed_value is cumulative-to-date, never client-authored:
        # accepting it lets the inline editor clobber the running total and corrupt
        # earned-value + the AIA 'previous' column. Recompute it server-side with
        # the same semantics as commit_preview_to_claim: what the claims before
        # this one in billing order billed on this SoV line + this period's value.
        fields.pop("cumulative_completed_value", None)
        period_value = fields.get("period_completed_value", obj.period_completed_value)
        fields.update(await service.claim_line_running_totals(claim, obj.contract_line_id, period_value))
        await repo.update_fields(line_id, **fields)
        await session.refresh(obj)
        if "period_completed_value" in fields:
            # A value typed in by hand replaces whatever the percent asked for,
            # so a regression recorded for this line no longer describes it.
            entries = list((claim.metadata_ or {}).get(PERCENT_REGRESSED_META_KEY) or [])
            kept = [e for e in entries if str(e.get("contract_line_id")) != str(obj.contract_line_id)]
            if len(kept) != len(entries):
                await service.record_percent_regressed(claim, kept)
        await service.roll_claim_retention(claim.id, gross_follows_lines=True)
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
    claim = await _verify_claim_access(session, obj.progress_claim_id, user_id)
    # Deleting a line rewrites the claim as surely as editing one, so the
    # same guard applies: it used to delete lines off an approved claim.
    service = ContractsService(session)
    service._assert_claim_editable(claim)
    await repo.delete(line_id)
    # The claim is what its lines say, a claim with none included.
    await service.roll_claim_retention(claim.id, gross_follows_lines=True)


# ── AIA G702/G703 payment applications (US/CA/AU only) ─────────────────────
#
# AIA G702 (Application and Certificate for Payment) and G703 (Continuation
# Sheet) are the standard US progress-billing documents, also adopted in CA and
# AU. They are country-gated: the service raises 404 unless the claim's project
# country resolves to US/CA/AU, so for every other market these endpoints behave
# as if they do not exist (no information leak). They are an additive AIA
# presentation layer over the existing progress-claim engine - no new claim
# state, no duplicated retention/finance math.


@router.get(
    "/progress-claims/{claim_id}/aia-application",
    response_model=AIAApplicationResponse,
    summary="AIA G702 summary + G703 continuation for a progress claim (US/CA/AU)",
)
async def get_aia_application(
    claim_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> AIAApplicationResponse:
    await _verify_claim_access(session, claim_id, user_id)
    service = ContractsService(session)
    payload = await service.build_aia_application(claim_id)
    return AIAApplicationResponse.model_validate(payload)


@router.get(
    "/progress-claims/{claim_id}/aia-application/pdf",
    summary="Export the AIA G702/G703 application as PDF (US/CA/AU)",
    response_description="application/pdf stream",
)
async def export_aia_application_pdf(
    claim_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> StreamingResponse:
    import io

    from app.modules.contracts.aia_pdf import render_aia_application_pdf

    await _verify_claim_access(session, claim_id, user_id)
    service = ContractsService(session)
    # English, like every other word on the form and the Content-Language
    # below. The request's language would have printed one row in German or
    # Russian on an English page.
    payload = await service.build_aia_application(claim_id, locale="en")
    # ReportLab layout is CPU-bound and synchronous; in a thread it does not
    # stall every other request on the event loop while the form is drawn.
    pdf_bytes = await asyncio.to_thread(render_aia_application_pdf, payload)
    safe_num = "".join(c for c in str(payload.get("application_number") or "app") if c.isalnum() or c in "-_") or "app"
    filename = f"AIA_G702_{safe_num}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": attachment_disposition(filename),
            # The payment application is drawn from English literals in
            # aia_pdf.py and no locale reaches it, so the route declares English
            # rather than letting the Accept-Language middleware answer for it.
            # The form is a US contract instrument, so English is also the
            # language it is meant to be read in; that makes the declaration
            # settled rather than provisional, unlike the exports whose labels
            # would follow a catalogue if one existed.
            "Content-Language": "en",
        },
    )


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
    obj = await ContractsService(session).create_final_account(data)
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
    # The service holds the status to the lifecycle and keeps the figures of an
    # agreed or closed account, the same rule Close keeps.
    obj = await ContractsService(session).update_final_account(account_id, data)
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
    # An agreed or closed account is refused; a draft or disputed one goes.
    await ContractsService(session).delete_final_account(account_id)


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


@router.get(
    "/contracts/{contract_id}/final-account-checklist",
    response_model=FinalAccountChecklistResponse,
)
async def contract_final_account_checklist(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> FinalAccountChecklistResponse:
    """Final-account (close-out) readiness checklist for a contract.

    Evaluates the close-out conditions (progress claims settled, extension-of-time
    claims decided, financial securities released, retention released, final
    account agreed / signed off and reconciled against the contract sum) from the
    data the contract already stores. Read-only; adds no state.
    """
    await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    payload = await service.final_account_checklist(contract_id)
    return FinalAccountChecklistResponse(**payload)


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


@router.get("/contracts/{contract_id}/sov/reconcile-change-orders")
async def sov_reconcile_preview(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> dict:
    """Changes approved before they reached the schedule of values, and what posting them adds."""
    await _verify_contract_access(session, contract_id, user_id)
    return await ContractsService(session).sov_reconcile_preview(contract_id)


@router.post("/contracts/{contract_id}/sov/reconcile-change-orders")
async def sov_reconcile_apply(
    contract_id: uuid.UUID,
    body: SovReconcileConfirm,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.update")),
) -> dict:
    """Post the previewed changes as schedule of values lines, once a person confirms them.

    Nothing is posted unless ``source_keys`` is exactly the list the preview
    gives now (409 ``reconcile_preview_stale`` otherwise).
    """
    await _verify_contract_access(session, contract_id, user_id)
    return await ContractsService(session).sov_reconcile_apply(contract_id, body.source_keys, actor_id=user_id)


# ── Retention release ────────────────────────────────────────────────────


@router.post("/contracts/{contract_id}/retention/release")
async def release_retention(
    contract_id: uuid.UUID,
    payload: dict,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.update")),
) -> dict:
    """Propose a retention release for the given event (older shape).

    Body:
        event: str - a release event, canonical or an older alias such as
            "punch_list_complete" / "defects_liability_end".
        custom_schedule: dict[event_name → percent of held] - optional override.

    The release is proposed, not paid: approve it and bill it on a claim
    through ``/retention-releases/{id}``.
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


async def _verify_release_access(session: SessionDep, release_id: uuid.UUID, user_id: str) -> None:
    row = await RetentionReleaseRepository(session).get_by_id(release_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Retention release not found")
    await _verify_contract_access(session, row.contract_id, user_id)


@router.get("/contracts/{contract_id}/retention", response_model=RetentionSummaryResponse)
async def retention_summary(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> RetentionSummaryResponse:
    """Retention on a contract: accrued, paid back, committed and free to release, with every release."""
    await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    summary = await service.retention_summary(await service.get_contract(contract_id))
    return RetentionSummaryResponse(
        **{k: v for k, v in summary.items() if k != "releases"},
        releases=[RetentionReleaseResponse.model_validate(r) for r in summary["releases"]],
    )


@router.get("/contracts/{contract_id}/retention/policy", response_model=RetentionPolicyResponse)
async def get_retention_policy(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> RetentionPolicyResponse:
    """How this contract holds retention, where the rule came from and what can still change."""
    await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    contract = await service.get_contract(contract_id)
    return RetentionPolicyResponse.model_validate(await service.retention_policy_view(contract))


@router.put("/contracts/{contract_id}/retention/policy", response_model=RetentionPolicyResponse)
async def put_retention_policy(
    contract_id: uuid.UUID,
    data: RetentionPolicyUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.update")),
) -> RetentionPolicyResponse:
    """Change how this contract holds retention.

    The ladder is refused with 409 once a claim has left draft: from then on
    it is part of what that claim certified. The statute reference and the
    notes stay editable for the life of the contract.
    """
    await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    contract = await service.get_contract(contract_id)
    return RetentionPolicyResponse.model_validate(await service.set_retention_policy(contract, data))


@router.post(
    "/contracts/{contract_id}/retention/releases/preview",
    response_model=RetentionReleasePreviewResponse,
)
async def preview_retention_release(
    contract_id: uuid.UUID,
    data: RetentionReleasePreviewRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> RetentionReleasePreviewResponse:
    """What a release for the event would pay. Writes nothing."""
    await _verify_contract_access(session, contract_id, user_id)
    preview = await ContractsService(session).preview_retention_release(contract_id, data)
    return RetentionReleasePreviewResponse(**preview)


@router.post(
    "/contracts/{contract_id}/retention/releases",
    response_model=RetentionReleaseResponse,
    status_code=201,
)
async def create_retention_release(
    contract_id: uuid.UUID,
    data: RetentionReleaseCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.update")),
) -> RetentionReleaseResponse:
    """Propose a release. It pays nothing until it is approved and billed on a claim."""
    await _verify_contract_access(session, contract_id, user_id)
    row = await ContractsService(session).create_retention_release(contract_id, data, user_id)
    return RetentionReleaseResponse.model_validate(row)


@router.post("/retention-releases/{release_id}/approve", response_model=RetentionReleaseResponse)
async def approve_retention_release(
    release_id: uuid.UUID,
    data: RetentionReleaseApprove,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.approve_retention_release")),
) -> RetentionReleaseResponse:
    """Approve a proposed release; 422 while a document it needs is missing."""
    await _verify_release_access(session, release_id, user_id)
    row = await ContractsService(session).approve_retention_release(release_id, data, user_id)
    return RetentionReleaseResponse.model_validate(row)


@router.post("/retention-releases/{release_id}/bill", response_model=RetentionReleaseResponse)
async def bill_retention_release(
    release_id: uuid.UUID,
    data: RetentionReleaseBill,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.update")),
) -> RetentionReleaseResponse:
    """Bill an approved release on a draft claim of the same contract."""
    await _verify_release_access(session, release_id, user_id)
    await _verify_claim_access(session, data.progress_claim_id, user_id)
    row = await ContractsService(session).bill_retention_release(release_id, data, user_id)
    return RetentionReleaseResponse.model_validate(row)


@router.post("/retention-releases/{release_id}/void", response_model=RetentionReleaseResponse)
async def void_retention_release(
    release_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.update")),
) -> RetentionReleaseResponse:
    """Void a release; one billed on a claim that is still editable comes off that claim."""
    await _verify_release_access(session, release_id, user_id)
    row = await ContractsService(session).void_retention_release(release_id, user_id)
    return RetentionReleaseResponse.model_validate(row)


@router.post("/progress-claims/{claim_id}/retention/recalculate", response_model=ProgressClaimResponse)
async def recalculate_claim_retention(
    claim_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.update")),
) -> ProgressClaimResponse:
    """Work a draft claim's retention out again from its policy."""
    claim = await _verify_claim_access(session, claim_id, user_id)
    service = ContractsService(session)
    service._assert_claim_editable(claim)
    return _claim_to_response(await service.roll_claim_retention(claim_id))


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
    # weight - only someone with access to the owning project may attach it.
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


@router.get("/contract-templates/", response_model=list[TemplateCatalogueEntry])
async def list_clause_templates(
    session: SessionDep,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> list[dict]:
    """The catalogue a user picks from: built-in standard forms and authored paper.

    One entry per code. Built-ins are the eleven constants we ship, which
    nobody can edit; authored entries are the tenant's own, shown at their
    current version, which is the latest published one or the latest draft when
    the lineage has never been published. ``source`` and ``editable`` on each
    entry say which is which, so the caller never has to infer it.
    """
    service = ContractsService(session)
    return await service.list_templates()


@router.get("/contract-templates/{template_code}", response_model=ContractTemplateResponse)
async def get_clause_template(
    template_code: str,
    session: SessionDep,
    version: int | None = Query(default=None, ge=0),
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> dict:
    """One template, from whichever half of the namespace holds it.

    Without ``version`` this resolves the current version. With it, that exact
    authored version, which is how a contract shows the paper it was actually
    drawn from after a later version has been published.
    """
    service = ContractsService(session)
    return await service.get_template(template_code, version)


@router.get(
    "/contract-templates/{template_code}/versions",
    response_model=list[ContractTemplateResponse],
)
async def list_clause_template_versions(
    template_code: str,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> list[dict]:
    """Every version under one code, oldest first.

    A built-in answers with its single frozen entry rather than a 404, so one
    version-history screen serves both halves of the catalogue.
    """
    service = ContractsService(session)
    return await service.list_template_versions(template_code)


@router.post(
    "/contract-templates/",
    response_model=ContractTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_clause_template(
    data: ContractTemplateCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.author_template")),
) -> dict:
    """Author a new template. It starts at version 1, in draft."""
    service = ContractsService(session)
    body = await service.create_template(data, user_id)
    await session.commit()
    return body


@router.post(
    "/contract-templates/{template_code}/fork",
    response_model=ContractTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def fork_clause_template(
    template_code: str,
    data: ContractTemplateForkRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.author_template")),
) -> dict:
    """Copy a built-in standard form into an editable draft under a new code.

    This is the only way to change a built-in. The clause map we ship carries
    numbers and titles and no body text, so the fork starts with the headings
    and an empty body for each, rather than inventing contract language.
    """
    service = ContractsService(session)
    body = await service.fork_builtin_template(
        template_code,
        data.new_code,
        user_id,
        data.new_name,
    )
    await session.commit()
    return body


@router.patch(
    "/contract-templates/{template_code}/versions/{version}",
    response_model=ContractTemplateResponse,
)
async def update_clause_template(
    template_code: str,
    version: int,
    data: ContractTemplateUpdate,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("contracts.author_template")),
) -> dict:
    """Edit the header of a draft version. A published version is frozen."""
    service = ContractsService(session)
    body = await service.update_template(
        template_code,
        version,
        data.model_dump(exclude_unset=True),
    )
    await session.commit()
    return body


@router.put(
    "/contract-templates/{template_code}/versions/{version}/clauses",
    response_model=ContractTemplateResponse,
)
async def set_clause_template_clauses(
    template_code: str,
    version: int,
    data: TemplateClauseSetRequest,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("contracts.author_template")),
) -> dict:
    """Replace the whole clause set of a draft version."""
    service = ContractsService(session)
    body = await service.replace_template_clauses(template_code, version, data.clauses)
    await session.commit()
    return body


@router.post(
    "/contract-templates/{template_code}/versions/{version}/publish",
    response_model=ContractTemplateResponse,
)
async def publish_clause_template(
    template_code: str,
    version: int,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.publish_template")),
) -> dict:
    """Freeze a draft version so contracts can be drawn from it."""
    service = ContractsService(session)
    body = await service.publish_template(template_code, version, user_id)
    await session.commit()
    return body


@router.post(
    "/contract-templates/{template_code}/versions",
    response_model=ContractTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def open_next_clause_template_version(
    template_code: str,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.author_template")),
) -> dict:
    """Open version N+1 as a draft, copying the current version's clauses.

    This is what "edit a published template" means here. The published version
    keeps saying what it said, because a contract may already name it.
    """
    service = ContractsService(session)
    body = await service.open_next_template_version(template_code, user_id)
    await session.commit()
    return body


@router.post(
    "/contract-templates/{template_code}/versions/{version}/archive",
    response_model=ContractTemplateResponse,
)
async def archive_clause_template_version(
    template_code: str,
    version: int,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("contracts.publish_template")),
) -> dict:
    """Retire one version so it stops being offered.

    Not a delete. A contract drawn from this version keeps naming it, and the
    record of what it said has to survive for that reference to mean anything.
    """
    service = ContractsService(session)
    body = await service.archive_template_version(template_code, version)
    await session.commit()
    return body


# ── Counterparty resolution ──────────────────────────────────────────────


@router.get("/contracts/{contract_id}/counterparty")
async def get_contract_counterparty(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> dict:
    """Resolve the contract counterparty's live display name.

    The legacy ``counterparty_id`` is a plain UUID that may point at a contact
    or a subcontractor row; the service joins both directories and returns the
    resolved name (or None for the caller to fall back on).
    """
    contract = await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    return await service.counterparty_overview(contract)


# ── Parties (structured roles) ─────────────────────────────────────────────


@router.get(
    "/contracts/{contract_id}/parties",
    response_model=list[ContractPartyResponse],
)
async def list_contract_parties(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> list[ContractPartyResponse]:
    """List a contract's parties, each with its resolved live display name."""
    await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    pairs = await service.list_parties_with_names(contract_id)
    return [_party_to_response(p, name) for p, name in pairs]


@router.post(
    "/contracts/{contract_id}/parties",
    response_model=ContractPartyResponse,
    status_code=201,
)
async def create_contract_party(
    contract_id: uuid.UUID,
    data: ContractPartyCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.create")),
) -> ContractPartyResponse:
    if data.contract_id != contract_id:
        raise HTTPException(status_code=400, detail="contract_id mismatch between URL and body")
    await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    party = await service.create_party(data)
    return _party_to_response(party, await service.resolve_party_name(party))


@router.get("/contracts/parties/{party_id}", response_model=ContractPartyResponse)
async def get_contract_party(
    party_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> ContractPartyResponse:
    obj = await session.get(ContractParty, party_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Contract party not found")
    await _verify_contract_access(session, obj.contract_id, user_id)
    service = ContractsService(session)
    return _party_to_response(obj, await service.resolve_party_name(obj))


@router.patch("/contracts/parties/{party_id}", response_model=ContractPartyResponse)
async def update_contract_party(
    party_id: uuid.UUID,
    data: ContractPartyUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.update")),
) -> ContractPartyResponse:
    obj = await session.get(ContractParty, party_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Contract party not found")
    await _verify_contract_access(session, obj.contract_id, user_id)
    service = ContractsService(session)
    party = await service.update_party(party_id, data)
    return _party_to_response(party, await service.resolve_party_name(party))


@router.delete("/contracts/parties/{party_id}", status_code=204)
async def delete_contract_party(
    party_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.delete")),
) -> None:
    obj = await session.get(ContractParty, party_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Contract party not found")
    await _verify_contract_access(session, obj.contract_id, user_id)
    service = ContractsService(session)
    await service.delete_party(party_id)


# ── Securities (bonds / guarantees / insurance) ────────────────────────────


@router.get(
    "/contracts/{contract_id}/securities",
    response_model=list[ContractSecurityResponse],
)
async def list_contract_securities(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    status_filter: str | None = Query(default=None, alias="status"),
    security_type: str | None = Query(default=None),
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> list[ContractSecurityResponse]:
    await _verify_contract_access(session, contract_id, user_id)
    repo = ContractSecurityRepository(session)
    items = await repo.list_for_contract(
        contract_id,
        status=status_filter,
        security_type=security_type,
    )
    return [ContractSecurityResponse.model_validate(it) for it in items]


@router.get("/contracts/{contract_id}/security-coverage")
async def contract_security_coverage(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> dict:
    """Summary of bonds / guarantees / insurance held against a contract."""
    await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    return await service.security_coverage(contract_id)


@router.post(
    "/contracts/{contract_id}/securities",
    response_model=ContractSecurityResponse,
    status_code=201,
)
async def create_contract_security(
    contract_id: uuid.UUID,
    data: ContractSecurityCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.create")),
) -> ContractSecurityResponse:
    if data.contract_id != contract_id:
        raise HTTPException(status_code=400, detail="contract_id mismatch between URL and body")
    await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    obj = await service.create_security(data)
    return ContractSecurityResponse.model_validate(obj)


@router.get("/contracts/securities/{security_id}", response_model=ContractSecurityResponse)
async def get_contract_security(
    security_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> ContractSecurityResponse:
    obj = await session.get(ContractSecurity, security_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Contract security not found")
    await _verify_contract_access(session, obj.contract_id, user_id)
    return ContractSecurityResponse.model_validate(obj)


@router.patch("/contracts/securities/{security_id}", response_model=ContractSecurityResponse)
async def update_contract_security(
    security_id: uuid.UUID,
    data: ContractSecurityUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.update")),
) -> ContractSecurityResponse:
    obj = await session.get(ContractSecurity, security_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Contract security not found")
    await _verify_contract_access(session, obj.contract_id, user_id)
    service = ContractsService(session)
    updated = await service.update_security(security_id, data)
    return ContractSecurityResponse.model_validate(updated)


@router.delete("/contracts/securities/{security_id}", status_code=204)
async def delete_contract_security(
    security_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.delete")),
) -> None:
    obj = await session.get(ContractSecurity, security_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Contract security not found")
    await _verify_contract_access(session, obj.contract_id, user_id)
    service = ContractsService(session)
    await service.delete_security(security_id)


# ── Extension-of-time (EOT) claims ─────────────────────────────────────────


@router.get(
    "/contracts/{contract_id}/eot-claims",
    response_model=list[EOTClaimResponse],
)
async def list_eot_claims(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    status_filter: str | None = Query(default=None, alias="status"),
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> list[EOTClaimResponse]:
    await _verify_contract_access(session, contract_id, user_id)
    repo = EOTClaimRepository(session)
    items = await repo.list_for_contract(contract_id, status=status_filter)
    return [EOTClaimResponse.model_validate(it) for it in items]


@router.get("/contracts/{contract_id}/eot-summary")
async def contract_eot_summary(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> dict:
    """Aggregate EOT exposure: days claimed / granted and latest revised date."""
    await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    return await service.eot_summary(contract_id)


@router.post(
    "/contracts/{contract_id}/eot-claims",
    response_model=EOTClaimResponse,
    status_code=201,
)
async def create_eot_claim(
    contract_id: uuid.UUID,
    data: EOTClaimCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.create")),
) -> EOTClaimResponse:
    if data.contract_id != contract_id:
        raise HTTPException(status_code=400, detail="contract_id mismatch between URL and body")
    await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    obj = await service.create_eot_claim(data)
    return EOTClaimResponse.model_validate(obj)


@router.get("/contracts/eot-claims/{eot_id}", response_model=EOTClaimResponse)
async def get_eot_claim(
    eot_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> EOTClaimResponse:
    obj = await session.get(EOTClaim, eot_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="EOT claim not found")
    await _verify_contract_access(session, obj.contract_id, user_id)
    return EOTClaimResponse.model_validate(obj)


@router.patch("/contracts/eot-claims/{eot_id}", response_model=EOTClaimResponse)
async def update_eot_claim(
    eot_id: uuid.UUID,
    data: EOTClaimUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.update")),
) -> EOTClaimResponse:
    obj = await session.get(EOTClaim, eot_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="EOT claim not found")
    await _verify_contract_access(session, obj.contract_id, user_id)
    service = ContractsService(session)
    updated = await service.update_eot_claim(eot_id, data)
    return EOTClaimResponse.model_validate(updated)


@router.delete("/contracts/eot-claims/{eot_id}", status_code=204)
async def delete_eot_claim(
    eot_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.delete")),
) -> None:
    obj = await session.get(EOTClaim, eot_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="EOT claim not found")
    await _verify_contract_access(session, obj.contract_id, user_id)
    service = ContractsService(session)
    await service.delete_eot_claim(eot_id)


@router.post("/contracts/eot-claims/{eot_id}/submit", response_model=EOTClaimResponse)
async def submit_eot_claim(
    eot_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.submit_eot")),
) -> EOTClaimResponse:
    obj = await session.get(EOTClaim, eot_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="EOT claim not found")
    await _verify_contract_access(session, obj.contract_id, user_id)
    service = ContractsService(session)
    eot = await service.transition_eot_claim(eot_id, "submitted", user_id)
    return EOTClaimResponse.model_validate(eot)


@router.post("/contracts/eot-claims/{eot_id}/review", response_model=EOTClaimResponse)
async def review_eot_claim(
    eot_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.decide_eot")),
) -> EOTClaimResponse:
    """Move a submitted EOT claim into review."""
    obj = await session.get(EOTClaim, eot_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="EOT claim not found")
    await _verify_contract_access(session, obj.contract_id, user_id)
    service = ContractsService(session)
    eot = await service.transition_eot_claim(eot_id, "under_review", user_id)
    return EOTClaimResponse.model_validate(eot)


@router.post("/contracts/eot-claims/{eot_id}/withdraw", response_model=EOTClaimResponse)
async def withdraw_eot_claim(
    eot_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.submit_eot")),
) -> EOTClaimResponse:
    obj = await session.get(EOTClaim, eot_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="EOT claim not found")
    await _verify_contract_access(session, obj.contract_id, user_id)
    service = ContractsService(session)
    eot = await service.transition_eot_claim(eot_id, "withdrawn", user_id)
    return EOTClaimResponse.model_validate(eot)


@router.post("/contracts/eot-claims/{eot_id}/decide", response_model=EOTClaimResponse)
async def decide_eot_claim(
    eot_id: uuid.UUID,
    payload: EOTDecisionRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.decide_eot")),
) -> EOTClaimResponse:
    """Record a final EOT decision (granted / partially_granted / rejected).

    ``days_granted`` is clamped server-side to ``[0, days_claimed]`` so a
    decision can never award more time than was claimed.
    """
    obj = await session.get(EOTClaim, eot_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="EOT claim not found")
    await _verify_contract_access(session, obj.contract_id, user_id)
    service = ContractsService(session)
    eot = await service.decide_eot_claim(
        eot_id,
        payload.decision,
        days_granted=payload.days_granted,
        decision_date=payload.decision_date,
        revised_completion_date=payload.revised_completion_date,
        actor_id=user_id,
    )
    return EOTClaimResponse.model_validate(eot)


# ── Documents register ─────────────────────────────────────────────────────


@router.get(
    "/contracts/{contract_id}/documents",
    response_model=list[ContractDocumentResponse],
)
async def list_contract_documents(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    doc_role: str | None = Query(default=None),
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> list[ContractDocumentResponse]:
    await _verify_contract_access(session, contract_id, user_id)
    repo = ContractDocumentRepository(session)
    items = await repo.list_for_contract(contract_id, doc_role=doc_role)
    return [ContractDocumentResponse.model_validate(it) for it in items]


@router.post(
    "/contracts/{contract_id}/documents",
    response_model=ContractDocumentResponse,
    status_code=201,
)
async def create_contract_document(
    contract_id: uuid.UUID,
    data: ContractDocumentCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.create")),
) -> ContractDocumentResponse:
    if data.contract_id != contract_id:
        raise HTTPException(status_code=400, detail="contract_id mismatch between URL and body")
    await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    obj = await service.create_document(data)
    return ContractDocumentResponse.model_validate(obj)


@router.get("/contracts/documents/{document_id}", response_model=ContractDocumentResponse)
async def get_contract_document(
    document_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> ContractDocumentResponse:
    obj = await session.get(ContractDocument, document_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Contract document not found")
    await _verify_contract_access(session, obj.contract_id, user_id)
    return ContractDocumentResponse.model_validate(obj)


@router.patch("/contracts/documents/{document_id}", response_model=ContractDocumentResponse)
async def update_contract_document(
    document_id: uuid.UUID,
    data: ContractDocumentUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.update")),
) -> ContractDocumentResponse:
    obj = await session.get(ContractDocument, document_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Contract document not found")
    await _verify_contract_access(session, obj.contract_id, user_id)
    service = ContractsService(session)
    updated = await service.update_document(document_id, data)
    return ContractDocumentResponse.model_validate(updated)


@router.delete("/contracts/documents/{document_id}", status_code=204)
async def delete_contract_document(
    document_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.delete")),
) -> None:
    obj = await session.get(ContractDocument, document_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Contract document not found")
    await _verify_contract_access(session, obj.contract_id, user_id)
    service = ContractsService(session)
    await service.delete_document(document_id)


# ── Milestones / payment schedule ──────────────────────────────────────────


@router.get(
    "/contracts/{contract_id}/milestones",
    response_model=list[ContractMilestoneResponse],
)
async def list_contract_milestones(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> list[ContractMilestoneResponse]:
    await _verify_contract_access(session, contract_id, user_id)
    repo = ContractMilestoneRepository(session)
    items = await repo.list_for_contract(contract_id)
    return [ContractMilestoneResponse.model_validate(it) for it in items]


@router.get("/contracts/{contract_id}/milestone-schedule")
async def contract_milestone_schedule(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> dict:
    """Resolve each milestone's value and the total scheduled milestone value."""
    await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    return await service.milestone_schedule(contract_id)


@router.post(
    "/contracts/{contract_id}/milestones",
    response_model=ContractMilestoneResponse,
    status_code=201,
)
async def create_contract_milestone(
    contract_id: uuid.UUID,
    data: ContractMilestoneCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.create")),
) -> ContractMilestoneResponse:
    if data.contract_id != contract_id:
        raise HTTPException(status_code=400, detail="contract_id mismatch between URL and body")
    await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    obj = await service.create_milestone(data)
    return ContractMilestoneResponse.model_validate(obj)


@router.get("/contracts/milestones/{milestone_id}", response_model=ContractMilestoneResponse)
async def get_contract_milestone(
    milestone_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> ContractMilestoneResponse:
    obj = await session.get(ContractMilestone, milestone_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Contract milestone not found")
    await _verify_contract_access(session, obj.contract_id, user_id)
    return ContractMilestoneResponse.model_validate(obj)


@router.patch("/contracts/milestones/{milestone_id}", response_model=ContractMilestoneResponse)
async def update_contract_milestone(
    milestone_id: uuid.UUID,
    data: ContractMilestoneUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.update")),
) -> ContractMilestoneResponse:
    obj = await session.get(ContractMilestone, milestone_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Contract milestone not found")
    await _verify_contract_access(session, obj.contract_id, user_id)
    service = ContractsService(session)
    updated = await service.update_milestone(milestone_id, data)
    return ContractMilestoneResponse.model_validate(updated)


@router.delete("/contracts/milestones/{milestone_id}", status_code=204)
async def delete_contract_milestone(
    milestone_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.delete")),
) -> None:
    obj = await session.get(ContractMilestone, milestone_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Contract milestone not found")
    await _verify_contract_access(session, obj.contract_id, user_id)
    service = ContractsService(session)
    await service.delete_milestone(milestone_id)


# ── Completeness validation ────────────────────────────────────────────────


@router.get("/contracts/{contract_id}/completeness")
async def contract_completeness(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("contracts.read")),
) -> dict:
    """Run the contracts rule set (parties / security / EOT) over a contract.

    Returns the report status, score and the grouped error / warning lists so
    the UI can show a traffic-light completeness panel for the contract.
    """
    await _verify_contract_access(session, contract_id, user_id)
    service = ContractsService(session)
    return await service.validate_contract_completeness(contract_id)
