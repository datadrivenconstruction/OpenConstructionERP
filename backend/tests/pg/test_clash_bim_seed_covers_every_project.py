# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Coordination data has to reach every project, not the first few.

Both seeders took a prefix of the project list and said so in a comment, so
nothing read as broken: the code did exactly what it claimed. The screens it
leaves behind cannot show it either - a project with no federation and no clash
run renders the same empty coordination hub as a project whose seed crashed.

Two failures are pinned here rather than one, because lifting the cap alone
changes nothing on a database that has been seeded before. Both seeders also
read a marker off ``project_ids[0]`` and treated the whole seed as done when
that one project already had rows, so every project added or uncovered later
stayed empty however many times the seed re-ran. The per-project assertions
below are the ones that fail on that marker and pass without it.

Assertions go through each module's own project-scoped read, not through a row
count: coverage is what the screen asks for, and a count over the whole table
is satisfied by three well-fed projects and seven empty ones.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.modules.bim_hub.models import BIMFederation, BIMFederationModel, BIMModel
from app.modules.bim_hub.repository import BIMFederationRepository
from app.modules.bim_hub.seed import seed_bim_hub
from app.modules.clash.models import ClashResult
from app.modules.clash.repository import ClashRepository
from app.modules.clash.seed import seed_clash
from app.modules.projects.models import Project
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

# Every demo project carries a Revit model, an IFC model and a DWG drawing
# (``seed_demo_assets`` attaches all three), so two is the smallest set that
# still exercises the member links and the model diff.
_MODELS_PER_PROJECT = 2


async def _make_project(session, name: str, *, models: int = _MODELS_PER_PROJECT) -> uuid.UUID:
    """A project with ``models`` imported BIM models - what both seeders group."""
    owner_id = uuid.uuid4()
    session.add(
        User(
            id=owner_id,
            email=f"{name.replace(' ', '-').lower()}@example.test",
            hashed_password="x",
            full_name=f"{name} Owner",
            role="manager",
            locale="en",
            is_active=True,
            metadata_={},
        )
    )
    # Flushed on its own: the project's owner FK has no ORM relationship behind
    # it, so nothing orders the two inserts for us.
    await session.flush()
    project_id = uuid.uuid4()
    session.add(
        Project(
            id=project_id,
            name=name,
            description="Coordination seed fixture",
            currency="EUR",
            status="active",
            owner_id=owner_id,
            metadata_={},
        )
    )
    await session.flush()
    for index in range(models):
        session.add(
            BIMModel(
                project_id=project_id,
                name=f"{name} model {index + 1}",
                discipline=("architectural", "structural")[index % 2],
                model_format="ifc",
                version="1",
                status="ready",
                metadata_={},
            )
        )
    await session.flush()
    return project_id


async def _federations(session, project_id: uuid.UUID) -> int:
    """Federations the project's own screen would list."""
    _rows, total = await BIMFederationRepository(session).list_for_project(project_id)
    return int(total)


async def _runs(session, project_id: uuid.UUID) -> int:
    """Clash runs the project's own screen would list."""
    return len(await ClashRepository(session).list_runs(project_id))


async def test_every_project_gets_a_federation_and_a_run(pg_session) -> None:
    """Three projects in, three covered - the fourth and later ones too."""
    project_ids = [await _make_project(pg_session, f"Coordination {n}") for n in range(4)]

    await seed_bim_hub(pg_session, project_ids)
    await seed_clash(pg_session, project_ids)
    await pg_session.flush()

    for index, project_id in enumerate(project_ids):
        assert await _federations(pg_session, project_id) == 1, f"project {index} has no federation"
        assert await _runs(pg_session, project_id) == 1, f"project {index} has no clash run"


