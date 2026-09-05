# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BOQ ORM models.

Tables:
    oe_boq_boq - bill of quantities (one per project scope)
    oe_boq_position - individual line items within a BOQ
    oe_boq_markup - markup/overhead lines applied to a BOQ
    oe_boq_activity_log - audit trail for BOQ mutations
    oe_boq_snapshot - point-in-time BOQ state for version history
    oe_boq_quantity_link - live model→position quantity binding
"""

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class BOQ(Base):
    """Bill of Quantities - groups positions for a project."""

    __tablename__ = "oe_boq_boq"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft", index=True)

    # ── Phase 12.2 lock & revision fields ────────────────────────────────
    estimate_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    parent_estimate_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_boq_boq.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    base_date: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # ── Issue #435: the variation request this bill was raised for ───────
    # NULL is the whole existing world: a bill of the project at large, the
    # only kind that existed before this column, and the only kind the
    # project's bill register lists or the "which bill does this land in"
    # resolver will consider. A value means the bill prices exactly one
    # variation request's scope and belongs to that request rather than to
    # the project's estimate.
    #
    # The link is deliberately stored HERE and not as a ``boq_id`` on the
    # variation request. A column on the owning record cannot be filtered
    # out of ``SELECT ... FROM oe_boq_boq WHERE project_id = ?`` without a
    # subquery from ``oe_boq`` into the owning module, which inverts the
    # dependency ``app/core/boq_target.py`` exists to avoid. That shape is
    # not hypothetical: ``DesignOption.boq_id`` is exactly it, and design
    # option bills consequently land, unannounced, in every project-wide
    # money aggregate in the tree.
    #
    # A plain GUID rather than a ForeignKey, the same convention as
    # ``MoCEntry.variation_request_id`` and ``Position.contract_id``: the
    # BOQ module must keep working when the variations module is not
    # installed, so it may not carry a DB-level dependency on its tables.
    #
    # NOT unique. A revision of a variation bill is still that request's
    # bill (see ``BOQService.duplicate_boq``), and the revision chain hangs
    # off ``parent_estimate_id`` exactly as it does for a project bill.
    variation_request_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    positions: Mapped[list["Position"]] = relationship(
        back_populates="boq",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Position.sort_order",
    )
    markups: Mapped[list["BOQMarkup"]] = relationship(
        back_populates="boq",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="BOQMarkup.sort_order",
    )

    def __repr__(self) -> str:
        return f"<BOQ {self.name} ({self.status})>"


class Position(Base):
    """Single line item in a BOQ - the core estimation entity."""

    __tablename__ = "oe_boq_position"
    __table_args__ = (
        # Covers the hot read path ``WHERE boq_id=? ORDER BY sort_order``
        # used by every position listing call (repository.list_positions,
        # repository.list_children, BOQ editor refresh, GAEB export).
        # Without the composite the planner has to fall back to
        # ``ix_oe_boq_position_boq_id`` + a temp B-tree sort on every
        # request - 1.2 s on a 6 k-position BOQ. With it: ~12 ms.
        # See alembic v3123_boq_fk_indexes for the prod migration.
        Index("ix_boq_position_boq_sort", "boq_id", "sort_order"),
        # Covers the tree-walk hot path
        # ``WHERE boq_id=? AND parent_id IS ?`` used by the hierarchical
        # BOQ renderer (#136 multi-level nesting up to depth 8).
        Index("ix_boq_position_boq_parent", "boq_id", "parent_id"),
    )

    boq_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_boq_boq.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_boq_position.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    ordinal: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    # Money/quantity stored as String by design - SQLite's native Numeric
    # degrades to REAL with precision loss, and JS JSON consumers lose
    # digits on large currency values via Number. Service layer coerces to
    # Decimal via ``_to_decimal`` for all arithmetic.
    quantity: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    unit_rate: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    total: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    classification: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    confidence: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # ── Issue #453: the judgement in a line, beside the arithmetic ────────
    # ``confidence`` says how sure the estimator is. It cannot say how WRONG
    # the line could be, and that is the number an offer is tested against:
    # a margin that survives the declared risk is ``target - z * sigma``
    # weighted by amount. ``risk_dispersion`` is that sigma, as a fraction of
    # the line's own amount, so it stays comparable across lines of very
    # different size and can be averaged with ``amount`` as the weight. Values
    # above 1 are allowed and mean what they say: a line can be more uncertain
    # than it is big.
    #
    # ``price_basis`` says what the price STANDS ON, which is not what
    # ``source`` says. Source records how the row was entered, defaults to
    # ``manual`` and is written literally by every ordinary create path, so on
    # a typed or workbook-imported bill it is ``manual`` on nearly every row -
    # money grouped by it looks like a price-evidence report and is a
    # provenance report with one bar. A hand-typed row can have an invoice
    # behind it and a catalogue row can rest on a guess.
    #
    # Both are NULL until somebody judges the line, and NULL is not zero and
    # not ``judgement``. A default on either would put an unearned number on
    # every row that already exists, which is the failure the columns exist to
    # prevent. String for the same reason the money columns above are strings.
    risk_dispersion: Mapped[str | None] = mapped_column(String(20), nullable=True)
    price_basis: Mapped[str | None] = mapped_column(String(30), nullable=True)
    cad_element_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    # ── Issue #347: owning BIM model of the linked elements ──────────────
    # ``cad_element_ids`` on its own is ambiguous in a multi-model project:
    # a stable_id is unique only per model (index ix_bim_element_model_stable)
    # and even a DB-UUID id must be resolved against the right model's element
    # set. This records the model that owns the elements in ``cad_element_ids``
    # so the BOQ "pick quantity from BIM" picker and the mini 3D preview
    # resolve each position against ITS model instead of the project's "first
    # ready" one. NULL = legacy/unknown - callers fall back to the
    # project-level model (pre-#347 behaviour, safe for single-model projects).
    cad_model_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    validation_status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")

    # ── Phase 12.2 expansion fields ──────────────────────────────────────
    wbs_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    cost_code_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # ── Methodology / analytical-dimension attributes ────────────────────
    # Additive nullable attributes driven by the project's estimating
    # methodology (app.modules.methodology). ``node_type`` is the typed
    # hierarchy level (e.g. section/complex/object/work for railway) taken
    # from the methodology's level defs. The remaining ids are plain
    # cross-module references resolved at the service layer (same convention
    # as wbs_id/cost_code_id above): contractor/contract reuse the existing
    # Contract/Subcontractor entities, ``funding_source_id`` points at
    # oe_funding_source, and ``stage_id`` at a stage dimension value.
    node_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    contractor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    contract_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    funding_source_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    stage_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # ── Issue #127: reusable code & linked-position groups ───────────────
    # ``reference_code`` is the USER-FACING reusable code
    # (Sección/Partida/Recurso, e.g. "0040"). It is DELIBERATELY distinct
    # from ``ordinal`` (the line number): ``ordinal`` stays unique within a
    # BOQ (GAEB X83 RNoPart/ID identity + boq_quality.no_duplicate_ordinals),
    # while the SAME ``reference_code`` may be reused across many positions.
    # Every position carries one (auto-generated "R-XXXXXXXX" when the
    # client supplies none) so it is always referenceable.
    reference_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Positions that SHARE one master definition all carry the same
    # ``link_group_id``. NULL = standalone (not yet part of a group).
    link_group_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    # 'master' = owns the canonical definition; 'instance' = a linked reuse
    # that mirrors the master's definition; NULL = standalone.
    link_role: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # ── Cost Spine linkage (v6.4) ────────────────────────────────────────
    # Additive nullable link to the cost line this position rolls up into.
    # Written by the spine generator; NULL on positions not yet wired.
    cost_line_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)

    # ── Issue #457: the production norm this line was priced from ────────
    # Written at the storage boundary from ``metadata["norm_id"]`` /
    # ``metadata["work_key"]``, which the apply-an-assembly path already sets
    # when the assembly was itself built from a norm. The identity is COPIED
    # rather than resolved through the assembly, because the assembly can be
    # edited or deleted after a bill was priced from it and provenance that has
    # to be resolved through a mutable row is not provenance. For the same
    # reason there is no foreign key to the norm table: the norm library is
    # editable and deletable, and a key would either block that or null the
    # provenance out on cascade.
    #
    # ``norm_work_key`` rides along rather than being looked up, because it is
    # the human handle and it has to survive the deletion of the row it names.
    #
    # Both NULL until something prices the line from a norm, and NULL is the
    # only honest way to say "not priced from a norm": most of a real bill is
    # typed or imported and never was. The metadata keys stay written too, so a
    # reader from before these columns keeps working.
    norm_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    norm_work_key: Mapped[str | None] = mapped_column(String(120), nullable=True)

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── BUG-CONCURRENCY01: optimistic concurrency token ─────────────────
    # Bumped on every successful service-layer update.  Clients echo the
    # last-read value on PATCH; mismatch returns 409 instead of allowing
    # a lost write.  Default 0 for legacy rows so existing data is valid.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Relationships
    # ``raise_on_sql``: the FK is already on this row, so walking back up to the
    # BOQ implicitly only ever costs a query. Every current reader orders it
    # explicitly (see ``events.py`` and ``router.py``, both
    # ``selectinload(Position.boq).noload(...)``); this makes the next one that
    # forgets fail here by name instead of as a MissingGreenlet further down.
    # Reads stay free when the parent collection already back-populated it.
    boq: Mapped[BOQ] = relationship(back_populates="positions", lazy="raise_on_sql")
    children: Mapped[list["Position"]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    # Known deviation from the self-referential rule (which asks for
    # ``raise_on_sql`` on the way up): this one is left eager on purpose. The
    # hierarchy is walked upward all over the editor and the GAEB export, and
    # ``selectin`` on a self-reference costs one extra SELECT per level rather
    # than per row. Revisit if position trees ever get deep.
    parent: Mapped["Position | None"] = relationship(
        back_populates="children",
        remote_side="Position.id",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Position {self.ordinal} - {self.description[:40]}>"


class BOQMarkup(Base):
    """Markup line applied to a BOQ (overhead, profit, tax, contingency).

    Represents a single markup/overhead line that is applied on top of the
    direct cost (sum of position totals).  Markups are ordered by ``sort_order``
    and can be applied as a percentage of the direct cost, a fixed amount, or
    cumulatively (percentage of direct cost + preceding markups).

    Columns:
        boq_id - owning BOQ
        name - human-readable label, e.g. "Site Overhead (BGK)"
        markup_type - "percentage" | "fixed"
        category - semantic grouping: overhead, profit, tax, contingency, …
        percentage - stored as string for SQLite compatibility (e.g. "8.0")
        fixed_amount - used when markup_type is "fixed"
        apply_to - "direct_cost" (default) or "cumulative"
        sort_order - evaluation order (ascending)
        is_active - soft toggle
        scope_position_id - NULL for a bill-wide line, otherwise the position
            (usually a section) this line is confined to, descendants included
        overrides_id - the bill-wide line a scoped line replaces, or NULL for a
            scoped line that adds something the bill-wide stack does not have

    Inheritance and override:
        A row with ``scope_position_id`` NULL is the company standard: it
        applies to the whole bill. A row that names a position applies only to
        that position and everything below it, and if it also names an
        ``overrides_id`` it stands in for that bill-wide line inside its own
        subtree. Everywhere else the bill-wide line is still what applies. This
        is what lets a standard carry a per-trade exception, which is the shape
        a markup set could not express before: previously the only way to price
        one section differently was to change the number for the whole bill.

        The overriding line keeps the position of the line it replaces in the
        compounding order, not its own ``sort_order``. Order is the company
        standard's decision; the exception is about the rate, and letting an
        override move a step would silently change what every later step
        compounds on.

        Overrides nest. A leaf takes every override on its chain of ancestors,
        with the nearest one winning per line, so a trade-level exception
        inside a phase-level exception behaves the way it reads.

        ``is_active`` false on a scoped line means the line is simply not
        there, so the bill-wide line is inherited again. To suppress a company
        line for one section, override it at zero rather than deactivating the
        override.
    """

    __tablename__ = "oe_boq_markup"
    __table_args__ = (
        # Covers ``WHERE boq_id=? ORDER BY sort_order, created_at`` -
        # the single read pattern for the markups grid (repository
        # ``list_for_boq``, BOQ total rollup, GAEB export markup write).
        Index("ix_boq_markup_boq_sort", "boq_id", "sort_order"),
    )

    boq_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_boq_boq.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    markup_type: Mapped[str] = mapped_column(String(50), nullable=False, default="percentage")
    category: Mapped[str] = mapped_column(String(100), nullable=False, default="overhead")
    percentage: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    fixed_amount: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    apply_to: Mapped[str] = mapped_column(String(50), nullable=False, default="direct_cost")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Both nullable, both defaulting to NULL, so every markup row that exists
    # today keeps the meaning it already had: bill-wide, inherited by
    # everything, computed on the whole direct cost.
    scope_position_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_boq_position.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # Self-referential and deliberately ``SET NULL`` rather than ``CASCADE``:
    # deleting the company line should leave the section's own number standing
    # as an ordinary scoped line, not delete money the estimator entered by
    # hand. The scoped line then simply stops replacing anything.
    overrides_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_boq_markup.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    # ``raise_on_sql`` for the same reason as ``Position.boq``: the FK is on the
    # row, nothing reads this attribute today, and an implicit walk upwards is
    # exactly the shape that crashes on an identity-map hit.
    boq: Mapped[BOQ] = relationship(back_populates="markups", lazy="raise_on_sql")

    def __repr__(self) -> str:
        return f"<BOQMarkup {self.name} ({self.markup_type}: {self.percentage}%)>"


class BOQActivityLog(Base):
    """Audit trail entry for BOQ-related mutations.

    Records every significant action (position created/updated/deleted,
    markup added, BOQ exported, etc.) for traceability and undo support.

    Columns:
        project_id - optional project scope for project-wide queries
        boq_id - optional BOQ scope
        user_id - who performed the action
        action - dot-notation action key, e.g. "position.created"
        target_type - entity kind: "position", "boq", "markup", "section"
        target_id - UUID of the affected entity (nullable for bulk ops)
        description - human-readable summary, e.g. "Added position 01.01.0010"
        changes - field-level diff, e.g. {"field": "quantity", "old": "100", "new": "150"}
        metadata_ - additional context (module version, client IP, etc.)
    """

    __tablename__ = "oe_boq_activity_log"
    __table_args__ = (
        Index("ix_boq_activity_user_created", "user_id", "created_at"),
        Index("ix_boq_activity_target", "target_type", "target_id"),
        # Audit-feed read paths - both per-project and per-BOQ activity
        # streams are ordered by created_at DESC. The composites turn an
        # O(n) sequential scan of the (potentially huge) audit table into
        # an index-only range scan.
        Index("ix_boq_activity_project_created", "project_id", "created_at"),
        Index("ix_boq_activity_boq_created", "boq_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    boq_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_boq_boq.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Nullable: system-generated activity (e.g. event-driven ``cost_breakdown.
    # computed``) has no acting user. Previously a nil-UUID sentinel was written,
    # which SQLite accepted (FK enforcement off by default) but PostgreSQL
    # rejected with a ForeignKeyViolationError. NULL = "System" in the feed.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    changes: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<BOQActivityLog {self.action} target={self.target_type}:{self.target_id}>"


class BOQSnapshot(Base):
    """Point-in-time snapshot of a BOQ for version history.

    Stores a full JSON snapshot of the BOQ state (positions, markups)
    so users can view and restore previous versions.
    """

    __tablename__ = "oe_boq_snapshot"
    __table_args__ = (
        # Version-history list is ordered by created_at DESC scoped to
        # one BOQ - composite turns the index seek into a range scan
        # without a separate sort step.
        Index("ix_boq_snapshot_boq_created", "boq_id", "created_at"),
    )

    boq_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_boq_boq.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    snapshot_data: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    def __repr__(self) -> str:
        return f"<BOQSnapshot boq={self.boq_id} name={self.name}>"


class QuantityLink(Base):
    """Live binding between a BOQ position and a set of BIM model elements.

    Records *how* a position's numeric field is derived from the canonical
    quantities of one or more model elements so the figure can be
    re-pulled when the source model revises. The link is a *rule*, never a
    cached value - the current quantity always lives on
    :class:`Position`; this row only states the extraction recipe and the
    provenance of the last applied pull.

    Columns:
        position_id - owning BOQ position (CASCADE on delete)
        boq_id - denormalised owning BOQ for cheap per-BOQ listing/refresh
        model_id - the BIM model the binding tracks (NOT version-pinned;
            ``compute_diff`` resolves the latest version on refresh)
        element_stable_ids - list[str] of canonical element ``stable_id``s
            whose quantities feed this position
        quantity_field - the canonical quantity key to read off each
            element's ``quantities`` map, e.g. ``area_m2`` / ``volume_m3``
        target_field - the Position numeric field the aggregate writes to;
            currently always ``quantity`` (only field a model can drive)
        aggregation - how multiple elements combine: ``sum`` (default),
            ``max``, ``min``, ``count``, ``first``
        status - ``active`` (in sync) | ``stale`` (a refresh detected the
            source elements changed and a human has not yet applied) |
            ``broken`` (model/elements no longer resolvable)
        source_model_version - the model ``version`` string captured at
            the last successful apply (provenance)
        last_applied_quantity - the position quantity this link last
            wrote (provenance / staleness baseline), stored as a string
            for the same SQLite-precision reason as Position.quantity
        last_pulled_at - ISO-8601 UTC timestamp of the last refresh probe
        last_applied_at - ISO-8601 UTC timestamp of the last human apply
        created_by / applied_by - user provenance (who bound / who applied)
        metadata_ - module-extensible blob (last diff envelope etc.)
    """

    __tablename__ = "oe_boq_quantity_link"
    __table_args__ = (
        Index("ix_boq_quantity_link_boq", "boq_id"),
        Index("ix_boq_quantity_link_status", "status"),
        # "Find broken / stale links for this BOQ" - the dashboard
        # health card hits this on every BOQ open.
        Index("ix_boq_quantity_link_boq_status", "boq_id", "status"),
    )

    position_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_boq_position.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    boq_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_boq_boq.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )
    element_stable_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    quantity_field: Mapped[str] = mapped_column(String(64), nullable=False)
    target_field: Mapped[str] = mapped_column(String(32), nullable=False, default="quantity", server_default="quantity")
    aggregation: Mapped[str] = mapped_column(String(16), nullable=False, default="sum", server_default="sum")
    # ── Issue #347: per-element quantity formulas ────────────────────────
    # ``projection_mode`` splits HOW each element's contribution is derived:
    #   'field'   - read ``quantity_field`` off the element's quantities map
    #               (the original behaviour, still the default);
    #   'formula' - evaluate ``formula`` per element against that element's
    #               variables, then combine with the same ``aggregation``.
    # Nullable + server_default so existing rows read as 'field' with no
    # backfill; ``quantity_field`` is left NOT NULL (formula-mode links store
    # an empty string there) so this stays a purely additive migration.
    projection_mode: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
        default="field",
        server_default="field",
    )
    # The arithmetic expression evaluated per element in 'formula' mode
    # (e.g. ``area_m2 * 0.5``). NULL in 'field' mode.
    formula: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")
    source_model_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_applied_quantity: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_pulled_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_applied_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    applied_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return (
            f"<QuantityLink pos={self.position_id} model={self.model_id} "
            f"{self.quantity_field}->{self.target_field} ({self.status})>"
        )


# Register the per-position AI copilot model on ``Base.metadata`` by importing
# it here. Module model discovery (app.main create_all + tests._pg template +
# conftest) imports ``app.modules.boq.models``; importing the copilot model from
# this already-discovered module guarantees ``oe_boq_position_copilot_message``
# is created on a fresh database and seen by Alembic autogenerate, without
# adding a hand-maintained import elsewhere.
from app.modules.boq.copilot_models import PositionCopilotMessage  # noqa: E402,F401
