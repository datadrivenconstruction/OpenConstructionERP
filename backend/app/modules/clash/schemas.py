# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pydantic schemas for the clash detection module."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# Review-workflow states a clash can move through.
CLASH_STATUSES = ("new", "active", "reviewed", "approved", "resolved", "ignored")
# A clash that still needs attention (drives the "open clashes" KPI).
OPEN_STATUSES = ("new", "active", "reviewed")
# Geometry-derived triage urgency, worst → least. The ordinal index
# doubles as the sort key for ``order_by=severity``.
CLASH_SEVERITIES = ("critical", "high", "medium", "low")
SEVERITY_ORDER = {s: i for i, s in enumerate(CLASH_SEVERITIES)}


class ClashSelectionSet(BaseModel):
    """One side (A or B) of a coordination-tool-style selection-set clash.

    A *set* is a filter over the project's own elements: every element
    whose ``element_type`` is in :attr:`element_types`, whose
    ``discipline`` is in :attr:`disciplines`, whose grouping *category*
    is in :attr:`categories` **or** whose IFC entity is in
    :attr:`ifc_entities` belongs to the set (union - each chip the user
    adds widens it). Used only with ``mode="selection_sets"``: a pair is
    reported iff one element is in Set A and the other is in Set B
    (strictly cross, e.g. walls × pipes, no wall × wall noise).

    ``element_types`` is the indexed ``element_type`` column;
    ``categories`` is the source-native category (RVT category /
    ``ifc_class``, falling back to the element type); ``ifc_entities`` is
    the raw IFC entity (``IfcWall``, …) from the element ``properties``
    - only meaningful for IFC-sourced models. ``properties`` is the
    open-ended ``{property_key: [allowed_values]}`` map: an element is
    also in the set when, for *any* key, its source-native
    ``properties[key]`` (string-coerced + trimmed) is one of the listed
    values - so the picker can facet by *any* element property, not just
    the four built-ins. The extra lists/maps keep older payloads (which
    only carried ``disciplines``/``element_types``) forward-compatible.
    """

    disciplines: list[str] = Field(default_factory=list, max_length=200)
    element_types: list[str] = Field(default_factory=list, max_length=2000)
    categories: list[str] = Field(default_factory=list, max_length=2000)
    ifc_entities: list[str] = Field(default_factory=list, max_length=2000)
    properties: dict[str, list[str]] = Field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not (
            self.disciplines
            or self.element_types
            or self.categories
            or self.ifc_entities
            or any(self.properties.values())
        )


# The kind of interference an engine pass looks for. Mirrors the
# Coordination-tool clash "Type" rule selector:
#   * ``hard``      - only report true geometric interpenetration
#                     (triangles actually intersect beyond ``tolerance_m``).
#   * ``clearance`` - only report proximity: pairs that do NOT intersect
#                     but sit within ``clearance_m`` (e.g. maintenance
#                     access around an AHU). Hard hits are suppressed.
#   * ``both``      - report hard interpenetration AND, for non-hard
#                     pairs, clearance violations (the legacy behaviour).
CLASH_TYPES = ("hard", "clearance", "both")


class ClashRule(BaseModel):
    """Wave A4 - one per-discipline-pair tolerance override row.

    A *rule* is the coordination-tool-style "rules tab" entry: a coordination
    discipline pair (e.g. ``Structural`` × ``Mechanical``) plus a
    discipline-specific tolerance the engine should use *instead* of the
    run-wide :attr:`ClashRun.tolerance_m` when both elements of a
    candidate pair fall on that axis. The pair match is symmetric:
    ``(A, B)`` and ``(B, A)`` resolve to the same rule.

    ``severity_override`` lets a coordinator stamp every result for the
    pair with a fixed severity (e.g. "Pipe × Beam is always *high*"),
    bypassing the geometry-derived ladder. Empty / ``None`` → keep the
    engine value. ``enabled=False`` keeps the row visible but inert -
    the engine ignores it (handy for parking a tuning iteration without
    losing the row). ``id`` is a stable client-generated identifier so
    React lists can ``key`` cleanly; the backend never indexes it.
    """

    id: str = Field(..., max_length=64)
    discipline_a: str = Field(..., max_length=64)
    discipline_b: str = Field(..., max_length=64)
    tolerance_m: float = Field(..., ge=0.0, le=10.0)
    severity_override: str | None = Field(default=None, max_length=16)
    enabled: bool = Field(default=True)


class ClashRuleList(BaseModel):
    """Replace the full rule set of a run (PATCH /runs/{id}/rules/ body).

    A flat list keeps the PATCH idempotent - clients always send the
    full desired state. Order matters: the first matching enabled rule
    wins (``_apply_rules`` short-circuits on the first match).
    """

    rules: list[ClashRule] = Field(default_factory=list, max_length=500)


