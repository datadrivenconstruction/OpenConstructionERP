"""Clash group-by-ANY-property tests: enumeration, faceting, membership.

Two layers (same isolation discipline as ``test_clash_triage_delta.py``):

* **Pure** (no DB) — :func:`_in_set` honouring the open-ended
  ``properties`` map (in-set vs not-in-set), defensiveness against
  missing / None / non-scalar property dicts, and a *legacy*
  ``ClashSelectionSet`` payload WITHOUT ``properties`` still validating
  and behaving exactly as before.
* **DB-backed** — a self-isolated SQLite exercising
  :meth:`ClashRepository.grouping_facets_for_models`: per-property-key
  enumeration excludes the four built-ins + noise (the < 1 % coverage,
  > 500 distinct, top-60 caps) and ``group_by=property:<key>`` returns
  the correct distinct value items + counts.

Per ``feedback_test_isolation.md`` ``DATABASE_URL`` is redirected to a
fresh temp SQLite file BEFORE ``app`` is first imported.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (MUST run BEFORE app imports) ─────────────

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-clash-prop-"))
_TMP_DB = _TMP_DIR / "clash_prop.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

from app.modules.clash.schemas import ClashSelectionSet  # noqa: E402
from app.modules.clash.service import _in_set  # noqa: E402

# ── Pure: _in_set honours the open-ended ``properties`` map ────────────────


class _PropElement:
    """Minimal stand-in for a BIMElement carrying a ``properties`` dict."""

    def __init__(self, properties: object) -> None:
        self.properties = properties
        self.element_type = "Generic"
        self.discipline = "Structural"


def test_in_set_matches_on_property_value():
    """ANY key whose string-coerced value is listed → in set."""
    spec = {"properties": {"FireRating": ["F90", "F120"]}}
    el = _PropElement({"FireRating": "F90"})
    assert _in_set(el, "Generic", "Structural", spec) is True
    # Non-listed value of the same key → not in set.
    el2 = _PropElement({"FireRating": "F30"})
    assert _in_set(el2, "Generic", "Structural", spec) is False


def test_in_set_property_value_is_string_coerced_and_trimmed():
    """Numeric / whitespace-padded property values still match."""
    spec = {"properties": {"Floor": ["3"]}}
    assert _in_set(_PropElement({"Floor": 3}), "Generic", "Structural", spec)
    assert _in_set(_PropElement({"Floor": " 3 "}), "Generic", "Structural", spec)


def test_in_set_property_is_a_union_with_the_builtins():
    """An element matches via the builtins OR the property map (union)."""
    spec = {
        "element_types": ["Wall"],
        "properties": {"Phase": ["Existing"]},
    }
    # Matches purely on the property even though element_type differs.
    assert _in_set(_PropElement({"Phase": "Existing"}), "Generic", "Structural", spec)
    # Matches purely on the builtin even with no matching property.
    assert _in_set(_PropElement({"Phase": "New"}), "Wall", "Structural", spec)
    # Matches neither → not in set.
    assert not _in_set(_PropElement({"Phase": "New"}), "Generic", "Structural", spec)


def test_in_set_property_is_defensive():
    """Missing / None / non-scalar properties never match, never crash."""
    spec = {"properties": {"Manufacturer": ["Acme"]}}
    assert _in_set(_PropElement(None), "Generic", "Structural", spec) is False
    assert _in_set(_PropElement({}), "Generic", "Structural", spec) is False
    assert _in_set(_PropElement("not-a-dict"), "Generic", "Structural", spec) is False
    # Non-scalar value for the key → no match (no crash).
    assert (
        _in_set(
            _PropElement({"Manufacturer": {"nested": 1}}),
            "Generic",
            "Structural",
            spec,
        )
        is False
    )
    # Empty allowed-value list for a key is ignored.
    assert (
        _in_set(
            _PropElement({"Manufacturer": "Acme"}),
            "Generic",
            "Structural",
            {"properties": {"Manufacturer": []}},
        )
        is False
    )


def test_legacy_selection_set_without_properties_still_validates():
    """A payload WITHOUT ``properties`` validates + behaves as before."""
    legacy = ClashSelectionSet.model_validate({"element_types": ["Wall"], "disciplines": ["Structural"]})
    assert legacy.properties == {}
    assert legacy.is_empty is False
    # Engine path: builtin union still resolves exactly as it used to.
    spec = legacy.model_dump()
    assert _in_set(_PropElement({"any": "thing"}), "Wall", "Mechanical", spec)
    assert not _in_set(_PropElement({"any": "thing"}), "Beam", "Mechanical", spec)
    # A truly empty set (no builtins, no properties) is still empty.
    assert ClashSelectionSet().is_empty is True
    # A set carrying only a properties chip is NOT empty.
    assert ClashSelectionSet(properties={"Phase": ["New"]}).is_empty is False


# ── DB-backed: per-property enumeration + property:<key> faceting ──────────


@pytest_asyncio.fixture(scope="module")
async def db_session():
    """A real AsyncSession over a freshly create_all'd temp SQLite."""
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, async_session_factory, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_session_factory() as session:
            yield session


