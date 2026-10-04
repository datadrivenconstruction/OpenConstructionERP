# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Service and router tests for the resource-index method (Russia).

The arithmetic is pinned in ``test_resource_index_math.py``. These cover what
sits around it: reading indices and norms from their tables (and refusing an
index that belongs to another region or quarter), reading VAT from the
platform's dated tax rows, mapping a BOQ onto the computation (operators once,
sections skipped, what cannot be priced listed with the reason), the sample
seed, the stored choices on the BOQ, and project tenancy on the routes.

The BOQ used here prices to the same hand-computed figures as the math test,
so a mapping mistake shows as a wrong kopeck.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from app.modules.boq.models import BOQ, Position
from app.modules.i18n_foundation.models import TaxConfiguration
from app.modules.price_index import resource_index_math as rim
from app.modules.price_index.models import PriceIndexSeedMarker, ResourceIndexValue, WorkTypeOverheadNorm
from app.modules.price_index.resource_index_schemas import (
    BOQResourceIndexComputeRequest,
    BOQResourceIndexSettings,
    ResourceIndexValueUpdate,
)
from app.modules.price_index.resource_index_service import (
    SETTINGS_KEY,
    ResourceIndexService,
    SettingsIncompleteError,
    VatUnresolvedError,
    map_boq_positions,
)
from app.modules.price_index.router import router as price_index_router
from app.modules.price_index.seed import (
    RESOURCE_INDEX_SEED_KEY,
    SAMPLE_QUARTER,
    SAMPLE_REGION,
    seed_resource_index_samples,
)
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

D = Decimal
REGION = "RU-TST"
QUARTER = "2026-Q1"


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session() as s:
        yield s


# ── Fixtures ──────────────────────────────────────────────────────────────────


async def _seed_ru_vat(session: AsyncSession) -> None:
    """The two dated RU standard rates and the reduced one, as the seed file carries them."""
    await session.execute(delete(TaxConfiguration).where(TaxConfiguration.country_code == "RU"))
    for rate, start, end, default, code in (
        ("20.0", "2019-01-01", "2025-12-31", True, "NDS"),
        ("22.0", "2026-01-01", None, True, "NDS"),
        ("10.0", "2004-01-01", None, False, "NDS_RED"),
    ):
        session.add(
            TaxConfiguration(
                country_code="RU",
                tax_name="VAT Standard (NDS)" if default else "VAT Reduced (NDS)",
                tax_code=code,
                rate_pct=rate,
                tax_type="vat",
                combination="national",
                subdivision_code=None,
                effective_from=start,
                effective_to=end,
                is_default=default,
            )
        )
    await session.flush()


async def _seed_reference(session: AsyncSession, *, region: str = REGION, quarter: str = QUARTER) -> None:
    for group, value in (("labor", "1.25"), ("machine", "1.10"), ("operator_wages", "1.30"), ("material", "1.05")):
        session.add(
            ResourceIndexValue(
                region_code=region,
                quarter=quarter,
                resource_group=group,
                index_value=D(value),
                source="Test letter",
                is_sample=False,
            )
        )
    for code, nr, sp in (("t_concrete", "103", "65"), ("t_earthworks", "89", "50")):
        existing = (
            await session.execute(select(WorkTypeOverheadNorm).where(WorkTypeOverheadNorm.work_type_code == code))
        ).scalar_one_or_none()
        if existing is None:
            session.add(WorkTypeOverheadNorm(work_type_code=code, label=code, nr_pct=D(nr), sp_pct=D(sp)))
    await session.flush()


async def _make_user(session: AsyncSession) -> uuid.UUID:
    u = User(email=f"ri{uuid.uuid4().hex[:8]}@test.com", hashed_password="x")
    session.add(u)
    await session.flush()
    return u.id


async def _make_boq(session: AsyncSession, owner: uuid.UUID) -> BOQ:
    project = Project(name="Smeta", owner_id=owner, region="RU", currency="RUB")
    session.add(project)
    await session.flush()
    boq = BOQ(project_id=project.id, name="Local smeta", metadata_={"keep": "me"})
    session.add(boq)
    await session.flush()
    return boq


def _res(rtype: str, qty: str, rate: str, code: str, **extra: str) -> dict:
    return {"code": code, "name": code, "type": rtype, "unit": "", "quantity": qty, "unit_rate": rate, **extra}


async def _add(
    session: AsyncSession,
    boq: BOQ,
    ordinal: str,
    *,
    quantity: str,
    resources: list[dict] | None,
    unit: str = "m3",
    sort: int = 0,
) -> Position:
    pos = Position(
        boq_id=boq.id,
        ordinal=ordinal,
        description=f"Position {ordinal}",
        unit=unit,
        quantity=quantity,
        unit_rate="0",
        total="0",
        metadata_={"resources": resources} if resources is not None else {},
        sort_order=sort,
    )
    session.add(pos)
    await session.flush()
    return pos