class ClashClusterRead(BaseModel):
    """Wave A4 - one spatial cluster of clashes within a run.

    Returned by ``GET /runs/{id}/clusters/`` so the frontend chip group
    can render ``"Cluster N · <label> (n)"`` without a per-result join.
    ``label`` is the heuristic ``"<disc_a> × <disc_b> - Level <s>"``
    string the service derives from the cluster's member rows.

    ``dominant_disciplines`` is the unique discipline pair the label was
    built from (used by the chip palette to colour clusters by trade);
    ``storey`` is the dominant storey index when the cluster's member
    rows resolved one, else ``None``. Both are advisory - the UI never
    falls over on absence.
    """

    model_config = ConfigDict(from_attributes=True)

    cluster_id: int
    label: str = ""
    size: int = 0
    dominant_disciplines: list[str] = Field(default_factory=list, max_length=2)
    storey: int | None = None


class ClashFalsePositiveRequest(BaseModel):
    """Mark a clash as a false positive - Wave A4 FP feedback loop.

    ``reason`` is a short, free-text triage note the coordinator picks
    from a small picker (or types). Persisted to the result's history
    audit trail so the FP-suggestion engine can later mine the corpus
    for shared discipline pairs.
    """

    reason: str = Field(..., min_length=1, max_length=500)


class ClashRuleSuggestion(BaseModel):
    """A proposed rule, derived from this run's recorded false positives.

    Returned by ``GET /runs/{id}/rule-suggestions/`` when ``N+`` false
    positives share a discipline pair. ``rule`` is the proposed
    :class:`ClashRule` row (with a fresh ``id``); ``reason`` explains
    *why* the system suggests it ("3 false positives on Mechanical ×
    Structural - bump tolerance to 0.05 m"). Empty when there is no
    confident proposal.
    """

    rule: ClashRule | None = None
    reason: str = ""
    fp_count: int = 0


class ClashRunCreate(BaseModel):
    """Configure + launch a clash run."""

    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(
        default=None,
        max_length=2000,
        description="Free-text note so a run is identifiable in history (scope, intent, reviewer). Optional.",
    )
    model_ids: list[uuid.UUID] = Field(
        ...,
        min_length=1,
        description="BIM models to test. One = intra-model; many = federated.",
    )
    clash_type: str = Field(
        default="both",
        description="hard | clearance | both - which interference an "
        "engine pass reports (coordination-tool-style Type selector). "
        "'hard' = interpenetration only; 'clearance' = proximity only; "
        "'both' = hard, then clearance for the non-hard pairs.",
    )
    ignore_same_model: bool = Field(
        default=False,
        description="Federated coordination noise filter: when true a "
        "pair is only reported if its two elements come from "
        "*different* BIM models (coordination tools' 'ignore clashes within the "
        "same file'). Skipped - has no effect - on a single-model run.",
    )
    tolerance_m: float = Field(
        default=0.01,
        ge=0.0,
        le=10.0,
        description="Hard-clash interpenetration threshold in metres.",
    )
    clearance_m: float = Field(
        default=0.0,
        ge=0.0,
        le=50.0,
        description="Proximity threshold in metres (0 disables the soft pass).",
    )
    mode: str = Field(
        default="cross_discipline",
        description="cross_discipline | all | selected | selection_sets",
    )
    discipline_filter: list[list[str]] | None = Field(
        default=None,
        description="Optional allow-list of [discipline_a, discipline_b] pairs.",
    )
    set_a: ClashSelectionSet | None = Field(
        default=None,
        description="Selection Set A (mode=selection_sets) - e.g. all walls.",
    )
    set_b: ClashSelectionSet | None = Field(
        default=None,
        description="Selection Set B (mode=selection_sets) - e.g. all pipes.",
    )
    carry_forward: bool = Field(
        default=True,
        description="Carry triage (status, assignee, due date, comments) "
        "forward from the most recent prior completed run of this "
        "project that shares a model, matching clashes by their stable "
        "signature. Keeps coordination state across re-runs.",
    )
    rules: list[ClashRule] = Field(
        default_factory=list,
        max_length=500,
        description="Wave A4 - per-discipline-pair tolerance overrides "
        "the engine consults during the broad phase. The first matching "
        "enabled rule (symmetric on the pair) swaps in its tolerance "
        "and stamps the result severity. Empty → run-wide tolerance "
        "alone (legacy behaviour).",
    )


