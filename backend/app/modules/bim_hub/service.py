"""‌⁠‍BIM Hub service​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ - business logic for BIM data management.

Stateless service layer. Handles:
- BIM model CRUD
- Element bulk import (for CAD pipeline results)
- BOQ link management
- Quantity map rules application
- Model diff calculation (compare elements by stable_id + geometry_hash)
"""

import fnmatch
import logging
import shutil
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.events import event_bus
from app.modules.bim_hub import file_storage as bim_file_storage
from app.modules.bim_hub.models import (
    BIMElement,
    BIMElementGroup,
    BIMFederation,
    BIMFederationModel,
    BIMModel,
    BIMModelDiff,
    BIMQuantityMap,
    BOQElementLink,
)
from app.modules.bim_hub.repository import (
    BIMElementRepository,
    BIMFederationRepository,
    BIMModelDiffRepository,
    BIMModelRepository,
    BIMQuantityMapRepository,
    BOQElementLinkRepository,
)
from app.modules.bim_hub.schemas import (
    BIMElementCreate,
    BIMElementGroupCreate,
    BIMElementGroupResponse,
    BIMElementGroupUpdate,
    BIMModelCreate,
    BIMModelSchemaResponse,
    BIMModelUpdate,
    BIMQuantityMapCreate,
    BIMQuantityMapUpdate,
    BOQElementLinkCreate,
    FederationCreate,
    FederationDiffResponse,
    FederationFullResponse,
    FederationHealthResponse,
    FederationMemberHealth,
    FederationModelAdd,
    FederationModelResponse,
    FederationResponse,
    FederationSnapshot,
    FederationSnapshotMember,
    FederationSnapshotMemberDelta,
    FederationTypeTreeClass,
    FederationTypeTreeMember,
    FederationTypeTreeResponse,
    FederationUpdate,
    QuantityMapApplyRequest,
    QuantityMapApplyResult,
)
from app.modules.boq.models import BOQ, Position

logger = logging.getLogger(__name__)
_logger_events = logging.getLogger(__name__ + ".events")


async def _safe_publish(
    name: str,
    data: dict[str, Any],
    source_module: str = "oe_bim_hub",
) -> None:
    """‌⁠‍Publish event safely - ignores MissingGreenlet errors with SQLite async."""
    try:
        event_bus.publish_detached(name, data, source_module=source_module)
    except Exception:
        _logger_events.debug("Event publish skipped (SQLite async): %s", name)


def _humanise_ifc_class(ifc_class: str) -> str:
    """Best-effort human label for an IfcClass string.

    ``"IfcWall"`` → ``"Wall"``, ``"IfcDuctSegment"`` → ``"Duct Segment"``.
    Anything that does not look like an IfcXxx class name is returned
    verbatim. The display_name is intentionally NOT i18n'd here: the
    federation type tree is a developer-facing surface that maps a
    canonical IFC class to a fallback label; the FE is free to translate
    by class id (``ifc_class``) later without re-fetching.
    """
    if not ifc_class:
        return "Unclassified"
    raw = ifc_class[3:] if ifc_class.startswith("Ifc") else ifc_class
    if not raw:
        return ifc_class
    # Insert space before each interior capital: "DuctSegment" → "Duct Segment".
    out_chars: list[str] = []
    for idx, ch in enumerate(raw):
        if idx > 0 and ch.isupper() and not raw[idx - 1].isupper():
            out_chars.append(" ")
        out_chars.append(ch)
    return "".join(out_chars)


# ── Federation health helpers (v7.x) ────────────────────────────────────────
#
# Pure, side-effect-free classification so the logic is unit-testable
# without a DB. ``BIMModel`` rows are passed in already-resolved.

# A ready, non-empty member is "stale" when its last update lags the
# freshest member of the federation by more than this many days. Tuned to
# a fortnight: a coordination set that re-uploads one discipline but not
# the others within two weeks is the classic stale-member scenario.
FEDERATION_STALENESS_THRESHOLD_DAYS = 14

# Statuses we treat as a successful conversion. Anything else that is not
# an explicit failure is treated as still-processing.
_READY_MODEL_STATUSES = frozenset({"ready", "complete", "completed", "done"})
_FAILED_MODEL_STATUSES = frozenset({"failed", "error", "errored"})


def _classify_federation_member(
    *,
    member_id: uuid.UUID,
    bim_model_id: uuid.UUID,
    discipline: str,
    model: BIMModel | None,
    newest_update: datetime | None,
) -> FederationMemberHealth:
    """Classify a single federation member into a health state.

    Pure function - takes the already-resolved ``BIMModel`` (or ``None``
    when the link dangles) and the federation's freshest update time, and
    returns the member's health report. The ordering of checks is the
    severity ladder: missing > failed > processing > empty > stale > ready.
    """
    if model is None:
        return FederationMemberHealth(
            member_id=member_id,
            bim_model_id=bim_model_id,
            model_name=f"model-{str(bim_model_id)[:8]}",
            discipline=discipline,
            state="missing",
            model_status=None,
            element_count=0,
            last_updated=None,
            staleness_days=None,
            warnings=["model_deleted"],
        )

    status_norm = (model.status or "").strip().lower()
    last_updated = model.updated_at
    staleness_days: int | None = None
    if last_updated is not None and newest_update is not None:
        staleness_days = max(0, (newest_update - last_updated).days)

    if status_norm in _FAILED_MODEL_STATUSES:
        return FederationMemberHealth(
            member_id=member_id,
            bim_model_id=bim_model_id,
            model_name=model.name,
            discipline=discipline,
            state="failed",
            model_status=model.status,
            element_count=model.element_count,
            last_updated=last_updated,
            staleness_days=staleness_days,
            warnings=["conversion_failed"],
        )

    if status_norm not in _READY_MODEL_STATUSES:
        return FederationMemberHealth(
            member_id=member_id,
            bim_model_id=bim_model_id,
            model_name=model.name,
            discipline=discipline,
            state="processing",
            model_status=model.status,
            element_count=model.element_count,
            last_updated=last_updated,
            staleness_days=staleness_days,
            warnings=["still_processing"],
        )

    if model.element_count <= 0:
        return FederationMemberHealth(
            member_id=member_id,
            bim_model_id=bim_model_id,
            model_name=model.name,
            discipline=discipline,
            state="empty",
            model_status=model.status,
            element_count=0,
            last_updated=last_updated,
            staleness_days=staleness_days,
            warnings=["no_elements"],
        )

    if staleness_days is not None and staleness_days > FEDERATION_STALENESS_THRESHOLD_DAYS:
        return FederationMemberHealth(
            member_id=member_id,
            bim_model_id=bim_model_id,
            model_name=model.name,
            discipline=discipline,
            state="stale",
            model_status=model.status,
            element_count=model.element_count,
            last_updated=last_updated,
            staleness_days=staleness_days,
            warnings=["stale_relative_to_set"],
        )

    return FederationMemberHealth(
        member_id=member_id,
        bim_model_id=bim_model_id,
        model_name=model.name,
        discipline=discipline,
        state="ready",
        model_status=model.status,
        element_count=model.element_count,
        last_updated=last_updated,
        staleness_days=staleness_days,
        warnings=[],
    )


# Severity ladder for the federation's headline state - the worst member
# wins. Index 0 is best.
_HEALTH_SEVERITY_ORDER: list[str] = [
    "ready",
    "stale",
    "empty",
    "processing",
    "failed",
    "missing",
]


def _aggregate_federation_health(
    federation_id: uuid.UUID,
    members: list[FederationMemberHealth],
    spread_days: int | None,
) -> FederationHealthResponse:
    """Roll member reports up into a federation-level health summary.

    Pure function so the aggregation (counts, score, worst-state) is
    testable without touching the DB.
    """
    counts: dict[str, int] = dict.fromkeys(_HEALTH_SEVERITY_ORDER, 0)
    for m in members:
        counts[m.state] = counts.get(m.state, 0) + 1
    total = len(members)
    ready = counts.get("ready", 0)
    score = round(ready / total, 2) if total else 0.0
    # Worst (= highest-severity) state present is the headline; an empty
    # member set has no worst state, so it reports ``no_members``.
    overall: str = "no_members" if total == 0 else "ready"
    for state in reversed(_HEALTH_SEVERITY_ORDER):
        if counts.get(state, 0) > 0:
            overall = state
            break
    return FederationHealthResponse(
        federation_id=federation_id,
        member_count=total,
        ready_count=ready,
        processing_count=counts.get("processing", 0),
        failed_count=counts.get("failed", 0),
        stale_count=counts.get("stale", 0),
        missing_count=counts.get("missing", 0),
        empty_count=counts.get("empty", 0),
        total_elements=sum(m.element_count for m in members),
        overall_state=overall,  # type: ignore[arg-type]
        score=score,
        spread_days=spread_days,
        members=members,
    )


def diff_federation_snapshots(
    federation_id: uuid.UUID,
    old: FederationSnapshot,
    new: FederationSnapshot,
) -> FederationDiffResponse:
    """Pure three-way diff between two federation snapshots.

    Bucketing is by ``bim_model_id``:

    * present only in ``new`` -> ``added``
    * present only in ``old`` -> ``removed``
    * present in both, element_count differs -> ``changed``
    * present in both, element_count identical -> ``unchanged``

    Side-effect free and DB-free so it can be unit-tested directly.
    """
    old_by_id = {m.bim_model_id: m for m in old.members}
    new_by_id = {m.bim_model_id: m for m in new.members}

    added = [m for mid, m in new_by_id.items() if mid not in old_by_id]
    removed = [m for mid, m in old_by_id.items() if mid not in new_by_id]

    changed: list[FederationSnapshotMemberDelta] = []
    unchanged: list[FederationSnapshotMember] = []
    for mid, new_m in new_by_id.items():
        old_m = old_by_id.get(mid)
        if old_m is None:
            continue
        if new_m.element_count != old_m.element_count:
            changed.append(
                FederationSnapshotMemberDelta(
                    bim_model_id=mid,
                    model_name=new_m.model_name,
                    discipline=new_m.discipline,
                    element_count_delta=new_m.element_count - old_m.element_count,
                    old_element_count=old_m.element_count,
                    new_element_count=new_m.element_count,
                )
            )
        else:
            unchanged.append(new_m)

    # Stable ordering for deterministic UI + snapshot tests.
    added.sort(key=lambda m: (m.discipline, m.model_name))
    removed.sort(key=lambda m: (m.discipline, m.model_name))
    changed.sort(key=lambda d: (-abs(d.element_count_delta), d.model_name))
    unchanged.sort(key=lambda m: (m.discipline, m.model_name))

    total_drift = new.total_elements - old.total_elements

    return FederationDiffResponse(
        federation_id=federation_id,
        old_captured_at=old.captured_at,
        new_captured_at=new.captured_at,
        added=added,
        removed=removed,
        changed=changed,
        unchanged=unchanged,
        total_element_drift=total_drift,
    )


def _safe_float(value: Any) -> float | None:
    """‌⁠‍Coerce a Position string/Decimal/None money or quantity to float.

    Position.quantity / unit_rate / total are stored as strings to avoid
    SQLite REAL precision loss. Aggregation endpoints surface them as JSON
    floats for the viewer - ``None`` stays ``None``, empty stays ``None``.
    """
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError, InvalidOperation):
        return None


# ── Canonical unit normalisation (E-XMOD-020) ───────────────────────────────
#
# The BIM→BOQ picker and CAD QTO importer historically wrote the
# superscript Unicode units ``m²`` / ``m³`` straight onto the new
# ``Position.unit``. Downstream validation rules (RateVsBenchmark,
# MeasurementConsistency, CPWD, Sekisan, …) key their allow-lists on the
# ASCII tokens ``m2`` / ``m3`` ONLY, so a BIM-sourced volume position
# silently escaped the unrealistic-rate / consistency guards. We fix this
# authoritatively at the *write boundary* of this module: every
# ``Position.unit`` this service persists is normalised to a single
# canonical ASCII token. (The validation rule file is owned by another
# pass and must NOT be edited - normalising here makes both sides agree.)
_SUPERSCRIPT_UNIT_MAP = {
    "²": "2",  # SUPERSCRIPT TWO  (m²)
    "³": "3",  # SUPERSCRIPT THREE (m³)
}


def normalize_unit_token(raw: Any) -> str:
    """Fold a unit string to its canonical ASCII form.

    ``m³`` → ``m3``, ``m²`` → ``m2``, ``M3`` → ``m3``. Whitespace is
    trimmed and the token is lower-cased so ``"M2"``/``"m²"``/``" m2 "``
    all collapse to ``"m2"``. Empty / ``None`` → ``""`` (caller decides
    the fallback - we never invent a unit here). Unknown units pass
    through lower-cased and superscript-folded; rejecting a real-world
    unit would be worse UX than letting the estimator edit post-import.
    """
    if raw is None:
        return ""
    text = str(raw).strip()
    if not text:
        return ""
    for sup, ascii_digit in _SUPERSCRIPT_UNIT_MAP.items():
        text = text.replace(sup, ascii_digit)
    text = text.lower()
    # BUG-D-TKC-NEW-02 - German / European BOQ conventions abbreviate
    # count units WITH a trailing period: "Stk.", "St.", "Stck.", "Pos.".
    # Folding the trailing period(s)/whitespace here (the single unit
    # write/compare boundary) makes "Stk." collapse to "stk" so it hits
    # the same _COUNT_UNITS branch as "Stk" / "Stück" instead of falling
    # through to the "unknown unit → untouched" branch. No real unit
    # token legitimately ends in '.', so this is safe for geometric
    # units (m2/m3/lfm) too.
    text = text.rstrip(". \t")
    return text


# Units that denote a *count of discrete items* (not a geometric
# dimension). Linking BIM geometry to a count position must NOT
# overwrite the estimator's hand-entered piece count with a volume /
# area / weight - see E-XMOD-003.
_COUNT_UNITS: frozenset[str] = frozenset(
    {
        "pcs",
        "pc",
        "nr",
        "no",
        "nos",
        "ea",
        "each",
        "unit",
        "units",
        "item",
        "items",
        # German / DIN / GAEB count units. ``normalize_unit_token`` now
        # strips a trailing period so "Stk." → "stk"; the dotted spellings
        # are kept here too as belt-and-braces (D-TKC-NEW-02).
        "st",
        "st.",
        "stk",
        "stk.",
        "stck",
        "stck.",
        "stück",
        "stück.",
        "stueck",
        "stueck.",
        "u",
        "lsum",
        "ls",
        "psch",
        "pausch",
        "pa",
        "ens",
        "set",
        "sets",
        "kpl",
    }
)


# Sentinel key used by ``list_elements_with_links`` to signal that a
# BIM-model validation report exists. Routers can detect "report ran but
# element passed" vs "no report at all" by checking this key's presence.
_VALIDATION_REPORT_SENTINEL: uuid.UUID = uuid.UUID(int=0)


def _fold_progress_onto_elements(
    elements: list[BIMElement],
    latest_pct_by_position: dict[uuid.UUID, float],
) -> dict[uuid.UUID, float]:
    """Fold per-position progress percentages onto their linked elements.

    For each element we look at every linked BOQ position
    (``element.boq_links``), pick the MAX of the latest percentages we
    know about, and key it by the element id. Elements with no linked
    position - or whose positions all lack a recorded percentage - are
    omitted entirely so the caller can treat "absent" as "no data"
    (neutral grey in the BIM "By progress" overlay).

    Pure / deterministic: no DB access, no I/O. The ``boq_links`` must
    already be loaded on each element (the listing query eager-loads
    them via ``selectinload``).
    """
    out: dict[uuid.UUID, float] = {}
    if not latest_pct_by_position:
        return out
    for elem in elements:
        best: float | None = None
        for lnk in elem.boq_links or []:
            pct = latest_pct_by_position.get(lnk.boq_position_id)
            if pct is None:
                continue
            if best is None or pct > best:
                best = pct
        if best is not None:
            out[elem.id] = best
    return out