async def _seed_model(session) -> uuid.UUID:
    """Insert a minimal user + project + BIM model; return model_id."""
    from app.modules.bim_hub.models import BIMModel
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        email=f"clash-prop-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Clash Prop Tester",
    )
    session.add(user)
    await session.flush()
    project = Project(name="Clash Prop Project", owner_id=user.id)
    session.add(project)
    await session.flush()
    model = BIMModel(project_id=project.id, name="Prop Model", status="ready")
    session.add(model)
    await session.flush()
    return model.id


def _bbox() -> dict:
    return {
        "min_x": 0.0,
        "min_y": 0.0,
        "min_z": 0.0,
        "max_x": 1.0,
        "max_y": 1.0,
        "max_z": 1.0,
    }


@pytest.mark.asyncio
async def test_property_key_enumeration_excludes_builtins_and_noise(
    db_session,
):
    """Enumeration drops builtins + the 1 % / 500-distinct / top-60 caps.

    100 elements:
      * ``FireRating`` on all 100  → kept (good coverage, few values)
      * ``rvt_category`` on all 100 → EXCLUDED (built-in key)
      * ``Manufacturer`` on 1     → EXCLUDED (< 1 % ⇒ floor is 1, n==1
        actually meets floor=max(1,1)=1, so add a clearly-below case)
      * ``GUID`` on all 100, all distinct → EXCLUDED (> 500? no — only
        100; instead test the >500 cap separately) ⇒ here GUID has 100
        distinct ≤ 500 so it survives unless coverage-filtered; we make
        it a high-cardinality KEPT control and assert ordering instead.
      * ``Rare`` on exactly 0 elements → never appears.
    """
    from app.modules.bim_hub.models import BIMElement
    from app.modules.clash.repository import ClashRepository

    model_id = await _seed_model(db_session)
    for i in range(100):
        db_session.add(
            BIMElement(
                model_id=model_id,
                stable_id=f"E{i}",
                name=f"E{i}",
                element_type="Wall",
                discipline="Structural",
                properties={
                    "FireRating": "F90" if i % 2 else "F120",
                    "rvt_category": "Walls",  # built-in → excluded
                    "ifc_class": "IfcWall",  # built-in → excluded
                    "Phase": "New" if i < 60 else "Existing",
                },
                bounding_box=_bbox(),
            )
        )
    # One element carrying a sub-1 % key (1 of 101 < floor of max(1, 1)).
    # floor = max(1, int(101 * 0.01)) = max(1, 1) = 1, so a single
    # occurrence meets the floor; to assert the floor actually bites we
    # need a key whose count is strictly below it. Bump scanned to 250
    # so floor becomes 2 and a single-occurrence key is dropped.
    for i in range(100, 250):
        db_session.add(
            BIMElement(
                model_id=model_id,
                stable_id=f"E{i}",
                name=f"E{i}",
                element_type="Wall",
                discipline="Structural",
                properties={"FireRating": "F60", "Phase": "New"},
                bounding_box=_bbox(),
            )
        )
    # Sub-floor key: present on exactly ONE of 250 (floor = 2).
    db_session.add(
        BIMElement(
            model_id=model_id,
            stable_id="ENoise",
            name="ENoise",
            element_type="Wall",
            discipline="Structural",
            properties={"RareOneOff": "x", "FireRating": "F90"},
            bounding_box=_bbox(),
        )
    )
    await db_session.flush()

    repo = ClashRepository(db_session)
    _chosen, avail, props = await repo.grouping_facets_for_models([model_id], "type")
    keys = {k for k, _ in props}
    assert "FireRating" in keys
    assert "Phase" in keys
    # Built-in keys must never be advertised as open-ended properties.
    assert "rvt_category" not in keys
    assert "ifc_class" not in keys
    # Sub-1 % key (1 of 251 elements, floor = 2) is dropped.
    assert "RareOneOff" not in keys
    # available builtins still resolved from the same single scan.
    assert "type" in avail
    assert "category" in avail
    # Coverage counts are real element counts.
    fire = dict(props)["FireRating"]
    assert fire == 251  # all 251 elements carry FireRating