# Grouping parameters the Set A / Set B pickers can be faceted by.
# ``discipline``/``type`` exist for every model; ``category`` and
# ``ifc_entity`` only when the selected models actually carry that data
# (RVT category / IFC entity in element ``properties``). In addition to
# these four built-ins, ``group_by`` also accepts the open-ended form
# ``property:<key>`` (the literal ``property:`` prefix + a raw element
# property key, e.g. ``property:FireRating``) - the facet is then the
# distinct values of that property across the selected models. The keys
# the UI can offer are advertised in
# :attr:`ClashCategoriesResponse.available_properties`.
CLASH_GROUP_BY = ("discipline", "type", "category", "ifc_entity")
# Marker prefix for the open-ended per-property grouping form.
CLASH_PROPERTY_GROUP_PREFIX = "property:"


class ClashModelOption(BaseModel):
    """One BIM model in the run-config model picker (lightweight projection).

    Surfaced by ``GET /projects/{id}/models`` so the Set A / Set B picker
    can list the project's models without pulling the full BIM-model row.
    ``name`` falls back to the model filename then a generic label;
    ``element_count`` is coerced to a non-negative int; ``status`` is the
    model's processing state (``None`` when the source carries none). A
    fixed schema (rather than a bare ``dict``) keeps the response typed in
    the OpenAPI contract and stops ORM internals leaking onto the wire.
    """

    id: str
    name: str
    element_count: int = 0
    status: str | None = None


class ClashCategoryItem(BaseModel):
    """One distinct grouping value with its element count."""

    value: str
    count: int


class ClashPropertyFacet(BaseModel):
    """One enumerable element-property key with its element coverage.

    ``key`` is a raw scalar property key present on the selected models'
    elements; ``count`` is how many bounding-box-carrying elements carry
    that key. The UI uses this list to build the "group by any property"
    selector - request ``group_by=property:<key>`` to facet by it.
    """

    key: str
    count: int


class ClashCategoriesResponse(BaseModel):
    """Facets for building the Set A / Set B pickers (one project).

    ``groups`` is the facet list for the *requested* grouping parameter
    (``group_by`` - one of the four built-ins or ``property:<key>``).
    ``element_types`` / ``disciplines`` are kept for backward
    compatibility (older frontends read them directly).
    ``available_group_by`` lists only the *built-in* parameters that
    actually have data across the selected models, so the UI never
    offers an empty "IfcEntity" grouping on a pure-RVT project.
    ``available_properties`` enumerates the open-ended element-property
    keys the UI may additionally group by (always populated regardless
    of ``group_by`` so the selector can be built up-front).
    """

    group_by: str = "type"
    groups: list[ClashCategoryItem] = Field(default_factory=list)
    available_group_by: list[str] = Field(default_factory=list)
    available_properties: list[ClashPropertyFacet] = Field(default_factory=list)
    element_types: list[ClashCategoryItem] = Field(default_factory=list)
    disciplines: list[ClashCategoryItem] = Field(default_factory=list)


class ClashComment(BaseModel):
    """One threaded triage note on a clash result.

    ``reply_to`` carries the ``ts`` of a parent comment when this one is
    a reply (Wave A3 threading). It is purely additive - legacy flat
    comments simply omit it (``None``) and render at the top level.
    """

    author: str = ""
    author_id: str | None = None
    ts: str = ""
    text: str = ""
    # ``ts`` of the parent comment when this is a reply. ``None`` (the
    # default) → top-level comment.
    reply_to: str | None = None


class ClashHistoryEntry(BaseModel):
    """One audit-log entry on a clash result (Wave A3 activity tab).

    Appended every time a triage field changes (status / severity /
    assigned_to / due_date) or a new comment is added. ``actor`` is the
    user id of the caller; ``ts`` is ISO-8601 UTC. ``before`` / ``after``
    are best-effort string snapshots - ``None`` when there was no prior
    value or the event has no natural pair (e.g. ``comment_add``).
    """

    ts: str = ""
    actor: str = ""
    field: str = ""
    before: str | None = None
    after: str | None = None


