# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Demo seed data for the clash (BIM clash detection) module.

Loaded on demand via ``await seed_clash(session, project_ids)``. The
coordination_hub dashboard aggregates clash KPIs from
:class:`app.modules.clash.models.ClashRun` and
:class:`app.modules.clash.models.ClashResult` (results joined to their run
by ``ClashResult.run_id == ClashRun.id`` and filtered by
``ClashRun.project_id``); with no clash data the dashboard shows zeros.
This seeder fills one completed run per covered project plus a realistic
spread of result rows across the review-workflow statuses so the
traffic-light KPIs, the discipline matrix and the open-clash list all
render with meaningful demo data.

The run references EXISTING ``app.modules.bim_hub.models.BIMModel`` rows
for the project when available (it never creates BIM models); when a
project has no models the result rows fall back to synthetic model ids so
the demo still populates. Safe to call repeatedly: if a ClashRun already
exists for the first project id the seeder returns ``{}`` immediately.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bim_hub.models import BIMModel
from app.modules.clash.models import ClashCluster, ClashResult, ClashRun

logger = logging.getLogger(__name__)

# Flagship demo project - always covered when present in the input list.
FLAGSHIP_PROJECT_ID = uuid.UUID("f1a95000-0001-4a00-8b00-000000000001")

# Review-workflow status mix for the seeded result rows. Mirrors
# ``clash.schemas.CLASH_STATUSES`` and the coordination_hub dashboard
# buckets: OPEN = (new, active, reviewed); resolved-style = (approved,
# resolved); ignored = (ignored). Counts here sum to 20 rows per run.
_STATUS_MIX: list[tuple[str, int]] = [
    ("new", 7),
    ("active", 4),
    ("reviewed", 3),
    ("approved", 2),
    ("resolved", 2),
    ("ignored", 2),
]

# Demo clashing element pairs. Each tuple is
# ``(a_discipline, a_type, b_discipline, b_type, clash_type)`` and is
# cycled across the result rows so the discipline matrix has real spread.
_PAIR_SPECS: list[tuple[str, str, str, str, str]] = [
    ("Mechanical", "Duct", "Structural", "Beam", "hard"),
    ("Plumbing", "Pipe", "Structural", "Slab", "hard"),
    ("Electrical", "Cable Tray", "Mechanical", "Duct", "clearance"),
    ("Mechanical", "AHU", "Architectural", "Wall", "clearance"),
    ("Plumbing", "Pipe", "Electrical", "Conduit", "hard"),
    ("Structural", "Column", "Architectural", "Door", "hard"),
    ("Mechanical", "Pipe", "Structural", "Beam", "clearance"),
]

# Severity ladder reused round-robin so the by_severity KPI is populated.
_SEVERITIES: list[str] = ["critical", "high", "medium", "low"]


def _signature(a_stable: str, b_stable: str, clash_type: str) -> tuple[str, str]:
    """Return ``(signature, signature_hash)`` for an element pair.

    ``signature`` is the first 16 hex of a stable sha1 over the ordered
    pair and clash type (mirrors the engine's run-independent identity);
    ``signature_hash`` is the full 40-hex sha1. Deterministic so re-runs of
    this seeder would hash the same physical pair to the same value.
    """
    lo, hi = sorted((a_stable, b_stable))
    digest = hashlib.sha1(f"{lo}|{hi}|{clash_type}".encode()).hexdigest()
    return digest[:16], digest