async def _hand_computed_boq(session: AsyncSession, owner: uuid.UUID) -> tuple[BOQ, Position, Position]:
    """The two positions of the math test, stored the way the BOQ editor stores them."""
    boq = await _make_boq(session, owner)
    # A section header: skipped, never listed.
    await _add(session, boq, "1", quantity="0", resources=None, unit="", sort=0)
    p1 = await _add(
        session,
        boq,
        "1.1",
        quantity="2",
        sort=1,
        resources=[
            _res("labor", "12.5", "400.00", "L1"),
            _res("equipment", "3", "1000.00", "M1"),
            _res("operator", "3", "500.00", "O1"),
            _res("material", "10", "250.00", "MAT1"),
        ],
    )
    p2 = await _add(
        session,
        boq,
        "1.2",
        quantity="1.5",
        sort=2,
        resources=[
            _res("labour", "2.4", "280.75", "L2"),
            _res("material", "0.5", "13.47", "MAT2A"),
            _res("material", "0.5", "13.47", "MAT2B"),
        ],
    )
    return boq, p1, p2


# ── Pure mapping ──────────────────────────────────────────────────────────────


class _Pos:
    def __init__(self, ordinal: str, quantity: str, resources: list[dict] | None, unit: str = "m3") -> None:
        self.id = uuid.uuid4()
        self.ordinal = ordinal
        self.description = f"P {ordinal}"
        self.unit = unit
        self.quantity = quantity
        self.unit_rate = "0"
        self.metadata_ = {"resources": resources} if resources is not None else {}
        self.price_basis: str | None = None


def test_mapping_lists_every_position_it_cannot_price() -> None:
    ok = _Pos("1", "1", [_res("labor", "1", "100", "L")])
    empty = _Pos("2", "3", [])
    electricity = _Pos("3", "1", [_res("labor", "1", "100", "L"), _res("electricity", "5", "6", "E")])
    foreign = _Pos("4", "1", [_res("material", "1", "100", "M", currency="EUR")])
    bad = _Pos("5", "1", [_res("material", "x", "100", "M")])
    no_wt = _Pos("6", "1", [_res("material", "1", "100", "M")])
    section = _Pos("7", "0", None, unit="")
    quoted = _Pos("8", "1", [_res("material", "1", "100", "M")])
    quoted.price_basis = "quotation"
    catalogue = _Pos("9", "1", [_res("material", "1", "100", "M")])
    catalogue.price_basis = "price_list"

    mapped, excluded = map_boq_positions(
        [ok, empty, electricity, foreign, bad, no_wt, section, quoted, catalogue],
        currency="RUB",
        work_types={
            str(ok.id): "wt",
            str(electricity.id): "wt",
            str(foreign.id): "wt",
            str(bad.id): "wt",
            str(quoted.id): "wt",
            str(catalogue.id): "wt",
        },
        default_work_type="",
        resources_at_base_prices=True,
    )
    # On a bill confirmed at base prices a catalogue line (price_list) is
    # indexed; a quotation is current money whatever the bill says.
    assert [m.position.ordinal for m in mapped] == ["1", "9"]
    reasons = {e.ordinal: (e.reason, e.detail) for e in excluded}
    assert reasons["8"] == ("not_base_prices", "quotation")
    assert reasons["2"][0] == "no_resources"
    assert reasons["3"] == ("unmapped_resource_type", "electricity")
    assert reasons["4"] == ("foreign_currency", "EUR")
    assert reasons["5"][0] == "bad_number"
    assert reasons["6"][0] == "no_work_type"
    assert "7" not in reasons  # a section header is not a position to price


def test_mapping_uses_chosen_then_default_work_type() -> None:
    a = _Pos("1", "1", [_res("labor", "1", "100", "L")])
    b = _Pos("2", "1", [_res("labor", "1", "100", "L")])
    mapped, excluded = map_boq_positions(
        [a, b],
        currency="RUB",
        work_types={str(a.id): "chosen_wt"},
        default_work_type="default_wt",
        resources_at_base_prices=True,
    )
    assert not excluded
    assert [(m.position.work_type, m.work_type_source) for m in mapped] == [
        ("chosen_wt", "chosen"),
        ("default_wt", "default"),
    ]


