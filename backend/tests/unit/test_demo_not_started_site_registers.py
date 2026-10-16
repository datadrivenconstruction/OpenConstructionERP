# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A demo site that has not started gets no generic RFIs or safety incidents.

The Ludwigsburg school waits for its construction gate, yet its hub showed open RFIs to
contractors and open safety incidents, written by the generic seeder for every template.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.core import demo_projects
from app.core.demo_showcase import NOT_STARTED_SITE_DEMO_IDS, generic_site_rows

ROWS = [{"rfi_number": "RFI-001", "status": "open"}]


def test_the_school_that_has_not_started_gets_no_generic_site_rows() -> None:
    assert "school-ludwigsburg" in NOT_STARTED_SITE_DEMO_IDS
    assert generic_site_rows("school-ludwigsburg", ROWS) == []


def test_a_running_site_keeps_its_generic_rows() -> None:
    assert "residential-regensburg" not in NOT_STARTED_SITE_DEMO_IDS
    assert generic_site_rows("residential-regensburg", ROWS) == ROWS


def test_the_rfi_and_incident_seeders_read_through_the_filter() -> None:
    src = Path(demo_projects.__file__).read_text(encoding="utf-8")
    assert re.search(r'rfi_list = _RFIS\.get\(demo_id\) or generic_site_rows\(demo_id, generated\.get\("rfis"', src)
    assert re.search(
        r'incident_list = _SAFETY_INCIDENTS\.get\(demo_id\) or generic_site_rows\(\s*demo_id, generated\.get\("safety_incidents"',
        src,
    )
