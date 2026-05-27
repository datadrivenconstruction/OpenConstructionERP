# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Service layer for EAC v2 parameter aliases (RFC 35 §6 EAC-2.1).

Pure functions on top of :mod:`app.modules.eac.aliases.resolver` plus
the SQLAlchemy ORM models. The router is the only thing that touches
HTTP types.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.eac.aliases.schemas import (
    EacAliasSynonymCreate,
    EacAliasUsageRow,
    EacParameterAliasCreate,
    EacParameterAliasUpdate,
)
from app.modules.eac.models import (
    EacAliasSnapshot,
    EacAliasSynonym,
    EacParameterAlias,
    EacRule,
)

logger = logging.getLogger(__name__)


class AliasInUseError(Exception):
    """‌⁠‍Raised when trying to hard-delete an alias still referenced by rules.

    The exception carries the list of rules so the API layer can surface
    them and let the user resolve the conflict (rename, replace, etc.).
    """

    def __init__(self, alias_id: uuid.UUID, usages: list[EacAliasUsageRow]) -> None:
        super().__init__(
            f"Alias {alias_id} is referenced by {len(usages)} rule(s); "
            "remove or rewrite those rules before deleting it.",
        )
        self.alias_id = alias_id
        self.usages = usages


class AliasConflictError(Exception):
    """‌⁠‍Raised when an alias with the same ``(scope, scope_id, name)`` exists.

    The ``uq_eac_parameter_alias_scope_name`` unique constraint guards
    against duplicate canonical names within a scope. Without this typed
    error the raw ``IntegrityError`` would surface as an opaque 500; the
    API layer maps this to a clean 409 Conflict instead.
    """

    def __init__(self, scope: str, scope_id: uuid.UUID | None, name: str) -> None:
        super().__init__(
            f"An alias named {name!r} already exists in scope {scope!r} (scope_id={scope_id}).",
        )
        self.scope = scope
        self.scope_id = scope_id
        self.name = name


# ── Helpers ─────────────────────────────────────────────────────────────


def _build_synonym(
    payload: EacAliasSynonymCreate,
    *,
    alias_id: uuid.UUID | None = None,
) -> EacAliasSynonym:
    """‌⁠‍Translate a Pydantic synonym body into an ORM row."""
    return EacAliasSynonym(
        alias_id=alias_id,
        pattern=payload.pattern,
        kind=payload.kind,
        case_sensitive=payload.case_sensitive,
        priority=payload.priority,
        pset_filter=payload.pset_filter,
        source_filter=payload.source_filter,
        unit_multiplier=Decimal(str(payload.unit_multiplier)),
    )


# ── Create / update / delete ────────────────────────────────────────────


async def create_alias(
    session: AsyncSession,
    payload: EacParameterAliasCreate,
    *,
    tenant_id: uuid.UUID | None,
) -> EacParameterAlias:
    """Create an alias and its synonyms in one transaction-flushed step.

    Raises :class:`AliasConflictError` when an alias with the same
    ``(scope, scope_id, name)`` already exists *within the same tenant*
    — the ``uq_eac_parameter_alias_scope_name`` unique constraint
    would otherwise surface as an opaque 500.

    R7 audit (Wave 3): the dup-check is scoped to ``tenant_id`` so
    tenant A creating an alias named ``X`` is not blocked because
    tenant B already has one. (Pre-R7 the check was cross-tenant and
    produced false 409s.)
    """
    dup_stmt = select(EacParameterAlias.id).where(
        EacParameterAlias.scope == payload.scope,
        EacParameterAlias.scope_id == payload.scope_id,
        EacParameterAlias.name == payload.name,
    )
    if tenant_id is not None:
        dup_stmt = dup_stmt.where(EacParameterAlias.tenant_id == tenant_id)
    if (await session.execute(dup_stmt)).first() is not None:
        raise AliasConflictError(payload.scope, payload.scope_id, payload.name)

    alias = EacParameterAlias(
        scope=payload.scope,
        scope_id=payload.scope_id,
        name=payload.name,
        description=payload.description,
        value_type_hint=payload.value_type_hint,
        default_unit=payload.default_unit,
        version=1,
        is_built_in=False,
        tenant_id=tenant_id,
    )
    session.add(alias)
    try:
        await session.flush()
    except IntegrityError as exc:
        # Race-safe backstop: a concurrent insert may have slipped between
        # the pre-check and this flush. Roll back the half-added row so the
        # session is reusable, then surface the same typed conflict.
        await session.rollback()
        raise AliasConflictError(payload.scope, payload.scope_id, payload.name) from exc

    for syn_payload in payload.synonyms:
        syn = _build_synonym(syn_payload, alias_id=alias.id)
        session.add(syn)
    await session.flush()
    await session.refresh(alias)
    return alias