def test_mapping_keeps_resource_types_apart() -> None:
    p = _Pos(
        "1",
        "2",
        [
            _res("labor", "1", "1", "a"),
            _res("equipment", "1", "1", "b"),
            _res("operator", "1", "1", "c"),
            _res("material", "1", "1", "d"),
        ],
    )
    mapped, _ = map_boq_positions(
        [p], currency="RUB", work_types={}, default_work_type="wt", resources_at_base_prices=True
    )
    assert [line.kind for line in mapped[0].position.resources] == [
        rim.KIND_LABOR,
        rim.KIND_MACHINE,
        rim.KIND_OPERATOR,
        rim.KIND_MATERIAL,
    ]


def _basis(ordinal: str, basis: str | None) -> _Pos:
    p = _Pos(ordinal, "1", [_res("labor", "1", "100", "L"), _res("material", "1", "50", "M")])
    p.price_basis = basis
    return p


def test_unjudged_lines_are_indexed_only_on_the_persons_confirmation() -> None:
    rows = [
        _basis("unset", None),
        _basis("list", "price_list"),
        _basis("judged", "judgement"),
        _basis("norm", "norm"),
        _basis("invoice", "invoice"),
        _basis("quote", "quotation"),
        _basis("contract", "contract_rate"),
        _basis("history", "historic"),
    ]

    mapped, excluded = map_boq_positions(rows, currency="RUB", work_types={}, default_work_type="wt")
    # Without the confirmation only a line that says it stands on the norm base is indexed.
    assert [m.position.ordinal for m in mapped] == ["norm"]
    reasons = {e.ordinal: (e.reason, e.detail) for e in excluded}
    assert reasons["unset"] == ("base_prices_unconfirmed", "")
    assert reasons["list"] == ("base_prices_unconfirmed", "price_list")
    assert reasons["judged"] == ("base_prices_unconfirmed", "judgement")
    for ordinal, basis in (
        ("invoice", "invoice"),
        ("quote", "quotation"),
        ("contract", "contract_rate"),
        ("history", "historic"),
    ):
        assert reasons[ordinal] == ("not_base_prices", basis)

    mapped, excluded = map_boq_positions(
        rows, currency="RUB", work_types={}, default_work_type="wt", resources_at_base_prices=True
    )
    # The confirmation covers the lines nobody judged; current money stays out.
    assert [m.position.ordinal for m in mapped] == ["unset", "list", "judged", "norm"]
    assert {e.ordinal for e in excluded} == {"invoice", "quote", "contract", "history"}
    assert {e.reason for e in excluded} == {"not_base_prices"}


def test_platform_generated_resource_splits_are_never_indexed_as_base_prices() -> None:
    """The splits the platform writes are shares of a CURRENT rate; indexing them is double indexing.

    Fed with what the generators really produce, not with a hand-made copy.
    """
    from app.core.demo_projects import _enrich_position_metadata, _resources_for_position

    # The trade split of a lump sum, flagged ``estimated``: out even when the
    # person confirms the bill, because the flag outranks the confirmation.
    split = _Pos("split", "1", _resources_for_position("Concrete works", "LS", 1.0, 2_640_000.0))
    assert split.metadata_["resources"] and all(r["estimated"] for r in split.metadata_["resources"])
    # The catalogue-style build-up of a demo position: machines with the
    # operator inside the machine price and no operator line.
    demo = _Pos("demo", "100", _enrich_position_metadata("RC wall C30/37", "m3", 26_400.0, {})["resources"])
    assert {r["type"] for r in demo.metadata_["resources"]} == {"material", "labor", "equipment"}

    for confirmed in (False, True):
        mapped, excluded = map_boq_positions(
            [split, demo],
            currency="RUB",
            work_types={},
            default_work_type="wt",
            resources_at_base_prices=confirmed,
        )
        assert mapped == []
        reasons = {e.ordinal: e.reason for e in excluded}
        assert reasons["split"] == "estimated_resources"
        assert reasons["demo"] == ("machine_without_operator_wages" if confirmed else "base_prices_unconfirmed")


def test_machine_without_operator_line_is_excluded_not_priced_with_otm_zero() -> None:
    bare = _Pos("bare", "1", [_res("labor", "1", "10000", "L"), _res("equipment", "1", "6000", "EX")])
    split = _Pos(
        "split",
        "1",
        [_res("labor", "1", "10000", "L"), _res("equipment", "1", "4000", "EX"), _res("operator", "1", "2000", "OP")],
    )
    stated_zero = _Pos(
        "zero",
        "1",
        [_res("labor", "1", "10000", "L"), _res("machine", "1", "6000", "VIB"), _res("operator", "0", "0", "OP")],
    )
    no_machine = _Pos("hand", "1", [_res("labor", "1", "10000", "L")])
    mapped, excluded = map_boq_positions(
        [bare, split, stated_zero, no_machine],
        currency="RUB",
        work_types={},
        default_work_type="wt",
        resources_at_base_prices=True,
    )
    assert [m.position.ordinal for m in mapped] == ["split", "zero", "hand"]
    assert [(e.ordinal, e.reason) for e in excluded] == [("bare", "machine_without_operator_wages")]


