# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost items read from other modules follow the same rule as the cost routes.

The rule is applied to ORM reads of ``CostItem`` wherever they are written, so
a module does not opt in. That only holds while every read IS an ORM read and
every vector hit is checked: the first half of this file exercises readers in
other modules as each kind of caller, the second half fails when somebody adds
a road around the rule (raw SQL on the table, ``session.get``, an unchecked
vector search).
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cost_scope
from app.modules.costs.models import CostCatalog, CostItem
from app.modules.users.models import User
from tests._pg import transactional_session

_APP = Path(__file__).resolve().parents[2] / "app"
_TEXT = "zzotherprivate"


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _seed(s: AsyncSession) -> dict[str, Any]:
    ids: dict[str, Any] = {}
    for name, role in (("alice", "manager"), ("bob", "editor"), ("admin", "admin")):
        user = User(
            id=uuid.uuid4(),
            email=f"other-{uuid.uuid4().hex[:8]}@test.io",
            hashed_password="x" * 60,
            full_name="Other Test",
            role=role,
            locale="en",
            is_active=True,
            metadata_={},
        )
        s.add(user)
        ids[name] = user.id
    await s.flush()
    region = f"ZZOTHER{uuid.uuid4().hex[:6].upper()}"
    catalog = CostCatalog(id=uuid.uuid4(), name=region, currency="EUR", created_by=ids["alice"])
    s.add(catalog)
    await s.flush()
    private = CostItem(
        id=uuid.uuid4(),
        code="ZZOTHER.PRIV",
        description=f"{_TEXT} private partition wall",
        unit="m2",
        rate="77",
        currency="EUR",
        region=region,
        catalog_id=catalog.id,
        is_active=True,
    )
    shared = CostItem(
        id=uuid.uuid4(),
        code="ZZOTHER.SHARED",
        description=f"{_TEXT} shared partition wall",
        unit="m2",
        rate="66",
        currency="EUR",
        region=f"{region}S",
        is_active=True,
    )
    s.add_all([private, shared])
    await s.flush()
    ids.update(private=private.id, shared=shared.id, region=region, catalog=catalog.id)
    # As a new request would find it: nothing loaded yet.
    s.expunge_all()
    return ids


READERS = [("alice", True), ("admin", True), ("bob", False), (None, False)]


@pytest.mark.asyncio
@pytest.mark.parametrize(("reader", "sees_private"), READERS)
async def test_readers_in_other_modules(session: AsyncSession, reader: str | None, sees_private: bool) -> None:
    from app.core.global_search import global_search
    from app.core.pipeline.registry import NodeContext
    from app.modules.assemblies.service import AssemblyService
    from app.modules.boq.price_list_carry import load_cost_item
    from app.modules.cost_explorer.repository import CostExplorerRepository
    from app.modules.costs.matcher import _load_candidates
    from app.modules.costs.repository import CostItemRepository
    from app.modules.pipelines.pipeline_nodes import _run_source_cost_catalog
    from app.modules.search.service import COLLECTION_COSTS, _sql_search_collection_raw

    w = await _seed(session)
    private, shared = str(w["private"]), str(w["shared"])
    found: dict[str, set[str]] = {}

    with cost_scope.caller_scope(w[reader] if reader else None):
        hits = await global_search(session, _TEXT, limit=50)
        found["global search"] = {str(h["id"]) for h in hits}

        explorer = CostExplorerRepository(session)
        by_code = await explorer.items_by_code("ZZOTHER.PRIV", 10) + await explorer.items_by_code("ZZOTHER.SHARED", 10)
        found["cost explorer by code"] = {str(i.id) for i in by_code}
        one = [await explorer.get_item(w["private"]), await explorer.get_item(w["shared"])]
        found["cost explorer by id"] = {str(i.id) for i in one if i is not None}
        many = await explorer.cost_items_by_ids([w["private"], w["shared"]])
        found["cost explorer by ids"] = {str(k) for k in many}

        candidates = await _load_candidates(session, f"{_TEXT} partition wall", region=None, source=None, cap=50)
        found["matcher candidates"] = {str(c.item.id) for c in candidates}

        repo = CostItemRepository(session)
        rows = await repo.get_by_codes(["ZZOTHER.PRIV", "ZZOTHER.SHARED"])
        found["costs by codes"] = {str(r.id) for r in rows}
        got = [await repo.get_by_id(w["private"]), await repo.get_by_id(w["shared"])]
        found["costs by id"] = {str(r.id) for r in got if r is not None}

        raw = await _sql_search_collection_raw(session, COLLECTION_COSTS, _TEXT, limit=50)
        found["unified search"] = {str(h.id) for h in raw}

        # What a BOQ position is priced from when it names a cost item.
        linked = [await load_cost_item(session, w["private"]), await load_cost_item(session, w["shared"])]
        found["boq position link"] = {str(i.id) for i in linked if i is not None}

        # An assembly drafted from a description is built out of cost items.
        draft = await AssemblyService(session).ai_generate_preview(description=f"{_TEXT} partition wall", unit="m2")
        text = repr(draft)
        found["assembly draft"] = {
            *([private] if "ZZOTHER.PRIV" in text else []),
            *([shared] if "ZZOTHER.SHARED" in text else []),
        }

        # A pipeline's cost source node, run for the user who started the run.
        ctx = NodeContext(
            db=session,
            node_id="n1",
            node_type="source.cost_catalog",
            params={"query": _TEXT, "limit": 50},
            inputs={},
            project_id=None,
            tenant_id=None,
            actor_id=str(w[reader]) if reader else None,
            run_id=uuid.uuid4(),
        )
        node_text = repr(await _run_source_cost_catalog(ctx))
        found["pipeline cost source"] = {
            *([private] if "ZZOTHER.PRIV" in node_text else []),
            *([shared] if "ZZOTHER.SHARED" in node_text else []),
        }

        assert await cost_scope.may_read_catalogue(session, w["catalog"]) is sees_private

    for name, ids in found.items():
        assert shared in ids, f"{name} as {reader} lost the shared row"
        assert (private in ids) is sees_private, f"{name} as {reader}"


