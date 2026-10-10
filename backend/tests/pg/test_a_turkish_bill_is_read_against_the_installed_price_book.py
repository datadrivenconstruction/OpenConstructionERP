"""PG: a Turkish bill is read against the installed unit-price base in one statement.

Two ``birimfiyat`` rules compare a line with the book it cites. A rule gets
data, not a session, so the surface that validates the bill looks the poz
numbers up first (``app.core.validation.poz_catalogue``) and hands the answer
in. These tests pin what that lookup costs and who pays it:

* one ``code IN (...)`` statement per chunk of poz numbers, whatever the size
  of the bill, and only rows of the national region that are active;
* a region with no rows is ``not_installed``, a base priced into another
  market is ``repriced``, and neither is mistaken for a book that agrees;
* a Turkish project's validation run, through the validation service and
  through the bill import, carries the two rules' results;
* a German project's run sends no statement to the cost tables at all.

The prices are invented for this file. Poz numbers and units are those of
chapters 25 and 35 of the Ministry book; its prices are not reproduced here.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import event

from app.core.validation.poz_catalogue import (
    POZ_CATALOGUE_RULE_IDS,
    POZ_IN_CHUNK,
    RATE_RULE_ID,
    TR_POZ_REGION,
    UNIT_RULE_ID,
    PozCatalogueState,
    load_poz_catalogue,
)
from app.core.validation.rules import register_builtin_rules
from app.modules.boq.models import BOQ, Position
from app.modules.costs.models import CostBaseState, CostItem
from app.modules.projects.models import Project
from app.modules.users.models import User

_FROM_COST_ITEM = re.compile(r"\bFROM\s+oe_costs_item\b", re.IGNORECASE)
_CODE_IN = re.compile(r"\bcode\s+IN\b", re.IGNORECASE)
_COST_TABLES = re.compile(r"\boe_costs_(?:item|base_state)\b", re.IGNORECASE)

PIPE = "25.305.6704"  # m
CABLE = "35.140.5210"  # m
UPS = "35.180.1315"  # Ad


@contextmanager
def _statements(session) -> Iterator[list[str]]:
    """Every SQL statement the session's connection sends while the block runs."""
    seen: list[str] = []
    engine = session.bind.engine.sync_engine

    def _record(_conn, _cursor, statement, _params, _context, _many) -> None:
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", _record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", _record)


def _lookups(statements: list[str]) -> list[str]:
    return [s for s in statements if _FROM_COST_ITEM.search(s) and _CODE_IN.search(s)]


def _item(code: str, unit: str, rate: str, *, region: str = TR_POZ_REGION, **extra: Any) -> CostItem:
    return CostItem(
        code=code,
        description="Test kalemi",
        unit=unit,
        rate=rate,
        currency=extra.pop("currency", "TRY"),
        source="cwicr",
        region=region,
        **extra,
    )


async def _book(session) -> None:
    """Three national rows, plus the rows a careless query would also return."""
    session.add_all(
        [
            _item(PIPE, "m", "1000.00"),
            _item(CABLE, "m", "900.00"),
            _item(UPS, "Ad", "700000.00"),
            # Same number in the general market catalogue of the same country.
            _item(PIPE, "Ad", "5.00", region="TR_ISTANBUL"),
            # A national row that was switched off.
            _item("25.305.6705", "m", "1100.00", is_active=False),
        ]
    )
    await session.flush()


async def _bill(session, *, country: str, currency: str, standard: str, lines: list[tuple[str, str, str, str]]):
    """A project with one bill; each line is (key, code, unit, rate)."""
    owner = User(email=f"poz-{uuid.uuid4().hex[:8]}@example.test", hashed_password="x", full_name="Poz reader")
    session.add(owner)
    await session.flush()
    project = Project(
        name=f"Poz {country}",
        owner_id=owner.id,
        currency=currency,
        country_code=country,
        classification_standard=standard,
        validation_rule_sets=["boq_quality"],
    )
    session.add(project)
    await session.flush()
    boq = BOQ(project_id=project.id, name="Tesisat", estimate_type="detailed")
    session.add(boq)
    await session.flush()
    for number, (key, code, unit, rate) in enumerate(lines, start=1):
        session.add(
            Position(
                boq_id=boq.id,
                ordinal=f"1.{number}",
                description="Tesisat kalemi",
                unit=unit,
                quantity="10",
                unit_rate=rate,
                total=str(Decimal(rate) * 10),
                classification={key: code},
                sort_order=number,
            )
        )
    await session.flush()
    return project, boq


