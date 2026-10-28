# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Assemblies must never report one number that holds two currencies.

The apply-template preview converts each matched component into the target
currency and rolls the results into ``grand_total``. When no rate could be found
it used to return the component's UNCONVERTED amount and add that to the very
same total, so a component priced in one currency contributed its face value to
a sum labelled with another. A warning was attached, and the number stayed
wrong: 100 EUR plus 1000 of an unpriceable currency was reported as 1100 EUR.

These tests pin the invariant that replaced it. Every amount is banked under one
ISO code, and the single-scalar fields (``grand_total`` / ``total_rate``) are
withheld entirely when more than one currency is in play - refusing to name a
total being the only honest answer when part of it could not be priced.

They also pin the DIRECTION of every conversion. ``Project.fx_rates`` is quoted
as "base units per 1 unit of the foreign currency" and ``oe_fx``'s ``cross_rate``
as "target units per one source unit"; both are applied by multiplication, so an
inverted rate yields a plausible number and raises nothing. Each conversion
assertion therefore checks an exact expected value against an asymmetric rate,
which a round-trip assertion would not catch.

No database is involved: the repositories and the catalogue matcher are stubbed,
and passing ``session=None`` makes the FX register resolve against the bundled
seed.

Run:
    cd backend
    python -m pytest tests/unit/test_assemblies_currency_blending.py -v --tb=short
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.assemblies import router as assemblies_router
from app.modules.assemblies.fx_bridge import FxContext, _register_provenance
from app.modules.assemblies.schemas import ApplyTemplateRequest, ComponentCreate, ComponentResponse

# Bundled-seed rates the register answers with when no rate set is stored
# (``app/modules/fx/fx_seed.json``, EUR base, units per 1 EUR).
SEED_GBP_PER_EUR = Decimal("0.845")

# In neither the bundled seed nor any project table below, so nothing can price
# it. The point of the fixture is that such a currency exists.
UNPRICEABLE = "XOF"


def _component(query: str, description: str) -> dict:
    """One template component row, as the template model stores it."""
    return {
        "cost_match_query": query,
        "factor": 1.0,
        "unit": "m3",
        "role": "material",
        "description": description,
    }


def _match(unit_rate: float, currency: str) -> SimpleNamespace:
    """A catalogue match, in the flat shape ``MatchResult`` exposes."""
    return SimpleNamespace(
        unit_rate=unit_rate,
        score=0.9,
        source="lexical",
        description="matched item",
        code="C-1",
        cost_item_id=str(uuid4()),
        currency=currency,
    )


def _project(currency: str = "EUR", fx_rates: list | None = None) -> SimpleNamespace:
    """A project stand-in carrying only what the preview reads off it."""
    return SimpleNamespace(
        id=uuid4(),
        owner_id=uuid4(),
        currency=currency,
        fx_rates=fx_rates or [],
        region=None,
    )


def _assert_no_blended_scalar(response) -> None:
    """The invariant: no single number in the response covers two currencies.

    ``totals_by_currency`` is the only place a figure may appear, and each of
    its buckets is one currency. The convenience scalars are allowed to exist
    only when there is nothing they could be blending.
    """
    codes = {sub.currency for sub in response.totals_by_currency}
    if len(codes) > 1:
        assert response.grand_total is None, f"grand_total {response.grand_total!r} spans {sorted(codes)}"
        assert response.total_rate is None, f"total_rate {response.total_rate!r} spans {sorted(codes)}"
    else:
        assert response.grand_total is not None
    for comp in response.components:
        if comp.total == 0.0:
            # Contributed nothing to any bucket, so there is no currency it
            # could be blending. This is the unmatched component.
            continue
        # A component either sits in a bucket of its own currency, or it was
        # converted into the target and its native code need not be a bucket.
        assert comp.converted_to_target or comp.currency in codes