# ── Seed ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sample_seed_is_flagged_and_only_fills_empty_tables(session: AsyncSession) -> None:
    await session.execute(delete(PriceIndexSeedMarker))
    await session.execute(delete(ResourceIndexValue))
    await session.execute(delete(WorkTypeOverheadNorm))
    first = await seed_resource_index_samples(session)
    assert first == {"resource_indices": 4, "overhead_norms": 4}

    rows = (await session.execute(select(ResourceIndexValue))).scalars().all()
    assert {r.resource_group for r in rows} == set(rim.INDEX_GROUPS)
    assert all(r.is_sample and r.region_code == SAMPLE_REGION and r.quarter == SAMPLE_QUARTER for r in rows)
    assert all("SAMPLE" in r.source and "not an official value" in r.source for r in rows)
    norms = (await session.execute(select(WorkTypeOverheadNorm))).scalars().all()
    assert norms and all(n.is_sample and "812/pr" in n.source for n in norms)

    # Idempotent: a second boot adds nothing.
    assert await seed_resource_index_samples(session) == {"resource_indices": 0, "overhead_norms": 0}

    # Once a person replaced the samples with their own rows, a reboot never
    # brings the samples back next to them.
    await session.execute(delete(ResourceIndexValue))
    session.add(ResourceIndexValue(region_code="RU-SPE", quarter="2026-Q2", resource_group="labor", index_value=D("2")))
    await session.flush()
    assert (await seed_resource_index_samples(session))["resource_indices"] == 0


@pytest.mark.asyncio
async def test_deleted_samples_stay_deleted_after_a_restart(session: AsyncSession) -> None:
    await session.execute(delete(PriceIndexSeedMarker))
    await session.execute(delete(ResourceIndexValue))
    await session.execute(delete(WorkTypeOverheadNorm))
    assert await seed_resource_index_samples(session) == {"resource_indices": 4, "overhead_norms": 4}

    # The person clears every sample row before typing in the official letter,
    # which leaves both tables exactly as empty as on a fresh install.
    await session.execute(delete(ResourceIndexValue))
    await session.execute(delete(WorkTypeOverheadNorm))
    await session.flush()

    # The next boot puts nothing back.
    assert await seed_resource_index_samples(session) == {"resource_indices": 0, "overhead_norms": 0}
    assert (await session.execute(select(ResourceIndexValue.id))).first() is None
    assert (await session.execute(select(WorkTypeOverheadNorm.id))).first() is None
    markers = (await session.execute(select(PriceIndexSeedMarker))).scalars().all()
    assert [m.seed_key for m in markers] == [RESOURCE_INDEX_SEED_KEY]


@pytest.mark.asyncio
async def test_an_install_with_its_own_data_is_marked_and_never_seeded(session: AsyncSession) -> None:
    # An install that had rows before the marker existed: nothing is added
    # now, and the marker means nothing is added after the rows go either.
    await session.execute(delete(PriceIndexSeedMarker))
    await session.execute(delete(ResourceIndexValue))
    await session.execute(delete(WorkTypeOverheadNorm))
    session.add(ResourceIndexValue(region_code="RU-SPE", quarter="2026-Q2", resource_group="labor", index_value=D("2")))
    session.add(WorkTypeOverheadNorm(work_type_code="own", label="own", nr_pct=D("90"), sp_pct=D("50")))
    await session.flush()
    assert await seed_resource_index_samples(session) == {"resource_indices": 0, "overhead_norms": 0}
    await session.execute(delete(ResourceIndexValue))
    await session.execute(delete(WorkTypeOverheadNorm))
    await session.flush()
    assert await seed_resource_index_samples(session) == {"resource_indices": 0, "overhead_norms": 0}


@pytest.mark.asyncio
async def test_editing_a_sample_row_makes_it_the_persons_own(session: AsyncSession) -> None:
    row = ResourceIndexValue(
        region_code="RU-X1", quarter="2026-Q1", resource_group="labor", index_value=D("1.6"), is_sample=True
    )
    session.add(row)
    await session.flush()
    updated = await ResourceIndexService(session).update_index(
        row.id, ResourceIndexValueUpdate(index_value=D("1.71"), source="Letter 12345-IF/09")
    )
    assert updated is not None
    assert updated.index_value == D("1.71")
    assert updated.is_sample is False


