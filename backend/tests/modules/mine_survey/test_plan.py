# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Blast block outlines from design collars."""

from __future__ import annotations

import pytest

from app.modules.mine_survey.plan import block_outline, convex_hull, hole_spacing


def test_block_outline_is_the_hull_pushed_out_by_half_the_spacing() -> None:
    collars = [(float(x), float(y)) for x in range(0, 16, 4) for y in range(0, 10, 3)]
    ring, spacing = block_outline(collars)
    assert spacing == pytest.approx(3.0)
    xs, ys = [p[0] for p in ring], [p[1] for p in ring]
    assert min(xs) == pytest.approx(-1.5) and max(xs) == pytest.approx(13.5)
    assert min(ys) == pytest.approx(-1.5) and max(ys) == pytest.approx(10.5)


def test_hull_drops_inner_holes() -> None:
    assert len(convex_hull([(0, 0), (10, 0), (10, 10), (0, 10), (5, 5)])) == 4
    assert hole_spacing([(0, 0)]) == 0.0