@pytest.mark.asyncio
async def test_a_match_run_cannot_name_a_catalogue_its_caller_may_not_read(session: AsyncSession) -> None:
    from app.modules.cost_match.schemas import MatchLineInput, MatchRunCreate
    from app.modules.cost_match.service import CatalogueNotFoundError, CostMatchService

    w = await _seed(session)
    data = MatchRunCreate(
        project_id=uuid.uuid4(),
        catalog_id=w["catalog"],
        region=w["region"],
        lines=[MatchLineInput(description=f"{_TEXT} partition wall", unit="m2")],
    )
    for reader in (w["bob"], None):
        with cost_scope.caller_scope(reader), pytest.raises(CatalogueNotFoundError):
            await CostMatchService(session).create_run(data, created_by=reader)
    # The same answer as for a catalogue that was never created.
    missing = data.model_copy(update={"catalog_id": uuid.uuid4()})
    with cost_scope.caller_scope(w["alice"]), pytest.raises(CatalogueNotFoundError):
        await CostMatchService(session).create_run(missing, created_by=w["alice"])


def test_a_pipeline_node_runs_as_the_user_who_started_the_run() -> None:
    """The executor has no request around it; it names the reader itself."""
    import inspect

    from app.core.pipeline import executor

    assert "cost_scope.caller_scope(actor_id)" in inspect.getsource(executor.run_node)


@pytest.mark.asyncio
async def test_a_row_loaded_by_system_code_is_not_handed_to_the_caller(session: AsyncSession) -> None:
    """The identity map would answer ``session.get`` without asking who reads."""
    from app.modules.costs.repository import CostItemRepository

    w = await _seed(session)
    repo = CostItemRepository(session)
    with cost_scope.caller_scope(w["bob"]):
        holder = await repo.code_holder("ZZOTHER.PRIV", region=w["region"])
        assert holder is not None, "the uniqueness probe must see a code another user holds"
        assert await repo.get_by_id(w["private"]) is None
        assert await repo.get_by_code("ZZOTHER.PRIV", region=w["region"]) is None


@pytest.mark.asyncio
async def test_event_handlers_read_every_row_whoever_caused_the_event(session: AsyncSession) -> None:
    """A reindex or an audit triggered by one user's request still covers the whole base."""
    from app.core.events import EventBus

    w = await _seed(session)
    bus = EventBus()
    seen: list[bool] = []

    async def handler(_event: object) -> None:
        seen.append(cost_scope.is_system())
        seen.append(await cost_scope.get_cost_item(session, w["private"]) is not None)

    bus.subscribe("costs.test.probe", handler)
    with cost_scope.caller_scope(w["bob"]):
        await bus.publish("costs.test.probe", {})
        assert not cost_scope.is_system()
    assert seen == [True, True]


@pytest.mark.asyncio
async def test_the_match_indexer_reads_the_whole_region_when_another_user_woke_it(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Indexed as the wrong reader, a catalogue would lose rows from its index as stale."""
    from app.modules.costs import match_index

    w = await _seed(session)
    seen: list[bool] = []

    async def fake_index(job: object) -> None:
        seen.append(cost_scope.is_system())
        seen.append(await cost_scope.get_cost_item(session, w["private"]) is not None)

    match_index.reset_state()
    monkeypatch.setattr(match_index, "index_catalogue", fake_index)
    job = match_index.IndexJob(region=str(w["region"]), language="en")
    match_index._jobs[job.region] = job
    match_index._queue.append(job.region)
    try:
        with cost_scope.caller_scope(w["bob"]):
            await match_index.run_queue()
    finally:
        match_index.reset_state()
    assert seen == [True, True]


# ── No road around the rule ──────────────────────────────────────────────


def _sources() -> list[tuple[str, str]]:
    return [(p.relative_to(_APP).as_posix(), p.read_text(encoding="utf-8")) for p in sorted(_APP.rglob("*.py"))]


def test_no_cost_item_is_loaded_by_identity() -> None:
    """``session.get`` answers from the identity map without a query; use ``cost_scope.get_cost_item``."""
    # System work that loads the row to index or audit it, never to return it.
    # ``core/cost_scope.py`` only names the call it replaces.
    allowed = {"modules/assemblies/events.py", "core/cost_scope.py"}
    pattern = re.compile(r"\.get\(\s*_?CostItem(?:Model)?\s*,")
    offenders = [path for path, text in _sources() if pattern.search(text) and path not in allowed]
    assert not offenders, offenders


def test_every_cost_vector_search_checks_its_hits() -> None:
    """The cost vector store has no owner on its points, so each search is followed by a check."""
    offenders = []
    for path, text in _sources():
        if path == "core/vector.py":
            continue
        searches = len(re.findall(r"\bvector_search\(|to_thread\(\s*vector_search\b", text))
        checks = len(re.findall(r"cost_scope\.visible_hits\(", text))
        if searches > checks:
            offenders.append(f"{path}: {searches} searches, {checks} checks")
    assert not offenders, offenders


def test_no_raw_sql_reads_cost_items() -> None:
    """Raw SQL is outside the reach of the rule, so nothing may select from the table by name."""
    pattern = re.compile(r"""(?:FROM|JOIN)\s+["']?oe_costs_item\b""", re.IGNORECASE)
    offenders = [path for path, text in _sources() if pattern.search(text)]
    assert not offenders, offenders
