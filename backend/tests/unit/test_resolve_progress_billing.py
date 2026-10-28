# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠``resolve_progress_billing`` answers for the right country or not at all.

The resolver hands a contract its retention tiers, release conditions and
payment evidence. The failure it exists to prevent is the one the tax table
once had: a pack that claims several countries answering for all of them with
one country's figures. So the tests pin both directions of every rule: the
right country gets the figures, and every neighbour, every bare market marker
and every pair of disagreeing packs gets ``None``.

Some tests swap ``pack_configs`` for a fixed set so a rule can be shown red and
green on data that differs in exactly one place; the rest read the shipped
packs.
"""

from __future__ import annotations

from typing import Any

import pytest

import app.core.regional_packs as regional_packs
from app.core.regional_packs import PROGRESS_BILLING_KEYS, resolve_progress_billing
from app.modules.dach_pack.config import PACK_CONFIG as DACH_CFG
from app.modules.us_ca_pack.config import STATE_RULES as CA_RULES
from app.modules.us_pack.config import PACK_CONFIG as US_CFG

_ANSWER_KEYS = {"country_code", *PROGRESS_BILLING_KEYS, "subdivision"}


def _country(result: dict[str, Any] | None) -> str | None:
    return None if result is None else result["country_code"]


# ── The shipped packs ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"country_code": "US"}, "US"),
        ({"country_code": " us "}, "US"),
        ({"country_code": "DE"}, "DE"),
        ({"country_code": "de"}, "DE"),
        ({"country_code": "AT"}, None),
        ({"country_code": "CH"}, None),
        ({"region": "US"}, "US"),
        ({"region": "DACH"}, None),
        ({"region": "dach"}, None),
        ({"region": "US_CA"}, None),
        ({"country_code": "DE", "region": "US"}, "DE"),
        ({"country_code": "AT", "region": "DACH"}, None),
        ({"country_code": "FR", "region": "US"}, None),
        ({"country_code": "XX"}, None),
        ({"country_code": ""}, None),
        ({}, None),
    ],
    ids=lambda value: repr(value),
)
def test_which_country_answers(kwargs: dict[str, str], expected: str | None) -> None:
    assert _country(resolve_progress_billing(**kwargs)) == expected


def test_german_figures_never_reach_austria_or_switzerland() -> None:
    """The pack claims all three; only Germany is written, so only Germany answers."""
    assert {"DE", "AT", "CH"} <= set(DACH_CFG["countries"]), "precondition: the pack still claims AT and CH"
    assert _country(resolve_progress_billing(country_code="DE")) == "DE"
    for neighbour in ("AT", "CH"):
        assert resolve_progress_billing(country_code=neighbour) is None
        assert resolve_progress_billing(country_code=neighbour, region="DACH") is None


def test_a_market_marker_alone_does_not_pick_a_country() -> None:
    """``DACH`` names three countries; returning Germany's figures for it would be a guess."""
    assert resolve_progress_billing(region="DACH") is None
    # Same fallback, a one-country market: the region names the country, so it answers.
    assert _country(resolve_progress_billing(region="US")) == "US"


@pytest.mark.parametrize("country", ["US", "DE"])
def test_the_answer_is_the_inner_block_not_the_wrapper(country: str) -> None:
    result = resolve_progress_billing(country_code=country)
    assert result is not None
    assert set(result) == _ANSWER_KEYS
    assert country not in result, "the per-country wrapper leaked into the answer"
    assert result["retention_policy"]["tiers"], "the policy a contract is seeded from is empty"