async def test_the_federation_names_the_models_the_project_already_had(pg_session) -> None:
    """A federation with no members is as empty as no federation at all."""
    project_id = await _make_project(pg_session, "Coordination members")

    await seed_bim_hub(pg_session, [project_id])
    await pg_session.flush()

    rows, _total = await BIMFederationRepository(pg_session).list_for_project(project_id)
    members = [m.bim_model_id for m in rows[0].members]
    own_models = (
        (await pg_session.execute(select(BIMModel.id).where(BIMModel.project_id == project_id))).scalars().all()
    )
    assert sorted(str(m) for m in members) == sorted(str(m) for m in own_models)


async def test_clash_results_reference_the_projects_own_models(pg_session) -> None:
    """The run has to point at models that exist, not at minted ids."""
    project_id = await _make_project(pg_session, "Coordination models")

    await seed_bim_hub(pg_session, [project_id])
    await seed_clash(pg_session, [project_id])
    await pg_session.flush()

    runs = await ClashRepository(pg_session).list_runs(project_id)
    own_models = {
        str(m)
        for m in (await pg_session.execute(select(BIMModel.id).where(BIMModel.project_id == project_id)))
        .scalars()
        .all()
    }
    referenced = (
        (await pg_session.execute(select(ClashResult.a_model_id).where(ClashResult.run_id == runs[0].id)))
        .scalars()
        .all()
    )
    assert referenced, "the run carries no results"
    assert {str(m) for m in referenced} <= own_models


async def test_a_project_seeded_later_is_not_locked_out_by_the_first(pg_session) -> None:
    """The assertion a marker read off ``project_ids[0]`` cannot pass.

    Both seeders used to short-circuit the whole call when the first project
    already had rows, which is exactly the state every re-run finds. A project
    that joined the estate afterwards was then unreachable by any number of
    re-seeds, and the two tests above would still have been green.
    """
    early = await _make_project(pg_session, "Coordination early")
    await seed_bim_hub(pg_session, [early])
    await seed_clash(pg_session, [early])
    await pg_session.flush()

    late = await _make_project(pg_session, "Coordination late")
    await seed_bim_hub(pg_session, [early, late])
    await seed_clash(pg_session, [early, late])
    await pg_session.flush()

    assert await _federations(pg_session, early) == 1, "the already-seeded project was federated twice"
    assert await _runs(pg_session, early) == 1, "the already-seeded project was run twice"
    assert await _federations(pg_session, late) == 1, "the later project was skipped by a first-project marker"
    assert await _runs(pg_session, late) == 1, "the later project was skipped by a first-project marker"


async def test_a_second_run_over_the_same_projects_adds_nothing(pg_session) -> None:
    project_ids = [await _make_project(pg_session, f"Coordination twice {n}") for n in range(2)]

    await seed_bim_hub(pg_session, project_ids)
    await seed_clash(pg_session, project_ids)
    await pg_session.flush()
    before = [(await _federations(pg_session, p), await _runs(pg_session, p)) for p in project_ids]

    await seed_bim_hub(pg_session, project_ids)
    await seed_clash(pg_session, project_ids)
    await pg_session.flush()

    after = [(await _federations(pg_session, p), await _runs(pg_session, p)) for p in project_ids]
    assert after == before


async def test_a_project_with_no_models_gets_no_federation(pg_session) -> None:
    """Nothing to group must stay nothing to group.

    Uncapping the seeder puts projects in front of it that the cap used to hide,
    including ones with no BIM models at all. The answer there is no federation
    - not an empty one, and not a crash on the member loop.
    """
    bare = await _make_project(pg_session, "Coordination bare", models=0)

    counts = await seed_bim_hub(pg_session, [bare])
    await pg_session.flush()

    assert counts["federations"] == 0
    assert await _federations(pg_session, bare) == 0
    orphan_members = (
        await pg_session.execute(
            select(func.count())
            .select_from(BIMFederationModel)
            .join(BIMFederation, BIMFederation.id == BIMFederationModel.federation_id)
            .where(BIMFederation.project_id == bare)
        )
    ).scalar_one()
    assert orphan_members == 0
