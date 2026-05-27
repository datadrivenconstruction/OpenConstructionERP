# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Clash detection ORM models.

Tables:
    oe_clash_run          — one interference/clearance analysis over N models
    oe_clash_result       — a single clashing element pair within a run
    oe_clash_issue        — persistent identity of a clash across re-runs
    oe_clash_suppression  — per-project "ignore this signature" rule

A ``ClashResult`` snapshots the participating elements' name / discipline /
model so the result list stays meaningful even after the source model is
re-imported and the ``oe_bim_element`` rows are replaced. ``id`` /
``created_at`` / ``updated_at`` come from :class:`app.database.Base`.

A ``ClashIssue`` is the stable identity of a clash *across* re-runs —
keyed by the spatial+pair signature (see :mod:`clash.service`). Each
result row points at one issue; the issue tracks first-seen / last-seen
runs, the smart status (new / persisted / resolved / ignored / archived)
and the project-local server-assigned id (``CLASH-042``…).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class ClashRun(Base):
    """‌⁠‍A single clash-detection analysis scoped to one project.

    ``model_ids`` is the set of BIM models fed into the broad phase. With
    one model it is an *internal* (intra-model) clash; with two or more it
    is a *federated* coordination run. ``summary`` caches the rendered
    discipline matrix + per-status counts so the dashboard never has to
    re-aggregate thousands of result rows on every poll.
    """

    __tablename__ = "oe_clash_run"
    __table_args__ = (Index("ix_clash_run_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Optional free-text note so a run is identifiable in history
    # (scope / intent / reviewer). NULL on legacy rows.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON list[str] of bim_model UUIDs covered by this run.
    model_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    # Which interference an engine pass reports (Navisworks-style Type
    # selector): 'hard' (interpenetration only), 'clearance' (proximity
    # only) or 'both' (hard, then clearance for the non-hard pairs — the
    # historical behaviour and the back-compatible default).
    clash_type: Mapped[str] = mapped_column(String(16), nullable=False, default="both", server_default="both")
    # Federated noise filter: when true only cross-model pairs are
    # reported (Navisworks 'ignore clashes within the same file'). No
    # effect on a single-model run.
    ignore_same_model: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    # Hard-clash penetration threshold (metres). A pair counts as a hard
    # clash when the bounding-box interpenetration on its tightest axis
    # exceeds this value — filters out the cosmetic touch of coincident
    # faces (slab-on-wall) while still catching real interferences.
    tolerance_m: Mapped[float] = mapped_column(Float, nullable=False, default=0.01, server_default="0.01")
    # Clearance threshold (metres). 0 disables the soft pass; >0 also
    # reports element pairs that do NOT intersect but sit within this gap
    # (e.g. maintenance access around an AHU).
    clearance_m: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0.0")
    # 'cross_discipline' (skip same-discipline pairs — the common default),
    # 'all' (every pair), 'selected' (only discipline_filter pairs) or
    # 'selection_sets' (Navisworks-style Set A × Set B, e.g. walls×pipes).
    mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="cross_discipline",
        server_default="cross_discipline",
    )
    # Optional allow-list of [discipline_a, discipline_b] pairs to test.
    discipline_filter: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Navisworks-style selection sets (mode='selection_sets'). Each is
    # {"disciplines": [...], "element_types": [...]}; a pair is reported
    # iff one element matches set_a and the other matches set_b (strictly
    # cross). NULL for the other modes.
    set_a: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    set_b: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    element_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    total_clashes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Cached presentation payload: {"matrix": [...], "disciplines": [...],
    # "by_status": {...}, "by_type": {...}}.
    summary: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    # Wave A4 — per-discipline-pair tolerance overrides. Each entry is
    # ``{id, discipline_a, discipline_b, tolerance_m, severity_override,
    # enabled}`` (see :class:`ClashRule` in ``schemas.py``). The engine
    # consults this list during the broad phase: the first matching
    # enabled rule swaps in its ``tolerance_m`` for the run-wide value
    # (and stamps its ``severity_override`` onto the result). Order
    # matters — the first match wins. Defaults to ``[]`` so legacy
    # runs / fresh runs without rules behave exactly as before.
    rules: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    # Smart-issue spatial signature grid (millimetres). The clash signature
    # hashes the *bucketed* clash-box centroid so sub-mm geometry drift
    # between re-runs hashes to the same issue. 500 mm is a sane coordination
    # default (Navisworks-style "snap to nearest half-metre"); a tighter grid
    # makes the signature more discriminating (true motion → new issue), a
    # wider grid makes it more forgiving. Per-project / per-run override so
    # a coordinator can dial it for their model precision.
    spatial_grid_mm: Mapped[int] = mapped_column(Integer, nullable=False, default=500, server_default="500")
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    results: Mapped[list["ClashResult"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<ClashRun {self.name} ({self.total_clashes} clashes)>"


class ClashResult(Base):
    """‌⁠‍One clashing element pair (A↔B) inside a :class:`ClashRun`.

    ``status`` drives the review workflow:
    ``new`` → ``active`` → ``reviewed`` → ``approved`` / ``resolved`` /
    ``ignored``. ``approved`` means "intentional, accepted" and
    ``ignored`` means "false positive"; both drop out of the open count.
    """

    __tablename__ = "oe_clash_result"
    __table_args__ = (
        Index("ix_clash_result_run", "run_id"),
        Index("ix_clash_result_run_status", "run_id", "status"),
        Index("ix_clash_result_run_disc", "run_id", "a_discipline", "b_discipline"),
        Index("ix_clash_result_run_sig", "run_id", "signature"),
        # Smart-issue join key. Per-run because every result row is run-
        # scoped, and the diff/upsert paths always filter by run first.
        Index("ix_clash_result_run_sighash", "run_id", "signature_hash"),
        Index("ix_clash_result_issue", "issue_id"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_clash_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    a_element_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    b_element_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    a_stable_id: Mapped[str] = mapped_column(String(255), nullable=False)
    b_stable_id: Mapped[str] = mapped_column(String(255), nullable=False)
    a_name: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    b_name: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    a_discipline: Mapped[str] = mapped_column(String(64), nullable=False, default="Unassigned")
    b_discipline: Mapped[str] = mapped_column(String(64), nullable=False, default="Unassigned")
    # Snapshot of the participating elements' element_type (category /
    # family-type) so the result table can show "Wall ↔ Pipe" and stays
    # meaningful after the source model is re-imported. Empty when the
    # source element had no type.
    a_element_type: Mapped[str] = mapped_column(String(100), nullable=False, default="", server_default="")
    b_element_type: Mapped[str] = mapped_column(String(100), nullable=False, default="", server_default="")
    a_model_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    b_model_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    # Storey (level) index each element sits on — clustered from real
    # geometry Z by the geometry loader. NULL when the model has no GLB
    # or the loader did not resolve a level. Powers the ``level_matrix``
    # in the run summary, which is the meaningful coordination grid for
    # the common single-discipline intra-model run (where the
    # discipline×discipline matrix collapses to a useless 1×1).
    a_storey: Mapped[int | None] = mapped_column(Integer, nullable=True)
    b_storey: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 'hard' (interpenetration) or 'clearance' (proximity, no overlap).
    clash_type: Mapped[str] = mapped_column(String(16), nullable=False, default="hard", server_default="hard")
    # Tightest-axis interpenetration (m); 0 for clearance clashes.
    penetration_m: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0.0")
    # Gap between the two boxes (m); 0 for hard clashes.
    distance_m: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0.0")
    cx: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cy: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cz: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="new", server_default="new")
    # Triage urgency derived from the geometry the engine measured:
    # ``critical | high | medium | low``. For a hard clash it is keyed off
    # ``penetration_m`` (deeper = worse); for a clearance clash off the
    # gap-to-threshold ratio (a clearance violation is never critical).
    # Server default keeps every legacy row at a safe ``medium``.
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="medium", server_default="medium")
    # Stable, run-independent identity of the clashing element pair:
    # ``sha1(min(a,b)|max(a,b)|clash_type)[:16]`` over the two stable ids.
    # Lets triage (status / assignee / due date / comments) carry forward
    # across re-runs and powers the run-to-run comparison. Empty on legacy
    # rows; backfilled by the engine on every fresh result.
    signature: Mapped[str] = mapped_column(String(16), nullable=False, default="", server_default="")
    # Smart-issue identity. ``signature_hash`` is the full SHA-1 (40 hex)
    # of the canonical signature input — element-pair stable ids (or weak
    # ifc_class/material fallback for GUID-less DWG sources) + spatial-
    # grid-bucketed clash-box centroid + clash_type — so two re-runs of
    # the same physical interference hash to the same value even after
    # sub-mm geometry drift. ``issue_id`` points at the persistent
    # :class:`ClashIssue` for triage continuity.
    signature_hash: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    issue_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_clash_issue.id", ondelete="SET NULL"),
        nullable=True,
    )
    # ``strong`` (sha1 over real stable_ids — DDC/IFC) vs ``weak`` (sha1
    # over ifc_class|material|sorted_quantity_keys for GUID-less sources
    # like DWG). Surfaced in the UI as a confidence chip on the issue.
    signature_quality: Mapped[str] = mapped_column(String(8), nullable=False, default="strong", server_default="strong")
    # Tolerance (mm) used when this signature was computed. A re-run with
    # a different tolerance treats the same physical pair as a *new*
    # signature on purpose — coordinators want to see "this clash got
    # picked up because we tightened the threshold" as new work, not as
    # a persisted issue. Stored on the row so the diff can explain it.
    tolerance_at_signature_time_mm: Mapped[float] = mapped_column(
        Float, nullable=False, default=10.0, server_default="10.0"
    )
    assigned_to: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # ISO-8601 date ("YYYY-MM-DD") the clash is due to be resolved by.
    # Stored as a string to match this codebase's nullable-date column
    # convention (e.g. finance.Invoice.due_date). NULL = no deadline.
    due_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Threaded triage discussion. JSON list of
    # ``{"author": str, "author_id": str|null, "ts": ISO8601, "text": str}``
    # newest-prepended on carry-forward. Empty list on legacy rows.
    comments: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    # Wave A3 — collaboration. Watcher user-ids (strings) subscribed to
    # this clash; powers the fan-out on triage / comment events.
    # ``history`` is an additive audit trail of
    # ``{ts, actor, field, before, after}`` entries appended every time
    # a triage field changes (status / severity / assignee / due_date)
    # or a comment is added. Chronological order, never truncated.
    # Both default to an empty list so legacy rows + response shapes
    # stay safe across re-deploys.
    watchers: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    history: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    # Wave A2 — open-ended JSON envelope for engine-derived annotations
    # that are NOT authoritative state (the user-confirmed ``severity`` /
    # ``status`` / ``assigned_to`` columns remain the source of truth).
    # Currently carries ``severity_suggestion`` — a one-step-up advisory
    # bump on deep hard clashes (``penetration_m > 0.10``) that the UI
    # surfaces as a "Suggested: …" chip next to the badge. SQLAlchemy
    # reserves ``metadata`` on Base; the column is mapped as ``meta``.
    meta: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    # Wave A4 — run-scoped spatial cluster id assigned by the
    # post-detection DBSCAN over (cx, cy, cz). NULL marks DBSCAN noise
    # (a lone clash with no neighbours within ``eps_m``) or rows from
    # runs that pre-date clustering. Looked up against
    # :class:`ClashCluster` for the AI-derived label.
    cluster_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bcf_topic_guid: Mapped[str | None] = mapped_column(String(36), nullable=True)

    run: Mapped[ClashRun] = relationship(back_populates="results")

    def __repr__(self) -> str:
        return f"<ClashResult {self.a_name} x {self.b_name} ({self.clash_type})>"


class ClashCluster(Base):
    """‌⁠‍AI-derived label for a run-scoped spatial cluster of clashes.

    The DBSCAN pass groups clash centroids that sit within ``eps_m`` of
    each other into ``cluster_id`` buckets (per :class:`ClashRun`); this
    table caches a short human-style label for each non-noise bucket
    (e.g. "MEP × Structural — Level 3") plus its member count, so the
    review-table chip group renders without a per-render heuristic
    re-derivation. Noise rows (``cluster_id IS NULL``) have no row here.
    """

    __tablename__ = "oe_clash_cluster"
    __table_args__ = (
        Index("ix_clash_cluster_run", "run_id"),
        Index("ix_clash_cluster_run_cluster", "run_id", "cluster_id"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_clash_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Run-scoped integer cluster index produced by ``_cluster_results``.
    # Unique per run (the index above is non-unique deliberately — a
    # cluster can be re-labelled, and SQLite + alembic round-trips are
    # easier without a unique constraint we don't strictly need).
    cluster_id: Mapped[int] = mapped_column(Integer, nullable=False)
    # Short, human-style heuristic label (no LLM call) — derived from the
    # dominant discipline pair + storey of the cluster's members.
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    # Member count — number of clash results assigned to this cluster.
    # Stored so the chip count never requires a join against results.
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    def __repr__(self) -> str:
        return f"<ClashCluster {self.cluster_id} '{self.label}' n={self.size}>"


class ClashIssue(Base):
    """‌⁠‍Smart-issue identity of a clash across re-runs.

    A :class:`ClashResult` is *run-scoped* — the same physical interference
    re-appears as a fresh row on every re-run. The ``ClashIssue`` is the
    *persistent* identity behind those rows: keyed by the project-scoped
    ``signature_hash``, it tracks first-seen / last-seen runs, a smart
    status (new / persisted / resolved / ignored / archived), assignee,
    due date and the project-local server-assigned id (``CLASH-042``).

    Status transitions:

        new        — created this run, has matching result rows
        persisted  — present in N>1 consecutive runs
        resolved   — gone from the latest run (was present in the prior)
        ignored    — manually suppressed (see :class:`ClashSuppression`)
        archived   — absent for ``_ARCHIVE_AFTER_MISSING`` consecutive runs

    Each project has its own monotonic counter (``server_assigned_id``)
    so ids are stable + readable + scoped — the same number never appears
    on two projects.
    """

    __tablename__ = "oe_clash_issue"
    __table_args__ = (
        # The signature is unique per project — same signature on two
        # projects must resolve to two distinct issues (no cross-project
        # carry-over). Two indexes power the hot paths: lookup-by-hash on
        # upsert, status filter on the list endpoint.
        UniqueConstraint(
            "project_id",
            "signature_hash",
            name="uq_clash_issue_project_sig",
        ),
        UniqueConstraint(
            "project_id",
            "server_assigned_id",
            name="uq_clash_issue_project_serverid",
        ),
        Index("ix_clash_issue_project", "project_id"),
        Index("ix_clash_issue_project_status", "project_id", "status"),
        Index("ix_clash_issue_project_sig", "project_id", "signature_hash"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Full SHA-1 hex (40 chars) of the canonical signature input — see
    # :func:`app.modules.clash.service._compute_signature_hash`. Lower-case
    # by convention; the comparator is byte-exact.
    signature_hash: Mapped[str] = mapped_column(String(40), nullable=False)
    # Smart-issue lifecycle status. Independent from
    # :class:`ClashResult.status` (which tracks per-row triage state).
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="new", server_default="new")
    first_seen_run_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_clash_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    last_seen_run_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_clash_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Set when status flips to ``resolved`` (the run whose diff first
    # missed this signature). Stays populated through subsequent absent
    # runs; cleared on ``unsuppress`` / reopen if the issue resurfaces.
    resolved_run_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_clash_run.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Count of consecutive runs the signature has been absent from. Used
    # to drive the archive transition (≥ ``_ARCHIVE_AFTER_MISSING`` →
    # archived). Reset to 0 whenever the signature shows up again.
    missing_run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="medium", server_default="medium")
    # Project-local human readable id ("CLASH-042"). Monotonic per project.
    server_assigned_id: Mapped[str] = mapped_column(String(32), nullable=False, default="", server_default="")
    tags: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    # ``strong`` (real stable_ids) | ``weak`` (DWG-style GUID-less fallback).
    signature_quality: Mapped[str] = mapped_column(String(8), nullable=False, default="strong", server_default="strong")

    def __repr__(self) -> str:
        return f"<ClashIssue {self.server_assigned_id} {self.status}>"


class ClashSuppression(Base):
    """‌⁠‍A per-project "ignore this signature" rule.

    Suppressing a signature flips every matching :class:`ClashIssue` to
    ``ignored`` and prevents the same signature from re-surfacing as
    ``new`` in future runs (it stays ``ignored`` while the suppression
    is in place). Scoped to a single project — suppressing ``ABC...`` on
    Project A has zero effect on Project B even if a clash there carries
    the same hash.
    """

    __tablename__ = "oe_clash_suppression"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "signature_hash",
            name="uq_clash_suppression_project_sig",
        ),
        Index("ix_clash_suppression_project", "project_id"),
        Index(
            "ix_clash_suppression_project_sig",
            "project_id",
            "signature_hash",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    signature_hash: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    suppressed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    def __repr__(self) -> str:
        return f"<ClashSuppression {self.signature_hash[:8]} '{self.reason[:40]}'>"
