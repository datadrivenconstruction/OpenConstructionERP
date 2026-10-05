# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A markup line can sit on exactly the base of the line above it.

German Zuschlagskalkulation charges Wagnis and Gewinn on the same base, the
Selbstkosten (Herstellkosten plus AGK). With only ``direct_cost`` and
``cumulative`` that stack could not be built: making both cumulative puts
Gewinn on Selbstkosten plus Wagnis, and making Gewinn direct puts it on the
EKT. A course author had to type W+G in as a fixed sum, which is a number that
stops following the bill the moment a quantity changes.

``apply_to = "same_as_previous"`` closes that. These tests pin:

* the cascade: the line takes the base of the nearest active line above, it
  chains, and it falls back to the sum of positions when there is no base
  above (first line, or a fixed amount above it);
* that ``subtotal`` keeps meaning what stored rows already mean by it;
* that every other walker of the stack (the list rollup, the cost plan, the
  contingency rule) reads the new value the same way, so the list, the export
  and the editor never disagree about one bill;
* the DACH case through the PATCH path the panel uses, with the bases each
  line ends up on asserted directly rather than through a total.

Run (CI):
    cd backend
    python -m pytest tests/unit/test_boq_markup_same_base_as_above.py -v
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

import app.modules.boq.service as boq_service
from app.core.validation.engine import ValidationContext
from app.modules.boq.models import BOQMarkup
from app.modules.boq.repository import BOQRepository
from app.modules.boq.schemas import MarkupCreate, MarkupUpdate
from app.modules.boq.service import DEFAULT_MARKUP_TEMPLATES, BOQService, _calculate_markup_amounts
from app.modules.boq.validators import MarkupContingencyNotOnProfit
from app.modules.cost_plan.engine import LeafInput, MarkupInput, build_cost_plan

D = Decimal


def _mk(
    name: str,
    percentage: str = "0",
    *,
    apply_to: str = "direct_cost",
    sort_order: int = 0,
    markup_type: str = "percentage",
    fixed_amount: str = "0",
    category: str = "overhead",
    is_active: bool = True,
) -> BOQMarkup:
    markup = BOQMarkup(
        boq_id=uuid.uuid4(),
        name=name,
        markup_type=markup_type,
        category=category,
        percentage=percentage,
        fixed_amount=fixed_amount,
        apply_to=apply_to,
        sort_order=sort_order,
        is_active=is_active,
        metadata_={},
    )
    markup.id = uuid.uuid4()
    return markup


def _bases(direct_cost: Decimal, stack: list[BOQMarkup]) -> dict[str, Decimal]:
    """The base each active percentage line was charged on, read back from its amount."""
    out: dict[str, Decimal] = {}
    for markup, amount in _calculate_markup_amounts(direct_cost, stack):
        pct = D(str(markup.percentage))
        if markup.is_active and markup.markup_type == "percentage" and pct:
            out[markup.name] = amount * D("100") / pct
    return out


def _amounts(direct_cost: Decimal, stack: list[BOQMarkup]) -> dict[str, Decimal]:
    return {m.name: a for m, a in _calculate_markup_amounts(direct_cost, stack)}


# ── The cascade ─────────────────────────────────────────────────────────────


def test_two_lines_share_one_base() -> None:
    stack = [
        _mk("Overhead", "10", sort_order=0),
        _mk("W", "2", apply_to="cumulative", sort_order=1),
        _mk("G", "3", apply_to="same_as_previous", sort_order=2),
    ]
    bases = _bases(D("1000"), stack)
    assert bases["W"] == D("1100")
    assert bases["G"] == D("1100")


def test_it_chains_through_several_lines() -> None:
    stack = [
        _mk("A", "10", sort_order=0),
        _mk("B", "5", apply_to="cumulative", sort_order=1),
        _mk("C", "4", apply_to="same_as_previous", sort_order=2),
        _mk("D", "2", apply_to="same_as_previous", sort_order=3),
    ]
    bases = _bases(D("1000"), stack)
    assert bases["B"] == bases["C"] == bases["D"] == D("1100")


