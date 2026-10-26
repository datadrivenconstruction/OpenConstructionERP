"""Defect photo evidence: attach, pin, detach, and the rectified-defect rule."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException

from app.core.validation.engine import ValidationEngine, rule_registry
from app.modules.defects_liability.models import DlpDefect, DlpWarranty
from app.modules.defects_liability.service import DefectsLiabilityService
from app.modules.defects_liability.validators import DEFECT_EVIDENCE_RULE_SET, register_defects_liability_rules

pytestmark = pytest.mark.asyncio


async def _defect(session, project_id, **kw) -> DlpDefect:
    warranty = DlpWarranty(
        project_id=project_id,
        reference=f"W-{kw.get('reference', 'D-1')}",
        title="Roofing",
        warranty_type="defects_liability",
        status="active",
        warranty_start_date=date(2026, 1, 1),
        warranty_end_date=date(2027, 1, 1),
    )
    session.add(warranty)
    await session.flush()
    defect = DlpDefect(
        project_id=project_id,
        warranty_id=warranty.id,
        reference=kw.get("reference", "D-1"),
        description="Leak at parapet",
        status=kw.get("status", "open"),
        photos=[],
        geo_lat=kw.get("geo_lat"),
        geo_lon=kw.get("geo_lon"),
    )
    session.add(defect)
    await session.flush()
    return defect


def _entry(lat: float = 51.0, lon: float = 7.0) -> dict:
    return {
        "photo_id": "p1",
        "evidence": {"sha256": "ab", "location": {"lat": lat, "lon": lon, "accuracy_m": 8.0, "source": "device"}},
    }


async def test_photo_pins_an_unpinned_defect(session, project_id):
    defect = await _defect(session, project_id)
    service = DefectsLiabilityService(session)
    await service.add_photo(project_id, defect.id, _entry())
    assert defect.photos[0]["photo_id"] == "p1"
    assert (defect.geo_lat, defect.geo_lon) == (51.0, 7.0)


async def test_photo_keeps_an_existing_pin(session, project_id):
    defect = await _defect(session, project_id, geo_lat=1.0, geo_lon=2.0)
    await DefectsLiabilityService(session).add_photo(project_id, defect.id, _entry())
    assert (defect.geo_lat, defect.geo_lon) == (1.0, 2.0)


async def test_remove_photo_and_bad_index(session, project_id):
    defect = await _defect(session, project_id)
    service = DefectsLiabilityService(session)
    await service.add_photo(project_id, defect.id, _entry())
    removed = await service.remove_photo(project_id, defect.id, 0)
    assert removed["photo_id"] == "p1" and defect.photos == []
    with pytest.raises(HTTPException) as exc:
        await service.remove_photo(project_id, defect.id, 3)
    assert exc.value.status_code == 422


async def test_foreign_project_defect_is_not_found(session, project_id):
    import uuid

    defect = await _defect(session, project_id)
    with pytest.raises(HTTPException) as exc:
        await DefectsLiabilityService(session).add_photo(uuid.uuid4(), defect.id, _entry())
    assert exc.value.status_code == 404


async def test_rectified_defect_without_photo_warns():
    register_defects_liability_rules()
    data = {
        "defects": [
            {"id": "a", "reference": "D-1", "status": "closed", "photos": []},
            {"id": "b", "reference": "D-2", "status": "closed", "photos": [{"photo_id": "x"}]},
            {"id": "c", "reference": "D-3", "status": "open", "photos": []},
        ]
    }
    report = await ValidationEngine(rule_registry).validate(data=data, rule_sets=[DEFECT_EVIDENCE_RULE_SET])
    assert [(r.element_ref, r.passed) for r in report.results] == [("a", False), ("b", True)]
