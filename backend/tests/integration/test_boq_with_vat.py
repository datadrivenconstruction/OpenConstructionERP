# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Where a bill of quantities keeps its consumption tax, and where it does not.

Tax on a bill is a markup row of category ``tax``. There is no ``tax_rate``
column: ``BOQ`` does not declare one, the service never writes one, and
``BOQTotals`` says outright that the matching output fields hold their
defaults for wire compatibility only. The input schemas went on accepting a
rate anyway, with a worked example of ``0.19`` beside the field, and the two
write paths lost it differently - ``POST /boqs/`` dropped it and answered 201,
``PATCH /boqs/{id}`` reached ``update(BOQ).values(tax_rate=...)`` and raised
``CompileError: Unconsumed column names: tax_rate``, which the global handler
turns into a 500.

This file used to be the reason that looked covered. It asserted
``grand_total == net_total + tax_amount`` against a ``BOQWithSections`` it
built itself, with the tax arithmetic done in the test body. Nothing in the
service performs that arithmetic, so every assertion was about the test's own
multiplication and the schema's field list, and all of it passed while the
value was being thrown away one layer down.

What replaces it has to fail in both directions, so there are three groups:

* A rate is refused, on create and on update, with a message naming the markup
  row. Red if the guard is dropped and the value goes back to being lost.
* Omitting the field, and sending an explicit ``null``, both go through - to
  the service and to the database, not just to the schema. ``BOQListItem`` and
  ``BOQWithSections`` still emit ``tax_rate``, so a client that reads a bill
  and sends the object back carries a null, and it is the caller that must not
  be refused. Red if the guard over-fires.
* The path that does carry tax still prices: a ``category == "tax"`` markup
  reaches the grand total through ``compute_boq_totals``. Red if the refusal
  is ever "fixed" by taking the real tax route out with it.

The last group is the one with teeth. A test that only proves ``None`` is
accepted would pass against a module where tax did not work at all.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from pydantic import ValidationError

from app.modules.boq.models import BOQ
from app.modules.boq.schemas import (
    TAX_RATE_NOT_STORED_MESSAGE,
    BOQCreate,
    BOQUpdate,
    MarkupCreate,
    PositionCreate,
)
from app.modules.boq.service import BOQService
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session():
    """A transaction-isolated PostgreSQL session, rolled back on teardown.

    Foreign keys are off because the project these tests seed has no real
    owner row behind it, the same arrangement
    ``test_ai_agents_apply_endpoints.py`` uses in this directory.
    """
    async with transactional_session(disable_fks=True) as live:
        yield live


#: The shapes a rate arrives in: the fraction the old field documented, the
#: percentage a reader of "19 %" would send instead, the string the old
#: ``examples`` entry actually used, a float, and the two zeros that look
#: harmless. All are refused, and all for the same reason, so none of them may
#: come back with a bounds message about a number nothing stores.
REFUSED_RATES: tuple[object, ...] = (Decimal("0.19"), 19, "0.19", 0.19, 0, Decimal("0"))


def _create(**overrides: object) -> BOQCreate:
    """A valid ``BOQCreate`` for a fixed project, with fields overridden."""
    payload: dict[str, object] = {
        "project_id": "00000000-0000-0000-0000-000000000001",
        "name": "Test BOQ",
    }
    payload.update(overrides)
    return BOQCreate(**payload)  # type: ignore[arg-type]


def _rate_errors(exc: ValidationError) -> list[dict]:
    """The validation entries that are about ``tax_rate``."""
    return [err for err in exc.errors() if "tax_rate" in (err.get("loc") or ())]


async def _seed_project(session, label: str):
    """A saved project to hang a bill on.

    ``owner_id`` is a generated id rather than a real user: the fixture runs
    with foreign keys off, and nothing under test reads the owner.
    """
    from app.modules.projects.models import Project

    project = Project(name=f"{label} {uuid.uuid4().hex[:6]}", currency="EUR", owner_id=str(uuid.uuid4()))
    session.add(project)
    await session.flush()
    return project