@pytest.mark.asyncio
async def test_a_sample_edited_in_place_drops_the_sample_note(session: AsyncSession) -> None:
    from app.modules.price_index.seed import SAMPLE_SOURCE_NOTE

    row = ResourceIndexValue(
        region_code="RU-X2",
        quarter="2026-Q1",
        resource_group="machine",
        index_value=D("1.3"),
        source=SAMPLE_SOURCE_NOTE,
        is_sample=True,
    )
    session.add(row)
    await session.flush()
    service = ResourceIndexService(session)
    # Only the value is typed in, as the inline editor does.
    updated = await service.update_index(row.id, ResourceIndexValueUpdate(index_value=D("1.42")))
    assert updated is not None
    assert updated.is_sample is False
    assert updated.source == ""
    # An unchanged value is not an edit: the row stays a sample with its note.
    other = ResourceIndexValue(
        region_code="RU-X2",
        quarter="2026-Q1",
        resource_group="labor",
        index_value=D("1.6"),
        source=SAMPLE_SOURCE_NOTE,
        is_sample=True,
    )
    session.add(other)
    await session.flush()
    same = await service.update_index(other.id, ResourceIndexValueUpdate(index_value=D("1.6")))
    assert same is not None
    assert same.is_sample is True
    assert same.source == SAMPLE_SOURCE_NOTE


# ── VAT from the dated tax rows ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_vat_is_read_for_the_date(session: AsyncSession) -> None:
    await _seed_ru_vat(session)
    service = ResourceIndexService(session)
    assert (await service.resolve_vat(date(2025, 12, 31)))[0] == D("20.0")
    assert (await service.resolve_vat(date(2026, 1, 1)))[0] == D("22.0")


@pytest.mark.asyncio
async def test_no_vat_row_is_an_error_not_a_constant(session: AsyncSession) -> None:
    await session.execute(delete(TaxConfiguration).where(TaxConfiguration.country_code == "RU"))
    await session.flush()
    with pytest.raises(VatUnresolvedError):
        await ResourceIndexService(session).resolve_vat(date(2026, 3, 1))


# ── BOQ computation ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_boq_prices_to_the_hand_computed_figures(session: AsyncSession) -> None:
    await _seed_ru_vat(session)
    await _seed_reference(session)
    owner = await _make_user(session)
    boq, p1, p2 = await _hand_computed_boq(session, owner)

    result = await ResourceIndexService(session).compute_boq(
        boq,
        BOQResourceIndexComputeRequest(
            region_code=REGION.lower(),
            quarter=QUARTER,
            work_types={str(p1.id): "t_concrete", str(p2.id): "t_earthworks"},
            on_date=date(2026, 2, 15),
            resources_at_base_prices=True,
        ),
    )
    assert result.is_complete is True
    assert result.priced_count == 2
    assert result.excluded == []
    t = result.totals
    assert t.direct == D("28934.60")
    assert t.em == D("9900.00")
    assert t.otm == D("3900.00")
    assert t.fot == D("17663.38")
    assert t.nr == D("18016.41")
    assert t.sp == D("11291.69")
    assert t.total == D("58242.70")
    assert t.vat_rate_pct == D("22.0")
    assert t.vat == D("12813.39")
    assert t.total_with_vat == D("71056.09")
    assert result.currency == "RUB"
    assert result.uses_sample_data is False

    # The mapped base cost reconciles with the platform's own figure for the
    # same position, quantity x sum(resource quantity x rate): operators are in
    # it exactly once (counting them twice would give 27 000.00).
    platform_p1 = D("2") * (D("12.5") * D("400") + 3 * D("1000") + 3 * D("500") + 10 * D("250"))
    assert platform_p1 == D("24000") == result.positions[0].base_direct
    # Across the bill the two differ only by the per-line kopeck rounding:
    # the platform's unrounded 25 030.905 against 25 030.90 here.
    platform_all = platform_p1 + D("1.5") * (D("2.4") * D("280.75") + 2 * D("0.5") * D("13.47"))
    assert platform_all == D("25030.905")
    assert t.base_direct == D("25030.90")


