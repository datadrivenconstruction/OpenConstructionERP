# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""EAC v2 CRUD API router.

Endpoints for EAC-1.1 + EAC-1.2:

* ``POST   /rules``               — create rule
* ``GET    /rules/{id}``          — fetch rule
* ``GET    /rules``               — list rules (filters)
* ``PUT    /rules/{id}``          — update rule (auto-bumps version)
* ``DELETE /rules/{id}``          — soft-delete (sets is_active=False)
* ``POST   /rules:validate``      — stub validator (real impl in EAC-1.3)
* ``POST   /rulesets``            — create ruleset
* ``GET    /rulesets/{id}``       — fetch ruleset
* ``GET    /rulesets``            — list rulesets
* ``PUT    /rulesets/{id}``       — update ruleset
* ``DELETE /rulesets/{id}``       — hard-delete (rules cascade by FK SET NULL)

The module loader auto-mounts this router at ``/api/v1/eac/``. The canonical
``/api/v2/eac/`` surface (RFC 35 L15) is wired up by the parent task in
``app/main.py`` outside this ticket's scope.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import CurrentUserId, SessionDep
from app.modules.eac.models import (
    GLOBAL_VARIABLE_VALUE_TYPES,
    OUTPUT_MODES,
    RULESET_KINDS,
    EacRule,
    EacRuleset,
    EacRuleVersion,
    EacRun,
    EacRunResultItem,
)
from app.modules.eac.schemas_api import (
    EacCompileRequest,
    EacCompileResponse,
    EacDryRunRequest,
    EacDryRunResponse,
    EacRuleCreate,
    EacRuleListFilters,
    EacRuleRead,
    EacRulesetCreate,
    EacRulesetRead,
    EacRulesetUpdate,
    EacRuleUpdate,
    EacRuleValidateRequest,
    EacRuleValidateResponse,
    EacRuleValidationError,
    EacRunAggregateResult,
    EacRunCancelResponse,
    EacRunDiffResponse,
    EacRunElementResult,
    EacRunIssueResult,
    EacRunRead,
    EacRunRerunRequest,
    EacRunResultItemRead,
    EacRunRulesetRequest,
    EacRunStatusResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["EAC v2"])

# Mount the EAC-2 aliases sub-router (RFC 35 §6).
from app.modules.eac.aliases.router import router as _aliases_router  # noqa: E402

router.include_router(_aliases_router)


# ── Tenant resolution ────────────────────────────────────────────────────


async def _resolve_tenant_id(
    session: AsyncSession, user_id: str
) -> uuid.UUID:
    """Resolve the tenant for the current user.

    W0.4 (RLS) hasn't shipped yet; until then, each user is treated as
    its own single-row tenant. This shim keeps tests deterministic and
    is replaced when the tenant table lands.
    """
    try:
        from app.modules.users.models import User

        user = await session.get(User, uuid.UUID(user_id))
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )
        # Many user models carry tenant_id as nullable. Fall back to
        # user.id if the project hasn't seeded tenants yet.
        tenant_attr = getattr(user, "tenant_id", None)
        if tenant_attr is not None:
            return uuid.UUID(str(tenant_attr))
        return user.id
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        # Fall back to deriving a tenant from the user id; never fail the
        # request because tenancy is not strictly enforced in EAC-1.1.
        return uuid.UUID(user_id)


# ── Validate helpers ─────────────────────────────────────────────────────


def _check_output_mode(value: str | None) -> None:
    if value is None:
        return
    if value not in OUTPUT_MODES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"output_mode must be one of {OUTPUT_MODES}, got '{value}'",
        )


def _check_ruleset_kind(value: str | None) -> None:
    if value is None:
        return
    if value not in RULESET_KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"kind must be one of {RULESET_KINDS}, got '{value}'",
        )


# ── Rules: create ────────────────────────────────────────────────────────