async def update_alias(
    session: AsyncSession,
    alias_id: uuid.UUID,
    payload: EacParameterAliasUpdate,
    *,
    tenant_id: uuid.UUID | None = None,
) -> EacParameterAlias:
    """Update an alias's metadata (and optionally replace its synonyms).

    R7 audit (Wave 3): when ``tenant_id`` is supplied, a cross-tenant
    ``alias_id`` raises :class:`LookupError` (router maps to 404) so
    the caller cannot mutate another tenant's row.
    """
    alias = await session.get(EacParameterAlias, alias_id)
    if alias is None:
        raise LookupError(f"Alias {alias_id} not found")
    if tenant_id is not None and alias.tenant_id != tenant_id:
        # Hide existence — same 404 surface as a true miss.
        raise LookupError(f"Alias {alias_id} not found")

    data = payload.model_dump(exclude_unset=True)
    new_synonyms = data.pop("synonyms", None)

    for field, value in data.items():
        setattr(alias, field, value)
    alias.version = (alias.version or 1) + 1

    if new_synonyms is not None:
        # Replace mode: delete existing children and re-add.
        # cascade='all, delete-orphan' on the relationship lets us just
        # clear the collection.
        alias.synonyms.clear()
        await session.flush()
        for syn_payload in new_synonyms:
            session.add(
                _build_synonym(
                    EacAliasSynonymCreate(**syn_payload),
                    alias_id=alias.id,
                )
            )
    await session.flush()
    await session.refresh(alias)
    return alias


async def delete_alias(
    session: AsyncSession,
    alias_id: uuid.UUID,
    *,
    tenant_id: uuid.UUID | None = None,
) -> None:
    """Hard-delete the alias, blocking when rules still reference it.

    R7 audit (Wave 3): cross-tenant ``alias_id`` raises
    :class:`LookupError` (router maps to 404).
    """
    alias = await session.get(EacParameterAlias, alias_id)
    if alias is None:
        raise LookupError(f"Alias {alias_id} not found")
    if tenant_id is not None and alias.tenant_id != tenant_id:
        raise LookupError(f"Alias {alias_id} not found")

    usages = await find_usages(session, alias_id, tenant_id=tenant_id)
    if usages:
        raise AliasInUseError(alias_id, usages)
    await session.delete(alias)
    await session.flush()


# ── Listing & search ────────────────────────────────────────────────────


