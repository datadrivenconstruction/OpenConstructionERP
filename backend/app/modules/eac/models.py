# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""EAC v2 ORM models.

Tables (per RFC 35 §5):

* ``oe_eac_ruleset``           — collection of rules forming a logical bundle
* ``oe_eac_rule``              — declarative rule with ``definition_json`` body
* ``oe_eac_run``               — execution record for a ruleset against a model
* ``oe_eac_run_result_item``   — per-element row produced by a run
* ``oe_eac_global_variable``   — org/project-scoped named values
* ``oe_eac_rule_version``      — append-only history of rule definitions

The schema follows the codebase's portable conventions:

* UUID primary keys via :class:`app.database.GUID` (PostgreSQL UUID where
  available, otherwise ``String(36)``).
* JSON columns via ``sqlalchemy.JSON`` so SQLite (test) and PostgreSQL
  (prod) speak the same dialect.
* "Array" columns use ``JSON`` storing a list — the ``ARRAY(String)``
  PostgreSQL native type is not portable to SQLite.
* Tenant scoping (``tenant_id``) is enforced at the application/RLS layer
  introduced in W0.4; models simply expose the column with an index.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base

# ── Enum value constants ─────────────────────────────────────────────────
#
# We persist enums as plain strings so the schema is portable across
# PostgreSQL and SQLite without ALTER TYPE migrations. The validator and
# Pydantic schemas enforce the closed set; the database is intentionally
# permissive to make rolling enum extensions cheap.

OUTPUT_MODES: tuple[str, ...] = ("aggregate", "boolean", "clash", "issue")
RULESET_KINDS: tuple[str, ...] = (
    "boq",
    "validation",
    "clash_matrix",
    "schedule_link",
    "mixed",
)
RUN_STATUSES: tuple[str, ...] = (
    "pending",
    "running",
    "success",
    "failed",
    "cancelled",
    "partial",
)
RUN_TRIGGERS: tuple[str, ...] = ("manual", "scheduled", "webhook", "auto_on_upload")
GLOBAL_VARIABLE_SCOPES: tuple[str, ...] = ("org", "project")
GLOBAL_VARIABLE_VALUE_TYPES: tuple[str, ...] = ("number", "string", "boolean", "date")

# EAC-2 alias enums (RFC 35 §6).
ALIAS_SCOPES: tuple[str, ...] = ("org", "project")
ALIAS_VALUE_TYPE_HINTS: tuple[str, ...] = (
    "number",
    "string",
    "boolean",
    "date",
    "any",
)
ALIAS_SYNONYM_KINDS: tuple[str, ...] = ("exact", "regex")
ALIAS_SOURCE_FILTERS: tuple[str, ...] = (
    "any",
    "instance",
    "type",
    "pset",
    "external_classification",
)


# ── Ruleset ──────────────────────────────────────────────────────────────