def _rule_sets(project: Project) -> list[str]:
    """The sets the Validate button resolves for the project, by the function it uses."""
    from app.modules.boq.router import _build_rule_sets

    return _build_rule_sets(
        project_rule_sets=project.validation_rule_sets or ["boq_quality"],
        classification_standard=project.classification_standard or "",
        region=project.region or "",
        country_code=project.country_code,
    )


# ── The loader ───────────────────────────────────────────────────────────────


async def test_the_book_is_read_in_one_statement_and_only_its_own_active_rows(pg_session) -> None:
    await _book(pg_session)
    with _statements(pg_session) as seen:
        catalogue = await load_poz_catalogue(pg_session, [PIPE, CABLE, UPS, "25.305.6705", "25.999.9999", PIPE])

    assert len(_lookups(seen)) == 1
    assert catalogue.state is PozCatalogueState.LOADED
    assert catalogue.asked == 5
    assert catalogue.home_currency == "TRY"
    assert set(catalogue.entries) == {PIPE, CABLE, UPS}
    pipe = catalogue.entries[PIPE]
    assert (pipe.unit, pipe.rate, pipe.currency) == ("m", Decimal("1000.00"), "TRY"), "the national row, not Istanbul's"
    with pytest.raises(TypeError):
        catalogue.entries["x"] = pipe  # type: ignore[index]


@pytest.mark.parametrize(("codes", "chunk", "expected"), [(12, 5, 3), (10, 5, 2), (1, 5, 1), (5000, POZ_IN_CHUNK, 1)])
async def test_one_statement_per_chunk_whatever_the_size_of_the_bill(
    pg_session, codes: int, chunk: int, expected: int
) -> None:
    await _book(pg_session)
    asked = [PIPE, *(f"25.{n // 10000:03d}.{n % 10000:04d}" for n in range(1, codes))]
    assert len(set(asked)) == codes
    with _statements(pg_session) as seen:
        catalogue = await load_poz_catalogue(pg_session, asked, chunk_size=chunk)

    assert len(_lookups(seen)) == expected
    assert catalogue.asked == codes
    assert PIPE in catalogue.entries


async def test_a_region_with_no_rows_is_not_installed_and_an_unmatched_bill_is_not(pg_session) -> None:
    empty = await load_poz_catalogue(pg_session, [PIPE])
    assert empty.state is PozCatalogueState.NOT_INSTALLED
    assert dict(empty.entries) == {}

    await _book(pg_session)
    unmatched = await load_poz_catalogue(pg_session, ["25.999.9999"])
    assert unmatched.state is PozCatalogueState.LOADED, "the book is there; it just does not have that number"
    assert dict(unmatched.entries) == {}


async def test_a_row_an_older_import_left_without_a_currency_is_in_the_currency_of_its_region(pg_session) -> None:
    """An empty currency is the region's own, as the cost module reads it, not a switched market."""
    pg_session.add(_item(PIPE, "m", "1000.00", currency=""))
    await pg_session.flush()
    catalogue = await load_poz_catalogue(pg_session, [PIPE])
    assert catalogue.state is PozCatalogueState.LOADED
    assert catalogue.entries[PIPE].currency == "TRY"


@pytest.mark.parametrize("field", ["active_market", "switching_to"])
async def test_a_base_switched_to_another_market_is_repriced(pg_session, field: str) -> None:
    await _book(pg_session)
    pg_session.add(CostBaseState(region=TR_POZ_REGION, **{field: "DE_BERLIN"}))
    await pg_session.flush()
    assert (await load_poz_catalogue(pg_session, [PIPE])).state is PozCatalogueState.REPRICED


async def test_a_base_recorded_as_at_home_is_loaded(pg_session) -> None:
    await _book(pg_session)
    pg_session.add(CostBaseState(region=TR_POZ_REGION, text_language="tr"))
    await pg_session.flush()
    assert (await load_poz_catalogue(pg_session, [PIPE])).state is PozCatalogueState.LOADED


async def test_a_row_stamped_with_another_currency_is_repriced_whatever_the_record_says(pg_session) -> None:
    pg_session.add(_item(PIPE, "m", "25.00", currency="EUR"))
    await pg_session.flush()
    assert (await load_poz_catalogue(pg_session, [PIPE])).state is PozCatalogueState.REPRICED


async def test_a_failed_read_is_unavailable_and_leaves_the_session_usable(pg_session, monkeypatch) -> None:
    from sqlalchemy import select

    from app.core.validation import poz_catalogue

    await _book(pg_session)

    async def _broken(session, codes, region, chunk_size):
        from sqlalchemy import text

        await session.execute(text("SELECT no_such_column FROM oe_costs_item"))

    monkeypatch.setattr(poz_catalogue, "_read", _broken)
    catalogue = await load_poz_catalogue(pg_session, [PIPE])
    assert catalogue.state is PozCatalogueState.UNAVAILABLE
    # The transaction the caller is in was not left aborted by the failure.
    assert (await pg_session.execute(select(CostItem.code).where(CostItem.code == PIPE).limit(1))).first()


