"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Rework cost on a punch item, entered and then edited from the punch list.

The punch list screen now prices a snag when it is raised and lets the price be
changed later from the item drawer. The schema tests elsewhere check that a
rework cost string validates; these check the path the drawer takes: a
``PunchItemUpdate`` through ``PunchListService.update_item`` onto the row.

The value matters beyond the punch list. QMS folds open items' rework cost into
the cost of poor quality, grouped by ``rework_cost_currency``, and the US pack
withholds a multiple of the open items' value from the retainage released at
substantial completion. So the currency has to arrive, stay, and be spelled
one way.

The repository is stubbed, so the null-currency test proves the schema refuses
the value before it reaches the row. It does not exercise the NOT NULL column
itself; a null there used to surface as an IntegrityError at flush.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.punchlist.schemas import PunchItemCreate, PunchItemUpdate
from app.modules.punchlist.service import PunchListService

PROJECT_ID = uuid.uuid4()


class _StubSession:
    async def refresh(self, obj: Any) -> None:
        pass


class _StubPunchRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self.updates: list[dict[str, Any]] = []

    async def create(self, item: Any) -> Any:
        item.id = uuid.uuid4()
        item.created_at = item.updated_at = datetime.now(UTC)
        self.rows[item.id] = item
        return item

    async def get_by_id(self, item_id: uuid.UUID) -> Any:
        return self.rows.get(item_id)

    async def update_fields(self, item_id: uuid.UUID, **kwargs: Any) -> None:
        self.updates.append(kwargs)
        item = self.rows[item_id]
        for key, value in kwargs.items():
            setattr(item, key, value)


def _service() -> PunchListService:
    svc = PunchListService.__new__(PunchListService)
    svc.session = _StubSession()
    svc.repo = _StubPunchRepo()
    return svc


async def _priced_item(svc: PunchListService, cost: str | None = "1200", currency: str = "EUR") -> Any:
    return await svc.create_item(
        PunchItemCreate(
            project_id=PROJECT_ID,
            title="Touch up paint at stair core",
            rework_cost=cost,
            rework_cost_currency=currency,
        ),
        user_id="u1",
    )


class _StubProjectRepo:
    """Stands in for ProjectRepository, which the create path looks the currency up in."""

    currency: str | None = "EUR"
    raises = False

    def __init__(self, session: Any) -> None:
        self.session = session

    async def get_by_id(self, project_id: uuid.UUID) -> Any:
        if _StubProjectRepo.raises:
            raise RuntimeError("no projects module here")
        return SimpleNamespace(id=project_id, currency=_StubProjectRepo.currency)