@pytest.mark.asyncio
async def test_a_bill_kept_in_another_currency_is_listed_not_priced(session: AsyncSession) -> None:
    """The same hand-computed bill in a euro project gets no rouble indices and no Russian VAT."""
    await _seed_ru_vat(session)
    await _seed_reference(session)
    owner = await _make_user(session)
    boq, p1, p2 = await _hand_computed_boq(session, owner)
    project = await session.get(Project, boq.project_id)
    assert project is not None
    project.currency = "EUR"
    await session.flush()

    result = await ResourceIndexService(session).compute_boq(
        boq,
        BOQResourceIndexComputeRequest(
            region_code=REGION,
            quarter=QUARTER,
            work_types={str(p1.id): "t_concrete", str(p2.id): "t_earthworks"},
            on_date=date(2026, 2, 15),
            resources_at_base_prices=True,
        ),
    )
    assert result.is_complete is False
    assert result.priced_count == 0
    assert {(e.position_id, e.reason, e.detail) for e in result.excluded} == {
        (str(p1.id), "foreign_currency", "EUR"),
        (str(p2.id), "foreign_currency", "EUR"),
    }
    assert result.totals.total == D("0")
    assert result.totals.vat == D("0")


@pytest.mark.asyncio
async def test_same_boq_before_the_vat_change(session: AsyncSession) -> None:
    await _seed_ru_vat(session)
    await _seed_reference(session)
    owner = await _make_user(session)
    boq, p1, p2 = await _hand_computed_boq(session, owner)
    result = await ResourceIndexService(session).compute_boq(
        boq,
        BOQResourceIndexComputeRequest(
            region_code=REGION,
            quarter=QUARTER,
            default_work_type="t_concrete",
            work_types={str(p2.id): "t_earthworks"},
            on_date=date(2025, 12, 31),
            resources_at_base_prices=True,
        ),
    )
    assert result.totals.total == D("58242.70")
    assert result.totals.vat == D("11648.54")
    sources = {p.ordinal: p.work_type_source for p in result.positions}
    assert sources == {"1.1": "default", "1.2": "chosen"}


@pytest.mark.asyncio
async def test_index_of_another_quarter_does_not_count(session: AsyncSession) -> None:
    await _seed_ru_vat(session)
    await _seed_reference(session, quarter="2025-Q4")
    owner = await _make_user(session)
    boq, _p1, _p2 = await _hand_computed_boq(session, owner)
    with pytest.raises(rim.MissingIndexError) as excinfo:
        await ResourceIndexService(session).compute_boq(
            boq,
            BOQResourceIndexComputeRequest(
                region_code=REGION,
                quarter=QUARTER,
                default_work_type="t_concrete",
                on_date=date(2026, 2, 1),
                resources_at_base_prices=True,
            ),
        )
    assert excinfo.value.groups == ("labor", "machine", "material", "operator_wages")


@pytest.mark.asyncio
async def test_partial_boq_is_flagged_not_presented_as_the_total(session: AsyncSession) -> None:
    await _seed_ru_vat(session)
    await _seed_reference(session)
    owner = await _make_user(session)
    boq, p1, _p2 = await _hand_computed_boq(session, owner)
    await _add(session, boq, "1.3", quantity="4", resources=[], sort=3)
    result = await ResourceIndexService(session).compute_boq(
        boq,
        BOQResourceIndexComputeRequest(
            region_code=REGION,
            quarter=QUARTER,
            work_types={str(p1.id): "t_concrete"},
            on_date=date(2026, 2, 1),
            resources_at_base_prices=True,
        ),
    )
    assert result.is_complete is False
    assert result.priced_count == 1
    assert {(e.ordinal, e.reason) for e in result.excluded} == {("1.2", "no_work_type"), ("1.3", "no_resources")}
    assert result.totals.total == D("55202.00")  # position 1.1 alone


@pytest.mark.asyncio
async def test_region_and_quarter_are_required(session: AsyncSession) -> None:
    owner = await _make_user(session)
    boq = await _make_boq(session, owner)
    with pytest.raises(SettingsIncompleteError):
        await ResourceIndexService(session).compute_boq(boq, BOQResourceIndexComputeRequest())


@pytest.mark.asyncio
async def test_settings_are_kept_under_one_key(session: AsyncSession) -> None:
    owner = await _make_user(session)
    boq = await _make_boq(session, owner)
    service = ResourceIndexService(session)
    saved = await service.save_settings(
        boq,
        BOQResourceIndexSettings(
            region_code="ru-mow",
            quarter="2026-q1",
            default_work_type="masonry",
            work_types={"abc": "finishing"},
            resources_at_base_prices=True,
        ),
        str(owner),
    )
    assert saved.region_code == "RU-MOW"
    assert saved.quarter == "2026-Q1"
    await session.refresh(boq)
    assert boq.metadata_["keep"] == "me"
    assert boq.metadata_[SETTINGS_KEY]["work_types"] == {"abc": "finishing"}
    assert service.read_settings(boq).default_work_type == "masonry"
    # The confirmation is read back, not dropped by the key whitelist.
    assert boq.metadata_[SETTINGS_KEY]["resources_at_base_prices"] is True
    assert service.read_settings(boq).resources_at_base_prices is True