@pytest.mark.parametrize(("country", "cfg"), [("US", US_CFG), ("DE", DACH_CFG)])
def test_the_figures_come_from_the_pack_file(
    country: str, cfg: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A resolver with its own copy of the figures would pass an equality check; this one moves the pack."""
    block = cfg["progress_billing"][country]
    result = resolve_progress_billing(country_code=country)
    assert result is not None
    for key in PROGRESS_BILLING_KEYS:
        assert result[key] == block[key]

    monkeypatch.setitem(block["retention_policy"], "tier_mode", "recompute")
    moved = resolve_progress_billing(country_code=country)
    assert moved is not None and moved["retention_policy"]["tier_mode"] == "recompute"
    assert result["retention_policy"]["tier_mode"] == "prospective", "an earlier answer changed under its caller"


def test_the_answer_is_a_copy_the_caller_may_change() -> None:
    first = resolve_progress_billing(country_code="US")
    assert first is not None
    first["retention_policy"]["tiers"].clear()
    first["billing_cycle"]["frequency"] = "weekly"
    again = resolve_progress_billing(country_code="US")
    assert again is not None
    assert again["retention_policy"]["tiers"] == US_CFG["progress_billing"]["US"]["retention_policy"]["tiers"]
    assert again["billing_cycle"]["frequency"] == "monthly"


# ── The state axis ─────────────────────────────────────────────────────────────


def test_a_known_subdivision_attaches_its_retainage_rules() -> None:
    result = resolve_progress_billing(country_code="US", subdivision_code="us-ca")
    assert result is not None
    subdivision = result["subdivision"]
    assert subdivision is not None
    assert subdivision["subdivision_code"] == "US-CA"
    assert [rule["code"] for rule in subdivision["retainage"]] == [rule["code"] for rule in CA_RULES["retainage"]]
    # The national figures do not change because a state was named.
    assert result["retention_policy"] == US_CFG["progress_billing"]["US"]["retention_policy"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"country_code": "US"},
        {"country_code": "US", "subdivision_code": ""},
        {"country_code": "US", "subdivision_code": "US-NY"},
        {"country_code": "DE", "subdivision_code": "US-CA"},
    ],
    ids=lambda value: repr(value),
)
def test_no_matching_subdivision_leaves_the_state_axis_empty(kwargs: dict[str, str]) -> None:
    """``None`` is what lets a rule say "state cap not checked" instead of applying a wrong one."""
    result = resolve_progress_billing(**kwargs)
    assert result is not None
    assert result["subdivision"] is None


# ── Agreement between packs, shown on fixed data ───────────────────────────────


def _pack(countries: list[str], *, rate: str | None, region: str = "ZZ", parent: str | None = None) -> dict[str, Any]:
    config: dict[str, Any] = {"region_code": region, "countries": countries}
    if parent:
        config["parent_pack"] = parent
    if rate is not None:
        config["progress_billing"] = {
            code: {"retention_policy": {"tiers": [{"from_percent_complete": "0", "rate": rate}]}} for code in countries
        }
    return config


def _use(monkeypatch: pytest.MonkeyPatch, *configs: dict[str, Any]) -> None:
    monkeypatch.setattr(regional_packs, "pack_configs", lambda: tuple(configs))


def _rate(result: dict[str, Any] | None) -> str | None:
    return None if result is None else result["retention_policy"]["tiers"][0]["rate"]


def test_packs_that_agree_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, _pack(["QQ"], rate="10"), _pack(["QQ"], rate="10", region="YY"))
    assert _rate(resolve_progress_billing(country_code="QQ")) == "10"


def test_packs_that_disagree_cancel_out(monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, _pack(["QQ"], rate="10"), _pack(["QQ"], rate="5", region="YY"))
    assert resolve_progress_billing(country_code="QQ") is None


def test_a_silent_pack_is_not_a_dissenting_one(monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, _pack(["QQ"], rate="10"), _pack(["QQ"], rate=None, region="YY"))
    assert _rate(resolve_progress_billing(country_code="QQ")) == "10"


def test_a_state_pack_never_votes(monkeypatch: pytest.MonkeyPatch) -> None:
    national = _pack(["QQ"], rate="10")
    state = _pack(["QQ"], rate="5", region="QQ_S", parent="oe_qq_pack")
    _use(monkeypatch, national, state)
    assert _rate(resolve_progress_billing(country_code="QQ")) == "10"
    # And alone it answers nothing: a state is not a country.
    _use(monkeypatch, state)
    assert resolve_progress_billing(country_code="QQ") is None


def test_region_fallback_needs_exactly_one_country(monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, _pack(["QQ"], rate="10", region="ONE"), _pack(["RR", "SS"], rate="7", region="TWO"))
    assert _rate(resolve_progress_billing(region="ONE")) == "10"
    assert resolve_progress_billing(region="TWO") is None
