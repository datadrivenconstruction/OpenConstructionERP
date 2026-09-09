"""A buyer's option selection carries a currency, and refuses a line in another.

``BuyerSelection.total_options_value`` summed every line's price with no
currency on the selection or on the lines, while the options those prices
were copied from each carry one. A kitchen upgrade quoted in EUR and a
flooring upgrade quoted in USD added into one total that is money in
neither, and nothing on the row or the wire could say so. This is the shape
the stock cost fix (``v3304``) closed for a weighted average: label the
figure, and refuse to blend where the labels disagree.

Both rows now carry ``currency``. A selection is stamped once at creation
from the buyer's chain (the buyer's own currency, else the plot's, else the
development's, else the project's); a blank selection is settled by the
first stamped line added to it. A line takes its option's currency, else
the option's development's. Two stated codes that disagree are refused with
a 422 naming both, the way an escrow transaction in the wrong money already
is in this module.

The first half drives the service over stub repositories; the second goes
through the API on the conftest PostgreSQL; the third executes the three
labelling statements ``v3324`` ships against that same database, importing
them from the revision rather than restating them.
"""

from __future__ import annotations

import importlib.util
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.property_dev.models import (
    Buyer,
    BuyerOption,
    BuyerOptionGroup,
    BuyerSelection,
    BuyerSelectionItem,
    Development,
    Plot,
)
from app.modules.property_dev.schemas import BuyerSelectionCreate, BuyerSelectionItemCreate
from app.modules.property_dev.service import PropertyDevService
from tests._pg import transactional_session

from .conftest import _register_user

# ── Stubs ───────────────────────────────────────────────────────────────


class _Repo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def get_by_id(self, oid: uuid.UUID) -> Any:
        return self.rows.get(oid)

    async def create(self, obj: Any) -> Any:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.rows[obj.id] = obj
        return obj

    async def update_fields(self, oid: uuid.UUID, **fields: Any) -> None:
        for key, value in fields.items():
            setattr(self.rows[oid], key, value)


class _ItemRepo(_Repo):
    async def list_for_selection(self, selection_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.selection_id == selection_id]


class _NoProjectSession:
    """The FX metadata loader catches every failure and answers None."""


def _service() -> PropertyDevService:
    svc = PropertyDevService.__new__(PropertyDevService)
    svc.session = _NoProjectSession()  # type: ignore[assignment]
    svc.developments = _Repo()  # type: ignore[assignment]
    svc.plots = _Repo()  # type: ignore[assignment]
    svc.option_groups = _Repo()  # type: ignore[assignment]
    svc.options = _Repo()  # type: ignore[assignment]
    svc.buyers = _Repo()  # type: ignore[assignment]
    svc.selections = _Repo()  # type: ignore[assignment]
    svc.selection_items = _ItemRepo()  # type: ignore[assignment]
    return svc


def _row(**fields: Any) -> SimpleNamespace:
    fields.setdefault("id", uuid.uuid4())
    return SimpleNamespace(**fields)


def _option(svc: PropertyDevService, *, code: str, currency: str, price: str = "100", group_id: Any = None) -> Any:
    opt = _row(code=code, price_delta=Decimal(price), currency=currency, is_active=True, group_id=group_id)
    svc.options.rows[opt.id] = opt  # type: ignore[attr-defined]
    return opt


def _selection(svc: PropertyDevService, *, currency: str) -> Any:
    sel = _row(buyer_id=uuid.uuid4(), status="draft", total_options_value=Decimal("0"), currency=currency)
    svc.selections.rows[sel.id] = sel  # type: ignore[attr-defined]
    return sel


# ── Service over stubs ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_selection_is_stamped_from_its_buyer() -> None:
    svc = _service()
    buyer = _row(currency="usd", plot_id=None, development_id=uuid.uuid4())
    svc.buyers.rows[buyer.id] = buyer  # type: ignore[attr-defined]

    sel = await svc.create_selection(BuyerSelectionCreate(buyer_id=buyer.id))

    assert sel.currency == "USD"