class EacRuleset(Base):
    """Logical bundle of rules.

    A ruleset groups rules sharing context: a BoQ extraction pack, a
    validation suite, a clash matrix, etc. Rulesets nest via
    ``parent_ruleset_id`` so users can compose a "DACH residential"
    ruleset out of "DIN 276 base" + "Berlin overrides".
    """

    __tablename__ = "oe_eac_ruleset"
    __table_args__ = (
        Index("ix_eac_ruleset_tenant_kind", "tenant_id", "kind"),
        Index("ix_eac_ruleset_tenant_project", "tenant_id", "project_id"),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="mixed",
        doc="One of: boq, validation, clash_matrix, schedule_link, mixed",
    )
    classifier_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    parent_ruleset_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_eac_ruleset.id", ondelete="SET NULL"),
        nullable=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    is_template: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    is_public_in_marketplace: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    tags: Mapped[list[str]] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
        doc="List[str] of free-form labels for filtering/discovery",
    )

    # Relationships
    rules: Mapped[list["EacRule"]] = relationship(
        back_populates="ruleset",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    runs: Mapped[list["EacRun"]] = relationship(
        back_populates="ruleset",
        cascade="all, delete-orphan",
        lazy="noload",
    )
    parent: Mapped["EacRuleset | None"] = relationship(
        remote_side="EacRuleset.id",
        lazy="noload",
    )

    def __repr__(self) -> str:
        return f"<EacRuleset {self.name} kind={self.kind}>"


# ── Rule ─────────────────────────────────────────────────────────────────


class EacRule(Base):
    """Declarative rule. Body lives in ``definition_json``.

    The Python and TypeScript layers never branch on rule shape — they
    parse ``definition_json`` against the ``EacRuleDefinition`` JSON
    Schema. This lets us version the schema and ship marketplace rule
    packs without code changes (RFC 35 L12).
    """

    __tablename__ = "oe_eac_rule"
    __table_args__ = (
        Index("ix_eac_rule_tenant_active", "tenant_id", "is_active"),
        Index("ix_eac_rule_ruleset_active", "ruleset_id", "is_active"),
    )

    ruleset_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_eac_ruleset.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="boolean",
        doc="One of: aggregate, boolean, clash, issue",
    )
    definition_json: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
        doc="Full EacRuleDefinition body (validated against JSON Schema)",
    )
    formula: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Optional formula evaluated by simpleeval (aggregate mode)",
    )
    result_unit: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        doc="Unit of the aggregate result, e.g. 'm2', 'm3', 'kg'",
    )
    tags: Mapped[list[str]] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    # Relationships
    ruleset: Mapped[EacRuleset | None] = relationship(back_populates="rules")
    versions: Mapped[list["EacRuleVersion"]] = relationship(
        back_populates="rule",
        cascade="all, delete-orphan",
        lazy="noload",
        order_by="EacRuleVersion.version_number",
    )

    def __repr__(self) -> str:
        return f"<EacRule {self.name} mode={self.output_mode} v{self.version}>"


# ── Run ──────────────────────────────────────────────────────────────────


class EacRun(Base):
    """Execution record for a ruleset against a model version.

    A run captures the inputs (ruleset + model version), outcome
    (status + summary), and per-element results (via
    :class:`EacRunResultItem`). Result rows that exceed a threshold
    are spooled to Parquet — the schema stays unchanged.
    """

    __tablename__ = "oe_eac_run"
    __table_args__ = (
        Index("ix_eac_run_tenant_status", "tenant_id", "status"),
        Index("ix_eac_run_ruleset_started", "ruleset_id", "started_at"),
    )

    ruleset_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_eac_ruleset.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default="pending",
        doc="One of: pending, running, success, failed, cancelled, partial",
    )
    summary_json: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=True,
    )
    elements_evaluated: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    elements_matched: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    error_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    triggered_by: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="manual",
        server_default="manual",
        doc="One of: manual, scheduled, webhook, auto_on_upload",
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)

    # Wave 1 / v2.6.0 — Parquet spool path for runs that overflow
    # HOT_RESULT_ITEM_CAP. NULL means no spill happened (or the run is
    # still pending). The path is interpreted by app.core.storage —
    # local filesystem or S3 depending on backend configuration.
    spool_path: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        doc="Storage key for spilled Parquet result data; NULL when fully in DB",
    )

    # Wave 1 / v2.6.0 — Idempotency key for POST /rulesets/{id}:run.
    # Either supplied by the client via Idempotency-Key header, or
    # computed from sha256(ruleset_id + ruleset.updated_at + sorted
    # element stable_ids + elements content hash). Re-posting with the
    # same key returns the existing run instead of starting a new one.
    idempotency_key: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        index=True,
        doc="sha256-derived dedup key; unique per (tenant, ruleset)",
    )

    # Relationships
    ruleset: Mapped[EacRuleset] = relationship(back_populates="runs")
    result_items: Mapped[list["EacRunResultItem"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        lazy="noload",
    )

    def __repr__(self) -> str:
        return f"<EacRun {self.id} status={self.status} matched={self.elements_matched}>"


# ── Run result item ──────────────────────────────────────────────────────


class EacRunResultItem(Base):
    """Per-element result row produced by a run.

    Hot rows (≤ 100k per run) live in PostgreSQL; cold rows spool to
    ``data/eac/runs/{run_id}/results.parquet`` (handled by the
    executor in EAC-1.4, transparent to this model).
    """

    __tablename__ = "oe_eac_run_result_item"
    __table_args__ = (
        Index("ix_eac_run_result_run_rule", "run_id", "rule_id"),
        Index("ix_eac_run_result_tenant", "tenant_id"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_eac_run.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_eac_rule.id", ondelete="CASCADE"),
        nullable=False,
    )
    element_id: Mapped[str] = mapped_column(String(128), nullable=False)
    result_value: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=True,
        doc="Output payload — shape depends on output_mode",
    )
    pass_: Mapped[bool | None] = mapped_column(
        "pass",
        Boolean,
        nullable=True,
        doc="Boolean outcome (None for aggregate/clash modes)",
    )
    attribute_snapshot: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=True,
        doc="Snapshot of attributes used by the rule (for explainability)",
    )
    error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Per-element error message (FR-1.11 partial errors)",
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)

    # Relationships
    run: Mapped[EacRun] = relationship(back_populates="result_items")

    def __repr__(self) -> str:
        return f"<EacRunResultItem run={self.run_id} rule={self.rule_id} elem={self.element_id}>"