def _fold_progress_date_onto_elements(
    elements: list[BIMElement],
    latest_pct_by_position: dict[uuid.UUID, float],
    date_by_position: dict[uuid.UUID, str | None],
) -> dict[uuid.UUID, str]:
    """Fold the recorded-date of each element's *headline* progress entry.

    Mirrors :func:`_fold_progress_onto_elements`: for each element we pick
    the linked BOQ position with the MAX latest percentage (the headline the
    overlay colours by) and emit that position's recorded date keyed by the
    element id. Elements with no linked progress - or whose winning position
    has no recorded date - are omitted, so the caller treats "absent" as
    "no date to show".

    Pure / deterministic: no DB access, no I/O. ``date_by_position`` values
    are already ISO-8601 strings (or ``None``); the winning position is
    decided by its pct so the date shown always belongs to the same entry
    as the displayed percentage.
    """
    out: dict[uuid.UUID, str] = {}
    if not latest_pct_by_position:
        return out
    for elem in elements:
        best_pct: float | None = None
        best_date: str | None = None
        for lnk in elem.boq_links or []:
            pct = latest_pct_by_position.get(lnk.boq_position_id)
            if pct is None:
                continue
            if best_pct is None or pct > best_pct:
                best_pct = pct
                best_date = date_by_position.get(lnk.boq_position_id)
        if best_pct is not None and best_date:
            out[elem.id] = best_date
    return out


async def _strip_orphaned_bim_links(
    session: AsyncSession,
    deleted_element_ids: list[str],
    project_id: uuid.UUID | None,
) -> None:
    """Strip ``deleted_element_ids`` from every JSON-array link site.

    Three cross-module link types denormalise BIM element ids into JSON
    array columns instead of FK tables (Task.bim_element_ids,
    Activity.bim_element_ids, Requirement.metadata_["bim_element_ids"]).
    The FK-based link types (BOQElementLink, DocumentBIMLink) clean
    themselves up via ``ondelete='CASCADE'``; the JSON ones do not, so
    deleted element ids would otherwise leak forever and confuse the
    BIM viewer's "linked tasks/activities/requirements" panel as well
    as any reverse-query helper.

    Runs INLINE on the caller's session - must NOT open a new session.
    The previous implementation lived in an event subscriber that
    opened ``async_session_factory()``, but under SQLite write-lock
    contention (the upstream service is mid-transaction) the new
    session deadlocked.  Sharing the active session means the cleanup
    runs inside the same transaction so a failure rolls back atomically
    with the upstream delete, and there is no lock contention.

    The actual filter happens in Python because neither SQLite nor
    PostgreSQL share a portable JSON-array-contains/remove operator
    we can use for cross-dialect bulk updates.  ``project_id`` scopes
    the candidate set so the scan stays bounded.
    """
    if not deleted_element_ids:
        return

    targets: set[str] = {str(eid) for eid in deleted_element_ids if eid}
    if not targets:
        return

    # Defer imports so this helper can be loaded by the bim_hub module
    # without dragging tasks/schedule/requirements into the import graph
    # at module level (the loader auto-imports modules in dependency order
    # and bim_hub's manifest doesn't list these as hard dependencies).
    from app.modules.requirements.models import Requirement, RequirementSet
    from app.modules.schedule.models import Activity, Schedule
    from app.modules.tasks.models import Task

    # ── Tasks ──────────────────────────────────────────────────────────
    try:
        task_stmt = select(Task)
        if project_id is not None:
            task_stmt = task_stmt.where(Task.project_id == project_id)
        task_rows = (await session.execute(task_stmt)).scalars().all()
        cleaned_tasks = 0
        for task in task_rows:
            ids = task.bim_element_ids or []
            if not isinstance(ids, list):
                continue
            kept = [x for x in ids if str(x) not in targets]
            if len(kept) != len(ids):
                task.bim_element_ids = kept
                cleaned_tasks += 1
        if cleaned_tasks:
            logger.info(
                "Orphan cleanup: stripped %d element id(s) from %d task(s)",
                len(targets),
                cleaned_tasks,
            )
    except Exception:  # noqa: BLE001 - best-effort, never break upstream
        logger.warning(
            "Orphan cleanup failed for tasks (project=%s)",
            project_id,
            exc_info=True,
        )

    # ── Activities ─────────────────────────────────────────────────────
    try:
        act_stmt = select(Activity).where(Activity.bim_element_ids.isnot(None))
        if project_id is not None:
            act_stmt = act_stmt.join(Schedule, Activity.schedule_id == Schedule.id).where(
                Schedule.project_id == project_id
            )
        act_rows = (await session.execute(act_stmt)).scalars().all()
        cleaned_activities = 0
        for activity in act_rows:
            ids = activity.bim_element_ids
            if not isinstance(ids, list):
                continue
            kept = [x for x in ids if str(x) not in targets]
            if len(kept) != len(ids):
                activity.bim_element_ids = kept
                cleaned_activities += 1
        if cleaned_activities:
            logger.info(
                "Orphan cleanup: stripped %d element id(s) from %d activity(s)",
                len(targets),
                cleaned_activities,
            )
    except Exception:  # noqa: BLE001
        logger.warning(
            "Orphan cleanup failed for activities (project=%s)",
            project_id,
            exc_info=True,
        )

    # ── Requirements ───────────────────────────────────────────────────
    try:
        req_stmt = select(Requirement)
        if project_id is not None:
            req_stmt = req_stmt.join(RequirementSet, Requirement.requirement_set_id == RequirementSet.id).where(
                RequirementSet.project_id == project_id
            )
        req_rows = (await session.execute(req_stmt)).scalars().all()
        cleaned_reqs = 0
        for req in req_rows:
            meta = dict(req.metadata_ or {})
            ids = meta.get("bim_element_ids")
            if not isinstance(ids, list):
                continue
            kept = [x for x in ids if str(x) not in targets]
            if len(kept) != len(ids):
                meta["bim_element_ids"] = kept
                req.metadata_ = meta
                cleaned_reqs += 1
        if cleaned_reqs:
            logger.info(
                "Orphan cleanup: stripped %d element id(s) from %d requirement(s)",
                len(targets),
                cleaned_reqs,
            )
    except Exception:  # noqa: BLE001
        logger.warning(
            "Orphan cleanup failed for requirements (project=%s)",
            project_id,
            exc_info=True,
        )

    await session.flush()


# On-disk directory for BIM geometry files (original.{ext}, geometry.dae,
# dataframe.xlsx, …). Matches the layout used by ``bim_hub.router`` which
# writes to ``<repo>/data/bim/{project_id}/{model_id}/``.
#
# ``service.py`` → ``app/modules/bim_hub/service.py`` → parents[4] == repo root
_BIM_DATA_DIR = Path(__file__).resolve().parents[4] / "data" / "bim"