@pytest.mark.asyncio
async def test_a_blank_buyer_reads_its_plot_then_its_development() -> None:
    svc = _service()
    dev = _row(currency="GBP", project_id=uuid.uuid4())
    svc.developments.rows[dev.id] = dev  # type: ignore[attr-defined]
    plot = _row(currency="", development_id=dev.id)
    svc.plots.rows[plot.id] = plot  # type: ignore[attr-defined]
    buyer = _row(currency="", plot_id=plot.id, development_id=dev.id)
    svc.buyers.rows[buyer.id] = buyer  # type: ignore[attr-defined]

    sel = await svc.create_selection(BuyerSelectionCreate(buyer_id=buyer.id))
    assert sel.currency == "GBP"

    plot.currency = "CHF"
    sel2 = await svc.create_selection(BuyerSelectionCreate(buyer_id=buyer.id))
    assert sel2.currency == "CHF"


@pytest.mark.asyncio
async def test_an_option_in_another_currency_is_refused() -> None:
    svc = _service()
    sel = _selection(svc, currency="USD")
    eur = _option(svc, code="KITCHEN-EUR", currency="EUR")

    with pytest.raises(HTTPException) as excinfo:
        await svc.add_selection_item(sel.id, BuyerSelectionItemCreate(option_id=eur.id, quantity=1))

    assert excinfo.value.status_code == 422
    detail = str(excinfo.value.detail)
    assert "EUR" in detail and "USD" in detail and "KITCHEN-EUR" in detail, detail
    assert svc.selection_items.rows == {}  # type: ignore[attr-defined]
    assert sel.total_options_value == Decimal("0")


@pytest.mark.asyncio
async def test_a_matching_pair_is_added_and_labelled() -> None:
    svc = _service()
    sel = _selection(svc, currency="USD")
    usd = _option(svc, code="FLOOR-USD", currency="usd", price="250")

    item = await svc.add_selection_item(sel.id, BuyerSelectionItemCreate(option_id=usd.id, quantity=2))

    assert item.currency == "USD"
    assert item.total_price == Decimal("500")
    assert sel.total_options_value == Decimal("500")
    assert sel.currency == "USD"


@pytest.mark.asyncio
async def test_a_blank_selection_is_settled_by_its_first_line_once() -> None:
    svc = _service()
    sel = _selection(svc, currency="")
    eur = _option(svc, code="A", currency="EUR")
    usd = _option(svc, code="B", currency="USD")

    first = await svc.add_selection_item(sel.id, BuyerSelectionItemCreate(option_id=eur.id, quantity=1))
    assert first.currency == "EUR"
    assert sel.currency == "EUR"

    with pytest.raises(HTTPException) as excinfo:
        await svc.add_selection_item(sel.id, BuyerSelectionItemCreate(option_id=usd.id, quantity=1))
    assert excinfo.value.status_code == 422
    assert sel.total_options_value == Decimal("100")


@pytest.mark.asyncio
async def test_a_blank_option_is_read_in_its_developments_currency() -> None:
    # The option carries no stamp; its group's development is in EUR. That is
    # the module's fallback for a blank stamp, and it disagrees with a USD
    # selection exactly as a stamped EUR option would.
    svc = _service()
    dev = _row(currency="EUR", project_id=uuid.uuid4())
    svc.developments.rows[dev.id] = dev  # type: ignore[attr-defined]
    group = _row(development_id=dev.id)
    svc.option_groups.rows[group.id] = group  # type: ignore[attr-defined]
    blank = _option(svc, code="BLANK", currency="", group_id=group.id)

    usd_sel = _selection(svc, currency="USD")
    with pytest.raises(HTTPException) as excinfo:
        await svc.add_selection_item(usd_sel.id, BuyerSelectionItemCreate(option_id=blank.id, quantity=1))
    assert excinfo.value.status_code == 422

    eur_sel = _selection(svc, currency="EUR")
    item = await svc.add_selection_item(eur_sel.id, BuyerSelectionItemCreate(option_id=blank.id, quantity=1))
    assert item.currency == "EUR"


@pytest.mark.asyncio
async def test_two_blanks_are_not_a_mismatch() -> None:
    svc = _service()
    sel = _selection(svc, currency="")
    blank = _option(svc, code="BLANK", currency="")

    item = await svc.add_selection_item(sel.id, BuyerSelectionItemCreate(option_id=blank.id, quantity=1))

    assert item.currency == "" and sel.currency == ""


# ── The shipping route ──────────────────────────────────────────────────


