# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Survey arithmetic against the DOMAIN.md worked example 2 (closed traverse)."""

from __future__ import annotations

import pytest

from app.modules.survey_core.survey_math import (
    bowditch_correction,
    level_allowed_mm,
    linear_misclosure,
    misclosure_ratio,
    same_position,
)


def test_traverse_misclosure_is_the_hypotenuse_of_its_components() -> None:
    assert linear_misclosure(0.042, -0.031) == pytest.approx(0.0522, abs=5e-5)


def test_traverse_ratio_is_length_over_misclosure() -> None:
    # L = 612.40 m, f = 0.05220 m -> 1:11,731 (rounding f to 0.0522 first gives 11,732).
    assert misclosure_ratio(612.40, linear_misclosure(0.042, -0.031)) == 11731


def test_ratio_of_a_perfect_closure_is_unbounded() -> None:
    assert misclosure_ratio(612.40, 0.0) is None


def test_bowditch_correction_on_the_158_m_leg() -> None:
    c_e, c_n = bowditch_correction(0.042, -0.031, 158.30, 612.40)
    assert round(c_e, 4) == -0.0109
    assert round(c_n, 4) == 0.0080


def test_bowditch_rejects_a_zero_length_traverse() -> None:
    with pytest.raises(ValueError):
        bowditch_correction(0.01, 0.01, 10.0, 0.0)


def test_level_allowance_grows_with_the_root_of_the_distance() -> None:
    assert level_allowed_mm(12.0, 2.25) == pytest.approx(18.0)


def test_same_position_uses_a_millimetre_tolerance() -> None:
    assert same_position((389000.0, 5819040.0, 34.0), (389000.0004, 5819040.0, 34.0))
    assert not same_position((389000.0, 5819040.0, 34.0), (389000.5, 5819040.0, 34.0))
    assert not same_position((1.0, 2.0, None), (1.0, 2.0, 3.0))