@pytest.mark.asyncio
async def test_unconfirmed_bill_lists_every_line_instead_of_indexing_it(session: AsyncSession) -> None:
    """The double-indexing case: the same bill, unconfirmed, prices nothing and says why."""
    await _seed_ru_vat(session)
    await _seed_reference(session)
    owner = await _make_user(session)
    boq, p1, p2 = await _hand_computed_boq(session, owner)
    request = BOQResourceIndexComputeRequest(
        region_code=REGION,
        quarter=QUARTER,
        work_types={str(p1.id): "t_concrete", str(p2.id): "t_earthworks"},
        on_date=date(2026, 2, 15),
    )
    result = await ResourceIndexService(session).compute_boq(boq, request)
    assert result.is_complete is False
    assert result.priced_count == 0
    assert {(e.ordinal, e.reason) for e in result.excluded} == {
        ("1.1", "base_prices_unconfirmed"),
        ("1.2", "base_prices_unconfirmed"),
    }
    assert result.totals.total == D("0.00")

    # One line marked as standing on the norm base is indexed on its own word.
    p2.price_basis = "norm"
    await session.flush()
    result = await ResourceIndexService(session).compute_boq(boq, request)
    assert [p.ordinal for p in result.positions] == ["1.2"]
    assert result.totals.total == D("3040.70")  # position 1.2 alone, as in the math test


# ── Router: refusals and tenancy ──────────────────────────────────────────────


def _app(session: AsyncSession, user_id: uuid.UUID) -> FastAPI:
    app = FastAPI()
    app.include_router(price_index_router, prefix="/v1/price-index")

    async def _sess() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _sess
    app.dependency_overrides[get_current_user_id] = lambda: str(user_id)
    app.dependency_overrides[get_current_user_payload] = lambda: {
        "sub": str(user_id),
        "role": "editor",
        "permissions": ["price_index.manage", "boq.update"],
    }
    return app


async def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t")