@pytest.fixture
def apply_preview(monkeypatch):
    """Run ``apply_template`` against stubbed repositories and catalogue."""

    async def _run(
        *,
        components: list[dict],
        project: SimpleNamespace,
        matches: dict[str, SimpleNamespace],
        quantity: float = 1.0,
    ):
        from app.modules.assemblies import repository as assemblies_repository
        from app.modules.costs import matcher as costs_matcher
        from app.modules.projects import repository as projects_repository

        template = SimpleNamespace(id=uuid4(), name="Template", unit="m3", components=components)

        class _TemplateRepo:
            def __init__(self, _session) -> None:
                pass

            async def get_by_id(self, _template_id):
                return template

        class _ProjectRepo:
            def __init__(self, _session) -> None:
                pass

            async def get_by_id(self, _project_id):
                return project

        async def _match_items(_session, query, **_kwargs):
            found = matches.get(query)
            return [found] if found is not None else []

        monkeypatch.setattr(assemblies_repository, "AssemblyTemplateRepository", _TemplateRepo)
        monkeypatch.setattr(projects_repository, "ProjectRepository", _ProjectRepo)
        monkeypatch.setattr(costs_matcher, "match_cwicr_items", _match_items)

        return await assemblies_router.apply_template(
            template_id=template.id,
            data=ApplyTemplateRequest(project_id=project.id, quantity=quantity),
            user_id=str(project.owner_id),
            payload={"role": "admin"},
            session=None,
        )

    return _run


async def test_unconvertible_component_is_not_summed_into_the_target_total(apply_preview):
    """The reported defect: an unpriceable component must stay out of the total."""
    response = await apply_preview(
        components=[_component("concrete", "Concrete"), _component("levy", "Import levy")],
        project=_project(currency="EUR", fx_rates=[]),
        matches={"concrete": _match(100.0, "EUR"), "levy": _match(1000.0, UNPRICEABLE)},
    )

    # Before the fix this returned grand_total == 1100: 100 EUR plus the face
    # value of 1000 XOF, added together and stamped "EUR".
    assert response.grand_total is None
    assert response.total_rate is None
    _assert_no_blended_scalar(response)

    buckets = {sub.currency: sub for sub in response.totals_by_currency}
    assert set(buckets) == {"EUR", UNPRICEABLE}
    assert buckets["EUR"].amount == Decimal("100")
    assert buckets[UNPRICEABLE].amount == Decimal("1000")
    assert buckets["EUR"].is_target is True
    assert buckets[UNPRICEABLE].is_target is False
    # The response still names its target, and says why the rest is apart.
    assert response.currency == "EUR"
    assert any(UNPRICEABLE in warning for warning in response.warnings)


async def test_register_prices_a_component_the_project_has_no_rate_for(apply_preview):
    """``oe_fx`` converts where the project's own table is empty, right way up."""
    response = await apply_preview(
        components=[_component("steel", "Steel")],
        project=_project(currency="EUR", fx_rates=[]),
        matches={"steel": _match(845.0, "GBP")},
    )

    # The seed says 0.845 GBP per 1 EUR, so 845 GBP is exactly 1000 EUR.
    # Inverting the rate would give 713.9 and raise nothing, which is why this
    # asserts the value rather than a round trip. Before the fix the project
    # had no rate for GBP, so 845 was returned unconverted and labelled EUR.
    assert response.currency == "EUR"
    assert response.grand_total == Decimal("1000.0000")
    assert [sub.currency for sub in response.totals_by_currency] == ["EUR"]
    _assert_no_blended_scalar(response)

    # The component row keeps its NATIVE figure and says which money it is in.
    assert response.components[0].total == 845.0
    assert response.components[0].currency == "GBP"
    assert response.components[0].converted_to_target is True