def test_it_borrows_a_direct_cost_base_too() -> None:
    stack = [
        _mk("A", "10", sort_order=0),
        _mk("B", "5", sort_order=1),
        _mk("C", "4", apply_to="same_as_previous", sort_order=2),
    ]
    assert _bases(D("1000"), stack)["C"] == D("1000")


def test_the_first_line_falls_back_to_the_sum_of_positions() -> None:
    stack = [_mk("G", "3", apply_to="same_as_previous")]
    assert _amounts(D("1000"), stack)["G"] == D("30")


def test_a_fixed_line_above_has_no_base_so_it_falls_back() -> None:
    stack = [
        _mk("Overhead", "10", apply_to="direct_cost", sort_order=0),
        _mk("Site set-up", markup_type="fixed", fixed_amount="500", sort_order=1),
        _mk("G", "3", apply_to="same_as_previous", sort_order=2),
    ]
    # Not 1,600 (the running total) and not the overhead's base by skipping
    # the fixed line: the nearest active line above has no base.
    assert _bases(D("1000"), stack)["G"] == D("1000")


def test_an_inactive_line_above_is_skipped() -> None:
    stack = [
        _mk("Overhead", "10", sort_order=0),
        _mk("W", "2", apply_to="cumulative", sort_order=1),
        _mk("Switched off", "7", apply_to="direct_cost", sort_order=2, is_active=False),
        _mk("G", "3", apply_to="same_as_previous", sort_order=3),
    ]
    assert _bases(D("1000"), stack)["G"] == D("1100")


def test_a_banded_line_above_lends_its_base() -> None:
    bond = _mk("Bond", markup_type="banded", apply_to="cumulative", sort_order=1)
    bond.metadata_ = {"bands": [{"up_to": None, "percentage": "1"}]}
    stack = [
        _mk("Overhead", "10", sort_order=0),
        bond,
        _mk("Insurance", "1", apply_to="same_as_previous", sort_order=2),
    ]
    assert _bases(D("1000"), stack)["Insurance"] == D("1100")


def test_subtotal_still_means_the_running_total() -> None:
    stack = [
        _mk("Overhead", "10", sort_order=0),
        _mk("Profit", "5", sort_order=1),
        _mk("VAT", "20", apply_to="subtotal", sort_order=2),
    ]
    assert _bases(D("1000"), stack)["VAT"] == D("1150")


def test_the_schemas_accept_the_new_base_and_nothing_made_up() -> None:
    assert MarkupCreate(name="G", apply_to="same_as_previous").apply_to == "same_as_previous"
    assert MarkupUpdate.model_validate({"apply_to": "same_as_previous"}).apply_to == "same_as_previous"
    with pytest.raises(ValidationError):
        MarkupUpdate.model_validate({"apply_to": "previous"})


# ── Every other walker of the stack reads it the same way ──────────────────


class _Rows(list):
    def scalars(self) -> _Rows:
        return self

    def all(self) -> list[Any]:
        return list(self)


class _FakeSession:
    """Answer the two reads ``active_markups_for_boqs`` makes."""

    def __init__(self, boq_id: uuid.UUID, direct_cost: Decimal, markups: list[BOQMarkup]) -> None:
        self._answers = [
            _Rows([type("Row", (), {"boq_id": boq_id, "direct_cost": direct_cost})()]),
            _Rows(markups),
        ]

    async def execute(self, _stmt: object) -> _Rows:
        return self._answers.pop(0)


@pytest.mark.asyncio
async def test_the_list_rollup_agrees_with_the_cascade() -> None:
    boq_id = uuid.uuid4()
    stack = [
        _mk("BGK", "8", sort_order=0),
        _mk("AGK", "9", apply_to="cumulative", sort_order=1),
        _mk("W", "2", apply_to="cumulative", sort_order=2),
        _mk("G", "3", apply_to="same_as_previous", sort_order=3),
    ]
    for m in stack:
        m.boq_id = boq_id
    repo = BOQRepository.__new__(BOQRepository)
    repo.session = _FakeSession(boq_id, D("1000000"), stack)  # type: ignore[assignment]

    rollup = await repo.totals_for_boqs([boq_id])

    expected = D("1000000") + sum(_amounts(D("1000000"), stack).values(), D("0"))
    assert D(str(rollup[boq_id]["grand_total"])) == expected.quantize(D("0.01"))