# ── Global variable ──────────────────────────────────────────────────────


class EacGlobalVariable(Base):
    """Named constant scoped to an organization or project.

    Examples:

    * ``MIN_WALL_THICKNESS_MM = 100`` (number, project scope)
    * ``DEFAULT_REGION = "Berlin"`` (string, org scope)
    * ``USE_METRIC_UNITS = true`` (boolean, org scope)

    Variables are referenced inside ``definition_json`` and resolved
    at evaluation time. Locked variables cannot be edited via the UI
    (``is_locked=True``) — useful for compliance-fixed values.
    """

    __tablename__ = "oe_eac_global_variable"
    __table_args__ = (
        UniqueConstraint(
            "scope",
            "scope_id",
            "name",
            name="uq_eac_global_variable_scope_name",
        ),
        Index("ix_eac_global_variable_tenant", "tenant_id"),
    )

    scope: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        doc="One of: org, project",
    )
    scope_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    value_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        doc="One of: number, string, boolean, date",
    )
    value_json: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
        doc="Wrapped value; e.g. {\"value\": 100} or {\"value\": \"Berlin\"}",
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_locked: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)

    def __repr__(self) -> str:
        return f"<EacGlobalVariable {self.scope}:{self.name} type={self.value_type}>"


# ── Rule version ─────────────────────────────────────────────────────────


class EacRuleVersion(Base):
    """Append-only history row for an :class:`EacRule`.

    Every edit to a rule produces a new ``EacRuleVersion`` with the
    incremented ``version_number``. This satisfies the audit-trail
    requirement and lets users revert to a prior body.
    """

    __tablename__ = "oe_eac_rule_version"
    __table_args__ = (
        UniqueConstraint(
            "rule_id",
            "version_number",
            name="uq_eac_rule_version_rule_number",
        ),
        Index("ix_eac_rule_version_tenant", "tenant_id"),
    )

    rule_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_eac_rule.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    definition_json: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    formula: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)

    # Relationships
    rule: Mapped[EacRule] = relationship(back_populates="versions")

    def __repr__(self) -> str:
        return f"<EacRuleVersion rule={self.rule_id} v={self.version_number}>"


# ── Parameter alias (EAC-2.1) ───────────────────────────────────────────


class EacParameterAlias(Base):
    """Canonical parameter name + a list of synonyms (RFC 35 §6).

    Aliases insulate rule definitions from the chaotic property naming
    landscape across CAD/BIM exports: a single canonical ``_Length`` can
    match ``Length``, ``length_mm`` (with unit conversion), ``Longueur``,
    ``Длина``, etc., depending on which synonyms the user enabled.

    Built-in aliases ship with ``is_built_in=True`` and ``scope='org'``
    + ``scope_id IS NULL`` so they're visible to every tenant. User
    aliases are scoped to org or project.
    """

    __tablename__ = "oe_eac_parameter_aliases"
    __table_args__ = (
        UniqueConstraint(
            "scope",
            "scope_id",
            "name",
            name="uq_eac_parameter_alias_scope_name",
        ),
        Index("ix_eac_parameter_alias_tenant", "tenant_id"),
        Index(
            "ix_eac_parameter_alias_scope",
            "scope",
            "scope_id",
        ),
    )

    scope: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        doc="One of: org, project",
    )
    scope_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        doc="Org or project UUID. NULL for global built-in aliases.",
    )
    name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        doc="Canonical name, e.g. '_Length'",
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_type_hint: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="any",
        server_default="any",
        doc="One of: number, string, boolean, date, any",
    )
    default_unit: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        doc="Default unit symbol — e.g. 'm', 'm2', 'kg'.",
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    is_built_in: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
        doc="Seeded by Alembic data migration; cannot be deleted via the API.",
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        index=True,
        doc="Tenant for tenant-scoped aliases; NULL for global built-ins.",
    )

    # Relationships
    synonyms: Mapped[list["EacAliasSynonym"]] = relationship(
        back_populates="alias",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="EacAliasSynonym.priority",
    )

    def __repr__(self) -> str:
        return f"<EacParameterAlias {self.name} scope={self.scope}>"


