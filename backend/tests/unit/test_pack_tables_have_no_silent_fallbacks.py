# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A new demo pack must not fall out of the hand-maintained tables in silence.

Three tables in ``demo_projects`` are keyed by something a pack file carries,
and every one of them answers a miss with a value that looks like an answer:

* ``_COUNTRY_ISO2`` is keyed by the country name in the pack's address, and a
  miss gives ``""``. That empty string becomes the catalogue row's country and
  the ``country_code`` of every contact the pack seeds, and it is also what
  ``_AUTHORITY_BY_COUNTRY`` and ``_NOTICE_CLAUSE_BY_COUNTRY`` are then looked up
  with, so the correspondence register quietly addresses nobody in particular.
* ``_PACK_DEMO_TYPE`` is keyed by ``demo_id`` and defaults to ``"Commercial"``.
  A default that is itself a valid answer cannot be told apart from a real one:
  a residential building in Shenzhen was listed as commercial from the day it
  shipped, and nobody could have noticed by reading the catalogue.
* ``_DEMO_COST_LEVEL`` is keyed by currency and defaults to ``(1.0, 1.0)``,
  which prices the shared euro-denominated seed literals at German levels. A
  pack in yen or won would seed plausible-looking numbers that are wrong by two
  orders of magnitude, and every one of them would still be a number.

None of the three raises, warns or logs. Boot stays green, the pack installs,
and the only way to find out is to go looking. Six packs written on one day all
landed in the first table at once, which is what prompted this file.

The tests below are deliberately about coverage of the tables, not about the
correctness of any single value. Being present is checkable by a machine; being
right is not.
"""

from __future__ import annotations

import pytest

from app.core.demo_packs import PACK_TEMPLATES
from app.core.demo_projects import (
    _COUNTRY_ISO2,
    _DEMO_COST_LEVEL,
    _PACK_DEMO_TYPE,
)


def test_there_are_packs_to_check() -> None:
    """A table gate over an empty population passes and means nothing."""
    assert len(PACK_TEMPLATES) >= 30, f"only {len(PACK_TEMPLATES)} pack templates loaded"


@pytest.mark.parametrize("template", PACK_TEMPLATES, ids=lambda t: t.demo_id)
def test_pack_country_name_resolves_to_an_iso_code(template) -> None:  # noqa: ANN001
    """The address country must be a key of the map, spelled exactly."""
    address = getattr(template, "address", None) or {}
    country = (address.get("country") or "").strip()
    if not country:
        pytest.skip(f"{template.demo_id} carries no structured address country")
    assert country in _COUNTRY_ISO2, (
        f"{template.demo_id} gives country {country!r}, which is not a key of _COUNTRY_ISO2. "
        f"The catalogue row and every seeded contact would carry an empty country_code, and the "
        f"authority and notice-clause lookups would both miss as well. Add the spelling this pack "
        f"uses; no edit inside the pack file can fix it."
    )


@pytest.mark.parametrize("template", PACK_TEMPLATES, ids=lambda t: t.demo_id)
def test_pack_has_an_explicit_archetype(template) -> None:
    """Never let the ``Commercial`` default stand in for a missing entry."""
    assert template.demo_id in _PACK_DEMO_TYPE, (
        f"{template.demo_id} is not in _PACK_DEMO_TYPE, so the catalogue labels it 'Commercial' "
        f"by default. That default is a valid archetype in its own right, so a wrong label here "
        f"is indistinguishable from a deliberate one."
    )


@pytest.mark.parametrize("template", PACK_TEMPLATES, ids=lambda t: t.demo_id)
def test_pack_currency_has_a_demo_cost_level(template) -> None:
    """Seeded module data must be levelled into the pack's own currency."""
    currency = (template.currency or "").strip().upper()[:3]
    assert currency in _DEMO_COST_LEVEL, (
        f"{template.demo_id} declares {currency!r}, which has no _DEMO_COST_LEVEL row, so its "
        f"shared euro-denominated seed literals stay at 1.0 and the pack seeds German prices "
        f"under a {currency} label."
    )
