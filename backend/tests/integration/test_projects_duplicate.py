"""Server-side project deep-clone — POST /v1/projects/{id}/duplicate/.

Pins the contract introduced when the frontend stopped doing a manual
``POST /`` + follow-up PATCH (which lost WBS, milestones, match settings,
validation_rule_sets, custom_fields and address geocoding state).

Coverage:

* Cloning a project with WBS rows + milestones + custom match settings +
  bespoke ``validation_rule_sets`` produces a new project with:
    - name suffixed " (Copy)"
    - a fresh UUID + fresh ``project_code``
    - identical scalar columns (region/currency/locale/address/...)
    - identical child counts but disjoint child IDs
    - WBS parent_id rewired through the new id mapping
    - cloned MatchProjectSettings (catalogue + classifier + threshold)
* A non-owner caller gets 403 on the source project (the auth check is
  reused from the rest of the router).
"""

from __future__ import annotations

import tempfile
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def _register_minimal_models() -> None:
    """Pull projects + users + audit models into Base.metadata."""
    import app.core.audit  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.users.models  # noqa: F401


@pytest_asyncio.fixture
async def temp_engine_and_factory():
    tmp_db = Path(tempfile.mkdtemp()) / "projects_duplicate_api.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)

    _register_minimal_models()

    from app.database import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    yield engine, factory, tmp_db

    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


_current_user_payload: dict[str, str] = {}


@pytest_asyncio.fixture
async def app(temp_engine_and_factory) -> AsyncGenerator[FastAPI, None]:
    _engine, factory, _tmp = temp_engine_and_factory

    from app.dependencies import (
        get_current_user_id,
        get_current_user_payload,
        get_session,
    )
    from app.modules.projects.router import router as projects_router

    fastapi_app = FastAPI()
    fastapi_app.include_router(projects_router, prefix="/api/v1/projects")

    async def _override_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def _override_payload() -> dict[str, str]:
        return dict(_current_user_payload)

    async def _override_user_id() -> str:
        return _current_user_payload.get("sub", "")

    fastapi_app.dependency_overrides[get_session] = _override_session
    fastapi_app.dependency_overrides[get_current_user_payload] = _override_payload
    fastapi_app.dependency_overrides[get_current_user_id] = _override_user_id

    yield fastapi_app


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _set_acting_user(user_id: uuid.UUID, role: str = "estimator") -> None:
    _current_user_payload.clear()
    _current_user_payload["sub"] = str(user_id)
    _current_user_payload["role"] = role


