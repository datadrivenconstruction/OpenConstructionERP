# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The contract standard a demo pack declares must reach the notice engine.

Driven from the shipped packs rather than from a constructed contract, because
a hand-built fixture is exactly what let the defect sit. ``normalize_standard``
mapped a FIDIC string to FIDIC in isolation and always had; what nothing
checked was the seam - whether any demo project put a standard anywhere the
resolver actually looks. None did, so every demo project fell through to the
standard-neutral periods, including the one whose pack names FIDIC, which the
engine supports and holds correct periods for.

Each test states the population it swept and asserts a floor on it. A suite of
this shape passes vacuously the day the packs stop declaring a form, and a
green run over an empty set is the failure mode it exists to prevent.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.core.demo_packs import PACK_TEMPLATES
from app.core.demo_projects import DemoTemplate, _generate_module_data
from app.modules.change_intelligence.time_bar import (
    GENERIC_PERIODS,
    NOTICE_PERIODS,
    STANDARD_UNKNOWN,
    normalize_standard,
    period_for,
)
from app.modules.change_intelligence.time_bar_service import (
    _TERMS_STANDARD_KEYS,
    _standard_from_terms,
)

_BASE = datetime(2026, 4, 1)


def _head_contract(template: DemoTemplate) -> dict | None:
    """The generated head contract for one pack, or ``None`` if it makes none."""
    generated = _generate_module_data(template, uuid.uuid4(), uuid.uuid4(), template.demo_id, _BASE)
    contracts = generated.get("contracts") or []
    return contracts[0] if contracts else None


def _declared_form(template: DemoTemplate) -> str:
    """The form of contract a pack declares in its own words, or ``""``."""
    return str(template.project_metadata.get("general_contractor_form") or "").strip()


def test_the_packs_still_declare_a_standard_with_periods() -> None:
    """Every declared form must resolve to a family with real periods.

    All shipped packs that name a contract form now resolve to a family with
    sourced notice periods (FIDIC, CCDC, etc.). The engine has three answers
    for a declared form: a family with its own periods, a family it recognises
    and holds no periods for, and a form it does not recognise at all. This
    test asserts the first branch is populated so the seam tests below are not
    sweeping an empty set.
    """
    declared = {t.demo_id: _declared_form(t) for t in PACK_TEMPLATES if _declared_form(t)}
    assert declared, "no pack declares a form of contract; the rest of this file proves nothing"

    resolved = {demo_id: normalize_standard(form) for demo_id, form in declared.items()}
    with_periods = {d for d, s in resolved.items() if s in NOTICE_PERIODS}

    assert with_periods, f"no pack declares a standard the engine holds periods for: {resolved}"


def test_a_declared_standard_is_stored_where_the_resolver_looks() -> None:
    """The key must be one the resolver reads, not merely a key.

    This is the half that was missing. Storing the form under a name the
    resolver never inspects satisfies every other assertion here and changes
    nothing on screen - which is exactly what ``general_contractor_form`` in
    project metadata did for as long as it existed.
    """
    swept = 0
    for template in PACK_TEMPLATES:
        if not _declared_form(template):
            continue
        head = _head_contract(template)
        assert head is not None, f"{template.demo_id} generates no head contract"
        terms = head.get("terms") or {}
        assert terms, f"{template.demo_id} declares a form but its head contract carries no terms"
        assert set(terms) & set(_TERMS_STANDARD_KEYS), (
            f"{template.demo_id} stores its standard under {sorted(terms)}, "
            f"none of which the resolver reads ({sorted(_TERMS_STANDARD_KEYS)})"
        )
        swept += 1
    assert swept >= 3, f"expected at least three packs declaring a form, swept {swept}"


