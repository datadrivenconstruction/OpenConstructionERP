"""Demo seed data for the bim_hub module.

Groups the EXISTING ``BIMModel`` rows of a project into a coordination
federation and a couple of saved element groups so the coordination hub
dashboard has something to show. This seeder NEVER creates new BIMModel
rows: it only queries the models already imported for a project and wires
them together.

Per project (first 3 project_ids, always including the flagship) it creates:
    - 1 BIMFederation referencing every existing BIMModel of the project
    - N BIMFederationModel join rows (one per existing model)
    - up to 2 BIMElementGroup saved selections
    - 1 BIMModelDiff when at least 2 models exist

The seeder is idempotent: it short-circuits when a federation already
exists for ``project_ids[0]``, and it guards each federation insert by the
unique federation name per project.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bim_hub.models import (
    BIMElementGroup,
    BIMFederation,
    BIMFederationModel,
    BIMModel,
    BIMModelDiff,
)

logger = logging.getLogger(__name__)

FLAGSHIP_PROJECT_ID = uuid.UUID("f1a95000-0001-4a00-8b00-000000000001")

# Discipline palette used to tint each member model in the federated viewer.
_DISCIPLINE_COLORS: dict[str, str] = {
    "architectural": "#38bdf8",
    "structural": "#f59e0b",
    "mechanical": "#a78bfa",
    "electrical": "#22c55e",
    "plumbing": "#06b6d4",
    "other": "#94a3b8",
}


def _discipline_for(model: BIMModel, index: int) -> str:
    """Map an existing model to a canonical federation discipline tag."""
    raw = (model.discipline or "").strip().lower()
    if raw in _DISCIPLINE_COLORS:
        return raw
    if raw.startswith("arch"):
        return "architectural"
    if raw.startswith("struct"):
        return "structural"
    if raw.startswith("mech") or raw in {"hvac", "mep"}:
        return "mechanical"
    if raw.startswith("elec"):
        return "electrical"
    if raw.startswith("plumb"):
        return "plumbing"
    # Deterministic spread so a project of unlabelled models still looks
    # like a multi-discipline federation in the dashboard.
    spread = ("architectural", "structural", "mechanical")
    return spread[index % len(spread)]


async def _seed_one_project(session: AsyncSession, project_id: uuid.UUID) -> dict[str, int]:
    """Seed one project's federation, member links, groups and a diff.

    Returns counts for logging. Skips the project when it has no BIMModel
    rows at all (nothing to federate) or when its federation already exists.
    """
    counts = {
        "federations": 0,
        "federation_members": 0,
        "element_groups": 0,
        "model_diffs": 0,
    }

    # Pull the existing models for this project. We group what exists and
    # never create new BIMModel rows.
    models_result = await session.execute(
        select(BIMModel).where(BIMModel.project_id == project_id).order_by(BIMModel.created_at)
    )
    models: list[BIMModel] = list(models_result.scalars().all())
    if not models:
        return counts

    federation_name = "Coordination Federation"

    # Per-project guard: skip if this named federation already exists.
    existing_fed = (
        await session.execute(
            select(BIMFederation)
            .where(BIMFederation.project_id == project_id)
            .where(BIMFederation.name == federation_name)
        )
    ).scalar_one_or_none()
    if existing_fed is not None:
        return counts

    federation = BIMFederation(
        project_id=project_id,
        name=federation_name,
        description=(
            "Demo coordination federation grouping every imported discipline "
            "model into a single coordinated set for the coordination hub."
        ),
        origin_offset={"x": 0.0, "y": 0.0, "z": 0.0},
        shared_units="m",
    )
    session.add(federation)
    await session.flush()
    counts["federations"] += 1

    # One join row per existing model. Capture member ids locally - reading
    # federation.members would lazy-load and raise MissingGreenlet under async.
    member_model_ids: list[uuid.UUID] = []
    for index, model in enumerate(models):
        discipline = _discipline_for(model, index)
        member = BIMFederationModel(
            federation_id=federation.id,
            bim_model_id=model.id,
            discipline=discipline,
            color_hint=_DISCIPLINE_COLORS.get(discipline, _DISCIPLINE_COLORS["other"]),
            visible=True,
            z_order=index,
        )
        session.add(member)
        member_model_ids.append(model.id)
        counts["federation_members"] += 1
    await session.flush()

    # Two saved element groups scoped to the whole project (model_id NULL so
    # they span every model in the federation). element_ids stays empty: these
    # are dynamic groups resolved from filter_criteria on read.
    group_specs = [
        (
            "All Walls",
            "Every wall element across the federated models.",
            {"element_type": ["IfcWall", "IfcWallStandardCase", "Wall"]},
            "#38bdf8",
        ),
        (
            "Doors and Windows",
            "Openings across the federated models for clash review.",
            {"element_type": ["IfcDoor", "IfcWindow", "Door", "Window"]},
            "#f59e0b",
        ),
    ]
    for name, description, criteria, color in group_specs:
        existing_group = (
            await session.execute(
                select(BIMElementGroup)
                .where(BIMElementGroup.project_id == project_id)
                .where(BIMElementGroup.name == name)
            )
        ).scalar_one_or_none()
        if existing_group is not None:
            continue
        group = BIMElementGroup(
            project_id=project_id,
            model_id=None,
            name=name,
            description=description,
            is_dynamic=True,
            filter_criteria=criteria,
            element_ids=[],
            element_count=0,
            color=color,
            metadata_={"seed": True, "demo": True},
        )
        session.add(group)
        counts["element_groups"] += 1
    await session.flush()

    # A diff between the first two existing models, when the project has at
    # least two. diff_summary is non-nullable with no default, so it must be a
    # concrete dict. The (old_model_id, new_model_id) pair is unique, so guard.
    if len(member_model_ids) >= 2:
        old_model_id = member_model_ids[0]
        new_model_id = member_model_ids[1]
        existing_diff = (
            await session.execute(
                select(BIMModelDiff)
                .where(BIMModelDiff.old_model_id == old_model_id)
                .where(BIMModelDiff.new_model_id == new_model_id)
            )
        ).scalar_one_or_none()
        if existing_diff is None:
            diff = BIMModelDiff(
                old_model_id=old_model_id,
                new_model_id=new_model_id,
                diff_summary={
                    "added": 12,
                    "removed": 4,
                    "modified": 7,
                    "unchanged": 240,
                },
                diff_details={
                    "added": ["elem_a1", "elem_a2"],
                    "removed": ["elem_r1"],
                    "modified": ["elem_m1", "elem_m2"],
                },
                metadata_={"seed": True, "demo": True},
            )
            session.add(diff)
            counts["model_diffs"] += 1

    await session.flush()
    return counts


async def seed_bim_hub(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
) -> dict[str, int]:
    """Seed coordination federations grouping existing BIM models.

    Args:
        session: Open async DB session.
        project_ids: Candidate projects to seed against. The flagship project
            is always included when present; otherwise at most the first 3
            project ids are processed to stay light.

    Returns:
        Aggregated counts of rows inserted per entity. Returns an empty dict
        when a federation already exists for ``project_ids[0]`` (idempotent).
    """
    totals = {
        "federations": 0,
        "federation_members": 0,
        "element_groups": 0,
        "model_diffs": 0,
    }
    if not project_ids:
        return totals

    # Idempotency marker: if the first project already has any federation,
    # treat the whole seed as already applied and return immediately.
    marker = (
        await session.execute(select(BIMFederation).where(BIMFederation.project_id == project_ids[0]).limit(1))
    ).scalar_one_or_none()
    if marker is not None:
        logger.info("bim_hub seed: federation already present, skipping.")
        return {}

    # Pick the targets: always the flagship when present, plus the first few.
    targets: list[uuid.UUID] = []
    for pid in project_ids[:3]:
        if pid not in targets:
            targets.append(pid)
    if FLAGSHIP_PROJECT_ID in project_ids and FLAGSHIP_PROJECT_ID not in targets:
        targets.append(FLAGSHIP_PROJECT_ID)

    for pid in targets:
        counts = await _seed_one_project(session, pid)
        for key, value in counts.items():
            totals[key] += value

    await session.flush()
    logger.info("bim_hub seed complete: %s", totals)
    return totals
