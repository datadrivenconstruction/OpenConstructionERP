# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""EVM (Earned Value Management) formula correctness tests for the EAC module.

This test suite validates all EVM calculations in isolation — no DB, no HTTP,
no async. All monetary values (BAC, EV, AC, EAC, ETC, VAC) are represented
as ``Decimal`` strings in storage and converted to ``Decimal`` for computation.
Dimensionless ratios (CPI, SPI, CV%, SV%) are plain Python ``float``.

The canonical EVM identities tested here:

  SV  = EV  - PV                   (Schedule Variance)
  CV  = EV  - AC                   (Cost Variance)
  CPI = EV  / AC                   (Cost Performance Index)
  SPI = EV  / PV                   (Schedule Performance Index)

  EAC₁ = BAC / CPI                 (Forecast from CPI trend)
  EAC₂ = AC  + (BAC - EV)          (Forecast: burn original estimate)
  EAC₃ = AC  + (BAC - EV) / (CPI × SPI) (Forecast: combined CPI+SPI)

  ETC = EAC - AC                   (Estimate to Complete)
  VAC = BAC - EAC                  (Variance at Completion)

Edge cases:
  - EV = 0 → CPI = None (avoids division by zero)
  - PV = 0 → SPI = None
  - CPI × SPI = 0 → EAC₃ = None
  - BAC = 0 → VAC = 0, EAC₁ = 0 (CPI check still applies)