class ClashResultResponse(BaseModel):
    """A single clashing pair."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    a_element_id: uuid.UUID
    b_element_id: uuid.UUID
    a_stable_id: str
    b_stable_id: str
    a_name: str
    b_name: str
    a_discipline: str
    b_discipline: str
    a_element_type: str = ""
    b_element_type: str = ""
    # Building-system snapshot (MEP system / family / type name) powering
    # the ``discipline_system`` grouping dimension. Empty when the source
    # element carried no system metadata; default keeps older payloads /
    # backends type-checking.
    a_element_system: str = ""
    b_element_system: str = ""
    a_model_id: uuid.UUID
    b_model_id: uuid.UUID
    a_storey: int | None = None
    b_storey: int | None = None
    clash_type: str
    penetration_m: float
    distance_m: float
    cx: float
    cy: float
    cz: float
    status: str
    severity: str = "medium"
    signature: str = ""
    assigned_to: str | None
    due_date: str | None = None
    comments: list[ClashComment] = Field(default_factory=list)
    # Wave A3 - collaboration state. ``watchers`` is the user-id list
    # subscribed to this clash (fan-out target on triage/comment events).
    # ``history`` is the audit trail rendered in the DetailPanel Activity
    # tab. Both default to empty so legacy payloads / older backends
    # still validate cleanly.
    watchers: list[str] = Field(default_factory=list)
    history: list[ClashHistoryEntry] = Field(default_factory=list)
    # Wave A2 - open-ended advisory annotations (engine-derived,
    # non-authoritative). Currently ``{"severity_suggestion": "<sev>"}``
    # on deep hard clashes - the UI shows a "Suggested" chip. Defaults to
    # ``{}`` so older payloads always type-check.
    meta: dict = Field(default_factory=dict)
    # Wave A4 - run-scoped spatial cluster id (DBSCAN over centroids).
    # ``None`` marks DBSCAN noise / legacy rows.
    cluster_id: int | None = None
    bcf_topic_guid: str | None


class ClashAddComment(BaseModel):
    """Append a triage note. ``author``/``author_id`` are optional -
    when omitted they resolve from the request's auth context.

    ``reply_to`` is the ``ts`` of an existing comment when this one
    threads under it (Wave A3). ``None``/omitted → top-level comment.
    """

    text: str = Field(..., min_length=1, max_length=5000)
    author: str | None = Field(default=None, max_length=255)
    author_id: str | None = Field(default=None, max_length=64)
    reply_to: str | None = Field(default=None, max_length=64)


class ClashResultUpdate(BaseModel):
    """Triage a clash - status, severity, assignee, due date and/or a new comment."""

    status: str | None = Field(default=None)
    # Reclassify the coordination urgency. The engine seeds a value from
    # geometry; the user has final say (Wave A2 bulk-set / accept-suggestion).
    severity: str | None = Field(default=None)
    assigned_to: str | None = Field(default=None)
    due_date: str | None = Field(default=None, max_length=20)
    add_comment: ClashAddComment | None = Field(default=None)


class ClashBulkResultUpdate(BaseModel):
    """Apply ONE triage change to many clashes at once (review-table bulk bar).

    Exactly one of ``status`` / ``severity`` / ``assigned_to`` is set per
    request (the toolbar issues one action at a time); the others stay
    ``None`` and are left untouched. Replaces the per-row PATCH fan-out so a
    large selection updates in a single round-trip.
    """

    result_ids: list[uuid.UUID] = Field(
        ...,
        min_length=1,
        max_length=25_000,
        description="The clashes to update (run-scoped; foreign ids are ignored).",
    )
    status: str | None = Field(default=None)
    severity: str | None = Field(default=None)
    assigned_to: str | None = Field(default=None)


class ClashBulkUpdateResponse(BaseModel):
    """Outcome of a bulk triage write - how many rows actually changed."""

    updated: int = 0
    requested: int = 0


class ClashMatrixCell(BaseModel):
    """One discipline×discipline cell of the clash matrix."""

    a: str
    b: str
    count: int
    open_count: int


class ClashLevelMatrixCell(BaseModel):
    """One storey×storey cell of the level matrix.

    Same shape/convention as :class:`ClashMatrixCell` so the frontend can
    render it with the identical grid component - only the axis keys are
    integer storey indices instead of discipline strings.
    """

    a: int
    b: int
    count: int
    open_count: int


# Multi-dimensional grouping dimensions the summary endpoint can produce.
#   * ``discipline_pair`` - discipline×discipline matrix (the default, the
#     historical ``matrix``).
#   * ``level`` - count of clashes per storey index (1-D breakdown).
#   * ``level_discipline`` - discipline×discipline matrix *per* storey.
#   * ``discipline_system`` - discipline·system × discipline·system matrix
#     (only meaningful when elements carry building-system metadata).
CLASH_GROUPING_DIMENSIONS = (
    "discipline_pair",
    "level",
    "level_discipline",
    "discipline_system",
)


class ClashGroupCount(BaseModel):
    """One labelled bucket in a 1-D grouping (e.g. clashes per level)."""

    key: str
    count: int
    open_count: int


class ClashLevelDisciplineGroup(BaseModel):
    """The discipline×discipline matrix scoped to a single storey level."""

    level: int
    cells: list[ClashMatrixCell] = Field(default_factory=list)


class ClashGroupedSummary(BaseModel):
    """Multi-dimensional grouping of a run's clashes for the review table.

    Exactly one of the optional payloads is populated for the requested
    ``dimension``; the rest stay empty. ``dimension`` echoes back the
    requested grouping so the UI can render the matching component without
    re-deriving it.
    """

    dimension: str = "discipline_pair"
    # ``discipline_pair`` (default) - the flat discipline×discipline grid.
    disciplines: list[str] = Field(default_factory=list)
    matrix: list[ClashMatrixCell] = Field(default_factory=list)
    # ``level`` - one bucket per storey index (key is the int as a string).
    levels: list[ClashGroupCount] = Field(default_factory=list)
    # ``level_discipline`` - a discipline matrix per storey.
    level_disciplines: list[ClashLevelDisciplineGroup] = Field(default_factory=list)
    # ``discipline_system`` - discipline·system × discipline·system grid.
    systems: list[str] = Field(default_factory=list)
    system_matrix: list[ClashMatrixCell] = Field(default_factory=list)
    # Whether any clash in the run resolved a building system - lets the UI
    # hide the ``discipline_system`` option when there is no data for it.
    has_system_data: bool = False


class ClashRunSummary(BaseModel):
    """Rendered dashboard payload cached on the run.

    ``matrix`` is the discipline×discipline grid (correct for true
    multi-discipline federated uploads). ``level_matrix`` is the
    storey×storey grid (the meaningful coordination view for the common
    single-discipline intra-model run). Both follow the same cell shape.
    """

    disciplines: list[str] = Field(default_factory=list)
    matrix: list[ClashMatrixCell] = Field(default_factory=list)
    storeys: list[int] = Field(default_factory=list)
    level_matrix: list[ClashLevelMatrixCell] = Field(default_factory=list)
    by_status: dict[str, int] = Field(default_factory=dict)
    by_type: dict[str, int] = Field(default_factory=dict)
    by_severity: dict[str, int] = Field(default_factory=dict)


class ClashRunResponse(BaseModel):
    """A clash run with its cached summary."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str | None = None
    model_ids: list[uuid.UUID]
    clash_type: str = "both"
    ignore_same_model: bool = False
    tolerance_m: float
    clearance_m: float
    mode: str
    discipline_filter: list[list[str]] | None
    set_a: ClashSelectionSet | None = None
    set_b: ClashSelectionSet | None = None
    status: str
    error: str | None
    element_count: int
    total_clashes: int
    summary: ClashRunSummary
    # Wave A4 - per-discipline-pair tolerance overrides on this run.
    # Always present on the response (empty list when no rules were
    # configured), so the rule editor never has to special-case absence.
    rules: list[ClashRule] = Field(default_factory=list)
    created_by: str
    created_at: datetime
    completed_at: datetime | None


