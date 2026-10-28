# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The starter rate library must survive the layers that read it silently.

Three readers take the seed data without complaining about it, so a bad row
here shows up as a wrong number on screen rather than as a failure:

* ``rate_math._normalize_kind`` treats every kind that is not exactly
  ``percentage`` as a flat amount, so a component written ``percent`` or
  ``pct`` becomes a currency amount per hour and the rate is quietly wrong;
* the ORM columns are bounded (``name`` and ``label`` at 255, ``currency`` at
  3), and an over-long literal is a database error at first boot inside a
  fail-soft seeder, which logs a warning nobody reads;
* the seeder's idempotency key is the template name, so two rows sharing a
  name would leave the second one permanently unseeded.

None of this needs a database: both the seed data and the build-up arithmetic
are module-level and pure.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.labor_rates import rate_math
from app.modules.labor_rates.schemas import OnCostIn, TemplateCreate
from app.modules.labor_rates.seed import DEFAULT_RATE_TEMPLATES

_KINDS = {rate_math.PERCENTAGE, rate_math.FIXED}


@pytest.mark.parametrize("row", DEFAULT_RATE_TEMPLATES, ids=lambda r: r["name"])
def test_every_seeded_component_kind_is_one_the_build_up_knows(row):
    """An unrecognised kind is read as a fixed amount, not rejected."""
    for label, kind, _value in row["components"]:
        assert kind in _KINDS, f"{row['name']}: component {label!r} carries kind {kind!r}"


@pytest.mark.parametrize("row", DEFAULT_RATE_TEMPLATES, ids=lambda r: r["name"])
def test_every_seeded_row_fits_its_columns(row):
    """An over-long literal fails at first boot inside a fail-soft seeder."""
    assert 0 < len(row["name"]) <= 255
    assert len(row["currency"]) == 3, f"{row['name']}: currency {row['currency']!r} is not a 3-letter code"
    assert row["currency"].isupper()
    assert len(row["description"]) <= 2000
    for label, _kind, _value in row["components"]:
        assert 0 < len(label) <= 255, f"{row['name']}: component label {label!r} does not fit"


@pytest.mark.parametrize("row", DEFAULT_RATE_TEMPLATES, ids=lambda r: r["name"])
def test_every_seeded_row_would_pass_the_create_endpoint(row):
    """The API refuses a base wage of zero; a seeder must not write one either.

    A template that builds up to nothing is not ``None``, so every consumer
    reads it as a priced rate and charges nothing for the labour hours while
    flagging nothing. Validating the seed row through the real request schema
    keeps the seeder and the endpoint answering the same question.
    """
    TemplateCreate(
        name=row["name"],
        base_wage=row["base_wage"],
        currency=row["currency"],
        description=row["description"],
        components=[OnCostIn(label=label, kind=kind, value=value) for label, kind, value in row["components"]],
    )


@pytest.mark.parametrize("row", DEFAULT_RATE_TEMPLATES, ids=lambda r: r["name"])
def test_every_seeded_row_burdens_its_wage(row):
    """A build-up that does not exceed the bare wage is on-costs that do nothing."""
    components = [rate_math.OnCost(label=label, kind=kind, value=value) for label, kind, value in row["components"]]
    all_in = rate_math.all_in_rate(row["base_wage"], components)
    assert all_in > Decimal(str(row["base_wage"])), f"{row['name']}: all-in rate {all_in} does not burden the wage"


def test_template_names_are_unique():
    """The seeder skips on name, so a duplicate is a row that never lands."""
    names = [row["name"] for row in DEFAULT_RATE_TEMPLATES]
    assert len(names) == len(set(names)), f"duplicate template names: {names}"


def test_the_library_spans_several_currencies():
    """One currency is a library that suits one project in the demo portfolio.

    The picker exists to be chosen from, and the demo projects are priced in
    euro, sterling, dollars and dirham, so a single-currency library would send
    every other project to the manual build-up.
    """
    currencies = {row["currency"] for row in DEFAULT_RATE_TEMPLATES}
    assert len(currencies) >= 3, f"the starter library only covers {sorted(currencies)}"
