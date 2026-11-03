"""Each survey rule fires on bad input and stays quiet on good input."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.modules.geo_hub.validators import evaluate

TODAY = date(2026, 6, 15)


def _cap(**over):
    base = {
        "id": "c1",
        "kind": "orthophoto",
        "captured_on": TODAY,
        "today": TODAY,
        "project_start": "2026-01-01",
        "project_end": "2026-12-31",
        "crs_epsg": 4326,
        "bbox": (13.40, 52.50, 13.41, 52.51),
        "anchor": {"lat": 52.505, "lon": 13.405},
        "gsd_cm": 3,
    }
    base.update(over)
    return {"capture": base}


async def _ids(data: dict) -> set[str]:
    return {r.rule_id for r in await evaluate(data)}


@pytest.mark.asyncio
async def test_clean_capture_has_no_findings() -> None:
    assert await _ids(_cap()) == set()


@pytest.mark.asyncio
async def test_future_date_is_an_error() -> None:
    results = await evaluate(_cap(captured_on=TODAY + timedelta(days=1)))
    hit = [r for r in results if r.rule_id == "geo_hub.survey.captured_on_not_future"]
    assert hit and hit[0].severity.value == "error"
    assert "future" in hit[0].message


@pytest.mark.asyncio
async def test_date_outside_project_window_warns() -> None:
    assert "geo_hub.survey.captured_on_in_project_window" in await _ids(_cap(captured_on=date(2025, 10, 1)))
    assert "geo_hub.survey.captured_on_in_project_window" in await _ids(
        _cap(captured_on=date(2027, 2, 15), today=date(2027, 3, 1))
    )
    # inside the 30 day margin is fine, and so is a project with no dates
    assert "geo_hub.survey.captured_on_in_project_window" not in await _ids(_cap(captured_on=date(2025, 12, 10)))
    assert "geo_hub.survey.captured_on_in_project_window" not in await _ids(_cap(project_start=None, project_end=None))


@pytest.mark.asyncio
async def test_orthophoto_without_georeference_warns_but_a_scan_does_not() -> None:
    assert "geo_hub.survey.georeferenced" in await _ids(_cap(crs_epsg=None, bbox=None))
    assert "geo_hub.survey.georeferenced" in await _ids(_cap(bbox=None))
    assert "geo_hub.survey.georeferenced" not in await _ids(_cap(kind="point_cloud", crs_epsg=None, bbox=None))


@pytest.mark.asyncio
async def test_footprint_far_from_anchor_warns() -> None:
    far = _cap(bbox=(2.30, 48.85, 2.31, 48.86))
    assert "geo_hub.survey.bbox_intersects_anchor" in await _ids(far)
    near = _cap(bbox=(13.43, 52.50, 13.44, 52.51))  # about 2 km east of the anchor
    assert "geo_hub.survey.bbox_intersects_anchor" not in await _ids(near)
    # no anchor or no bbox: nothing to compare
    assert "geo_hub.survey.bbox_intersects_anchor" not in await _ids(_cap(anchor=None))


@pytest.mark.asyncio
async def test_coarse_gsd_is_info() -> None:
    results = await evaluate(_cap(gsd_cm=25))
    hit = [r for r in results if r.rule_id == "geo_hub.survey.gsd_reasonable"]
    assert hit and hit[0].severity.value == "info"
    assert "geo_hub.survey.gsd_reasonable" not in await _ids(_cap(gsd_cm=10))


@pytest.mark.asyncio
@pytest.mark.parametrize("pct", [-0.01, 100.5, "abc", None])
async def test_observed_pct_out_of_range_is_an_error(pct) -> None:
    ids = await _ids({"observation": {"observed_pct": pct, "activity_in_project": True}})
    assert ids == {"geo_hub.survey.observed_pct_range"}


@pytest.mark.asyncio
@pytest.mark.parametrize("pct", [0, "0", 50, "100", 99.99])
async def test_observed_pct_in_range_passes(pct) -> None:
    assert await _ids({"observation": {"observed_pct": pct, "activity_in_project": True}}) == set()


@pytest.mark.asyncio
async def test_activity_from_another_project_is_an_error() -> None:
    ids = await _ids({"observation": {"observed_pct": 10, "activity_in_project": False}})
    assert ids == {"geo_hub.survey.observation_requires_activity_in_project"}