class ClashRunListItem(BaseModel):
    """Lightweight run row for the runs list (no result rows)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None = None
    clash_type: str = "both"
    status: str
    model_ids: list[uuid.UUID]
    element_count: int
    total_clashes: int
    created_at: datetime
    completed_at: datetime | None


class ClashResultPage(BaseModel):
    """Paginated clash-result slice."""

    items: list[ClashResultResponse]
    total: int
    offset: int
    limit: int


class ClashBCFExportRequest(BaseModel):
    """Export selected clashes (or all open) as native BCF topics."""

    result_ids: list[uuid.UUID] | None = Field(
        default=None,
        description="Specific clashes to export. Omit → all OPEN clashes.",
    )


class ClashBCFExportResponse(BaseModel):
    """Outcome of a BCF export."""

    exported: int
    skipped: int


class ClashBCFImportResponse(BaseModel):
    """Outcome of a BCF round-trip import.

    ``matched`` is the number of topics whose recomputed signature
    matched an existing :class:`ClashResult`; ``unmatched`` is the
    number of topics with no signature hit (logged, ignored). ``errors``
    is the count of structural parse problems the codec reported.
    """

    matched: int
    unmatched: int
    errors: int = 0


class ClashWatchResponse(BaseModel):
    """Watcher-list snapshot returned by watch / unwatch."""

    watchers: list[str] = Field(default_factory=list)
    watching: bool = False


class ClashResultSummary(BaseModel):
    """Compact clash row used by the run-to-run comparison."""

    id: uuid.UUID
    a_name: str
    b_name: str
    clash_type: str
    severity: str
    penetration_m: float
    distance_m: float
    status: str
    assigned_to: str | None = None


class ClashPersistentPair(BaseModel):
    """A clash present in both the base and the current run (same signature)."""

    current: ClashResultSummary
    base: ClashResultSummary


class ClashCompareStats(BaseModel):
    """Counts behind a run-to-run comparison."""

    new: int
    resolved: int
    persistent: int
    base_total: int
    current_total: int


class ClashCompareResponse(BaseModel):
    """Diff of the current run against a base run, partitioned by signature.

    ``new`` = clashes whose signature appears only in the current run;
    ``resolved`` = signatures that were in the base run but are gone now;
    ``persistent`` = signatures present in both (paired current↔base).
    """

    new: list[ClashResultSummary] = Field(default_factory=list)
    resolved: list[ClashResultSummary] = Field(default_factory=list)
    persistent: list[ClashPersistentPair] = Field(default_factory=list)
    stats: ClashCompareStats


class ClashApplyRuleRequest(BaseModel):
    """Wave A4 - POST body for ``/runs/{id}/apply-rule-suggestion``.

    Identifies the discipline pair the coordinator wants to widen plus
    the proposed tolerance. The endpoint appends a fresh
    :class:`ClashRule` row to ``run.rules`` and re-evaluates the run's
    existing results: any hard clash on the pair whose ``penetration_m``
    now sits at or below ``tolerance_m`` is flipped to ``status='ignored'``
    (with an audit-trail entry). Symmetric on the pair.
    """

    discipline_a: str = Field(..., max_length=64, min_length=1)
    discipline_b: str = Field(..., max_length=64, min_length=1)
    tolerance_m: float = Field(..., ge=0.0, le=10.0)


class ClashApplyRuleResponse(BaseModel):
    """Outcome of ``POST /runs/{id}/apply-rule-suggestion``.

    ``rule_added`` is ``False`` only when the new rule would have been a
    duplicate of an existing entry (symmetric pair + same tolerance); the
    re-evaluation pass still runs and ``results_affected`` is the number
    of clash rows whose status was flipped to ``ignored``.
    """

    rule_added: bool
    results_affected: int


class ClashDisciplinePairStat(BaseModel):
    """One discipline×discipline coordination grid cell - KPI projection.

    Mirrors :class:`ClashMatrixCell` but adds ``open_share`` (``open_count
    / count``, 0..1) so the dashboard can render the "top clashing pairs"
    table without recomputing the ratio client-side. Zero ``count`` is
    impossible (the aggregator skips empty cells), so ``open_share`` is
    always well-defined.
    """

    a: str
    b: str
    count: int
    open_count: int
    open_share: float


# ── Smart-issue / signature schemas (v41) ───────────────────────────────

# Smart-issue lifecycle status (independent of per-row ClashResult.status).
CLASH_ISSUE_STATUSES = ("new", "persisted", "resolved", "ignored", "archived")
CLASH_ISSUE_PRIORITIES = ("low", "medium", "high", "critical")
CLASH_SIGNATURE_QUALITIES = ("strong", "weak")


class ClashIssueRead(BaseModel):
    """A single smart-issue row (signature-scoped, project-scoped).

    The smart issue is the *persistent* identity of a clash across re-runs
    - see :class:`app.modules.clash.models.ClashIssue` for the lifecycle.
    ``member_count`` is the number of :class:`ClashResult` rows currently
    linked to this issue (across every run of the project); the list
    endpoint computes it with one extra COUNT query so the UI can render
    it as a chip without fetching the rows.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    signature_hash: str
    status: str
    first_seen_run_id: uuid.UUID
    last_seen_run_id: uuid.UUID
    resolved_run_id: uuid.UUID | None = None
    missing_run_count: int = 0
    assignee_id: uuid.UUID | None = None
    due_date: str | None = None  # ISO date "YYYY-MM-DD" (None if unset)
    priority: str = "medium"
    server_assigned_id: str = ""
    tags: list[str] = Field(default_factory=list)
    signature_quality: str = "strong"
    member_count: int = 0
    created_at: datetime
    updated_at: datetime