async def test_project_rate_outranks_the_register(apply_preview):
    """A rate typed against the project beats the market feed (a guard, not a fix)."""
    response = await apply_preview(
        components=[_component("steel", "Steel")],
        project=_project(currency="EUR", fx_rates=[{"code": "GBP", "rate": "1.1737"}]),
        matches={"steel": _match(100.0, "GBP")},
    )

    # 100 GBP at the project's own 1.1737 EUR per GBP is 117.37. The seed would
    # have said 118.3432, so the value also proves which source won.
    assert response.grand_total == Decimal("117.3700")
    assert response.currency == "EUR"


async def test_no_project_currency_does_not_elect_one_by_match_order(apply_preview):
    """With no project currency, the answer must not depend on match order."""
    usd = _component("usd-line", "Priced in USD")
    jpy = _component("jpy-line", "Priced in JPY")
    matches = {"usd-line": _match(100.0, "USD"), "jpy-line": _match(1000.0, "JPY")}

    forward = await apply_preview(components=[usd, jpy], project=_project(currency=""), matches=matches)
    reverse = await apply_preview(components=[jpy, usd], project=_project(currency=""), matches=matches)

    # Before the fix the target was locked to whichever component matched
    # first, so these two orders reported different currencies for the same
    # recipe - and both blended the other component into the total.
    assert forward.currency == ""
    assert reverse.currency == ""
    assert forward.grand_total is None
    assert reverse.grand_total is None
    _assert_no_blended_scalar(forward)
    _assert_no_blended_scalar(reverse)

    def _buckets(response) -> set:
        return {(sub.currency, sub.amount) for sub in response.totals_by_currency}

    assert _buckets(forward) == _buckets(reverse)
    assert _buckets(forward) == {("USD", Decimal("100")), ("JPY", Decimal("1000"))}


async def test_an_unmatched_component_does_not_invent_a_currency_bucket(apply_preview):
    """A component that matched nothing must not withhold a total that is well defined.

    An unmatched component has no price and no currency. Banked anyway, its zero
    opens a bucket keyed on the empty string, and on a project with no currency
    of its own that phantom bucket is enough to make a one-currency preview look
    like two and drop the total. The asymmetry that hides this: with a project
    currency set the zero lands in the target and nothing goes wrong.
    """
    response = await apply_preview(
        components=[_component("usd-line", "Priced in USD"), _component("missing", "No catalogue match")],
        project=_project(currency=""),
        matches={"usd-line": _match(100.0, "USD")},
    )

    assert response.unresolved_components == ["missing"]
    assert [sub.currency for sub in response.totals_by_currency] == ["USD"]
    assert response.totals_by_currency[0].component_count == 1
    assert response.currency == "USD"
    assert response.grand_total == Decimal("100.0000")
    _assert_no_blended_scalar(response)


async def test_single_currency_preview_still_reports_one_total(apply_preview):
    """The ordinary case is untouched: one currency, one total (a guard)."""
    response = await apply_preview(
        components=[_component("concrete", "Concrete"), _component("rebar", "Rebar")],
        project=_project(currency="EUR", fx_rates=[]),
        matches={"concrete": _match(100.0, "EUR"), "rebar": _match(25.0, "EUR")},
        quantity=4.0,
    )

    assert response.currency == "EUR"
    assert response.grand_total == Decimal("500.0000")
    assert response.total_rate == 125.0
    assert [sub.currency for sub in response.totals_by_currency] == ["EUR"]
    assert response.totals_by_currency[0].component_count == 2
    _assert_no_blended_scalar(response)


def test_fx_context_refuses_a_pair_it_cannot_price():
    """No rate is reported as no rate, never as an unconverted amount."""
    context = FxContext(
        project_base="EUR",
        project_rates={},
        register_rates={"USD": Decimal("1.08")},
        register_base="EUR",
    )
    rate, provenance = context.rate(UNPRICEABLE, "EUR")

    assert rate is None
    assert provenance["fx_source"] == ""
    assert provenance["reason"] == "no_rate"


