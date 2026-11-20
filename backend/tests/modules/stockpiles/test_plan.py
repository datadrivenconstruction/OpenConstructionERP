# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A stockpile on the plan: toe and crest of a cone over a flat base."""

from __future__ import annotations

import math

import numpy as np
import pytest

from app.modules.stockpiles.plan import CREST_SHARE, TOE_HEIGHT_M, pile_outline
from app.modules.surfaces_volumes.tin import Tin


def _cone(height: float = 5.0, radius: float = 10.0) -> tuple[Tin, Tin]:
    xs = np.linspace(-15, 15, 61)
    e, n = np.meshgrid(xs, xs)
    e, n = e.ravel(), n.ravel()
    r = np.hypot(e, n)
    pile = Tin.from_points(e, n, 100.0 + np.maximum(height * (1 - r / radius), 0.0))
    base = Tin.from_points(e, n, np.full(len(e), 100.0))
    return pile, base


def test_toe_and_crest_of_a_cone_are_circles() -> None:
    out = pile_outline(*_cone())
    assert out.max_height_m == pytest.approx(5.0, abs=0.15)
    toe_r = [math.hypot(x, y) for x, y in out.toe]
    crest_r = [math.hypot(x, y) for x, y in out.crest]
    # Toe at 0.1 m above the base: r = 10 * (1 - 0.1 / 5) = 9.8 m.
    assert np.mean(toe_r) == pytest.approx(10 * (1 - TOE_HEIGHT_M / 5.0), abs=0.3)
    assert np.mean(crest_r) == pytest.approx(10 * (1 - CREST_SHARE * out.max_height_m / 5.0), abs=0.3)
    assert out.footprint_m2 == pytest.approx(math.pi * 9.8**2, rel=0.05)
    assert out.heat is not None and out.heat["nx"] * out.heat["ny"] == len(out.heat["dh"])


def test_no_pile_gives_no_outline() -> None:
    _, base = _cone()
    out = pile_outline(base, base)
    assert out.toe == [] and out.crest == []