class ClashIssuePage(BaseModel):
    """Paginated list of smart issues for the project-wide issues view."""

    items: list[ClashIssueRead] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 0


class ClashSuppressRequest(BaseModel):
    """POST body for ``/clash/issues/{issue_id}/suppress``.

    ``reason`` is a short, free-text triage note (1..500 chars). Persisted
    on :class:`ClashSuppression.reason`. Empty reasons are rejected at the
    schema level - suppressions must always carry an audit trail.
    """

    reason: str = Field(..., min_length=1, max_length=500)


class ClashBulkSuppressRequest(BaseModel):
    """POST body for ``…/runs/{run_id}/results/suppress`` (bulk).

    Suppress the smart issues behind a selection of review-table rows in
    one round-trip - backs the table's "Suppress selected" action. The
    selection is keyed by :class:`ClashResult` id (what the table holds);
    the server maps those to the underlying issue signatures and
    suppresses them. ``reason`` follows the same 1..500-char audit-trail
    rule as the single-issue path; foreign / unknown ids are silently
    dropped and reported back in ``skipped_ids`` (IDOR-safe), never raised.
    """

    result_ids: list[uuid.UUID] = Field(
        ...,
        min_length=1,
        max_length=25_000,
        description="The clashes to suppress (run-scoped; foreign ids are ignored).",
    )
    reason: str = Field(..., min_length=1, max_length=500)