# ── A validation run ─────────────────────────────────────────────────────────


async def test_a_turkish_run_carries_the_two_rules_and_a_german_run_asks_the_cost_tables_nothing(pg_session) -> None:
    from app.modules.validation.service import ValidationModuleService

    register_builtin_rules()
    await _book(pg_session)
    turkish, turkish_bill = await _bill(
        pg_session,
        country="TR",
        currency="TRY",
        standard="birimfiyat",
        lines=[
            ("birimfiyat", PIPE, "m", "1000.00"),  # as the book has it
            ("birimfiyat", CABLE, "m", "792.00"),  # 12 percent below
            ("birimfiyat", UPS, "m", "700000.00"),  # the book says Ad
            ("birimfiyat", "25.999.9999", "m", "10.00"),  # not in the book
        ],
    )
    german, german_bill = await _bill(
        pg_session,
        country="DE",
        currency="EUR",
        standard="din276",
        lines=[("din276", "330", "m2", "120.00"), ("din276", "340", "m2", "95.00")],
    )
    turkish_sets = _rule_sets(turkish)
    german_sets = _rule_sets(german)
    assert "birimfiyat" in turkish_sets
    assert "birimfiyat" not in german_sets

    service = ValidationModuleService(pg_session)
    with _statements(pg_session) as seen:
        started = time.perf_counter()
        report = await service.run_validation(turkish.id, turkish_bill.id, turkish_sets)
        elapsed_ms = (time.perf_counter() - started) * 1000
    assert len(_lookups(seen)) == 1, f"one lookup for the bill ({elapsed_ms:.0f} ms for the whole run)"

    ours = [r for r in report["results"] if r["rule_id"] in POZ_CATALOGUE_RULE_IDS]
    units = [r for r in ours if r["rule_id"] == UNIT_RULE_ID]
    rates = [r for r in ours if r["rule_id"] == RATE_RULE_ID]
    assert len(units) == 3, "the three lines whose poz the book has"
    unit_findings = [r for r in units if not r["passed"]]
    assert len(unit_findings) == 1
    assert unit_findings[0]["severity"] == "warning"
    assert UPS in unit_findings[0]["message"]
    assert len(rates) == 2, "the line in the wrong unit gets no rate verdict"
    rate_findings = [r for r in rates if not r["passed"]]
    assert len(rate_findings) == 1
    assert rate_findings[0]["severity"] == "info"
    assert "12.0 percent below" in rate_findings[0]["message"]
    assert CABLE in rate_findings[0]["message"]

    with _statements(pg_session) as seen:
        report = await service.run_validation(german.id, german_bill.id, german_sets)
    assert [s for s in seen if _COST_TABLES.search(s)] == [], "a German bill pays nothing for the Turkish book"
    assert not [r for r in report["results"] if r["rule_id"] in POZ_CATALOGUE_RULE_IDS]


async def test_the_bill_import_validation_reads_the_book_for_a_turkish_project_only(pg_session) -> None:
    from app.modules.boq.router import _run_import_validation
    from app.modules.boq.service import BOQService

    register_builtin_rules()
    turkish, turkish_bill = await _bill(
        pg_session,
        country="TR",
        currency="TRY",
        standard="birimfiyat",
        lines=[("birimfiyat", PIPE, "m", "1000.00"), ("birimfiyat", CABLE, "m", "900.00")],
    )
    german, german_bill = await _bill(
        pg_session, country="DE", currency="EUR", standard="din276", lines=[("din276", "330", "m2", "120.00")]
    )
    service = BOQService(pg_session)

    # No base installed: the Turkish import is told once that the book was not read.
    with _statements(pg_session) as seen:
        summary = await _run_import_validation(turkish_bill.id, service, pg_session)
    if summary is None:
        pytest.skip("inline import validation is switched off in this environment")
    assert len(_lookups(seen)) == 1
    ours = [r for r in summary["results"] if r["rule_id"] in POZ_CATALOGUE_RULE_IDS]
    assert len(ours) == 1
    assert ours[0]["severity"] == "info"
    assert not ours[0]["passed"]
    assert ours[0]["element_ref"] is None
    assert TR_POZ_REGION in ours[0]["message"]

    with _statements(pg_session) as seen:
        summary = await _run_import_validation(german_bill.id, service, pg_session)
    assert summary is not None
    assert [s for s in seen if _COST_TABLES.search(s)] == []
    assert not [r for r in summary["results"] if r["rule_id"] in POZ_CATALOGUE_RULE_IDS]