def test_fx_context_prefers_the_projects_own_rate():
    """A contractually fixed project rate outranks the market feed."""
    context = FxContext(
        project_base="EUR",
        project_rates={"GBP": "1.1737"},
        register_rates={"GBP": SEED_GBP_PER_EUR},
        register_base="EUR",
    )
    rate, provenance = context.rate("GBP", "EUR")

    assert rate == Decimal("1.1737")
    assert provenance["fx_source"] == "project_fx_rates"


def test_fx_context_register_rate_points_the_right_way():
    """Foreign into base divides by the units-per-base quote, never multiplies."""
    context = FxContext(register_rates={"GBP": SEED_GBP_PER_EUR}, register_base="EUR")
    rate, provenance = context.rate("GBP", "EUR")

    assert provenance["fx_source"] == "oe_fx"
    assert rate == Decimal("1") / SEED_GBP_PER_EUR
    # The inverted reading, which would raise nothing and look plausible.
    assert rate != SEED_GBP_PER_EUR


def test_register_provenance_does_not_shadow_the_mechanism_marker():
    """The feed's own name must not land on top of ``fx_source``.

    ``ResolvedRates.provenance()`` carries a ``source`` key naming the FEED the
    register answered from. Prefixing every key with ``fx_`` turns it into a
    second ``fx_source`` that overwrites the marker saying which mechanism
    priced the pair, so a project-rate conversion and a seed conversion become
    indistinguishable to anything reading it.
    """
    resolved = SimpleNamespace(
        provenance=lambda: {"source": "seed", "as_of": date(2026, 6, 30), "origin": "bundled_seed"},
        coverage_note=lambda: "",
    )
    out = _register_provenance(resolved)

    assert out["fx_feed"] == "seed"
    assert "fx_source" not in out
    assert out["fx_as_of"] == "2026-06-30"


def test_register_provenance_survives_the_merge_into_a_rate_answer():
    """End to end: provenance travels with the rate without hiding the source."""
    context = FxContext(
        register_rates={"GBP": SEED_GBP_PER_EUR},
        register_base="EUR",
        register_provenance={"fx_feed": "seed", "fx_as_of": "2026-06-30"},
    )
    _rate, provenance = context.rate("GBP", "EUR")

    assert provenance["fx_source"] == "oe_fx"
    assert provenance["fx_feed"] == "seed"
    assert provenance["fx_as_of"] == "2026-06-30"


def test_project_rate_is_not_applied_in_the_wrong_direction():
    """``fx_rates`` converts INTO the project's base and never out of it."""
    context = FxContext(
        project_base="EUR",
        project_rates={"GBP": "1.1737"},
        register_rates={"GBP": SEED_GBP_PER_EUR},
        register_base="EUR",
    )
    rate, provenance = context.rate("EUR", "GBP")

    # Base to foreign is the register's job: the project quote is "EUR per GBP"
    # and reusing it here would invert it silently.
    assert provenance["fx_source"] == "oe_fx"
    assert rate == SEED_GBP_PER_EUR


# ── The add-component rescue ────────────────────────────────────────────────
#
# ``add_component`` builds its response directly, and falls back to
# reconstructing one from the request payload when that raises - the comment on
# the branch says it exists to survive MissingGreenlet on expired ORM
# attributes. The fallback computed ``data.factor * data.quantity *
# data.unit_cost``, and the schema types those as float, float and Decimal.
# ``float * Decimal`` is a TypeError, so the rescue raised every time it ran:
# the caller still got a 500, now with a traceback pointing at arithmetic
# instead of at the greenlet problem, sending whoever debugged it to the wrong
# file. These tests drive the endpoint into that branch rather than exercising
# the expression, so they fail if the rescue stops rescuing for any reason.


