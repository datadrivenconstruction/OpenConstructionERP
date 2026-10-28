# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A measurement sheet has to come out in the shape its market's rules expect.

The measurement presets carry a ``region`` field, exactly like the price
breakdown presets did, and until now nothing resolved a preset from it. Both
endpoints took the preset by name with ``"international"`` as the default, so a
German quantity surveyor computing a take-off got the international sheet
unless they knew to type ``preset=reb`` into a query string, and an Austrian
one never reached OENORM A 2063 at all. Two country conventions shipped
complete and unreachable.

The second half matters as much as the first: the compute endpoint and the
saved-sheet endpoint are a pair. A take-off computed as a REB DA11 sheet and
read back as an international one is worse than either convention applied
consistently, so both endpoints are checked here rather than only the one the
audit named.

Germany and Austria are separate rows on purpose. Switzerland shares the
language with both and has no measurement preset of its own, which is the case
that separates "resolve from the market" from "hand over whatever looks close".
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import textwrap
import uuid
from decimal import Decimal
from typing import Any

import pytest

from app.modules.measurement.presets import PRESETS, get_preset, preset_for_country

#: Markets whose measurement rules the presets claim to implement, and the
#: preset each must resolve to. Written out rather than derived from the table,
#: so a preset silently retagged to another region fails here instead of
#: agreeing with itself.
EXPECTED = {
    "DE": "reb",
    "AT": "oenorm",
}

#: The neutral answer, for a market with no preset and for no market at all.
NEUTRAL = "international"

#: One valid take-off line, enough to build a sheet with.
LINES = [{"description": "wall", "formula": "3.50 * 2.40", "ref": "1"}]


@pytest.mark.parametrize(("country", "preset"), sorted(EXPECTED.items()))
def test_a_market_with_a_convention_gets_it(country: str, preset: str) -> None:
    """Each market with measurement rules of its own resolves to them."""
    resolved = preset_for_country(country)
    assert resolved == preset, (
        f"a measurement sheet for a {country} project is rendered with the {resolved!r} preset "
        f"instead of {preset!r}, so the surveyor gets a sheet laid out under another market's rules."
    )


def test_germany_and_austria_are_not_the_same_answer() -> None:
    """The two DACH conventions are separate rows and must stay separable.

    REB 23.003 and OENORM A 2063 round the same way and are still different
    documents: one is the German measurement rules with its DA11 and DA12
    sheets, the other the Austrian data exchange. A resolver that collapsed
    the region to "German-speaking" would satisfy every other test in this
    file, because both answers would be non-neutral and both would be a real
    preset.
    """
    de = preset_for_country("DE")
    at = preset_for_country("AT")
    assert de != at, f"Germany and Austria both resolve to {de!r}; a shared language is not a shared rule set"
    assert get_preset(de).standard == "REB 23.003"
    assert get_preset(at).standard == "OENORM A 2063"


def test_case_and_whitespace_do_not_change_the_answer() -> None:
    """The country column is not validated on the way in, so the reader normalises."""
    assert preset_for_country("de") == preset_for_country("DE")
    assert preset_for_country("  at  ") == preset_for_country("AT")


@pytest.mark.parametrize("country", [None, "", "   ", "ZZ", "FR", "GB", "US"])
def test_a_market_with_no_preset_gets_the_neutral_one(country: str | None) -> None:
    """No preset for this market and no market at all are the same answer.

    The neutral preset is the one that assumes nothing, so it is the honest
    result for both. What must not happen is a market being handed the nearest
    preset that looks close enough.
    """
    assert preset_for_country(country) == NEUTRAL


def test_switzerland_is_not_handed_its_neighbours_sheet() -> None:
    """Swiss projects share the language with both DACH presets, not the rules.

    REB 23.003 is a German standard and OENORM A 2063 an Austrian one. A Swiss
    take-off is measured under neither, and handing it one because the words on
    it are readable is exactly the substitution the neutral preset exists to
    avoid. Named here with a test rather than left to be inferred from the
    absence of a mapping, because the absence looks identical to an oversight.
    """
    assert preset_for_country("CH") == NEUTRAL, (
        "CH resolves to a DACH measurement preset. A shared language is not a shared rule set."
    )


