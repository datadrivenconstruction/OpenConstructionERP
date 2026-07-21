# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Multi-base match run: catalogue_ids round-trip + run_match fan-out.

Wave-2 lets a match session rank across several CWICR v3 catalogues at
once. These tests pin the three guarantees the backend must uphold:

* ``catalogue_ids`` round-trips create -> read (deduped, order preserved),
  stored on ``MatchSession.metadata_`` with no new DB column.
* a run with two catalogues fans the per-group rank out across both bases,
  stamps each candidate with its distinct source region, and keeps the same
  rate code from two bases as two distinct base-tagged candidates while
  collapsing only exact ``(base, code)`` repeats.
* a single-catalogue run is byte-identical to before - one rank call per
  group, candidates stored verbatim (no fan-out stamping, no dedup).

The tests run against a throwaway PostgreSQL database (never the
production DB) and monkeypatch the matcher factory so no Qdrant / embedding
model is required - the fan-out plumbing is what's under test here.
"""

from __future__ import annotations

import uuid

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.match_service.envelope import ElementEnvelope, MatchCandidate
from app.modules.match_elements import schemas
from app.modules.match_elements.models import MatchGroup, MatchSession
from app.modules.match_elements.service import MatchElementsService
from tests._pg import isolated_engine

_DE = "DE_BERLIN"
_US = "USA_USD"


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def factory():
    """Per-test throwaway PostgreSQL database cloned from the schema template."""
    async with isolated_engine() as engine:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _seed_project(db: AsyncSession) -> uuid.UUID:
    """Insert a real User + Project so MatchSession / settings can FK to it."""
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        id=uuid.uuid4(),
        email=f"mb-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x" * 60,
        full_name="Multibase Test",
        role="estimator",
        locale="en",
        is_active=True,
        metadata_={},
    )
    project = Project(
        id=uuid.uuid4(),
        name="Multibase Test Project",
        owner_id=user.id,
        region="DACH",
        status="active",
    )
    db.add(user)
    await db.flush()
    db.add(project)
    await db.flush()
    return project.id


class _FakeMatcher:
    """Records every ``rank`` call and returns fixed candidates.

    Returns two candidates that share code ``R-001`` (so the merge dedup is
    exercised) plus a distinct ``R-002``. ``region_code`` starts empty so the
    test can prove the fan-out stamps it and the single-base path does not.
    Fresh candidate objects each call - the fan-out mutates ``region_code`` in
    place, so a shared list would leak stamps across bases.
    """

    name = "vector"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def rank(
        self,
        *,
        envelope: ElementEnvelope,
        project_id: uuid.UUID,
        catalogue_id=None,
        top_k: int = 10,
    ) -> list[MatchCandidate]:
        self.calls.append({"catalogue_id": catalogue_id, "top_k": top_k})

        def _c(code: str, score: float) -> MatchCandidate:
            return MatchCandidate(
                id=str(uuid.uuid4()),
                code=code,
                description=f"rate {code}",
                unit="m3",
                unit_rate=100.0,
                currency="EUR",
                score=score,
                region_code="",
            )

        return [_c("R-001", 0.90), _c("R-001", 0.90), _c("R-002", 0.80)]


async def _make_text_session(
    svc: MatchElementsService,
    db: AsyncSession,
    project_id: uuid.UUID,
    *,
    catalogue_ids: list[str] | None,
) -> MatchSession:
    """Create a one-line text session (yields exactly one match group)."""
    spec = schemas.SessionCreate(
        project_id=project_id,
        source="text",
        name="mb session",
        catalogue_id=(catalogue_ids[0] if catalogue_ids else None),
        catalogue_ids=catalogue_ids,
        text_inputs=["Concrete wall C30/37, 240mm"],
    )
    read = await svc.create_session(db, spec, uuid.uuid4())
    row = await db.get(MatchSession, read.id)
    assert row is not None
    return row


async def _methods_for(db: AsyncSession, session_id: uuid.UUID, method: str) -> list[dict]:
    """Return the persisted candidate dicts for the (single) group's method."""
    rows = (await db.execute(select(MatchGroup).where(MatchGroup.session_id == session_id))).scalars().all()
    assert len(rows) == 1, f"expected one text group, got {len(rows)}"
    return list((rows[0].methods or {}).get(method) or [])


# ── catalogue_ids round-trip ──────────────────────────────────────────────


async def test_catalogue_ids_round_trips_create_to_read(factory) -> None:
    """catalogue_ids persist on the session and read back deduped + ordered."""
    svc = MatchElementsService()
    async with factory() as db:
        project_id = await _seed_project(db)
        # Intentional duplicate + reversed order to prove dedup / order-preserve.
        spec = schemas.SessionCreate(
            project_id=project_id,
            source="text",
            name="round-trip",
            catalogue_id=_DE,
            catalogue_ids=[_DE, _DE, _US],
            text_inputs=["anything"],
        )
        created = await svc.create_session(db, spec, uuid.uuid4())
        assert created.catalogue_ids == [_DE, _US]
        assert created.catalogue_id == _DE

        # Re-read through a fresh service call - value must survive the round-trip.
        read = await svc.get_session(db, created.id)
        assert read.catalogue_ids == [_DE, _US]

        # And it lives in metadata_, not a new column.
        row = await db.get(MatchSession, created.id)
        assert (row.metadata_ or {}).get("catalogue_ids") == [_DE, _US]


