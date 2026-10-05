# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The markup panel edits a line's base, type, amount, bands and order.

The BOQ markups panel used to edit a line's name, percentage and category and
nothing else, so every country's real stack needed an API call to build:

* Germany prices AGK and W+G on Herstellkosten (EKT + BGK), which is a
  ``cumulative`` base sitting after BGK, not the direct cost.
* France puts frais généraux on the déboursé sec and the bénéfice on the coût
  de revient, which again is a running total.
* A US surety prices a bond off a tiered card per 1,000 of contract sum.
* The UK puts risk on direct cost plus the other markups.

These tests drive the same ``PATCH`` path the panel now uses
(:meth:`BOQService.update_markup`) and then price the result with the
authoritative cascade, so a panel edit is proven to move the money the way the
estimator meant. No database is involved: the repository is a dictionary, and
what is under test is the service's handling of the payload and the cascade.

Run (CI):
    cd backend
    python -m pytest tests/unit/test_boq_markup_panel_edits.py -v
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from fastapi import HTTPException

import app.modules.boq.service as boq_service
from app.modules.boq.models import BOQMarkup
from app.modules.boq.schemas import MarkupUpdate
from app.modules.boq.service import BOQService, _calculate_markup_amounts

pytestmark = pytest.mark.asyncio


class _FakeMarkupRepo:
    """The two repository calls ``update_markup`` makes, over a dictionary."""

    def __init__(self, rows: list[BOQMarkup]) -> None:
        self.rows = {row.id: row for row in rows}

    async def get_by_id(self, markup_id: uuid.UUID) -> BOQMarkup | None:
        return self.rows.get(markup_id)

    async def update_fields(self, markup_id: uuid.UUID, **fields: object) -> BOQMarkup | None:
        row = self.rows.get(markup_id)
        if row is None:
            return None
        for key, value in fields.items():
            setattr(row, key, value)
        return row

    def ordered(self) -> list[BOQMarkup]:
        """Return the rows the way ``list_for_boq`` orders them: by ``sort_order``."""
        return sorted(self.rows.values(), key=lambda row: row.sort_order)


def _mk(
    name: str,
    *,
    percentage: str = "0",
    apply_to: str = "direct_cost",
    sort_order: int = 0,
    category: str = "overhead",
    markup_type: str = "percentage",
    metadata: dict[str, Any] | None = None,
) -> BOQMarkup:
    markup = BOQMarkup(
        boq_id=uuid.uuid4(),
        name=name,
        markup_type=markup_type,
        category=category,
        percentage=percentage,
        fixed_amount="0",
        apply_to=apply_to,
        sort_order=sort_order,
        is_active=True,
        metadata_=metadata or {},
    )
    markup.id = uuid.uuid4()
    return markup


@pytest.fixture
def make_service(monkeypatch: pytest.MonkeyPatch):
    """Build a service over a fake repository with the lock check and events off."""

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


def _priced(repo: _FakeMarkupRepo, direct_cost: Decimal) -> dict[str, Decimal]:
    return {row.name: amount for row, amount in _calculate_markup_amounts(direct_cost, repo.ordered())}


# ── The update path accepts every field the panel now sends ─────────────────


async def test_update_persists_base_type_amount_and_order(make_service) -> None:
    line = _mk("Site set-up")
    service, repo = make_service([line])

    await service.update_markup(
        line.id,
        MarkupUpdate.model_validate(
            {"markup_type": "fixed", "fixed_amount": "12500.50", "apply_to": "cumulative", "sort_order": 3}
        ),
    )

    assert line.markup_type == "fixed"
    # Money arrives as a string and is stored as the exact Decimal text, not a float.
    assert Decimal(line.fixed_amount) == Decimal("12500.50")
    assert line.apply_to == "cumulative"
    assert line.sort_order == 3
    assert _priced(repo, Decimal("100000"))["Site set-up"] == Decimal("12500.50")


async def test_switching_to_banded_with_a_card_is_accepted_and_prices_by_tranche(make_service) -> None:
    line = _mk("Bond", percentage="1.0", category="bond")
    service, repo = make_service([line])

    await service.update_markup(
        line.id,
        MarkupUpdate.model_validate(
            {
                "markup_type": "banded",
                "metadata": {
                    "bands": [
                        {"up_to": "100000", "percentage": "2.5"},
                        {"up_to": None, "percentage": "1.5"},
                    ]
                },
            }
        ),
    )

    assert line.markup_type == "banded"
    # 100,000 at 2.5 % plus 50,000 at 1.5 %.
    assert _priced(repo, Decimal("150000"))["Bond"] == Decimal("3250")


