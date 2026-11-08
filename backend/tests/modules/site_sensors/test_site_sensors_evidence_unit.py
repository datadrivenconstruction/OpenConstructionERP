# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Sensor evidence: the CSV, its SHA-256, the summary, the PDF and the rules that check them."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.register_export import ProjectHeader, build_register_pdf
from app.modules.site_sensors import evidence
from app.modules.site_sensors.schemas import DeviceCreate, StripCreate
from app.modules.site_sensors.validators import run_rules

T0 = datetime(2026, 10, 20, 8, tzinfo=UTC)
DEVICE = SimpleNamespace(code="VB-01", name="North boundary", kind="vibration", unit="mm/s")


def _raw(n: int, start: float = 1.0) -> list[tuple[datetime, float]]:
    return [(T0 + timedelta(minutes=i), start + i % 5) for i in range(n)]


def test_csv_lists_every_reading_in_time_order_with_a_header() -> None:
    hourly = [{"hour": T0 - timedelta(hours=1), "n": 60, "min": 0.5, "max": 2.5, "avg": 1.25}]
    data = evidence.readings_csv([(T0 + timedelta(minutes=1), 3.5), (T0, 2.0)], hourly)
    rows = list(csv.reader(io.StringIO(data.decode())))
    assert rows[0] == list(evidence.CSV_COLUMNS)
    assert [r[1] for r in rows[1:]] == ["hourly", "raw", "raw"]
    assert rows[1] == ["2026-10-20T07:00:00Z", "hourly", "1.25", "0.5", "2.5", "60"]
    assert rows[3][:3] == ["2026-10-20T08:01:00Z", "raw", "3.5"]


def test_the_hash_is_stable_and_one_changed_reading_changes_it() -> None:
    a = evidence.readings_csv(_raw(10), [])
    b = evidence.readings_csv(_raw(10), [])
    assert evidence.sha256_hex(a) == evidence.sha256_hex(b)
    assert len(evidence.sha256_hex(a)) == 64
    changed = _raw(10)
    changed[4] = (changed[4][0], 99.0)
    assert evidence.sha256_hex(evidence.readings_csv(changed, [])) != evidence.sha256_hex(a)
    assert evidence.sha256_hex(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_summary_weights_folded_hours_by_their_reading_count() -> None:
    hourly = [{"hour": T0, "n": 3, "min": 1.0, "max": 4.0, "avg": 2.0}]
    s = evidence.summarise([(T0, 6.0)], hourly)
    assert (s["count"], s["min"], s["max"]) == (4, 1.0, 6.0)
    assert s["mean"] == pytest.approx(3.0)
    assert evidence.summarise([], []) == {"count": 0, "min": None, "max": None, "mean": None}


def test_hourly_summaries_fold_minutes_into_hours() -> None:
    folded = evidence.hourly_summaries(_raw(130))
    assert [h["n"] for h in folded] == [60, 60, 10]
    assert folded[0]["hour"] == T0


def test_a_window_must_run_forward_and_stay_within_a_year() -> None:
    with pytest.raises(evidence.EvidenceError, match="window_reversed"):
        evidence.check_window(T0, T0)
    with pytest.raises(evidence.EvidenceError, match="window_too_long"):
        evidence.check_window(T0, T0 + timedelta(days=367))
    start, end = evidence.check_window(datetime(2026, 10, 20), datetime(2026, 10, 21))
    assert start.tzinfo is UTC and end - start == timedelta(days=1)


@pytest.mark.parametrize("n", [5, evidence.PDF_RAW_ROW_LIMIT + 50])
def test_the_pdf_renders_both_a_short_series_and_an_hourly_summary(n: int) -> None:
    raw = _raw(n)
    csv_digest = evidence.sha256_hex(evidence.readings_csv(raw, []))
    doc = evidence.evidence_register(
        device=DEVICE,
        limit=8.0,
        start=T0,
        end=T0 + timedelta(days=1),
        raw=raw,
        hourly=[],
        exceedances=2,
        csv_digest=csv_digest,
        project=ProjectHeader(name="Harbour Quay", country="DE"),
    )
    assert len(doc.rows) == (n if n <= evidence.PDF_RAW_ROW_LIMIT else -(-n // 60))
    assert any(csv_digest in "".join(value.split()) for _, value in doc.details)
    assert build_register_pdf(doc).startswith(b"%PDF")


async def test_evidence_rule_wants_a_sha256_readings_and_both_documents() -> None:
    good = {"id": "e1", "device": "VB-01", "sha256": "a" * 64, "readings": 12, "filed": True}
    bad = [
        {**good, "id": "e2", "sha256": "xyz"},
        {**good, "id": "e3", "readings": 0},
        {**good, "id": "e4", "filed": False},
        {**good, "id": "e5", "sha256": "A" * 64},
    ]
    results = [r for r in await run_rules({"evidence": [good, *bad]}) if r["rule_id"] == "site_sensors.evidence_hashed"]
    assert {r["element_ref"]: r["passed"] for r in results} == {
        "e1": True,
        "e2": False,
        "e3": False,
        "e4": False,
        "e5": False,
    }


async def test_bim_rule_flags_an_element_without_its_model() -> None:
    rows = [
        {"id": "d1", "label": "VB-01", "model_id": "m1", "element_id": "x"},
        {"id": "d2", "label": "VB-02", "model_id": None, "element_id": "y"},
    ]
    results = [r for r in await run_rules({"bim_links": rows}) if r["rule_id"] == "site_sensors.bim_link_complete"]
    assert [(r["element_ref"], r["passed"]) for r in results] == [("d1", True), ("d2", False)]


def test_an_element_link_is_refused_without_a_model() -> None:
    import uuid

    pid, eid = uuid.uuid4(), uuid.uuid4()
    with pytest.raises(ValidationError, match="bim_element_needs_model"):
        DeviceCreate(project_id=pid, code="X", kind="noise", bim_element_id=eid)
    with pytest.raises(ValidationError, match="bim_element_needs_model"):
        StripCreate(device_id=pid, bim_element_id=eid)
    assert DeviceCreate(project_id=pid, code="X", kind="noise", bim_model_id=uuid.uuid4(), bim_element_id=eid)
