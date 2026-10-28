# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Service layer for the compliance DSL module.

Owns:

* Parsing + lint of incoming definitions (delegates to
  :mod:`app.core.validation.dsl`).
* Persisting rule rows.
* Registering compiled rules with the global rule registry so the
  validation engine can dispatch them alongside the hand-coded
  built-ins.
* Removing previously-registered rules when the row is deactivated or
  deleted.

Errors are typed and carry a stable ``message_key`` so the router can
i18n them cleanly.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.core.validation.dsl import (
    DSLError,
    RuleDefinition,
    compile_rule,
    parse_definition,
)
from app.core.validation.engine import ValidationRule, rule_registry
from app.modules.compliance.models import ComplianceDSLRule
from app.modules.compliance.repository import ComplianceDSLRepository

logger = logging.getLogger(__name__)


# ── Errors ─────────────────────────────────────────────────────────────────


class ComplianceError(Exception):
    """Base class for compliance-module service errors."""

    http_status: int = 500
    message_key: str = "compliance.dsl.error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class ComplianceValidationError(ComplianceError):
    http_status = 422
    message_key = "compliance.dsl.validation_failed"


class ComplianceNotFoundError(ComplianceError):
    http_status = 404
    message_key = "compliance.dsl.not_found"


class ComplianceConflictError(ComplianceError):
    http_status = 409
    message_key = "compliance.dsl.duplicate_rule_id"


class ComplianceAccessDeniedError(ComplianceError):
    http_status = 403
    message_key = "compliance.dsl.access_denied"


# ── DTO ────────────────────────────────────────────────────────────────────


@dataclass
class CompileArgs:
    definition_yaml: str
    owner_user_id: uuid.UUID
    tenant_id: str | None = None
    activate: bool = True


# ── Service ────────────────────────────────────────────────────────────────


