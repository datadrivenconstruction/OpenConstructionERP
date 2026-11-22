# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project ORM models.

Tables:
    oe_projects_project          - construction estimation projects
    oe_projects_wbs              - work breakdown structure nodes
    oe_projects_milestone        - project milestones (payment, approval, handover)
    oe_projects_match_settings   - per-project element-to-CWICR auto-match settings
    oe_projects_demo_tombstone   - demo projects the user removed, kept out of later boots
    oe_projects_participant_grant - a company's granted participation in a project
                                    it does not own (ADR 006)
"""

# ── Match-settings defaults (v2.8.0) ─────────────────────────────────────
# Module-level constants so the model, schemas, service, and Alembic
# migration all share a single source of truth - no magic numbers.
#
# Values are env-overridable so a deploy that ships in a non-English
# market (e.g. a Russian rollout) can change the default for fresh
# projects without a code change. Existing projects keep whatever they
# were saved with - these constants only pin the *new-row* default.
import os as _os
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base

MATCH_DEFAULT_TARGET_LANGUAGE: str = _os.environ.get("MATCH_DEFAULT_TARGET_LANGUAGE", "en").strip().lower() or "en"
MATCH_DEFAULT_CLASSIFIER: str = "none"


def _env_float_default(name: str, fallback: float) -> float:
    raw = _os.environ.get(name)
    if raw is None or not raw.strip():
        return fallback
    try:
        return float(raw)
    except ValueError:
        return fallback


MATCH_DEFAULT_AUTO_LINK_THRESHOLD: float = _env_float_default("MATCH_DEFAULT_AUTO_LINK_THRESHOLD", 0.85)
MATCH_DEFAULT_AUTO_LINK_ENABLED: bool = False
MATCH_DEFAULT_MODE: str = "manual"
MATCH_DEFAULT_SOURCES: tuple[str, ...] = ("bim", "pdf", "dwg", "photo")

MATCH_ALLOWED_CLASSIFIERS: frozenset[str] = frozenset(
    {"none", "din276", "nrm", "masterformat"},
)
MATCH_ALLOWED_MODES: frozenset[str] = frozenset({"manual", "auto"})
MATCH_ALLOWED_SOURCES: frozenset[str] = frozenset(MATCH_DEFAULT_SOURCES)


class Project(Base):
    """Construction estimation project."""

    __tablename__ = "oe_projects_project"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    region: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    classification_standard: Mapped[str] = mapped_column(String(50), nullable=False, default="din276")
    # No EUR bias: empty string means "not chosen yet", mirroring the
    # ProjectCreate schema default. API creates always pass an explicit
    # value; the empty default only applies to bare ORM constructions.
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="de")
    validation_rule_sets: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=lambda: ["boq_quality"],
        server_default='["boq_quality"]',
    )
    # ── Item #27 - compliance rule packs enforced at workflow gates ──────
    # Jurisdiction-scoped bundles of validation rule sets (see
    # app.modules.contracts.compliance_packs.RULE_PACKS) that the contract
    # signature gate enforces on a draft → active transition. Defaults to the
    # cross-market ``universal`` pack so every project has a meaningful gate
    # out of the box; a project can override via PATCH
    # /{id}/compliance-rule-packs.
    compliance_rule_packs: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=lambda: ["universal"],
        server_default='["universal"]',
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    owner_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Organization (ADR 005) ──────────────────────────────────────────
    # The tenant this project belongs to. Nullable, and it stays nullable
    # here: ``oe_projects_project`` carries no ``tenant_id`` column, so it is
    # not in ``tenant_tables()`` and no row-level policy is attached to it.
    # This is the edge ``Organization -> Project`` in the ownership graph,
    # recorded so that ownership can be answered from the project instead of
    # only through its owner's membership, which is a two-hop question and
    # changes meaning the moment an owner leaves the company.
    #
    # ``SET NULL`` rather than ``CASCADE``: removing an organization must not
    # remove its projects. A project with no organization can be re-pointed by
    # the boot repair or by an administrator; a deleted one cannot be recovered.
    #
    # Tightening this to ``NOT NULL`` is deliberately not part of this change.
    # It is a decision to make once ``rls_readiness_report`` says every row has
    # an owner, not a constraint to add and then discover which installs fail
    # it.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_organization.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ── Country code (Wave 28; migration v3136) ─────────────────────────
    # ISO 3166-1 alpha-2. Drives the CPM calendar engine and the AIA
    # G702/G703 country gate (US/CA/AU only). The column already exists in
    # the DB with server_default 'DE'; mapping it here lets the ORM and the
    # project response surface it without a new migration.
    #
    # Nullable since v3319, and the note this replaced is worth keeping in
    # summary because the shape of the bug recurs. The column used to be
    # NOT NULL DEFAULT 'DE' while the API accepted the field as optional, so a
    # create that omitted a country stored the project as German: "nobody
    # chose" and "somebody chose Germany" were the same row, and every
    # consumer answered for Germany without anything saying it was a guess.
    #
    # It was left that way on the reasoning that the two consumers, the CPM
    # working calendar and the AIA payment-application gate, were tolerable
    # places to be wrong. A third consumer changed that: markup-region
    # resolution reads this column, so an unstated market would have been
    # quoted with German overheads, German profit and German VAT.
    #
    # NULL means the country is unknown, not that it is neutral. Every reader
    # has to decide what to do with that; none of them may substitute a
    # plausible country for it. Rows written before v3319 still carry 'DE' and
    # the distinction is not recoverable for them, which the migration says at
    # length rather than papering over.
    country_code: Mapped[str | None] = mapped_column(
        String(2),
        nullable=True,
        default=None,
    )
    # ISO 3166-2 state or province where the work is, e.g. "US-CA". Some rules
    # are set below the country: California caps a home-improvement deposit,
    # Victoria a domestic-building one. NULL means not recorded, and a rule
    # scoped to a subdivision then says it could not run rather than guess.
    subdivision_code: Mapped[str | None] = mapped_column(String(6), nullable=True, default=None)
    # The company in the group that owns the project, a row of the legal
    # entities module. NULL means none was named and the default entity
    # answers. No database foreign key: legal entities is a module that can be
    # left out, and the core project table must build without its table. The
    # module checks the id on write and refuses to delete an entity in use.
    legal_entity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, default=None, index=True)

    # Whether the client is a public buyer: "public" or "private", the
    # vocabulary the state packs write their retention rules in. Where a
    # country's law on retention follows the client (France: the Code de la
    # commande publique for public contracts, loi 71-584 for private works),
    # the contract defaults read it here. NULL means not recorded, not
    # private, and every reader keeps the country's neutral figures for it.
    works: Mapped[str | None] = mapped_column(String(16), nullable=True, default=None)

    # ── Phase 12 expansion fields (all nullable for backward compat) ─────
    project_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    project_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    phase: Mapped[str | None] = mapped_column(String(50), nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    parent_project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    address: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=True
    )
    contract_value: Mapped[str | None] = mapped_column(String(50), nullable=True)
    planned_start_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    planned_end_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    actual_start_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    actual_end_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    budget_estimate: Mapped[str | None] = mapped_column(String(50), nullable=True)
    contingency_pct: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # ── Cost Benchmarks portfolio input (migration v3174) ────────────────
    # Gross floor area in m2 GFA, decimal-string to match the project money
    # columns (full precision, no JSON Number rounding). NULL means area is
    # not recorded; the benchmark portfolio aggregation skips such projects.
    gross_floor_area: Mapped[str | None] = mapped_column(String(50), nullable=True)
    custom_fields: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=True
    )
    work_calendar_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # ── v2.6.0 - multi-currency + per-project VAT (RFC 37, Issues #88/#89/#93) ──
    # ``fx_rates`` holds extra currencies the project uses alongside ``currency``
    # (the base). Shape:
    #     [{"code": "USD", "rate": "1200.50", "label": "US Dollar"}]
    # ``rate`` is a decimal-string giving how many BASE units per 1 unit of the
    # foreign currency. Empty list = single-currency project (existing
    # behaviour).
    fx_rates: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    # ``default_vat_rate`` overrides the regional template's VAT row when a new
    # BOQ is seeded. Stored as a decimal-string percentage (e.g. ``"21"`` for
    # 21%). NULL means "use regional default" - preserves pre-2.6 behaviour
    # for projects that never set it.
    default_vat_rate: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
    )
    # ``custom_units`` lets a project carry unit codes not in the canonical
    # frontend list (Issue #93 item 3). Plain list of strings - order matters
    # because the UI shows custom units after the canonical set in the order
    # the user added them.
    custom_units: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # ── v2.9.4 - Per-project storage override (Issue #109) ──────────────
    # When ``storage_uses_default`` is True (the default), all attachments
    # for this project land under the system-wide data dir resolved by the
    # documents / photos / sheets / BIM / DWG services. When False and
    # ``storage_path_override`` is non-empty, services route writes for
    # this project under ``{override}/{project_id}/<kind>/...`` instead.
    # Reads always check both paths so legacy rows keep working.
    storage_path_override: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        default=None,
    )
    storage_uses_default: Mapped[bool] = mapped_column(
        nullable=False,
        default=True,
        server_default="1",
    )

    # ── Relationships ────────────────────────────────────────────────────
    children: Mapped[list["Project"]] = relationship(
        back_populates="parent_project",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    parent_project: Mapped["Project | None"] = relationship(
        back_populates="children",
        remote_side="Project.id",
        lazy="selectin",
    )
    wbs_nodes: Mapped[list["ProjectWBS"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ProjectWBS.sort_order",
    )
    milestones: Mapped[list["ProjectMilestone"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ProjectMilestone.planned_date",
    )

    def __repr__(self) -> str:
        return f"<Project {self.name} ({self.status})>"


class ProjectStatusHistory(Base):
    """Timestamped audit trail of a project's status transitions.

    One row per change to ``Project.status`` (e.g. active -> on_hold,
    active -> archived, archived -> active). ``from_status`` is null for the
    initial status recorded at creation. ``changed_by`` references the acting
    user and is nullable / ``SET NULL`` so deleting a user never erases the
    history. Surfaced read-only by the projects router so the UI can show who
    changed status from X to Y and when.
    """

    __tablename__ = "oe_project_status_history"
    __table_args__ = (
        Index("ix_project_status_history_project", "project_id"),
        Index(
            "ix_project_status_history_project_created",
            "project_id",
            "created_at",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Null = the initial status recorded when the project was created.
    from_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    to_status: Mapped[str] = mapped_column(String(50), nullable=False)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    def __repr__(self) -> str:
        return f"<ProjectStatusHistory project={self.project_id} {self.from_status}->{self.to_status}>"


#: What a grant lets the grantee company do (ADR 006, owner decision 7).
#:
#: A three-value vocabulary rather than a reference to an RBAC permission set,
#: so a grant says something a contract can say: this company may look, this
#: company may add its own work, this company may steer the project. Ordered
#: from least to most authority, which is the order :data:`GRANT_SCOPE_RANK`
#: below makes explicit so a comparison never depends on tuple position.
GRANT_SCOPES = ("view", "contribute", "manage")

#: The same three values, least authority first, for "at least this scope".
GRANT_SCOPE_RANK = {scope: rank for rank, scope in enumerate(GRANT_SCOPES)}

#: What state a grant is in. Mirrors ``Membership.status`` on purpose, so the
#: two authorization layers a caller passes through read the same way and a
#: screen can show both without translating one of them.
#:
#: There is deliberately no ``offered``. The owner decided a grant is
#: unilateral (ADR 006, decision 2): the company that owns the project decides
#: who participates, and nothing waits for the grantee to accept. A status that
#: nothing can ever hold is a vocabulary entry that reads as a state machine
#: with a missing transition.
GRANT_STATUSES = ("active", "suspended", "revoked")


class ProjectParticipantGrant(Base):
    """One company's participation in one project it does not own. ADR 006.

    The edge ``Project -> Grant -> grantee Organization`` in the ownership graph,
    and the answer to the question ADR 005 left open: a project belongs to one
    organization, so what happens when work on it belongs to more than one.

    **The grantee is an organization, never a user** (owner decision 8). A
    company participates and its members inherit that participation through
    their membership of the company, which is the composition ADR 005 already
    established. An individual consultant who needs access creates a one-person
    organization: one rule for everybody, and no second kind of participant
    whose authorization has to be resolved differently. The column is a foreign
    key to ``oe_users_organization`` and there is no user-shaped alternative to
    it, so the mistake ADR 005 spent a repair fixing - a person's id in a
    company's column - cannot be repeated here by accident.

    **A grant is one of two layers, and both must answer yes.** This is the
    company layer: is the caller's organization the owner of the project or a
    live grantee on it. The person layer stays where it is,
    ``verify_project_access`` and ``is_project_member``: is this specific person
    on the project's team. A company-level grant with no team membership does
    not open a project, because that would let a company's entire staff read a
    project nobody assigned them to. Team membership with no company
    participation does not open it either, which is the case that existed before
    this table and is the hole it closes.

    **It carries no ``tenant_id`` of its own**, for the same reason
    ``Organization`` carries none: a grant is not inside a tenant, it is a
    statement about the relation between two of them. A tenant column here would
    put the table in ``tenant_tables()`` and give it a policy comparing its own
    identity with the caller's, which would hide every grant from the grantee it
    names - the one reader that has to see it.

    **Revoked rows are kept.** Revocation is an event with an author, a moment
    and a reason, not a deletion, so the sequence of grants on a project is
    reconstructible from this table alone even if ``oe_activity_log`` is pruned.
    That is also why the uniqueness is a *partial* index over the live rows: one
    live grant per company per project, and re-granting after a revocation
    inserts a new row rather than resurrecting the old one, so the history
    survives and the live set the predicate reads stays unambiguous.

    **Nothing about a grant is retroactive.** Revoking one stops the predicate
    matching from the moment the row is written; it does not delete, re-stamp or
    hide anything, and it must never be implemented as an unbounded ``UPDATE``.
    Rows a grantee wrote under a grant carry the grantee's own ``tenant_id``
    (owner decision 3), so they stay the grantee's afterwards and the project's
    owner can no longer read them through the project arm. That is the intended
    answer, not a leak in the other direction: ownership follows the author's
    company, which is what keeps the row's own tenant scope honest.
    """

    __tablename__ = "oe_projects_participant_grant"
    __table_args__ = (
        # One LIVE grant per company per project. Partial rather than plain so
        # that a revoked row does not block the re-grant that replaces it, and
        # so the constraint the predicate relies on - at most one row to read
        # per (project, company) - is the one the database enforces.
        Index(
            "uq_projects_participant_grant_live",
            "project_id",
            "grantee_organization_id",
            unique=True,
            postgresql_where=text("status <> 'revoked'"),
            sqlite_where=text("status <> 'revoked'"),
        ),
        # Both ends optional, because an open-ended grant is the normal one and
        # a tender period or a site handover is the normal reason to close it.
        # What is not allowed is a window that ends before it starts.
        CheckConstraint(
            "valid_from IS NULL OR valid_until IS NULL OR valid_until > valid_from",
            name="ck_participant_grant_window",
        ),
        # Not a free string, in the database and not only in the schema layer:
        # a value outside the vocabulary would be a grant nobody can interpret,
        # and every reader of ``scope`` would have to invent a default for it.
        CheckConstraint(
            "scope IN ('view', 'contribute', 'manage')",
            name="ck_participant_grant_scope",
        ),
        CheckConstraint(
            "status IN ('active', 'suspended', 'revoked')",
            name="ck_participant_grant_status",
        ),
        # Every index on this table is named explicitly, including the two that
        # the naming convention would have produced legally. Two reasons: the
        # convention's ``ix_%(column_0_label)s`` for
        # ``granted_on_behalf_of_organization_id`` resolves to 69 characters,
        # which PostgreSQL will not store as written, and a migration has to
        # spell the same names ``create_all`` produces or the boot heal adds a
        # second copy of a constraint it cannot recognise
        # (``app.core.postgres_migrator._effective_name`` exists because that
        # happened). One scheme across the table means neither side has to
        # remember which columns were short enough to be left to the convention.
        Index("ix_projects_participant_grant_project", "project_id"),
        Index("ix_projects_participant_grant_grantee", "grantee_organization_id"),
        # The lookup the ownership change uses: every grant this company made,
        # which is what has to be suspended when the project stops being theirs.
        Index("ix_projects_participant_grant_on_behalf", "granted_on_behalf_of_organization_id"),
    )

    # ``CASCADE``: a grant on a deleted project is a statement about nothing.
    # Projects are archived rather than deleted in the ordinary course, so this
    # fires on a purge and not on a delete a user can perform by accident.
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE", name="fk_projects_participant_grant_project"),
        nullable=False,
    )
    # The participating company. ``CASCADE`` because a grant naming an
    # organization that no longer exists authorizes nobody and reads as a
    # dangling edge in the graph this table is.
    grantee_organization_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_organization.id", ondelete="CASCADE", name="fk_projects_participant_grant_grantee"),
        nullable=False,
    )
    # The human who decided. ``SET NULL`` and not ``CASCADE``: the decision
    # outlives the person, and deleting a user must not delete the record that
    # a company was given access to a project. Nullable for the same reason it
    # is nulled - after that it is still a fact that the grant was made.
    granted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL", name="fk_projects_participant_grant_granted_by"),
        nullable=True,
    )
    # The owning company at the moment of the grant. Recorded because ownership
    # can move and the authority to grant moves with it: this is the column that
    # says who was entitled to make this decision, which is the question a
    # suspended grant has to answer when it is reviewed.
    granted_on_behalf_of_organization_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey(
            "oe_users_organization.id",
            ondelete="CASCADE",
            name="fk_projects_participant_grant_on_behalf",
        ),
        nullable=False,
    )
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="view")
    # ``active`` / ``suspended`` / ``revoked``. Suspended is not revoked: it is
    # what a grant becomes when the project changes owner (owner decision 4),
    # pending a review by whoever owns it now, and it can go back to active
    # without anybody re-deciding the whole grant.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL", name="fk_projects_participant_grant_revoked_by"),
        nullable=True,
    )
    revocation_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    @property
    def is_live(self) -> bool:
        """Whether this grant authorizes anything right now.

        One rule, in one place, because four readers have to agree on it: the
        per-request project list, the row-level predicate, the read path it
        replaced, and the screen that lists a project's participants. A grant is
        live when it is ``active`` and inside its window; an expired grant is
        not a revoked one and stays readable as history without being readable
        as authority.

        Naive about timezones on purpose - both ends are stored aware and
        compared against an aware ``now()``, so the comparison is between two
        instants and never between an instant and a wall clock.
        """
        if self.status != "active":
            return False
        now = datetime.now(UTC)
        if self.valid_from is not None and self.valid_from > now:
            return False
        return not (self.valid_until is not None and self.valid_until <= now)

    def __repr__(self) -> str:
        return (
            f"<ProjectParticipantGrant project={self.project_id} "
            f"grantee={self.grantee_organization_id} {self.scope}/{self.status}>"
        )


class ProjectWBS(Base):
    """Work Breakdown Structure node for a project.

    Supports hierarchical decomposition of project scope into cost, schedule,
    or scope-oriented WBS trees.  Each node can carry planned cost/hours for
    earned-value analysis.
    """

    __tablename__ = "oe_projects_wbs"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_wbs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_translations: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=True
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wbs_type: Mapped[str] = mapped_column(String(50), nullable=False, default="cost")
    planned_cost: Mapped[str | None] = mapped_column(String(50), nullable=True)
    planned_hours: Mapped[str | None] = mapped_column(String(50), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    project: Mapped[Project] = relationship(back_populates="wbs_nodes")
    children: Mapped[list["ProjectWBS"]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    parent: Mapped["ProjectWBS | None"] = relationship(
        back_populates="children",
        remote_side="ProjectWBS.id",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<ProjectWBS {self.code} - {self.name}>"


class ProjectMilestone(Base):
    """Project milestone - payment, approval, handover, or general checkpoint.

    Tracks planned vs actual dates and can link to payment percentages for
    progress-based invoicing workflows.
    """

    __tablename__ = "oe_projects_milestone"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    milestone_type: Mapped[str] = mapped_column(String(50), nullable=False, default="general")
    planned_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    actual_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    linked_payment_pct: Mapped[str | None] = mapped_column(String(10), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    project: Mapped[Project] = relationship(back_populates="milestones")

    def __repr__(self) -> str:
        return f"<ProjectMilestone {self.name} ({self.status})>"


class MatchProjectSettings(Base):
    """Per-project settings for the element-to-CWICR auto-match pipeline.

    Captures the user's choices for the BIM/PDF/DWG/photo → catalog matcher:

    * ``target_language`` - ISO-639 two-letter code of the CWICR catalog
      slice to search against (e.g. ``de``, ``bg``, ``en``). Free-form so
      newly seeded languages don't require a schema bump.
    * ``classifier`` - optional classification standard the matcher should
      bias towards (``din276`` / ``nrm`` / ``masterformat``) or ``none``
      to skip classification altogether (per A4 decision).
    * ``auto_link_threshold`` - float in ``[0.0, 1.0]``; matches with a
      score above this are auto-linked (only when ``auto_link_enabled``).
    * ``auto_link_enabled`` - master toggle. False forces every match to
      go through human confirmation regardless of the threshold.
    * ``mode`` - ``manual`` (default) or ``auto``. The user must opt in
      to fully-automated linking.
    * ``sources_enabled`` - JSON list, subset of
      ``["bim", "pdf", "dwg", "photo"]``. Sources omitted from this list
      are skipped by the matcher service.

    One-to-one with :class:`Project` via the ``project_id`` unique FK.
    Cascade-delete on the project mirrors the WBS/milestone behaviour:
    when a project is hard-deleted its match settings go with it.
    """

    __tablename__ = "oe_projects_match_settings"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            name="uq_oe_projects_match_settings_project_id",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_language: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        default=MATCH_DEFAULT_TARGET_LANGUAGE,
        server_default=MATCH_DEFAULT_TARGET_LANGUAGE,
    )
    classifier: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=MATCH_DEFAULT_CLASSIFIER,
        server_default=MATCH_DEFAULT_CLASSIFIER,
    )
    auto_link_threshold: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=MATCH_DEFAULT_AUTO_LINK_THRESHOLD,
        server_default=str(MATCH_DEFAULT_AUTO_LINK_THRESHOLD),
    )
    auto_link_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=MATCH_DEFAULT_AUTO_LINK_ENABLED,
        server_default="0",
    )
    mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=MATCH_DEFAULT_MODE,
        server_default=MATCH_DEFAULT_MODE,
    )
    sources_enabled: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=lambda: list(MATCH_DEFAULT_SOURCES),
        server_default='["bim", "pdf", "dwg", "photo"]',
    )
    # CWICR catalogue ID the project matches against
    # (e.g. "RU_STPETERSBURG", "DE_BERLIN", "USA_USD"). Nullable: a freshly
    # created project has no binding - match endpoint returns a structured
    # ``no_catalog_selected`` error and the UI surfaces an explicit picker.
    # No auto-pick from ``project.region`` because regions are coarse tags
    # (DACH / EU / US) while catalogue IDs are city-level (DE_BERLIN).
    cost_database_id: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        default=None,
    )

    def __repr__(self) -> str:
        return (
            f"<MatchProjectSettings project={self.project_id} "
            f"mode={self.mode} classifier={self.classifier} "
            f"catalog={self.cost_database_id}>"
        )


class ProjectProfile(Base):
    """The applied profile for a project (concept doc §6.1).

    One row per project. Captures the wizard answers (preset, axes,
    region, …) so the module set can be recomputed when the profile is
    edited. ``focus_mode_enabled`` is the user-facing master switch the
    sidebar reads: when false the nav shows every module ungreyed
    (legacy behaviour) - the "this mode can be turned off" requirement.

    The wizard *draft* is intentionally NOT here (doc §6.4) - drafts
    live in :class:`ProjectWizardDraft` with a TTL so a half-finished
    setup never pollutes a real project.
    """

    __tablename__ = "oe_project_profile"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_project_profile_project"),
        Index("ix_project_profile_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    preset: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="custom",
        server_default="custom",
    )
    # Multi-select axes stored as JSON lists.
    activity: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    phases: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    role: Mapped[str | None] = mapped_column(String(48), nullable=True)
    size: Mapped[str | None] = mapped_column(String(24), nullable=True)
    region: Mapped[str | None] = mapped_column(String(32), nullable=True)
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    extensions_enabled: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    # Master switch the sidebar honours. True = numbered route + greyed
    # non-selected modules. False = show everything normally.
    focus_mode_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )
    # {"wizard_steps_completed":[1,2,3,5],"skipped_steps":[4],
    #  "completion_score":0.83}
    setup_completion: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<ProjectProfile project={self.project_id} preset={self.preset} focus={self.focus_mode_enabled}>"


class ProjectModule(Base):
    """Per-project module selection (concept doc §6.1 ``modules``).

    Presentation-only gating: this drives the sidebar's visual emphasis
    (active + numbered vs greyed) - it never unloads a module or blocks
    its API. ``ordinal`` is the global sequential number (doc §3.2);
    null for cross-cutting / disabled modules. ``source`` records why
    the module is in the set (core / region / preset / score / manual)
    so the wizard can explain it and edit-setup can diff cleanly.
    """

    __tablename__ = "oe_project_module"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "module_name",
            name="uq_project_module_unique",
        ),
        Index("ix_project_module_project", "project_id"),
        Index("ix_project_module_project_enabled", "project_id", "enabled"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    module_name: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    # must | recommended | optional | hidden
    tier: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="hidden",
        server_default="hidden",
    )
    score: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    phase: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="construction",
        server_default="construction",
    )
    # core | region | preset | score | manual
    source: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="score",
        server_default="score",
    )
    # Global sequential number for the numbered route; null = no number
    # (cross-cutting / disabled).
    ordinal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    why: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return f"<ProjectModule project={self.project_id} {self.module_name} {self.tier} ord={self.ordinal}>"


class ProjectWizardDraft(Base):
    """Transient wizard state (concept doc §6.4).

    Separate from :class:`ProjectProfile` so an abandoned half-finished
    setup never creates a real project. Promoted to a Project +
    ProjectProfile atomically on the wizard's final "Create" step.
    Rows older than ``WIZARD_DRAFT_TTL_DAYS`` are swept by a periodic
    job (not part of Slice 1 - the column is here so the sweep has a
    timestamp to filter on).
    """

    __tablename__ = "oe_project_wizard_draft"
    __table_args__ = (
        Index("ix_project_wizard_draft_owner", "created_by"),
        Index("ix_project_wizard_draft_created", "created_at"),
    )

    # Free-form wizard answers so far; shape mirrors ProjectProfile plus
    # the in-progress project name / code / dates.
    payload: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    def __repr__(self) -> str:
        return f"<ProjectWizardDraft by={self.created_by}>"


class DemoProjectTombstone(Base):
    """A demo project the user removed, so no later boot puts it back.

    Deleting a demo project archives the row, and an archived row already
    stops the installer from creating the demo again. Purging demo data removes
    the row itself, and after that nothing in the database remembered that the
    demo had ever been there: an install whose demo-seed choice file did not
    survive, or whose ``SEED_DEMO`` is set in the environment, reinstalled every
    purged showcase project on the next boot.

    One row per ``demo_id``, written when a demo project is deleted or purged
    and removed when a person installs that demo again. The boot installers
    read it and skip what it names; an explicit install from the app ignores
    it, because a person asking for the demo outranks the record of a person
    removing it. ``removed_project_id`` is the row that was removed and carries
    no foreign key, since the project it names may no longer exist. It is not
    called ``project_id`` on purpose: the demo purge sweeps every table with a
    ``project_id`` column for the purged ids, and it would take this record
    with the project it describes.
    """

    __tablename__ = "oe_projects_demo_tombstone"
    __table_args__ = (UniqueConstraint("demo_id", name="uq_oe_projects_demo_tombstone_demo_id"),)

    demo_id: Mapped[str] = mapped_column(String(100), nullable=False)
    removed_project_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # "archived" when the project was deleted, "purged" when demo data was removed.
    reason: Mapped[str] = mapped_column(String(16), nullable=False, default="archived")

    def __repr__(self) -> str:
        return f"<DemoProjectTombstone {self.demo_id} ({self.reason})>"