def test_every_preset_that_claims_a_market_can_be_reached_from_it() -> None:
    """No preset may declare a region that no country resolves to.

    This is the assertion that names the original defect. Two presets declared
    a region, the field had no reader at all, and the only way to reach either
    was to know its slug.
    """
    claimed = {name: p.region for name, p in PRESETS.items() if p.region and p.region.lower() != NEUTRAL}
    print(f"{len(claimed)} of {len(PRESETS)} measurement presets claim a market: {claimed}")
    assert len(claimed) >= 2, (
        f"only {len(claimed)} presets claim a market. This floor is the population the endpoints "
        f"could not reach: REB for Germany and OENORM for Austria. If one was deliberately removed, "
        f"lower it and say which."
    )

    unreachable = {name: region for name, region in claimed.items() if preset_for_country(region) != name}
    assert not unreachable, (
        f"presets that declare a market no country resolves to: {unreachable}. Either the region "
        f"tag is not a country code the resolver understands, or two presets claim one market and "
        f"one of them is being shadowed."
    )


def test_two_presets_do_not_quietly_claim_one_market() -> None:
    """A duplicate region would make one of the pair unreachable, silently.

    The index is built by comprehension, so a second preset declaring an
    existing region overwrites the first and nothing says so.
    """
    regions = [p.region.upper() for p in PRESETS.values() if p.region and p.region.lower() != NEUTRAL]
    duplicates = sorted({r for r in regions if regions.count(r) > 1})
    assert not duplicates, (
        f"more than one preset claims each of {duplicates}. The region index keeps the last one "
        f"declared and the others become unreachable without any error."
    )


# ── The endpoints ───────────────────────────────────────────────────────────
#
# The resolver being right is worthless if the endpoints never call it: the
# whole defect was a correct preset that nothing selected. These drive both
# endpoints with a stub position and a stub project and read the rendered
# sheet, so a fix applied to only one of the pair fails here.


class _Position:
    """The few attributes both endpoints read off a position."""

    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.boq_id = uuid.uuid4()
        self.ordinal = "1.1"
        self.description = "Brickwork"
        self.unit = "m2"
        self.quantity = Decimal("8.400")
        self.metadata_ = {"measurement": {"unit": "m2", "lines": LINES}}


class _Project:
    def __init__(self, country_code: str | None) -> None:
        self.country_code = country_code


class _Repo:
    def __init__(self, position: _Position) -> None:
        self._position = position

    async def get_by_id(self, _position_id: uuid.UUID) -> _Position:
        return self._position


class _Service:
    """Just enough BOQService for the two measurement endpoints.

    ``project_calls`` is the point of the class: an explicitly named preset
    must not send the endpoint to the project at all, and counting the lookups
    proves that, where comparing the output could not tell "the caller's preset
    won" from "the country happened to agree".
    """

    def __init__(self, country_code: str | None, *, has_project: bool = True) -> None:
        self.position_repo = _Repo(_Position())
        self._project = _Project(country_code) if has_project else None
        self.project_calls = 0

    async def project_for_boq(self, _boq_id: uuid.UUID) -> _Project | None:
        self.project_calls += 1
        return self._project


async def _render(endpoint: Any, service: _Service, preset: str | None) -> str:
    """Call one measurement endpoint for a Markdown sheet and return its heading.

    The heading carries the preset's label, which is the observable difference
    between the presets: all three round to three decimals today, so a sheet
    rendered under the wrong rules is otherwise identical to the right one.
    """
    kwargs: dict[str, Any] = {
        "position_id": uuid.uuid4(),
        "user_id": "00000000-0000-0000-0000-000000000001",
        "payload": {"role": "admin"},
        "session": None,
        "fmt": "markdown",
        "preset": preset,
        "service": service,
    }
    if "data" in inspect.signature(endpoint).parameters:
        kwargs["data"] = {"lines": LINES, "unit": "m2"}
    response = await endpoint(**kwargs)
    body = b"".join([chunk async for chunk in response.body_iterator])
    return body.decode("utf-8").splitlines()[0]


@pytest.fixture(params=["compute_position_measurement", "get_position_measurement"])
def endpoint(request: pytest.FixtureRequest) -> Any:
    """Both measurement endpoints, so a fix applied to one of the pair fails.

    Imported inside the fixture rather than at module level: the router pulls
    in the application, and this file's resolver tests must still run if that
    import ever needs more than a unit test has.
    """
    from app.modules.boq import router

    return getattr(router, request.param)