async def test_catalogue_ids_update_and_clear(factory) -> None:
    """PATCH replaces the set; an explicit empty list clears it."""
    svc = MatchElementsService()
    async with factory() as db:
        project_id = await _seed_project(db)
        created = await svc.create_session(
            db,
            schemas.SessionCreate(
                project_id=project_id,
                source="text",
                catalogue_ids=[_DE],
                text_inputs=["x"],
            ),
            uuid.uuid4(),
        )
        assert created.catalogue_ids == [_DE]

        updated = await svc.update_session(
            db,
            created.id,
            schemas.SessionUpdate(catalogue_ids=[_DE, _US]),
        )
        assert updated.catalogue_ids == [_DE, _US]

        cleared = await svc.update_session(
            db,
            created.id,
            schemas.SessionUpdate(catalogue_ids=[]),
        )
        assert cleared.catalogue_ids is None

        # An omitted field must leave the (now cleared) selection untouched.
        untouched = await svc.update_session(
            db,
            created.id,
            schemas.SessionUpdate(name="renamed"),
        )
        assert untouched.catalogue_ids is None
        assert untouched.name == "renamed"


# ── run_match multi-base fan-out ──────────────────────────────────────────


async def test_run_match_fans_out_across_two_catalogues(factory, monkeypatch) -> None:
    """Two catalogues -> per-group rank runs once per base, distinct regions."""
    svc = MatchElementsService()
    fake = _FakeMatcher()
    monkeypatch.setattr(svc, "_matcher", lambda *a, **k: fake)

    async with factory() as db:
        project_id = await _seed_project(db)
        sess = await _make_text_session(svc, db, project_id, catalogue_ids=[_DE, _US])

        # Capture the project's catalogue binding before the run so we can
        # prove the fan-out's temporary per-base rebinding is fully restored.
        from app.modules.projects.service import get_or_create_match_settings

        settings_row = await get_or_create_match_settings(db, project_id)
        pre_binding = settings_row.cost_database_id

        summaries = await svc.run_match(
            db,
            sess.id,
            schemas.RunMatchRequest(method="vector"),
            user_id=uuid.uuid4(),
        )

        # One group, ranked once per base.
        assert len(fake.calls) == 2

        cands = await _methods_for(db, sess.id, "vector")
        # Per base: the fake returns R-001 twice + R-002; within a base the
        # exact (base, code) repeat collapses to one R-001. Across two bases
        # that is 2 codes x 2 bases = 4 distinct base-tagged candidates.
        assert len(cands) == 4

        by_region: dict[str, set[str]] = {}
        for c in cands:
            by_region.setdefault(c["region_code"], set()).add(c["code"])
        # Both bases present and each carries both codes.
        assert set(by_region) == {_DE, _US}
        assert by_region[_DE] == {"R-001", "R-002"}
        assert by_region[_US] == {"R-001", "R-002"}

        # No (base, code) pair is duplicated - dedup held.
        pairs = [(c["region_code"], c["code"]) for c in cands]
        assert len(pairs) == len(set(pairs))

        # The same rate code survives from both bases as distinct candidates.
        r001 = [c for c in cands if c["code"] == "R-001"]
        assert {c["region_code"] for c in r001} == {_DE, _US}

        # Summary still surfaces a top suggestion from the merged, sorted set.
        assert len(summaries) == 1
        assert summaries[0].suggested_code == "R-001"

        # The temporary per-base binding must be restored - never left pointing
        # at the last fanned base.
        assert settings_row.cost_database_id == pre_binding


async def test_run_match_single_catalogue_is_unchanged(factory, monkeypatch) -> None:
    """One catalogue -> single rank call, candidates stored verbatim.

    No fan-out stamping and no dedup: the group keeps exactly what the
    matcher returned (region_code left empty, both R-001 rows kept), proving
    the single-base path is byte-identical to today.
    """
    svc = MatchElementsService()
    fake = _FakeMatcher()
    monkeypatch.setattr(svc, "_matcher", lambda *a, **k: fake)

    # Let the vector catalogue-gate pass without a real vectorised catalogue,
    # so the single-base path reaches the matcher (as it does in production
    # once a base is bound). These patches only affect the vector short-circuit.
    async def _bind(*_a, **_k):
        return _DE

    async def _status(*_a, **_k):
        return "ok", 100, 100

    monkeypatch.setattr("app.modules.projects.service.auto_bind_dominant_catalogue", _bind, raising=True)
    monkeypatch.setattr("app.core.match_service.ranker_qdrant._resolve_catalog_status", _status, raising=True)

    async with factory() as db:
        project_id = await _seed_project(db)
        sess = await _make_text_session(svc, db, project_id, catalogue_ids=[_DE])

        await svc.run_match(
            db,
            sess.id,
            schemas.RunMatchRequest(method="vector"),
            user_id=uuid.uuid4(),
        )

        # Single base -> exactly one rank call for the one group.
        assert len(fake.calls) == 1

        cands = await _methods_for(db, sess.id, "vector")
        # Verbatim matcher output: 3 rows (no dedup), region_code untouched.
        assert len(cands) == 3
        assert [c["code"] for c in cands] == ["R-001", "R-001", "R-002"]
        assert all(c["region_code"] == "" for c in cands)
