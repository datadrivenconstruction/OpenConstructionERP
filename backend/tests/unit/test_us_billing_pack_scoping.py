"""The G702/G703 form and state lien-waiver law come from the US pack, never from core.

Scoping both ways: a US (and, as before, CA/AU) project sees the form, every
other market gets nothing and the old URL answers 404; US state waiver law
applies to US projects only.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.modules.contracts import pay_application_forms as forms
from app.modules.contracts import router as contracts_router

CONTRACTS_DIR = Path(contracts_router.__file__).resolve().parent


def test_the_form_is_supplied_by_the_us_pack() -> None:
    form = forms.get_form("aia-application")
    assert form is not None
    assert form.module == "oe_us_pack"
    assert form.render_pdf.__module__ == "app.modules.us_pack.billing_forms"


@pytest.mark.parametrize(
    ("country", "address"),
    [("US", None), ("CA", None), ("AU", None), ("", {"country": "United States"})],
)
def test_us_and_adopting_markets_see_the_form(country: str, address: dict | None) -> None:
    assert [f.slug for f in forms.eligible_forms(country, address)] == ["aia-application"]


@pytest.mark.parametrize(
    ("country", "address"),
    [("DE", None), ("GB", None), ("TR", None), ("SA", None), ("", {"country": "Germany"}), (None, None)],
)
def test_other_markets_see_no_form(country: str | None, address: dict | None) -> None:
    assert forms.eligible_forms(country, address) == []


def test_us_state_waiver_law_applies_to_us_projects_only() -> None:
    rules = forms.lien_waiver_rules_for("US")
    assert rules is not None and rules.module == "oe_us_pack"
    assert rules.statutory_form("CA", "unconditional_partial")["citation"] == "Cal. Civ. Code § 8134"
    assert rules.statutory_form("Texas", "conditional_final")["state"] == "US-TX"
    assert rules.statutory_form("NY", "conditional_final") is None
    assert any(t["jurisdiction"] == "US-CA" for t in rules.templates)
    for other in ("DE", "GB", "CA", "AU"):
        assert forms.lien_waiver_rules_for(other) is None


def test_core_contracts_source_names_no_us_form() -> None:
    for name in ("router.py", "service.py", "pay_application_forms.py", "pay_application.py"):
        source = (CONTRACTS_DIR / name).read_text(encoding="utf-8")
        assert "aia-application" not in source, name
        assert "aia_pdf" not in source, name
        assert "is_aia_eligible" not in source, name
    assert not (CONTRACTS_DIR / "aia.py").exists()
    assert not (CONTRACTS_DIR / "aia_pdf.py").exists()


def test_form_routes_are_declared_after_every_specific_claim_route() -> None:
    paths = [getattr(r, "path", "") for r in contracts_router.router.routes]
    catch_all = paths.index("/progress-claims/{claim_id}/{form_slug}")
    specific = [
        i
        for i, p in enumerate(paths)
        if p.startswith("/progress-claims/{claim_id}/") and "{form_slug}" not in p and p.count("/") == 3
    ]
    assert specific and max(specific) < catch_all


@pytest.mark.asyncio
async def test_an_unregistered_form_is_404_before_any_lookup() -> None:
    with pytest.raises(HTTPException) as exc:
        await contracts_router.get_form_application(uuid.uuid4(), "g702-anywhere", None, "user")  # type: ignore[arg-type]
    assert exc.value.status_code == 404