@pytest.mark.parametrize(("country", "standard"), [("DE", "REB 23.003"), ("AT", "OENORM A 2063")])
def test_the_endpoint_asks_the_project_when_no_preset_is_named(endpoint: Any, country: str, standard: str) -> None:
    """A project in a market with rules of its own gets them without being asked."""
    service = _Service(country)
    heading = asyncio.run(_render(endpoint, service, None))
    assert standard in heading, (
        f"a {country} project with no preset named renders {heading!r}, which is not the "
        f"{standard} sheet its own rules call for."
    )
    assert service.project_calls == 1, "the endpoint did not consult the project's country at all"


def test_a_market_with_no_measurement_rules_keeps_the_neutral_sheet(endpoint: Any) -> None:
    """France has no measurement preset, so it must not borrow a neighbour's."""
    service = _Service("FR")
    heading = asyncio.run(_render(endpoint, service, None))
    assert get_preset(NEUTRAL).label in heading, (
        f"a French project renders {heading!r} instead of the neutral sheet. A market with no "
        f"preset of its own gets the one that assumes nothing, never the nearest-looking one."
    )
    for other in ("REB 23.003", "OENORM A 2063"):
        assert other not in heading


@pytest.mark.parametrize("has_project", [True, False], ids=["country column unset", "no project at all"])
def test_a_project_that_names_no_country_keeps_the_neutral_sheet(endpoint: Any, has_project: bool) -> None:
    """Both ways the project can decline to answer end on the neutral sheet.

    These are two different inputs and only one of them is obvious.
    ``project_for_boq`` is fail-soft by design: it returns ``None`` when the
    BOQ has no project or the lookup raises, so the endpoint can be handed no
    project at all, not merely a project whose country column is empty. The
    ``getattr`` default is what covers that, and a default nobody exercises is
    a default nobody has checked.
    """
    service = _Service(None, has_project=has_project)
    heading = asyncio.run(_render(endpoint, service, None))
    assert get_preset(NEUTRAL).label in heading


@pytest.mark.parametrize(("preset", "standard"), [("oenorm", "OENORM A 2063"), ("international", "Measurement sheet")])
def test_a_named_preset_beats_the_projects_country(endpoint: Any, preset: str, standard: str) -> None:
    """The caller names a preset, the caller gets that preset.

    Both cases are named against a German project on purpose. Asking a German
    project for the Austrian sheet proves the country is not silently
    overriding, and asking it for the international one proves the old
    behaviour is still available to a caller who wants it: country resolution
    is what happens when nobody chose, not a policy imposed on somebody who did.
    """
    service = _Service("DE")
    heading = asyncio.run(_render(endpoint, service, preset))
    assert standard in heading, f"the caller asked for {preset!r} and got {heading!r}"
    assert "REB 23.003" not in heading, "the project's country overrode the preset the caller named"
    assert service.project_calls == 0, (
        "the endpoint looked the project up even though the caller named a preset. The lookup is "
        "not free and its answer is not wanted here."
    )


def test_both_endpoints_resolve_through_the_shared_reader(endpoint: Any) -> None:
    """Neither endpoint may grow a second copy of the market table.

    The functional checks above would pass just as well against a dict written
    out inside the endpoint, and a second copy of a market table is how this
    codebase has repeatedly ended up with two answers to one question that
    drift apart. This reads the source: the preset parameter has to accept
    None, and the body has to reach the module's own resolver.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(endpoint)))
    func = tree.body[0]
    assert isinstance(func, ast.AsyncFunctionDef)

    args = {a.arg: a for a in func.args.args + func.args.kwonlyargs}
    preset_arg = args.get("preset")
    assert preset_arg is not None, f"{endpoint.__name__} no longer takes a preset"
    assert preset_arg.annotation is not None
    annotation = ast.unparse(preset_arg.annotation)
    assert "None" in annotation, (
        f"preset is annotated {annotation!r}. It has to accept None, which is how a caller says "
        "'decide from the project'. A string default puts one market's shape back on every sheet."
    )

    called = {ast.unparse(node.func) for node in ast.walk(func) if isinstance(node, ast.Call)}
    assert "preset_for_country" in called, (
        f"{endpoint.__name__} does not call preset_for_country, so its preset is either fixed "
        f"again or resolved from a second copy of the market table."
    )
