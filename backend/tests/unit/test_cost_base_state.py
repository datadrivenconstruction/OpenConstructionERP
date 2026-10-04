"""A cost base's market and language survive a restart, a second worker and a return home.

Which market a national base is priced into, and which language its text is in,
used to live in a process-local dict and in the browser. These tests run against
a real PostgreSQL database (a throwaway clone per test, ``isolated_engine``) and
model a second worker or a restarted process as a second engine on the same
database, so nothing the first one kept in memory can help the second.

What they pin:

* the stored state round-trips through the table and reads the same from a
  fresh engine; partial writes leave the other fields alone;
* two users switching two different bases at once each get their own answer;
* the advisory lock excludes a second worker on the same base and only that
  base, with the in-process lock taken out of play so it cannot pass for it;
* ``/base-catalog`` reports what is stored, and "unknown" for a loaded base
  with nothing stored;
* the language swap is skipped after a restart only when the stored language
  matches, which is the bug the process-local dict had;
* a market switch reprices, stores the market and mirrors the market catalogue
  into the Resource Catalog without touching a resource a person added;
* a return to the home market gives every work item its home rate, components
  and currency back, ids kept, an item the home file does not hold untouched,
  and rebuilds the price sheet and the catalogue;
* an ``already_loaded`` load retries a home-language switch that did not land,
  and only when the stored state says so.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.modules.catalog.models import CatalogResource
from app.modules.costs import base_state
from app.modules.costs import router as costs_router
from app.modules.costs.models import CostBaseState, CostItem, ResourcePrice
from app.modules.costs.resource_pricing import ResourcePriceService
from tests._pg import isolated_engine

BASE = "ZH_CHINA"
OTHER_BASE = "TR_NATIONAL"
MARKET = "GB_LONDON_en"


@pytest_asyncio.fixture
async def db() -> Any:
    async with isolated_engine() as engine:
        yield engine


def _sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _second_worker(engine: AsyncEngine) -> AsyncEngine:
    """Another engine on the same database: a restarted process or a second worker."""
    return create_async_engine(engine.url, future=True)


def _comp(code: str, qty: float, unit_rate: float, ctype: str = "material") -> dict[str, Any]:
    return {
        "code": code,
        "name": f"Resource {code}",
        "unit": "kg",
        "quantity": qty,
        "unit_rate": unit_rate,
        "cost": round(qty * unit_rate, 2),
        "type": ctype,
    }


#: The base's own work items, as its home parquet holds them (home prices).
HOME_ITEMS: dict[str, dict[str, Any]] = {
    "ZH-001": {
        "description": "Home text of item one",
        "rate": "25.0",
        "components": [_comp("R1", 2, 10.0), _comp("R2", 1, 5.0)],
        "metadata": {"material_cost": 25.0},
    },
    "ZH-002": {
        "description": "Home text of item two",
        "rate": "10.0",
        "components": [_comp("R1", 1, 10.0)],
        "metadata": {"material_cost": 10.0},
    },
}


async def _load_home_base(session: AsyncSession, region: str = BASE, *, extra: int = 0) -> dict[str, uuid.UUID]:
    """Put the base's home rows in, plus a row the home file does not hold."""
    ids: dict[str, uuid.UUID] = {}
    currency = costs_router._resolve_currency(None, region)
    for code, item in HOME_ITEMS.items():
        row = CostItem(
            code=code,
            description=item["description"],
            unit="m3",
            rate=item["rate"],
            currency=currency,
            source="cwicr",
            region=region,
            components=item["components"],
            metadata_=item["metadata"],
            is_active=True,
        )
        session.add(row)
        await session.flush()
        ids[code] = row.id
    # Added by a person under the base's region: no components, no home row.
    own = CostItem(
        code="ZH-OWN",
        description="An item a person added",
        unit="pcs",
        rate="42.50",
        currency=currency,
        source="custom",
        region=region,
        components=[],
        is_active=True,
    )
    session.add(own)
    for n in range(extra):
        session.add(
            CostItem(
                code=f"ZH-PAD-{n:03d}",
                description=f"Padding item {n}",
                unit="m",
                rate="1",
                currency=currency,
                source="cwicr",
                region=region,
                components=[],
                is_active=True,
            )
        )
    await session.flush()
    ids["ZH-OWN"] = own.id
    await session.commit()
    return ids


