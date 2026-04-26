# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""FastAPI router for EAC v2 parameter aliases (RFC 35 §6 EAC-2.3).

Mounted under the parent EAC router at ``/api/v1/eac/aliases``.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import CurrentUserId, SessionDep
from app.modules.eac.aliases.bulk_resolver import resolve_bulk
from app.modules.eac.aliases.resolver import resolve_alias
from app.modules.eac.aliases.schemas import (
    EacAliasBulkResolveRequest,
    EacAliasExportRequest,
    EacAliasImportSummary,
    EacAliasResolveRequest,
    EacAliasResolveResponse,
    EacAliasSynonymCreate,
    EacAliasTestRequest,
    EacAliasTestResponse,
    EacAliasUsageResponse,
    EacParameterAliasCreate,
    EacParameterAliasRead,
    EacParameterAliasUpdate,
)
from app.modules.eac.aliases.service import (
    AliasInUseError,
    create_alias,
    delete_alias,
    find_usages,
    list_aliases,
    update_alias,
)
from app.modules.eac.models import (
    ALIAS_SCOPES,
    ALIAS_SOURCE_FILTERS,
    ALIAS_SYNONYM_KINDS,
    ALIAS_VALUE_TYPE_HINTS,
    EacParameterAlias,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["EAC v2 — Aliases"])


# ── Helpers ──────────────────────────────────────────────────────────────


def _check_scope(value: str | None) -> None:
    if value is None:
        return
    if value not in ALIAS_SCOPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"scope must be one of {ALIAS_SCOPES}, got '{value}'",
        )


def _check_kind(value: str | None) -> None:
    if value is None:
        return
    if value not in ALIAS_SYNONYM_KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"kind must be one of {ALIAS_SYNONYM_KINDS}, got '{value}'",
        )


def _check_source_filter(value: str | None) -> None:
    if value is None:
        return
    if value not in ALIAS_SOURCE_FILTERS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"source_filter must be one of {ALIAS_SOURCE_FILTERS}, "
                f"got '{value}'"
            ),
        )


def _check_vth(value: str | None) -> None:
    if value is None:
        return
    if value not in ALIAS_VALUE_TYPE_HINTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"value_type_hint must be one of {ALIAS_VALUE_TYPE_HINTS}, "
                f"got '{value}'"
            ),
        )


async def _resolve_tenant_id(
    session: AsyncSession, user_id: str
) -> uuid.UUID:
    """Resolve the current user's tenant.

    Mirrors the helper used by :mod:`app.modules.eac.router` so this
    file isn't coupled to its private implementation.
    """
    try:
        from app.modules.users.models import User

        user = await session.get(User, uuid.UUID(user_id))
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )
        tenant_attr = getattr(user, "tenant_id", None)
        if tenant_attr is not None:
            return uuid.UUID(str(tenant_attr))
        return user.id
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        return uuid.UUID(user_id)


# ── List ─────────────────────────────────────────────────────────────────