class ComplianceDSLService:
    """High-level operations on compliance DSL rules."""

    MAX_DEFINITION_BYTES = 64_000

    def __init__(self, repo: ComplianceDSLRepository) -> None:
        self.repo = repo

    # -- syntax validation (no side effects) -------------------------------

    @staticmethod
    def parse_or_raise(definition: str | dict[str, Any]) -> RuleDefinition:
        try:
            return parse_definition(definition)
        except DSLError as exc:
            raise ComplianceValidationError(
                str(exc),
                details={"path": exc.path, **exc.details},
            ) from exc

    # -- compile + persist -------------------------------------------------

    async def compile_and_save(self, args: CompileArgs) -> ComplianceDSLRule:
        if len(args.definition_yaml.encode("utf-8")) > self.MAX_DEFINITION_BYTES:
            raise ComplianceValidationError(
                f"Definition exceeds {self.MAX_DEFINITION_BYTES} bytes.",
            )
        definition = self.parse_or_raise(args.definition_yaml)

        # Pre-flight lookup gives a clean 409 in the common case. We ALSO
        # catch IntegrityError on the insert below, because the check and
        # the insert are not atomic: two concurrent requests can both pass
        # this check and both attempt to INSERT, with one tripping the
        # ``uq_oe_compliance_dsl_rule_tenant_rule_id`` unique constraint.
        # The second guard closes that race window so the loser gets a 409
        # instead of an opaque 500 from an uncaught IntegrityError.
        existing = await self.repo.get_by_rule_id(
            definition.rule_id,
            tenant_id=args.tenant_id,
        )
        if existing is not None:
            raise ComplianceConflictError(
                f"A rule with id '{definition.rule_id}' already exists.",
                details={"rule_id": definition.rule_id},
            )

        row = ComplianceDSLRule(
            id=uuid.uuid4(),
            tenant_id=args.tenant_id,
            rule_id=definition.rule_id,
            name=definition.name,
            severity=definition.severity.value,
            standard=definition.standard,
            description=definition.description or None,
            definition_yaml=args.definition_yaml,
            owner_user_id=args.owner_user_id,
            is_active=bool(args.activate),
        )
        try:
            await self.repo.add(row)
            # Commit before touching the in-memory registry. repo.add only
            # flushes; the request-level commit would otherwise land AFTER the
            # registration below, so a rolled-back save would leave the engine
            # running a rule that was never persisted (active until the next
            # restart). Committing here makes registration strictly post-commit.
            await self.repo.session.commit()
        except IntegrityError as exc:
            logger.info(
                "Race on compliance DSL rule_id %s (treated as duplicate)",
                definition.rule_id,
            )
            raise ComplianceConflictError(
                f"A rule with id '{definition.rule_id}' already exists.",
                details={"rule_id": definition.rule_id},
            ) from exc

        # Register with the engine so subsequent validation runs pick the rule
        # up. The row is committed above, so a registration failure here is
        # logged and safely re-attempted at the next startup via
        # :func:`register_active_rules` - it never leaves an unpersisted rule live.
        if row.is_active:
            try:
                _register_compiled(definition, args.tenant_id)
            except Exception:  # pragma: no cover - defensive
                logger.exception(
                    "Failed to register compiled rule %s",
                    definition.rule_id,
                )

        return row

    # -- read / list -------------------------------------------------------

    async def get(
        self,
        rule_pk: uuid.UUID,
        *,
        tenant_id: str | None,
    ) -> ComplianceDSLRule:
        row = await self.repo.get_by_pk(rule_pk, tenant_id=tenant_id)
        if row is None:
            raise ComplianceNotFoundError(
                f"Compliance DSL rule {rule_pk} not found.",
            )
        return row

    async def list_(
        self,
        *,
        tenant_id: str | None,
        active_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[ComplianceDSLRule], int]:
        return await self.repo.list_for_tenant(
            tenant_id=tenant_id,
            active_only=active_only,
            limit=limit,
            offset=offset,
        )

    # -- delete ------------------------------------------------------------

    async def delete(
        self,
        rule_pk: uuid.UUID,
        *,
        tenant_id: str | None,
        owner_user_id: uuid.UUID,
    ) -> None:
        row = await self.repo.get_by_pk(rule_pk, tenant_id=tenant_id)
        if row is None:
            raise ComplianceNotFoundError(
                f"Compliance DSL rule {rule_pk} not found.",
            )
        if row.owner_user_id != owner_user_id:
            raise ComplianceAccessDeniedError(
                "Only the rule owner can delete this rule.",
            )
        # Deregister before deleting so concurrent validation calls
        # don't pick up a half-removed rule. Key on the row's own tenant so
        # we evict the tenant-scoped registry entry, not a bare/global one.
        _deregister_compiled(row.tenant_id, row.rule_id)
        await self.repo.delete(row)


# ── Registry helpers ───────────────────────────────────────────────────────
#
# SECURITY (cross-tenant isolation): the validation ``rule_registry`` is a
# single process-global singleton with no tenant dimension - one ``_rules``
# dict (rule_id -> rule) and one ``_rule_sets`` dict (set_name -> [rule_ids])
# shared by every tenant. User-authored compliance DSL rules are persisted
# per tenant (``oe_compliance_dsl_rule.tenant_id``) but, if registered with
# their bare ids/sets, they would become globally resolvable: tenant B running
# ``/validation/run`` with tenant A's set name would execute tenant A's rule
# against tenant B's data, and a tenant could register ``rule_id``/``standard``
# matching a built-in (e.g. ``din276.cost_group_required`` / ``din276``) and
# overwrite that built-in's body - or inject into the built-in ``din276`` /
# ``boq_quality`` set - for everyone.
#
# Fix: namespace every compliance DSL rule by its tenant before it touches the
# registry. The ``t:{tenant_id}:`` prefix is applied UNCONDITIONALLY to both
# the rule id and every set name, so a tenant's rules always land in their own
# ``t:{id}:*`` id/set space regardless of what strings they put in
# ``standard`` / ``rule_sets`` (those fields are not colon-restricted by the
# parser, only ``rule_id`` is). Built-ins register with un-prefixed ids and
# ``sets=None`` (so their global names ``boq_quality`` / ``din276`` / ``gaeb``
# / ... resolve only to built-ins), so they are never reachable or overwritten
# by a tenant rule. This mirrors the IDS importer
# (:mod:`app.modules.validation.router`), which namespaces both the set
# (``{rule_set}:{project_id}``) and the rule id (``{project_id}:{rule_id}``).


