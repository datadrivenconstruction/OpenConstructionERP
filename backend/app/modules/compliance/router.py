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
from typing import Annotated, Any

import yaml
from fastapi import APIRouter, HTTPException, Query, status

from app.core.validation.dsl import (
    list_supported_patterns,
    parse_nl_to_dsl,
)
from app.dependencies import CurrentUserPayload, SessionDep
from app.modules.compliance.manifest import manifest
from app.modules.compliance.repository import ComplianceDSLRepository
from app.modules.compliance.schemas import (
    DSLCompileRequest,
    DSLFromNlRequest,
    DSLFromNlResponse,
    DSLNlPatternOut,
    DSLNlPatternsResponse,
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


def _user_id_from_payload(payload: dict[str, Any]) -> uuid.UUID:
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


def _tenant_id_from_payload(payload: dict[str, Any]) -> str | None:
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


# ── T13: Natural-language DSL builder ──────────────────────────────────────


async def _build_ai_caller(
    payload: dict[str, Any],  # noqa: ARG001 — placeholder for future per-tenant routing
    session: Any,  # noqa: ANN401 — typed as AsyncSession by SessionDep, kept loose to avoid an import cycle
) -> Any:
    """Build a bound ``(system, prompt) -> str`` callable, or ``None``.

    The returned coroutine wraps :func:`app.modules.ai.ai_client.call_ai`
    so the DSL module never imports HTTP / settings models. If no API
    key is configured for the caller — or any error happens during
    resolution — we return ``None`` so :func:`parse_nl_to_dsl` skips the
    AI path silently. **Never raises**.
    """
    try:
        # Lazy imports keep the compliance module independent of AI.
        from app.modules.ai.ai_client import (
            call_ai,
            resolve_provider_and_key,
        )
        from app.modules.ai.repository import AISettingsRepository
    except Exception:  # pragma: no cover — defensive
        return None

    user_id_raw = payload.get("sub") or payload.get("user_id")
    if not user_id_raw:
        return None
    try:
        uid = uuid.UUID(str(user_id_raw))
    except ValueError:
        return None

    try:
        settings_obj = await AISettingsRepository(session).get_by_user_id(uid)
        provider, api_key = resolve_provider_and_key(settings_obj)
    except Exception:
        return None

    async def _caller(system: str, prompt: str) -> str:
        text, _tokens = await call_ai(
            provider=provider,
            api_key=api_key,
            system=system,
            prompt=prompt,
            max_tokens=1024,
        )
        return text

    return _caller


@router.get(
    "/dsl/nl-patterns",
    response_model=DSLNlPatternsResponse,
    summary="List supported NL → DSL patterns (for the builder hints panel)",
)
async def list_nl_patterns(
    payload: CurrentUserPayload,  # noqa: ARG001 — auth-only side effect
) -> DSLNlPatternsResponse:
    items = [DSLNlPatternOut.model_validate(p) for p in list_supported_patterns()]
    return DSLNlPatternsResponse(items=items)


@router.post(
    "/dsl/from-nl",
    response_model=DSLFromNlResponse,
    status_code=status.HTTP_200_OK,
    summary="Convert plain-English / DE / RU text into a DSL definition",
)
async def from_nl(
    body: DSLFromNlRequest,
    payload: CurrentUserPayload,
    session: SessionDep,
) -> DSLFromNlResponse:
    ai_caller = None
    if body.use_ai:
        ai_caller = await _build_ai_caller(payload, session)

    result = await parse_nl_to_dsl(
        body.text,
        lang=body.lang,
        use_ai=body.use_ai,
        ai_caller=ai_caller,
    )

    yaml_str: str | None = None
    if result.dsl_definition:
        try:
            yaml_str = yaml.safe_dump(
                result.dsl_definition,
                sort_keys=False,
                allow_unicode=True,
                default_flow_style=False,
            )
        except yaml.YAMLError as exc:  # pragma: no cover — defensive
            logger.warning("Failed to serialise NL builder result: %s", exc)
            yaml_str = None

    return DSLFromNlResponse(
        dsl_definition=result.dsl_definition,
        dsl_yaml=yaml_str,
        confidence=result.confidence,
        used_method=result.used_method,
        matched_pattern=result.matched_pattern,
        errors=list(result.errors),
        suggestions=list(result.suggestions),
    )


# Re-exported so module-loader pickup is explicit.
__all__ = ["manifest", "router"]