@pytest.mark.asyncio
async def test_router_missing_index_is_a_422_naming_the_groups(session: AsyncSession) -> None:
    await _seed_ru_vat(session)
    await _seed_reference(session)
    owner = await _make_user(session)
    payload = {
        "region_code": "RU-NOWHERE",
        "quarter": "2026-Q1",
        "on_date": "2026-02-01",
        "positions": [
            {
                "quantity": "1",
                "work_type": "t_concrete",
                "resources": [{"kind": "labor", "quantity": "1", "base_unit_price": "100"}],
            }
        ],
    }
    async with await _client(_app(session, owner)) as client:
        resp = await client.post("/v1/price-index/resource-index/compute/", json=payload)
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["code"] == "missing_index"
        assert detail["groups"] == ["labor"]

        payload["region_code"] = REGION
        resp = await client.post("/v1/price-index/resource-index/compute/", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        # 1 x 1 x 100.00 = 100.00 ; x 1.25 = 125.00 ; NR 103 % = 128.75 ; SP 65 % = 81.25
        assert body["totals"]["total"] == "335.00"
        assert body["positions"][0]["lines"][0]["current_amount"] == "125.00"


@pytest.mark.asyncio
async def test_router_hides_another_projects_boq(session: AsyncSession) -> None:
    owner = await _make_user(session)
    stranger = await _make_user(session)
    boq = await _make_boq(session, owner)
    async with await _client(_app(session, stranger)) as client:
        for method, path, body in (
            ("GET", f"/v1/price-index/resource-index/boqs/{boq.id}/settings/", None),
            ("PUT", f"/v1/price-index/resource-index/boqs/{boq.id}/settings/", {"region_code": "RU-MOW"}),
            ("POST", f"/v1/price-index/resource-index/boqs/{boq.id}/compute/", {"region_code": "RU-MOW"}),
        ):
            resp = await client.request(method, path, json=body)
            assert resp.status_code == 404, (method, path, resp.text)
    await session.refresh(boq)
    assert SETTINGS_KEY not in boq.metadata_


@pytest.mark.asyncio
async def test_router_owner_saves_and_reads_settings(session: AsyncSession) -> None:
    owner = await _make_user(session)
    boq = await _make_boq(session, owner)
    async with await _client(_app(session, owner)) as client:
        resp = await client.put(
            f"/v1/price-index/resource-index/boqs/{boq.id}/settings/",
            json={"region_code": "RU-MOW", "quarter": "2026-Q1", "work_types": {"x": "masonry"}},
        )
        assert resp.status_code == 200, resp.text
        resp = await client.get(f"/v1/price-index/resource-index/boqs/{boq.id}/settings/")
        assert resp.json()["work_types"] == {"x": "masonry"}
        resp = await client.post(f"/v1/price-index/resource-index/boqs/{boq.id}/compute/", json={})
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "settings_incomplete"


@pytest.mark.asyncio
async def test_router_locked_boq_refuses_settings_and_stays_untouched(session: AsyncSession) -> None:
    owner = await _make_user(session)
    boq = await _make_boq(session, owner)
    boq.is_locked = True
    await session.flush()
    await session.refresh(boq)
    stamp = boq.updated_at
    async with await _client(_app(session, owner)) as client:
        resp = await client.put(
            f"/v1/price-index/resource-index/boqs/{boq.id}/settings/",
            json={"region_code": "RU-MOW", "quarter": "2026-Q1", "resources_at_base_prices": True},
        )
        assert resp.status_code == 409, resp.text
        # Reading the choices and pricing stay open on a locked bill.
        assert (await client.get(f"/v1/price-index/resource-index/boqs/{boq.id}/settings/")).status_code == 200
    await session.refresh(boq)
    assert boq.metadata_ == {"keep": "me"}
    assert boq.updated_at == stamp


@pytest.mark.asyncio
async def test_router_missing_operator_line_is_a_422_naming_the_position(session: AsyncSession) -> None:
    await _seed_ru_vat(session)
    await _seed_reference(session)
    owner = await _make_user(session)
    payload = {
        "region_code": REGION,
        "quarter": "2026-Q1",
        "on_date": "2026-02-01",
        "positions": [
            {
                "ordinal": "7",
                "quantity": "1",
                "work_type": "t_earthworks",
                "resources": [
                    {"kind": "labor", "quantity": "1", "base_unit_price": "10000"},
                    {"kind": "machine", "quantity": "1", "base_unit_price": "6000"},
                ],
            }
        ],
    }
    async with await _client(_app(session, owner)) as client:
        resp = await client.post("/v1/price-index/resource-index/compute/", json=payload)
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["code"] == "missing_operator_wages"
        assert detail["positions"] == ["7"]


@pytest.mark.asyncio
async def test_router_duplicate_index_is_a_conflict(session: AsyncSession) -> None:
    owner = await _make_user(session)
    await _seed_reference(session)
    async with await _client(_app(session, owner)) as client:
        resp = await client.post(
            "/v1/price-index/resource-index/indices/",
            json={"region_code": REGION, "quarter": QUARTER, "resource_group": "labor", "index_value": "2"},
        )
        assert resp.status_code == 409
        resp = await client.post(
            "/v1/price-index/resource-index/indices/",
            json={"region_code": REGION, "quarter": "2026-q2", "resource_group": "labor", "index_value": "2"},
        )
        assert resp.status_code == 201
        assert resp.json()["quarter"] == "2026-Q2"
        assert resp.json()["is_sample"] is False
        resp = await client.post(
            "/v1/price-index/resource-index/indices/",
            json={"region_code": REGION, "quarter": "2026-Q3", "resource_group": "wages", "index_value": "2"},
        )
        assert resp.status_code == 422


async def test_router_lists_page_with_a_total_so_a_short_answer_is_visible(session: AsyncSession) -> None:
    owner = await _make_user(session)
    await _seed_reference(session)
    async with await _client(_app(session, owner)) as client:
        base = "/v1/price-index/resource-index/indices/"
        first = (await client.get(base, params={"region_code": REGION, "quarter": QUARTER, "limit": 3})).json()
        assert first["total"] == 4
        assert (first["offset"], first["limit"]) == (0, 3)
        assert len(first["items"]) == 3
        rest = (
            await client.get(base, params={"region_code": REGION, "quarter": QUARTER, "offset": 3, "limit": 3})
        ).json()
        assert rest["total"] == 4
        assert len(rest["items"]) == 1
        # The two pages together are the whole set, each group exactly once.
        groups = sorted(i["resource_group"] for i in first["items"] + rest["items"])
        assert groups == ["labor", "machine", "material", "operator_wages"]
        assert (await client.get(base, params={"limit": 0})).status_code == 422

        norms = (await client.get("/v1/price-index/resource-index/norms/", params={"limit": 1})).json()
        assert len(norms["items"]) == 1
        assert norms["total"] >= 2


def test_schema_literals_match_the_math_module() -> None:
    from typing import get_args

    from app.modules.price_index.resource_index_schemas import ResourceGroup, ResourceKind

    assert set(get_args(ResourceGroup)) == set(rim.INDEX_GROUPS)
    assert set(get_args(ResourceKind)) == set(rim.RESOURCE_KINDS)