# ── Alias synonym ───────────────────────────────────────────────────────


class EacAliasSynonym(Base):
    """One synonym pattern attached to a parent :class:`EacParameterAlias`.

    Synonyms are tried in ``priority`` order (asc). The first match wins.
    Numeric values can be unit-converted by ``unit_multiplier`` so a
    synonym pattern ``length_mm`` with multiplier ``0.001`` returns the
    canonical metres for an alias whose default unit is ``m``.
    """

    __tablename__ = "oe_eac_alias_synonyms"
    __table_args__ = (
        Index("ix_eac_alias_synonym_alias_priority", "alias_id", "priority"),
    )

    alias_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_eac_parameter_aliases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pattern: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Property name string (exact) or regex pattern.",
    )
    kind: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="exact",
        server_default="exact",
        doc="One of: exact, regex",
    )
    case_sensitive: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=100,
        server_default="100",
        doc="Ascending — lower wins. Built-in canonical names use 10.",
    )
    pset_filter: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Optional Pset name to narrow the search.",
    )
    source_filter: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="any",
        server_default="any",
        doc="One of: any, instance, type, pset, external_classification",
    )
    unit_multiplier: Mapped[Decimal] = mapped_column(
        Numeric(20, 10),
        nullable=False,
        default=Decimal("1"),
        server_default="1",
        doc="Multiplier applied to numeric values after a match.",
    )

    # Relationships
    alias: Mapped[EacParameterAlias] = relationship(back_populates="synonyms")

    def __repr__(self) -> str:
        return (
            f"<EacAliasSynonym alias={self.alias_id} pattern={self.pattern!r} "
            f"prio={self.priority}>"
        )


# ── Alias snapshot ──────────────────────────────────────────────────────


class EacAliasSnapshot(Base):
    """Immutable snapshot of all aliases for a scope at a point in time.

    Captured by :class:`EacRun` at the start of execution to guarantee
    deterministic replay even if the user later edits or deletes aliases
    referenced by the rule definitions in this run.
    """

    __tablename__ = "oe_eac_alias_snapshots"
    __table_args__ = (
        Index("ix_eac_alias_snapshot_scope", "scope", "scope_id"),
    )

    taken_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    aliases_json: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
        doc=(
            "Full snapshot: {alias_name: {id, value_type_hint, default_unit, "
            "synonyms: [...]}}."
        ),
    )

    def __repr__(self) -> str:
        return f"<EacAliasSnapshot scope={self.scope} at={self.taken_at}>"


__all__ = [
    "ALIAS_SCOPES",
    "ALIAS_SOURCE_FILTERS",
    "ALIAS_SYNONYM_KINDS",
    "ALIAS_VALUE_TYPE_HINTS",
    "EacAliasSnapshot",
    "EacAliasSynonym",
    "EacGlobalVariable",
    "EacParameterAlias",
    "EacRule",
    "EacRuleVersion",
    "EacRuleset",
    "EacRun",
    "EacRunResultItem",
    "GLOBAL_VARIABLE_SCOPES",
    "GLOBAL_VARIABLE_VALUE_TYPES",
    "OUTPUT_MODES",
    "RULESET_KINDS",
    "RUN_STATUSES",
    "RUN_TRIGGERS",
]


def _stable_uuid(seed: str) -> uuid.UUID:
    """Deterministic UUIDv5 helper for fixtures and tests."""
    return uuid.uuid5(uuid.NAMESPACE_OID, f"oe.eac.{seed}")