class ClashBulkSuppressResponse(BaseModel):
    """Outcome of a bulk suppression, reported in result-id terms.

    ``suppressed_ids`` are the selected results whose issue flipped to
    ``ignored``; ``skipped_ids`` are results that did not belong to the
    run, had no smart issue yet, or whose issue was dropped (e.g. missing
    signature). The counts mirror the two lists.
    """

    suppressed_ids: list[uuid.UUID] = Field(default_factory=list)
    skipped_ids: list[uuid.UUID] = Field(default_factory=list)
    suppressed_count: int = 0
    skipped_count: int = 0


class ClashRunDiff(BaseModel):
    """Smart-issue diff counts for ``/clash/runs/{run_id}/diff``.

    Computed by diffing the run's results against the project's known
    smart issues. ``new`` = signatures first seen this run; ``persisted``
    = signatures present in both this run and the previous; ``resolved``
    = signatures present in the previous run but absent now; ``reopened``
    = signatures whose issue had ``status='resolved'`` but resurfaced;
    ``ignored`` = signatures whose issue is suppressed.
    """

    new: int = 0
    persisted: int = 0
    resolved: int = 0
    reopened: int = 0
    ignored: int = 0


class ClashKpiResponse(BaseModel):
    """Dashboard projection for ``GET /runs/{id}/kpi``.

    All counts respect every clash in the run (no pagination). ``mttr_hours``
    is the average wall-clock delta from a row's first ``status='new'``
    history entry (or ``created_at`` fallback) to its first transition
    *out* of ``new`` into ``resolved`` - ``None`` when no row has a
    qualifying transition yet. ``top_clashing_pairs`` is the top five
    discipline pairs by total ``count`` (ties broken by ``open_count``
    desc, then pair alphabetic for determinism).
    """

    total: int
    by_status: dict[str, int] = Field(default_factory=dict)
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_type: dict[str, int] = Field(default_factory=dict)
    by_discipline_pair: list[ClashDisciplinePairStat] = Field(default_factory=list)
    mttr_hours: float | None = None
    top_clashing_pairs: list[ClashDisciplinePairStat] = Field(default_factory=list)


# ── Persistent clash profiles (item #23) ────────────────────────────────


class ClashProfileBase(BaseModel):
    """Shared run-configuration fields for a clash profile.

    A *profile* snapshots every run parameter a coordinator tunes (minus
    the model selection) so the same coordination policy can be relaunched
    on a fresh model set. Bounds mirror :class:`ClashRunCreate` so a
    profile can always be applied to a real run without re-validation.
    """

    clash_type: str = Field(default="both", description="hard | clearance | both")
    ignore_same_model: bool = Field(default=False)
    tolerance_m: float = Field(default=0.01, ge=0.0, le=10.0)
    clearance_m: float = Field(default=0.0, ge=0.0, le=50.0)
    mode: str = Field(default="cross_discipline", description="cross_discipline | all | selected | selection_sets")
    discipline_filter: list[list[str]] | None = Field(default=None)
    set_a: ClashSelectionSet | None = Field(default=None)
    set_b: ClashSelectionSet | None = Field(default=None)
    rules: list[ClashRule] = Field(default_factory=list, max_length=500)
    spatial_grid_mm: int = Field(default=500, ge=100, le=5000)


class ClashProfileCreate(ClashProfileBase):
    """Create a named clash profile (template library entry)."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class ClashProfileUpdate(BaseModel):
    """Patch a clash profile - every field optional (partial update).

    Only the fields actually supplied are written; ``None`` means "leave
    untouched" (so ``description=None`` cannot blank an existing note via
    this path - clearing is out of scope for the MVP).
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    clash_type: str | None = Field(default=None)
    ignore_same_model: bool | None = Field(default=None)
    tolerance_m: float | None = Field(default=None, ge=0.0, le=10.0)
    clearance_m: float | None = Field(default=None, ge=0.0, le=50.0)
    mode: str | None = Field(default=None)
    discipline_filter: list[list[str]] | None = Field(default=None)
    set_a: ClashSelectionSet | None = Field(default=None)
    set_b: ClashSelectionSet | None = Field(default=None)
    rules: list[ClashRule] | None = Field(default=None, max_length=500)
    spatial_grid_mm: int | None = Field(default=None, ge=100, le=5000)