"""

from __future__ import annotations

from decimal import Decimal

# ── EVM calculation engine (pure functions, no DB/ORM) ───────────────────────


def _d(value: str | int | float) -> Decimal:
    """Convert a value to Decimal. Mirrors service-layer money coercion."""
    return Decimal(str(value))


def compute_cpi(ev: Decimal, ac: Decimal) -> float | None:
    """Cost Performance Index = EV / AC.

    Returns None when AC is zero to signal division-by-zero instead of
    raising. Callers must treat None as 'undefined / project not started'.
    """
    if ac == 0:
        return None
    return float(ev / ac)


def compute_spi(ev: Decimal, pv: Decimal) -> float | None:
    """Schedule Performance Index = EV / PV.

    Returns None when PV is zero (no work was planned yet).
    """
    if pv == 0:
        return None
    return float(ev / pv)


def compute_sv(ev: Decimal, pv: Decimal) -> Decimal:
    """Schedule Variance = EV - PV."""
    return ev - pv


def compute_cv(ev: Decimal, ac: Decimal) -> Decimal:
    """Cost Variance = EV - AC."""
    return ev - ac


def compute_eac_cpi(bac: Decimal, cpi: float | None) -> Decimal | None:
    """EAC₁ = BAC / CPI — forecast purely from cost performance trend.

    Returns None when CPI is undefined (AC=0) or zero.
    """
    if cpi is None or cpi == 0.0:
        return None
    return (bac / Decimal(str(cpi))).quantize(Decimal("0.01"))


def compute_eac_remaining(ac: Decimal, bac: Decimal, ev: Decimal) -> Decimal:
    """EAC₂ = AC + (BAC - EV) — burn original estimate for remaining work."""
    return ac + (bac - ev)


def compute_eac_combined(
    ac: Decimal,
    bac: Decimal,
    ev: Decimal,
    cpi: float | None,
    spi: float | None,
) -> Decimal | None:
    """EAC₃ = AC + (BAC - EV) / (CPI × SPI) — combined performance factor.

    Returns None when either index is undefined or their product is zero.
    """
    if cpi is None or spi is None:
        return None
    product = cpi * spi
    if product == 0.0:
        return None
    remaining = bac - ev
    return (ac + remaining / Decimal(str(product))).quantize(Decimal("0.01"))


def compute_etc(eac: Decimal | None, ac: Decimal) -> Decimal | None:
    """ETC = EAC - AC. Returns None when EAC is undefined."""
    if eac is None:
        return None
    return eac - ac


def compute_vac(bac: Decimal, eac: Decimal | None) -> Decimal | None:
    """VAC = BAC - EAC. Returns None when EAC is undefined."""
    if eac is None:
        return None
    return bac - eac


# ── Tests ────────────────────────────────────────────────────────────────────


class TestCPIandSPI:
    """Cost and Schedule Performance Indices."""

    def test_cpi_standard_case(self) -> None:
        # BAC=1000, EV=600, AC=700 → CPI = 600/700 ≈ 0.857
        ev, ac = _d(600), _d(700)
        cpi = compute_cpi(ev, ac)
        assert cpi is not None
        assert abs(cpi - 0.857143) < 0.001, f"Expected ≈0.857, got {cpi}"

    def test_spi_standard_case(self) -> None:
        # EV=600, PV=800 → SPI = 0.75
        ev, pv = _d(600), _d(800)
        spi = compute_spi(ev, pv)
        assert spi is not None
        assert abs(spi - 0.75) < 0.0001

    def test_cpi_perfect_performance(self) -> None:
        # EV == AC → CPI = 1.0
        ev = ac = _d(500)
        assert compute_cpi(ev, ac) == 1.0

    def test_spi_on_schedule(self) -> None:
        # EV == PV → SPI = 1.0
        ev = pv = _d(300)
        assert compute_spi(ev, pv) == 1.0

    def test_cpi_returns_none_when_ac_zero(self) -> None:
        """CPI is undefined when no actual cost has been incurred yet."""
        cpi = compute_cpi(_d(0), _d(0))
        assert cpi is None, "CPI must be None, not raise, when AC=0"

    def test_spi_returns_none_when_pv_zero(self) -> None:
        """SPI is undefined before any work was planned."""
        spi = compute_spi(_d(100), _d(0))
        assert spi is None, "SPI must be None, not raise, when PV=0"

    def test_cpi_over_budget(self) -> None:
        # AC > EV → CPI < 1.0 (over budget)
        ev, ac = _d(400), _d(600)
        cpi = compute_cpi(ev, ac)
        assert cpi is not None and cpi < 1.0

    def test_cpi_under_budget(self) -> None:
        # EV > AC → CPI > 1.0 (under budget)
        ev, ac = _d(600), _d(400)
        cpi = compute_cpi(ev, ac)
        assert cpi is not None and cpi > 1.0

    def test_spi_ahead_of_schedule(self) -> None:
        # EV > PV → SPI > 1.0
        ev, pv = _d(800), _d(600)
        spi = compute_spi(ev, pv)
        assert spi is not None and spi > 1.0

    def test_cpi_ev_zero_ac_nonzero(self) -> None:
        # No earned value yet but actuals spent → CPI = 0.0 (not None)
        cpi = compute_cpi(_d(0), _d(200))
        assert cpi == 0.0


class TestVariances:
    """Cost and Schedule Variance."""

    def test_sv_negative_behind_schedule(self) -> None:
        sv = compute_sv(_d(600), _d(800))
        assert sv == _d(-200)

    def test_sv_positive_ahead_of_schedule(self) -> None:
        sv = compute_sv(_d(800), _d(600))
        assert sv == _d(200)

    def test_sv_zero_on_schedule(self) -> None:
        assert compute_sv(_d(500), _d(500)) == _d(0)

    def test_cv_negative_over_budget(self) -> None:
        cv = compute_cv(_d(600), _d(700))
        assert cv == _d(-100)

    def test_cv_positive_under_budget(self) -> None:
        cv = compute_cv(_d(700), _d(600))
        assert cv == _d(100)

    def test_cv_zero_on_budget(self) -> None:
        assert compute_cv(_d(500), _d(500)) == _d(0)


class TestEACFormulas:
    """Three EAC formula variants plus ETC and VAC."""

    def test_eac1_canonical_case(self) -> None:
        # BAC=1000, EV=600, AC=700 → CPI=0.857 → EAC₁ = 1000/0.857 ≈ 1166.67
        bac, ev, ac = _d(1000), _d(600), _d(700)
        cpi = compute_cpi(ev, ac)
        eac = compute_eac_cpi(bac, cpi)
        assert eac is not None
        assert abs(float(eac) - 1166.67) < 0.01, f"Got {eac}"

    def test_eac2_remaining_estimate(self) -> None:
        # EAC₂ = AC + (BAC - EV) = 700 + (1000 - 600) = 1100
        bac, ev, ac = _d(1000), _d(600), _d(700)
        eac = compute_eac_remaining(ac, bac, ev)
        assert eac == _d(1100)

    def test_eac3_combined_factors(self) -> None:
        # BAC=1000, EV=600, AC=700, PV=800
        # CPI=0.857, SPI=0.75 → EAC₃ = 700 + 400/(0.857×0.75)
        bac, ev, ac, pv = _d(1000), _d(600), _d(700), _d(800)
        cpi = compute_cpi(ev, ac)
        spi = compute_spi(ev, pv)
        eac = compute_eac_combined(ac, bac, ev, cpi, spi)
        assert eac is not None
        expected = 700 + 400 / (0.857143 * 0.75)
        assert abs(float(eac) - expected) < 0.05, f"Got {eac}"

    def test_eac1_none_when_cpi_none(self) -> None:
        # AC=0 → CPI=None → EAC₁=None
        bac, ev, ac = _d(1000), _d(0), _d(0)
        cpi = compute_cpi(ev, ac)
        assert compute_eac_cpi(bac, cpi) is None

    def test_eac3_none_when_spi_none(self) -> None:
        # PV=0 → SPI=None → EAC₃=None
        bac, ev, ac, pv = _d(1000), _d(300), _d(350), _d(0)
        cpi = compute_cpi(ev, ac)
        spi = compute_spi(ev, pv)
        assert compute_eac_combined(ac, bac, ev, cpi, spi) is None

    def test_eac1_zero_bac(self) -> None:
        # BAC=0 → EAC₁=0 (CPI may be defined)
        cpi = compute_cpi(_d(50), _d(50))  # CPI=1.0
        eac = compute_eac_cpi(_d(0), cpi)
        assert eac == _d(0)

    def test_etc_from_eac1(self) -> None:
        # ETC = EAC - AC
        bac, ev, ac = _d(1000), _d(600), _d(700)
        cpi = compute_cpi(ev, ac)
        eac = compute_eac_cpi(bac, cpi)
        etc = compute_etc(eac, ac)
        assert etc is not None
        assert abs(float(etc) - (float(eac) - 700)) < 0.01  # type: ignore[arg-type]

    def test_vac_negative_over_budget(self) -> None:
        # VAC = BAC - EAC; when EAC > BAC → VAC < 0
        bac, ev, ac = _d(1000), _d(600), _d(700)
        cpi = compute_cpi(ev, ac)
        eac = compute_eac_cpi(bac, cpi)
        vac = compute_vac(bac, eac)
        assert vac is not None and vac < 0

    def test_eac_and_vac_on_budget_project(self) -> None:
        # Perfect project: EV=AC=PV → CPI=SPI=1.0 → EAC=BAC → VAC=0
        bac = ev = ac = pv = _d(500)
        cpi = compute_cpi(ev, ac)
        spi = compute_spi(ev, pv)
        eac1 = compute_eac_cpi(bac, cpi)
        eac2 = compute_eac_remaining(ac, bac, ev)
        eac3 = compute_eac_combined(ac, bac, ev, cpi, spi)
        assert eac1 == bac
        assert eac2 == bac
        assert eac3 == bac
        vac = compute_vac(bac, eac1)
        assert vac == _d(0)

    def test_etc_none_when_eac_none(self) -> None:
        """ETC is undefined when EAC is undefined (e.g. CPI or SPI undefined)."""
        assert compute_etc(None, _d(200)) is None

    def test_vac_none_when_eac_none(self) -> None:
        """VAC is undefined when EAC is undefined."""
        assert compute_vac(_d(1000), None) is None


class TestEdgeCases:
    """Boundary conditions that must not raise exceptions."""

    def test_negative_ev_treated_as_reversal(self) -> None:
        # Negative EV is unusual but must not crash; CPI may go negative.
        cpi = compute_cpi(_d(-100), _d(200))
        assert cpi is not None and cpi < 0

    def test_eac2_ev_exceeds_bac(self) -> None:
        # EV > BAC is possible after scope changes; remaining = BAC - EV < 0.
        bac, ev, ac = _d(1000), _d(1200), _d(900)
        eac = compute_eac_remaining(ac, bac, ev)
        # = 900 + (1000 - 1200) = 900 - 200 = 700
        assert eac == _d(700)

    def test_cpi_very_small_ac(self) -> None:
        # Avoid floating-point overflow; small AC is fine.
        ev = _d("0.01")
        ac = _d("0.001")
        cpi = compute_cpi(ev, ac)
        assert cpi is not None and abs(cpi - 10.0) < 0.001

    def test_all_zeros_no_crash(self) -> None:
        """All inputs zero must not raise."""
        bac = ev = ac = pv = _d(0)
        cpi = compute_cpi(ev, ac)
        spi = compute_spi(ev, pv)
        assert cpi is None
        assert spi is None
        assert compute_sv(ev, pv) == _d(0)
        assert compute_cv(ev, ac) == _d(0)
        assert compute_eac_cpi(bac, cpi) is None
        assert compute_eac_remaining(ac, bac, ev) == _d(0)
        assert compute_eac_combined(ac, bac, ev, cpi, spi) is None

    def test_decimal_string_money_roundtrip(self) -> None:
        """Money values stored as String(20) → Decimal roundtrip is lossless."""
        stored = "123456789.99"  # String(20) column value
        recovered = _d(stored)
        assert str(recovered) == stored

    def test_decimal_string_precision_preserved(self) -> None:
        """Decimal-string format does not lose precision through float coercion."""
        # This would lose precision if we naively used float().
        precise = _d("999999999.12")
        assert precise == Decimal("999999999.12")

    def test_cpi_spi_are_floats_not_decimal(self) -> None:
        """CPI and SPI are floats (dimensionless ratios), not Decimal."""
        cpi = compute_cpi(_d(600), _d(700))
        spi = compute_spi(_d(600), _d(800))
        assert isinstance(cpi, float), f"CPI should be float, got {type(cpi)}"
        assert isinstance(spi, float), f"SPI should be float, got {type(spi)}"

    def test_money_fields_are_decimal_not_float(self) -> None:
        """EAC, ETC, VAC, SV, CV are Decimal (money precision), not float."""
        bac, ev, ac = _d(1000), _d(600), _d(700)
        eac2 = compute_eac_remaining(ac, bac, ev)
        sv = compute_sv(ev, _d(800))
        cv = compute_cv(ev, ac)
        assert isinstance(eac2, Decimal), f"EAC₂ should be Decimal, got {type(eac2)}"
        assert isinstance(sv, Decimal), f"SV should be Decimal, got {type(sv)}"
        assert isinstance(cv, Decimal), f"CV should be Decimal, got {type(cv)}"