class BIMHubService:
    """Business logic for BIM Hub operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.model_repo = BIMModelRepository(session)
        self.element_repo = BIMElementRepository(session)
        self.link_repo = BOQElementLinkRepository(session)
        self.qmap_repo = BIMQuantityMapRepository(session)
        self.diff_repo = BIMModelDiffRepository(session)

    # ── BIM Model CRUD ───────────────────────────────────────────────────────

    async def create_model(
        self,
        data: BIMModelCreate,
        user_id: str | None = None,
    ) -> BIMModel:
        """Create a new BIM model record."""
        model = BIMModel(
            project_id=data.project_id,
            name=data.name,
            discipline=data.discipline,
            model_format=data.model_format,
            version=data.version,
            import_date=data.import_date,
            status=data.status,
            bounding_box=data.bounding_box,
            original_file_id=data.original_file_id,
            canonical_file_path=data.canonical_file_path,
            parent_model_id=data.parent_model_id,
            created_by=user_id,
            metadata_=data.metadata,
        )
        model = await self.model_repo.create(model)
        logger.info("BIM model created: %s (project=%s)", data.name, data.project_id)
        return model

    async def get_model(self, model_id: uuid.UUID) -> BIMModel:
        """Get a BIM model by ID. Raises 404 if not found."""
        model = await self.model_repo.get(model_id)
        if model is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BIM model not found",
            )
        return model

    async def list_models(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[BIMModel], int]:
        """List BIM models for a project."""
        return await self.model_repo.list_for_project(project_id, offset=offset, limit=limit)

    async def update_model(
        self,
        model_id: uuid.UUID,
        data: BIMModelUpdate,
    ) -> BIMModel:
        """Update a BIM model's fields."""
        await self.get_model(model_id)  # 404 check

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if not fields:
            return await self.get_model(model_id)

        await self.model_repo.update_fields(model_id, **fields)
        updated = await self.model_repo.get(model_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BIM model not found after update",
            )
        logger.info("BIM model updated: %s (fields=%s)", model_id, list(fields.keys()))
        return updated

    async def delete_model(self, model_id: uuid.UUID) -> None:
        """Delete a BIM model, all its elements, and stored geometry blobs.

        CASCADE on the DB foreign key handles element deletion automatically.
        Orphaned BIM-link references in JSON columns (Task.bim_element_ids,
        Activity.bim_element_ids, Requirement.metadata_["bim_element_ids"])
        are cleaned lazily - callers that resolve these ids already tolerate
        missing elements, and a future background sweeper can purge stale
        references.  This keeps the delete O(1) w.r.t. element count so
        models with 7 000+ elements don't time out the HTTP request.

        Blob cleanup is best-effort - a failure to remove the blobs MUST
        NOT fail the delete operation (the DB row is already gone and the
        orphan sweeper can pick up any stragglers later).
        """
        model = await self.get_model(model_id)  # 404 check
        project_id = model.project_id

        # Publish a single model-level delete event instead of per-element
        # events.  Vector-store subscribers can bulk-purge by model_id.
        await _safe_publish(
            "bim_hub.model.deleted",
            {
                "model_id": str(model_id),
                "project_id": str(project_id) if project_id else None,
            },
        )

        # CASCADE handles element rows; no need to fetch element ids.
        await self.model_repo.delete(model_id)
        logger.info("BIM model deleted: %s  (elements removed via CASCADE)", model_id)

        # NOTE: _strip_orphaned_bim_links is intentionally skipped here.
        # For large models (7000+ elements) it loaded every Task, Activity,
        # and Requirement row in the project and filtered in Python, causing
        # 30+ second timeouts.  JSON-array link sites tolerate dangling ids
        # gracefully (the BIM viewer already ignores missing elements), and
        # a periodic orphan-sweep job can clean them up in the background.

        # Best-effort blob cleanup (after DB delete so we never strand
        # files belonging to a still-live DB row).  Routed through the
        # storage backend so S3 deployments work transparently.
        await bim_file_storage.delete_model_blobs(project_id, model_id)

    async def cleanup_orphan_bim_files(self) -> dict[str, Any]:
        """Scan ``data/bim/`` and remove directories with no matching DB row.

        Walks ``data/bim/{project_id}/{model_id}/`` and deletes any model
        directory whose ``model_id`` is not present in the ``oe_bim_models``
        table. Also removes empty ``project_id`` directories.

        Returns a summary with the count of removed model dirs and bytes
        reclaimed. Called from the admin-only
        ``POST /api/v1/bim_hub/cleanup-orphans/`` endpoint.
        """
        if not _BIM_DATA_DIR.is_dir():
            return {"scanned": 0, "removed_models": 0, "removed_projects": 0, "bytes_freed": 0}

        # Load all known model ids from the DB in a single query.
        from app.modules.bim_hub.models import BIMModel

        result = await self.session.execute(select(BIMModel.id))
        known_ids = {str(row[0]) for row in result.all()}

        scanned = 0
        removed_models = 0
        removed_projects = 0
        bytes_freed = 0
        removed_details: list[str] = []

        for project_dir in _BIM_DATA_DIR.iterdir():
            if not project_dir.is_dir():
                continue
            for model_dir in project_dir.iterdir():
                if not model_dir.is_dir():
                    continue
                scanned += 1
                if model_dir.name in known_ids:
                    continue
                # Orphan - compute size then remove.
                try:
                    size = sum(f.stat().st_size for f in model_dir.rglob("*") if f.is_file())
                except OSError:
                    size = 0
                try:
                    shutil.rmtree(model_dir, ignore_errors=True)
                    removed_models += 1
                    bytes_freed += size
                    removed_details.append(str(model_dir))
                    logger.info("Orphan BIM dir removed: %s (%d bytes)", model_dir, size)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to remove orphan %s: %s", model_dir, exc)
            # Drop now-empty project directories.
            try:
                if not any(project_dir.iterdir()):
                    project_dir.rmdir()
                    removed_projects += 1
            except OSError:
                pass

        return {
            "scanned": scanned,
            "removed_models": removed_models,
            "removed_projects": removed_projects,
            "bytes_freed": bytes_freed,
            "removed": removed_details,
        }

    async def cleanup_stale_processing(
        self,
        project_id: uuid.UUID,
        max_age_hours: int = 1,
    ) -> int:
        """Remove models stuck in 'processing' with 0 elements older than max_age_hours."""
        count = await self.model_repo.cleanup_stale_processing(project_id, max_age_hours=max_age_hours)
        if count:
            logger.info(
                "Cleaned up %d stale processing model(s) for project %s",
                count,
                project_id,
            )
        return count

    async def get_model_schema(self, model_id: uuid.UUID) -> BIMModelSchemaResponse:
        """Harvest distinct element types and property key/value pairs from a
        model's element set (RFC 24).

        Caps each property's distinct-value list at 1000 (alpha-sorted) and
        flags truncation so the UI can show a "show more" hint. Null / empty
        property values are excluded from the value lists. Elements without
        an ``element_type`` do not contribute a type but still contribute
        properties.
        """
        model = await self.model_repo.get(model_id)
        if model is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BIM model not found",
            )

        fetch_limit = max(int(getattr(model, "element_count", 0) or 0), 50_000)
        elements, _total = await self.element_repo.list_for_model(
            model_id,
            offset=0,
            limit=fetch_limit,
        )

        distinct_types: set[str] = set()
        property_values: dict[str, set[str]] = {}
        cap = 1000

        for el in elements:
            etype = getattr(el, "element_type", None)
            if etype:
                distinct_types.add(etype)
            props = getattr(el, "properties", None) or {}
            if not isinstance(props, dict):
                continue
            for key, value in props.items():
                if value is None:
                    property_values.setdefault(key, set())
                    continue
                str_val = str(value).strip()
                if not str_val:
                    continue
                property_values.setdefault(key, set()).add(str_val)

        property_keys: dict[str, list[str]] = {}
        property_keys_truncated: dict[str, bool] = {}
        for key, values in property_values.items():
            sorted_vals = sorted(values)
            truncated = len(sorted_vals) > cap
            property_keys[key] = sorted_vals[:cap]
            property_keys_truncated[key] = truncated

        return BIMModelSchemaResponse(
            distinct_types=sorted(distinct_types),
            property_keys=property_keys,
            property_keys_truncated=property_keys_truncated,
            available_quantities=["area_m2", "volume_m3", "length_m", "weight_kg", "count"],
            element_count=len(elements),
        )

    # ── BIM Elements ─────────────────────────────────────────────────────────

    async def list_elements(
        self,
        model_id: uuid.UUID,
        *,
        element_type: str | None = None,
        storey: str | None = None,
        discipline: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> tuple[list[BIMElement], int]:
        """List elements for a model with optional filters."""
        await self.get_model(model_id)  # 404 check
        return await self.element_repo.list_for_model(
            model_id,
            element_type=element_type,
            storey=storey,
            discipline=discipline,
            offset=offset,
            limit=limit,
        )

    async def list_elements_with_links(
        self,
        model_id: uuid.UUID,
        *,
        element_type: str | None = None,
        storey: str | None = None,
        discipline: str | None = None,
        group_id: uuid.UUID | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> tuple[
        list[BIMElement],
        int,
        dict[uuid.UUID, list[dict[str, Any]]],
        dict[uuid.UUID, list[dict[str, Any]]],
        dict[uuid.UUID, list[dict[str, Any]]],
        dict[uuid.UUID, list[dict[str, Any]]],
        dict[uuid.UUID, list[dict[str, Any]]],
        dict[uuid.UUID, list[dict[str, Any]]],
        dict[uuid.UUID, float],
        dict[uuid.UUID, str],
    ]:
        """List elements AND their BOQ / Document / Task / Activity / Requirement briefs.

        Returns ``(elements, total, boq_links_by_element_id,
        doc_links_by_element_id, task_links_by_element_id,
        activity_briefs_by_element_id, requirement_briefs_by_element_id,
        validation_summaries_by_element_id, current_pct_by_element_id,
        current_pct_date_by_element_id)`` where each brief is a plain dict
        with the fields expected by the corresponding Pydantic brief schema.

        ``current_pct_date_by_element_id`` maps each element id to the
        ISO-8601 recorded date of the headline progress entry (the same
        entry whose percentage lands in ``current_pct_by_element_id``), so
        the viewer can show "65% as of 2026-06-01" when an element is
        selected in the "By progress" overlay. Absent when the element has
        no linked progress or the winning entry carries no recorded date.

        ``current_pct_by_element_id`` maps each element id to the latest
        ``percent_complete`` (0-100) of the BOQ position(s) it is linked
        to.  When an element links to several positions we take the MAX of
        their latest percentages, because a human reading a "by progress"
        3D overlay reads the most-advanced linked work as the element's
        headline state.  Elements with no linked position (or with linked
        positions that have no ProgressEntry yet) are simply absent from
        the dict, so the viewer paints them neutral grey.

        BOQ briefs match ``BOQElementLinkBrief`` (id, boq_position_id,
        boq_position_ordinal, boq_position_description, link_type, confidence).

        Document briefs match ``DocumentLinkBrief`` (id, document_id,
        document_name, document_category, link_type, confidence).

        Task briefs match ``bim_hub.schemas.TaskBrief`` (id, project_id,
        title, status, task_type, due_date). Tasks are denormalised - each
        ``Task`` row carries a JSON ``bim_element_ids`` array - so we load
        all project tasks once and filter in Python. This is cross-dialect
        safe and correct for the bounded sizes we expect (< a few thousand
        tasks per project).

        Activity briefs match ``bim_hub.schemas.ActivityBrief`` (id, name,
        start_date, end_date, status, percent_complete). Activities are
        loaded through ``oe_schedule_schedule`` for the model's project and
        filtered in Python on their ``bim_element_ids`` JSON array - same
        rationale as tasks.

        This avoids an N+1 by issuing:
            1. A single SELECT on BIMElement with ``selectinload(boq_links)``.
            2. A single SELECT on Position for all distinct linked position ids.
            3. A single SELECT joining ``oe_documents_bim_link`` → ``oe_documents_document``
               filtered by the element ids in the current page.
            4. A single SELECT on Task for all tasks in the project containing
               the model.
            5. A single SELECT on Activity joined to Schedule for all
               activities in the model's project.
        """
        # Local imports to avoid import-time cycles between bim_hub and
        # documents / tasks / schedule / requirements.
        from app.modules.documents.models import Document, DocumentBIMLink
        from app.modules.requirements.models import Requirement, RequirementSet
        from app.modules.schedule.models import Activity, Schedule
        from app.modules.tasks.models import Task

        model = await self.get_model(model_id)  # 404 check + need project_id

        # ── Step 1: load elements with BOQ links eagerly ────────────────
        base = select(BIMElement).where(BIMElement.model_id == model_id)
        if element_type is not None:
            base = base.where(BIMElement.element_type == element_type)
        if storey is not None:
            base = base.where(BIMElement.storey == storey)
        if discipline is not None:
            base = base.where(BIMElement.discipline == discipline)

        # Lazy-load by group: restrict to member element ids when a group
        # filter is supplied.  This makes cross-module deep-links like
        # ``/bim?group={id}`` load only the relevant subset instead of the
        # entire model (7k+ elements).
        if group_id is not None:
            group = await self.get_element_group(group_id)
            member_ids_raw = group.element_ids or []
            member_uuids = [uuid.UUID(eid) if isinstance(eid, str) else eid for eid in member_ids_raw]
            if member_uuids:
                base = base.where(BIMElement.id.in_(member_uuids))
            else:
                # Group has no members - return empty result set.
                base = base.where(False)  # type: ignore[arg-type]

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = (
            base.options(selectinload(BIMElement.boq_links)).order_by(BIMElement.created_at).offset(offset).limit(limit)
        )
        result = await self.session.execute(stmt)
        elements = list(result.scalars().all())
        element_ids = [elem.id for elem in elements]

        # ── Step 2: fetch ordinals/descriptions for every linked position
        pos_ids: set[uuid.UUID] = set()
        for elem in elements:
            for lnk in elem.boq_links or []:
                pos_ids.add(lnk.boq_position_id)

        pos_info: dict[uuid.UUID, tuple[str | None, str | None, Any, str | None, Any, Any]] = {}
        if pos_ids:
            pos_stmt = select(
                Position.id,
                Position.ordinal,
                Position.description,
                Position.quantity,
                Position.unit,
                Position.unit_rate,
                Position.total,
            ).where(Position.id.in_(pos_ids))
            pos_result = await self.session.execute(pos_stmt)
            for pid, ordinal, desc, qty, unit, urate, pos_total in pos_result.all():
                pos_info[pid] = (ordinal, desc, qty, unit, urate, pos_total)

        # ── Step 3: build BOQ brief dicts per element ───────────────────
        boq_links_by_element_id: dict[uuid.UUID, list[dict[str, Any]]] = {}
        for elem in elements:
            briefs: list[dict[str, Any]] = []
            for lnk in elem.boq_links or []:
                info = pos_info.get(lnk.boq_position_id)
                ordinal = info[0] if info else None
                desc = info[1] if info else None
                qty = None
                if info and info[2] is not None:
                    try:
                        qty = float(info[2])
                    except (TypeError, ValueError):
                        qty = None  # non-numeric quantity must not 500 the list
                unit = info[3] if info else None
                # v3 §10 - money goes through Pydantic as the raw 4dp string
                # from Position so Decimal() doesn't round-trip through float
                # and re-introduce binary precision drift.
                urate = str(info[4]) if info and info[4] is not None and str(info[4]).strip() else None
                brief_total = str(info[5]) if info and info[5] is not None and str(info[5]).strip() else None
                briefs.append(
                    {
                        "id": lnk.id,
                        "boq_position_id": lnk.boq_position_id,
                        "boq_position_ordinal": ordinal,
                        "boq_position_description": desc,
                        "boq_position_quantity": qty,
                        "boq_position_unit": unit,
                        "boq_position_unit_rate": urate,
                        "boq_position_total": brief_total,
                        "link_type": lnk.link_type,
                        "confidence": lnk.confidence,
                    }
                )
            boq_links_by_element_id[elem.id] = briefs

        # ── Step 4: fetch DocumentBIMLink rows joined with Document for this page
        doc_links_by_element_id: dict[uuid.UUID, list[dict[str, Any]]] = {eid: [] for eid in element_ids}
        if element_ids:
            doc_link_stmt = (
                select(
                    DocumentBIMLink.id,
                    DocumentBIMLink.bim_element_id,
                    DocumentBIMLink.document_id,
                    DocumentBIMLink.link_type,
                    DocumentBIMLink.confidence,
                    Document.name,
                    Document.category,
                )
                .join(Document, Document.id == DocumentBIMLink.document_id)
                .where(DocumentBIMLink.bim_element_id.in_(element_ids))
                .order_by(DocumentBIMLink.created_at.desc())
            )
            doc_link_result = await self.session.execute(doc_link_stmt)
            for row in doc_link_result.all():
                link_id, elem_id, doc_id, link_type, confidence, doc_name, doc_cat = row
                doc_links_by_element_id.setdefault(elem_id, []).append(
                    {
                        "id": link_id,
                        "document_id": doc_id,
                        "document_name": doc_name,
                        "document_category": doc_cat,
                        "link_type": link_type,
                        "confidence": confidence,
                    }
                )

        # ── Step 5: fetch Task rows for this project and filter in Python ──
        # Tasks store bim_element_ids as a denormalised JSON array; pulling all
        # project tasks once and filtering in memory is cross-dialect safe and
        # fine for the bounded sizes we expect.
        task_links_by_element_id: dict[uuid.UUID, list[dict[str, Any]]] = {eid: [] for eid in element_ids}
        if element_ids:
            element_id_strs = {str(eid) for eid in element_ids}
            task_stmt = select(Task).where(Task.project_id == model.project_id)
            task_result = await self.session.execute(task_stmt)
            for task in task_result.scalars().all():
                raw_ids = task.bim_element_ids or []
                if not raw_ids:
                    continue
                task_ids_as_str = {str(x) for x in raw_ids}
                matching = element_id_strs & task_ids_as_str
                if not matching:
                    continue
                brief = {
                    "id": task.id,
                    "project_id": task.project_id,
                    "title": task.title,
                    "status": task.status,
                    "task_type": task.task_type,
                    "due_date": task.due_date,
                }
                for eid in element_ids:
                    if str(eid) in matching:
                        task_links_by_element_id.setdefault(eid, []).append(brief)

        # ── Step 6: fetch Schedule Activities for this project and filter ──
        # Activities store ``bim_element_ids`` as a JSON list on each row.
        # We join through ``oe_schedule_schedule`` to scope by the model's
        # project, then filter in Python - same cross-dialect reasoning as
        # the task loop above.
        activity_briefs_by_element_id: dict[uuid.UUID, list[dict[str, Any]]] = {eid: [] for eid in element_ids}
        if element_ids:
            element_id_strs = {str(eid) for eid in element_ids}
            activity_stmt = (
                select(Activity)
                .join(Schedule, Activity.schedule_id == Schedule.id)
                .where(Schedule.project_id == model.project_id)
                .where(Activity.bim_element_ids.isnot(None))
            )
            activity_result = await self.session.execute(activity_stmt)
            for act in activity_result.scalars().all():
                raw_ids = act.bim_element_ids
                if not isinstance(raw_ids, list) or not raw_ids:
                    continue
                act_ids_as_str = {str(x) for x in raw_ids}
                matching = element_id_strs & act_ids_as_str
                if not matching:
                    continue
                try:
                    pct = float(act.progress_pct) if act.progress_pct else 0.0
                except (TypeError, ValueError):
                    pct = 0.0
                brief = {
                    "id": act.id,
                    "name": act.name,
                    "start_date": act.start_date,
                    "end_date": act.end_date,
                    "status": act.status,
                    "percent_complete": pct,
                }
                for eid in element_ids:
                    if str(eid) in matching:
                        activity_briefs_by_element_id.setdefault(eid, []).append(brief)

        # ── Step 6.5: fetch Requirement rows for this project ──────────
        # Requirements pin themselves to BIM elements via a JSON array
        # in ``Requirement.metadata_["bim_element_ids"]`` (no dedicated
        # column to keep migrations cheap).  We load every requirement
        # in the project once and filter in Python - same cross-dialect
        # reasoning as the task and activity loops above.
        requirement_briefs_by_element_id: dict[uuid.UUID, list[dict[str, Any]]] = {eid: [] for eid in element_ids}
        if element_ids:
            element_id_strs = {str(eid) for eid in element_ids}
            req_stmt = (
                select(Requirement)
                .join(
                    RequirementSet,
                    Requirement.requirement_set_id == RequirementSet.id,
                )
                .where(RequirementSet.project_id == model.project_id)
            )
            req_result = await self.session.execute(req_stmt)
            for req in req_result.scalars().all():
                raw_meta = req.metadata_ or {}
                raw_ids = raw_meta.get("bim_element_ids") or []
                if not isinstance(raw_ids, list) or not raw_ids:
                    continue
                req_ids_as_str = {str(x) for x in raw_ids}
                matching = element_id_strs & req_ids_as_str
                if not matching:
                    continue
                brief = {
                    "id": req.id,
                    "requirement_set_id": req.requirement_set_id,
                    "entity": req.entity or "",
                    "attribute": req.attribute or "",
                    "constraint_type": req.constraint_type or "equals",
                    "constraint_value": req.constraint_value or "",
                    "unit": req.unit or "",
                    "category": req.category or "general",
                    "priority": req.priority or "must",
                    "status": req.status or "open",
                }
                for eid in element_ids:
                    if str(eid) in matching:
                        requirement_briefs_by_element_id.setdefault(eid, []).append(brief)

        # ── Step 7: load latest ValidationReport for this model ──────────
        # Look up the most recent ``target_type='bim_model'`` report and
        # zip its per-element results into a dict keyed by element_id.
        # Missing reports are fine - the router falls back to 'unchecked'.
        #
        # To distinguish "report exists, element passed" from "no report
        # exists at all", we stash a sentinel entry under
        # ``_VALIDATION_REPORT_SENTINEL`` (UUID(int=0)) whose list contains
        # a single marker dict. The router inspects this key before the
        # per-element loop.
        validation_summaries_by_element_id: dict[uuid.UUID, list[dict[str, Any]]] = {eid: [] for eid in element_ids}
        if element_ids:
            from app.modules.validation.repository import ValidationReportRepository

            val_repo = ValidationReportRepository(self.session)
            latest_report = await val_repo.get_latest_for_target(
                target_type="bim_model",
                target_id=str(model_id),
            )
            if latest_report is not None:
                validation_summaries_by_element_id[_VALIDATION_REPORT_SENTINEL] = [{"report_id": str(latest_report.id)}]
                element_id_strs = {str(eid): eid for eid in element_ids}
                raw_results = latest_report.results or []
                for entry in raw_results:
                    if not isinstance(entry, dict):
                        continue
                    entry_eid = entry.get("element_id")
                    if not entry_eid:
                        continue
                    key_uuid = element_id_strs.get(str(entry_eid))
                    if key_uuid is None:
                        continue
                    severity = entry.get("severity") or "info"
                    if severity not in ("error", "warning", "info"):
                        severity = "info"
                    validation_summaries_by_element_id.setdefault(key_uuid, []).append(
                        {
                            "rule_id": entry.get("rule_id", ""),
                            "severity": severity,
                            "message": entry.get("message", ""),
                        }
                    )

        # ── Step 8: latest BOQ progress per element (model-based overlay) ─
        # Each element may link to one or more BOQ positions; we resolve the
        # latest ProgressEntry.percent_complete for every distinct linked
        # position in ONE round trip (correlated-MAX subquery in the
        # progress repository) and fold it back onto the elements. Taking
        # the MAX across an element's positions mirrors the "headline
        # progress" a human reads from a coloured 3D scene.
        #
        # We also resolve the recorded DATE of each position's latest entry
        # in the SAME round trip (the repository returns both columns), then
        # fold the date of the element's *winning* position so the selected-
        # element panel can show "65% as of 2026-06-01".
        current_pct_by_element_id: dict[uuid.UUID, float] = {}
        current_pct_date_by_element_id: dict[uuid.UUID, str] = {}
        if pos_ids and model.project_id is not None:
            from app.modules.progress.repository import ProgressRepository

            progress_repo = ProgressRepository(self.session)
            latest_by_position = await progress_repo.latest_pct_and_date_for_positions(
                model.project_id,
                list(pos_ids),
            )
            latest_pct_by_position = {pid: pct for pid, (pct, _dt) in latest_by_position.items()}
            date_by_position: dict[uuid.UUID, str | None] = {
                pid: (recorded_at.isoformat() if recorded_at is not None else None)
                for pid, (_pct, recorded_at) in latest_by_position.items()
            }
            current_pct_by_element_id = _fold_progress_onto_elements(
                elements,
                latest_pct_by_position,
            )
            current_pct_date_by_element_id = _fold_progress_date_onto_elements(
                elements,
                latest_pct_by_position,
                date_by_position,
            )

        return (
            elements,
            total,
            boq_links_by_element_id,
            doc_links_by_element_id,
            task_links_by_element_id,
            activity_briefs_by_element_id,
            requirement_briefs_by_element_id,
            validation_summaries_by_element_id,
            current_pct_by_element_id,
            current_pct_date_by_element_id,
        )

    async def get_element(self, element_id: uuid.UUID) -> BIMElement:
        """Get a single element by ID. Raises 404 if not found."""
        element = await self.element_repo.get(element_id)
        if element is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BIM element not found",
            )
        return element

    async def _reload_element_with_links(self, element_id: uuid.UUID) -> BIMElement:
        """Re-fetch an element with its ``boq_links`` eagerly loaded.

        A freshly created element (e.g. from ``ensure_element``'s lazy-create
        branches) has its ``selectin`` ``boq_links`` relationship UNLOADED.
        Serializing it through ``BIMElementResponse`` (from_attributes) would
        trigger an emit-on-access lazy load inside Pydantic's validation
        context, outside the async greenlet, raising ``MissingGreenlet`` →
        a raw 500. Reloading via an explicit SELECT eager-loads the
        relationship so serialization never touches the DB.
        """
        return (
            await self.session.execute(
                select(BIMElement).options(selectinload(BIMElement.boq_links)).where(BIMElement.id == element_id)
            )
        ).scalar_one()

    # ── Asset Register (v2.3.0) ─────────────────────────────────────────

    async def list_tracked_assets(
        self,
        project_id: uuid.UUID,
        *,
        element_type: str | None = None,
        operational_status: str | None = None,
        search: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[tuple[BIMElement, BIMModel]], int]:
        """Delegate to the repository. Kept on the service so permission
        checks and cross-module joins land in one place later without
        touching the router."""
        return await self.element_repo.list_tracked_assets_for_project(
            project_id,
            element_type=element_type,
            operational_status=operational_status,
            search=search,
            offset=offset,
            limit=limit,
        )

    async def update_asset_info(
        self,
        element_id: uuid.UUID,
        *,
        asset_info: dict,
        is_tracked_asset: bool | None = None,
    ) -> BIMElement:
        """Update an element's asset_info. 404 if element not found."""
        element = await self.element_repo.update_asset_info(
            element_id,
            asset_info=asset_info,
            is_tracked_asset=is_tracked_asset,
        )
        if element is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BIM element not found",
            )
        return element

    # ── COBie export (v2.3.0) ───────────────────────────────────────────

    async def export_cobie(self, model_id: uuid.UUID) -> tuple[bytes, str]:
        """Build a COBie.UK.2.4 workbook for a BIM model.

        Returns (xlsx_bytes, suggested_filename). 404 if model missing.
        """
        from app.modules.bim_hub.exporters import build_cobie_workbook

        model = await self.model_repo.get(model_id)
        if model is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BIM model not found",
            )
        # Pull every element for the model - pagination unnecessary here
        # because COBie is a handover snapshot, not an interactive view.
        # Large models (50k elements) still finish well under 10s in our
        # perf baseline with the existing paginated helper (limit=5000).
        elements: list[BIMElement] = []
        offset = 0
        page_size = 5000
        while True:
            batch, total = await self.element_repo.list_for_model(model_id, offset=offset, limit=page_size)
            elements.extend(batch)
            if offset + page_size >= total or not batch:
                break
            offset += page_size

        xlsx = build_cobie_workbook(model, elements)
        safe_name = (model.name or "model").replace(" ", "_").replace("/", "_")
        filename = f"COBie_{safe_name}.xlsx"
        return xlsx, filename

    async def ensure_element(
        self,
        model_id: uuid.UUID,
        *,
        stable_id: str | None = None,
        mesh_ref: str | None = None,
    ) -> BIMElement:
        """Resolve a BIMElement by stable_id or mesh_ref, lazy-creating
        a DB row from Parquet when the element isn't already persisted.

        Rationale: the DDC "standard" Excel extract sometimes filters out
        entire categories (tapered roofs, planting, sketch lines, detail
        components). Those elements still have full property rows in the
        Parquet dataframe and their meshes exist in the GLB scene - so
        the user can CLICK them in the 3D viewer - but they have no
        ``oe_bim_element`` row. When the user tries to link one to a BOQ
        position the request fails because ``BOQElementLink.bim_element_id``
        needs a real UUID FK. This method creates that row on demand so
        linking works uniformly for every visible mesh.

        Lookup order: stable_id → mesh_ref. Returns an existing row when
        one already matches. Raises 404 if the reference can't be matched
        to either a DB row or a Parquet row.
        """
        if not stable_id and not mesh_ref:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Either stable_id or mesh_ref is required",
            )

        model = await self.get_model(model_id)

        stmt = select(BIMElement).where(BIMElement.model_id == model_id)
        if stable_id:
            existing = (await self.session.execute(stmt.where(BIMElement.stable_id == stable_id))).scalar_one_or_none()
            if existing is not None:
                return existing
        if mesh_ref:
            existing = (await self.session.execute(stmt.where(BIMElement.mesh_ref == mesh_ref))).scalar_one_or_none()
            if existing is not None:
                return existing
            # mesh_ref often equals stable_id (the Revit ElementId) for DDC exports
            existing = (await self.session.execute(stmt.where(BIMElement.stable_id == mesh_ref))).scalar_one_or_none()
            if existing is not None:
                return existing

        # Not in DB - try to lazy-create from Parquet.
        import asyncio

        from app.modules.bim_hub.dataframe_store import query_parquet, read_schema

        ref = mesh_ref or stable_id
        if not ref:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "BIM element not found")

        # The DDC Parquet "id" column is usually literally ``id`` but some
        # converter versions / IFC exports emit ``Id`` / ``ElementId`` /
        # ``Element ID``.  Probe the actual schema and pick the first
        # id-like column that exists so the lookup is converter-agnostic
        # instead of hard-coding ``id`` (which raised ValueError →
        # spurious 404 on every snapshot-seeded model).
        try:
            schema = await asyncio.to_thread(read_schema, str(model.project_id), str(model_id))
        except (OSError, ValueError):
            schema = []
        schema_cols = {c["name"] for c in schema}
        id_col: str | None = None
        for cand in ("id", "Id", "ID", "ElementId", "Element ID", "element_id"):
            if cand in schema_cols:
                id_col = cand
                break

        rows: list[dict[str, Any]] = []
        if id_col is not None:
            try:
                rows = await asyncio.to_thread(
                    query_parquet,
                    str(model.project_id),
                    str(model_id),
                    columns=None,
                    filters=[{"column": id_col, "op": "=", "value": str(ref)}],
                    limit=1,
                )
            except ValueError:
                rows = []

        if not rows:
            # No Parquet (snapshot-seeded models ship geometry only) or no
            # matching row: still create a minimal placeholder element so
            # the mesh the user clicked in the 3D viewer can be linked to a
            # BOQ position.  This is the whole point of ``ensure_element`` -
            # "every visible mesh is linkable" - and it must not depend on a
            # full DDC Parquet extract being present.  IDOR is already
            # enforced by the caller's ``_verify_model_access`` check.
            element = BIMElement(
                model_id=model_id,
                stable_id=str(ref),
                mesh_ref=str(ref),
                element_type="Unmatched",
                name=f"Element {ref}",
                properties={},
                quantities={},
                metadata_={"source": "viewer_lazy_create"},
            )
            element = await self.element_repo.create(element)
            await self.session.flush()
            logger.info(
                "Lazy-created placeholder BIMElement id=%s model=%s ref=%s (source=viewer, no parquet row)",
                element.id,
                model_id,
                ref,
            )
            return await self._reload_element_with_links(element.id)

        row = rows[0]
        # Split the Parquet row into canonical quantity / property buckets so
        # downstream unit-sync logic (_sync_boq_quantity_from_links) can find
        # Area/Volume/Length values. The row layout varies by Revit category
        # so we match case-insensitively on common keys.
        qty_key_map = {
            "area": "area_m2",
            "volume": "volume_m3",
            "length": "length_m",
            "width": "width_m",
            "height": "height_m",
            "perimeter": "perimeter_m",
            "weight": "weight_kg",
        }
        quantities: dict[str, Any] = {}
        properties: dict[str, Any] = {}
        for raw_key, raw_val in row.items():
            if raw_val is None or raw_val == "":
                continue
            lower = str(raw_key).strip().lower()
            target = None
            for needle, canonical in qty_key_map.items():
                if needle == lower or lower.endswith(f" {needle}") or lower.endswith(f"_{needle}"):
                    target = canonical
                    break
            if target is not None:
                try:
                    quantities[target] = float(raw_val)
                except (TypeError, ValueError):
                    properties[str(raw_key)] = raw_val
            else:
                properties[str(raw_key)] = raw_val

        element = BIMElement(
            model_id=model_id,
            stable_id=str(ref),
            mesh_ref=str(ref),
            element_type=str(row.get("category") or row.get("Category") or "Unknown"),
            name=str(row.get("name") or row.get("Name") or row.get("Type") or f"Element {ref}"),
            storey=str(row.get("level") or row.get("Level") or "") or None,
            discipline=str(row.get("discipline") or row.get("Discipline") or "") or None,
            properties=properties,
            quantities=quantities,
            metadata_={"source": "parquet_lazy_create"},
        )
        element = await self.element_repo.create(element)
        await self.session.flush()
        logger.info(
            "Lazy-created BIMElement id=%s model=%s ref=%s (source=parquet)",
            element.id,
            model_id,
            ref,
        )
        return await self._reload_element_with_links(element.id)

    async def bulk_import_elements(
        self,
        model_id: uuid.UUID,
        elements_data: list[BIMElementCreate],
    ) -> list[BIMElement]:
        """Bulk import elements for a model (from CAD pipeline results).

        Replaces all existing elements for the model and updates
        element_count on the model record.
        """
        model = await self.get_model(model_id)

        # Capture existing element ids so we can emit element.deleted
        # events for the vector store before wiping them.
        existing_ids_stmt = select(BIMElement.id).where(BIMElement.model_id == model_id)
        existing_ids = [row_id for (row_id,) in (await self.session.execute(existing_ids_stmt)).all()]

        # Delete existing elements
        deleted = await self.element_repo.delete_all_for_model(model_id)
        if deleted:
            logger.info("Deleted %d existing elements for model %s", deleted, model_id)

        # Strip orphaned references from JSON-array link sites (Tasks,
        # Activities, Requirements) BEFORE we fan out the vector-delete
        # events.  Runs inline on the active session so SQLite write-lock
        # contention can not bite us.
        await _strip_orphaned_bim_links(
            self.session,
            [str(eid) for eid in existing_ids],
            model.project_id,
        )

        for old_id in existing_ids:
            await _safe_publish(
                "bim_hub.element.deleted",
                {
                    "element_id": str(old_id),
                    "model_id": str(model_id),
                    "project_id": str(model.project_id) if model.project_id else None,
                },
            )

        # Create new elements
        elements = [
            BIMElement(
                model_id=model_id,
                stable_id=e.stable_id,
                element_type=e.element_type,
                name=e.name,
                storey=e.storey,
                discipline=e.discipline,
                properties=e.properties,
                quantities=e.quantities,
                geometry_hash=e.geometry_hash,
                bounding_box=e.bounding_box,
                mesh_ref=e.mesh_ref,
                lod_variants=e.lod_variants,
                metadata_=e.metadata,
            )
            for e in elements_data
        ]
        created = await self.element_repo.bulk_create(elements)

        for elem in created:
            await _safe_publish(
                "bim_hub.element.created",
                {
                    "element_id": str(elem.id),
                    "model_id": str(model_id),
                    "project_id": str(model.project_id) if model.project_id else None,
                },
            )

        # Compute unique storeys
        storeys = {e.storey for e in created if e.storey}

        # Eagerly capture the model name and the freshly-assigned
        # element PKs BEFORE ``update_fields`` - the repository helper
        # calls ``session.expire_all()`` which invalidates every mapped
        # instance in this session (including ``model`` and every row
        # we just created).  Attribute access after expire triggers a
        # lazy reload that needs a greenlet context, and under the
        # async HTTP test harness that lazy load raises
        # ``MissingGreenlet`` while building the response.
        model_name = model.name
        created_ids = [elem.id for elem in created]

        # Update model counts
        await self.model_repo.update_fields(
            model_id,
            element_count=len(created),
            storey_count=len(storeys),
            status="active",
        )

        # Re-fetch the newly-created elements in a single round trip so
        # callers receive non-expired ORM instances that Pydantic can
        # serialise without lazy loads.
        refresh_stmt = (
            select(BIMElement).where(BIMElement.id.in_(created_ids)).options(selectinload(BIMElement.boq_links))
        )
        refreshed = list((await self.session.execute(refresh_stmt)).scalars().all())
        # Preserve the insertion order the caller requested - the IN
        # filter above returns in arbitrary order.
        order_index = {rid: idx for idx, rid in enumerate(created_ids)}
        refreshed.sort(key=lambda e: order_index.get(e.id, len(order_index)))

        logger.info(
            "Bulk imported %d elements for model %s (%d storeys)",
            len(refreshed),
            model_name,
            len(storeys),
        )
        return refreshed

    # ── BOQ Links ────────────────────────────────────────────────────────────

    async def list_links_for_position(
        self,
        boq_position_id: uuid.UUID,
    ) -> list[BOQElementLink]:
        """List all BIM element links for a BOQ position."""
        return await self.link_repo.list_by_boq_position(boq_position_id)

    async def list_links_for_model(
        self,
        model_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        """Aggregate BOQ links for every element in a model.

        Returns one row per ``(boq_position_id, link_type, confidence)`` with
        the full list of linked BIM element UUIDs and a handful of position
        fields. Powers the BIM viewer's "Linked BOQ" side-panel, which needs
        the totals across the whole model - not just the 2000-element page
        the enriched elements endpoint returns.
        """
        stmt = (
            select(
                BOQElementLink.boq_position_id,
                BOQElementLink.bim_element_id,
                BOQElementLink.link_type,
                BOQElementLink.confidence,
                Position.boq_id,
                Position.ordinal,
                Position.description,
                Position.quantity,
                Position.unit,
                Position.unit_rate,
                Position.total,
            )
            .join(BIMElement, BIMElement.id == BOQElementLink.bim_element_id)
            .join(Position, Position.id == BOQElementLink.boq_position_id)
            .where(BIMElement.model_id == model_id)
        )
        result = await self.session.execute(stmt)
        rows = result.all()

        # Aggregate by (position_id, link_type, confidence) - matches how the
        # panel groups visually. A position with both ``manual`` and
        # ``rule_based`` links shows as two rows, which is what the user
        # expects to see.
        agg: dict[tuple[uuid.UUID, str, str | None], dict[str, Any]] = {}
        for row in rows:
            key = (row.boq_position_id, row.link_type, row.confidence)
            entry = agg.get(key)
            if entry is None:
                entry = {
                    "boq_position_id": row.boq_position_id,
                    "boq_id": row.boq_id,
                    "boq_position_ordinal": row.ordinal,
                    "boq_position_description": row.description,
                    "boq_position_quantity": _safe_float(row.quantity),
                    "boq_position_unit": row.unit,
                    # v3 §10 - pass money values as their raw 4dp string so
                    # Pydantic Decimal coercion is exact (not float-rounded).
                    "boq_position_unit_rate": (
                        str(row.unit_rate) if row.unit_rate is not None and str(row.unit_rate).strip() else None
                    ),
                    "boq_position_total": (
                        str(row.total) if row.total is not None and str(row.total).strip() else None
                    ),
                    "link_type": row.link_type,
                    "confidence": row.confidence,
                    "element_ids": [],
                }
                agg[key] = entry
            entry["element_ids"].append(row.bim_element_id)

        return list(agg.values())

    async def create_link(
        self,
        data: BOQElementLinkCreate,
        user_id: str | None = None,
    ) -> BOQElementLink:
        """Create a link between a BOQ position and a BIM element.

        Also mirrors the BIM element id into ``Position.cad_element_ids``
        so legacy consumers that read that JSON array stay in sync with
        the canonical ``oe_bim_boq_link`` table.
        """
        # Verify element exists
        element = await self.element_repo.get(data.bim_element_id)
        if element is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BIM element not found",
            )

        # Idempotency guard. ``oe_bim_boq_link`` has a UNIQUE constraint on
        # (boq_position_id, bim_element_id). Re-linking the same element to a
        # position it is already linked to (the user clicks "Add to BOQ" twice,
        # or a group/bulk link includes an already-linked element) would
        # otherwise hit that constraint on flush and surface as a raw 500
        # "Internal server error". Return a clean 409 instead - the frontend
        # treats a 409 whose message contains "already" as a no-op so bulk
        # linking stays idempotent.
        existing = next(
            (
                lnk
                for lnk in await self.link_repo.list_by_boq_position(data.boq_position_id)
                if lnk.bim_element_id == data.bim_element_id
            ),
            None,
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This BIM element is already linked to that BOQ position",
            )

        link = BOQElementLink(
            boq_position_id=data.boq_position_id,
            bim_element_id=data.bim_element_id,
            link_type=data.link_type,
            confidence=data.confidence,
            rule_id=data.rule_id,
            created_by=user_id,
            metadata_=data.metadata,
        )
        try:
            link = await self.link_repo.create(link)
        except IntegrityError as exc:
            # Lost a race with a concurrent writer that inserted the same
            # (position, element) pair between our pre-check and flush. Roll
            # back the failed flush and report the same friendly 409.
            await self.session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This BIM element is already linked to that BOQ position",
            ) from exc

        # Keep Position.cad_element_ids in sync (legacy JSON mirror).
        await self._append_cad_element_id(data.boq_position_id, data.bim_element_id)

        # Auto-populate BOQ position quantity from linked element quantities.
        await self._sync_boq_quantity_from_links(data.boq_position_id)

        logger.info(
            "BOQ-BIM link created: pos=%s elem=%s type=%s",
            data.boq_position_id,
            data.bim_element_id,
            data.link_type,
        )
        return link

    async def delete_link(self, link_id: uuid.UUID) -> None:
        """Delete a BOQ-BIM link and drop the mirrored id from the position."""
        link = await self.link_repo.get(link_id)
        if link is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BOQ-BIM link not found",
            )
        position_id = link.boq_position_id
        element_id = link.bim_element_id
        await self.link_repo.delete(link_id)

        # Remove the mirrored id from Position.cad_element_ids.
        await self._remove_cad_element_id(position_id, element_id)

        # Re-sync BOQ position quantity after link removal.
        await self._sync_boq_quantity_from_links(position_id)

        logger.info("BOQ-BIM link deleted: %s", link_id)

    # ── cad_element_ids sync helpers ─────────────────────────────────────

    async def _append_cad_element_id(
        self,
        position_id: uuid.UUID,
        element_id: uuid.UUID,
    ) -> None:
        """Append ``element_id`` to ``Position.cad_element_ids`` if missing.

        Initialises the array when the column is NULL (legacy rows) and
        skips duplicates. No-op when the position no longer exists - the
        caller is responsible for verifying position existence beforehand.
        """
        pos = await self.session.get(Position, position_id)
        if pos is None:
            return
        current = list(pos.cad_element_ids or [])
        elem_str = str(element_id)
        if elem_str not in current:
            current.append(elem_str)
            pos.cad_element_ids = current
            # Re-assign to force SQLAlchemy to notice the mutation on JSON.
            await self.session.flush()

    async def _sync_boq_quantity_from_links(
        self,
        position_id: uuid.UUID,
    ) -> None:
        """Recompute ``Position.quantity`` from all linked BIM element quantities.

        Strategy: sum the *dimensionally-correct* quantity field from
        linked elements based on the position's unit:

        - m3 / m³           → Σ volume_m3
        - m2 / m²           → Σ area_m2
        - m / lfm / lm      → Σ length_m
        - kg                → Σ weight_kg
        - t (metric tonne)  → Σ weight_kg ÷ 1000   (D-TKC-005)
        - pcs / St / ea / … → element *count*       (E-XMOD-003)

        Correctness invariants (these were the v1.9.0 defects):

        * **E-XMOD-003** - a count position (``pcs``/``St``/``ea``/
          ``lsum``/…) must NEVER take volume/area/weight. It gets the
          number of linked elements (1 per element) so "7.5 pcs of
          walls" can no longer happen.
        * **D-TKC-005** - a tonne position divides ``weight_kg`` by
          1000 so 4000 kg → 4 t, not 4000 t.
        * **D-TKC-028** - if NO dimensionally-correct quantity exists
          for the unit, the position is left untouched. We never fall
          back to "first non-zero numeric value" (which silently summed
          an area into a length position, etc.). The estimator's manual
          value is preserved instead of being corrupted.
        """
        pos = await self.session.get(Position, position_id)
        if pos is None:
            return

        links = await self.link_repo.list_by_boq_position(position_id)
        if not links:
            return

        # Canonical ASCII unit token (m³→m3, M2→m2, …) so the mapping
        # below is locale/encoding independent.
        unit = normalize_unit_token(pos.unit)

        # ── Count units: quantity = number of linked elements ─────────
        # No geometric substitution - this is the E-XMOD-003 fix.
        if unit in _COUNT_UNITS:
            count_total = 0
            for lnk in links:
                elem = await self.element_repo.get(lnk.bim_element_id)
                if elem is not None:
                    count_total += 1
            if count_total > 0:
                pos.quantity = str(count_total)
                try:
                    rate = Decimal(pos.unit_rate or "0")
                    pos.total = str((Decimal(count_total) * rate).quantize(Decimal("0.01")))
                except (InvalidOperation, TypeError, ValueError):
                    pass
                await self.session.flush()
                logger.info(
                    "BOQ position %s (count unit %r) quantity auto-set to %d linked BIM element(s)",
                    position_id,
                    pos.unit,
                    count_total,
                )
            return

        # ── Geometric units: dimension-locked quantity key ────────────
        _UNIT_TO_QKEY: dict[str, list[str]] = {
            "m3": ["volume_m3", "Volume", "volume"],
            "m2": ["area_m2", "Area", "area"],
            "m": ["length_m", "Length", "length"],
            "lfm": ["length_m", "Length", "length"],
            "lm": ["length_m", "Length", "length"],
            "kg": ["weight_kg", "Weight", "weight"],
            "t": ["weight_kg", "Weight", "weight"],
            "to": ["weight_kg", "Weight", "weight"],
        }
        preferred_keys = _UNIT_TO_QKEY.get(unit, [])
        if not preferred_keys:
            # D-TKC-028 - unknown / non-geometric unit and not a known
            # count unit: do NOT guess a dimension. Leaving the manual
            # quantity intact is strictly safer than summing an
            # arbitrary geometric value of the wrong dimension.
            logger.info(
                "BOQ position %s unit %r has no dimensionally-correct "
                "BIM quantity mapping - manual quantity left untouched "
                "(no arbitrary fallback)",
                position_id,
                pos.unit,
            )
            return

        # kg → 1, t → 1/1000 (D-TKC-005: tonne conversion).
        scale = Decimal("0.001") if unit in ("t", "to") else Decimal("1")

        total = Decimal(0)
        for lnk in links:
            elem = await self.element_repo.get(lnk.bim_element_id)
            if elem is None:
                continue
            qtys = elem.quantities or {}

            value: Decimal | None = None
            for key in preferred_keys:
                raw = qtys.get(key)
                if raw is not None:
                    try:
                        value = Decimal(str(raw))
                        break
                    except (InvalidOperation, TypeError, ValueError):
                        continue

            # D-TKC-028 - NO arbitrary fallback. An element that lacks
            # the dimensionally-correct quantity simply contributes 0.
            if value is not None and value > 0:
                total += value * scale

        if total > 0:
            # Round to 4 decimal places to avoid floating-point noise
            pos.quantity = str(total.quantize(Decimal("0.0001")))
            # Also recompute total = quantity * unit_rate
            try:
                rate = Decimal(pos.unit_rate or "0")
                pos.total = str((total * rate).quantize(Decimal("0.01")))
            except (InvalidOperation, TypeError, ValueError):
                pass
            await self.session.flush()
            logger.info(
                "BOQ position %s quantity auto-updated to %s from %d linked BIM elements",
                position_id,
                pos.quantity,
                len(links),
            )

    async def _remove_cad_element_id(
        self,
        position_id: uuid.UUID,
        element_id: uuid.UUID,
    ) -> None:
        """Remove ``element_id`` from ``Position.cad_element_ids`` if present."""
        pos = await self.session.get(Position, position_id)
        if pos is None:
            return
        current = list(pos.cad_element_ids or [])
        elem_str = str(element_id)
        if elem_str in current:
            current.remove(elem_str)
            pos.cad_element_ids = current
            await self.session.flush()

    # ── Quantity Maps ────────────────────────────────────────────────────────

    async def list_quantity_maps(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[BIMQuantityMap], int]:
        """List all quantity mapping rules."""
        return await self.qmap_repo.list_all(offset=offset, limit=limit)

    async def create_quantity_map(
        self,
        data: BIMQuantityMapCreate,
    ) -> BIMQuantityMap:
        """Create a new quantity mapping rule."""
        qmap = BIMQuantityMap(
            org_id=data.org_id,
            project_id=data.project_id,
            name=data.name,
            name_translations=data.name_translations,
            element_type_filter=data.element_type_filter,
            property_filter=data.property_filter,
            quantity_source=data.quantity_source,
            multiplier=data.multiplier,
            unit=data.unit,
            waste_factor_pct=data.waste_factor_pct,
            boq_target=data.boq_target,
            is_active=data.is_active,
            metadata_=data.metadata,
        )
        qmap = await self.qmap_repo.create(qmap)
        logger.info("Quantity map created: %s (source=%s)", data.name, data.quantity_source)
        return qmap

    async def update_quantity_map(
        self,
        map_id: uuid.UUID,
        data: BIMQuantityMapUpdate,
    ) -> BIMQuantityMap:
        """Update a quantity mapping rule."""
        existing = await self.qmap_repo.get(map_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Quantity map rule not found",
            )

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if not fields:
            return existing

        await self.qmap_repo.update_fields(map_id, **fields)
        updated = await self.qmap_repo.get(map_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Quantity map rule not found after update",
            )
        return updated

    async def apply_quantity_maps(
        self,
        request: QuantityMapApplyRequest,
    ) -> QuantityMapApplyResult:
        """Apply quantity mapping rules to all elements in a model.

        Two modes, selected by ``request.dry_run``:

        **dry_run=True (default)** - compute and return a preview only.
            No ``BOQElementLink`` rows and no ``Position`` rows are created.
            ``links_created`` and ``positions_created`` stay at 0.

        **dry_run=False** - actually persist the result:
            * For every rule with a resolvable ``boq_target``, create a
              ``BOQElementLink`` (link_type="rule_based", confidence="high",
              rule_id=rule.id) for each matched element, skipping any
              (position_id, element_id) pair that already exists.
            * If a rule's ``boq_target`` does not resolve to an existing
              position **and** the target dict has ``auto_create: True``,
              a new ``Position`` is inserted into the project's first BOQ
              with quantity = Σ(adjusted quantity across matched elements)
              and then the links are created against the new position.
            * Each rule's writes run inside a single savepoint
              (``session.begin_nested``) - a failure while processing one
              rule rolls that rule back cleanly without aborting the
              others or the outer request transaction.
            * Also keeps ``Position.cad_element_ids`` in sync via
              ``_append_cad_element_id``.
        """
        model = await self.get_model(request.model_id)

        # Get all elements for the model
        elements, _ = await self.element_repo.list_for_model(model.id, offset=0, limit=50000)

        # Get active rules (project-scoped first, then global)
        rules = await self.qmap_repo.list_active(project_id=model.project_id)

        # ── Step 1: compute matches per rule (same math regardless of
        # dry_run so the preview stays identical across modes). ───────────
        # Tracks (element, rule) pairs that fired the rule but were
        # then dropped because the quantity could not be extracted -
        # most often because the element is missing the property the
        # rule reads.  We surface this in the result so the dry-run
        # preview can show *why* a population is smaller than expected
        # instead of silently dropping rows.
        per_rule_matches: dict[uuid.UUID, list[tuple[BIMElement, Decimal, Decimal]]] = {}
        # Per-rule count of elements that matched the filter but yielded no
        # usable quantity. Combined with the match count it gives a match
        # quality ratio we stamp onto the auto-created Position as a
        # confidence score (AI-augmented, human-confirmed provenance).
        per_rule_skips: dict[uuid.UUID, int] = {}
        results: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        matched_element_ids: set[uuid.UUID] = set()

        for element in elements:
            for rule in rules:
                if not self._rule_matches_element(rule, element):
                    continue

                qty = self._extract_quantity(element, rule.quantity_source)
                if qty is None:
                    per_rule_skips[rule.id] = per_rule_skips.get(rule.id, 0) + 1
                    skipped.append(
                        {
                            "element_id": str(element.id),
                            "stable_id": element.stable_id,
                            "element_type": element.element_type,
                            "rule_id": str(rule.id),
                            "rule_name": rule.name,
                            "quantity_source": rule.quantity_source,
                            "reason": "missing_property",
                            "detail": (f"element has no value for '{rule.quantity_source}' (property/quantity key)"),
                        }
                    )
                    continue

                try:
                    multiplier = Decimal(rule.multiplier or "1")
                    waste_pct = Decimal(rule.waste_factor_pct or "0")
                    adjusted = qty * multiplier * (Decimal("1") + waste_pct / Decimal("100"))
                except (InvalidOperation, ValueError) as exc:
                    per_rule_skips[rule.id] = per_rule_skips.get(rule.id, 0) + 1
                    skipped.append(
                        {
                            "element_id": str(element.id),
                            "stable_id": element.stable_id,
                            "element_type": element.element_type,
                            "rule_id": str(rule.id),
                            "rule_name": rule.name,
                            "quantity_source": rule.quantity_source,
                            "reason": "invalid_decimal",
                            "detail": (
                                f"could not convert quantity {qty!r} with "
                                f"multiplier={rule.multiplier!r} / "
                                f"waste={rule.waste_factor_pct!r}: {exc}"
                            ),
                        }
                    )
                    continue

                per_rule_matches.setdefault(rule.id, []).append((element, qty, adjusted))
                matched_element_ids.add(element.id)

                results.append(
                    {
                        "element_id": str(element.id),
                        "stable_id": element.stable_id,
                        "element_type": element.element_type,
                        "rule_id": str(rule.id),
                        "rule_name": rule.name,
                        "quantity_source": rule.quantity_source,
                        "raw_quantity": float(qty),
                        "adjusted_quantity": float(adjusted),
                        "unit": rule.unit,
                        "boq_target": rule.boq_target,
                    }
                )

        matched_elements = len(matched_element_ids)
        rules_applied = sum(1 for matches in per_rule_matches.values() if matches)
        links_created = 0
        positions_created = 0

        # ── Step 2: persist (only when dry_run is False) ───────────────
        if not request.dry_run and per_rule_matches:
            rules_by_id = {rule.id: rule for rule in rules}
            for rule_id, matches in per_rule_matches.items():
                rule = rules_by_id.get(rule_id)
                if rule is None or not matches:
                    continue

                confidence = self._match_quality_confidence(
                    matched=len(matches),
                    skipped=per_rule_skips.get(rule_id, 0),
                )
                try:
                    async with self.session.begin_nested():
                        created_links, created_positions = await self._persist_rule_matches(
                            rule=rule,
                            model=model,
                            matches=matches,
                            confidence=confidence,
                        )
                        links_created += created_links
                        positions_created += created_positions
                except Exception:  # noqa: BLE001 - per-rule isolation
                    logger.exception(
                        "Failed to persist quantity map rule %s on model %s",
                        rule_id,
                        model.id,
                    )
                    # Savepoint already rolled back; continue with next rule.

        # Surface skip count alongside match counts so operators can
        # tell at-a-glance whether the population is honest.  A high
        # skip count almost always means the rule's ``quantity_source``
        # is wrong or the IFC export is missing a column.
        if skipped:
            logger.warning(
                "Quantity maps: %d (element, rule) pair(s) skipped on "
                "model %s - most common reason is a missing property "
                "(rule expects something the BIM export did not provide). "
                "First skipped pair: %s",
                len(skipped),
                model.name,
                skipped[0],
            )

        logger.info(
            "Quantity maps applied: %d elements matched, %d rules applied, "
            "%d links created, %d positions created, %d skipped for model "
            "%s (dry_run=%s)",
            matched_elements,
            rules_applied,
            links_created,
            positions_created,
            len(skipped),
            model.name,
            request.dry_run,
        )

        return QuantityMapApplyResult(
            matched_elements=matched_elements,
            rules_applied=rules_applied,
            links_created=links_created,
            positions_created=positions_created,
            skipped_count=len(skipped),
            results=results,
            skipped=skipped,
        )

    async def _persist_rule_matches(
        self,
        *,
        rule: BIMQuantityMap,
        model: BIMModel,
        matches: list[tuple[BIMElement, Decimal, Decimal]],
        confidence: str | None = None,
    ) -> tuple[int, int]:
        """Create BOQElementLink (and optionally a Position) for one rule.

        Called from ``apply_quantity_maps`` inside a savepoint. Returns
        ``(links_created, positions_created)``.

        ``confidence`` is the rule's match-quality bucket (``high`` / ``medium``
        / ``low``); it is stamped onto an auto-created Position as provenance.
        """
        if not matches:
            return 0, 0

        target = rule.boq_target or {}
        if not isinstance(target, dict):
            logger.warning("Rule %s has non-dict boq_target; skipping persistence", rule.id)
            return 0, 0

        # ── Resolve the target Position ───────────────────────────────
        position = await self._resolve_boq_target_position(
            target=target,
            project_id=model.project_id,
        )
        positions_created = 0

        if position is None:
            if not target.get("auto_create"):
                logger.info(
                    "Rule %s: boq_target unresolved and auto_create is false; skipping",
                    rule.id,
                )
                return 0, 0

            position = await self._auto_create_position_for_rule(
                rule=rule,
                project_id=model.project_id,
                matches=matches,
                confidence=confidence,
            )
            if position is None:
                return 0, 0
            positions_created = 1

        # ── Create links for every matched element ────────────────────
        links_created = 0
        existing_elem_ids = await self._existing_link_element_ids(position.id)

        for element, _raw, _adjusted in matches:
            if element.id in existing_elem_ids:
                continue  # idempotent - dup UNIQUE would 500 us otherwise

            link = BOQElementLink(
                boq_position_id=position.id,
                bim_element_id=element.id,
                link_type="rule_based",
                confidence="high",
                rule_id=str(rule.id),
                metadata_={},
            )
            try:
                await self.link_repo.create(link)
            except IntegrityError:
                # Race with a concurrent writer - treat as already linked.
                logger.debug(
                    "IntegrityError creating link pos=%s elem=%s (treated as duplicate)",
                    position.id,
                    element.id,
                )
                continue

            await self._append_cad_element_id(position.id, element.id)
            existing_elem_ids.add(element.id)
            links_created += 1

        return links_created, positions_created

    async def _resolve_boq_target_position(
        self,
        *,
        target: dict[str, Any],
        project_id: uuid.UUID,
    ) -> Position | None:
        """Look up a Position from a rule's ``boq_target`` dict.

        Supports two lookup keys:
            - ``position_id``: direct UUID lookup (scoped to project).
            - ``position_ordinal``: match by ordinal within any BOQ of the
              given project (returns the first match).
        """
        raw_pid = target.get("position_id")
        if raw_pid:
            try:
                pid = uuid.UUID(str(raw_pid))
            except (ValueError, TypeError):
                return None
            pos = await self.session.get(Position, pid)
            if pos is None:
                return None
            # Make sure the position belongs to the same project.
            boq = await self.session.get(BOQ, pos.boq_id)
            if boq is None or boq.project_id != project_id:
                return None
            return pos

        ordinal = target.get("position_ordinal")
        if ordinal:
            stmt = (
                select(Position)
                .join(BOQ, BOQ.id == Position.boq_id)
                .where(BOQ.project_id == project_id, Position.ordinal == str(ordinal))
                .limit(1)
            )
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none()

        return None

    async def _auto_create_position_for_rule(
        self,
        *,
        rule: BIMQuantityMap,
        project_id: uuid.UUID,
        matches: list[tuple[BIMElement, Decimal, Decimal]],
        confidence: str | None = None,
    ) -> Position | None:
        """Insert a new Position in the project's first/default BOQ.

        Quantity = sum of adjusted quantities across all matches for this
        rule. Unit = rule.unit (fallback "pcs"). Classification is lifted
        from ``rule.metadata_["classification"]`` when present.
        Returns ``None`` if the project has no BOQ to attach to.

        ``source`` is always ``"cad_import"`` (the position is derived from a
        BIM model) and ``confidence`` carries the rule's match-quality bucket so
        the estimator can audit how trustworthy the auto-generated quantity is.
        """
        # Find the project's first BOQ (oldest created_at, same as
        # ``BOQRepository.list_for_project`` order inverted).
        stmt = select(BOQ).where(BOQ.project_id == project_id).order_by(BOQ.created_at.asc()).limit(1)
        boq = (await self.session.execute(stmt)).scalar_one_or_none()
        if boq is None:
            logger.warning(
                "Auto-create requested for rule %s but project %s has no BOQ",
                rule.id,
                project_id,
            )
            return None

        # Aggregate the adjusted quantity across all matched elements.
        total_qty = sum((adjusted for _, _, adjusted in matches), Decimal("0"))

        # Pull classification out of the rule's metadata if present.
        rule_meta = rule.metadata_ or {}
        classification = rule_meta.get("classification") or {}
        if not isinstance(classification, dict):
            classification = {}

        # Pick a free ordinal - "BIM-<short rule id>" - unlikely to clash.
        ordinal = f"BIM-{str(rule.id)[:8]}"

        # Determine sort_order: after everything else.
        max_order_stmt = select(func.coalesce(func.max(Position.sort_order), 0)).where(Position.boq_id == boq.id)
        max_order = (await self.session.execute(max_order_stmt)).scalar_one() or 0

        # Pull a default unit_rate from the rule's boq_target dict if the
        # author prefilled one (e.g. via the "Suggest from CWICR" button
        # in the rule editor).  When non-zero we also compute the line
        # total here so the new position lands fully priced - no second
        # pass needed in the BOQ editor.
        #
        # QR-004 - a rule author could prefill an arbitrary
        # ``unit_rate`` (e.g. ``1e308``) that landed verbatim in a
        # priced BOQ position with ``source='cad_import'``. We parse
        # via Decimal (locale-independent), reject non-finite /
        # negative, and clamp implausibly large rates so a careless or
        # malicious rule cannot inject a corrupt price. ``total_qty``
        # itself is already a finite Decimal (the apply-time math is
        # now bounded by the QR-001 multiplier/waste validators).
        _MAX_PREFILL_RATE = Decimal("100000000")  # 1e8 per-unit ceiling
        default_rate = "0"
        rate_decimal = Decimal("0")
        target_dict = rule.boq_target or {}
        if isinstance(target_dict, dict):
            raw_rate = target_dict.get("unit_rate")
            candidate: str | None = None
            if isinstance(raw_rate, (int, float)):
                candidate = str(raw_rate)
            elif isinstance(raw_rate, str) and raw_rate.strip():
                candidate = raw_rate.strip()
            if candidate is not None:
                try:
                    parsed = Decimal(candidate)
                except (InvalidOperation, ValueError):
                    logger.warning(
                        "Rule %s prefilled a non-numeric unit_rate %r; falling back to 0",
                        rule.id,
                        raw_rate,
                    )
                    parsed = Decimal("0")
                if not parsed.is_finite() or parsed < 0:
                    logger.warning(
                        "Rule %s prefilled a non-finite/negative unit_rate %r; clamped to 0",
                        rule.id,
                        raw_rate,
                    )
                    parsed = Decimal("0")
                elif parsed > _MAX_PREFILL_RATE:
                    logger.warning(
                        "Rule %s prefilled an implausibly large unit_rate %r; clamped to %s",
                        rule.id,
                        raw_rate,
                        _MAX_PREFILL_RATE,
                    )
                    parsed = _MAX_PREFILL_RATE
                rate_decimal = parsed
                default_rate = str(parsed)

        line_total = total_qty * rate_decimal

        # E-XMOD-020 - persist the canonical ASCII unit token (m³→m3)
        # so the new position is subject to the same RateVsBenchmark /
        # MeasurementConsistency rules as a hand-typed "m3".
        canonical_unit = normalize_unit_token(rule.unit) or "pcs"

        position = Position(
            boq_id=boq.id,
            parent_id=None,
            ordinal=ordinal,
            description=rule.name,
            unit=canonical_unit,
            quantity=str(total_qty),
            unit_rate=default_rate,
            total=str(line_total),
            classification=classification,
            source="cad_import",
            confidence=confidence,
            cad_element_ids=[],
            validation_status="pending",
            metadata_={
                "auto_created_by_rule": str(rule.id),
                "match_confidence": confidence,
            },
            sort_order=max_order + 1,
        )
        self.session.add(position)
        await self.session.flush()
        logger.info(
            "Auto-created Position %s (ordinal=%s) for rule %s in BOQ %s",
            position.id,
            ordinal,
            rule.id,
            boq.id,
        )
        return position

    async def _existing_link_element_ids(
        self,
        position_id: uuid.UUID,
    ) -> set[uuid.UUID]:
        """Return the set of bim_element_ids already linked to a position."""
        stmt = select(BOQElementLink.bim_element_id).where(BOQElementLink.boq_position_id == position_id)
        result = await self.session.execute(stmt)
        return {row[0] for row in result.all()}

    async def sync_cad_element_ids(
        self,
        project_id: uuid.UUID | None = None,
    ) -> dict[str, int]:
        """Rewrite ``Position.cad_element_ids`` from ``oe_bim_boq_link``.

        Idempotent back-fill helper. Walks every ``BOQElementLink`` in the
        database (optionally scoped to a single project) and overwrites
        the JSON array on the linked ``Position`` with the sorted list of
        bim_element_id strings. Use this when:

            * the app shipped before the link↔position mirror existed and
              legacy rows have out-of-date or empty ``cad_element_ids``;
            * a bulk DB import bypassed the service layer;
            * a migration has added/removed links in bulk.

        Returns a small summary ``{"links_scanned", "positions_updated"}``.
        """
        # ── Load links (optionally scoped to project) ─────────────────
        if project_id is not None:
            stmt = (
                select(BOQElementLink.boq_position_id, BOQElementLink.bim_element_id)
                .join(Position, Position.id == BOQElementLink.boq_position_id)
                .join(BOQ, BOQ.id == Position.boq_id)
                .where(BOQ.project_id == project_id)
            )
        else:
            stmt = select(BOQElementLink.boq_position_id, BOQElementLink.bim_element_id)

        result = await self.session.execute(stmt)
        grouped: dict[uuid.UUID, set[str]] = {}
        links_scanned = 0
        for pos_id, elem_id in result.all():
            links_scanned += 1
            grouped.setdefault(pos_id, set()).add(str(elem_id))

        # Also make sure positions that exist in the project but have NO
        # links get their cad_element_ids reset to [] (so stale ids from a
        # previous state are cleared).
        if project_id is not None:
            all_pos_stmt = select(Position.id).join(BOQ, BOQ.id == Position.boq_id).where(BOQ.project_id == project_id)
            all_pos = (await self.session.execute(all_pos_stmt)).scalars().all()
            for pid in all_pos:
                grouped.setdefault(pid, set())

        positions_updated = 0
        for pos_id, elem_ids in grouped.items():
            pos = await self.session.get(Position, pos_id)
            if pos is None:
                continue
            desired = sorted(elem_ids)
            current = list(pos.cad_element_ids or [])
            if sorted(current) != desired:
                pos.cad_element_ids = desired
                positions_updated += 1

        await self.session.flush()
        logger.info(
            "sync_cad_element_ids: scanned %d links, updated %d positions (project=%s)",
            links_scanned,
            positions_updated,
            project_id,
        )
        return {
            "links_scanned": links_scanned,
            "positions_updated": positions_updated,
        }

    @staticmethod
    def _rule_matches_element(rule: BIMQuantityMap, element: BIMElement) -> bool:
        """Check if a quantity map rule matches an element."""
        # Check element_type_filter
        if rule.element_type_filter:
            if rule.element_type_filter != "*":
                if not element.element_type:
                    return False
                if not fnmatch.fnmatch(element.element_type.lower(), rule.element_type_filter.lower()):
                    return False

        # Check property_filter via the shared type-aware helper so we
        # match dynamic-element-group semantics: list values fall back
        # to membership, dict values to recursive containment, None to
        # explicit "not set" handling.  The previous implementation
        # str()'d everything, which collapsed ``["steel","concrete"]``
        # into the literal string ``"['steel', 'concrete']"`` and made
        # multi-valued IFC properties unmatchable.
        if rule.property_filter:
            props = element.properties or {}
            for key, pattern in rule.property_filter.items():
                if not BIMHubService._property_value_matches(props.get(key), pattern):
                    return False

        return True

    @staticmethod
    def _property_value_matches(actual: Any, expected: Any) -> bool:  # noqa: PLR0911
        """Type-aware comparison for BIM property filters.

        Used by both the dynamic-element-group ``_matches`` predicate
        and the quantity-map rule engine, so multi-valued IFC properties
        (lists, nested dicts) and missing properties behave consistently
        across the two callers.

        Rules:
            * ``expected is None`` matches when ``actual is None`` (explicit
              "this property must not be set").
            * ``actual is None`` otherwise → ``False`` (the filter wants
              a value but the element has none).
            * ``actual`` is a list →
                - ``expected`` is a list  → non-empty set intersection
                - ``expected`` is a scalar → membership test (with
                  fnmatch wildcards on each list item if it's a string)
            * ``actual`` is a dict + ``expected`` is a dict → recursive
              containment (every key in ``expected`` must match the
              corresponding key in ``actual``).
            * Both are strings → fnmatch (case-insensitive, supports
              ``*`` and ``?`` wildcards).
            * Otherwise → exact equality after stringifying.

        Returns ``True`` when the actual value satisfies the expected
        pattern, ``False`` otherwise.
        """
        # Explicit "must not be set" filter
        if expected is None:
            return actual is None
        if actual is None:
            return False

        # List actual: membership / intersection semantics
        if isinstance(actual, list):
            if isinstance(expected, list):
                return any(
                    BIMHubService._property_value_matches(item, exp_item) for item in actual for exp_item in expected
                )
            # Scalar expected → does the list contain a matching item?
            return any(BIMHubService._property_value_matches(item, expected) for item in actual)

        # Dict actual + dict expected: recursive containment
        if isinstance(actual, dict) and isinstance(expected, dict):
            return all(BIMHubService._property_value_matches(actual.get(k), v) for k, v in expected.items())

        # String values: fnmatch wildcards (existing _rule_matches_element
        # behaviour, kept for backwards compatibility with rules that use
        # ``*`` and ``?`` patterns).
        if isinstance(actual, str) and isinstance(expected, str):
            return fnmatch.fnmatch(actual.lower(), expected.lower())

        # Booleans / numerics / mixed types → fall back to exact equality
        # via string coercion.  This handles e.g. ``actual=42`` against
        # ``expected="42"`` and ``actual=True`` against ``expected="true"``.
        return str(actual).lower() == str(expected).lower()

    @staticmethod
    def _match_quality_confidence(*, matched: int, skipped: int) -> str | None:
        """Derive a confidence bucket from a rule's match quality.

        The signal is the share of elements selected by the rule's filter that
        actually produced a usable quantity (``matched`` of ``matched + skipped``).
        A rule that selected many elements but dropped most of them for missing
        properties is low-confidence, so the auto-created BOQ position is stamped
        accordingly and the estimator knows to look harder before pricing it.

        Mirrors the frontend ``draftConfidence`` thresholds so the sandbox
        preview and the persisted provenance agree.

        Returns ``"high"`` / ``"medium"`` / ``"low"``, or ``None`` when there is
        nothing to score.
        """
        considered = matched + skipped
        if considered == 0:
            return None
        ratio = matched / considered
        if ratio >= 0.9:
            return "high"
        if ratio >= 0.6:
            return "medium"
        return "low"

    @staticmethod
    def _extract_quantity(element: BIMElement, source: str) -> Decimal | None:
        """Extract a quantity from an element based on the source specification.

        Supports:
        - Direct quantity keys: area_m2, volume_m3, length_m, weight_kg, count
        - Property references: property:xxx (e.g., property:fire_rating)
        """
        quantities = element.quantities or {}

        if source.startswith("property:"):
            prop_name = source[len("property:") :]
            value = (element.properties or {}).get(prop_name)
        elif source == "count":
            return Decimal("1")
        else:
            value = quantities.get(source)

        if value is None:
            return None

        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None

    # ── Model Diff ───────────────────────────────────────────────────────────

    async def compute_diff(
        self,
        new_model_id: uuid.UUID,
        old_model_id: uuid.UUID,
    ) -> BIMModelDiff:
        """Compute diff between two model versions by comparing elements.

        Elements are matched by stable_id. Changes detected via geometry_hash.
        Returns a BIMModelDiff with summary counts and detailed changes.
        """
        new_model = await self.get_model(new_model_id)
        old_model = await self.get_model(old_model_id)

        # Check if diff already exists
        existing = await self.diff_repo.get_by_pair(old_model_id, new_model_id)
        if existing is not None:
            return existing

        # Load all elements for both models
        old_elements, _ = await self.element_repo.list_for_model(old_model.id, offset=0, limit=50000)
        new_elements, _ = await self.element_repo.list_for_model(new_model.id, offset=0, limit=50000)

        old_by_sid = {e.stable_id: e for e in old_elements}
        new_by_sid = {e.stable_id: e for e in new_elements}

        old_ids = set(old_by_sid.keys())
        new_ids = set(new_by_sid.keys())

        added_ids = new_ids - old_ids
        deleted_ids = old_ids - new_ids
        common_ids = old_ids & new_ids

        modified: list[dict[str, Any]] = []
        unchanged = 0

        for sid in common_ids:
            old_e = old_by_sid[sid]
            new_e = new_by_sid[sid]

            changes: list[dict[str, Any]] = []
            # Detect what changed across all tracked fields
            if old_e.geometry_hash != new_e.geometry_hash:
                changes.append(
                    {
                        "field": "geometry_hash",
                        "old": old_e.geometry_hash,
                        "new": new_e.geometry_hash,
                    }
                )
            if old_e.element_type != new_e.element_type:
                changes.append(
                    {
                        "field": "element_type",
                        "old": old_e.element_type,
                        "new": new_e.element_type,
                    }
                )
            if old_e.quantities != new_e.quantities:
                changes.append(
                    {
                        "field": "quantities",
                        "old": old_e.quantities,
                        "new": new_e.quantities,
                    }
                )
            if old_e.properties != new_e.properties:
                changes.append(
                    {
                        "field": "properties",
                        "old": old_e.properties,
                        "new": new_e.properties,
                    }
                )

            if changes:
                modified.append(
                    {
                        "stable_id": sid,
                        "element_type": new_e.element_type,
                        "changes": changes,
                    }
                )
            else:
                unchanged += 1

        diff_summary = {
            "unchanged": unchanged,
            "modified": len(modified),
            "added": len(added_ids),
            "deleted": len(deleted_ids),
        }

        diff_details = {
            "modified": modified,
            "added": [
                {
                    "stable_id": sid,
                    "element_type": new_by_sid[sid].element_type,
                    "name": new_by_sid[sid].name,
                }
                for sid in added_ids
            ],
            "deleted": [
                {
                    "stable_id": sid,
                    "element_type": old_by_sid[sid].element_type,
                    "name": old_by_sid[sid].name,
                }
                for sid in deleted_ids
            ],
        }

        diff = BIMModelDiff(
            old_model_id=old_model_id,
            new_model_id=new_model_id,
            diff_summary=diff_summary,
            diff_details=diff_details,
        )
        diff = await self.diff_repo.create(diff)

        logger.info(
            "Model diff computed: %s -> %s (added=%d, deleted=%d, modified=%d, unchanged=%d)",
            old_model.name,
            new_model.name,
            len(added_ids),
            len(deleted_ids),
            len(modified),
            unchanged,
        )
        return diff

    async def get_diff(self, diff_id: uuid.UUID) -> BIMModelDiff:
        """Get a model diff by ID. Raises 404 if not found."""
        diff = await self.diff_repo.get(diff_id)
        if diff is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Model diff not found",
            )
        return diff

    # ── Element Groups ───────────────────────────────────────────────────────

    async def list_element_groups(
        self,
        project_id: uuid.UUID,
        *,
        model_id: uuid.UUID | None = None,
    ) -> list[BIMElementGroupResponse]:
        """List element groups for a project, optionally scoped to one model.

        For dynamic groups the cached ``element_ids`` snapshot is returned as
        ``member_element_ids``; it is NOT re-resolved on list calls. Callers
        that need up-to-the-second membership should PATCH the group (which
        triggers a re-resolve) or fetch via the dedicated resolve endpoint.
        """
        stmt = select(BIMElementGroup).where(BIMElementGroup.project_id == project_id)
        if model_id is not None:
            stmt = stmt.where(BIMElementGroup.model_id == model_id)
        stmt = stmt.order_by(BIMElementGroup.created_at.asc())
        result = await self.session.execute(stmt)
        groups = list(result.scalars().all())
        return [self._group_to_response(g) for g in groups]

    async def get_element_group(self, group_id: uuid.UUID) -> BIMElementGroup:
        """Get a BIM element group by id. Raises 404 if not found."""
        group = await self.session.get(BIMElementGroup, group_id)
        if group is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BIM element group not found",
            )
        return group

    async def create_element_group(
        self,
        project_id: uuid.UUID,
        payload: BIMElementGroupCreate,
        user_id: uuid.UUID | None,
    ) -> BIMElementGroupResponse:
        """Create a new element group.

        If ``payload.is_dynamic`` is True, the filter is evaluated immediately
        and the resolved element ids are cached in ``element_ids`` +
        ``element_count``. Otherwise the explicit ``element_ids`` list from
        the payload is stored verbatim.
        """
        group = BIMElementGroup(
            project_id=project_id,
            model_id=payload.model_id,
            name=payload.name,
            description=payload.description,
            is_dynamic=payload.is_dynamic,
            filter_criteria=payload.filter_criteria or {},
            element_ids=[str(eid) for eid in (payload.element_ids or [])],
            element_count=len(payload.element_ids or []),
            color=payload.color,
            created_by=user_id,
            metadata_=payload.metadata or {},
        )
        self.session.add(group)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An element group with this name already exists in the project",
            ) from exc

        # Dynamic groups: resolve membership now and cache it.
        if group.is_dynamic:
            resolved = await self._resolve_members_for_group(group)
            group.element_ids = [str(eid) for eid in resolved]
            group.element_count = len(resolved)
            await self.session.flush()

        await self.session.refresh(group)
        logger.info(
            "BIM element group created: %s (project=%s, dynamic=%s, count=%d)",
            group.name,
            project_id,
            group.is_dynamic,
            group.element_count,
        )
        return self._group_to_response(group)

    async def update_element_group(
        self,
        group_id: uuid.UUID,
        payload: BIMElementGroupUpdate,
    ) -> BIMElementGroupResponse:
        """Patch fields on a group and re-resolve the cache if needed.

        Re-resolution is triggered whenever ``filter_criteria``, ``model_id``,
        or ``is_dynamic`` is touched by the payload, OR when
        ``is_dynamic`` stays True and the caller supplied a new filter.
        """
        group = await self.get_element_group(group_id)

        fields = payload.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        # Normalise UUID list to str for JSON storage.
        if "element_ids" in fields and fields["element_ids"] is not None:
            fields["element_ids"] = [str(eid) for eid in fields["element_ids"]]
            fields["element_count"] = len(fields["element_ids"])

        re_resolve = "filter_criteria" in fields or "model_id" in fields or "is_dynamic" in fields

        for key, value in fields.items():
            setattr(group, key, value)

        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An element group with this name already exists in the project",
            ) from exc

        # Re-resolve the cache only for dynamic groups when their inputs moved.
        if re_resolve and group.is_dynamic:
            resolved = await self._resolve_members_for_group(group)
            group.element_ids = [str(eid) for eid in resolved]
            group.element_count = len(resolved)
            await self.session.flush()

        await self.session.refresh(group)
        logger.info(
            "BIM element group updated: %s (fields=%s)",
            group_id,
            list(fields.keys()),
        )
        return self._group_to_response(group)

    async def delete_element_group(self, group_id: uuid.UUID) -> None:
        """Delete a BIM element group. Raises 404 if not found."""
        group = await self.get_element_group(group_id)
        await self.session.delete(group)
        await self.session.flush()
        logger.info("BIM element group deleted: %s", group_id)

    async def resolve_element_group_members(
        self,
        group_id: uuid.UUID,
    ) -> list[uuid.UUID]:
        """Recompute the member list for a group and update its cache.

        Runs the current ``filter_criteria`` against ``oe_bim_element``,
        scoped to ``model_id`` (or all models in the project if
        ``model_id`` is NULL). Persists the refreshed ``element_ids`` +
        ``element_count`` snapshot and returns the new list.

        This works for both dynamic and static groups, but a static group
        will still overwrite its cached snapshot - callers that want to
        preserve a hand-curated static list should NOT call this method.
        """
        group = await self.get_element_group(group_id)
        resolved = await self._resolve_members_for_group(group)
        group.element_ids = [str(eid) for eid in resolved]
        group.element_count = len(resolved)
        await self.session.flush()
        return resolved

    async def _resolve_members_for_group(
        self,
        group: BIMElementGroup,
    ) -> list[uuid.UUID]:
        """Execute the filter against oe_bim_element for a group.

        Supported filter keys (``filter_criteria``):

        - ``element_type``: str | list[str] - exact match (OR across list).
        - ``category``: str | list[str] - match against ``properties.category``.
        - ``discipline``: str | list[str] - exact match.
        - ``storey``: str | list[str] - exact match.
        - ``property_filter``: dict[str, Any] - every key/value pair must be
          present inside ``properties`` JSON. On Postgres we use the native
          JSONB containment operator (``@>``); on SQLite we fall back to
          loading the candidates and filtering in Python.
        - ``name_contains``: str - case-insensitive substring match using
          ILIKE.

        Scope:
        - If ``group.model_id`` is set, we filter to that model only.
        - Otherwise we walk every ``BIMModel`` in ``group.project_id``.

        If the filter is empty and the group is static, we return the cached
        ``element_ids`` untouched so a static group's snapshot survives a
        re-resolve trigger; for dynamic empty filters we return the empty
        list.
        """
        criteria = group.filter_criteria or {}

        # Static group with no criteria: preserve the hand-curated snapshot.
        if not criteria and not group.is_dynamic:
            return [uuid.UUID(str(eid)) for eid in (group.element_ids or [])]

        base = select(BIMElement)

        if group.model_id is not None:
            base = base.where(BIMElement.model_id == group.model_id)
        else:
            # Constrain to every model belonging to the project.
            model_ids_stmt = select(BIMModel.id).where(BIMModel.project_id == group.project_id)
            model_ids_result = await self.session.execute(model_ids_stmt)
            model_ids = [row[0] for row in model_ids_result.all()]
            if not model_ids:
                return []
            base = base.where(BIMElement.model_id.in_(model_ids))

        # element_type (str or list) - OR-match.
        element_type = criteria.get("element_type")
        if element_type:
            values = element_type if isinstance(element_type, list) else [element_type]
            values = [v for v in values if v]
            if values:
                base = base.where(BIMElement.element_type.in_(values))

        # discipline (str or list) - OR-match.
        discipline = criteria.get("discipline")
        if discipline:
            values = discipline if isinstance(discipline, list) else [discipline]
            values = [v for v in values if v]
            if values:
                base = base.where(BIMElement.discipline.in_(values))

        # storey (str or list) - OR-match.
        storey = criteria.get("storey")
        if storey:
            values = storey if isinstance(storey, list) else [storey]
            values = [v for v in values if v]
            if values:
                base = base.where(BIMElement.storey.in_(values))

        # name_contains - case-insensitive substring.
        name_contains = criteria.get("name_contains")
        if name_contains:
            base = base.where(BIMElement.name.ilike(f"%{name_contains}%"))

        # category - lives inside the JSON ``properties`` column.
        category = criteria.get("category")
        property_filter = criteria.get("property_filter") or {}
        if not isinstance(property_filter, dict):
            property_filter = {}

        # Assemble the full expected-properties dict for JSON containment.
        expected_props: dict[str, Any] = dict(property_filter)
        category_values: list[str] = []
        if category:
            category_values = category if isinstance(category, list) else [category]
            category_values = [str(v) for v in category_values if v]

        # Cap dynamic group materialisation. Dynamic groups are interactive
        # (3D-viewer click) so we trade exhaustive coverage for a bounded
        # response time. 50K elements is 2× the largest realistic single
        # model and the truncation will be obvious in the UI element-count.
        _DYNAMIC_GROUP_CAP = 50_000
        base = base.limit(_DYNAMIC_GROUP_CAP)

        # Load candidates and filter in Python with the shared type-aware
        # predicate. We deliberately do NOT push property_filter down to a
        # PostgreSQL ``@>`` JSONB containment query: ``@>`` is exact, type-strict
        # and case-sensitive, whereas ``_property_value_matches`` is
        # case-insensitive, supports ``*``/``?`` wildcards and coerces scalar
        # types (so ``{"count": 42}`` matches a stored ``"42"``). A ``@>``
        # fast-path therefore returned a DIFFERENT element set on PostgreSQL
        # than on SQLite for the same group filter. The 50K cap bounds the
        # in-Python pass, so both backends now resolve groups identically.
        result = await self.session.execute(base)
        elements = list(result.scalars().all())

        def _matches(elem: BIMElement) -> bool:
            props = elem.properties or {}
            if category_values:
                cat = str(props.get("category") or "")
                if cat not in category_values:
                    return False
            # Use the shared type-aware helper so list/dict/None
            # property values match consistently with the quantity-map
            # rule engine.  Previously this used exact equality which
            # silently failed for multi-valued IFC properties.
            return all(
                BIMHubService._property_value_matches(props.get(key), value) for key, value in expected_props.items()
            )

        return [e.id for e in elements if _matches(e)]

    async def _scoped_element_ids_for_group(
        self,
        group: BIMElementGroup,
    ) -> list[uuid.UUID] | None:
        """Return the candidate-element id-list a group's filter runs over.

        Group-scope rule:
        - If ``group.model_id`` is set, restrict to that single model.
        - Else, restrict to every model in the group's project.

        Returns ``None`` (treated as "no candidates") when the project has
        no BIM models at all so the caller can short-circuit to ``[]``.
        """
        if group.model_id is not None:
            stmt = select(BIMElement.id).where(BIMElement.model_id == group.model_id)
            return list((await self.session.execute(stmt)).scalars().all())

        model_ids_stmt = select(BIMModel.id).where(BIMModel.project_id == group.project_id)
        model_ids = [row[0] for row in (await self.session.execute(model_ids_stmt)).all()]
        if not model_ids:
            return None
        stmt = select(BIMElement.id).where(BIMElement.model_id.in_(model_ids))
        return list((await self.session.execute(stmt)).scalars().all())

    # ── Smart Views - property catalog + preview (canonical-format) ──────────

    async def get_smart_view_property_catalog(
        self,
        model_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Build the Smart View property catalog for a single model.

        Returns the Identity / Geometry / Quantities / Properties grouped
        view of every queryable field, with sample distinct values and a
        source-format badge per row.  Caps element scan at 50K (the
        ``DYNAMIC_GROUP_CAP``) so federated models with hundreds of
        thousands of rows stay responsive.
        """
        from app.modules.bim_hub.smart_views import (
            _source_format_of,
            build_property_catalog,
            catalog_to_dict,
        )

        model = await self.model_repo.get(model_id)
        if model is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BIM model not found",
            )

        elements, _total = await self.element_repo.list_for_model(
            model_id,
            offset=0,
            limit=50_000,
        )

        catalog = build_property_catalog(
            list(elements),
            model_format=getattr(model, "model_format", None),
        )
        return {
            "model_id": model_id,
            "source_format": _source_format_of(getattr(model, "model_format", None)),
            "element_count": len(elements),
            "entries": [catalog_to_dict(e) for e in catalog],
        }

    async def preview_smart_view(
        self,
        rule_tree: dict[str, Any] | None,
        legacy_criteria: dict[str, Any] | None,
        model_id: uuid.UUID | None,
        project_id: uuid.UUID | None,
        sample_limit: int = 20,
    ) -> dict[str, Any]:
        """Resolve a (possibly unsaved) Smart View predicate to (count, ids).

        Accepts either a new ``rule_tree`` or the legacy ``filter_criteria``
        shape and runs it through the canonical evaluator.  When neither is
        supplied the predicate is treated as "match every element in scope".
        """
        from app.modules.bim_hub.smart_views import (
            evaluate as smartview_evaluate,
        )
        from app.modules.bim_hub.smart_views import (
            legacy_criteria_to_tree,
            validate_rule_tree,
        )

        if rule_tree is not None:
            tree = validate_rule_tree(rule_tree)
        elif legacy_criteria:
            tree = legacy_criteria_to_tree(legacy_criteria)
        else:
            tree = {"op": "AND", "rules": []}

        # Scope: explicit model_id wins; otherwise restrict to project's models.
        base = select(BIMElement)
        if model_id is not None:
            base = base.where(BIMElement.model_id == model_id)
        elif project_id is not None:
            mids = await self.session.execute(select(BIMModel.id).where(BIMModel.project_id == project_id))
            mid_list = [row[0] for row in mids.all()]
            if not mid_list:
                return {
                    "matched_count": 0,
                    "sample_element_ids": [],
                    "truncated": False,
                    "normalised_rule_tree": tree,
                }
            base = base.where(BIMElement.model_id.in_(mid_list))
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Either model_id or project_id is required for preview",
            )

        base = base.limit(50_000)
        result = await self.session.execute(base)
        elements = list(result.scalars().all())
        matched = smartview_evaluate(tree, elements)

        sample = [e.id for e in matched[: max(0, sample_limit)]]
        return {
            "matched_count": len(matched),
            "sample_element_ids": sample,
            "truncated": len(elements) >= 50_000,
            "normalised_rule_tree": tree,
        }

    @staticmethod
    def _group_to_response(group: BIMElementGroup) -> BIMElementGroupResponse:
        """Convert a ``BIMElementGroup`` ORM row to its API response.

        Populates ``member_element_ids`` from the cached ``element_ids``
        snapshot (which, for dynamic groups, is refreshed by the service
        whenever the filter or scope moves).
        """
        raw_ids = list(group.element_ids or [])
        parsed_ids: list[uuid.UUID] = []
        for raw in raw_ids:
            try:
                parsed_ids.append(uuid.UUID(str(raw)))
            except (ValueError, TypeError):
                continue
        return BIMElementGroupResponse(
            id=group.id,
            project_id=group.project_id,
            model_id=group.model_id,
            name=group.name,
            description=group.description,
            is_dynamic=group.is_dynamic,
            filter_criteria=group.filter_criteria or {},
            element_ids=parsed_ids,
            element_count=group.element_count,
            color=group.color,
            created_by=group.created_by,
            metadata_=group.metadata_ or {},
            created_at=group.created_at,
            updated_at=group.updated_at,
            member_element_ids=parsed_ids,
        )

    # ── BIM Federation (v4.0 / Slice 1) ──────────────────────────────────────

    async def create_federation(
        self,
        payload: FederationCreate,
    ) -> FederationResponse:
        """Persist a new federation header (no members yet)."""
        repo = BIMFederationRepository(self.session)
        federation = BIMFederation(
            project_id=payload.project_id,
            name=payload.name,
            description=payload.description,
            origin_offset=payload.origin_offset.model_dump(),
            shared_units=payload.shared_units,
        )
        await repo.create(federation)
        await self.session.refresh(federation)
        logger.info(
            "BIM federation created: %s (project=%s)",
            federation.name,
            federation.project_id,
        )
        return self._federation_to_response(federation)

    async def list_federations(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[FederationResponse], int]:
        """List federations for a project."""
        repo = BIMFederationRepository(self.session)
        rows, total = await repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
        )
        return [self._federation_to_response(f) for f in rows], total

    async def get_federation(
        self,
        federation_id: uuid.UUID,
    ) -> BIMFederation:
        """Fetch a federation with members or raise 404."""
        repo = BIMFederationRepository(self.session)
        federation = await repo.get(federation_id)
        if federation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Federation not found",
            )
        return federation

    async def get_federation_full(
        self,
        federation_id: uuid.UUID,
    ) -> FederationFullResponse:
        """Get a federation header plus its z-ordered member list."""
        federation = await self.get_federation(federation_id)
        return self._federation_to_full_response(federation)

    async def update_federation(
        self,
        federation_id: uuid.UUID,
        payload: FederationUpdate,
    ) -> FederationFullResponse:
        """Patch a federation header (members untouched)."""
        federation = await self.get_federation(federation_id)
        fields = payload.model_dump(exclude_unset=True)
        if "origin_offset" in fields and fields["origin_offset"] is not None:
            # FederationOriginOffset → dict
            offset = fields["origin_offset"]
            if hasattr(offset, "model_dump"):
                fields["origin_offset"] = offset.model_dump()
        if fields:
            repo = BIMFederationRepository(self.session)
            await repo.update_fields(federation_id, **fields)
        await self.session.refresh(federation)
        return self._federation_to_full_response(federation)

    async def delete_federation(self, federation_id: uuid.UUID) -> None:
        """Delete a federation. Members cascade via FK."""
        federation = await self.get_federation(federation_id)
        await self.session.delete(federation)
        await self.session.flush()
        logger.info("BIM federation deleted: %s", federation_id)

    async def add_federation_member(
        self,
        federation_id: uuid.UUID,
        payload: FederationModelAdd,
    ) -> FederationModelResponse:
        """Bind an existing BIM model to a federation.

        Verifies that the BIM model exists AND belongs to the same project
        as the federation - cross-project membership would break the
        project-ownership authorization model.
        """
        federation = await self.get_federation(federation_id)
        # The model must exist and live in the same project as the
        # federation. ``BIMModelRepository`` already enforces existence;
        # we re-check project here.
        model_repo = BIMModelRepository(self.session)
        model = await model_repo.get(payload.bim_model_id)
        if model is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BIM model not found",
            )
        if model.project_id != federation.project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "BIM model belongs to a different project - federations "
                    "can only contain models from the same project"
                ),
            )
        repo = BIMFederationRepository(self.session)
        # Duplicate guard - the DB-level UniqueConstraint will also fire,
        # but a friendly 409 beats a raw IntegrityError 500.
        existing = await repo.find_member(federation_id, payload.bim_model_id)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Model is already a member of this federation",
            )
        member = BIMFederationModel(
            federation_id=federation_id,
            bim_model_id=payload.bim_model_id,
            discipline=payload.discipline,
            color_hint=payload.color_hint,
            visible=payload.visible,
            z_order=payload.z_order,
        )
        try:
            await repo.add_member(member)
        except IntegrityError as exc:
            await self.session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Model is already a member of this federation",
            ) from exc
        await self.session.refresh(member)
        logger.info(
            "BIM federation member added: federation=%s model=%s",
            federation_id,
            payload.bim_model_id,
        )
        return FederationModelResponse.model_validate(member)

    async def remove_federation_member(
        self,
        federation_id: uuid.UUID,
        bim_model_id: uuid.UUID,
    ) -> None:
        """Remove a model from a federation by model id."""
        # Touching the federation ensures 404 propagates correctly when
        # the federation itself is missing/foreign.
        await self.get_federation(federation_id)
        repo = BIMFederationRepository(self.session)
        member = await repo.find_member(federation_id, bim_model_id)
        if member is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Federation member not found",
            )
        await repo.remove_member(member.id)
        await self.session.flush()
        logger.info(
            "BIM federation member removed: federation=%s model=%s",
            federation_id,
            bim_model_id,
        )

    @staticmethod
    def _federation_to_response(
        federation: BIMFederation,
    ) -> FederationResponse:
        return FederationResponse(
            id=federation.id,
            project_id=federation.project_id,
            name=federation.name,
            description=federation.description,
            origin_offset=federation.origin_offset or {},
            shared_units=federation.shared_units,
            member_count=len(federation.members or []),
            created_at=federation.created_at,
            updated_at=federation.updated_at,
        )

    @staticmethod
    def _federation_to_full_response(
        federation: BIMFederation,
    ) -> FederationFullResponse:
        members_sorted = sorted(
            federation.members or [],
            key=lambda m: (m.z_order, m.created_at),
        )
        return FederationFullResponse(
            id=federation.id,
            project_id=federation.project_id,
            name=federation.name,
            description=federation.description,
            origin_offset=federation.origin_offset or {},
            shared_units=federation.shared_units,
            member_count=len(members_sorted),
            created_at=federation.created_at,
            updated_at=federation.updated_at,
            members=[FederationModelResponse.model_validate(m) for m in members_sorted],
        )

    # ── Federation Type Tree (v4.0 / Slice 2) ───────────────────────────────

    async def aggregate_federation_type_tree(
        self,
        federation_id: uuid.UUID,
    ) -> FederationTypeTreeResponse:
        """Compute the federation-flat type tree.

        Walks every BIM element that belongs to a model that is a
        member of the federation, groups by ``element_type`` (= IfcClass),
        and returns:

        * one row per IfcClass with the total element count,
        * a per-member breakdown for the drill-down ("how many IfcWalls
          live in the ARCH model vs. the STRUCT model"),
        * a small ``sample_properties`` set drawn from the first
          representative element of each class so the colour-by-property
          UI knows which property keys are even worth offering.

        The "federation-flat, not per-model" shape mirrors BIMcollab Zoom
        and is the key UX insight: it makes "select every IfcDuctSegment
        across 12 federated models" a one-click operation.

        Empty federations / federations whose members have no elements
        return ``total_elements=0`` and ``classes=[]`` - the response is
        always well-formed.
        """
        # 1. Resolve federation + members (raises 404 when missing).
        federation = await self.get_federation(federation_id)
        members = list(federation.members or [])
        if not members:
            return FederationTypeTreeResponse(
                federation_id=federation_id,
                total_elements=0,
                classes=[],
            )

        # 2. Build a stable model_id → (model_name, discipline) map.
        #    The federation's stored discipline tag wins over the model
        #    row's own discipline (member-level override is the source
        #    of truth for federation context).
        member_model_ids = [m.bim_model_id for m in members]
        model_rows = (
            (await self.session.execute(select(BIMModel).where(BIMModel.id.in_(member_model_ids)))).scalars().all()
        )
        model_lookup: dict[uuid.UUID, tuple[str, str]] = {}
        for row in model_rows:
            model_lookup[row.id] = (row.name, row.discipline or "other")
        # Overlay the federation-member discipline (canonical for this fed).
        for member in members:
            existing = model_lookup.get(member.bim_model_id)
            if existing is None:
                # Stale member referencing a deleted model - surface a
                # neutral placeholder so the row is still countable.
                model_lookup[member.bim_model_id] = (
                    f"model-{str(member.bim_model_id)[:8]}",
                    member.discipline or "other",
                )
            else:
                model_lookup[member.bim_model_id] = (
                    existing[0],
                    member.discipline or existing[1],
                )

        # 3. Aggregate per (model_id, ifc_class).
        #    SQLAlchemy func.count on a non-nullable PK column is the
        #    fast path across all supported dialects (SQLite + Postgres).
        agg_stmt = (
            select(
                BIMElement.model_id,
                BIMElement.element_type,
                func.count(BIMElement.id).label("element_count"),
            )
            .where(BIMElement.model_id.in_(member_model_ids))
            .group_by(BIMElement.model_id, BIMElement.element_type)
        )
        agg_rows = (await self.session.execute(agg_stmt)).all()
        if not agg_rows:
            return FederationTypeTreeResponse(
                federation_id=federation_id,
                total_elements=0,
                classes=[],
            )

        # 4. Pivot to {ifc_class -> {model_id -> count}} with a parallel
        #    {ifc_class -> total} for sort + total computation.
        class_totals: dict[str, int] = {}
        class_per_model: dict[str, dict[uuid.UUID, int]] = {}
        for model_id, element_type, element_count in agg_rows:
            # NULL / empty element_type rolls up under "Unclassified" so
            # they never silently disappear from the tree.
            ifc_class = element_type if element_type else "Unclassified"
            class_totals[ifc_class] = class_totals.get(ifc_class, 0) + int(element_count)
            per_model = class_per_model.setdefault(ifc_class, {})
            per_model[model_id] = per_model.get(model_id, 0) + int(element_count)

        # 5. Pull one representative element per class to extract the
        #    sample_properties - capped at 6 keys so the UI tooltip
        #    stays readable.
        #    A single subquery per class would be cleaner but Postgres
        #    + SQLite both run this fine as N small queries (N = number
        #    of distinct classes, typically < 50). For very wide models
        #    we could swap to DISTINCT ON; the current shape keeps
        #    portability simple.
        sample_props: dict[str, list[str]] = {}
        for ifc_class in class_totals:
            element_type_filter = (
                BIMElement.element_type == ifc_class
                if ifc_class != "Unclassified"
                else BIMElement.element_type.is_(None)
            )
            sample_stmt = (
                select(BIMElement.properties)
                .where(
                    BIMElement.model_id.in_(member_model_ids),
                    element_type_filter,
                )
                .limit(1)
            )
            row = (await self.session.execute(sample_stmt)).scalar_one_or_none()
            if isinstance(row, dict):
                sample_props[ifc_class] = list(row.keys())[:6]
            else:
                sample_props[ifc_class] = []

        # 6. Materialise the response, sorted by element_count DESC. Ties
        #    break by ifc_class ASC so the order is fully deterministic
        #    (tests + UI snapshots depend on this).
        classes_payload: list[FederationTypeTreeClass] = []
        for ifc_class in sorted(class_totals.keys(), key=lambda c: (-class_totals[c], c)):
            per_model = class_per_model.get(ifc_class, {})
            breakdown_rows: list[FederationTypeTreeMember] = []
            # Sort the breakdown by element_count DESC then model_name
            # ASC for a stable visual order across renders.
            sorted_pairs = sorted(
                per_model.items(),
                key=lambda kv: (-kv[1], model_lookup.get(kv[0], ("", ""))[0]),
            )
            for model_id, count in sorted_pairs:
                model_name, discipline = model_lookup.get(
                    model_id,
                    (f"model-{str(model_id)[:8]}", "other"),
                )
                breakdown_rows.append(
                    FederationTypeTreeMember(
                        model_id=model_id,
                        model_name=model_name,
                        discipline=discipline,
                        element_count=int(count),
                    )
                )
            classes_payload.append(
                FederationTypeTreeClass(
                    ifc_class=ifc_class,
                    display_name=_humanise_ifc_class(ifc_class),
                    element_count=int(class_totals[ifc_class]),
                    member_breakdown=breakdown_rows,
                    sample_properties=sample_props.get(ifc_class, []),
                )
            )

        total_elements = sum(class_totals.values())
        return FederationTypeTreeResponse(
            federation_id=federation_id,
            total_elements=total_elements,
            classes=classes_payload,
        )

    # ── Federation Health (v7.x) ─────────────────────────────────────────────

    async def compute_federation_health(
        self,
        federation_id: uuid.UUID,
    ) -> FederationHealthResponse:
        """Classify every member model into a readiness state.

        Resolves each member's underlying ``BIMModel`` and buckets it:

        * ``missing``    - the link points at a model row that no longer
          exists (dangling reference after the model was deleted).
        * ``failed``     - the model's conversion pipeline reported failure.
        * ``processing`` - the model is still importing / converting.
        * ``empty``      - the model is ready but extracted zero elements.
        * ``stale``      - the model is ready and non-empty but was last
          updated noticeably earlier than the freshest member (a likely
          superseded discipline that was never re-uploaded).
        * ``ready``      - the model is ready, non-empty, and fresh.

        The report is a pure read-only computation; nothing is persisted.
        Empty federations return a well-formed ``no_members`` report
        (``score=0.0``) rather than raising.
        """
        federation = await self.get_federation(federation_id)
        members = list(federation.members or [])
        if not members:
            return FederationHealthResponse(
                federation_id=federation_id,
                overall_state="no_members",
            )

        # Batch-resolve the underlying model rows so we never N+1.
        member_model_ids = [m.bim_model_id for m in members]
        model_rows = (
            (await self.session.execute(select(BIMModel).where(BIMModel.id.in_(member_model_ids)))).scalars().all()
        )
        models_by_id = {row.id: row for row in model_rows}

        # The "freshest" member anchors staleness: any ready+non-empty
        # member that lags the freshest by more than the threshold is stale.
        ready_update_times = [
            models_by_id[m.bim_model_id].updated_at
            for m in members
            if m.bim_model_id in models_by_id and models_by_id[m.bim_model_id].updated_at is not None
        ]
        newest = max(ready_update_times) if ready_update_times else None
        oldest = min(ready_update_times) if ready_update_times else None
        spread_days = (newest - oldest).days if (newest and oldest) else None

        member_reports: list[FederationMemberHealth] = []
        for member in members:
            model = models_by_id.get(member.bim_model_id)
            discipline = member.discipline or (model.discipline if model else None) or "other"
            report = _classify_federation_member(
                member_id=member.id,
                bim_model_id=member.bim_model_id,
                discipline=discipline,
                model=model,
                newest_update=newest,
            )
            member_reports.append(report)

        return _aggregate_federation_health(federation_id, member_reports, spread_days)

    # ── Federation Snapshot & Diff (v7.x) ────────────────────────────────────

    async def capture_federation_snapshot(
        self,
        federation_id: uuid.UUID,
    ) -> FederationSnapshot:
        """Build a portable, storage-free composition fingerprint.

        Captures the current member set with each member's discipline,
        resolved model name, version, and live element count. The FE
        exports this as JSON and can upload an older one later to diff
        against ``capture_federation_snapshot`` taken at compare time.
        """
        federation = await self.get_federation(federation_id)
        members = list(federation.members or [])
        snapshot_members: list[FederationSnapshotMember] = []
        total_elements = 0
        if members:
            member_model_ids = [m.bim_model_id for m in members]
            model_rows = (
                (await self.session.execute(select(BIMModel).where(BIMModel.id.in_(member_model_ids)))).scalars().all()
            )
            models_by_id = {row.id: row for row in model_rows}
            for member in sorted(members, key=lambda m: (m.z_order, m.created_at)):
                model = models_by_id.get(member.bim_model_id)
                element_count = model.element_count if model else 0
                total_elements += element_count
                snapshot_members.append(
                    FederationSnapshotMember(
                        bim_model_id=member.bim_model_id,
                        model_name=(model.name if model else f"model-{str(member.bim_model_id)[:8]}"),
                        discipline=member.discipline or (model.discipline if model else None) or "other",
                        element_count=element_count,
                        version=(model.version if model else None),
                    )
                )

        return FederationSnapshot(
            schema_version="1",
            federation_id=federation_id,
            name=federation.name,
            captured_at=datetime.now(UTC),
            member_count=len(snapshot_members),
            total_elements=total_elements,
            members=snapshot_members,
        )

    async def diff_federation_snapshot(
        self,
        federation_id: uuid.UUID,
        old_snapshot: FederationSnapshot,
    ) -> FederationDiffResponse:
        """Diff a caller-supplied prior snapshot against the live state.

        The "new" side is captured live at request time so the diff always
        reflects reality, never a second stale upload. Bucketing is by
        ``bim_model_id``: present-in-both => changed/unchanged (by element
        count), new-only => added, old-only => removed.
        """
        # Touch the federation so a missing/foreign id 404s consistently.
        new_snapshot = await self.capture_federation_snapshot(federation_id)
        return diff_federation_snapshots(federation_id, old_snapshot, new_snapshot)