# ── A rate is refused, and the refusal says where tax lives ─────────────────


class TestARateIsRefused:
    """Neither write schema accepts a tax rate, whatever shape it arrives in."""

    @pytest.mark.parametrize("rate", REFUSED_RATES)
    def test_create_refuses_a_rate(self, rate: object) -> None:
        with pytest.raises(ValidationError) as caught:
            _create(tax_rate=rate)
        errors = _rate_errors(caught.value)
        assert errors, f"{rate!r} was accepted on BOQCreate, so it is being dropped again"
        assert TAX_RATE_NOT_STORED_MESSAGE in errors[0]["msg"]

    @pytest.mark.parametrize("rate", REFUSED_RATES)
    def test_update_refuses_a_rate(self, rate: object) -> None:
        with pytest.raises(ValidationError) as caught:
            BOQUpdate(tax_rate=rate)  # type: ignore[arg-type]
        errors = _rate_errors(caught.value)
        assert errors, f"{rate!r} was accepted on BOQUpdate, so PATCH still reaches a missing column"
        assert TAX_RATE_NOT_STORED_MESSAGE in errors[0]["msg"]

    def test_the_refusal_names_the_markup_row(self) -> None:
        """The message has to be actionable, not just a denial.

        A caller told "no" and nothing else writes the rate into the name or
        the description next, which is how the number ends up somewhere the
        totals engine cannot see it either.
        """
        assert "markup" in TAX_RATE_NOT_STORED_MESSAGE
        assert "'tax'" in TAX_RATE_NOT_STORED_MESSAGE
        assert "/markups/" in TAX_RATE_NOT_STORED_MESSAGE

    def test_a_rate_is_refused_before_it_is_parsed(self) -> None:
        """Garbage gets the same answer as a well-formed rate.

        The old field carried ``ge=0, le=1``, so ``1.5`` came back as "less
        than or equal to 1" - a bounds message about a value nothing stores,
        which reads as "use a smaller one" rather than "use a markup row".
        """
        for sent in ("nineteen_percent", "1.5", "-0.01"):
            with pytest.raises(ValidationError) as caught:
                _create(tax_rate=sent)
            assert TAX_RATE_NOT_STORED_MESSAGE in _rate_errors(caught.value)[0]["msg"]


# ── The callers that must still get through ────────────────────────────────


class TestTheAllowedCallers:
    """Omitted and explicit-null both work, at the schema and at the service."""

    def test_omitted_is_accepted(self) -> None:
        assert _create().tax_rate is None
        assert BOQUpdate().tax_rate is None

    def test_explicit_null_is_accepted(self) -> None:
        """The round-tripping client's shape.

        ``BOQListItem`` and ``BOQWithSections`` both emit ``tax_rate`` as
        null. A client that reads one, changes a name and sends the object
        back is changing nothing here, and refusing it would break the only
        flow that sends this field at all.
        """
        assert _create(tax_rate=None).tax_rate is None
        assert BOQUpdate(tax_rate=None).tax_rate is None

    def test_an_explicit_null_never_reaches_the_update_statement(self) -> None:
        """``exclude`` on the update field, measured rather than asserted by eye.

        ``BOQService.update_boq`` dumps with ``exclude_unset=True`` and hands
        the result to ``update(BOQ).values(**fields)``. An explicit null is
        set, so without ``exclude`` it survives the dump and names a column
        the table does not have.
        """
        dumped = BOQUpdate(name="Renamed", tax_rate=None).model_dump(exclude_unset=True)
        assert "tax_rate" not in dumped, (
            "An explicit null survives the dump and will reach update(BOQ).values(), "
            "which raises CompileError: Unconsumed column names: tax_rate"
        )
        assert dumped == {"name": "Renamed"}
        assert set(dumped) <= set(BOQ.__table__.columns.keys()), (
            "update_boq hands these keys to update(BOQ).values(); every one of them has to be "
            "a column on oe_boq_boq or the statement fails to compile"
        )

    @pytest.mark.asyncio
    async def test_the_allowed_shapes_reach_the_database(self, session) -> None:
        """Through the service, not just through the schema.

        The version of this file that these tests replace never called the
        service, which is exactly why it never noticed the value was being
        dropped behind it.
        """
        project = await _seed_project(session, "Tax")
        service = BOQService(session)
        omitted = await service.create_boq(_create(project_id=project.id, name="Omitted"))
        explicit = await service.create_boq(_create(project_id=project.id, name="Null", tax_rate=None))
        assert omitted.id is not None
        assert explicit.id is not None

        # And the PATCH the round-tripping client sends.
        renamed = await service.update_boq(explicit.id, BOQUpdate(name="Null renamed", tax_rate=None))
        assert renamed.name == "Null renamed"