def test_the_cost_plan_shows_the_borrowed_base() -> None:
    stack = [
        _mk("BGK", "8", sort_order=0),
        _mk("AGK", "9", apply_to="cumulative", sort_order=1),
        _mk("W", "2", apply_to="cumulative", sort_order=2),
        _mk("G", "3", apply_to="same_as_previous", sort_order=3),
    ]
    amounts = _amounts(D("1000000"), stack)
    plan = build_cost_plan(
        boq_id=uuid.uuid4(),
        boq_name="Bill",
        project_id=uuid.uuid4(),
        currency="EUR",
        leaves=[LeafInput(id=uuid.uuid4(), ordinal="1", description="item", amount=D("1000000"))],
        markups=[
            MarkupInput(
                id=m.id,
                name=m.name,
                category=m.category,
                markup_type=m.markup_type,
                apply_to=m.apply_to,
                amount=amounts[m.name],
                percentage=D(m.percentage),
            )
            for m in stack
        ],
    )
    rows = {row.name: row for row in plan.markups}
    assert D(str(rows["W"].base)) == D("1177200")
    assert D(str(rows["G"].base)) == D("1177200")


@pytest.mark.asyncio
async def test_a_contingency_borrowing_a_base_with_profit_in_it_is_flagged() -> None:
    def row(order: int, name: str, category: str, apply_to: str) -> dict[str, Any]:
        return {
            "id": f"m-{name}",
            "name": name,
            "markup_type": "percentage",
            "category": category,
            "percentage": "5",
            "fixed_amount": "0",
            "apply_to": apply_to,
            "sort_order": order,
            "is_active": True,
            "scope_position_id": None,
            "overrides_id": None,
        }

    flagged = [
        row(0, "Overhead", "overhead", "direct_cost"),
        row(1, "Profit", "profit", "direct_cost"),
        row(2, "Insurance", "insurance", "cumulative"),
        row(3, "Contingency", "contingency", "same_as_previous"),
    ]
    context = ValidationContext(data={"positions": [], "markups": flagged}, metadata={"locale": "en"})
    assert len(await MarkupContingencyNotOnProfit().validate(context)) == 1

    # Borrowing the base of the profit line itself: that base does not contain
    # the profit, so nothing is charged on it.
    clean = [
        row(0, "Overhead", "overhead", "direct_cost"),
        row(1, "Profit", "profit", "cumulative"),
        row(2, "Contingency", "contingency", "same_as_previous"),
    ]
    context = ValidationContext(data={"positions": [], "markups": clean}, metadata={"locale": "en"})
    assert await MarkupContingencyNotOnProfit().validate(context) == []


# ── DACH through the PATCH path the panel uses ─────────────────────────────


class _FakeMarkupRepo:
    def __init__(self, rows: list[BOQMarkup]) -> None:
        self.rows = {row.id: row for row in rows}

    async def get_by_id(self, markup_id: uuid.UUID) -> BOQMarkup | None:
        return self.rows.get(markup_id)

    async def update_fields(self, markup_id: uuid.UUID, **fields: object) -> BOQMarkup | None:
        row = self.rows[markup_id]
        for key, value in fields.items():
            setattr(row, key, value)
        return row

    def ordered(self) -> list[BOQMarkup]:
        return sorted(self.rows.values(), key=lambda row: row.sort_order)


@pytest.fixture
def service_over(monkeypatch: pytest.MonkeyPatch):
    async def _no_publish(*_args: object, **_kwargs: object) -> None:
        return None

    async def _not_locked(_self: BOQService, _boq_id: uuid.UUID) -> None:
        return None

    monkeypatch.setattr(boq_service, "_safe_publish", _no_publish)
    monkeypatch.setattr(BOQService, "_ensure_not_locked", _not_locked)

    def _build(rows: list[BOQMarkup]) -> tuple[BOQService, _FakeMarkupRepo]:
        service = BOQService.__new__(BOQService)
        repo = _FakeMarkupRepo(rows)
        service.markup_repo = repo  # type: ignore[assignment]
        service.session = None  # type: ignore[assignment]
        return service, repo

    return _build