def _ns(tenant_id: str | None) -> str:
    """Per-tenant registry namespace prefix (system rules share one bucket)."""
    return f"t:{tenant_id}" if tenant_id else "t:__system__"


def _scoped_rule_id(tenant_id: str | None, rule_id: str) -> str:
    """Tenant-scoped registry key for a compiled rule id."""
    return f"{_ns(tenant_id)}:{rule_id}"


def _scoped_sets(
    tenant_id: str | None,
    rule_sets: list[str] | None,
    standard: str,
) -> list[str]:
    """Tenant-scoped rule-set names this rule registers into.

    Mirrors the registry's own default (set = ``[standard]`` when the
    definition lists no explicit sets) and then prefixes every name with the
    tenant namespace so it can never collide with a built-in / another
    tenant's set.
    """
    base = list(rule_sets) if rule_sets else [standard]
    ns = _ns(tenant_id)
    return [f"{ns}:{s}" for s in base]


def _register_compiled(
    definition: RuleDefinition,
    tenant_id: str | None,
) -> ValidationRule:
    """Compile + register a definition under the tenant's namespace.

    Mutating ``rule.rule_id`` on the instance is safe: :func:`compile_rule`
    returns a fresh ``ValidationRule`` subclass instance per call and the
    engine reads ``rule.rule_id`` off the instance at register and run time
    (the instance attribute shadows the class attribute). This is exactly
    what the IDS importer does.
    """
    rule = compile_rule(definition)
    rule.rule_id = _scoped_rule_id(tenant_id, rule.rule_id)
    rule_registry.register(
        rule,
        _scoped_sets(
            tenant_id,
            list(definition.rule_sets) or None,
            definition.standard,
        ),
    )
    return rule


def _deregister_compiled(tenant_id: str | None, rule_id: str) -> None:
    """Best-effort removal of a tenant's rule from the global registry.

    Keyed on the tenant-scoped id so one tenant's delete can never evict
    a built-in or another tenant's identically-named rule. The registry
    doesn't expose a public ``remove`` so we touch the private dicts
    directly; this is safe because the registry is a plain in-memory cache.
    """
    scoped = _scoped_rule_id(tenant_id, rule_id)
    rules = getattr(rule_registry, "_rules", None)
    if isinstance(rules, dict):
        rules.pop(scoped, None)
    sets = getattr(rule_registry, "_rule_sets", None)
    if isinstance(sets, dict):
        for name, ids in list(sets.items()):
            if scoped in ids:
                sets[name] = [r for r in ids if r != scoped]


async def register_active_rules(repo: ComplianceDSLRepository) -> int:
    """Load every active rule from the DB and register it with the engine.

    Called at app startup. Failures on individual rules are logged and
    skipped - one bad rule must not prevent the others from loading.
    """
    rows = await repo.list_all_active()
    registered = 0
    for row in rows:
        try:
            definition = parse_definition(row.definition_yaml)
            _register_compiled(definition, row.tenant_id)
            registered += 1
        except DSLError as exc:
            logger.warning(
                "Skipping invalid compliance DSL rule %s (%s): %s",
                row.rule_id,
                row.id,
                exc,
            )
        except Exception:  # pragma: no cover - defensive
            logger.exception(
                "Failed to compile compliance DSL rule %s",
                row.rule_id,
            )
    if registered:
        logger.info(
            "Registered %d compliance DSL rules from database",
            registered,
        )
    return registered


__all__ = [
    "CompileArgs",
    "ComplianceAccessDeniedError",
    "ComplianceConflictError",
    "ComplianceDSLService",
    "ComplianceError",
    "ComplianceNotFoundError",
    "ComplianceValidationError",
    "register_active_rules",
]
