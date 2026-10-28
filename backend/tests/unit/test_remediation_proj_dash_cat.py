"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Remediation-backlog regression tests — projects / dashboard / catalog.

Covers the triaged backlog IDs that were still real bugs at v3.1.0:

* A-PROJ-01 — whitespace-only project name must 422 like ``""`` does.
* A-PROJ-02 — currency normalised (trim/upper) + soft 3-letter shape
  check; region/classification stay OPEN (global product) but trimmed.
* A-PROJ-03 — negative contract_value / budget_estimate and
  out-of-range contingency_pct rejected.
* A-PROJ-05 — milestone linked_payment_pct constrained to 0–100.
* A-PROJ-06 / A-DASH-03 — flexible date parsing used for chronological
  ordering across ISO / EU / US formats.
* CAT-001 — catalog price-band integrity (min<=base<=max).
* CAT-003 — price serialisation no longer truncates to 2dp, so a
  factor then its inverse round-trips.

Pure-model / pure-helper tests — no DB required.
"""

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.modules.catalog.router import _fmt_price as _router_fmt_price
from app.modules.catalog.schemas import CatalogResourceCreate
from app.modules.catalog.service import _fmt_price as _service_fmt_price
from app.modules.projects.schemas import (
    MilestoneCreate,
    ProjectCreate,
    ProjectUpdate,
    parse_flexible_date,
)

# ── A-PROJ-01 ────────────────────────────────────────────────────────────


class TestWhitespaceName:
    def test_whitespace_only_name_rejected(self):
        with pytest.raises(ValidationError):
            ProjectCreate(name="   ")

    def test_tab_newline_name_rejected(self):
        with pytest.raises(ValidationError):
            ProjectCreate(name="\t\n  ")

    def test_normal_name_trimmed(self):
        assert ProjectCreate(name="  Tower  ").name == "Tower"

    def test_update_whitespace_name_rejected(self):
        with pytest.raises(ValidationError):
            ProjectUpdate(name="   ")


# ── A-PROJ-02 (soft normalisation, NOT a closed enum) ────────────────────


class TestCurrencyNormalisation:
    def test_currency_uppercased_and_trimmed(self):
        assert ProjectCreate(name="P", currency=" eur ").currency == "EUR"

    def test_empty_currency_stays_empty(self):
        # No default bias — user has not chosen yet.
        assert ProjectCreate(name="P", currency="").currency == ""

    def test_garbage_currency_rejected(self):
        # "NOTACURRENCY" / "123" are data-integrity errors, not regional
        # variants.
        with pytest.raises(ValidationError):
            ProjectCreate(name="P", currency="123")

    def test_uncommon_but_valid_currency_accepted(self):
        # Global product: any 3-letter code is fine (no ISO-4217 whitelist).
        for cur in ("JPY", "AED", "BRL", "MNT", "XOF"):
            assert ProjectCreate(name="P", currency=cur).currency == cur

    def test_region_stays_open_but_trimmed(self):
        p = ProjectCreate(name="P", region="  Atlantis  ", classification_standard=" made_up ")
        # Region/standard are NOT whitelisted (global product) — only trimmed.
        assert p.region == "Atlantis"
        assert p.classification_standard == "made_up"


# ── A-PROJ-03 ────────────────────────────────────────────────────────────


class TestNegativeMoney:
    def test_negative_contract_value_rejected(self):
        with pytest.raises(ValidationError):
            ProjectCreate(name="P", contract_value="-99999999")

    def test_negative_budget_estimate_rejected(self):
        with pytest.raises(ValidationError):
            ProjectCreate(name="P", budget_estimate="-1")

    def test_negative_contingency_rejected(self):
        with pytest.raises(ValidationError):
            ProjectCreate(name="P", contingency_pct="-50")

    def test_contingency_over_100_rejected(self):
        with pytest.raises(ValidationError):
            ProjectCreate(name="P", contingency_pct="150")

    def test_valid_money_accepted(self):
        p = ProjectCreate(
            name="P",
            contract_value="1250000.50",
            budget_estimate="900000",
            contingency_pct="7.5",
        )
        assert p.contract_value == "1250000.50"
        assert p.contingency_pct == "7.5"

    def test_empty_string_clears_to_none(self):
        assert ProjectCreate(name="P", contract_value="").contract_value is None


# ── A-PROJ-05 ────────────────────────────────────────────────────────────


class TestMilestonePaymentPct:
    def test_over_100_rejected(self):
        with pytest.raises(ValidationError):
            MilestoneCreate(name="M", linked_payment_pct="500")

    def test_negative_rejected(self):
        with pytest.raises(ValidationError):
            MilestoneCreate(name="M", linked_payment_pct="-5")

    def test_valid_pct_accepted(self):
        assert MilestoneCreate(name="M", linked_payment_pct="30").linked_payment_pct == "30"

    def test_none_accepted(self):
        assert MilestoneCreate(name="M").linked_payment_pct is None


# ── A-PROJ-06 / A-DASH-03 (flexible chronological date parsing) ───────────


class TestParseFlexibleDate:
    def test_iso(self):
        assert parse_flexible_date("2026-03-15") == datetime(2026, 3, 15)

    def test_european(self):
        assert parse_flexible_date("01.06.2026") == datetime(2026, 6, 1)

    def test_us(self):
        assert parse_flexible_date("12/31/2026") == datetime(2026, 12, 31)

    def test_none_and_blank(self):
        assert parse_flexible_date(None) is None
        assert parse_flexible_date("   ") is None

    def test_unparseable(self):
        assert parse_flexible_date("not-a-date") is None

    def test_chronological_order_across_formats(self):
        # The exact A-PROJ-06 repro: ISO sorts last as a raw string but
        # is actually the earliest date.
        dates = ["12/31/2026", "01.06.2026", "2026-03-15", None]
        ordered = sorted(dates, key=lambda d: parse_flexible_date(d) or datetime.max)
        assert ordered == ["2026-03-15", "01.06.2026", "12/31/2026", None]


# ── CAT-001 ──────────────────────────────────────────────────────────────


class TestCatalogPriceBand:
    def _base(self, **kw):
        d = dict(
            resource_code="X",
            name="n",
            resource_type="material",
            category="C",
            unit="m3",
            base_price=50,
        )
        d.update(kw)
        return d

    def test_inverted_band_rejected(self):
        with pytest.raises(ValidationError):
            CatalogResourceCreate(**self._base(min_price=999, max_price=1))

    def test_base_outside_band_rejected(self):
        with pytest.raises(ValidationError):
            CatalogResourceCreate(**self._base(base_price=50, min_price=10, max_price=20))

    def test_valid_band_accepted(self):
        r = CatalogResourceCreate(**self._base(base_price=50, min_price=10, max_price=99))
        assert r.min_price == 10 and r.max_price == 99

    def test_no_band_single_price_accepted(self):
        # Defaults min/max = 0 — the documented "no band" sentinel.
        r = CatalogResourceCreate(**self._base(base_price=50))
        assert r.min_price == 0 and r.max_price == 0


# ── CAT-003 (precision round-trip) ───────────────────────────────────────


class TestPricePrecision:
    @pytest.mark.parametrize("fmt", [_router_fmt_price, _service_fmt_price])
    def test_factor_then_inverse_round_trips(self, fmt):
        original = 10.005
        up = float(fmt(original * 1.05))
        back = float(fmt(up * (1 / 1.05)))
        # 2dp truncation would lose this; full precision keeps it tight.
        assert abs(back - original) < 1e-6

    @pytest.mark.parametrize("fmt", [_router_fmt_price, _service_fmt_price])
    def test_no_negative_zero(self, fmt):
        assert fmt(0.0) == "0"
        assert fmt(-0.0) == "0"

    @pytest.mark.parametrize("fmt", [_router_fmt_price, _service_fmt_price])
    def test_small_value_not_truncated_to_zero(self, fmt):
        assert float(fmt(0.004)) == pytest.approx(0.004)