async def test_switching_to_banded_without_a_card_is_refused(make_service) -> None:
    line = _mk("Bond", percentage="1.0", category="bond")
    service, _repo = make_service([line])

    with pytest.raises(HTTPException) as exc:
        await service.update_markup(line.id, MarkupUpdate.model_validate({"markup_type": "banded"}))
    assert exc.value.status_code == 422
    assert line.markup_type == "percentage"


async def test_a_new_card_replaces_the_old_one_rather_than_merging_into_it(make_service) -> None:
    line = _mk(
        "Bond",
        markup_type="banded",
        category="bond",
        metadata={"bands": [{"up_to": "1000", "percentage": "5"}, {"up_to": None, "percentage": "1"}], "note": "keep"},
    )
    service, repo = make_service([line])

    await service.update_markup(
        line.id,
        MarkupUpdate.model_validate({"metadata": {"bands": [{"up_to": None, "percentage": "2"}]}}),
    )

    assert line.metadata_["bands"] == [{"up_to": None, "percentage": "2"}]
    # Other keys on the row survive a panel save of the card.
    assert line.metadata_["note"] == "keep"
    assert _priced(repo, Decimal("10000"))["Bond"] == Decimal("200")


@pytest.mark.parametrize(
    ("bands", "fragment"),
    [
        ([{"up_to": "1000", "percentage": "2"}, {"up_to": "1000", "percentage": "1"}], "same ceiling"),
        ([{"up_to": None, "percentage": "2"}, {"up_to": None, "percentage": "1"}], "open-ended"),
        ([{"up_to": "-5", "percentage": "2"}], "above zero"),
        ([{"up_to": None, "percentage": "120"}], "0 to 100"),
        ([{"up_to": "abc", "percentage": "2"}], "cannot be read"),
    ],
)
async def test_a_card_that_cannot_mean_one_thing_is_refused(
    make_service, bands: list[dict[str, Any]], fragment: str
) -> None:
    line = _mk("Bond", category="bond")
    service, _repo = make_service([line])

    with pytest.raises(HTTPException) as exc:
        await service.update_markup(
            line.id, MarkupUpdate.model_validate({"markup_type": "banded", "metadata": {"bands": bands}})
        )
    assert exc.value.status_code == 422
    assert fragment in str(exc.value.detail)


# ── Cascade order follows sort_order ────────────────────────────────────────


async def test_moving_a_line_changes_what_later_lines_compound_on(make_service) -> None:
    overhead = _mk("Overhead", percentage="10", sort_order=0)
    profit = _mk("Profit", percentage="5", apply_to="cumulative", sort_order=1)
    service, repo = make_service([overhead, profit])

    before = _priced(repo, Decimal("1000"))
    assert before == {"Overhead": Decimal("100"), "Profit": Decimal("55")}

    # The panel's "move up" renumbers both rows.
    await service.update_markup(profit.id, MarkupUpdate.model_validate({"sort_order": 0}))
    await service.update_markup(overhead.id, MarkupUpdate.model_validate({"sort_order": 1}))

    # Profit now runs first, on the direct cost alone.
    assert [row.name for row in repo.ordered()] == ["Profit", "Overhead"]
    assert _priced(repo, Decimal("1000")) == {"Profit": Decimal("50"), "Overhead": Decimal("100")}


# ── Country stacks an estimator can now build in the panel ──────────────────