# ── The table and the helper ──────────────────────────────────────────────


async def test_the_stored_state_reads_the_same_from_a_fresh_worker(db: AsyncEngine) -> None:
    async with _sessions(db)() as s:
        await base_state.write_base_state(s, BASE, text_language="fr", active_market="FR_PARIS_fr", switching_to=None)

    restarted = await _second_worker(db)
    try:
        async with _sessions(restarted)() as s2:
            state = await base_state.read_base_state(s2, BASE)
    finally:
        await restarted.dispose()

    assert state is not None
    assert (state.text_language, state.active_market, state.switching_to) == ("fr", "FR_PARIS_fr", None)
    assert state.market_state == "market"


async def test_a_partial_write_leaves_the_other_fields_alone(db: AsyncEngine) -> None:
    async with _sessions(db)() as s:
        await base_state.write_base_state(s, BASE, active_market=MARKET, text_language="en")
        await base_state.write_base_state(s, BASE, text_language="zh")
        await base_state.write_base_state(s, BASE, switching_to="DE_BERLIN_de")
        state = await base_state.read_base_state(s, BASE)
        rows = (await s.execute(select(CostBaseState))).scalars().all()

    assert state is not None
    assert (state.active_market, state.text_language, state.switching_to) == (MARKET, "zh", "DE_BERLIN_de")
    assert state.market_state == "switching"
    assert len(rows) == 1


async def test_nothing_stored_is_unknown_not_home(db: AsyncEngine) -> None:
    async with _sessions(db)() as s:
        assert await base_state.read_base_state(s, BASE) is None
        await base_state.write_base_state(s, BASE, active_market=MARKET)
        await base_state.forget_base_state(s, BASE)
        assert await base_state.read_base_state(s, BASE) is None


async def test_two_users_switching_two_bases_at_once_each_keep_their_own(db: AsyncEngine) -> None:
    alice, bob = uuid.uuid4(), uuid.uuid4()
    second = await _second_worker(db)
    try:

        async def _switch(engine: AsyncEngine, region: str, market: str, lang: str, user: uuid.UUID) -> None:
            async with _sessions(engine)() as s:
                await base_state.write_base_state(s, region, switching_to=market, updated_by=user)
                await asyncio.sleep(0)
                await base_state.write_base_state(
                    s, region, active_market=market, text_language=lang, switching_to=None, updated_by=user
                )

        await asyncio.gather(
            _switch(db, BASE, MARKET, "en", alice),
            _switch(second, OTHER_BASE, "FR_PARIS_fr", "fr", bob),
        )
        async with _sessions(second)() as s:
            china = await base_state.read_base_state(s, BASE)
            turkiye = await base_state.read_base_state(s, OTHER_BASE)
            owners = {row.region: row.updated_by for row in (await s.execute(select(CostBaseState))).scalars().all()}
    finally:
        await second.dispose()

    assert china is not None and turkiye is not None
    assert (china.active_market, china.text_language) == (MARKET, "en")
    assert (turkiye.active_market, turkiye.text_language) == ("FR_PARIS_fr", "fr")
    assert owners == {BASE: alice, OTHER_BASE: bob}


# ── The lock ──────────────────────────────────────────────────────────────


