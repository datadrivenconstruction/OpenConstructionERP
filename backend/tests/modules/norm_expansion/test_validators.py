"""The norm_expansion rule set warns about norms that expand into nothing or twice."""

import pytest

from app.core.validation.engine import ValidationContext
from app.modules.norm_expansion.validators import MaterialQuantityPositive, NoDuplicateMaterial, NormHasDemand


def _ctx(norm):
    return ValidationContext(data={"norm": norm})


def _norm(**kw):
    base = {"work_key": "plaster", "labor_hours_per_unit": "0.4", "machine_hours_per_unit": "0", "materials": []}
    base.update(kw)
    return base


@pytest.mark.asyncio
async def test_empty_norm_warns_and_a_real_one_passes():
    (bad,) = await NormHasDemand().validate(_ctx(_norm(labor_hours_per_unit="0")))
    (good,) = await NormHasDemand().validate(_ctx(_norm()))
    assert not bad.passed
    assert good.passed


@pytest.mark.asyncio
async def test_material_with_no_quantity_warns():
    mats = [{"name": "Gypsum", "unit": "kg", "qty_per_unit": "0"}]
    (res,) = await MaterialQuantityPositive().validate(_ctx(_norm(materials=mats)))
    assert not res.passed
    assert res.details["materials"] == ["Gypsum"]


@pytest.mark.asyncio
async def test_same_material_twice_warns_but_other_unit_does_not():
    twice = [{"name": "Sand", "unit": "t", "qty_per_unit": "1"}, {"name": "sand ", "unit": "t", "qty_per_unit": "2"}]
    units = [{"name": "Sand", "unit": "t", "qty_per_unit": "1"}, {"name": "Sand", "unit": "m3", "qty_per_unit": "2"}]
    (dup,) = await NoDuplicateMaterial().validate(_ctx(_norm(materials=twice)))
    (ok,) = await NoDuplicateMaterial().validate(_ctx(_norm(materials=units)))
    assert not dup.passed
    assert ok.passed