async def list_aliases(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID | None = None,
    scope: str | None = None,
    scope_id: uuid.UUID | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[EacParameterAlias]:
    """List aliases for a scope, optionally narrowed by a free-text query.

    R7 audit (Wave 3): when ``tenant_id`` is supplied, the query is
    scoped to that tenant so a list call from tenant A never leaks
    tenant B's rows. Built-in (system) aliases (``tenant_id IS NULL``)
    remain visible to every tenant — they ship with the platform.

    The free-text query matches against the alias name OR any of its
    synonym patterns. We do the synonym filter in Python rather than
    write a portable JSON containment expression — the result set per
    org/project is bounded (RFC 35 §6 ships with 40 built-ins; user
    sets rarely exceed a few hundred).
    """
    from sqlalchemy import or_ as _or

    stmt = select(EacParameterAlias)
    if tenant_id is not None:
        stmt = stmt.where(
            _or(
                EacParameterAlias.tenant_id == tenant_id,
                EacParameterAlias.tenant_id.is_(None),
            )
        )
    if scope is not None:
        stmt = stmt.where(EacParameterAlias.scope == scope)
    if scope_id is not None:
        stmt = stmt.where(EacParameterAlias.scope_id == scope_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(EacParameterAlias.name.ilike(like))
    stmt = stmt.order_by(EacParameterAlias.name).limit(limit).offset(offset)
    result = await session.execute(stmt)
    aliases = list(result.scalars().unique().all())

    if q:
        like_lower = q.lower()
        # If the alias name didn't match, see if any synonym pattern does;
        # we still want to surface aliases whose synonyms contain the term.
        keep: list[EacParameterAlias] = []
        for alias in aliases:
            if like_lower in alias.name.lower():
                keep.append(alias)
                continue
            if any(like_lower in (s.pattern or "").lower() for s in (alias.synonyms or [])):
                keep.append(alias)
        # If the SQL filter already trimmed down by name, also include any
        # aliases whose name didn't match but whose synonyms did. We cannot
        # easily express that in portable SQL without a join + JSON path,
        # so we run a synonym lookup for the secondary candidates here.
        if not keep:
            extra_stmt = (
                select(EacParameterAlias)
                .join(EacAliasSynonym, EacAliasSynonym.alias_id == EacParameterAlias.id)
                .where(EacAliasSynonym.pattern.ilike(like))
            )
            if tenant_id is not None:
                extra_stmt = extra_stmt.where(
                    _or(
                        EacParameterAlias.tenant_id == tenant_id,
                        EacParameterAlias.tenant_id.is_(None),
                    )
                )
            if scope is not None:
                extra_stmt = extra_stmt.where(EacParameterAlias.scope == scope)
            if scope_id is not None:
                extra_stmt = extra_stmt.where(
                    EacParameterAlias.scope_id == scope_id,
                )
            extra_stmt = extra_stmt.limit(limit).offset(offset)
            extra_result = await session.execute(extra_stmt)
            keep = list(extra_result.scalars().unique().all())
        aliases = keep
    return aliases


# ── Usage discovery ─────────────────────────────────────────────────────


def _find_alias_id_refs(node: Any, alias_id_str: str, hits: list[None]) -> None:
    """Walk a definition_json tree and append on every alias_id match."""
    if isinstance(node, dict):
        kind = node.get("kind")
        if kind == "alias" and node.get("alias_id") == alias_id_str:
            hits.append(None)
        for value in node.values():
            _find_alias_id_refs(value, alias_id_str, hits)
    elif isinstance(node, list):
        for item in node:
            _find_alias_id_refs(item, alias_id_str, hits)


async def find_usages(
    session: AsyncSession,
    alias_id: uuid.UUID,
    *,
    tenant_id: uuid.UUID | None = None,
) -> list[EacAliasUsageRow]:
    """Find every active rule whose ``definition_json`` references this alias.

    R7 audit (Wave 3): the rule scan is scoped to ``tenant_id`` so an
    alias-in-use check never inspects another tenant's rule corpus.

    Implementation note: PostgreSQL has ``->>`` operators we could use,
    but to stay portable across SQLite-backed tests we walk the JSON in
    Python. The candidate set is bounded by tenant.
    """
    alias_id_str = str(alias_id)
    stmt = select(EacRule).where(EacRule.is_active.is_(True))
    if tenant_id is not None:
        stmt = stmt.where(EacRule.tenant_id == tenant_id)
    result = await session.execute(stmt)
    rules = list(result.scalars().unique().all())

    out: list[EacAliasUsageRow] = []
    for rule in rules:
        if not rule.definition_json:
            continue
        hits: list[None] = []
        _find_alias_id_refs(rule.definition_json, alias_id_str, hits)
        if hits:
            out.append(
                EacAliasUsageRow(
                    rule_id=rule.id,
                    rule_name=rule.name,
                    rule_output_mode=rule.output_mode,
                )
            )
    return out


# ── Snapshot ────────────────────────────────────────────────────────────


async def take_snapshot(
    session: AsyncSession,
    *,
    scope: str,
    scope_id: uuid.UUID | None,
    tenant_id: uuid.UUID | None = None,
) -> EacAliasSnapshot:
    """Capture every alias for the given scope into an immutable row.

    Used by :class:`EacRun` so a replay sees the exact alias set the
    original execution worked with — even if the user renames or
    deletes aliases later.

    R7 audit (Wave 3): when ``tenant_id`` is supplied, the snapshot
    only contains aliases visible to that tenant (own rows + built-ins).
    """
    aliases = await list_aliases(
        session,
        tenant_id=tenant_id,
        scope=scope,
        scope_id=scope_id,
        limit=10_000,
    )
    payload: dict[str, dict[str, Any]] = {}
    for alias in aliases:
        payload[alias.name] = {
            "id": str(alias.id),
            "value_type_hint": alias.value_type_hint,
            "default_unit": alias.default_unit,
            "synonyms": [
                {
                    "id": str(s.id),
                    "pattern": s.pattern,
                    "kind": s.kind,
                    "case_sensitive": s.case_sensitive,
                    "priority": s.priority,
                    "pset_filter": s.pset_filter,
                    "source_filter": s.source_filter,
                    "unit_multiplier": str(s.unit_multiplier),
                }
                for s in (alias.synonyms or [])
            ],
        }

    snapshot = EacAliasSnapshot(
        scope=scope,
        scope_id=scope_id,
        aliases_json=payload,
    )
    session.add(snapshot)
    await session.flush()
    return snapshot


__all__ = [
    "AliasConflictError",
    "AliasInUseError",
    "create_alias",
    "delete_alias",
    "find_usages",
    "list_aliases",
    "take_snapshot",
    "update_alias",
]


# Helper retained for the ``or_`` import in case future filters need it.
_OR = or_