@pytest.fixture(autouse=True)
def _stub_projects(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.projects import repository as project_repository

    _StubProjectRepo.currency = "EUR"
    _StubProjectRepo.raises = False
    monkeypatch.setattr(project_repository, "ProjectRepository", _StubProjectRepo)


@pytest.mark.asyncio
async def test_an_item_raised_without_a_currency_takes_the_projects_own() -> None:
    # A snag from a clash, an inspection or an NCR never names a currency, and
    # the schema default is USD. On a euro job that used to file the item in a
    # currency neither the COPQ report nor the retainage withholding reads.
    svc = _service()
    item = await svc.create_item(PunchItemCreate(project_id=PROJECT_ID, title="Cracked screed"), user_id="u1")
    assert item.rework_cost_currency == "EUR"


@pytest.mark.asyncio
async def test_a_currency_the_caller_named_is_kept_even_when_it_is_usd() -> None:
    svc = _service()
    item = await svc.create_item(
        PunchItemCreate(project_id=PROJECT_ID, title="x", rework_cost_currency="USD"),
        user_id="u1",
    )
    assert item.rework_cost_currency == "USD"


@pytest.mark.asyncio
@pytest.mark.parametrize("project_currency", [None, "", "   ", "EURO", "E1R"])
async def test_a_project_without_a_usable_currency_falls_back_to_usd(project_currency: str | None) -> None:
    # An undecided project currency is a legitimate state, not an error.
    _StubProjectRepo.currency = project_currency
    svc = _service()
    item = await svc.create_item(PunchItemCreate(project_id=PROJECT_ID, title="x"), user_id="u1")
    assert item.rework_cost_currency == "USD"


@pytest.mark.asyncio
async def test_a_failed_project_lookup_falls_back_to_usd_instead_of_failing_the_create() -> None:
    _StubProjectRepo.raises = True
    svc = _service()
    item = await svc.create_item(PunchItemCreate(project_id=PROJECT_ID, title="x"), user_id="u1")
    assert item.rework_cost_currency == "USD"


@pytest.mark.asyncio
async def test_create_stores_the_cost_in_the_currency_it_was_given() -> None:
    svc = _service()
    item = await _priced_item(svc, cost="1200.50", currency="EUR")
    assert item.rework_cost == "1200.5"
    assert item.rework_cost_currency == "EUR"


@pytest.mark.asyncio
async def test_update_writes_a_new_cost_and_currency_onto_the_row() -> None:
    svc = _service()
    item = await _priced_item(svc, cost=None, currency="USD")

    updated = await svc.update_item(item.id, PunchItemUpdate(rework_cost="850.00", rework_cost_currency="CAD"))

    assert updated.rework_cost == "850"
    assert updated.rework_cost_currency == "CAD"


@pytest.mark.asyncio
async def test_update_without_a_currency_keeps_the_stored_one() -> None:
    svc = _service()
    item = await _priced_item(svc, cost="1200", currency="EUR")

    await svc.update_item(item.id, PunchItemUpdate(rework_cost="900"))

    assert svc.repo.updates[-1] == {"rework_cost": "900"}
    assert item.rework_cost_currency == "EUR"


@pytest.mark.asyncio
async def test_update_with_a_null_cost_clears_the_amount_and_keeps_the_currency() -> None:
    svc = _service()
    item = await _priced_item(svc, cost="1200", currency="EUR")

    await svc.update_item(item.id, PunchItemUpdate(rework_cost=None))

    # A cleared cost means nobody has priced the item, which QMS counts as
    # unpriced rather than as zero. The explicit null has to reach the row.
    assert svc.repo.updates[-1] == {"rework_cost": None}
    assert item.rework_cost is None
    assert item.rework_cost_currency == "EUR"


@pytest.mark.parametrize(
    ("typed", "stored"),
    [("900", "900"), ("1000.00", "1000"), ("850.50", "850.5"), ("0", "0"), ("12.34567", "12.3457")],
)
@pytest.mark.parametrize("model", ["create", "update"])
def test_a_round_amount_is_stored_without_an_exponent(model: str, typed: str, stored: str) -> None:
    # str() of a normalised Decimal("900") is "9E+2", which is what the API
    # used to hand back and what the drawer would have put in the edit box.
    if model == "create":
        payload = PunchItemCreate(project_id=PROJECT_ID, title="x", rework_cost=typed)
    else:
        payload = PunchItemUpdate(rework_cost=typed)
    assert payload.rework_cost == stored


def test_update_refuses_a_null_currency() -> None:
    with pytest.raises(ValidationError, match="rework_cost_currency cannot be null"):
        PunchItemUpdate(rework_cost="100", rework_cost_currency=None)


@pytest.mark.parametrize("model", ["create", "update"])
def test_a_lower_case_currency_is_stored_upper_case(model: str) -> None:
    if model == "create":
        payload = PunchItemCreate(project_id=PROJECT_ID, title="x", rework_cost="1", rework_cost_currency=" eur ")
    else:
        payload = PunchItemUpdate(rework_cost="1", rework_cost_currency="eur")
    assert payload.rework_cost_currency == "EUR"


@pytest.mark.parametrize("bad", ["", "EU", "E1R", "€€€"])
@pytest.mark.parametrize("model", ["create", "update"])
def test_a_currency_that_is_not_an_iso_code_is_refused(model: str, bad: str) -> None:
    if model == "create":
        with pytest.raises(ValidationError, match="rework_cost_currency"):
            PunchItemCreate(project_id=PROJECT_ID, title="x", rework_cost_currency=bad)
    else:
        with pytest.raises(ValidationError, match="rework_cost_currency"):
            PunchItemUpdate(rework_cost_currency=bad)


def test_create_without_a_currency_still_defaults_to_usd() -> None:
    # Unchanged behaviour, pinned so the screen knows it must send the
    # project's currency: the backend does not look the project up.
    assert PunchItemCreate(project_id=PROJECT_ID, title="x").rework_cost_currency == "USD"