@pytest.mark.asyncio
async def test_dach_w_and_g_on_the_same_base(service_over) -> None:
    """EKT 1,000,000; BGK 8 % on positions; AGK 9 % running; W 2 % running; G 3 % same base as W.

    Bases: BGK 1,000,000 (EKT), AGK 1,080,000 (Herstellkosten),
    W 1,177,200 and G 1,177,200 (Selbstkosten = Herstellkosten + AGK).
    """
    bgk = _mk("BGK", "8", sort_order=0)
    agk = _mk("AGK", "9", sort_order=1)
    w = _mk("W", "2", sort_order=2, category="contingency")
    g = _mk("G", "3", sort_order=3, category="profit")
    service, repo = service_over([bgk, agk, w, g])

    await service.update_markup(agk.id, MarkupUpdate.model_validate({"apply_to": "cumulative"}))
    await service.update_markup(w.id, MarkupUpdate.model_validate({"apply_to": "cumulative"}))
    await service.update_markup(g.id, MarkupUpdate.model_validate({"apply_to": "same_as_previous"}))
    assert g.apply_to == "same_as_previous"

    bases = _bases(D("1000000"), repo.ordered())
    assert bases == {
        "BGK": D("1000000"),
        "AGK": D("1080000"),
        "W": D("1177200"),
        "G": D("1177200"),
    }
    amounts = _amounts(D("1000000"), repo.ordered())
    assert amounts["W"] == D("23544")
    assert amounts["G"] == D("35316")
    assert D("1000000") + sum(amounts.values(), D("0")) == D("1236060")


@pytest.mark.asyncio
async def test_the_dach_template_with_w_and_g_as_two_rows(service_over) -> None:
    """The shipped DACH template, edited the way a German estimator would.

    The template ships every line on the EKT. In the panel the estimator moves
    AGK onto Herstellkosten and W onto Selbstkosten (running total), and sets
    G to the same base as W, so W and G stay two rows and are both charged on
    the Selbstkosten. MwSt stays on the running total of everything above.
    """
    rows = [
        _mk(
            str(entry["name"]),
            str(entry["percentage"]),
            apply_to=str(entry["apply_to"]),
            sort_order=int(entry["sort_order"]),
            category=str(entry["category"]),
        )
        for entry in DEFAULT_MARKUP_TEMPLATES["DACH"]
    ]
    by_name = {row.name: row for row in rows}
    service, repo = service_over(rows)

    # The template as shipped prices exactly as before.
    shipped = _amounts(D("1000000"), repo.ordered())
    assert shipped["Wagnis (W)"] == D("20000")
    assert shipped["Gewinn (G)"] == D("30000")

    agk = by_name["Allgemeine Geschäftskosten (AGK)"]
    w = by_name["Wagnis (W)"]
    g = by_name["Gewinn (G)"]
    await service.update_markup(agk.id, MarkupUpdate.model_validate({"apply_to": "cumulative"}))
    await service.update_markup(w.id, MarkupUpdate.model_validate({"apply_to": "cumulative"}))
    await service.update_markup(g.id, MarkupUpdate.model_validate({"apply_to": "same_as_previous"}))

    bases = _bases(D("1000000"), repo.ordered())
    herstellkosten = D("1100000")  # EKT + BGK 10 %
    selbstkosten = D("1188000")  # + AGK 8 % of Herstellkosten
    assert bases["Allgemeine Geschäftskosten (AGK)"] == herstellkosten
    assert bases["Wagnis (W)"] == selbstkosten
    assert bases["Gewinn (G)"] == selbstkosten
    # MwSt on Selbstkosten + W 23,760 + G 35,640.
    assert bases["Mehrwertsteuer (MwSt.)"] == D("1247400")