async def _fixture(client, headers, *, buyer_currency: str, option_currency: str) -> dict[str, Any]:
    proj = await client.post(
        "/api/v1/projects/",
        json={"name": f"SelCcy-{uuid.uuid4().hex[:6]}", "currency": "EUR"},
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    dev = await client.post(
        "/api/v1/property-dev/developments/",
        json={
            "project_id": proj.json()["id"],
            "code": f"DEV-SEL-{uuid.uuid4().hex[:6]}",
            "name": "Options",
            "total_plots": 1,
        },
        headers=headers,
    )
    assert dev.status_code == 201, dev.text
    dev_id = dev.json()["id"]
    buyer = await client.post(
        "/api/v1/property-dev/buyers/",
        json={"development_id": dev_id, "full_name": "Buyer", "currency": buyer_currency},
        headers=headers,
    )
    assert buyer.status_code == 201, buyer.text
    group = await client.post(
        "/api/v1/property-dev/option-groups/",
        json={"development_id": dev_id, "code": f"KIT-{uuid.uuid4().hex[:4]}", "name": "Kitchen"},
        headers=headers,
    )
    assert group.status_code == 201, group.text
    option = await client.post(
        "/api/v1/property-dev/options/",
        json={
            "group_id": group.json()["id"],
            "code": f"ISLAND-{uuid.uuid4().hex[:4]}",
            "name": "Island",
            "price_delta": "1500",
            "currency": option_currency,
        },
        headers=headers,
    )
    assert option.status_code == 201, option.text
    selection = await client.post(
        "/api/v1/property-dev/selections/",
        json={"buyer_id": buyer.json()["id"]},
        headers=headers,
    )
    assert selection.status_code == 201, selection.text
    return {"selection": selection.json(), "option_id": option.json()["id"]}


@pytest.mark.asyncio
async def test_the_route_refuses_a_eur_option_on_a_usd_selection(client) -> None:
    _, _, headers = await _register_user(client, role="admin")
    made = await _fixture(client, headers, buyer_currency="USD", option_currency="EUR")
    assert made["selection"]["currency"] == "USD", made["selection"]

    res = await client.post(
        f"/api/v1/property-dev/selections/{made['selection']['id']}/items",
        json={"option_id": made["option_id"], "quantity": 1},
        headers=headers,
    )

    assert res.status_code == 422, res.text
    assert "EUR" in res.json()["detail"] and "USD" in res.json()["detail"], res.text
    after = await client.get(f"/api/v1/property-dev/selections/{made['selection']['id']}", headers=headers)
    assert Decimal(str(after.json()["total_options_value"])) == Decimal("0"), after.json()


@pytest.mark.asyncio
async def test_the_route_adds_a_matching_option_and_labels_both_rows(client) -> None:
    _, _, headers = await _register_user(client, role="admin")
    made = await _fixture(client, headers, buyer_currency="EUR", option_currency="EUR")

    res = await client.post(
        f"/api/v1/property-dev/selections/{made['selection']['id']}/items",
        json={"option_id": made["option_id"], "quantity": 2},
        headers=headers,
    )

    assert res.status_code == 201, res.text
    assert res.json()["currency"] == "EUR", res.json()
    assert Decimal(res.json()["total_price"]) == Decimal("3000"), res.json()
    after = await client.get(f"/api/v1/property-dev/selections/{made['selection']['id']}", headers=headers)
    assert after.json()["currency"] == "EUR", after.json()
    assert Decimal(str(after.json()["total_options_value"])) == Decimal("3000"), after.json()


# ── The v3324 labelling statements, run on PostgreSQL ───────────────────

_REVISION = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "v3324_buyer_selection_currency.py"


def _load_revision():
    """Import the revision module by path; ``alembic/versions`` is not a package."""
    spec = importlib.util.spec_from_file_location("v3324_under_test", _REVISION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REVISION = _load_revision()


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _run_backfill(session: AsyncSession) -> None:
    """Execute exactly the statements the revision ships, in its order."""
    await session.execute(text(REVISION._BACKFILL_ITEMS_SQL))
    await session.execute(text(REVISION._BACKFILL_SELECTIONS_FROM_BUYER_SQL))
    await session.execute(text(REVISION._BACKFILL_SELECTIONS_FROM_ITEMS_SQL))
    await session.flush()


async def _legacy_rows(
    session: AsyncSession,
    *,
    dev_currency: str,
    buyer_currency: str,
    plot_currency: str | None,
    option_currency: str,
) -> tuple[BuyerSelection, BuyerSelectionItem]:
    """Rows as they stood before the column existed: both stamps blank."""
    dev = Development(project_id=uuid.uuid4(), code=f"LEG-{uuid.uuid4().hex[:8]}", name="Legacy", currency=dev_currency)
    session.add(dev)
    await session.flush()
    plot_id = None
    if plot_currency is not None:
        plot = Plot(development_id=dev.id, plot_number=f"L-{uuid.uuid4().hex[:4]}", currency=plot_currency)
        session.add(plot)
        await session.flush()
        plot_id = plot.id
    buyer = Buyer(development_id=dev.id, plot_id=plot_id, full_name="Legacy buyer", currency=buyer_currency)
    group = BuyerOptionGroup(development_id=dev.id, code=f"G-{uuid.uuid4().hex[:4]}")
    session.add_all([buyer, group])
    await session.flush()
    option = BuyerOption(group_id=group.id, code="OPT", price_delta=Decimal("100"), currency=option_currency)
    session.add(option)
    await session.flush()
    selection = BuyerSelection(buyer_id=buyer.id, currency="")
    session.add(selection)
    await session.flush()
    item = BuyerSelectionItem(
        selection_id=selection.id,
        option_id=option.id,
        unit_price_snapshot=Decimal("100"),
        total_price=Decimal("100"),
        currency="",
    )
    session.add(item)
    await session.flush()
    return selection, item


async def _read_back(session: AsyncSession, selection_id, item_id) -> tuple[str, str]:
    sel = (
        await session.execute(
            text("SELECT currency FROM oe_property_dev_buyer_selection WHERE id = :id"), {"id": str(selection_id)}
        )
    ).scalar_one()
    item = (
        await session.execute(
            text("SELECT currency FROM oe_property_dev_buyer_selection_item WHERE id = :id"), {"id": str(item_id)}
        )
    ).scalar_one()
    return sel, item


class TestTheStatementsRunOnPostgres:
    async def test_a_line_takes_its_options_currency_and_a_selection_its_buyers(self, session: AsyncSession) -> None:
        selection, item = await _legacy_rows(
            session, dev_currency="EUR", buyer_currency="usd", plot_currency=None, option_currency="GBP"
        )

        await _run_backfill(session)

        assert await _read_back(session, selection.id, item.id) == ("USD", "GBP")

    async def test_a_blank_buyer_falls_through_its_plot_then_its_development(self, session: AsyncSession) -> None:
        via_plot, plot_item = await _legacy_rows(
            session, dev_currency="EUR", buyer_currency="", plot_currency="CHF", option_currency=""
        )
        via_dev, dev_item = await _legacy_rows(
            session, dev_currency="EUR", buyer_currency="", plot_currency="", option_currency=""
        )

        await _run_backfill(session)

        assert await _read_back(session, via_plot.id, plot_item.id) == ("CHF", "EUR")
        # The blank option is read in its development's currency, as the
        # service reads it, not in the selection's.
        assert await _read_back(session, via_dev.id, dev_item.id) == ("EUR", "EUR")

    async def test_a_selection_with_nothing_on_its_chain_adopts_its_lines_one_currency(
        self, session: AsyncSession
    ) -> None:
        selection, item = await _legacy_rows(
            session, dev_currency="", buyer_currency="", plot_currency=None, option_currency="SEK"
        )

        await _run_backfill(session)

        assert await _read_back(session, selection.id, item.id) == ("SEK", "SEK")

    async def test_a_row_with_no_currency_anywhere_is_left_blank_not_null(self, session: AsyncSession) -> None:
        selection, item = await _legacy_rows(
            session, dev_currency="", buyer_currency="", plot_currency=None, option_currency=""
        )

        await _run_backfill(session)

        assert await _read_back(session, selection.id, item.id) == ("", "")

    async def test_a_row_already_stamped_is_not_rewritten(self, session: AsyncSession) -> None:
        selection, item = await _legacy_rows(
            session, dev_currency="EUR", buyer_currency="EUR", plot_currency=None, option_currency="EUR"
        )
        await session.execute(
            text("UPDATE oe_property_dev_buyer_selection SET currency = 'JPY' WHERE id = :id"),
            {"id": str(selection.id)},
        )

        await _run_backfill(session)

        assert await _read_back(session, selection.id, item.id) == ("JPY", "EUR")