async def _seed_source_project(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert an owner User + a richly-populated source Project.

    Returns ``(owner_id, project_id)``.
    """
    from app.modules.projects.models import (
        MatchProjectSettings,
        Project,
        ProjectMilestone,
        ProjectWBS,
    )
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"owner-{uuid.uuid4().hex[:6]}@dup.io",
        hashed_password="x" * 60,
        full_name="Dup Owner",
        role="estimator",
        locale="en",
        is_active=True,
        metadata_={},
    )
    project = Project(
        id=uuid.uuid4(),
        owner_id=owner.id,
        name="Source Project",
        description="A rich source row to deep-clone",
        region="DACH",
        classification_standard="din276",
        currency="EUR",
        locale="de",
        validation_rule_sets=["din276", "gaeb", "boq_quality"],
        status="active",
        project_code="PRJ-2026-9001",
        project_type="commercial",
        phase="design",
        client_id="client-abc",
        address={"city": "Berlin", "country": "DE", "lat": 52.52, "lng": 13.40},
        contract_value="1500000.00",
        planned_start_date="2026-03-01",
        planned_end_date="2027-06-30",
        budget_estimate="1700000.00",
        contingency_pct="5",
        custom_fields={"ref_no": "BLN-2026-01", "wave": "A"},
        fx_rates=[{"code": "USD", "rate": "1.08", "label": "US Dollar"}],
        default_vat_rate="19",
        custom_units=["m3-loose", "stk"],
        metadata_={"imported_from": "test"},
    )
    # WBS — root + child to exercise the parent_id rewiring pass.
    root = ProjectWBS(
        id=uuid.uuid4(),
        project_id=project.id,
        code="1",
        name="Substructure",
        level=0,
        sort_order=10,
        wbs_type="cost",
        planned_cost="500000",
    )
    child = ProjectWBS(
        id=uuid.uuid4(),
        project_id=project.id,
        parent_id=root.id,
        code="1.1",
        name="Foundations",
        level=1,
        sort_order=20,
        wbs_type="cost",
        planned_cost="200000",
    )
    milestone = ProjectMilestone(
        id=uuid.uuid4(),
        project_id=project.id,
        name="Permit Approval",
        milestone_type="approval",
        planned_date="2026-04-15",
        status="pending",
        linked_payment_pct="10",
    )
    match = MatchProjectSettings(
        id=uuid.uuid4(),
        project_id=project.id,
        target_language="de",
        classifier="din276",
        auto_link_threshold=0.92,
        auto_link_enabled=True,
        mode="auto",
        sources_enabled=["bim", "pdf"],
        cost_database_id="DE_BERLIN",
    )

    async with factory() as session:
        session.add(owner)
        await session.flush()
        session.add(project)
        await session.flush()
        session.add_all([root, child, milestone, match])
        await session.commit()

    return owner.id, project.id


@pytest.mark.asyncio
async def test_duplicate_clones_full_project_graph(
    client: AsyncClient,
    temp_engine_and_factory,
) -> None:
    """End-to-end clone — every column, every child, fresh IDs."""
    from app.modules.projects.models import (
        MatchProjectSettings,
        Project,
        ProjectMilestone,
        ProjectWBS,
    )

    _engine, factory, _tmp = temp_engine_and_factory
    owner_id, source_id = await _seed_source_project(factory)
    _set_acting_user(owner_id)

    resp = await client.post(f"/api/v1/projects/{source_id}/duplicate/")
    assert resp.status_code == 201, resp.text
    body = resp.json()

    # Name suffix + fresh UUID + owner stays the caller.
    assert body["name"] == "Source Project (Copy)"
    assert body["id"] != str(source_id)
    assert body["owner_id"] == str(owner_id)
    # Fresh project_code (auto-generated PRJ-YYYY-####), distinct from source.
    assert body["project_code"] != "PRJ-2026-9001"
    assert body["project_code"].startswith("PRJ-")

    # Scalar / JSON columns carried over verbatim.
    assert body["region"] == "DACH"
    assert body["classification_standard"] == "din276"
    assert body["currency"] == "EUR"
    assert body["locale"] == "de"
    assert sorted(body["validation_rule_sets"]) == sorted(
        ["din276", "gaeb", "boq_quality"],
    )
    assert body["project_type"] == "commercial"
    assert body["phase"] == "design"
    assert body["address"] == {
        "city": "Berlin",
        "country": "DE",
        "lat": 52.52,
        "lng": 13.40,
    }
    assert body["custom_fields"] == {"ref_no": "BLN-2026-01", "wave": "A"}
    assert body["fx_rates"] == [
        {"code": "USD", "rate": "1.08", "label": "US Dollar"},
    ]
    assert body["default_vat_rate"] == "19"
    assert sorted(body["custom_units"]) == ["m3-loose", "stk"]
    assert body["metadata"] == {"imported_from": "test"}

    new_id = uuid.UUID(body["id"])

    # Drill down via the DB factory to assert child rows.
    async with factory() as session:
        # WBS — same count, fresh IDs, parent_id rewired through the
        # new mapping (root.parent_id is None, child.parent_id is the
        # NEW root's id, not the source root's id).
        src_wbs = (
            (
                await session.execute(
                    select(ProjectWBS).where(ProjectWBS.project_id == source_id),
                )
            )
            .scalars()
            .all()
        )
        new_wbs = (
            (
                await session.execute(
                    select(ProjectWBS).where(ProjectWBS.project_id == new_id),
                )
            )
            .scalars()
            .all()
        )
        assert len(new_wbs) == len(src_wbs) == 2
        src_ids = {n.id for n in src_wbs}
        new_ids = {n.id for n in new_wbs}
        assert src_ids.isdisjoint(new_ids)

        # Child node points at the cloned root, not the source root.
        new_by_code = {n.code: n for n in new_wbs}
        assert new_by_code["1"].parent_id is None
        assert new_by_code["1.1"].parent_id == new_by_code["1"].id
        # Ordinals + levels + planned_cost preserved.
        assert new_by_code["1"].sort_order == 10
        assert new_by_code["1.1"].sort_order == 20
        assert new_by_code["1"].level == 0
        assert new_by_code["1.1"].level == 1
        assert new_by_code["1"].planned_cost == "500000"

        # Milestones — same count, fresh IDs, scalar data preserved.
        src_ms = (
            (
                await session.execute(
                    select(ProjectMilestone).where(
                        ProjectMilestone.project_id == source_id,
                    ),
                )
            )
            .scalars()
            .all()
        )
        new_ms = (
            (
                await session.execute(
                    select(ProjectMilestone).where(
                        ProjectMilestone.project_id == new_id,
                    ),
                )
            )
            .scalars()
            .all()
        )
        assert len(new_ms) == len(src_ms) == 1
        assert new_ms[0].id != src_ms[0].id
        assert new_ms[0].name == "Permit Approval"
        assert new_ms[0].milestone_type == "approval"
        assert new_ms[0].planned_date == "2026-04-15"
        assert new_ms[0].linked_payment_pct == "10"

        # MatchProjectSettings — cloned with new project_id but same values.
        new_match = (
            await session.execute(
                select(MatchProjectSettings).where(
                    MatchProjectSettings.project_id == new_id,
                ),
            )
        ).scalar_one_or_none()
        assert new_match is not None
        assert new_match.target_language == "de"
        assert new_match.classifier == "din276"
        assert new_match.auto_link_threshold == pytest.approx(0.92)
        assert new_match.auto_link_enabled is True
        assert new_match.mode == "auto"
        assert sorted(new_match.sources_enabled) == ["bim", "pdf"]
        assert new_match.cost_database_id == "DE_BERLIN"

        # Source project + its children remain untouched.
        src_project = await session.get(Project, source_id)
        assert src_project is not None
        assert src_project.name == "Source Project"


@pytest.mark.asyncio
async def test_duplicate_rejects_non_owner(
    client: AsyncClient,
    temp_engine_and_factory,
) -> None:
    """A non-owner viewer cannot clone someone else's project."""
    from app.modules.users.models import User

    _engine, factory, _tmp = temp_engine_and_factory
    _owner_id, source_id = await _seed_source_project(factory)

    # Stand up a second user that owns nothing.
    other = User(
        id=uuid.uuid4(),
        email=f"other-{uuid.uuid4().hex[:6]}@dup.io",
        hashed_password="x" * 60,
        full_name="Other",
        role="estimator",
        locale="en",
        is_active=True,
        metadata_={},
    )
    async with factory() as session:
        session.add(other)
        await session.commit()

    _set_acting_user(other.id)
    resp = await client.post(f"/api/v1/projects/{source_id}/duplicate/")
    assert resp.status_code == 403, resp.text
