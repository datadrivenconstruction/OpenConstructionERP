"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Normalisation, element grouping and percentile band maths of the cost benchmarks."""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.cost_benchmarks import bench_math as bm


def _basis(**kw):
    defaults = {
        "base_date": date(2026, 6, 1),
        "base_region": "MUC",
        "reporting_currency": "EUR",
        "index_points": {"2022-06": Decimal("100"), "2026-06": Decimal("125")},
        "region_factors": {"MUC": Decimal("1.20"), "BER": Decimal("1.00")},
        "fx_quotes": {"USD": Decimal("1.10"), "GBP": Decimal("0.85")},
    }
    defaults.update(kw)
    return bm.Basis(**defaults)


def test_normalise_applies_index_location_and_fx():
    f = bm.factors_for(_basis(), cost_date=date(2022, 6, 15), region="BER", currency="USD")
    assert f.temporal == Decimal("1.25")
    assert f.location == Decimal("1.2")
    # 1100 USD = 1000 EUR, x 1.25 x 1.2
    assert bm.normalise(Decimal("1100"), f) == Decimal("1500.00")
    assert not f.stale
    assert not f.missing_fx


def test_missing_fx_quote_is_flagged_not_guessed():
    f = bm.factors_for(_basis(), cost_date=date(2026, 6, 1), region=None, currency="JPY")
    assert f.missing_fx


def test_stale_index_when_last_point_far_from_base_date():
    f = bm.factors_for(_basis(base_date=date(2028, 6, 1)), cost_date=date(2026, 6, 1), region=None, currency="EUR")
    assert f.stale


def test_no_index_is_stale():
    f = bm.factors_for(_basis(index_points={}), cost_date=date(2026, 6, 1), region=None, currency="EUR")
    assert f.stale
    assert f.temporal == 1


@pytest.mark.parametrize(
    ("standard", "code", "group"),
    [
        ("din276", "331", "330"),
        ("nrm1", "2.5.1", "2.5"),
        ("masterformat", "03 30 00", "03"),
        ("uniformat", "B2010", "B20"),
    ],
)
def test_element_group(standard, code, group):
    assert bm.element_group(standard, code) == group


def test_band_percentiles_and_position():
    b = bm.band([Decimal(v) for v in (100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 1100)])
    assert (b.p10, b.p50, b.p90) == (Decimal("200"), Decimal("600"), Decimal("1000"))
    assert bm.position(Decimal("150"), b) == "below"
    assert bm.position(Decimal("600"), b) == "within"
    assert bm.position(Decimal("1200"), b) == "above"
    assert bm.position(None, b) == "unknown"


def test_empty_band_is_unknown():
    b = bm.band([])
    assert b.count == 0
    assert bm.position(Decimal("1"), b) == "unknown"


def test_per_unit_and_gfa_bucket():
    assert bm.per_unit(Decimal("1000"), Decimal("0")) is None
    assert bm.per_unit(Decimal("1000"), Decimal("3")) == Decimal("333.33")
    assert bm.gfa_bucket(Decimal("4200")) == "<5000"
    assert bm.gfa_bucket(None) == "unknown"