@router.post(
    "/rules",
    response_model=EacRuleRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_rule(
    payload: EacRuleCreate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> EacRuleRead:
    """Create a new EAC rule.

    Saves a row in ``oe_eac_rule`` and a corresponding ``oe_eac_rule_version``
    history entry with ``version_number=1``.
    """
    _check_output_mode(payload.output_mode)
    tenant_id = await _resolve_tenant_id(session, user_id)

    rule = EacRule(
        ruleset_id=payload.ruleset_id,
        name=payload.name,
        description=payload.description,
        output_mode=payload.output_mode,
        definition_json=payload.definition_json or {},
        formula=payload.formula,
        result_unit=payload.result_unit,
        tags=list(payload.tags or []),
        version=1,
        is_active=True,
        tenant_id=tenant_id,
        project_id=payload.project_id,
        created_by_user_id=uuid.UUID(user_id),
        updated_by_user_id=uuid.UUID(user_id),
    )
    session.add(rule)
    await session.flush()

    version_row = EacRuleVersion(
        rule_id=rule.id,
        version_number=1,
        definition_json=rule.definition_json,
        formula=rule.formula,
        changed_by_user_id=uuid.UUID(user_id),
        change_reason="initial",
        tenant_id=tenant_id,
    )
    session.add(version_row)
    await session.flush()

    return EacRuleRead.model_validate(rule)


# ── Rules: get ──────────────────────────────────────────────────────────


@router.get("/rules/{rule_id}", response_model=EacRuleRead)
async def get_rule(
    rule_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> EacRuleRead:
    """Fetch a single rule by ID."""
    tenant_id = await _resolve_tenant_id(session, user_id)
    rule = await session.get(EacRule, rule_id)
    if rule is None or rule.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Rule {rule_id} not found",
        )
    return EacRuleRead.model_validate(rule)


# ── Rules: list ─────────────────────────────────────────────────────────


@router.get("/rules", response_model=list[EacRuleRead])
async def list_rules(
    user_id: CurrentUserId,
    session: SessionDep,
    ruleset_id: uuid.UUID | None = Query(default=None),
    project_id: uuid.UUID | None = Query(default=None),
    output_mode: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    tag: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[EacRuleRead]:
    """List rules visible to the current tenant, with optional filters."""
    _check_output_mode(output_mode)
    tenant_id = await _resolve_tenant_id(session, user_id)

    filters = EacRuleListFilters(
        ruleset_id=ruleset_id,
        project_id=project_id,
        output_mode=output_mode,
        is_active=is_active,
        tag=tag,
        search=search,
        limit=limit,
        offset=offset,
    )

    stmt = select(EacRule).where(EacRule.tenant_id == tenant_id)
    if filters.ruleset_id is not None:
        stmt = stmt.where(EacRule.ruleset_id == filters.ruleset_id)
    if filters.project_id is not None:
        stmt = stmt.where(EacRule.project_id == filters.project_id)
    if filters.output_mode is not None:
        stmt = stmt.where(EacRule.output_mode == filters.output_mode)
    if filters.is_active is not None:
        stmt = stmt.where(EacRule.is_active.is_(filters.is_active))
    if filters.search:
        like = f"%{filters.search}%"
        stmt = stmt.where(
            or_(
                EacRule.name.ilike(like),
                EacRule.description.ilike(like),
            )
        )
    stmt = stmt.order_by(EacRule.created_at.desc()).limit(filters.limit).offset(filters.offset)

    result = await session.execute(stmt)
    rules = list(result.scalars().all())

    if filters.tag:
        # Tags live in a JSON column — filter in Python rather than write a
        # dialect-specific JSON containment expression that breaks SQLite.
        rules = [r for r in rules if filters.tag in (r.tags or [])]

    return [EacRuleRead.model_validate(r) for r in rules]


# ── Rules: update ───────────────────────────────────────────────────────


@router.put("/rules/{rule_id}", response_model=EacRuleRead)
async def update_rule(
    rule_id: uuid.UUID,
    payload: EacRuleUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> EacRuleRead:
    """Update a rule, recording a new version row in the history table."""
    _check_output_mode(payload.output_mode)
    tenant_id = await _resolve_tenant_id(session, user_id)
    rule = await session.get(EacRule, rule_id)
    if rule is None or rule.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Rule {rule_id} not found",
        )

    data = payload.model_dump(exclude_unset=True)
    change_reason = data.pop("change_reason", None)

    definition_changed = "definition_json" in data and data["definition_json"] != rule.definition_json
    formula_changed = "formula" in data and data["formula"] != rule.formula

    for field, value in data.items():
        setattr(rule, field, value)
    rule.updated_by_user_id = uuid.UUID(user_id)

    if definition_changed or formula_changed:
        rule.version = (rule.version or 1) + 1
        version_row = EacRuleVersion(
            rule_id=rule.id,
            version_number=rule.version,
            definition_json=rule.definition_json,
            formula=rule.formula,
            changed_by_user_id=uuid.UUID(user_id),
            change_reason=change_reason,
            tenant_id=tenant_id,
        )
        session.add(version_row)

    await session.flush()
    return EacRuleRead.model_validate(rule)


# ── Rules: delete (soft) ────────────────────────────────────────────────


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> None:
    """Soft-delete a rule by flipping ``is_active`` to ``False``."""
    tenant_id = await _resolve_tenant_id(session, user_id)
    rule = await session.get(EacRule, rule_id)
    if rule is None or rule.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Rule {rule_id} not found",
        )
    rule.is_active = False
    rule.updated_by_user_id = uuid.UUID(user_id)
    await session.flush()


# ── Rules: validate (stub) ──────────────────────────────────────────────


@router.post(
    "/rules:validate",
    response_model=EacRuleValidateResponse,
)
async def validate_rule(
    payload: EacRuleValidateRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> EacRuleValidateResponse:
    """Validate a rule definition (schema + semantics, EAC-1.3).

    Pipeline:

    1. Pydantic shape check — catches malformed payloads before any
       DB work.
    2. Semantic validator — alias / global-var existence, formula
       syntax, ReDoS reject, ``between`` ordering, local-var cycle
       detection (FR-1.10).
    """
    errors: list[EacRuleValidationError] = []

    # 1. Schema-level shape check.
    from pydantic import ValidationError

    from app.modules.eac.engine.validator import validate_rule as _semantic_validate
    from app.modules.eac.schemas import EacRuleDefinition

    try:
        parsed_def = EacRuleDefinition.model_validate(payload.definition_json)
    except ValidationError as exc:
        for err in exc.errors():
            errors.append(
                EacRuleValidationError(
                    code="schema." + str(err.get("type", "invalid")),
                    path=".".join(str(p) for p in err.get("loc", ())),
                    message=str(err.get("msg", "Invalid")),
                    message_i18n_key=None,
                )
            )
        # Shape failures short-circuit semantic checks: the validator
        # operates on a well-formed Pydantic model.
        return EacRuleValidateResponse(valid=False, errors=errors)

    # 2. Semantic validator.
    try:
        tenant_id = await _resolve_tenant_id(session, user_id)
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 — soft fallback when tenant can't resolve
        tenant_id = None

    try:
        result = await _semantic_validate(
            parsed_def,
            session=session,
            tenant_id=tenant_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Semantic validator raised unexpectedly")
        errors.append(
            EacRuleValidationError(
                code="validator.internal_error",
                path="$",
                message=f"Validator error: {exc}",
                message_i18n_key=None,
            )
        )
        return EacRuleValidateResponse(valid=False, errors=errors)

    for issue in result.issues:
        errors.append(
            EacRuleValidationError(
                code=issue.code,
                path=issue.path,
                message=issue.message_i18n_key,
                message_i18n_key=issue.message_i18n_key,
            )
        )

    return EacRuleValidateResponse(valid=result.valid, errors=errors)


# ── Rulesets ────────────────────────────────────────────────────────────


@router.post(
    "/rulesets",
    response_model=EacRulesetRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_ruleset(
    payload: EacRulesetCreate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> EacRulesetRead:
    """Create a new ruleset."""
    _check_ruleset_kind(payload.kind)
    tenant_id = await _resolve_tenant_id(session, user_id)

    ruleset = EacRuleset(
        name=payload.name,
        description=payload.description,
        kind=payload.kind,
        classifier_id=payload.classifier_id,
        parent_ruleset_id=payload.parent_ruleset_id,
        tenant_id=tenant_id,
        project_id=payload.project_id,
        is_template=payload.is_template,
        is_public_in_marketplace=payload.is_public_in_marketplace,
        tags=list(payload.tags or []),
    )
    session.add(ruleset)
    await session.flush()
    return EacRulesetRead.model_validate(ruleset)


@router.get("/rulesets/{ruleset_id}", response_model=EacRulesetRead)
async def get_ruleset(
    ruleset_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> EacRulesetRead:
    """Fetch a single ruleset by ID."""
    tenant_id = await _resolve_tenant_id(session, user_id)
    ruleset = await session.get(EacRuleset, ruleset_id)
    if ruleset is None or ruleset.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ruleset {ruleset_id} not found",
        )
    return EacRulesetRead.model_validate(ruleset)


@router.get("/rulesets", response_model=list[EacRulesetRead])
async def list_rulesets(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID | None = Query(default=None),
    kind: str | None = Query(default=None),
    is_template: bool | None = Query(default=None),
    is_public_in_marketplace: bool | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[EacRulesetRead]:
    """List rulesets visible to the current tenant."""
    _check_ruleset_kind(kind)
    tenant_id = await _resolve_tenant_id(session, user_id)

    stmt = select(EacRuleset).where(EacRuleset.tenant_id == tenant_id)
    if project_id is not None:
        stmt = stmt.where(EacRuleset.project_id == project_id)
    if kind is not None:
        stmt = stmt.where(EacRuleset.kind == kind)
    if is_template is not None:
        stmt = stmt.where(EacRuleset.is_template.is_(is_template))
    if is_public_in_marketplace is not None:
        stmt = stmt.where(EacRuleset.is_public_in_marketplace.is_(is_public_in_marketplace))
    stmt = stmt.order_by(EacRuleset.created_at.desc()).limit(limit).offset(offset)

    result = await session.execute(stmt)
    rulesets = list(result.scalars().all())
    return [EacRulesetRead.model_validate(r) for r in rulesets]


@router.put("/rulesets/{ruleset_id}", response_model=EacRulesetRead)
async def update_ruleset(
    ruleset_id: uuid.UUID,
    payload: EacRulesetUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> EacRulesetRead:
    """Update a ruleset."""
    _check_ruleset_kind(payload.kind)
    tenant_id = await _resolve_tenant_id(session, user_id)
    ruleset = await session.get(EacRuleset, ruleset_id)
    if ruleset is None or ruleset.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ruleset {ruleset_id} not found",
        )

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(ruleset, field, value)
    await session.flush()
    return EacRulesetRead.model_validate(ruleset)


@router.delete(
    "/rulesets/{ruleset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_ruleset(
    ruleset_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> None:
    """Hard-delete a ruleset.

    Child rules' ``ruleset_id`` is set to NULL (FK ``ON DELETE SET NULL``).
    """
    tenant_id = await _resolve_tenant_id(session, user_id)
    ruleset = await session.get(EacRuleset, ruleset_id)
    if ruleset is None or ruleset.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ruleset {ruleset_id} not found",
        )
    await session.delete(ruleset)
    await session.flush()


# ── Runs (EAC-1.4 / RFC 35 §1.7) ────────────────────────────────────────


@router.post(
    "/rules:dry-run",
    response_model=EacDryRunResponse,
)
async def dry_run_rule_endpoint(
    payload: EacDryRunRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> EacDryRunResponse:
    """Run a draft rule definition against ad-hoc elements without persisting.

    Used by the rule editor's "Test" panel: the user supplies the rule
    body they're editing plus a few canonical element rows; we return
    the executor's verdict so they can see green/red ticks before
    saving.
    """
    # Reuse the validator to short-circuit malformed payloads with
    # a 422 instead of a 500.
    from app.modules.eac.engine.executor import (
        ExecutionError,
        UnsupportedOutputModeError,
    )
    from app.modules.eac.engine.runner import dry_run_rule

    try:
        tenant_id = await _resolve_tenant_id(session, user_id)
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        tenant_id = None

    try:
        result = await dry_run_rule(
            payload.definition_json,
            payload.elements,
            session=session,
            tenant_id=tenant_id,
        )
    except UnsupportedOutputModeError as exc:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=str(exc),
        ) from exc
    except ExecutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return EacDryRunResponse(
        output_mode=result.output_mode,
        elements_evaluated=result.elements_evaluated,
        elements_matched=result.elements_matched,
        elements_passed=result.elements_passed,
        boolean_results=[
            EacRunElementResult(
                element_id=r.element_id,
                passed=r.passed,
                attribute_snapshot=dict(r.attribute_snapshot),
                error=r.error,
            )
            for r in result.boolean_results
        ],
        issue_results=[
            EacRunIssueResult(
                element_id=i.element_id,
                title=i.title,
                description=i.description,
                topic_type=i.topic_type,
                priority=i.priority,
                stage=i.stage,
                labels=list(i.labels),
                attribute_snapshot=dict(i.attribute_snapshot),
            )
            for i in result.issue_results
        ],
        aggregate_result=(
            EacRunAggregateResult(
                value=result.aggregate_result.value,
                result_unit=result.aggregate_result.result_unit,
                elements_evaluated=result.aggregate_result.elements_evaluated,
            )
            if result.aggregate_result is not None
            else None
        ),
        errors=list(result.errors),
    )


@router.post(
    "/rulesets/{ruleset_id}:run",
    response_model=EacRunRead,
    status_code=status.HTTP_201_CREATED,
)
async def run_ruleset_endpoint(
    ruleset_id: uuid.UUID,
    payload: EacRunRulesetRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> EacRunRead:
    """Execute every active rule in a ruleset and persist an EacRun.

    The caller may either supply ``elements`` inline (small models,
    tests) or a ``model_id`` — in the latter case the runner loads
    BIMElement rows and converts them to canonical dicts via
    :func:`bim_element_to_canonical`.
    """
    from app.modules.eac.engine.executor import ExecutionError
    from app.modules.eac.engine.runner import (
        bim_element_to_canonical,
        run_ruleset,
    )

    tenant_id = await _resolve_tenant_id(session, user_id)
    ruleset = await session.get(EacRuleset, ruleset_id)
    if ruleset is None or ruleset.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ruleset {ruleset_id} not found",
        )

    elements: list[dict[str, Any]]
    if payload.elements is not None:
        elements = payload.elements
    elif payload.model_id is not None:
        from app.modules.bim_hub.models import BIMElement

        stmt = select(BIMElement).where(BIMElement.model_id == payload.model_id)
        rows = (await session.scalars(stmt)).all()
        elements = [bim_element_to_canonical(r) for r in rows]
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Either elements or model_id must be supplied",
        )

    try:
        run = await run_ruleset(
            session=session,
            ruleset_id=ruleset_id,
            tenant_id=tenant_id,
            elements=elements,
            model_version_id=payload.model_version_id,
            triggered_by=payload.triggered_by,
        )
    except ExecutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return EacRunRead.model_validate(run)


@router.get("/runs/{run_id}", response_model=EacRunRead)
async def get_run(
    run_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> EacRunRead:
    """Fetch a single run record."""
    tenant_id = await _resolve_tenant_id(session, user_id)
    run = await session.get(EacRun, run_id)
    if run is None or run.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run {run_id} not found",
        )
    return EacRunRead.model_validate(run)


@router.get("/runs", response_model=list[EacRunRead])
async def list_runs(
    user_id: CurrentUserId,
    session: SessionDep,
    ruleset_id: uuid.UUID | None = Query(default=None),
    run_status: str | None = Query(default=None, alias="status"),
    triggered_by: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[EacRunRead]:
    """List runs filtered by ruleset / status / trigger."""
    tenant_id = await _resolve_tenant_id(session, user_id)
    stmt = (
        select(EacRun)
        .where(EacRun.tenant_id == tenant_id)
        .order_by(EacRun.started_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if ruleset_id is not None:
        stmt = stmt.where(EacRun.ruleset_id == ruleset_id)
    if run_status is not None:
        stmt = stmt.where(EacRun.status == run_status)
    if triggered_by is not None:
        stmt = stmt.where(EacRun.triggered_by == triggered_by)
    rows = (await session.scalars(stmt)).all()
    return [EacRunRead.model_validate(r) for r in rows]


@router.get(
    "/runs/{run_id}/results",
    response_model=list[EacRunResultItemRead],
)
async def list_run_results(
    run_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    rule_id: uuid.UUID | None = Query(default=None),
    only_failures: bool | None = Query(default=None),
    has_error: bool | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> list[EacRunResultItemRead]:
    """Paginate the per-element result rows for a run.

    ``only_failures`` filters to rows where ``pass_=False`` — used by
    the run-detail view's "show what failed" tab.
    """
    tenant_id = await _resolve_tenant_id(session, user_id)
    run = await session.get(EacRun, run_id)
    if run is None or run.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run {run_id} not found",
        )

    stmt = (
        select(EacRunResultItem)
        .where(EacRunResultItem.run_id == run_id)
        .order_by(EacRunResultItem.id.asc())
        .limit(limit)
        .offset(offset)
    )
    if rule_id is not None:
        stmt = stmt.where(EacRunResultItem.rule_id == rule_id)
    if only_failures is True:
        stmt = stmt.where(EacRunResultItem.pass_.is_(False))
    if has_error is True:
        stmt = stmt.where(EacRunResultItem.error.is_not(None))
    elif has_error is False:
        stmt = stmt.where(EacRunResultItem.error.is_(None))

    rows = (await session.scalars(stmt)).all()
    return [EacRunResultItemRead.model_validate(r) for r in rows]


# ── Engine API completeness (RFC 35 §1.7 / task #221) ───────────────────


@router.post(
    "/rules:compile",
    response_model=EacCompileResponse,
)
async def compile_rule_endpoint(
    payload: EacCompileRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> EacCompileResponse:
    """Validate + compile a rule body to an executable plan.

    Returns a structured plan (SQL skeleton, parameters, projection)
    plus the validator's verdict so the editor can show issues alongside
    the compiled plan. A malformed payload surfaces as 422; a
    well-formed but semantically wrong payload returns 200 with
    ``valid=false`` so the UI can render the partial plan.
    """
    from pydantic import ValidationError

    from app.modules.eac.engine.api import compile_plan, describe_plan

    try:
        tenant_id = await _resolve_tenant_id(session, user_id)
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        tenant_id = None

    try:
        compiled = await compile_plan(
            payload.definition_json,
            session=session,
            tenant_id=tenant_id,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid rule definition: {exc.errors()[:3]}",
        ) from exc

    described = describe_plan(compiled.plan)
    return EacCompileResponse(
        valid=compiled.valid,
        duckdb_sql=described["duckdb_sql"],
        projection_columns=described["projection_columns"],
        parameters=described["parameters"],
        post_python_step=described["post_python_step"],
        estimated_cost=described["estimated_cost"],
        issues=list(compiled.issues),
    )


@router.get(
    "/runs/{run_id}/status",
    response_model=EacRunStatusResponse,
)
async def get_run_status_endpoint(
    run_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> EacRunStatusResponse:
    """Return progress + state for ``run_id``.

    Designed for the run-detail header: progress percentage, error
    summary, and status are all the UI needs to drive the live polling
    loop. 404 when the run does not exist or belongs to another tenant.
    """
    from app.modules.eac.service import get_run_status

    tenant_id = await _resolve_tenant_id(session, user_id)
    snapshot = await get_run_status(session, run_id, tenant_id=tenant_id)
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run {run_id} not found",
        )
    return EacRunStatusResponse(
        run_id=snapshot.run_id,
        status=snapshot.status,
        progress=snapshot.progress,
        elements_evaluated=snapshot.elements_evaluated,
        elements_matched=snapshot.elements_matched,
        error_count=snapshot.error_count,
        started_at=snapshot.started_at,
        finished_at=snapshot.finished_at,
        errors=list(snapshot.errors),
    )


@router.post(
    "/runs/{run_id}:cancel",
    response_model=EacRunCancelResponse,
)
async def cancel_run_endpoint(
    run_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> EacRunCancelResponse:
    """Request graceful cancellation of ``run_id``.

    Returns 200 with ``cancelled=true`` when the request was accepted
    (run is pending/running, or already cancelled — idempotent).
    Returns 404 when the run does not exist for the current tenant.
    Returns 409 when the run is in a terminal non-cancelled state
    (success/failed) — cancel is meaningless there.
    """
    from app.modules.eac.service import cancel_run

    tenant_id = await _resolve_tenant_id(session, user_id)
    pre = await session.get(EacRun, run_id)
    if pre is None or pre.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run {run_id} not found",
        )
    if pre.status in {"success", "failed"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run {run_id} is already in terminal state '{pre.status}'",
        )

    accepted = await cancel_run(
        session,
        run_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    refreshed = await session.get(EacRun, run_id)
    return EacRunCancelResponse(
        run_id=run_id,
        cancelled=accepted,
        status=refreshed.status if refreshed is not None else "unknown",
    )


@router.post(
    "/runs/{run_id}:rerun",
    response_model=EacRunRead,
    status_code=status.HTTP_201_CREATED,
)
async def rerun_run_endpoint(
    run_id: uuid.UUID,
    payload: EacRunRerunRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> EacRunRead:
    """Replay a prior run and persist a fresh ``EacRun`` row."""
    from app.modules.eac.engine.executor import ExecutionError
    from app.modules.eac.service import rerun

    tenant_id = await _resolve_tenant_id(session, user_id)
    try:
        new_run = await rerun(
            session,
            run_id,
            tenant_id=tenant_id,
            elements=payload.elements,
            triggered_by=payload.triggered_by,
            user_id=user_id,
        )
    except ExecutionError as exc:
        # Source run not found / tenant mismatch — surface as 404 so the
        # caller doesn't conflate it with a malformed payload (422).
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return EacRunRead.model_validate(new_run)


@router.get(
    "/runs/{run_id_a}:diff/{run_id_b}",
    response_model=EacRunDiffResponse,
)
async def diff_runs_endpoint(
    run_id_a: uuid.UUID,
    run_id_b: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> EacRunDiffResponse:
    """Compare two runs of the same ruleset.

    422 when the runs belong to different rulesets (diff is not
    meaningful) or when one of them is missing.
    """
    from app.modules.eac.engine.executor import ExecutionError
    from app.modules.eac.service import diff_runs

    tenant_id = await _resolve_tenant_id(session, user_id)
    try:
        result = await diff_runs(
            session, run_id_a, run_id_b, tenant_id=tenant_id
        )
    except ExecutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return EacRunDiffResponse(
        run_id_a=result.run_id_a,
        run_id_b=result.run_id_b,
        elements_only_in_a=list(result.elements_only_in_a),
        elements_only_in_b=list(result.elements_only_in_b),
        flipped_pass_to_fail=list(result.flipped_pass_to_fail),
        flipped_fail_to_pass=list(result.flipped_fail_to_pass),
        unchanged_count=result.unchanged_count,
    )


# ── Module exports ──────────────────────────────────────────────────────

# The ``OUTPUT_MODES``, ``RULESET_KINDS``, ``GLOBAL_VARIABLE_VALUE_TYPES``
# imports keep tooling/IDEs aware these constants belong to the public
# router contract even though they aren't referenced as runtime values
# above (used by E2E suites and OpenAPI examples).
_PUBLIC_ENUMS = (OUTPUT_MODES, RULESET_KINDS, GLOBAL_VARIABLE_VALUE_TYPES)
_RouterDeps = Annotated[Any, Depends(lambda: None)]  # placeholder for future deps