@pytest.fixture
def no_process_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hand out a fresh in-process lock each time, as two separate processes would have.

    Without this the in-process lock alone would serialise both "workers" in
    this one test process, and the test would pass with the advisory lock broken.
    """
    monkeypatch.setattr(base_state, "_process_lock", lambda region: asyncio.Lock())


async def test_the_lock_keeps_a_second_worker_off_the_same_base(db: AsyncEngine, no_process_lock: None) -> None:
    held = asyncio.Event()
    release = asyncio.Event()

    async def _first_worker() -> None:
        async with _sessions(db)() as s, base_state.base_market_lock(s, BASE):
            held.set()
            await release.wait()

    task = asyncio.create_task(_first_worker())
    await held.wait()
    second = await _second_worker(db)
    try:
        async with _sessions(second)() as s2:
            with pytest.raises(base_state.BaseBusyError):
                async with base_state.base_market_lock(s2, BASE, wait_s=0.6):
                    pytest.fail("the second worker got into a base the first one holds")
            # Another base is not held by anyone.
            async with base_state.base_market_lock(s2, OTHER_BASE, wait_s=0.6):
                pass
            release.set()
            await task
            # Released: the second worker gets in now.
            async with base_state.base_market_lock(s2, BASE, wait_s=5):
                pass
    finally:
        release.set()
        await second.dispose()


async def test_the_lock_is_released_when_the_switch_fails(db: AsyncEngine, no_process_lock: None) -> None:
    async with _sessions(db)() as s:
        with pytest.raises(RuntimeError):
            async with base_state.base_market_lock(s, BASE):
                raise RuntimeError("reprice broke")
    second = await _second_worker(db)
    try:
        async with _sessions(second)() as s2, base_state.base_market_lock(s2, BASE, wait_s=2):
            pass
    finally:
        await second.dispose()


# ── /base-catalog ─────────────────────────────────────────────────────────


async def test_the_catalog_reports_the_stored_market_and_unknown_without_one(db: AsyncEngine) -> None:
    async with _sessions(db)() as s:
        await _load_home_base(s, BASE, extra=10)
        await _load_home_base(s, OTHER_BASE, extra=10)
        await base_state.write_base_state(s, BASE, active_market=MARKET, text_language="en")
        out = await costs_router.get_base_catalog(s)

    assert out["base_states"][BASE]["market_state"] == "market"
    assert out["base_states"][BASE]["active_market"] == MARKET
    assert out["base_states"][OTHER_BASE]["market_state"] == "unknown"
    china = next(f for f in out["families"] if f["key"] == "china")
    active = [v["variant_id"] for v in china["variants"] if v["active"]]
    assert active == [f"{BASE}:{MARKET}"]


async def test_a_switch_in_flight_marks_no_card_active(db: AsyncEngine) -> None:
    async with _sessions(db)() as s:
        await _load_home_base(s, BASE, extra=10)
        await base_state.write_base_state(s, BASE, active_market=MARKET, switching_to="FR_PARIS_fr")
        out = await costs_router.get_base_catalog(s)

    assert out["base_states"][BASE]["market_state"] == "switching"
    china = next(f for f in out["families"] if f["key"] == "china")
    assert not any(v["active"] for v in china["variants"])


# ── The language swap after a restart ─────────────────────────────────────


@pytest.fixture
def fake_swap(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    swaps: list[str] = []

    async def _find(db_id: str) -> Path:
        return tmp_path / f"{db_id}.parquet"

    def _swap(target: str, parquet: str, base_region: str, staging_region: str) -> int:
        swaps.append(staging_region)
        return 2

    monkeypatch.setattr(costs_router, "_find_cwicr_file", _find)
    monkeypatch.setattr(costs_router, "_swap_region_text_sync", _swap)
    monkeypatch.setattr(costs_router, "_invalidate_cost_cache", lambda: None)
    return swaps


async def test_the_text_language_survives_a_restart(db: AsyncEngine, fake_swap: list[str]) -> None:
    async with _sessions(db)() as s:
        assert await costs_router._ensure_region_text_language(BASE, "fr", s) == "fr"
    assert fake_swap == [f"__xlate_{BASE}_fr"]

    restarted = await _second_worker(db)
    try:
        async with _sessions(restarted)() as s2:
            # Same language: the restarted worker knows it from the table.
            assert await costs_router._ensure_region_text_language(BASE, "fr", s2) == "fr"
            assert fake_swap == [f"__xlate_{BASE}_fr"]
            # Another language still swaps.
            assert await costs_router._ensure_region_text_language(BASE, "de", s2) == "de"
            state = await base_state.read_base_state(s2, BASE)
    finally:
        await restarted.dispose()
    assert fake_swap == [f"__xlate_{BASE}_fr", f"__xlate_{BASE}_de"]
    assert state is not None and state.text_language == "de"


# ── Market switch and return home, end to end ─────────────────────────────

MARKET_ROWS = [
    {
        "resource_code": "R1",
        "name": "Resource R1",
        "type": "material",
        "unit": "kg",
        "price_avg": "3",
        "currency": "GBP",
    },
    {
        "resource_code": "R2",
        "name": "Resource R2",
        "type": "material",
        "unit": "kg",
        "price_avg": "1",
        "currency": "GBP",
    },
]
HOME_CATALOG_ROWS = [
    {
        "resource_code": "R1",
        "name": "Resource R1",
        "type": "material",
        "unit": "kg",
        "price_avg": "10",
        "currency": "CNY",
    },
    {
        "resource_code": "R2",
        "name": "Resource R2",
        "type": "material",
        "unit": "kg",
        "price_avg": "5",
        "currency": "CNY",
    },
]


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch, fake_swap: list[str], db: AsyncEngine) -> Iterator[dict[str, Any]]:
    """Every outside dependency of the two endpoints, faked; the database is real."""
    import app.modules.catalog.router as catalog_router

    sync_url = db.url.set(drivername="postgresql+psycopg2").render_as_string(hide_password=False)
    state: dict[str, Any] = {"staged": []}

    async def _load(db_id: str, session: Any, **kwargs: Any) -> dict:
        return {"status": "already_loaded"}

    async def _market_rows(base_region: str, market_token: str) -> list[dict[str, Any]]:
        return [dict(r) for r in MARKET_ROWS]

    async def _home_rows(region: str) -> list[dict[str, Any]]:
        return [dict(r) for r in HOME_CATALOG_ROWS]

    def _import_home_parquet(parquet_path: str, db_id: str, db_file: str) -> dict[str, Any]:
        """What the importer writes for the base's own parquet, into the staging region."""
        state["staged"].append(db_id)
        engine = create_engine(db_file)
        try:
            with engine.begin() as conn:
                for code, item in HOME_ITEMS.items():
                    conn.execute(
                        CostItem.__table__.insert().values(
                            id=uuid.uuid4(),
                            code=code,
                            description=item["description"],
                            unit="m3",
                            rate=item["rate"],
                            currency="",
                            source="cwicr",
                            region=db_id,
                            components=item["components"],
                            metadata=item["metadata"],
                            is_active=True,
                        )
                    )
        finally:
            engine.dispose()
        return {"imported": len(HOME_ITEMS)}

    monkeypatch.setattr(costs_router, "load_cwicr_region", _load)
    monkeypatch.setattr(catalog_router, "fetch_market_catalog_rows", _market_rows)
    monkeypatch.setattr(catalog_router, "fetch_region_catalog_rows", _home_rows)
    monkeypatch.setattr(costs_router, "_process_and_insert_cwicr", _import_home_parquet)
    # The overlay's own sync engine has to reach this test's database. Set and
    # put back here, not through ``monkeypatch``: monkeypatch is undone after
    # ``db`` is torn down, and ``db`` drops the database through an admin
    # connection that reads this same variable.
    previous = os.environ.get("DATABASE_SYNC_URL")
    os.environ["DATABASE_SYNC_URL"] = sync_url
    try:
        yield state
    finally:
        if previous is None:
            os.environ.pop("DATABASE_SYNC_URL", None)
        else:
            os.environ["DATABASE_SYNC_URL"] = previous


