# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""FastAPI router for the compliance DSL module.

Endpoints
~~~~~~~~~

* ``POST   /dsl/validate-syntax`` — lint a definition before saving.
* ``POST   /dsl/compile``         — parse, persist, and register a rule.
* ``GET    /dsl/rules``           — list rules visible to the caller.
* ``GET    /dsl/rules/{rule_pk}`` — read a single rule.
* ``DELETE /dsl/rules/{rule_pk}`` — remove a rule (owner-only).

All endpoints require an authenticated caller; the DI overrides used
in tests inject a synthetic payload so the router is exercisable
without standing up the full auth stack.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.dependencies import CurrentUserPayload, SessionDep
from app.modules.compliance.manifest import manifest
from app.modules.compliance.repository import ComplianceDSLRepository
from app.modules.compliance.schemas import (
    DSLCompileRequest,
    DSLRuleListResponse,
    DSLRuleOut,
    DSLValidateRequest,
    DSLValidateResponse,
)
from app.modules.compliance.service import (
    CompileArgs,
    ComplianceDSLService,
    ComplianceError,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Compliance"])


# ── Helpers ────────────────────────────────────────────────────────────────


def _user_id_from_payload(payload: dict) -> uuid.UUID:
    sub = payload.get("sub") or payload.get("user_id")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing user identity in token.",
        )
    try:
        return uuid.UUID(str(sub))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user id in token.",
        ) from exc


def _tenant_id_from_payload(payload: dict) -> str | None:
    tenant = payload.get("tenant_id")
    if tenant:
        return str(tenant)
    sub = payload.get("sub") or payload.get("user_id")
    return str(sub) if sub else None


def _raise_compliance_http(exc: ComplianceError) -> None:
    raise HTTPException(
        status_code=exc.http_status,
        detail={
            "message": str(exc),
            "message_key": exc.message_key,
            "details": exc.details,
        },
    )


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.post(
    "/dsl/validate-syntax",
    response_model=DSLValidateResponse,
    status_code=status.HTTP_200_OK,
    summary="Lint a compliance DSL definition without saving",
)
async def validate_syntax(
    body: DSLValidateRequest,
    payload: CurrentUserPayload,  # noqa: ARG001 — auth-only side effect
) -> DSLValidateResponse:
    if (body.definition_yaml is None) == (body.definition is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Provide exactly one of 'definition_yaml' or "
                "'definition'."
            ),
        )

    source = body.definition_yaml if body.definition_yaml is not None else body.definition
    try:
        definition = ComplianceDSLService.parse_or_raise(source)  # type: ignore[arg-type]
    except ComplianceError as exc:
        return DSLValidateResponse(valid=False, error=str(exc))
    return DSLValidateResponse(
        valid=True,
        rule_id=definition.rule_id,
        severity=definition.severity.value,
        standard=definition.standard,
    )


@router.post(
    "/dsl/compile",
    response_model=DSLRuleOut,
    status_code=status.HTTP_201_CREATED,
    summary="Compile, persist and register a DSL rule",
)
async def compile_rule_endpoint(
    body: DSLCompileRequest,
    payload: CurrentUserPayload,
    session: SessionDep,
) -> DSLRuleOut:
    user_id = _user_id_from_payload(payload)
    tenant_id = _tenant_id_from_payload(payload)
    service = ComplianceDSLService(
        repo=ComplianceDSLRepository(session),
    )
    try:
        row = await service.compile_and_save(
            CompileArgs(
                definition_yaml=body.definition_yaml,
                owner_user_id=user_id,
                tenant_id=tenant_id,
                activate=body.activate,
            )
        )
    except ComplianceError as exc:
        _raise_compliance_http(exc)
        raise  # pragma: no cover — _raise always raises

    await session.commit()
    return DSLRuleOut.model_validate(row)


@router.get(
    "/dsl/rules",
    response_model=DSLRuleListResponse,
    summary="List compliance DSL rules visible to the caller",
)
async def list_rules(
    payload: CurrentUserPayload,
    session: SessionDep,
    active_only: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DSLRuleListResponse:
    tenant_id = _tenant_id_from_payload(payload)
    service = ComplianceDSLService(
        repo=ComplianceDSLRepository(session),
    )
    rows, total = await service.list_(
        tenant_id=tenant_id,
        active_only=active_only,
        limit=limit,
        offset=offset,
    )
    return DSLRuleListResponse(
        total=total,
        items=[DSLRuleOut.model_validate(r) for r in rows],
    )


@router.get(
    "/dsl/rules/{rule_pk}",
    response_model=DSLRuleOut,
    summary="Read a single compliance DSL rule",
)
async def get_rule(
    rule_pk: uuid.UUID,
    payload: CurrentUserPayload,
    session: SessionDep,
) -> DSLRuleOut:
    tenant_id = _tenant_id_from_payload(payload)
    service = ComplianceDSLService(
        repo=ComplianceDSLRepository(session),
    )
    try:
        row = await service.get(rule_pk, tenant_id=tenant_id)
    except ComplianceError as exc:
        _raise_compliance_http(exc)
        raise  # pragma: no cover

    return DSLRuleOut.model_validate(row)


@router.delete(
    "/dsl/rules/{rule_pk}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a compliance DSL rule (owner only)",
)
async def delete_rule(
    rule_pk: uuid.UUID,
    payload: CurrentUserPayload,
    session: SessionDep,
) -> None:
    user_id = _user_id_from_payload(payload)
    tenant_id = _tenant_id_from_payload(payload)
    service = ComplianceDSLService(
        repo=ComplianceDSLRepository(session),
    )
    try:
        await service.delete(
            rule_pk, tenant_id=tenant_id, owner_user_id=user_id,
        )
    except ComplianceError as exc:
        _raise_compliance_http(exc)
        raise  # pragma: no cover

    await session.commit()


# Re-exported so module-loader pickup is explicit.
__all__ = ["manifest", "router"]