@router.get("/aliases", response_model=list[EacParameterAliasRead])
async def list_aliases_route(
    user_id: CurrentUserId,
    session: SessionDep,
    scope: str | None = Query(default=None),
    scope_id: uuid.UUID | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[EacParameterAliasRead]:
    """List aliases visible to the caller, optionally filtered by scope/text."""
    _check_scope(scope)
    _ = await _resolve_tenant_id(session, user_id)
    aliases = await list_aliases(
        session,
        scope=scope,
        scope_id=scope_id,
        q=q,
        limit=limit,
        offset=offset,
    )
    return [EacParameterAliasRead.model_validate(a) for a in aliases]


# ── Create ───────────────────────────────────────────────────────────────


@router.post(
    "/aliases",
    response_model=EacParameterAliasRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_alias_route(
    payload: EacParameterAliasCreate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> EacParameterAliasRead:
    """Create an alias along with its synonyms."""
    _check_scope(payload.scope)
    _check_vth(payload.value_type_hint)
    for syn in payload.synonyms:
        _check_kind(syn.kind)
        _check_source_filter(syn.source_filter)
    tenant_id = await _resolve_tenant_id(session, user_id)
    alias = await create_alias(session, payload, tenant_id=tenant_id)
    return EacParameterAliasRead.model_validate(alias)


# ── Read one ─────────────────────────────────────────────────────────────


@router.get("/aliases/{alias_id}", response_model=EacParameterAliasRead)
async def get_alias_route(
    alias_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> EacParameterAliasRead:
    """Fetch a single alias by id."""
    _ = await _resolve_tenant_id(session, user_id)
    alias = await session.get(EacParameterAlias, alias_id)
    if alias is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alias {alias_id} not found",
        )
    return EacParameterAliasRead.model_validate(alias)


# ── Update ───────────────────────────────────────────────────────────────


@router.put("/aliases/{alias_id}", response_model=EacParameterAliasRead)
async def update_alias_route(
    alias_id: uuid.UUID,
    payload: EacParameterAliasUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> EacParameterAliasRead:
    """Update an alias's metadata; pass ``synonyms`` to replace them."""
    if payload.value_type_hint is not None:
        _check_vth(payload.value_type_hint)
    if payload.synonyms is not None:
        for syn in payload.synonyms:
            _check_kind(syn.kind)
            _check_source_filter(syn.source_filter)
    _ = await _resolve_tenant_id(session, user_id)
    try:
        alias = await update_alias(session, alias_id, payload)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return EacParameterAliasRead.model_validate(alias)


# ── Delete ───────────────────────────────────────────────────────────────


@router.delete("/aliases/{alias_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alias_route(
    alias_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> None:
    """Hard-delete an alias. Blocks when rules still reference it."""
    _ = await _resolve_tenant_id(session, user_id)
    try:
        await delete_alias(session, alias_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except AliasInUseError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "alias_in_use",
                "message": str(exc),
                "usages": [u.model_dump() for u in exc.usages],
                "alternatives": [
                    "rename_alias",
                    "replace_alias_in_rules",
                    "deactivate_referencing_rules",
                ],
            },
        ) from exc


# ── Usages ───────────────────────────────────────────────────────────────


@router.get("/aliases/{alias_id}/usages", response_model=EacAliasUsageResponse)
async def get_alias_usages_route(
    alias_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> EacAliasUsageResponse:
    """Return every active rule that references this alias."""
    _ = await _resolve_tenant_id(session, user_id)
    alias = await session.get(EacParameterAlias, alias_id)
    if alias is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alias {alias_id} not found",
        )
    usages = await find_usages(session, alias_id)
    return EacAliasUsageResponse(
        usages=usages,
        can_delete=not usages,
    )


# ── Test endpoint (synthetic single-property element) ────────────────────


@router.post("/aliases/{alias_id}/test", response_model=EacAliasTestResponse)
async def test_alias_route(
    alias_id: uuid.UUID,
    payload: EacAliasTestRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> EacAliasTestResponse:
    """Probe an alias against a synthetic ``{property_name}`` element."""
    _check_source_filter(payload.source)
    _ = await _resolve_tenant_id(session, user_id)
    alias = await session.get(EacParameterAlias, alias_id)
    if alias is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alias {alias_id} not found",
        )

    if payload.pset_name:
        synthetic = {
            "properties": {
                payload.pset_name: {payload.property_name: "<probe>"},
            }
        }
    else:
        synthetic = {"properties": {payload.property_name: "<probe>"}}

    result = resolve_alias(alias, list(alias.synonyms or []), synthetic)
    return EacAliasTestResponse(
        matched=result.matched,
        matched_synonym_id=result.matched_synonym_id,
        pset_name=result.pset_name,
    )


# ── Bulk resolve ─────────────────────────────────────────────────────────


@router.post(
    "/aliases:resolve-bulk",
    response_model=list[EacAliasResolveResponse],
)
async def resolve_aliases_bulk_route(
    payload: EacAliasBulkResolveRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> list[EacAliasResolveResponse]:
    """Resolve multiple aliases against a single element in one round-trip."""
    _ = await _resolve_tenant_id(session, user_id)
    if not payload.alias_ids:
        return []

    stmt = select(EacParameterAlias).where(EacParameterAlias.id.in_(payload.alias_ids))
    result = await session.execute(stmt)
    aliases = list(result.scalars().unique().all())
    if not aliases:
        return []

    resolutions = resolve_bulk(aliases, payload.element)
    out: list[EacAliasResolveResponse] = []
    for alias in aliases:
        res = resolutions.get(alias.id)
        if res is None:
            continue
        out.append(
            EacAliasResolveResponse(
                alias_id=alias.id,
                alias_name=alias.name,
                matched=res.matched,
                matched_synonym_id=res.matched_synonym_id,
                raw_value=res.raw_value,
                value_after_unit_conversion=res.value_after_unit_conversion,
                pset_name=res.pset_name,
            )
        )
    return out


# ── Single resolve helper (companion to :resolve-bulk) ──────────────────


@router.post("/aliases:resolve", response_model=EacAliasResolveResponse)
async def resolve_alias_route(
    payload: EacAliasResolveRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> EacAliasResolveResponse:
    """Resolve one alias against ``payload.element``."""
    _ = await _resolve_tenant_id(session, user_id)
    alias = await session.get(EacParameterAlias, payload.alias_id)
    if alias is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alias {payload.alias_id} not found",
        )
    res = resolve_alias(alias, list(alias.synonyms or []), payload.element)
    return EacAliasResolveResponse(
        alias_id=alias.id,
        alias_name=alias.name,
        matched=res.matched,
        matched_synonym_id=res.matched_synonym_id,
        raw_value=res.raw_value,
        value_after_unit_conversion=res.value_after_unit_conversion,
        pset_name=res.pset_name,
    )


# ── Export ───────────────────────────────────────────────────────────────


@router.post("/aliases:export")
async def export_aliases_route(
    payload: EacAliasExportRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    format: str = Query(default="json", description="json | csv"),  # noqa: A002 — FastAPI param
) -> dict | str:
    """Export aliases (filtered) as JSON or CSV.

    Returns a dict for ``format=json`` and a CSV string for
    ``format=csv``. The router layer takes care of content-type via the
    declared response shape; FastAPI auto-converts.
    """
    if format not in ("json", "csv"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="format must be 'json' or 'csv'",
        )
    _check_scope(payload.scope)
    _ = await _resolve_tenant_id(session, user_id)
    aliases = await list_aliases(
        session,
        scope=payload.scope,
        scope_id=payload.scope_id,
        q=None,
        limit=10_000,
    )
    if not payload.include_built_in:
        aliases = [a for a in aliases if not a.is_built_in]

    if format == "json":
        return {
            "aliases": [
                EacParameterAliasRead.model_validate(a).model_dump(mode="json")
                for a in aliases
            ]
        }

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "alias_name",
            "value_type_hint",
            "default_unit",
            "synonym_pattern",
            "kind",
            "case_sensitive",
            "priority",
            "pset_filter",
            "source_filter",
            "unit_multiplier",
        ]
    )
    for alias in aliases:
        for syn in alias.synonyms or []:
            writer.writerow(
                [
                    alias.name,
                    alias.value_type_hint,
                    alias.default_unit or "",
                    syn.pattern,
                    syn.kind,
                    int(bool(syn.case_sensitive)),
                    syn.priority,
                    syn.pset_filter or "",
                    syn.source_filter,
                    str(syn.unit_multiplier),
                ]
            )
    return buf.getvalue()


# ── Import ───────────────────────────────────────────────────────────────


@router.post("/aliases:import", response_model=EacAliasImportSummary)
async def import_aliases_route(
    user_id: CurrentUserId,
    session: SessionDep,
    file: UploadFile = File(...),  # noqa: B008 — FastAPI dependency
    scope: str = Query(default="org"),
    scope_id: uuid.UUID | None = Query(default=None),
) -> EacAliasImportSummary:
    """Import aliases from a JSON or CSV file.

    Insert-or-update by ``(scope, scope_id, name)``: an existing alias
    keeps its id and gets its synonyms replaced, a missing one is
    created. Returns counts + per-line errors.
    """
    _check_scope(scope)
    tenant_id = await _resolve_tenant_id(session, user_id)
    raw = await file.read()

    summary = EacAliasImportSummary(inserted=0, updated=0, skipped=0, errors=[])
    name = (file.filename or "").lower()
    is_csv = name.endswith(".csv")

    items: list[dict] = []
    try:
        if is_csv:
            decoded = raw.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(decoded))
            grouped: dict[str, dict] = {}
            for row in reader:
                alias_name = row.get("alias_name") or row.get("name")
                if not alias_name:
                    summary.errors.append(f"Row without alias_name: {row}")
                    summary.skipped += 1
                    continue
                grouped.setdefault(
                    alias_name,
                    {
                        "name": alias_name,
                        "value_type_hint": row.get("value_type_hint") or "any",
                        "default_unit": row.get("default_unit") or None,
                        "synonyms": [],
                    },
                )
                grouped[alias_name]["synonyms"].append(
                    {
                        "pattern": row.get("synonym_pattern") or row.get("pattern") or "",
                        "kind": row.get("kind") or "exact",
                        "case_sensitive": (row.get("case_sensitive") or "0") in (
                            "1",
                            "true",
                            "True",
                        ),
                        "priority": int(row.get("priority") or 100),
                        "pset_filter": row.get("pset_filter") or None,
                        "source_filter": row.get("source_filter") or "any",
                        "unit_multiplier": row.get("unit_multiplier") or "1",
                    }
                )
            items = list(grouped.values())
        else:
            doc = json.loads(raw.decode("utf-8"))
            items = doc.get("aliases") if isinstance(doc, dict) else doc
            if not isinstance(items, list):
                items = []
    except Exception as exc:  # noqa: BLE001
        summary.errors.append(f"Parse error: {exc}")
        return summary

    for item in items:
        try:
            alias_name = item.get("name") or item.get("alias_name")
            if not alias_name:
                summary.errors.append("Missing name in entry")
                summary.skipped += 1
                continue

            stmt = select(EacParameterAlias).where(
                EacParameterAlias.scope == scope,
                EacParameterAlias.scope_id == scope_id,
                EacParameterAlias.name == alias_name,
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()

            synonyms = [EacAliasSynonymCreate(**s) for s in item.get("synonyms", [])]

            if existing is None:
                payload = EacParameterAliasCreate(
                    scope=scope,
                    scope_id=scope_id,
                    name=alias_name,
                    description=item.get("description"),
                    value_type_hint=item.get("value_type_hint") or "any",
                    default_unit=item.get("default_unit"),
                    synonyms=synonyms,
                )
                await create_alias(session, payload, tenant_id=tenant_id)
                summary.inserted += 1
            else:
                update_payload = EacParameterAliasUpdate(
                    description=item.get("description"),
                    value_type_hint=item.get("value_type_hint") or "any",
                    default_unit=item.get("default_unit"),
                    synonyms=synonyms,
                )
                await update_alias(session, existing.id, update_payload)
                summary.updated += 1
        except Exception as exc:  # noqa: BLE001
            summary.errors.append(f"Failed to import {item!r}: {exc}")
            summary.skipped += 1

    return summary


# ── Module exports ──────────────────────────────────────────────────────


# Marker re-exports so `_RouterDeps` & helpers are visible to E2E suites.
_PUBLIC_ENUMS = (
    ALIAS_SCOPES,
    ALIAS_SYNONYM_KINDS,
    ALIAS_SOURCE_FILTERS,
    ALIAS_VALUE_TYPE_HINTS,
)
_RouterDeps = Annotated[None, Depends(lambda: None)]
_PATTERN_HOOK = re.compile(r".+")  # placeholder kept for future regex import use
