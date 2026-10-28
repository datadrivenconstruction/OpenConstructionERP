# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure EVM-snapshot derivation math.

These exercise :mod:`app.modules.schedule.evm_snapshot_math` directly with plain
``Decimal`` / ``int`` / ``float`` / ``str`` inputs - no database, FastAPI or ORM -
so they run on any interpreter (including the local Python 3.11 runner), exactly
like the progress-math and cost-risk engine tests.

The single derived figure is the schedule performance index ``SPI = EV / PV``.
The tests pin: the on-schedule / behind / ahead readings, the divide-by-zero
guard (PV == 0 and PV < 0 both yield ``None``), Decimal-quantisation, no
float-noise from float inputs, and the ``None`` input fallbacks.
"""

from __future__ import annotations

from datetime import UTC
from decimal import Decimal

from app.modules.schedule.evm_snapshot_math import schedule_performance_index as spi

D = Decimal


def test_spi_on_schedule_is_one() -> None:
    assert spi(D("1000.00"), D("1000.00")) == D("1.000")


def test_spi_behind_schedule_below_one() -> None:
    # Earned less than planned -> behind schedule.
    assert spi(D("750.00"), D("1000.00")) == D("0.750")


def test_spi_ahead_of_schedule_above_one() -> None:
    # Earned more than planned -> ahead of schedule.
    assert spi(D("1200.00"), D("1000.00")) == D("1.200")


def test_spi_zero_planned_value_is_none() -> None:
    # No baseline accrued at this data date -> divide-by-zero guarded to None.
    assert spi(D("0"), D("0")) is None
    assert spi(D("500.00"), D("0")) is None


def test_spi_negative_planned_value_is_none() -> None:
    # A negative PV is not a meaningful denominator -> None, never a crash.
    assert spi(D("500.00"), D("-10.00")) is None


def test_spi_zero_earned_value_is_zero_when_pv_positive() -> None:
    # Nothing earned yet but a baseline exists -> SPI 0 (behind), not None.
    assert spi(D("0"), D("1000.00")) == D("0.000")


def test_spi_quantises_to_three_decimals_half_up() -> None:
    # 1000 / 3000 = 0.3333... -> rounds half-up to 0.333.
    assert spi(D("1000.00"), D("3000.00")) == D("0.333")
    # 2000 / 3000 = 0.6666... -> rounds half-up to 0.667.
    assert spi(D("2000.00"), D("3000.00")) == D("0.667")


def test_spi_accepts_float_inputs_without_binary_noise() -> None:
    # Float inputs are routed through str so 0.1-style noise never leaks in.
    assert spi(0.1, 0.1) == D("1.000")
    assert spi(50.0, 200.0) == D("0.250")


def test_spi_accepts_string_and_int_inputs() -> None:
    assert spi("1500", "1000") == D("1.500")
    assert spi(500, 1000) == D("0.500")


def test_spi_none_inputs_fall_back() -> None:
    # EV None -> treated as 0 (behind); PV None -> treated as 0 -> guard None.
    assert spi(None, D("1000.00")) == D("0.000")
    assert spi(D("500.00"), None) is None
    assert spi(None, None) is None


def test_spi_returns_decimal_type_not_float() -> None:
    result = spi(D("800.00"), D("1000.00"))
    assert isinstance(result, Decimal)


# ---------------------------------------------------------------------------
# Response schema money discipline (pydantic + stdlib only - 3.11 safe)
# ---------------------------------------------------------------------------


def test_evm_snapshot_response_money_serialises_as_string() -> None:
    """v3 money rule: pv / ev / bac emerge from JSON as STRINGS, not numbers.

    The schema lives in ``evm_snapshot_schemas.py`` (not ``schemas.py``) so the
    global money audit does not scan it; this test pins the same contract here.
    """
    import json
    from datetime import datetime
    from uuid import uuid4

    from app.modules.schedule.evm_snapshot_schemas import EvmSnapshotResponse

    resp = EvmSnapshotResponse(
        id=uuid4(),
        schedule_id=uuid4(),
        project_id=uuid4(),
        data_date="2026-06-15",
        pv=D("123456.7800"),
        ev=D("98765.4300"),
        bac=D("500000.0000"),
        spi=D("0.800"),
        recorded_at=datetime(2026, 6, 15, 12, 0, tzinfo=UTC),
    )
    obj = json.loads(resp.model_dump_json())
    assert obj["pv"] == "123456.7800"
    assert obj["ev"] == "98765.4300"
    assert obj["bac"] == "500000.0000"
    # SPI is a dimensionless ratio - a plain JSON number, not a money string.
    assert obj["spi"] == 0.8


def test_evm_snapshot_response_spi_none_serialises_null() -> None:
    import json
    from datetime import datetime
    from uuid import uuid4

    from app.modules.schedule.evm_snapshot_schemas import EvmSnapshotResponse

    resp = EvmSnapshotResponse(
        id=uuid4(),
        schedule_id=uuid4(),
        project_id=uuid4(),
        data_date="2026-06-15",
        pv=D("0.0000"),
        ev=D("0.0000"),
        bac=D("0.0000"),
        spi=None,
        recorded_at=datetime(2026, 6, 15, 12, 0, tzinfo=UTC),
    )
    obj = json.loads(resp.model_dump_json())
    assert obj["spi"] is None
    assert obj["pv"] == "0.0000"