async def _items(s: AsyncSession, region: str = BASE) -> dict[str, SimpleNamespace]:
    """A detached snapshot of the region's rows, read fresh from the database."""
    s.expire_all()
    rows = (await s.execute(select(CostItem).where(CostItem.region == region))).scalars().all()
    return {
        row.code: SimpleNamespace(
            id=row.id,
            rate=row.rate,
            currency=row.currency,
            components=row.components,
            metadata_=row.metadata_,
        )
        for row in rows
    }


async def _catalog(s: AsyncSession) -> list[tuple[str, str, str, str]]:
    """The catalogue rows a reader sees: the active ones."""
    s.expire_all()
    rows = (
        (
            await s.execute(
                select(CatalogResource).where(CatalogResource.region == BASE, CatalogResource.is_active.is_(True))
            )
        )
        .scalars()
        .all()
    )
    return sorted((r.source, r.resource_code, r.base_price, r.currency) for r in rows)


async def _catalog_ids(s: AsyncSession) -> dict[str, uuid.UUID]:
    """Every catalogue row of the base by code, active or retired."""
    s.expire_all()
    rows = (await s.execute(select(CatalogResource).where(CatalogResource.region == BASE))).scalars().all()
    return {r.resource_code: r.id for r in rows}


def _catalog_row(code: str, price: str, currency: str, source: str = "github_import") -> CatalogResource:
    return CatalogResource(
        resource_code=code,
        name=f"Resource {code}",
        resource_type="material",
        category="General",
        unit="kg",
        base_price=price,
        currency=currency,
        source=source,
        region=BASE,
    )