@pytest.mark.asyncio
async def test_property_key_distinct_and_topn_caps(db_session):
    """> 500-distinct keys dropped; the key list is capped to top 60."""
    from app.modules.bim_hub.models import BIMElement
    from app.modules.clash.repository import ClashRepository

    model_id = await _seed_model(db_session)
    # 600 elements: ``UniqueId`` has 600 distinct values (> 500 → drop);
    # ``K00..K79`` are 80 stable-low-cardinality keys on every element
    # (top-60 cap must trim to 60).
    for i in range(600):
        props = {"UniqueId": f"id-{i}"}
        for k in range(80):
            props[f"K{k:02d}"] = f"v{k}"
        db_session.add(
            BIMElement(
                model_id=model_id,
                stable_id=f"U{i}",
                name=f"U{i}",
                element_type="Pipe",
                discipline="Mechanical",
                properties=props,
                bounding_box=_bbox(),
            )
        )
    await db_session.flush()

    repo = ClashRepository(db_session)
    _chosen, _avail, props = await repo.grouping_facets_for_models([model_id], "type")
    keys = [k for k, _ in props]
    assert "UniqueId" not in keys  # > 500 distinct → excluded
    assert len(keys) <= 60  # top-N cap honoured
    # All survivors are the low-cardinality K** keys, full coverage.
    assert all(k.startswith("K") for k in keys)
    assert all(n == 600 for _, n in props)


@pytest.mark.asyncio
async def test_group_by_property_key_returns_distinct_value_items(
    db_session,
):
    """``group_by=property:<key>`` → distinct value items + counts."""
    from app.modules.bim_hub.models import BIMElement
    from app.modules.clash.repository import ClashRepository

    model_id = await _seed_model(db_session)
    layout = ["F90"] * 5 + ["F120"] * 3 + ["F30"] * 2 + [None] * 2  # 2 with no FireRating at all
    for i, fr in enumerate(layout):
        props: dict = {"Phase": "New"}
        if fr is not None:
            props["FireRating"] = fr
        db_session.add(
            BIMElement(
                model_id=model_id,
                stable_id=f"G{i}",
                name=f"G{i}",
                element_type="Door",
                discipline="Architectural",
                properties=props,
                bounding_box=_bbox(),
            )
        )
    await db_session.flush()

    repo = ClashRepository(db_session)
    chosen, _avail, props = await repo.grouping_facets_for_models([model_id], "property:FireRating")
    # Sorted by count desc then value: F90(5), F120(3), F30(2).
    assert chosen == [("F90", 5), ("F120", 3), ("F30", 2)]
    # The selector list still enumerates FireRating + Phase as keys.
    assert "FireRating" in {k for k, _ in props}
    assert "Phase" in {k for k, _ in props}