class _RescueService:
    """Stands in for ``AssemblyService``; returns a bare row with an id only."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def add_component(self, assembly_id, data):
        self.calls.append((assembly_id, data))
        # Deliberately not a Component: reading anything but ``id`` off it is
        # the mistake the fallback exists to avoid.
        return SimpleNamespace(id=uuid4())


@pytest.fixture
def rescue_add_component(monkeypatch):
    """Call the endpoint with ``_component_to_response`` forced to fail."""

    async def _noop_verify(*args, **kwargs):
        return None

    def _boom(comp):
        raise RuntimeError("simulated MissingGreenlet on an expired attribute")

    monkeypatch.setattr(assemblies_router, "_verify_assembly_owner", _noop_verify)
    monkeypatch.setattr(assemblies_router, "_component_to_response", _boom)

    async def _run(payload: dict):
        service = _RescueService()
        return await assemblies_router.add_component(
            assembly_id=uuid4(),
            data=ComponentCreate(**payload),
            user_id=str(uuid4()),
            payload={"role": "admin"},
            session=None,
            service=service,
        )

    return _run


async def test_add_component_rescue_returns_a_decimal_total_instead_of_raising(rescue_add_component):
    """The rescue must produce a response, and produce it in Decimal.

    2.675 is the discriminating value: as a float it is really 2.67499999...,
    so a float product rounds to 2.67, while the exact decimal rounds half to
    even and gives 2.68. Asserting the exact total therefore fails both ways
    this line can be wrong - the TypeError it raised before, and the precision
    loss that wrapping the money in ``float()`` would introduce instead.
    """
    response = await rescue_add_component(
        {"description": "Rescued line", "unit": "m3", "factor": 1.0, "quantity": 1.0, "unit_cost": "2.675"}
    )

    assert response.total == Decimal("2.68")
    assert isinstance(response.total, Decimal)
    assert response.unit_cost == Decimal("2.675")


async def test_add_component_rescue_resolves_the_unit_rate_alias(rescue_add_component):
    """``unit_rate`` prices a line just as ``unit_cost`` does, and did not here.

    The service stores ``get_unit_cost()``, which falls back to ``unit_rate``.
    The rescue read ``data.unit_cost`` raw, so a payload that priced its line
    through the alias got 0 back while the database held the real figure - a
    zero that looks like a legitimately free line rather than a failure.
    """
    response = await rescue_add_component(
        {"description": "Priced through the alias", "unit": "m3", "factor": 2.0, "quantity": 3.0, "unit_rate": "10.50"}
    )

    assert response.unit_cost == Decimal("10.50")
    assert response.total == Decimal("63.00")


async def test_add_component_rescue_only_runs_when_the_direct_build_fails(monkeypatch):
    """A guard: the happy path must not be routed through the fallback.

    Without this, deleting the ``try`` and always taking the fallback would
    leave both tests above green while every response silently became an
    approximation of the stored row.

    The assertion is on a SENTINEL total the fallback cannot produce, not on a
    call being recorded. Recording the call proves only that the direct builder
    was entered - a first draft of this test appended a marker and then raised,
    the ``except`` swallowed the raise, the fallback answered, and the marker
    assertion passed on a response the direct builder never produced.
    """
    sentinel = Decimal("777.77")
    now = datetime.now(UTC)

    async def _noop_verify(*args, **kwargs):
        return None

    def _direct(comp):
        return ComponentResponse(
            id=comp.id,
            assembly_id=uuid4(),
            cost_item_id=None,
            description="built directly",
            factor=1.0,
            quantity=1.0,
            unit="m3",
            unit_cost=Decimal("1"),
            total=sentinel,
            sort_order=0,
            created_at=now,
            updated_at=now,
        )

    monkeypatch.setattr(assemblies_router, "_verify_assembly_owner", _noop_verify)
    monkeypatch.setattr(assemblies_router, "_component_to_response", _direct)

    response = await assemblies_router.add_component(
        assembly_id=uuid4(),
        data=ComponentCreate(description="Ordinary", unit="m3", factor=1.0, quantity=1.0, unit_cost=Decimal("5")),
        user_id=str(uuid4()),
        payload={"role": "admin"},
        session=None,
        service=_RescueService(),
    )

    # The fallback would have said 5.00 from the payload.
    assert response.total == sentinel
    assert response.description == "built directly"