async def _switch_to_london(s: AsyncSession, user: str) -> dict:
    return await costs_router.load_base_market(BASE, MARKET, session=s, _user_id=user, service=ResourcePriceService(s))


async def test_a_market_switch_reprices_stores_and_mirrors_the_catalogue(
    db: AsyncEngine, wired: dict[str, Any]
) -> None:
    user = str(uuid.uuid4())
    async with _sessions(db)() as s:
        await _load_home_base(s)
        await ResourcePriceService(s).seed_region(BASE)
        s.add(
            CatalogResource(
                resource_code="MY-1",
                name="Mine",
                resource_type="material",
                category="Own",
                unit="kg",
                base_price="7",
                currency="CNY",
                source="manual",
                region=BASE,
            )
        )
        s.add(
            CatalogResource(
                resource_code="R1",
                name="Resource R1",
                resource_type="material",
                category="General",
                unit="kg",
                base_price="10",
                currency="CNY",
                source="github_import",
                region=BASE,
            )
        )
        await s.commit()

        out = await _switch_to_london(s, user)
        items = await _items(s)
        state = await base_state.read_base_state(s, BASE)
        catalog = await _catalog(s)
        stored_by = (await s.execute(select(CostBaseState.updated_by))).scalar_one()

    # rate = sum(qty x market price): 2x3 + 1x1 and 1x3, not the home 25 and 10.
    assert Decimal(items["ZH-001"].rate) == Decimal("7.00")
    assert Decimal(items["ZH-002"].rate) == Decimal("3.00")
    assert {i.currency for i in items.values()} == {"GBP"}
    # The item without components has no recipe to reprice: its rate is untouched.
    assert items["ZH-OWN"].rate == "42.50"
    assert out["active_market"] == MARKET
    assert state is not None and (state.market_state, state.active_market) == ("market", MARKET)
    assert stored_by == uuid.UUID(user)
    # Market resources replace the imported home row; the person's own row stays.
    assert catalog == [
        ("manual", "MY-1", "7", "CNY"),
        ("market_import", "R1", "3", "GBP"),
        ("market_import", "R2", "1", "GBP"),
    ]
    assert out["catalog"]["updated"] == 1
    assert out["catalog"]["added"] == 1


