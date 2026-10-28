# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure-logic unit tests for the Gap I progress-claim bridge helpers.

Covers the side-effect-free helpers that back the bridge service:

* ``boq_position_id_for_line`` — extracting the BOQ-position link from a SoV
  line's metadata (string UUID, real UUID, missing, malformed).
* ``compute_progress_claim_line`` — deriving one claim line's figures from a
  contract line + observed percent, with clamping, value override and the
  "never exceed the contract line value" guard.

These run without a database (SimpleNamespace stubs), so they are fast and
deterministic. The DB-backed behaviour (preview / commit / idempotency /
events / project isolation) lives in
``tests/modules/test_contracts_progress_bridge_db.py``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

from app.modules.contracts.service import (
    BOQ_POSITION_META_KEY,
    boq_position_id_for_line,
    compute_progress_claim_line,
)


def _line(
    *,
    quantity: str = "0",
    unit_rate: str = "0",
    total_value: str = "0",
    metadata: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        quantity=Decimal(quantity),
        unit_rate=Decimal(unit_rate),
        total_value=Decimal(total_value),
        metadata_=metadata if metadata is not None else {},
    )


# ── boq_position_id_for_line ──────────────────────────────────────────────


def test_boq_link_string_uuid() -> None:
    pos = uuid.uuid4()
    line = _line(metadata={BOQ_POSITION_META_KEY: str(pos)})
    assert boq_position_id_for_line(line) == pos


def test_boq_link_real_uuid() -> None:
    pos = uuid.uuid4()
    line = _line(metadata={BOQ_POSITION_META_KEY: pos})
    assert boq_position_id_for_line(line) == pos


def test_boq_link_missing_returns_none() -> None:
    assert boq_position_id_for_line(_line(metadata={})) is None
    assert boq_position_id_for_line(_line(metadata={"other": "x"})) is None


def test_boq_link_blank_returns_none() -> None:
    assert boq_position_id_for_line(_line(metadata={BOQ_POSITION_META_KEY: ""})) is None
    assert boq_position_id_for_line(_line(metadata={BOQ_POSITION_META_KEY: None})) is None


def test_boq_link_malformed_returns_none() -> None:
    line = _line(metadata={BOQ_POSITION_META_KEY: "not-a-uuid"})
    assert boq_position_id_for_line(line) is None


def test_boq_link_non_dict_metadata_returns_none() -> None:
    line = SimpleNamespace(id=uuid.uuid4(), metadata_=["bad"])
    assert boq_position_id_for_line(line) is None


# ── compute_progress_claim_line ───────────────────────────────────────────


def test_claim_line_basic_percent() -> None:
    line = _line(quantity="10", unit_rate="100", total_value="1000")
    out = compute_progress_claim_line(line, Decimal("40"))
    assert out["period_completed_value"] == Decimal("400.0000")
    assert out["period_completed_qty"] == Decimal("4.0000")
    assert out["period_completed_pct"] == Decimal("40.0000")
    assert out["cumulative_completed_value"] == Decimal("400.0000")


def test_claim_line_decimal_precision_no_float() -> None:
    line = _line(quantity="3", unit_rate="33.33", total_value="99.99")
    out = compute_progress_claim_line(line, Decimal("33.333"))
    # All outputs are Decimal, never float.
    for v in out.values():
        assert isinstance(v, Decimal)
    # 99.99 * 33.333 / 100 = 33.3296667 -> quantized to 4 dp
    assert out["period_completed_value"] == Decimal("33.3297")


def test_claim_line_clamps_percent_above_100() -> None:
    line = _line(total_value="500", quantity="5")
    out = compute_progress_claim_line(line, Decimal("150"))
    assert out["period_completed_pct"] == Decimal("100.0000")
    assert out["period_completed_value"] == Decimal("500.0000")


def test_claim_line_clamps_negative_percent_to_zero() -> None:
    line = _line(total_value="500")
    out = compute_progress_claim_line(line, Decimal("-20"))
    assert out["period_completed_pct"] == Decimal("0.0000")
    assert out["period_completed_value"] == Decimal("0.0000")


def test_claim_line_value_override_used() -> None:
    line = _line(total_value="1000")
    out = compute_progress_claim_line(line, Decimal("50"), value_override=Decimal("321"))
    assert out["period_completed_value"] == Decimal("321")
    assert out["cumulative_completed_value"] == Decimal("321")


def test_claim_line_value_override_clamped_to_line_value() -> None:
    # A tampered override above the contract line value cannot inflate the claim.
    line = _line(total_value="1000")
    out = compute_progress_claim_line(line, Decimal("50"), value_override=Decimal("99999"))
    assert out["period_completed_value"] == Decimal("1000")


def test_claim_line_negative_override_clamped_to_zero() -> None:
    line = _line(total_value="1000")
    out = compute_progress_claim_line(line, Decimal("50"), value_override=Decimal("-5"))
    assert out["period_completed_value"] == Decimal("0")