class ClashProfileRead(ClashProfileBase):
    """A persisted clash profile."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime


class ClashProfileApplyRequest(BaseModel):
    """Launch a new clash run from a profile.

    The profile supplies every engine parameter; the caller supplies the
    models to test plus an optional run name. Carry-forward defaults on so
    triage state continues across re-runs (same as a normal run).
    """

    model_ids: list[uuid.UUID] = Field(..., min_length=1)
    name: str | None = Field(default=None, max_length=255)
    carry_forward: bool = Field(default=True)


# ── Cluster → coordination action (cross-module link) ────────────────────

# Where a clash group can be turned into a tracked work item. ``punchlist``
# spawns a site-actionable punch item; ``task`` spawns a coordination task
# in the project task board. Both keep a back-link to the originating run /
# cluster so the action and the geometry stay traceable.
CLASH_ACTION_TARGETS = ("punchlist", "task")


class ClashGroupActionProposal(BaseModel):
    """AI-augmented draft for turning a clash cluster into a work item.

    Returned by ``GET /runs/{id}/clusters/{cid}/action-proposal``. The
    engine *proposes* a title, body, priority and assignee from the
    cluster's geometry + triage state; the coordinator reviews and confirms
    (editing any field) before the work item is created. ``confidence`` is a
    0..1 score on how well-formed the proposal is (high when the cluster has
    a clear dominant discipline pair + severity, lower for mixed clusters) -
    surfaced in the UI as a chip so a human never auto-applies a weak guess.
    """

    cluster_id: int
    target: str = Field(default="punchlist", description="punchlist | task")
    title: str
    description: str
    priority: str = Field(default="medium", description="low | medium | high | critical")
    suggested_assignee: str | None = None
    member_count: int = 0
    dominant_disciplines: list[str] = Field(default_factory=list, max_length=2)
    storey: int | None = None
    max_severity: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    # True when these members already produced a linked work item; the UI
    # disables the confirm button and shows the existing link instead.
    already_linked: bool = False
    existing_action_id: str | None = None
    existing_action_target: str | None = None


class ClashGroupActionRequest(BaseModel):
    """Confirm creation of a work item from a clash cluster (human step).

    Every field is optional and overrides the matching value from the
    proposal - the coordinator edits the AI draft, then confirms. ``target``
    decides which module receives the new row. ``advance_status`` (default
    on) moves the cluster's still-``new`` members to ``reviewed`` so the
    review board reflects that a human has acted on them.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    target: str = Field(default="punchlist", description="punchlist | task")
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    priority: str | None = Field(default=None, pattern=r"^(low|medium|high|critical)$")
    assigned_to: str | None = Field(default=None, max_length=36)
    due_date: str | None = Field(default=None, max_length=40)
    advance_status: bool = Field(default=True)


class ClashGroupActionResponse(BaseModel):
    """Result of creating a work item from a clash cluster.

    ``action_id`` is the new punch item / task id; ``action_target`` echoes
    the module it landed in. ``results_linked`` is how many clash rows now
    carry the back-link, ``results_advanced`` how many were moved to
    ``reviewed`` by the same call. ``created`` is False (idempotent no-op)
    when the cluster already had a linked work item - ``action_id`` then
    points at the pre-existing one.
    """

    created: bool = True
    action_id: str
    action_target: str
    cluster_id: int
    results_linked: int = 0
    results_advanced: int = 0


# ── Interference risk matrix (clash x schedule correlation) ──────────────────
# Statuses the correlation can assign to a clash, worst-first.
CLASH_RISK_STATUSES = ("imminent", "upcoming", "no-overlap", "no-schedule-data")


class ClashRiskMatrixItem(BaseModel):
    """One clash correlated against the schedule.

    Money fields (``cost_impact``, ``risk_score``) are serialised as strings
    so the Decimal value survives the wire without binary-float rounding.
    ``days_until_overlap`` is signed (negative once the shared window has
    opened) and ``None`` when the trades never overlap or a schedule link is
    missing; ``gap_days`` is the days between the two windows when disjoint.
    """

    clash_id: uuid.UUID
    severity: str
    trade_a: str
    trade_b: str
    cost_impact: str
    status: str
    overlaps: bool
    overlap_days: int
    days_until_overlap: int | None = None
    gap_days: int | None = None
    window_a_start: str | None = None
    window_a_end: str | None = None
    window_b_start: str | None = None
    window_b_end: str | None = None
    risk_score: str
    explanation: str


class ClashRiskMatrixResponse(BaseModel):
    """Ranked interference risk list for a project's open clashes.

    ``counts`` carries a tally per status plus ``total``. ``generated_for`` is
    the reference date the correlation was run against (ISO date), so the
    caller can see which ``today`` drove the imminent / upcoming split.
    """

    project_id: uuid.UUID
    currency: str
    horizon_days: int
    generated_for: str
    counts: dict[str, int]
    items: list[ClashRiskMatrixItem]