# ── The route tax actually takes ───────────────────────────────────────────


class TestTaxStillPrices:
    """A ``category == "tax"`` markup reaches the grand total.

    This is the population the refusal must not break. Asserting only that a
    null ``tax_rate`` is accepted would pass just as well against a build
    where tax did not work at all, so the number is checked end to end.
    """

    @pytest.mark.asyncio
    async def test_a_tax_markup_is_charged_on_the_marked_up_total(self, session) -> None:
        project = await _seed_project(session, "VAT")
        service = BOQService(session)
        boq = await service.create_boq(_create(project_id=project.id, name="Priced"))
        await service.add_position(
            PositionCreate(
                boq_id=boq.id,
                ordinal="01",
                description="Reinforced concrete wall",
                unit="m3",
                quantity=100.0,
                unit_rate=Decimal("1.00"),
            )
        )
        await service.add_markup(
            boq.id,
            MarkupCreate(
                name="VAT 19%",
                markup_type="percentage",
                category="tax",
                percentage=19.0,
                apply_to="cumulative",
                sort_order=10,
            ),
        )
        await session.flush()

        totals = (await service.compute_boq_totals([boq.id]))[boq.id]
        direct = Decimal(str(totals["direct_cost"]))
        grand = Decimal(str(totals["grand_total"]))
        assert direct == Decimal("100.00"), totals
        assert grand == Decimal("119.00"), (
            "A tax markup of 19 % on a direct cost of 100 has to reach the grand total. "
            f"It did not, so the only route a bill has to its tax is broken: {totals}"
        )


# ── The shape of the defect, so the next one is caught ─────────────────────


@pytest.mark.parametrize("schema", [BOQCreate, BOQUpdate])
def test_no_write_field_names_a_column_the_bill_does_not_have(schema: type) -> None:
    """Every field on a BOQ write schema is either stored or refused.

    This is the general form of the defect. ``tax_rate`` was declared on both
    write schemas, described with a worked example, and backed by nothing -
    and the only thing that noticed was a migration round-trip test recording
    the orphan column at the other end of the chain.

    A field that names no column is allowed, but only when every non-null
    value is refused rather than accepted, so it can keep its place on the
    wire without being a way to lose data. Several probe values are tried and
    all of them have to be refused: a field that happens to reject the one
    shape the probe picked, while accepting its own type, is exactly the
    silent drop this is looking for.
    """
    columns = set(BOQ.__table__.columns.keys())
    unbacked = sorted(name for name in schema.model_fields if name not in columns)
    print(f"{schema.__name__}: {len(schema.model_fields)} fields, {len(unbacked)} name no column: {unbacked}")

    for name in unbacked:
        for probe in ("x", 1, Decimal("0.19"), True):
            try:
                schema(**{"project_id": uuid.uuid4(), "name": "Probe", name: probe})  # type: ignore[arg-type]
            except ValidationError as exc:
                if any(name in (err.get("loc") or ()) for err in exc.errors()):
                    continue
            pytest.fail(
                f"{schema.__name__}.{name} names no column on oe_boq_boq and accepts {probe!r}. "
                "On create such a value is dropped and the caller is told 201; on update it "
                "reaches update(BOQ).values() and raises CompileError, which the global handler "
                "turns into a 500. Refuse it, or store it."
            )
