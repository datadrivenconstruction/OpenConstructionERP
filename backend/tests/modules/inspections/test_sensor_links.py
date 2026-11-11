"""Formwork strike release inspections: checklist prefill and the early exits."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.modules.inspections import sensor_links


def _by_id(lines):
    return {line["id"]: line for line in lines}


def test_checklist_has_three_critical_unanswered_lines():
    lines = sensor_links.build_checklist(strength=22.5, target=20, age_hours=71.6, min_temp_c=4.0)
    assert [line["id"] for line in lines] == ["strength", "age", "temperature"]
    for line in lines:
        assert line["critical"] is True
        assert line["response"] is None
        assert line["response_type"] == "yes_no"
        assert line["question_key"].startswith("inspections.strike_release.")
    notes = _by_id(lines)
    assert notes["strength"]["notes"] == "22.5 MPa / 20 MPa"
    assert notes["age"]["notes"] == "72 h"
    assert notes["temperature"]["notes"] == "min 4 degC"


def test_checklist_marks_missing_readings():
    lines = _by_id(sensor_links.build_checklist(strength=None, target=25.5, age_hours=None, min_temp_c=None))
    assert lines["strength"]["notes"] == "- / 25.5 MPa"
    assert lines["age"]["notes"] == "-"
    assert lines["temperature"]["notes"] == "-"


def test_uuid_and_aware_helpers():
    u = uuid.uuid4()
    assert sensor_links._uuid(str(u)) == u
    assert sensor_links._uuid(None) is None
    assert sensor_links._uuid("nope") is None
    from datetime import UTC, datetime

    naive = datetime(2026, 1, 1, 12, 0)
    assert sensor_links._aware(naive).tzinfo is UTC
    aware = datetime(2026, 1, 1, tzinfo=UTC)
    assert sensor_links._aware(aware) is aware


class _Session:
    def __init__(self, strip=None):
        self.strip = strip
        self.gets = 0

    async def get(self, model, key):
        self.gets += 1
        return self.strip


@pytest.mark.asyncio
async def test_strike_inspection_ignores_bad_payload_without_touching_db():
    session = _Session()
    assert await sensor_links.create_strike_inspection(session, {}) is None
    assert (
        await sensor_links.create_strike_inspection(session, {"strip_id": "x", "project_id": str(uuid.uuid4())}) is None
    )
    assert session.gets == 0


@pytest.mark.asyncio
async def test_strike_inspection_refuses_unknown_or_foreign_strip():
    data = {"strip_id": str(uuid.uuid4()), "project_id": str(uuid.uuid4())}
    assert await sensor_links.create_strike_inspection(_Session(None), data) is None
    foreign = SimpleNamespace(project_id=uuid.uuid4())
    assert await sensor_links.create_strike_inspection(_Session(foreign), data) is None
