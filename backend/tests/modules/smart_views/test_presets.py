# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Smart Views — preset catalogue + install tests.

Exercises the static catalogue surface (``BUILTIN_PRESETS``,
``list_presets``) and the service-layer ``install_preset`` path. Every
test uses a per-test temp SQLite per ``feedback_test_isolation.md``.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.modules.smart_views.evaluator import evaluate_smart_view
from app.modules.smart_views.presets import BUILTIN_PRESETS, get_preset
from app.modules.smart_views.schemas import (
    SmartViewCreate,
    SmartViewRule,
    SmartViewSelector,
)
from app.modules.smart_views.service import SmartViewService


def _register_models() -> None:
    """Eagerly register every ORM module referenced by the test DB."""
    import app.modules.bim_hub.models  # noqa: F401
    import app.modules.boq.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.smart_views.models  # noqa: F401
    import app.modules.users.models  # noqa: F401


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Spin up an isolated SQLite + seed one user + one project."""
    tmp_db = Path(tempfile.mkdtemp(prefix="oe-sv-pres-")) / "sv.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)

    from sqlalchemy import event as sa_event
    from sqlalchemy.engine import Engine

    @sa_event.listens_for(Engine, "connect")
    def _fk_on(dbapi_conn: object, _: object) -> None:
        cursor = dbapi_conn.cursor()  # type: ignore[union-attr]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    _register_models()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        from app.modules.projects.models import Project
        from app.modules.users.models import User

        owner = User(
            id=uuid.uuid4(),
            email=f"p-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x",
            full_name="P",
        )
        s.add(owner)
        await s.flush()
        project = Project(
            id=uuid.uuid4(),
            name="P",
            owner_id=owner.id,
            currency="EUR",
        )
        s.add(project)
        await s.commit()
        s.info["owner_id"] = owner.id
        s.info["project_id"] = project.id
        yield s
    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


# ── 1. Catalogue size is exactly 6 ────────────────────────────────────────


def test_builtin_presets_count() -> None:
    """The shipped catalogue must hold exactly 6 entries.

    Locks the public surface — adding/removing a preset should be a
    conscious change with a doc update, not an accident.
    """
    assert len(BUILTIN_PRESETS) == 6
    ids = [p["preset_id"] for p in BUILTIN_PRESETS]
    # Slugs are stable across releases (used as idempotency keys).
    assert ids == [
        "walls_by_fire_rating",
        "mep_by_discipline",
        "structural_concrete_c30",
        "doors_fire_rated",
        "exterior_walls",
        "spaces_by_zone",
    ]
    # No duplicates either.
    assert len(set(ids)) == len(ids)


# ── 2. Every preset round-trips through the Pydantic schema ──────────────


def test_each_preset_schema_valid() -> None:
    """Validate each preset through ``SmartViewRule`` + ``SmartViewCreate``.

    Catches drift (e.g. a typo'd operator) at import time rather than
    at install time.
    """
    scope_id = uuid.uuid4()
    for preset in BUILTIN_PRESETS:
        rules = [SmartViewRule.model_validate(r) for r in preset["rules"]]
        # SmartViewCreate is what the service uses internally; building
        # one proves the preset is install-shaped.
        payload = SmartViewCreate(
            scope_type="user",
            scope_id=scope_id,
            name=preset["name"],
            description=preset.get("description"),
            rules=rules,
            default_action=preset.get("default_action", "show_all"),
        )
        assert payload.name == preset["name"]
        assert len(payload.rules) == len(preset["rules"])


# ── 3. install_preset materialises a row ────────────────────────────────


@pytest.mark.asyncio
async def test_install_preset_creates_row(session: AsyncSession) -> None:
    """The first install creates a SmartView and returns it."""
    owner_id: uuid.UUID = session.info["owner_id"]
    service = SmartViewService(session)
    response = await service.install_preset(
        "walls_by_fire_rating",
        scope_type="user",
        scope_id=owner_id,
        user_id=owner_id,
    )
    await session.commit()
    assert response.name == "Walls by fire rating"
    assert response.scope_type == "user"
    assert response.scope_id == owner_id
    assert response.created_by == owner_id
    assert len(response.rules) == 1


# ── 4. Idempotency: same preset twice → same row ────────────────────────


@pytest.mark.asyncio
async def test_install_preset_idempotent(session: AsyncSession) -> None:
    """Installing the same preset twice returns the first row.

    Mirrors the service contract documented in ``install_preset``:
    idempotent on (created_by, scope_type, scope_id, name). A user who
    renamed the installed view CAN reinstall and get a fresh card —
    that's a property of the ``name`` lookup, not a bug.
    """
    owner_id: uuid.UUID = session.info["owner_id"]
    service = SmartViewService(session)
    first = await service.install_preset(
        "walls_by_fire_rating",
        scope_type="user",
        scope_id=owner_id,
        user_id=owner_id,
    )
    await session.commit()
    second = await service.install_preset(
        "walls_by_fire_rating",
        scope_type="user",
        scope_id=owner_id,
        user_id=owner_id,
    )
    await session.commit()
    assert second.id == first.id


# ── 5. Unknown preset → 404 ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_install_preset_unknown_id_404(session: AsyncSession) -> None:
    """A garbage preset_id raises ``HTTPException(404)``."""
    owner_id: uuid.UUID = session.info["owner_id"]
    service = SmartViewService(session)
    with pytest.raises(HTTPException) as exc:
        await service.install_preset(
            "no_such_preset",
            scope_type="user",
            scope_id=owner_id,
            user_id=owner_id,
        )
    assert exc.value.status_code == 404
    assert get_preset("no_such_preset") is None


# ── 6. Each preset's rules evaluate cleanly on a 3-element fixture ─────


def test_each_preset_evaluator_round_trip() -> None:
    """Run every preset against a synthetic 3-element fixture.

    We are not asserting *what* the evaluator paints, just that it
    completes without raising on any built-in preset. The fixture
    deliberately mixes element types so at least one rule per preset
    has something to chew on.
    """
    # The evaluator accepts plain dicts that look like BIMElement rows.
    elements = [
        {
            "stable_id": "W1",
            "element_type": "IfcWall",
            "properties": {
                "FireRating": "F90",
                "IsExternal": True,
                "Material": "C30/37 XC4",
            },
        },
        {
            "stable_id": "D1",
            "element_type": "IfcDoor",
            "properties": {"FireRating": "T30"},
        },
        {
            "stable_id": "S1",
            "element_type": "IfcSpace",
            "properties": {"LongName": "Office 101"},
        },
    ]
    for preset in BUILTIN_PRESETS:
        rules = [SmartViewRule.model_validate(r) for r in preset["rules"]]
        # Build a SmartView-like shim — the evaluator reads ``rules``,
        # ``default_action`` and nothing else from the view object.
        view = type(
            "ViewShim",
            (),
            {
                "rules": [r.model_dump(mode="json") for r in rules],
                "default_action": preset.get("default_action", "show_all"),
            },
        )()
        states, legend = evaluate_smart_view(view, elements)
        assert isinstance(states, dict)
        # Result must cover every element (defaults populate
        # untouched ones).
        assert set(states.keys()) == {"W1", "D1", "S1"}
        # Legend is either None or a dict — never a crash.
        assert legend is None or isinstance(legend, dict)


# ── 7. list_presets shape ───────────────────────────────────────────────


def test_list_presets_summary_shape() -> None:
    """Static catalogue surface returns the expected summary objects."""
    summaries = SmartViewService.list_presets()
    assert len(summaries) == 6
    for s in summaries:
        assert s.preset_id
        assert s.name
        assert s.description
        assert s.rule_count >= 1


# ── 8. SmartViewSelector validation rejects empty selectors in presets ──


@pytest.mark.asyncio
async def test_empty_selector_selector_is_rejected() -> None:
    """The schema validator must still reject an empty selector.

    Regression guard for the preset library — if someone ships a
    preset with no ifc_class AND no property, validation must fail
    *before* the row hits the DB.
    """
    with pytest.raises(ValueError):
        SmartViewSelector()


# ── 9. Cross-scope idempotency: same preset can be installed twice when
#       scoped differently (user vs project) ────────────────────────────


@pytest.mark.asyncio
async def test_install_preset_per_scope(session: AsyncSession) -> None:
    """A preset installed at user scope and at project scope coexist.

    The idempotency key is (created_by, scope_type, scope_id, name); two
    different scopes produce two different rows.
    """
    owner_id: uuid.UUID = session.info["owner_id"]
    project_id: uuid.UUID = session.info["project_id"]
    service = SmartViewService(session)
    a = await service.install_preset(
        "exterior_walls",
        scope_type="user",
        scope_id=owner_id,
        user_id=owner_id,
    )
    await session.commit()
    b = await service.install_preset(
        "exterior_walls",
        scope_type="project",
        scope_id=project_id,
        user_id=owner_id,
    )
    await session.commit()
    assert a.id != b.id
    assert a.scope_type == "user"
    assert b.scope_type == "project"
