# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The read side says which VAT rate is in force, and where it came from.

``compute_estimate`` substitutes the project's own rate for a stack's single
tax line, and everything downstream of the computation reports the figure it
used. The read path did not: it served the stored steps, so an editor showing
a tax line at nought belonged to a bill costed at the project's rate with
nothing on screen saying so. ``EffectiveVat`` is that missing sentence.

What is asserted here is the resolution, not the pricing. The pricing is
already held by ``test_one_country_one_markup_stack.py`` on the catalogue
branch and by ``tests/pg/test_methodology_takes_the_projects_vat.py`` on the
stored branch. This file holds the third statement, that a reader is told the
same thing the engine did, which is the one that was missing.

The project lookup is stubbed rather than stored, so these run in the plain
unit lane. What cannot be stubbed away is the rule for when a single project
figure may stand in for a stack: the resolver and the override read it from
one helper, and the last test here is what stops a future edit from restating
it in one place and not the other.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.modules.methodology.service import MethodologyService

_PROJECT = uuid.uuid4()


class _Stub:
    """A methodology with just the attribute the resolver reads."""

    def __init__(self, cascade_steps: list[dict[str, object]]) -> None:
        self.cascade_steps = cascade_steps


def _service(project_rate: str | None) -> MethodologyService:
    """A service whose project lookup answers ``project_rate`` and nothing else.

    Stubbing the lookup rather than the resolver keeps the rule under test:
    everything from "is there exactly one tax line" onwards is the real code.
    """
    service = MethodologyService.__new__(MethodologyService)

    async def _project_vat_rate(_project_id: uuid.UUID) -> str | None:
        return project_rate

    service._project_vat_rate = _project_vat_rate  # type: ignore[method-assign]
    return service


def _stack(rate: str, category: str = "tax") -> list[dict[str, object]]:
    return [
        {"key": "oh", "label": "Overhead", "category": "overhead", "kind": "percentage", "rate": "10"},
        {"key": "vat", "label": "VAT", "category": category, "kind": "percentage", "rate": rate},
    ]


@pytest.mark.asyncio
async def test_a_project_rate_is_reported_as_the_project_s() -> None:
    """The sharp case: the stack says nought, the project charges 25."""
    result = await _service("25").effective_vat(_Stub(_stack("0")), _PROJECT)

    assert result.rate == Decimal("25")
    assert result.source == "project"
    assert result.stored_rate == Decimal("0")
    assert result.differs_from_stored is True


@pytest.mark.asyncio
async def test_a_project_without_a_rate_leaves_the_methodology_speaking_for_itself() -> None:
    """No project rate means the stack's own tax line is the rate in force."""
    result = await _service(None).effective_vat(_Stub(_stack("19")), _PROJECT)

    assert result.rate == Decimal("19")
    assert result.source == "methodology"
    assert result.stored_rate == Decimal("19")
    assert result.differs_from_stored is False


@pytest.mark.asyncio
async def test_a_project_on_the_same_rate_is_not_announced_as_an_override() -> None:
    """Equal figures are not a divergence, however they were arrived at.

    Three Nordic templates already carry 25, so a correct override is a no-op
    by value there. Reporting that as a difference would put a notice on every
    Danish screen saying the rate had been replaced by the same rate.
    """
    result = await _service("25").effective_vat(_Stub(_stack("25")), _PROJECT)

    assert result.rate == Decimal("25")
    assert result.source == "project"
    assert result.differs_from_stored is False


@pytest.mark.asyncio
async def test_trailing_zeroes_do_not_invent_a_difference() -> None:
    """ "25.00" and "25" are one rate written twice, and Decimal knows it."""
    result = await _service("25.00").effective_vat(_Stub(_stack("25")), _PROJECT)

    assert result.differs_from_stored is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("steps", "why"),
    [
        ([], "an empty stack has no tax line"),
        ([{"key": "oh", "category": "overhead", "rate": "10"}], "no tax line at all"),
        (
            [
                {"key": "vat", "category": "tax", "rate": "19"},
                {"key": "gst", "category": "tax", "rate": "5"},
            ],
            "two tax lines, so no single figure describes the stack",
        ),
    ],
)
async def test_no_single_tax_line_is_reported_as_no_answer(steps: list[dict[str, object]], why: str) -> None:
    """Absence is reported as absence, never as a zero-rated stack.

    A nought here would be read as "this is zero-rated", which is a different
    and false statement. The project rate is deliberately present in this
    service, so the test also shows that a rate nobody can place does not get
    placed anyway.
    """
    result = await _service("25").effective_vat(_Stub(steps), _PROJECT)

    assert result.rate is None, why
    assert result.source == "none", why
    assert result.stored_rate is None, why
    assert result.differs_from_stored is False, why


@pytest.mark.asyncio
async def test_an_unreadable_stored_rate_is_unknown_rather_than_nought() -> None:
    """A rate that cannot be parsed is not a rate of nought.

    Nought is a rate somebody chose; unreadable is a rate nobody can state.
    Collapsing the second into the first is exactly the defect this whole
    block of work exists to remove, one layer down.
    """
    result = await _service(None).effective_vat(_Stub(_stack("not a number")), _PROJECT)

    assert result.stored_rate is None
    assert result.rate is None
    assert result.source == "methodology"


@pytest.mark.asyncio
async def test_the_resolver_and_the_override_agree_about_where_the_tax_line_is() -> None:
    """One rule, read twice, never restated.

    The override rewrites the step the resolver reports on. If a future edit
    taught one of them a different notion of "exactly one tax line", a project
    would be charged a rate the screen did not name, which is the original
    defect wearing new clothes. Asserted by making both answer about the same
    stacks and requiring their answers to line up.
    """
    for steps in (_stack("0"), _stack("19"), _stack("19", category="overhead"), []):
        index = MethodologyService._single_tax_index(steps)
        swapped = MethodologyService._with_project_vat(steps, "25")
        reported = await _service("25").effective_vat(_Stub(steps), _PROJECT)

        if index is None:
            assert swapped is steps, "no substitution is possible"
            assert reported.source == "none", "and the reader is told exactly that"
        else:
            assert swapped[index]["rate"] == "25", "the override moved the step it found"
            assert reported.rate == Decimal("25"), "and the reader is told the same figure"
            assert reported.source == "project"
