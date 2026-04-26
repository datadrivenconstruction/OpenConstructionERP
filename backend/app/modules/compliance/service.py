# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Service layer for the compliance DSL module.

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
                str(exc), details={"path": exc.path, **exc.details},
            ) from exc

    # -- compile + persist -------------------------------------------------

    async def compile_and_save(self, args: CompileArgs) -> ComplianceDSLRule:
        if len(args.definition_yaml.encode("utf-8")) > self.MAX_DEFINITION_BYTES:
            raise ComplianceValidationError(
                f"Definition exceeds {self.MAX_DEFINITION_BYTES} bytes.",
            )
        definition = self.parse_or_raise(args.definition_yaml)

        existing = await self.repo.get_by_rule_id(
            definition.rule_id, tenant_id=args.tenant_id,
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
        await self.repo.add(row)

        # Register with the engine so subsequent validation runs pick
        # the rule up. Failures are logged but don't abort the save —
        # the row is still on disk and the next startup will re-attempt
        # registration via :func:`register_active_rules`.
        if row.is_active:
            try:
                _register_compiled(definition)
            except Exception:  # pragma: no cover — defensive
                logger.exception(
                    "Failed to register compiled rule %s",
                    definition.rule_id,
                )

        return row

    # -- read / list -------------------------------------------------------

    async def get(
        self, rule_pk: uuid.UUID, *, tenant_id: str | None,
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
        # don't pick up a half-removed rule.
        _deregister_compiled(row.rule_id)
        await self.repo.delete(row)


# ── Registry helpers ───────────────────────────────────────────────────────


def _register_compiled(definition: RuleDefinition) -> ValidationRule:
    """Compile + register a definition, replacing any prior copy."""
    rule = compile_rule(definition)
    rule_sets = list(definition.rule_sets) if definition.rule_sets else None
    rule_registry.register(rule, rule_sets)
    return rule


def _deregister_compiled(rule_id: str) -> None:
    """Best-effort removal from the global registry.

    The registry doesn't expose a public ``remove`` so we touch the
    private dicts directly. This is safe because the registry is a
    plain in-memory cache; a future refactor can lift this into a
    public method without changing the call sites.
    """
    rules = getattr(rule_registry, "_rules", None)
    if isinstance(rules, dict):
        rules.pop(rule_id, None)
    sets = getattr(rule_registry, "_rule_sets", None)
    if isinstance(sets, dict):
        for name, ids in list(sets.items()):
            if rule_id in ids:
                sets[name] = [r for r in ids if r != rule_id]


async def register_active_rules(repo: ComplianceDSLRepository) -> int:
    """Load every active rule from the DB and register it with the engine.

    Called at app startup. Failures on individual rules are logged and
    skipped — one bad rule must not prevent the others from loading.
    """
    rows = await repo.list_all_active()
    registered = 0
    for row in rows:
        try:
            definition = parse_definition(row.definition_yaml)
            _register_compiled(definition)
            registered += 1
        except DSLError as exc:
            logger.warning(
                "Skipping invalid compliance DSL rule %s (%s): %s",
                row.rule_id,
                row.id,
                exc,
            )
        except Exception:  # pragma: no cover — defensive
            logger.exception(
                "Failed to compile compliance DSL rule %s", row.rule_id,
            )
    if registered:
        logger.info(
            "Registered %d compliance DSL rules from database", registered,
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