def test_a_pack_naming_a_supported_standard_gets_that_standards_periods() -> None:
    """The seam end to end: pack text, terms, resolver, periods.

    Supported means the family has a row in ``NOTICE_PERIODS``, not merely that
    the normaliser recognised it: a held family is recognised and has no periods
    to compare against, and is swept by the control below instead.
    """
    swept = 0
    for template in PACK_TEMPLATES:
        form = _declared_form(template)
        expected = normalize_standard(form)
        if expected not in NOTICE_PERIODS:
            continue
        head = _head_contract(template)
        assert head is not None, f"{template.demo_id} generates no head contract"
        resolved = _standard_from_terms(head.get("terms") or {})
        assert resolved == expected, (
            f"{template.demo_id} declares {form!r} ({expected}) but its contract resolves to {resolved}"
        )
        for notice_type, days in NOTICE_PERIODS[expected].items():
            assert period_for(resolved, notice_type) == days
        swept += 1
    assert swept >= 1, "no pack declares a supported standard; this test swept nothing"


def test_the_supported_standard_differs_from_the_generic_fallback_where_it_should() -> None:
    """Otherwise a project resolving to UNKNOWN would satisfy the test above.

    Before the fix every demo project resolved to UNKNOWN and was given
    ``GENERIC_PERIODS``. FIDIC and the generic table agree on claim and EOT at
    28 days, so an assertion that happened to pick either would have passed
    against the defect. This names the periods where the two genuinely
    disagree and pins those.
    """
    swept = 0
    for template in PACK_TEMPLATES:
        expected = normalize_standard(_declared_form(template))
        if expected not in NOTICE_PERIODS:
            continue
        differing = {
            notice_type: (days, GENERIC_PERIODS[notice_type])
            for notice_type, days in NOTICE_PERIODS[expected].items()
            if notice_type in GENERIC_PERIODS and GENERIC_PERIODS[notice_type] != days
        }
        assert differing, f"{expected} agrees with the generic table everywhere; this proves nothing"

        head = _head_contract(template)
        resolved = _standard_from_terms((head or {}).get("terms") or {})
        for notice_type, (own, generic) in differing.items():
            assert period_for(resolved, notice_type) == own
            assert period_for(resolved, notice_type) != generic
        swept += 1
    assert swept >= 1, "no pack declares a supported standard; this test swept nothing"


def test_a_pack_naming_ccdc_gets_ccdc_periods_not_the_generic_fallback() -> None:
    """The Canadian packs declare CCDC, which now has its own sourced periods.

    CCDC claim and EOT are 10 working days (GC 6.5/6.6), materially different
    from the generic 28 calendar-day fallback. This pins that a Canadian pack
    resolves to CCDC and gets the contract's own windows, not the neutral ones.
    """
    swept = 0
    for template in PACK_TEMPLATES:
        form = _declared_form(template)
        expected = normalize_standard(form)
        if not form or expected != "CCDC":
            continue
        head = _head_contract(template)
        assert head is not None, f"{template.demo_id} generates no head contract"
        resolved = _standard_from_terms(head.get("terms") or {})
        assert resolved == expected, f"{template.demo_id} declares {form!r}, expected {expected}"
        assert resolved != STANDARD_UNKNOWN, f"{template.demo_id} declares {form!r} and lost the name of it"
        for notice_type in GENERIC_PERIODS:
            actual = period_for(resolved, notice_type)
            assert actual is not None, f"{notice_type} period is None for {resolved}"
            assert actual != GENERIC_PERIODS[notice_type], (
                f"{notice_type}: CCDC period equals the generic fallback ({actual})"
            )
        swept += 1
    assert swept >= 1, "no pack declares CCDC; the control swept nothing"


def test_a_pack_declaring_no_form_carries_no_contract_standard() -> None:
    """Most packs name no form, and inventing one for them would be worse."""
    swept = 0
    for template in PACK_TEMPLATES:
        if _declared_form(template):
            continue
        head = _head_contract(template)
        if head is None:
            continue
        assert not (head.get("terms") or {}).get("contract_standard"), (
            f"{template.demo_id} declares no form but its contract carries a standard"
        )
        swept += 1
    assert swept >= 10, f"expected most packs to declare no form, swept {swept}"