async def _models_for_project(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> list[uuid.UUID]:
    """Return existing BIM model ids for ``project_id`` (never creates any)."""
    stmt = select(BIMModel.id).where(BIMModel.project_id == project_id).order_by(BIMModel.created_at.desc()).limit(4)
    rows = (await session.execute(stmt)).scalars().all()
    return [r for r in rows]


async def seed_clash(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
) -> dict[str, int]:
    """Seed one completed clash run plus a status-spread result set per project.

    Args:
        session: Active async SQLAlchemy session (caller owns the commit).
        project_ids: Candidate projects to seed. At most the first 3 are
            covered, with the flagship project always included when present.

    Returns:
        A summary dict of inserted row counts keyed by entity
        (``runs`` / ``results`` / ``clusters``). Returns an empty dict when
        a clash run already exists for ``project_ids[0]`` (idempotent guard).
    """
    if not project_ids:
        return {}

    # --- idempotency guard: bail if the first project already has a run ---
    existing = (
        await session.execute(select(ClashRun.id).where(ClashRun.project_id == project_ids[0]).limit(1))
    ).scalar_one_or_none()
    if existing is not None:
        return {}

    # --- pick the covered projects (flagship first, then first 3 total) ---
    covered: list[uuid.UUID] = []
    if FLAGSHIP_PROJECT_ID in project_ids:
        covered.append(FLAGSHIP_PROJECT_ID)
    for pid in project_ids:
        if pid not in covered:
            covered.append(pid)
        if len(covered) >= 3:
            break

    counts: dict[str, int] = {"runs": 0, "results": 0, "clusters": 0}
    now = datetime.now(UTC)

    for proj_idx, project_id in enumerate(covered):
        model_ids = await _models_for_project(session, project_id)
        # Reference real model ids when available; otherwise fall back to
        # synthetic ids so the demo still populates a result set.
        if model_ids:
            a_model_id = model_ids[0]
            b_model_id = model_ids[1] if len(model_ids) > 1 else model_ids[0]
        else:
            a_model_id = uuid.uuid4()
            b_model_id = uuid.uuid4()
        model_ids_json = [str(m) for m in model_ids] if model_ids else [str(a_model_id), str(b_model_id)]

        started = now - timedelta(days=2, hours=proj_idx)
        completed = started + timedelta(minutes=4)

        run = ClashRun(
            project_id=project_id,
            name="Coordination clash run",
            description="Federated MEP vs structural coordination pass (demo data).",
            model_ids=model_ids_json,
            clash_type="both",
            ignore_same_model=False,
            tolerance_m=0.01,
            clearance_m=0.025,
            mode="cross_discipline",
            status="completed",
            element_count=1840,
            total_clashes=sum(n for _, n in _STATUS_MIX),
            summary={},
            created_by="demo-seed",
            completed_at=completed,
        )
        session.add(run)
        await session.flush()
        run_id = run.id
        counts["runs"] += 1

        # Build the status-spread result rows for this run. Track local
        # by-status / by-type / by-severity tallies so the run summary cache
        # is filled without lazy-loading run.results after flush.
        status_sequence: list[str] = []
        for status_value, repeat in _STATUS_MIX:
            status_sequence.extend([status_value] * repeat)

        by_status: dict[str, int] = {}
        by_type: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        cluster_members: dict[int, int] = {}

        for row_idx, status_value in enumerate(status_sequence):
            a_disc, a_type, b_disc, b_type, clash_kind = _PAIR_SPECS[row_idx % len(_PAIR_SPECS)]
            severity = _SEVERITIES[row_idx % len(_SEVERITIES)]
            a_stable = f"seed-{project_id}-A-{row_idx:03d}"
            b_stable = f"seed-{project_id}-B-{row_idx:03d}"
            signature, signature_hash = _signature(a_stable, b_stable, clash_kind)

            hard = clash_kind == "hard"
            penetration = round(0.015 + (row_idx % 5) * 0.012, 4) if hard else 0.0
            distance = 0.0 if hard else round(0.008 + (row_idx % 4) * 0.004, 4)
            storey = row_idx % 4

            session.add(
                ClashResult(
                    run_id=run_id,
                    a_element_id=uuid.uuid4(),
                    b_element_id=uuid.uuid4(),
                    a_stable_id=a_stable,
                    b_stable_id=b_stable,
                    a_name=f"{a_type} A-{row_idx + 1:03d}",
                    b_name=f"{b_type} B-{row_idx + 1:03d}",
                    a_discipline=a_disc,
                    b_discipline=b_disc,
                    a_element_type=a_type,
                    b_element_type=b_type,
                    a_element_system="",
                    b_element_system="",
                    a_model_id=a_model_id,
                    b_model_id=b_model_id,
                    a_storey=storey,
                    b_storey=storey,
                    clash_type=clash_kind,
                    penetration_m=penetration,
                    distance_m=distance,
                    cx=round(10.0 + row_idx * 1.5, 3),
                    cy=round(5.0 + row_idx * 0.75, 3),
                    cz=round(3.0 + storey * 3.2, 3),
                    status=status_value,
                    severity=severity,
                    signature=signature,
                    signature_hash=signature_hash,
                    signature_quality="strong",
                    tolerance_at_signature_time_mm=10.0,
                    assigned_to=None,
                    due_date=None,
                    comments=[],
                    watchers=[],
                    history=[],
                    meta={},
                    cluster_id=storey,
                    bcf_topic_guid=None,
                )
            )
            counts["results"] += 1
            by_status[status_value] = by_status.get(status_value, 0) + 1
            type_key = f"{a_disc} x {b_disc}"
            by_type[type_key] = by_type.get(type_key, 0) + 1
            by_severity[severity] = by_severity.get(severity, 0) + 1
            cluster_members[storey] = cluster_members.get(storey, 0) + 1

        # Cache the rendered summary on the run so the dashboard never has
        # to re-aggregate. ``meta`` columns are real dicts/lists per the
        # JSON column contract.
        run.summary = {
            "by_status": by_status,
            "by_type": by_type,
            "by_severity": by_severity,
        }
        session.add(run)

        # A few simple cluster labels (one per occupied storey bucket).
        for cluster_idx, size in sorted(cluster_members.items()):
            session.add(
                ClashCluster(
                    run_id=run_id,
                    cluster_id=cluster_idx,
                    label=f"Coordination cluster - Level {cluster_idx}",
                    size=size,
                )
            )
            counts["clusters"] += 1

    await session.flush()
    logger.info("Clash seed inserted: %s", counts)
    return counts
