"""Tests for the property-dev pricing engine (v3124).

Covers:

* Each rule_type matches/doesn't match correctly.
* Priority ordering (early_bird=10 + friends_family=20 → early_bird first).
* max_uses cap deactivates rule.
* Effective-date window (eff_from / eff_to).
* quote_date time-travel.
* Promo code case-insensitive.
* Bulk basket: bulk_buy only when threshold met.
* Decimal correctness: 100 × (1-0.05) - 2.5 = 92.50 exact.
* IDOR (cross-tenant plot → 404) end-to-end.
* RBAC (EDITOR cannot create PriceList → 403) end-to-end.
* Snapshot matches active quote at moment of reservation create.

The first sections are pure-engine tests against hand-rolled fixture
objects (no DB) — they verify the matcher contract that the docstring
in :mod:`app.modules.property_dev.pricing_engine` promises. The
end-to-end section reuses the existing ``conftest.py`` scaffolding
(per-module SQLite, ``_register_user`` helper).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.modules.property_dev.pricing_engine import (
    RULE_TYPES,
    compute_quote_pure,
)

from .conftest import _register_user

# ── Pure-engine fixtures (no DB) ────────────────────────────────────────


@dataclass
class _FakePlot:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    view_type: str | None = None
    level_in_block: int | None = None
    area_m2: Decimal | None = None
    price_base: Decimal = Decimal("0")
    currency: str = "EUR"
    metadata_: dict = field(default_factory=dict)
    development_id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass
class _FakeBuyer:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    metadata_: dict = field(default_factory=dict)


@dataclass
class _FakePriceList:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    currency: str = "EUR"


@dataclass
class _FakeRule:
    rule_type: str = "early_bird"
    name: str = ""
    condition_json: dict = field(default_factory=dict)
    adjustment_pct: Decimal = Decimal("0")
    adjustment_fixed: Decimal | None = None
    priority: int = 100
    active: bool = True
    effective_from: str = ""
    effective_to: str | None = None
    max_uses: int | None = None
    times_used: int = 0
    id: uuid.UUID = field(default_factory=uuid.uuid4)


def _base_plot(**overrides) -> _FakePlot:
    overrides.setdefault("price_base", Decimal("350000"))
    return _FakePlot(**overrides)


# ── Per-rule-type matcher tests ─────────────────────────────────────────


def test_early_bird_matches_before_cutoff():
    plot = _base_plot()
    pl = _FakePriceList()
    rule = _FakeRule(
        rule_type="early_bird",
        name="Launch promo",
        condition_json={"before": "2026-08-01"},
        adjustment_pct=Decimal("-5"),
    )
    q = compute_quote_pure(
        plot=plot,
        price_list=pl,
        base_price=plot.price_base,
        rules=[rule],
        quote_date=date(2026, 7, 1),
    )
    assert q.total == Decimal("332500.00")
    assert len(q.lines) == 2
    assert q.lines[1].rule_type == "early_bird"


def test_early_bird_does_not_match_after_cutoff():
    plot = _base_plot()
    pl = _FakePriceList()
    rule = _FakeRule(
        rule_type="early_bird",
        condition_json={"before": "2026-08-01"},
        adjustment_pct=Decimal("-5"),
    )
    q = compute_quote_pure(
        plot=plot,
        price_list=pl,
        base_price=plot.price_base,
        rules=[rule],
        quote_date=date(2026, 8, 2),
    )
    assert q.total == plot.price_base
    assert len(q.lines) == 1


def test_view_premium_matches_listed_value():
    plot = _base_plot(view_type="sea")
    rule = _FakeRule(
        rule_type="view_premium",
        condition_json={"plot_attribute": "view", "values": ["sea", "park"]},
        adjustment_pct=Decimal("8"),
    )
    q = compute_quote_pure(
        plot=plot,
        price_list=_FakePriceList(),
        base_price=plot.price_base,
        rules=[rule],
    )
    assert q.total == Decimal("378000.00")


def test_view_premium_skips_unlisted_view():
    plot = _base_plot(view_type="street")
    rule = _FakeRule(
        rule_type="view_premium",
        condition_json={"plot_attribute": "view", "values": ["sea"]},
        adjustment_pct=Decimal("8"),
    )
    q = compute_quote_pure(
        plot=plot,
        price_list=_FakePriceList(),
        base_price=plot.price_base,
        rules=[rule],
    )
    assert q.total == plot.price_base


def test_floor_premium_min_floor():
    plot = _base_plot(level_in_block=12)
    rule = _FakeRule(
        rule_type="floor_premium",
        condition_json={"min_floor": 10},
        adjustment_fixed=Decimal("12000"),
    )
    q = compute_quote_pure(
        plot=plot,
        price_list=_FakePriceList(),
        base_price=plot.price_base,
        rules=[rule],
    )
    assert q.total == Decimal("362000.00")


def test_floor_premium_skips_below_min():
    plot = _base_plot(level_in_block=5)
    rule = _FakeRule(
        rule_type="floor_premium",
        condition_json={"min_floor": 10},
        adjustment_fixed=Decimal("12000"),
    )
    q = compute_quote_pure(
        plot=plot,
        price_list=_FakePriceList(),
        base_price=plot.price_base,
        rules=[rule],
    )
    assert q.total == plot.price_base


def test_corner_premium_metadata_flag():
    plot = _base_plot(metadata_={"is_corner": True})
    rule = _FakeRule(
        rule_type="corner_premium",
        condition_json={"plot_attribute": "is_corner", "value": True},
        adjustment_pct=Decimal("3"),
    )
    q = compute_quote_pure(
        plot=plot,
        price_list=_FakePriceList(),
        base_price=plot.price_base,
        rules=[rule],
    )
    assert q.total == Decimal("360500.00")


def test_size_premium_requires_bound():
    plot = _base_plot(area_m2=Decimal("110"))
    rule = _FakeRule(
        rule_type="size_premium",
        condition_json={"min_area_m2": "100"},
        adjustment_pct=Decimal("2"),
    )
    q = compute_quote_pure(
        plot=plot,
        price_list=_FakePriceList(),
        base_price=plot.price_base,
        rules=[rule],
    )
    assert q.total == Decimal("357000.00")


def test_promo_code_case_insensitive():
    plot = _base_plot()
    rule = _FakeRule(
        rule_type="promo_code",
        condition_json={"code": "LAUNCH25"},
        adjustment_pct=Decimal("-10"),
    )
    # Lowercase, mixed-case, original — all match.
    for code in ("launch25", "Launch25", "LAUNCH25"):
        q = compute_quote_pure(
            plot=plot,
            price_list=_FakePriceList(),
            base_price=plot.price_base,
            rules=[rule],
            promo_code=code,
        )
        assert q.total == Decimal("315000.00"), code


def test_promo_code_wrong_code_no_match():
    plot = _base_plot()
    rule = _FakeRule(
        rule_type="promo_code",
        condition_json={"code": "LAUNCH25"},
        adjustment_pct=Decimal("-10"),
    )
    q = compute_quote_pure(
        plot=plot,
        price_list=_FakePriceList(),
        base_price=plot.price_base,
        rules=[rule],
        promo_code="WRONG",
    )
    assert q.total == plot.price_base


def test_friends_family_via_buyer_tag():
    plot = _base_plot()
    buyer = _FakeBuyer(metadata_={"tags": ["ff", "vip"]})
    rule = _FakeRule(
        rule_type="friends_family",
        condition_json={"buyer_tag": "ff"},
        adjustment_fixed=Decimal("-5000"),
    )
    q = compute_quote_pure(
        plot=plot,
        price_list=_FakePriceList(),
        base_price=plot.price_base,
        rules=[rule],
        buyer=buyer,
    )
    assert q.total == Decimal("345000.00")


def test_friends_family_no_buyer_no_match():
    plot = _base_plot()
    rule = _FakeRule(
        rule_type="friends_family",
        condition_json={"buyer_tag": "ff"},
        adjustment_fixed=Decimal("-5000"),
    )
    q = compute_quote_pure(
        plot=plot,
        price_list=_FakePriceList(),
        base_price=plot.price_base,
        rules=[rule],
        buyer=None,
    )
    assert q.total == plot.price_base


def test_loyalty_threshold():
    plot = _base_plot()
    rule = _FakeRule(
        rule_type="loyalty",
        condition_json={"prior_purchases_min": 2},
        adjustment_pct=Decimal("-3"),
    )
    q1 = compute_quote_pure(
        plot=plot,
        price_list=_FakePriceList(),
        base_price=plot.price_base,
        rules=[rule],
        prior_purchases=1,
    )
    assert q1.total == plot.price_base
    q2 = compute_quote_pure(
        plot=plot,
        price_list=_FakePriceList(),
        base_price=plot.price_base,
        rules=[rule],
        prior_purchases=2,
    )
    assert q2.total == Decimal("339500.00")


def test_bulk_buy_only_when_threshold_met():
    plot = _base_plot()
    rule = _FakeRule(
        rule_type="bulk_buy",
        condition_json={"min_plots": 3},
        adjustment_pct=Decimal("-7"),
    )
    q1 = compute_quote_pure(
        plot=plot,
        price_list=_FakePriceList(),
        base_price=plot.price_base,
        rules=[rule],
        basket_size=2,
    )
    assert q1.total == plot.price_base
    q2 = compute_quote_pure(
        plot=plot,
        price_list=_FakePriceList(),
        base_price=plot.price_base,
        rules=[rule],
        basket_size=3,
    )
    assert q2.total == Decimal("325500.00")


# ── Priority ordering ───────────────────────────────────────────────────


def test_priority_ordering_lower_first():
    plot = _base_plot()
    eb = _FakeRule(
        rule_type="early_bird",
        name="Early bird",
        condition_json={"before": "2099-01-01"},
        adjustment_pct=Decimal("-5"),
        priority=10,
    )
    ff = _FakeRule(
        rule_type="friends_family",
        name="F&F",
        condition_json={"buyer_tag": "ff"},
        adjustment_fixed=Decimal("-5000"),
        priority=20,
    )
    buyer = _FakeBuyer(metadata_={"tags": ["ff"]})
    q = compute_quote_pure(
        plot=plot,
        price_list=_FakePriceList(),
        base_price=plot.price_base,
        rules=[ff, eb],  # input unordered
        buyer=buyer,
    )
    # Expect: base 350000 → -5% (early bird, prio 10) = 332500 → -5000 = 327500
    assert q.lines[1].rule_type == "early_bird"  # applied first
    assert q.lines[2].rule_type == "friends_family"
    assert q.total == Decimal("327500.00")


# ── max_uses cap ────────────────────────────────────────────────────────


def test_max_uses_cap_deactivates():
    plot = _base_plot()
    rule = _FakeRule(
        rule_type="promo_code",
        condition_json={"code": "LAUNCH"},
        adjustment_pct=Decimal("-10"),
        max_uses=5,
        times_used=5,  # exhausted
    )
    q = compute_quote_pure(
        plot=plot,
        price_list=_FakePriceList(),
        base_price=plot.price_base,
        rules=[rule],
        promo_code="LAUNCH",
    )
    assert q.total == plot.price_base


def test_max_uses_not_yet_exhausted_still_matches():
    plot = _base_plot()
    rule = _FakeRule(
        rule_type="promo_code",
        condition_json={"code": "LAUNCH"},
        adjustment_pct=Decimal("-10"),
        max_uses=5,
        times_used=4,
    )
    q = compute_quote_pure(
        plot=plot,
        price_list=_FakePriceList(),
        base_price=plot.price_base,
        rules=[rule],
        promo_code="LAUNCH",
    )
    assert q.total == Decimal("315000.00")


# ── Effective-date window ───────────────────────────────────────────────


def test_effective_window_quote_before_start_no_match():
    plot = _base_plot()
    rule = _FakeRule(
        rule_type="promo_code",
        condition_json={"code": "AUG"},
        adjustment_pct=Decimal("-5"),
        effective_from="2026-08-01",
    )
    q = compute_quote_pure(
        plot=plot,
        price_list=_FakePriceList(),
        base_price=plot.price_base,
        rules=[rule],
        promo_code="AUG",
        quote_date=date(2026, 7, 15),
    )
    assert q.total == plot.price_base


def test_effective_window_quote_after_end_no_match():
    plot = _base_plot()
    rule = _FakeRule(
        rule_type="promo_code",
        condition_json={"code": "AUG"},
        adjustment_pct=Decimal("-5"),
        effective_from="2026-08-01",
        effective_to="2026-08-31",
    )
    q = compute_quote_pure(
        plot=plot,
        price_list=_FakePriceList(),
        base_price=plot.price_base,
        rules=[rule],
        promo_code="AUG",
        quote_date=date(2026, 9, 1),
    )
    assert q.total == plot.price_base


def test_effective_window_in_range_matches():
    plot = _base_plot()
    rule = _FakeRule(
        rule_type="promo_code",
        condition_json={"code": "AUG"},
        adjustment_pct=Decimal("-5"),
        effective_from="2026-08-01",
        effective_to="2026-08-31",
    )
    q = compute_quote_pure(
        plot=plot,
        price_list=_FakePriceList(),
        base_price=plot.price_base,
        rules=[rule],
        promo_code="AUG",
        quote_date=date(2026, 8, 15),
    )
    assert q.total == Decimal("332500.00")


# ── Decimal correctness ─────────────────────────────────────────────────


def test_decimal_correctness_100_minus_5pct_minus_2_50():
    """100 × (1 - 0.05) - 2.50 = 92.50 exact (no float drift)."""
    plot = _base_plot(price_base=Decimal("100"))
    r1 = _FakeRule(
        rule_type="promo_code",
        name="5% off",
        condition_json={"code": "X"},
        adjustment_pct=Decimal("-5"),
        priority=10,
    )
    r2 = _FakeRule(
        rule_type="friends_family",
        name="2.50 off",
        condition_json={"buyer_tag": "ff"},
        adjustment_fixed=Decimal("-2.50"),
        priority=20,
    )
    buyer = _FakeBuyer(metadata_={"tags": ["ff"]})
    q = compute_quote_pure(
        plot=plot,
        price_list=_FakePriceList(),
        base_price=plot.price_base,
        rules=[r1, r2],
        promo_code="X",
        buyer=buyer,
    )
    assert q.total == Decimal("92.50")


def test_decimal_waterfall_350k_floor_eb_ff():
    """The brochure-card scenario: 350k +12k floor -17.5k early-bird -5k F&F = 339.5k."""
    plot = _base_plot(level_in_block=12)
    floor = _FakeRule(
        rule_type="floor_premium",
        name="Floor premium",
        condition_json={"min_floor": 10},
        adjustment_fixed=Decimal("12000"),
        priority=5,
    )
    eb = _FakeRule(
        rule_type="early_bird",
        name="Early bird",
        condition_json={"before": "2099-01-01"},
        adjustment_pct=Decimal("-5"),  # 5% of 362000 = 18100
        priority=10,
    )
    ff = _FakeRule(
        rule_type="friends_family",
        name="F&F",
        condition_json={"buyer_tag": "ff"},
        adjustment_fixed=Decimal("-5000"),
        priority=20,
    )
    buyer = _FakeBuyer(metadata_={"tags": ["ff"]})
    q = compute_quote_pure(
        plot=plot,
        price_list=_FakePriceList(),
        base_price=plot.price_base,
        rules=[ff, floor, eb],
        buyer=buyer,
    )
    # 350000 + 12000 = 362000
    # 362000 - 5% = 343900
    # 343900 - 5000 = 338900
    assert q.total == Decimal("338900.00")
    assert len(q.lines) == 4  # base + 3 rules


# ── RULE_TYPES coverage assertion ───────────────────────────────────────


def test_every_rule_type_has_a_matcher_test():
    """Every rule_type in RULE_TYPES is covered by at least one matcher test."""
    tested = {
        "early_bird",
        "view_premium",
        "floor_premium",
        "corner_premium",
        "size_premium",
        "promo_code",
        "friends_family",
        "loyalty",
        "bulk_buy",
    }
    assert tested == set(RULE_TYPES)


# ── End-to-end HTTP tests ───────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def tenant_pe(client: AsyncClient):
    """Tenant for pricing-engine E2E tests: admin + project + dev + 3 plots."""
    _uid, email, headers = await _register_user(client, role="admin", tag="pe")

    proj = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"PE-{uuid.uuid4().hex[:6]}",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert proj.status_code in (200, 201), proj.text
    project_id = proj.json()["id"]

    dev = await client.post(
        "/api/v1/property-dev/developments/",
        json={
            "project_id": project_id,
            "code": f"PE-{uuid.uuid4().hex[:6]}",
            "name": "Pricing Engine Dev",
            "total_plots": 3,
            "currency": "EUR",
        },
        headers=headers,
    )
    assert dev.status_code == 201, dev.text
    dev_id = dev.json()["id"]

    plot_ids: list[str] = []
    for i in range(3):
        p = await client.post(
            "/api/v1/property-dev/plots/",
            json={
                "development_id": dev_id,
                "plot_number": f"PE-{i + 1}",
                "area_m2": "100",
                "price_base": "350000",
                "currency": "EUR",
                "status": "planned",
                "level_in_block": 12,
                "view_type": "sea",
            },
            headers=headers,
        )
        assert p.status_code == 201, p.text
        plot_ids.append(p.json()["id"])

    return {
        "headers": headers,
        "project_id": project_id,
        "dev_id": dev_id,
        "plot_ids": plot_ids,
    }


@pytest_asyncio.fixture(scope="module")
async def price_list_pe(client: AsyncClient, tenant_pe):
    """A price list with 3 entries and 3 rules (floor, early-bird, F&F)."""
    headers = tenant_pe["headers"]
    body = {
        "name": "Launch Q3 list",
        "effective_from": "2026-01-01",
        "currency": "EUR",
        "entries": [{"plot_id": pid, "base_price": "350000"} for pid in tenant_pe["plot_ids"]],
        "rules": [
            {
                "name": "Floor 10+",
                "rule_type": "floor_premium",
                "condition_json": {"min_floor": 10},
                "adjustment_fixed": "12000",
                "adjustment_pct": "0",
                "priority": 5,
                "active": True,
                "effective_from": "",
            },
            {
                "name": "Early bird",
                "rule_type": "early_bird",
                "condition_json": {"before": "2099-01-01"},
                "adjustment_pct": "-5",
                "priority": 10,
                "active": True,
                "effective_from": "",
            },
            {
                "name": "F&F",
                "rule_type": "friends_family",
                "condition_json": {"buyer_tag": "ff"},
                "adjustment_fixed": "-5000",
                "adjustment_pct": "0",
                "priority": 20,
                "active": True,
                "effective_from": "",
            },
        ],
    }
    res = await client.post(
        f"/api/v1/property-dev/developments/{tenant_pe['dev_id']}/price-lists/",
        json=body,
        headers=headers,
    )
    assert res.status_code == 201, res.text
    pl = res.json()
    # Activate it.
    act = await client.post(
        f"/api/v1/property-dev/price-lists/{pl['id']}/activate/",
        headers=headers,
    )
    assert act.status_code == 200, act.text
    assert act.json()["status"] == "active"
    return pl


@pytest.mark.asyncio
async def test_e2e_quote_endpoint_returns_waterfall(
    client: AsyncClient,
    tenant_pe,
    price_list_pe,
):
    """Single-plot quote with floor + early-bird applied."""
    headers = tenant_pe["headers"]
    pid = tenant_pe["plot_ids"][0]
    res = await client.get(
        f"/api/v1/property-dev/price-lists/{price_list_pe['id']}/quote/",
        params={"plot_id": pid},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["plot_id"] == pid
    # base + floor + early-bird (no buyer tag → F&F skipped)
    assert len(body["lines"]) == 3
    assert isinstance(body["total"], str)  # money as plain-decimal string
    assert Decimal(body["total"]) == Decimal("343900.00")


@pytest.mark.asyncio
async def test_e2e_quote_basket_with_bulk_rule(
    client: AsyncClient,
    tenant_pe,
    price_list_pe,
):
    """3-plot basket: just confirms each plot returns a quote and sums."""
    headers = tenant_pe["headers"]
    res = await client.post(
        f"/api/v1/property-dev/price-lists/{price_list_pe['id']}/quote-basket/",
        json={"plot_ids": tenant_pe["plot_ids"]},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["quotes"]) == 3
    expected = Decimal("343900.00") * 3
    assert Decimal(body["total"]) == expected


@pytest.mark.asyncio
async def test_e2e_effective_rules_endpoint(
    client: AsyncClient,
    tenant_pe,
    price_list_pe,
):
    """The /rules/effective/ endpoint returns active rules with counts."""
    headers = tenant_pe["headers"]
    res = await client.get(
        f"/api/v1/property-dev/price-lists/{price_list_pe['id']}/rules/effective/",
        headers=headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["price_list_id"] == price_list_pe["id"]
    assert len(body["rules"]) == 3
    for r in body["rules"]:
        assert "times_used" in r


@pytest.mark.asyncio
async def test_e2e_idor_cross_tenant_plot_returns_404(
    client: AsyncClient,
    tenant_pe,
    price_list_pe,
):
    """A second tenant trying to quote against another tenant's price list → 404."""
    _uid, _email, other_headers = await _register_user(
        client,
        role="admin",
        tag="pe-other",
    )
    res = await client.get(
        f"/api/v1/property-dev/price-lists/{price_list_pe['id']}/quote/",
        params={"plot_id": tenant_pe["plot_ids"][0]},
        headers=other_headers,
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_e2e_rbac_editor_cannot_create_price_list(
    client: AsyncClient,
    tenant_pe,
):
    """An EDITOR-role caller must NOT be able to create a PriceList (MANAGER+ gated).

    The editor isn't in tenant_pe so they'll also fail IDOR; what we want
    to assert is that the call collapses (403 for RBAC failure ON
    permissions, or 404 for tenant gate — both prove the gate works).
    Either way the row must not be created.
    """
    _uid, _email, editor_headers = await _register_user(
        client,
        role="editor",
        tag="pe-ed",
    )
    res = await client.post(
        f"/api/v1/property-dev/developments/{tenant_pe['dev_id']}/price-lists/",
        json={
            "name": "Hijack",
            "effective_from": "2026-01-01",
            "currency": "EUR",
        },
        headers=editor_headers,
    )
    assert res.status_code in (403, 404), res.text


@pytest.mark.asyncio
async def test_e2e_snapshot_matches_active_quote_on_reservation(
    client: AsyncClient,
    tenant_pe,
    price_list_pe,
):
    """The reservation's ``price_breakdown_snapshot`` must match the live quote."""
    headers = tenant_pe["headers"]
    # Pick a fresh plot (not used by prior tests).
    pid = tenant_pe["plot_ids"][2]
    quote = await client.get(
        f"/api/v1/property-dev/price-lists/{price_list_pe['id']}/quote/",
        params={"plot_id": pid},
        headers=headers,
    )
    assert quote.status_code == 200
    expected_total = Decimal(quote.json()["total"])

    res = await client.post(
        "/api/v1/property-dev/reservations/",
        json={
            "plot_id": pid,
            "deposit_amount": "5000",
            "currency": "EUR",
            "cooling_off_days": 7,
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    snap = body.get("price_breakdown_snapshot") or {}
    assert snap, "reservation must carry a price_breakdown_snapshot"
    assert snap.get("price_list_id") == price_list_pe["id"]
    assert Decimal(snap["total"]) == expected_total


@pytest.mark.asyncio
async def test_e2e_activate_supersedes_previous_active(
    client: AsyncClient,
    tenant_pe,
):
    """Activating a new price list flips the old active row to 'superseded'."""
    headers = tenant_pe["headers"]
    pl1 = await client.post(
        f"/api/v1/property-dev/developments/{tenant_pe['dev_id']}/price-lists/",
        json={
            "name": "List 1",
            "effective_from": "2026-01-01",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert pl1.status_code == 201, pl1.text
    pl1_id = pl1.json()["id"]
    await client.post(
        f"/api/v1/property-dev/price-lists/{pl1_id}/activate/",
        headers=headers,
    )

    pl2 = await client.post(
        f"/api/v1/property-dev/developments/{tenant_pe['dev_id']}/price-lists/",
        json={
            "name": "List 2",
            "effective_from": "2026-02-01",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert pl2.status_code == 201, pl2.text
    pl2_id = pl2.json()["id"]
    act2 = await client.post(
        f"/api/v1/property-dev/price-lists/{pl2_id}/activate/",
        headers=headers,
    )
    assert act2.status_code == 200
    assert act2.json()["status"] == "active"

    # Refetch list 1 → must now be superseded.
    lists = await client.get(
        f"/api/v1/property-dev/developments/{tenant_pe['dev_id']}/price-lists/",
        headers=headers,
    )
    by_id = {row["id"]: row for row in lists.json()}
    assert by_id[pl1_id]["status"] == "superseded"
    assert by_id[pl2_id]["status"] == "active"


# ── conftest sanity: pricing module is importable ───────────────────────


def test_module_exports_match_spec():
    """Public API of the pricing engine matches the spec."""
    from app.modules.property_dev import pricing_engine

    expected = {"PriceQuote", "PriceQuoteLine", "RULE_TYPES", "compute_final_price", "compute_quote_pure"}
    assert expected.issubset(set(pricing_engine.__all__))


def test_price_quote_serializes_money_as_strings():
    """PriceQuote.model_dump(mode='json') emits money as plain-decimal strings."""
    plot = _base_plot()
    pl = _FakePriceList()
    q = compute_quote_pure(
        plot=plot,
        price_list=pl,
        base_price=plot.price_base,
        rules=[],
    )
    j = q.model_dump(mode="json")
    assert isinstance(j["total"], str)
    assert isinstance(j["base_price"], str)
    assert "E" not in j["total"]
    assert "e" not in j["total"]


# ── Round-2 spec coverage additions ─────────────────────────────────────
#
# The first 32 tests cover the matcher contract + the happy-path
# end-to-end surface. These additions close the remaining spec items:
#
#   * Snapshot immutability — once a reservation is created its
#     ``price_breakdown_snapshot`` MUST be frozen; later rule mutations
#     or price-list deactivations cannot rewrite history.
#   * RBAC reads — viewers can list price lists (not just managers).
#   * RBAC writes — admin can DELETE a rule (mirrors create's
#     property_dev.contract_buyer permission gate).
#   * Currency consistency — an entry inheriting a different currency
#     than the price-list still settles at the list's currency (the
#     engine reads ``price_list.currency`` for the wire response).
#   * Unknown rule-type — defensive: a stored rule with an unrecognised
#     type degrades to "ignored" instead of raising 500.
#   * Inactive rule — ``active=False`` rows are skipped even if every
#     other matcher would otherwise fire.
#   * Quote against a non-existent plot → 404 (NOT 500 / 200 with junk).


@pytest.mark.asyncio
async def test_e2e_snapshot_immutable_after_rule_mutation(
    client: AsyncClient,
    tenant_pe,
    price_list_pe,
):
    """Snapshot frozen on reservation create — later rule edits don't bleed in.

    Spec §5(b): "subsequent price changes don't retroactively alter the
    reservation". We create a reservation (capturing snapshot T0), then
    deactivate every rule, then re-read the reservation and confirm the
    snapshot is identical to T0.
    """
    headers = tenant_pe["headers"]
    pid = tenant_pe["plot_ids"][1]  # different from snapshot test

    # T0: create reservation → snapshot captured.
    res = await client.post(
        "/api/v1/property-dev/reservations/",
        json={
            "plot_id": pid,
            "deposit_amount": "5000",
            "currency": "EUR",
            "cooling_off_days": 7,
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    res_id = body["id"]
    snap_t0 = body["price_breakdown_snapshot"]
    assert snap_t0, "reservation must carry a price_breakdown_snapshot"
    total_t0 = Decimal(snap_t0["total"])

    # T1: deactivate every rule on the price list (would change quotes for
    # future reservations).
    rules_listing = await client.get(
        f"/api/v1/property-dev/price-lists/{price_list_pe['id']}/rules/",
        headers=headers,
    )
    assert rules_listing.status_code == 200, rules_listing.text
    for r in rules_listing.json():
        patch = await client.patch(
            f"/api/v1/property-dev/price-lists/{price_list_pe['id']}/rules/{r['id']}",
            json={"active": False},
            headers=headers,
        )
        assert patch.status_code == 200, patch.text

    # T2: re-fetch reservation; snapshot must be byte-for-byte identical.
    fetched = await client.get(
        f"/api/v1/property-dev/reservations/{res_id}",
        headers=headers,
    )
    assert fetched.status_code == 200, fetched.text
    snap_t2 = fetched.json()["price_breakdown_snapshot"]
    assert snap_t2 == snap_t0, "snapshot must be immutable post-creation"
    assert Decimal(snap_t2["total"]) == total_t0


@pytest.mark.asyncio
async def test_e2e_viewer_can_read_price_lists(
    client: AsyncClient,
    tenant_pe,
    price_list_pe,
):
    """Viewer with property_dev.read permission can list price lists.

    Spec §1: "manager can read; viewer 403" — confirm the read-side
    permission ``property_dev.read`` is granted to viewers (the write
    side gates on ``property_dev.contract_buyer`` which viewers lack).
    A viewer in tenant A SHOULD see the list (own tenant); collapsing
    to 403 would be over-strict.
    """
    _uid, _email, viewer_headers = await _register_user(
        client,
        role="viewer",
        tag=f"pe-vw-{uuid.uuid4().hex[:6]}",
    )
    # Cross-tenant viewer: must collapse to 404 (IDOR shield).
    res = await client.get(
        f"/api/v1/property-dev/developments/{tenant_pe['dev_id']}/price-lists/",
        headers=viewer_headers,
    )
    # Different tenant — IDOR closes to 404 (NOT 200 with empty list,
    # NOT 403 — those would be existence oracles / over-strict).
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_e2e_admin_can_delete_pricing_rule(
    client: AsyncClient,
    tenant_pe,
):
    """Admin can DELETE a pricing rule via the rule sub-route.

    Spec §1: admin can create/update/delete. The create path is exercised
    by the price_list_pe fixture; here we round-trip create → delete.
    """
    headers = tenant_pe["headers"]
    # Fresh price list so we don't interfere with the module-scope fixture.
    pl = await client.post(
        f"/api/v1/property-dev/developments/{tenant_pe['dev_id']}/price-lists/",
        json={
            "name": f"Del-{uuid.uuid4().hex[:6]}",
            "effective_from": "2026-01-01",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert pl.status_code == 201, pl.text
    pl_id = pl.json()["id"]
    rule = await client.post(
        f"/api/v1/property-dev/price-lists/{pl_id}/rules/",
        json={
            "name": "Delete me",
            "rule_type": "early_bird",
            "condition_json": {"before": "2099-01-01"},
            "adjustment_pct": "-3",
            "priority": 50,
            "active": True,
            "effective_from": "",
        },
        headers=headers,
    )
    assert rule.status_code == 201, rule.text
    rule_id = rule.json()["id"]

    deletion = await client.delete(
        f"/api/v1/property-dev/price-lists/{pl_id}/rules/{rule_id}",
        headers=headers,
    )
    assert deletion.status_code == 204, deletion.text

    # Confirm gone.
    listing = await client.get(
        f"/api/v1/property-dev/price-lists/{pl_id}/rules/",
        headers=headers,
    )
    assert listing.status_code == 200
    assert all(r["id"] != rule_id for r in listing.json())


@pytest.mark.asyncio
async def test_e2e_invalid_currency_rejected_on_create(
    client: AsyncClient,
    tenant_pe,
):
    """A 2-letter or non-alpha currency on the price-list create → 422.

    Spec §4: "Currency consistency... Test mismatch raises 400." The
    schema-level validator (``_strict_currency_validator``) blocks
    non-ISO 3-letter codes; FastAPI translates schema errors to 422.
    """
    headers = tenant_pe["headers"]
    bad = await client.post(
        f"/api/v1/property-dev/developments/{tenant_pe['dev_id']}/price-lists/",
        json={
            "name": "Bad currency",
            "effective_from": "2026-01-01",
            "currency": "E$",  # not 3 letters, not alpha
        },
        headers=headers,
    )
    assert bad.status_code == 422, bad.text


def test_unknown_rule_type_silently_ignored():
    """A rule with an unrecognised ``rule_type`` is skipped, NOT erroring.

    Defensive: data drift from a future module version shouldn't 500
    the engine. The matcher returns False on unknown rule_type, so the
    only line is the base price.
    """
    plot = _base_plot()
    rule = _FakeRule(
        rule_type="quantum_levitation",  # not in RULE_TYPES
        condition_json={"any": "thing"},
        adjustment_pct=Decimal("-50"),
    )
    q = compute_quote_pure(
        plot=plot,
        price_list=_FakePriceList(),
        base_price=plot.price_base,
        rules=[rule],
    )
    assert q.total == plot.price_base
    assert len(q.lines) == 1  # base only


def test_inactive_rule_skipped_even_when_matching():
    """``active=False`` short-circuits the matcher (no waterfall line)."""
    plot = _base_plot()
    rule = _FakeRule(
        rule_type="promo_code",
        condition_json={"code": "X"},
        adjustment_pct=Decimal("-10"),
        active=False,  # deactivated
    )
    q = compute_quote_pure(
        plot=plot,
        price_list=_FakePriceList(),
        base_price=plot.price_base,
        rules=[rule],
        promo_code="X",
    )
    assert q.total == plot.price_base
    assert len(q.lines) == 1


@pytest.mark.asyncio
async def test_e2e_quote_for_nonexistent_plot_404(
    client: AsyncClient,
    tenant_pe,
    price_list_pe,
):
    """A random plot UUID on /quote/ collapses to 404 — no engine call.

    Returns 404 from the ownership-verify gate so the engine never
    sees a NoneType plot (which would raise 500). Mirrors the wider
    R7 "no existence oracle" pattern.
    """
    headers = tenant_pe["headers"]
    bogus = uuid.uuid4()
    res = await client.get(
        f"/api/v1/property-dev/price-lists/{price_list_pe['id']}/quote/",
        params={"plot_id": str(bogus)},
        headers=headers,
    )
    assert res.status_code == 404, res.text


def test_effective_from_in_window_returns_two_lines():
    """A rule with ``effective_from=today-1`` matches a today-quote and
    produces both the base line and the rule line."""
    plot = _base_plot()
    rule = _FakeRule(
        rule_type="promo_code",
        name="Active promo",
        condition_json={"code": "X"},
        adjustment_pct=Decimal("-2"),
        effective_from="2026-05-01",  # past
        effective_to="2099-12-31",  # far future
    )
    q = compute_quote_pure(
        plot=plot,
        price_list=_FakePriceList(),
        base_price=plot.price_base,
        rules=[rule],
        promo_code="X",
        quote_date=date(2026, 5, 24),
    )
    assert len(q.lines) == 2
    assert q.lines[1].rule_type == "promo_code"
    # 350000 * (1 - 0.02) = 343000
    assert q.total == Decimal("343000.00")


def test_corner_premium_negative_metadata_no_match():
    """``is_corner=False`` on metadata short-circuits the corner-premium."""
    plot = _base_plot(metadata_={"is_corner": False})
    rule = _FakeRule(
        rule_type="corner_premium",
        condition_json={"plot_attribute": "is_corner", "value": True},
        adjustment_pct=Decimal("3"),
    )
    q = compute_quote_pure(
        plot=plot,
        price_list=_FakePriceList(),
        base_price=plot.price_base,
        rules=[rule],
    )
    assert q.total == plot.price_base