async def test_german_agk_and_wg_on_herstellkosten(make_service) -> None:
    """EKT 100,000; BGK 10 % on EKT; AGK 8 % on Herstellkosten; W+G 5 % on Selbstkosten; MwSt 19 %.

    Starts from the DACH template's shape, every line on the direct cost, and
    applies the two panel edits a German estimator makes: AGK becomes
    cumulative so it sits on EKT + BGK, and W+G becomes cumulative so it sits
    on the Selbstkosten.
    """
    bgk = _mk("BGK", percentage="10", sort_order=0)
    agk = _mk("AGK", percentage="8", sort_order=1)
    wg = _mk("W+G", percentage="5", sort_order=2, category="profit")
    vat = _mk("MwSt", percentage="19", apply_to="cumulative", sort_order=3, category="tax")
    service, repo = make_service([bgk, agk, wg, vat])

    await service.update_markup(agk.id, MarkupUpdate.model_validate({"apply_to": "cumulative"}))
    await service.update_markup(wg.id, MarkupUpdate.model_validate({"apply_to": "cumulative"}))

    amounts = _priced(repo, Decimal("100000"))
    herstellkosten = Decimal("100000") + amounts["BGK"]
    selbstkosten = herstellkosten + amounts["AGK"]
    angebot_netto = selbstkosten + amounts["W+G"]

    assert amounts["BGK"] == Decimal("10000")
    assert herstellkosten == Decimal("110000")
    assert amounts["AGK"] == Decimal("8800")
    assert selbstkosten == Decimal("118800")
    assert amounts["W+G"] == Decimal("5940")
    assert angebot_netto == Decimal("124740")
    assert amounts["MwSt"] == Decimal("23700.60")
    assert angebot_netto + amounts["MwSt"] == Decimal("148440.60")


async def test_french_frais_generaux_on_debourse_and_benefice_on_cout_de_revient(make_service) -> None:
    fg = _mk("Frais généraux", percentage="12", sort_order=0)
    benefice = _mk("Bénéfice", percentage="6", sort_order=1, category="profit")
    service, repo = make_service([fg, benefice])

    await service.update_markup(benefice.id, MarkupUpdate.model_validate({"apply_to": "cumulative"}))

    amounts = _priced(repo, Decimal("200000"))
    # Coût de revient = déboursé sec 200,000 + frais généraux 24,000.
    assert amounts["Frais généraux"] == Decimal("24000")
    assert amounts["Bénéfice"] == Decimal("13440")


async def test_us_surety_bond_on_a_tiered_card_per_thousand(make_service) -> None:
    """A performance bond off a typical tiered card, rates per 1,000 written as percent.

    25 per 1,000 on the first 100,000 (2.5 %), 15 per 1,000 on the next
    400,000 (1.5 %), 10 per 1,000 on the next 2,000,000 (1.0 %), 7.50 per
    1,000 above that (0.75 %). The bond sits on the contract sum, so it is the
    last line and cumulative.
    """
    overhead = _mk("Overhead & profit", percentage="15", sort_order=0, category="overhead")
    bond = _mk("Performance bond", percentage="0", sort_order=1, category="bond")
    service, repo = make_service([overhead, bond])

    await service.update_markup(
        bond.id,
        MarkupUpdate.model_validate(
            {
                "markup_type": "banded",
                "apply_to": "cumulative",
                "metadata": {
                    "bands": [
                        {"up_to": "100000", "percentage": "2.5"},
                        {"up_to": "500000", "percentage": "1.5"},
                        {"up_to": "2500000", "percentage": "1.0"},
                        {"up_to": None, "percentage": "0.75"},
                    ]
                },
            }
        ),
    )

    amounts = _priced(repo, Decimal("2800000"))
    # Contract sum 2,800,000 + 420,000 = 3,220,000.
    # 2,500 + 6,000 + 20,000 + 720,000 * 0.75 % (5,400) = 33,900.
    assert amounts["Overhead & profit"] == Decimal("420000")
    assert amounts["Performance bond"] == Decimal("33900")


async def test_uk_risk_on_direct_cost_plus_the_other_markups(make_service) -> None:
    prelims = _mk("Preliminaries", percentage="13", sort_order=0)
    ohp = _mk("Overheads and profit", percentage="6", sort_order=1, apply_to="cumulative", category="profit")
    risk = _mk("Risk", percentage="5", sort_order=2, category="contingency")
    service, repo = make_service([prelims, ohp, risk])

    await service.update_markup(risk.id, MarkupUpdate.model_validate({"apply_to": "cumulative"}))

    amounts = _priced(repo, Decimal("1000000"))
    assert amounts["Preliminaries"] == Decimal("130000")
    assert amounts["Overheads and profit"] == Decimal("67800")
    # 5 % of 1,000,000 + 130,000 + 67,800.
    assert amounts["Risk"] == Decimal("59890")