async def test_market_switches_keep_assembly_links_to_catalogue_resources(
    db: AsyncEngine, wired: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A switch and a return home update catalogue rows in place, so no link is cut.

    ``Component.catalog_resource_id`` is ``ON DELETE SET NULL``: a delete and
    re-insert of the catalogue on every switch nulled it without a word.
    """
    from app.modules.assemblies.models import Assembly, Component

    async with _sessions(db)() as s:
        await _load_home_base(s)
        await ResourcePriceService(s).seed_region(BASE)
        s.add_all([_catalog_row("R1", "10", "CNY"), _catalog_row("R2", "5", "CNY"), _catalog_row("R9", "2", "CNY")])
        await s.commit()
        home_ids = await _catalog_ids(s)
        assembly = Assembly(code="ASM-LINK", name="Linked", unit="m3")
        s.add(assembly)
        await s.flush()
        for code in ("R1", "R2", "R9"):
            s.add(
                Component(
                    assembly_id=assembly.id,
                    catalog_resource_id=home_ids[code],
                    description=f"Uses {code}",
                    unit="kg",
                )
            )
        await s.commit()
        assembly_id = assembly.id

        async def _links() -> dict[str, uuid.UUID | None]:
            s.expire_all()
            comps = (await s.execute(select(Component).where(Component.assembly_id == assembly_id))).scalars().all()
            return {c.description: c.catalog_resource_id for c in comps}

        await _switch_to_london(s, str(uuid.uuid4()))
        after_switch = await _catalog_ids(s)
        links_after_switch = await _links()
        catalog_in_market = await _catalog(s)

        await costs_router.restore_base_home_market(BASE, session=s, _user_id=str(uuid.uuid4()))
        after_home = await _catalog_ids(s)
        links_after_home = await _links()
        catalog_at_home = await _catalog(s)

        # A return home whose catalogue cannot be read hides the market rows
        # and still deletes none of them.
        await _switch_to_london(s, str(uuid.uuid4()))

        async def _unreadable(region: str) -> list[dict[str, Any]]:
            raise RuntimeError("catalogue download refused")

        import app.modules.catalog.router as catalog_router

        monkeypatch.setattr(catalog_router, "fetch_region_catalog_rows", _unreadable)
        out = await costs_router.restore_base_home_market(BASE, session=s, _user_id=str(uuid.uuid4()))
        after_unreadable = await _catalog_ids(s)
        links_after_unreadable = await _links()
        catalog_unreadable = await _catalog(s)

    expected_links = {f"Uses {code}": home_ids[code] for code in ("R1", "R2", "R9")}
    assert after_switch == home_ids
    assert after_home == home_ids
    assert after_unreadable == home_ids
    assert links_after_switch == expected_links
    assert links_after_home == expected_links
    assert links_after_unreadable == expected_links
    # R9 is in neither catalogue file: hidden from the list, never deleted.
    assert catalog_in_market == [("market_import", "R1", "3", "GBP"), ("market_import", "R2", "1", "GBP")]
    assert catalog_at_home == [("github_import", "R1", "10", "CNY"), ("github_import", "R2", "5", "CNY")]
    assert catalog_unreadable == []
    assert out["catalog"]["retired"] == 2
    assert "hidden" in out["catalog"]["error"]


async def test_return_home_gives_every_item_its_home_prices_back(db: AsyncEngine, wired: dict[str, Any]) -> None:
    user = str(uuid.uuid4())
    home_currency = costs_router._resolve_currency(None, BASE)
    assert home_currency and home_currency != "GBP"

    async with _sessions(db)() as s:
        ids = await _load_home_base(s)
        await ResourcePriceService(s).seed_region(BASE)
        s.add(
            CatalogResource(
                resource_code="MY-1",
                name="Mine",
                resource_type="material",
                category="Own",
                unit="kg",
                base_price="7",
                currency="CNY",
                source="manual",
                region=BASE,
            )
        )
        await s.commit()
        await _switch_to_london(s, user)
        # A price edited on the sheet after the switch: the return home replaces it.
        await ResourcePriceService(s).set_price(BASE, "R1", Decimal("4"))
        await s.commit()

        out = await costs_router.restore_base_home_market(BASE, session=s, _user_id=user)

        items = await _items(s)
        staging_left = await _items(s, f"__xlate_{BASE}_home")
        sheet = {
            r.resource_key: (Decimal(r.unit_price), r.source, r.currency)
            for r in (await s.execute(select(ResourcePrice).where(ResourcePrice.region == BASE))).scalars().all()
        }
        state = await base_state.read_base_state(s, BASE)
        catalog = await _catalog(s)

    for code, home in HOME_ITEMS.items():
        assert items[code].id == ids[code], "the return home must keep every id"
        assert items[code].rate == home["rate"]
        assert items[code].components == home["components"]
        assert items[code].metadata_ == home["metadata"]
    # Not in the home file: rate and recipe as they were, currency back to home.
    assert items["ZH-OWN"].rate == "42.50"
    assert {i.currency for i in items.values()} == {home_currency}
    assert staging_left == {}
    assert wired["staged"] == [f"__xlate_{BASE}_home"]

    assert sheet == {
        "R1": (Decimal("10.00"), "cwicr_import", home_currency),
        "R2": (Decimal("5.00"), "cwicr_import", home_currency),
    }
    assert out["user_prices_discarded"] == 1
    assert out["items_restored"] == len(HOME_ITEMS)
    assert out["previous_market"] == MARKET
    assert out["currency"] == home_currency
    # Then the text goes to the base's own language, as a fresh load does.
    assert out["text_language"] == "zh"
    assert state is not None
    assert (state.market_state, state.active_market, state.switching_to, state.text_language) == (
        "home",
        None,
        None,
        "zh",
    )
    assert out["state"]["market_state"] == "home"
    assert catalog == [
        ("github_import", "R1", "10", "CNY"),
        ("github_import", "R2", "5", "CNY"),
        ("manual", "MY-1", "7", "CNY"),
    ]


async def test_return_home_reprices_a_recipe_the_home_file_does_not_hold(
    db: AsyncEngine, wired: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A priced recipe added under the base comes back in home prices, not relabelled market ones.

    The market here is a high-number currency (VND scale), so the two ways to
    get this wrong both show: stamping the home currency over the market rate
    (60000 "CNY"), and seeding the home sheet from the market rows (the
    largest-price rule would make R1 cost 30000 at home).
    """
    import app.modules.catalog.router as catalog_router

    vnd_rows = [
        {"resource_code": "R1", "name": "Resource R1", "type": "material", "unit": "kg", "price_avg": "30000"},
        {"resource_code": "R2", "name": "Resource R2", "type": "material", "unit": "kg", "price_avg": "15000"},
        {"resource_code": "R7", "name": "Resource R7", "type": "material", "unit": "kg", "price_avg": "500"},
    ]
    for row in vnd_rows:
        row["currency"] = "VND"

    async def _vnd(base_region: str, market_token: str) -> list[dict[str, Any]]:
        return [dict(r) for r in vnd_rows]

    monkeypatch.setattr(catalog_router, "fetch_market_catalog_rows", _vnd)
    home_currency = costs_router._resolve_currency(None, BASE)
    user = str(uuid.uuid4())

    async with _sessions(db)() as s:
        await _load_home_base(s)
        # Added by a person: priced recipes the home parquet does not hold.
        s.add(
            CostItem(
                code="ZH-MINE",
                description="A priced recipe a person added",
                unit="m3",
                rate="20.00",
                currency=home_currency,
                source="custom",
                region=BASE,
                components=[_comp("R1", 2, 10.0)],
                is_active=True,
            )
        )
        # Its only resource is one no home row uses, so no home price exists.
        s.add(
            CostItem(
                code="ZH-ODD",
                description="A recipe on a resource the home sheet lacks",
                unit="m3",
                rate="8.00",
                currency=home_currency,
                source="custom",
                region=BASE,
                components=[_comp("R7", 1, 8.0)],
                is_active=True,
            )
        )
        await s.commit()
        await ResourcePriceService(s).seed_region(BASE)
        await _switch_to_london(s, user)
        in_market = await _items(s)

        out = await costs_router.restore_base_home_market(BASE, session=s, _user_id=user)
        items = await _items(s)
        sheet = {
            r.resource_key: Decimal(r.unit_price)
            for r in (await s.execute(select(ResourcePrice).where(ResourcePrice.region == BASE))).scalars().all()
        }

    # The switch really moved them into VND, so the return has something to undo.
    assert (Decimal(in_market["ZH-MINE"].rate), in_market["ZH-MINE"].currency) == (Decimal("60000.00"), "VND")
    assert (Decimal(in_market["ZH-ODD"].rate), in_market["ZH-ODD"].currency) == (Decimal("500.00"), "VND")

    # The home sheet comes from home rows only: no VND price leaks into it.
    assert sheet["R1"] == Decimal("10.00")
    assert sheet["R2"] == Decimal("5.00")
    # Repriced from that sheet: 2 x 10, in the home currency.
    assert (Decimal(items["ZH-MINE"].rate), items["ZH-MINE"].currency) == (Decimal("20.00"), home_currency)
    assert items["ZH-MINE"].components[0]["unit_rate"] == 10.0
    # Nothing at home prices R7: the item keeps its VND rate under its VND label,
    # and the answer says so instead of calling it restored.
    assert (Decimal(items["ZH-ODD"].rate), items["ZH-ODD"].currency) == (Decimal("500.00"), "VND")
    assert out["items_left_in_market"] == 1
    assert out["items_repriced_home"] == 1
    # The rest is exactly as the home file has it.
    for code, home in HOME_ITEMS.items():
        assert (items[code].rate, items[code].currency) == (home["rate"], home_currency)
    assert (items["ZH-OWN"].rate, items["ZH-OWN"].currency) == ("42.50", home_currency)
    assert out["items_restored"] == len(HOME_ITEMS)


async def test_return_home_then_market_again_lands_the_same_market_prices(
    db: AsyncEngine, wired: dict[str, Any]
) -> None:
    """Home and back must not compound: the second London rate equals the first."""
    user = str(uuid.uuid4())
    async with _sessions(db)() as s:
        await _load_home_base(s)
        await ResourcePriceService(s).seed_region(BASE)
        await _switch_to_london(s, user)
        first = {code: Decimal(i.rate) for code, i in (await _items(s)).items()}
        await costs_router.restore_base_home_market(BASE, session=s, _user_id=user)
        await _switch_to_london(s, user)
        second = {code: Decimal(i.rate) for code, i in (await _items(s)).items()}
    assert first == second


async def test_return_home_refuses_a_base_without_markets_or_not_loaded(db: AsyncEngine, wired: dict[str, Any]) -> None:
    async with _sessions(db)() as s:
        with pytest.raises(HTTPException) as global_base:
            await costs_router.restore_base_home_market("FR_PARIS", session=s, _user_id="u")
        with pytest.raises(HTTPException) as empty:
            await costs_router.restore_base_home_market(BASE, session=s, _user_id="u")
    assert global_base.value.status_code == 404
    assert empty.value.status_code == 404


async def test_return_home_without_its_file_changes_nothing(
    db: AsyncEngine, wired: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _missing(db_id: str) -> None:
        return None

    async with _sessions(db)() as s:
        await _load_home_base(s)
        await ResourcePriceService(s).seed_region(BASE)
        await _switch_to_london(s, str(uuid.uuid4()))
        monkeypatch.setattr(costs_router, "_find_cwicr_file", _missing)
        with pytest.raises(HTTPException) as exc:
            await costs_router.restore_base_home_market(BASE, session=s, _user_id="u")
        items = await _items(s)
        state = await base_state.read_base_state(s, BASE)
    assert exc.value.status_code == 502
    assert Decimal(items["ZH-001"].rate) == Decimal("7.00")
    assert state is not None and (state.market_state, state.active_market) == ("market", MARKET)


# ── The catalogue import shares the row builder ───────────────────────────


async def test_the_region_import_still_reads_rows_the_same_way(
    db: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The import now goes through the shared row builder: same skips, same full replace."""
    import app.modules.catalog.router as catalog_router

    csv_text = (
        "resource_code,name,type,category,unit,price_avg,price_min,price_max,currency,usage_count,grade\n"
        "R1,Cement,Material,Binders,kg,10,12,8,CNY,3,P.O 42.5\n"
        ",No code,material,General,kg,1,0,0,CNY,0,\n"
        "R2,Broken price,material,General,kg,abc,0,0,CNY,0,\n"
    )
    monkeypatch.setattr(catalog_router, "_read_region_catalog_csv", lambda region, folder: (csv_text.encode(), "cache"))
    async with _sessions(db)() as s:
        s.add(
            CatalogResource(
                resource_code="OLD",
                name="Old",
                resource_type="material",
                category="X",
                unit="kg",
                base_price="1",
                currency="CNY",
                source="manual",
                region=BASE,
            )
        )
        await s.commit()
        out = await catalog_router.import_region_catalog(s, BASE)
        await s.commit()
        rows = (await s.execute(select(CatalogResource).where(CatalogResource.region == BASE))).scalars().all()
        got = [
            (r.resource_code, r.resource_type, r.base_price, r.min_price, r.max_price, r.specifications) for r in rows
        ]

    assert out == {"imported": 1, "skipped": 2, "region": BASE, "source": "cache"}
    # The manual import replaces the whole region, as it always did; the band
    # 12..8 is swapped and the average clamped into it.
    assert got == [("R1", "material", "10", "8", "12", {"grade": "P.O 42.5"})]


# ── Retrying the home language on a later load ────────────────────────────


@pytest.mark.parametrize(
    ("stored", "retried"),
    [
        ({"text_language": "en", "active_market": None}, True),
        ({"text_language": None, "active_market": None}, True),
        ({"text_language": "zh", "active_market": None}, False),
        ({"text_language": "en", "active_market": MARKET}, False),
        (None, False),
    ],
)
async def test_a_later_load_retries_a_home_language_switch_that_did_not_land(
    db: AsyncEngine, fake_swap: list[str], stored: dict[str, Any] | None, retried: bool
) -> None:
    async with _sessions(db)() as s:
        await _load_home_base(s, extra=10)
        if stored is not None:
            await base_state.write_base_state(s, BASE, **stored)
        out = await costs_router.load_cwicr_region(BASE, s)
        state = await base_state.read_base_state(s, BASE)

    assert out["status"] == "already_loaded"
    assert (fake_swap == [f"__xlate_{BASE}_zh"]) is retried
    if retried:
        assert out["text_language"] == "zh"
        assert state is not None and state.text_language == "zh"
