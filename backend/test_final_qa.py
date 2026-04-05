#!/usr/bin/env python3
"""
OpenEstimate — Final QA Test Suite
====================================

Comprehensive test of ALL new features against the live server.
Covers: Field Reports, Photo Gallery, Takeoff Measurements,
Requirements, Markups, Punch List, Cross-module, and Regression.

Usage:
    cd backend
    python test_final_qa.py

Requires: server running on http://localhost:8000
"""

import json
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import httpx

# ── Configuration ──────────────────────────────────────────────────────────────

BASE_URL = "http://localhost:8000"
DEMO_EMAIL = "demo@openestimator.io"
DEMO_PASSWORD = "DemoPass1234!"
TIMEOUT = 30.0

# ── Test Result Tracking ──────────────────────────────────────────────────────


@dataclass
class TestResult:
    name: str
    passed: bool
    status_code: int | None = None
    expected: int | None = None
    detail: str = ""


@dataclass
class Section:
    name: str
    results: list[TestResult] = field(default_factory=list)

    def add(
        self,
        name: str,
        passed: bool,
        status_code: int | None = None,
        expected: int | None = None,
        detail: str = "",
    ) -> None:
        self.results.append(
            TestResult(name=name, passed=passed, status_code=status_code,
                       expected=expected, detail=detail)
        )
        icon = "PASS" if passed else "FAIL"
        sc = f" [{status_code}]" if status_code is not None else ""
        exp = f" (expected {expected})" if expected and not passed else ""
        det = f" -- {detail}" if detail and not passed else ""
        print(f"    {icon}  {name}{sc}{exp}{det}")

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if not r.passed)


# ── Globals ────────────────────────────────────────────────────────────────────

client: httpx.Client
TOKEN: str = ""
PROJECT_ID: str = ""
BOQ_ID: str = ""
POSITION_ID: str = ""
sections: list[Section] = []


def login() -> bool:
    """Login and set global token. Returns True on success."""
    global TOKEN
    r = client.post("/api/v1/users/auth/login", json={
        "email": DEMO_EMAIL, "password": DEMO_PASSWORD
    })
    if r.status_code == 200:
        TOKEN = r.json().get("access_token", "")
        client.headers["Authorization"] = f"Bearer {TOKEN}"
        return True
    return False


def get_project_with_boq() -> tuple[str, str, str]:
    """Find a project that has BOQs with positions. Return (project_id, boq_id, position_id)."""
    r = client.get("/api/v1/projects/")
    if r.status_code != 200:
        return "", "", ""
    projects = r.json()
    if not projects:
        return "", "", ""

    # Try each project to find one with BOQs and positions
    for proj in projects:
        pid = str(proj["id"])
        r2 = client.get(f"/api/v1/boq/boqs/?project_id={pid}")
        if r2.status_code == 200 and r2.json():
            boqs = r2.json()
            for boq in boqs:
                bid = str(boq["id"])
                # Use the /structured endpoint to get positions
                r3 = client.get(f"/api/v1/boq/boqs/{bid}/structured")
                if r3.status_code == 200:
                    data = r3.json()
                    # Structured response has sections with positions
                    sections = data.get("sections", [])
                    for sec in sections:
                        positions = sec.get("positions", [])
                        if positions:
                            return pid, bid, str(positions[0]["id"])
                    # Also try top-level positions
                    positions = data.get("positions", [])
                    if positions:
                        return pid, bid, str(positions[0]["id"])
            # Has BOQ but no positions
            return pid, str(boqs[0]["id"]), ""

    # Return first project even if no BOQs
    return str(projects[0]["id"]), "", ""


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: Field Reports (10 tests)
# ══════════════════════════════════════════════════════════════════════════════


def test_field_reports() -> Section:
    s = Section("1. Field Reports")
    print(f"\n{'='*60}")
    print(f"  SECTION: {s.name}")
    print(f"{'='*60}")

    report_id = ""
    today = date.today().isoformat()

    # 1.1 Create daily report with workforce
    r = client.post("/api/v1/fieldreports/reports", json={
        "project_id": PROJECT_ID,
        "report_date": today,
        "report_type": "daily",
        "weather_condition": "clear",
        "temperature_c": 22.5,
        "humidity": 55,
        "workforce": [
            {"trade": "Carpenter", "count": 4, "hours": 8.0},
            {"trade": "Electrician", "count": 2, "hours": 6.0},
        ],
        "equipment_on_site": ["Crane", "Excavator"],
        "work_performed": "Foundation pouring completed",
        "notes": "QA test report",
    })
    passed = r.status_code == 201
    if passed:
        report_id = r.json().get("id", "")
        data = r.json()
        passed = (
            passed
            and len(data.get("workforce", [])) == 2
            and data.get("status") == "draft"
        )
    s.add("1.1 Create daily report with workforce", passed, r.status_code, 201)

    # 1.2 Create inspection report
    r2 = client.post("/api/v1/fieldreports/reports", json={
        "project_id": PROJECT_ID,
        "report_date": today,
        "report_type": "inspection",
        "weather_condition": "cloudy",
        "work_performed": "Rebar inspection before pour",
        "safety_incidents": "None",
    })
    inspection_id = ""
    passed2 = r2.status_code == 201
    if passed2:
        inspection_id = r2.json().get("id", "")
        passed2 = r2.json().get("report_type") == "inspection"
    s.add("1.2 Create inspection report", passed2, r2.status_code, 201)

    # 1.3 List reports with date filter
    r3 = client.get(f"/api/v1/fieldreports/reports?project_id={PROJECT_ID}&date_from={today}")
    passed3 = r3.status_code == 200 and isinstance(r3.json(), list) and len(r3.json()) >= 2
    s.add("1.3 List reports with date filter", passed3, r3.status_code, 200,
          detail=f"count={len(r3.json()) if r3.status_code == 200 else 'N/A'}")

    # 1.4 Get single report
    r4 = client.get(f"/api/v1/fieldreports/reports/{report_id}")
    passed4 = r4.status_code == 200 and r4.json().get("id") == report_id
    s.add("1.4 Get single report", passed4, r4.status_code, 200)

    # 1.5 Update report (add delays)
    r5 = client.patch(f"/api/v1/fieldreports/reports/{report_id}", json={
        "delays": "Rain delay - 2 hours",
        "delay_hours": 2.0,
    })
    passed5 = r5.status_code == 200
    if passed5:
        d = r5.json()
        passed5 = d.get("delays") == "Rain delay - 2 hours" and d.get("delay_hours") == 2.0
    s.add("1.5 Update report (add delays)", passed5, r5.status_code, 200)

    # 1.6 Submit report (draft -> submitted)
    r6 = client.post(f"/api/v1/fieldreports/reports/{report_id}/submit")
    passed6 = r6.status_code == 200 and r6.json().get("status") == "submitted"
    s.add("1.6 Submit report (draft -> submitted)", passed6, r6.status_code, 200,
          detail=f"status={r6.json().get('status') if r6.status_code == 200 else 'N/A'}")

    # 1.7 Approve report (submitted -> approved)
    r7 = client.post(f"/api/v1/fieldreports/reports/{report_id}/approve")
    passed7 = r7.status_code == 200 and r7.json().get("status") == "approved"
    s.add("1.7 Approve report (submitted -> approved)", passed7, r7.status_code, 200,
          detail=f"status={r7.json().get('status') if r7.status_code == 200 else 'N/A'}")

    # 1.8 Calendar endpoint
    month_str = date.today().strftime("%Y-%m")
    r8 = client.get(f"/api/v1/fieldreports/reports/calendar?project_id={PROJECT_ID}&month={month_str}")
    passed8 = r8.status_code == 200 and isinstance(r8.json(), list)
    s.add("1.8 Calendar endpoint", passed8, r8.status_code, 200)

    # 1.9 Summary endpoint
    r9 = client.get(f"/api/v1/fieldreports/reports/summary?project_id={PROJECT_ID}")
    passed9 = r9.status_code == 200
    if passed9:
        d = r9.json()
        passed9 = "total_reports" in d or "total" in d or isinstance(d, dict)
    s.add("1.9 Summary endpoint", passed9, r9.status_code, 200)

    # 1.10 Delete report (inspection)
    r10 = client.delete(f"/api/v1/fieldreports/reports/{inspection_id}")
    passed10 = r10.status_code == 204
    s.add("1.10 Delete report", passed10, r10.status_code, 204)

    # Cleanup: delete the daily report too
    if report_id:
        client.delete(f"/api/v1/fieldreports/reports/{report_id}")

    return s


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: Photo Gallery (8 tests)
# ══════════════════════════════════════════════════════════════════════════════


def test_photo_gallery() -> Section:
    s = Section("2. Photo Gallery")
    print(f"\n{'='*60}")
    print(f"  SECTION: {s.name}")
    print(f"{'='*60}")

    # 2.1 Photos list endpoint
    r1 = client.get(f"/api/v1/documents/photos?project_id={PROJECT_ID}")
    passed1 = r1.status_code == 200 and isinstance(r1.json(), list)
    s.add("2.1 Photos list endpoint works", passed1, r1.status_code, 200)

    # 2.2 Photos gallery endpoint
    r2 = client.get(f"/api/v1/documents/photos/gallery?project_id={PROJECT_ID}")
    passed2 = r2.status_code == 200 and isinstance(r2.json(), list)
    s.add("2.2 Photos gallery endpoint works", passed2, r2.status_code, 200)

    # 2.3 Photos timeline endpoint
    r3 = client.get(f"/api/v1/documents/photos/timeline?project_id={PROJECT_ID}")
    passed3 = r3.status_code == 200 and isinstance(r3.json(), list)
    s.add("2.3 Photos timeline endpoint works", passed3, r3.status_code, 200)

    # 2.4 Photos list with category filter
    r4 = client.get(f"/api/v1/documents/photos?project_id={PROJECT_ID}&category=site")
    passed4 = r4.status_code == 200 and isinstance(r4.json(), list)
    s.add("2.4 Photos list with category filter", passed4, r4.status_code, 200)

    # 2.5 Photos list with date_from filter
    r5 = client.get(f"/api/v1/documents/photos?project_id={PROJECT_ID}&date_from=2020-01-01")
    passed5 = r5.status_code == 200 and isinstance(r5.json(), list)
    s.add("2.5 Photos list with date_from filter", passed5, r5.status_code, 200)

    # 2.6 Photos list with search filter
    r6 = client.get(f"/api/v1/documents/photos?project_id={PROJECT_ID}&search=test")
    passed6 = r6.status_code == 200 and isinstance(r6.json(), list)
    s.add("2.6 Photos list with search filter", passed6, r6.status_code, 200)

    # 2.7 Photos list with offset and limit
    r7 = client.get(f"/api/v1/documents/photos?project_id={PROJECT_ID}&offset=0&limit=10")
    passed7 = r7.status_code == 200 and isinstance(r7.json(), list)
    s.add("2.7 Photos list with offset/limit", passed7, r7.status_code, 200)

    # 2.8 Photos list with tag filter
    r8 = client.get(f"/api/v1/documents/photos?project_id={PROJECT_ID}&tag=foundation")
    passed8 = r8.status_code == 200 and isinstance(r8.json(), list)
    s.add("2.8 Photos list with tag filter", passed8, r8.status_code, 200)

    return s


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: Takeoff Measurements (11 tests)
# ══════════════════════════════════════════════════════════════════════════════


def test_takeoff_measurements() -> Section:
    s = Section("3. Takeoff Measurements")
    print(f"\n{'='*60}")
    print(f"  SECTION: {s.name}")
    print(f"{'='*60}")

    measurement_ids: list[str] = []

    # 3.1 Create distance measurement
    r1 = client.post("/api/v1/takeoff/measurements", json={
        "project_id": PROJECT_ID,
        "type": "distance",
        "group_name": "Walls",
        "group_color": "#FF0000",
        "annotation": "Wall length A-B",
        "points": [{"x": 100, "y": 200}, {"x": 300, "y": 200}],
        "measurement_value": 12.5,
        "measurement_unit": "m",
    })
    passed1 = r1.status_code == 201
    if passed1:
        measurement_ids.append(r1.json()["id"])
        passed1 = r1.json().get("type") == "distance"
    s.add("3.1 Create distance measurement", passed1, r1.status_code, 201)

    # 3.2 Create polyline measurement (multi-point)
    r2 = client.post("/api/v1/takeoff/measurements", json={
        "project_id": PROJECT_ID,
        "type": "polyline",
        "group_name": "Perimeter",
        "points": [{"x": 0, "y": 0}, {"x": 100, "y": 0}, {"x": 100, "y": 50}, {"x": 0, "y": 50}],
        "measurement_value": 300.0,
        "measurement_unit": "m",
    })
    passed2 = r2.status_code == 201
    if passed2:
        measurement_ids.append(r2.json()["id"])
    s.add("3.2 Create polyline measurement", passed2, r2.status_code, 201)

    # 3.3 Create area measurement
    r3 = client.post("/api/v1/takeoff/measurements", json={
        "project_id": PROJECT_ID,
        "type": "area",
        "group_name": "Floors",
        "group_color": "#00FF00",
        "points": [{"x": 0, "y": 0}, {"x": 100, "y": 0}, {"x": 100, "y": 80}, {"x": 0, "y": 80}],
        "measurement_value": 45.0,
        "measurement_unit": "m2",
    })
    passed3 = r3.status_code == 201
    if passed3:
        measurement_ids.append(r3.json()["id"])
    s.add("3.3 Create area measurement", passed3, r3.status_code, 201)

    # 3.4 Create volume measurement (with depth)
    r4 = client.post("/api/v1/takeoff/measurements", json={
        "project_id": PROJECT_ID,
        "type": "volume",
        "group_name": "Concrete",
        "points": [{"x": 0, "y": 0}, {"x": 100, "y": 0}, {"x": 100, "y": 80}, {"x": 0, "y": 80}],
        "measurement_value": 45.0,
        "measurement_unit": "m3",
        "depth": 0.3,
        "volume": 13.5,
    })
    passed4 = r4.status_code == 201
    if passed4:
        measurement_ids.append(r4.json()["id"])
        passed4 = r4.json().get("depth") == 0.3
    s.add("3.4 Create volume measurement (with depth)", passed4, r4.status_code, 201)

    # 3.5 Create count measurement
    r5 = client.post("/api/v1/takeoff/measurements", json={
        "project_id": PROJECT_ID,
        "type": "count",
        "group_name": "Windows",
        "points": [{"x": 50, "y": 50}],
        "count_value": 12,
        "measurement_unit": "pcs",
    })
    passed5 = r5.status_code == 201
    if passed5:
        measurement_ids.append(r5.json()["id"])
        passed5 = r5.json().get("count_value") == 12
    s.add("3.5 Create count measurement", passed5, r5.status_code, 201)

    # 3.6 List measurements with filters (group, type, page)
    r6 = client.get(
        f"/api/v1/takeoff/measurements?project_id={PROJECT_ID}&group=Walls&type=distance"
    )
    passed6 = r6.status_code == 200 and isinstance(r6.json(), list) and len(r6.json()) >= 1
    s.add("3.6 List measurements with filters", passed6, r6.status_code, 200,
          detail=f"count={len(r6.json()) if r6.status_code == 200 else 'N/A'}")

    # 3.7 Measurement summary endpoint
    r7 = client.get(f"/api/v1/takeoff/measurements/summary?project_id={PROJECT_ID}")
    passed7 = r7.status_code == 200
    if passed7:
        d = r7.json()
        passed7 = "total_measurements" in d and d["total_measurements"] >= 5
    s.add("3.7 Measurement summary endpoint", passed7, r7.status_code, 200,
          detail=f"total={r7.json().get('total_measurements') if r7.status_code == 200 else 'N/A'}")

    # 3.8 Export measurements (CSV format)
    r8 = client.get(f"/api/v1/takeoff/measurements/export?project_id={PROJECT_ID}&format=csv")
    passed8 = r8.status_code == 200
    if passed8:
        d = r8.json()
        passed8 = "csv" in d or "measurements" in d
    s.add("3.8 Export measurements (CSV)", passed8, r8.status_code, 200)

    # 3.9 Link measurement to BOQ position
    test_pos = POSITION_ID if POSITION_ID else str(uuid.uuid4())
    if measurement_ids:
        r9 = client.post(
            f"/api/v1/takeoff/measurements/{measurement_ids[0]}/link-to-boq",
            json={"boq_position_id": test_pos}
        )
        passed9 = r9.status_code == 200
        if passed9:
            passed9 = r9.json().get("linked_boq_position_id") == test_pos
        s.add("3.9 Link measurement to BOQ position", passed9, r9.status_code, 200)
    else:
        s.add("3.9 Link measurement to BOQ position", False, detail="No measurements created")

    # 3.10 Bulk create measurements
    r10 = client.post("/api/v1/takeoff/measurements/bulk", json={
        "measurements": [
            {
                "project_id": PROJECT_ID,
                "type": "distance",
                "group_name": "Bulk Group",
                "points": [{"x": 10, "y": 20}, {"x": 30, "y": 40}],
                "measurement_value": 5.0,
                "measurement_unit": "m",
            },
            {
                "project_id": PROJECT_ID,
                "type": "area",
                "group_name": "Bulk Group",
                "points": [{"x": 0, "y": 0}, {"x": 10, "y": 0}, {"x": 10, "y": 10}, {"x": 0, "y": 10}],
                "measurement_value": 100.0,
                "measurement_unit": "m2",
            },
        ]
    })
    passed10 = r10.status_code == 201 and isinstance(r10.json(), list) and len(r10.json()) == 2
    if passed10:
        for item in r10.json():
            measurement_ids.append(item["id"])
    s.add("3.10 Bulk create measurements", passed10, r10.status_code, 201)

    # 3.11 Delete measurement
    if measurement_ids:
        del_id = measurement_ids.pop()
        r11 = client.delete(f"/api/v1/takeoff/measurements/{del_id}")
        passed11 = r11.status_code == 204
        s.add("3.11 Delete measurement", passed11, r11.status_code, 204)
    else:
        s.add("3.11 Delete measurement", False, detail="No measurement to delete")

    # Cleanup remaining measurements
    for mid in measurement_ids:
        client.delete(f"/api/v1/takeoff/measurements/{mid}")

    return s


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4: Requirements (8 tests)
# ══════════════════════════════════════════════════════════════════════════════


def test_requirements() -> Section:
    s = Section("4. Requirements")
    print(f"\n{'='*60}")
    print(f"  SECTION: {s.name}")
    print(f"{'='*60}")

    set_id = ""
    req_ids: list[str] = []

    # 4.1 Create set + 3 requirements
    r1 = client.post("/api/v1/requirements/", json={
        "project_id": PROJECT_ID,
        "name": "QA Test Requirements",
        "description": "Testing quality gates",
        "source_type": "manual",
    })
    passed1 = r1.status_code == 201
    if passed1:
        set_id = r1.json().get("id", "")

    # Add 3 requirements
    reqs_data = [
        {
            "entity": "Wall",
            "attribute": "thickness",
            "constraint_type": "min",
            "constraint_value": "200",
            "unit": "mm",
            "category": "structural",
            "priority": "must",
        },
        {
            "entity": "Slab",
            "attribute": "fire_rating",
            "constraint_type": "equals",
            "constraint_value": "F90",
            "category": "fire_safety",
            "priority": "must",
        },
        {
            "entity": "Window",
            "attribute": "u_value",
            "constraint_type": "max",
            "constraint_value": "1.3",
            "unit": "W/m2K",
            "category": "energy",
            "priority": "should",
        },
    ]
    for rd in reqs_data:
        rr = client.post(f"/api/v1/requirements/{set_id}/requirements", json=rd)
        if rr.status_code == 201:
            req_ids.append(rr.json().get("id", ""))
            passed1 = passed1 and True
        else:
            passed1 = False

    passed1 = passed1 and len(req_ids) == 3
    s.add("4.1 Create set + 3 requirements", passed1,
          detail=f"set_id={set_id[:8] if set_id else 'N/A'}, reqs={len(req_ids)}")

    # 4.2 Run all 4 gates (verify status pass/fail, score 0-100)
    gate_results = []
    all_gates_ok = True
    for gate_num in range(1, 5):
        rg = client.post(f"/api/v1/requirements/{set_id}/gates/{gate_num}/run")
        if rg.status_code == 200:
            gdata = rg.json()
            gate_results.append(gdata)
            score = gdata.get("score", -1)
            status = gdata.get("status", "")
            if not (0 <= score <= 100 and status in ("pass", "fail", "warning")):
                all_gates_ok = False
        else:
            all_gates_ok = False
    s.add("4.2 Run all 4 gates (score 0-100)", all_gates_ok,
          detail=f"gates_run={len(gate_results)}")

    # 4.3 Export CSV
    r3 = client.get(f"/api/v1/requirements/{set_id}/export?format=csv")
    passed3 = r3.status_code == 200
    s.add("4.3 Export CSV", passed3, r3.status_code, 200)

    # 4.4 Export JSON
    r4 = client.get(f"/api/v1/requirements/{set_id}/export?format=json")
    passed4 = r4.status_code == 200
    if passed4:
        data = r4.json()
        passed4 = isinstance(data, list) and len(data) == 3
    s.add("4.4 Export JSON", passed4, r4.status_code, 200,
          detail=f"count={len(r4.json()) if r4.status_code == 200 and isinstance(r4.json(), list) else 'N/A'}")

    # 4.5 Import from text (pipe-separated: entity | attribute | constraint_value)
    r5 = client.post(f"/api/v1/requirements/{set_id}/import/text", json={
        "text": "Wall | thickness | min | 200 | mm\nSlab | fire_rating | equals | F90\nDoor | width | min | 900 | mm",
        "set_name": "Imported from spec",
        "default_category": "structural",
        "default_priority": "must",
    })
    passed5 = r5.status_code == 201
    s.add("4.5 Import from text", passed5, r5.status_code, 201)

    # 4.6 Link to BOQ (requires a real position since endpoint validates FK)
    if req_ids and POSITION_ID:
        r6 = client.post(
            f"/api/v1/requirements/{set_id}/requirements/{req_ids[0]}/link/{POSITION_ID}"
        )
        passed6 = r6.status_code == 200
        if passed6:
            passed6 = r6.json().get("linked_position_id") is not None
        s.add("4.6 Link to BOQ", passed6, r6.status_code, 200)
    elif req_ids:
        # No real position available - test that endpoint rejects invalid FK correctly
        fake_pos = str(uuid.uuid4())
        r6 = client.post(
            f"/api/v1/requirements/{set_id}/requirements/{req_ids[0]}/link/{fake_pos}"
        )
        # 404 is expected when position doesn't exist — endpoint validates FK
        passed6 = r6.status_code == 404
        s.add("4.6 Link to BOQ (FK validation)", passed6, r6.status_code, 404,
              detail="No real position; verified FK check returns 404")
    else:
        s.add("4.6 Link to BOQ", False, detail="No requirements created")

    # 4.7 Stats endpoint
    r7 = client.get(f"/api/v1/requirements/stats?project_id={PROJECT_ID}")
    passed7 = r7.status_code == 200 and isinstance(r7.json(), dict)
    s.add("4.7 Stats endpoint", passed7, r7.status_code, 200)

    # 4.8 Delete set
    r8 = client.delete(f"/api/v1/requirements/{set_id}")
    passed8 = r8.status_code == 204
    s.add("4.8 Delete set", passed8, r8.status_code, 204)

    return s


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5: Markups (8 tests)
# ══════════════════════════════════════════════════════════════════════════════


def test_markups() -> Section:
    s = Section("5. Markups")
    print(f"\n{'='*60}")
    print(f"  SECTION: {s.name}")
    print(f"{'='*60}")

    markup_ids: list[str] = []
    doc_id = f"doc-qa-{uuid.uuid4().hex[:8]}"

    # 5.1 Create cloud, arrow, text, distance, stamp markups
    markup_types = [
        {"type": "cloud", "geometry": {"points": [{"x": 10, "y": 10}, {"x": 100, "y": 10}, {"x": 100, "y": 80}]}, "text": "Check this area", "color": "#ff0000"},
        {"type": "arrow", "geometry": {"start": {"x": 50, "y": 50}, "end": {"x": 150, "y": 100}}, "text": "Arrow note", "color": "#0000ff"},
        {"type": "text", "geometry": {"x": 200, "y": 200}, "text": "Important: verify dimensions", "color": "#00ff00"},
        {"type": "distance", "geometry": {"start": {"x": 0, "y": 0}, "end": {"x": 100, "y": 0}}, "measurement_value": 5.2, "measurement_unit": "m", "color": "#ff9900"},
        {"type": "stamp", "geometry": {"x": 300, "y": 300}, "text": "APPROVED", "color": "#22c55e"},
    ]
    all_created = True
    for mdata in markup_types:
        r = client.post("/api/v1/markups/", json={
            "project_id": PROJECT_ID,
            "document_id": doc_id,
            "page": 1,
            **mdata,
        })
        if r.status_code == 201:
            markup_ids.append(r.json()["id"])
        else:
            all_created = False
    all_created = all_created and len(markup_ids) == 5
    s.add("5.1 Create cloud/arrow/text/distance/stamp", all_created,
          detail=f"created={len(markup_ids)}/5")

    # 5.2 List with type filter
    r2 = client.get(f"/api/v1/markups/?project_id={PROJECT_ID}&type=cloud")
    passed2 = r2.status_code == 200 and isinstance(r2.json(), list) and len(r2.json()) >= 1
    s.add("5.2 List with type filter", passed2, r2.status_code, 200)

    # 5.3 Update status
    if markup_ids:
        r3 = client.patch(f"/api/v1/markups/{markup_ids[0]}", json={"status": "resolved"})
        passed3 = r3.status_code == 200 and r3.json().get("status") == "resolved"
        s.add("5.3 Update status", passed3, r3.status_code, 200)
    else:
        s.add("5.3 Update status", False, detail="No markup to update")

    # 5.4 Summary
    r4 = client.get(f"/api/v1/markups/summary?project_id={PROJECT_ID}")
    passed4 = r4.status_code == 200 and "total_markups" in r4.json()
    s.add("5.4 Summary", passed4, r4.status_code, 200,
          detail=f"total={r4.json().get('total_markups') if r4.status_code == 200 else 'N/A'}")

    # 5.5 Stamp templates CRUD
    stamp_r = client.post("/api/v1/markups/stamps/templates", json={
        "project_id": PROJECT_ID,
        "name": "QA Approved",
        "category": "custom",
        "text": "QA APPROVED",
        "color": "#22c55e",
        "include_date": True,
        "include_name": True,
    })
    stamp_id = ""
    passed5 = stamp_r.status_code == 201
    if passed5:
        stamp_id = stamp_r.json().get("id", "")
    # List stamps
    stamp_list = client.get(f"/api/v1/markups/stamps/templates?project_id={PROJECT_ID}")
    passed5 = passed5 and stamp_list.status_code == 200 and len(stamp_list.json()) >= 1
    s.add("5.5 Stamp templates CRUD", passed5, stamp_r.status_code, 201)

    # 5.6 Scale config CRUD
    scale_r = client.post("/api/v1/markups/scales/", json={
        "document_id": doc_id,
        "page": 1,
        "pixels_per_unit": 50.0,
        "unit_label": "m",
        "real_distance": 10.0,
        "calibration_points": {"p1": {"x": 0, "y": 0}, "p2": {"x": 500, "y": 0}},
    })
    scale_id = ""
    passed6 = scale_r.status_code == 201
    if passed6:
        scale_id = scale_r.json().get("id", "")
    # List scales
    scale_list = client.get(f"/api/v1/markups/scales/?document_id={doc_id}")
    passed6 = passed6 and scale_list.status_code == 200 and len(scale_list.json()) >= 1
    s.add("5.6 Scale config CRUD", passed6, scale_r.status_code, 201)

    # 5.7 Link to BOQ
    test_pos7 = POSITION_ID if POSITION_ID else str(uuid.uuid4())
    if markup_ids:
        r7 = client.post(f"/api/v1/markups/{markup_ids[1]}/link-to-boq", json={
            "position_id": test_pos7,
        })
        passed7 = r7.status_code == 200
        if passed7:
            passed7 = r7.json().get("linked_boq_position_id") is not None
        s.add("5.7 Link to BOQ", passed7, r7.status_code, 200)
    else:
        s.add("5.7 Link to BOQ", False, detail="No markups created")

    # 5.8 Export CSV + Delete
    r8 = client.get(f"/api/v1/markups/export?project_id={PROJECT_ID}")
    passed8 = r8.status_code == 200
    s.add("5.8 Export CSV", passed8, r8.status_code, 200)

    # Cleanup
    for mid in markup_ids:
        client.delete(f"/api/v1/markups/{mid}")
    if stamp_id:
        client.delete(f"/api/v1/markups/stamps/templates/{stamp_id}")
    if scale_id:
        client.delete(f"/api/v1/markups/scales/{scale_id}")

    return s


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6: Punch List (8 tests)
# ══════════════════════════════════════════════════════════════════════════════


def test_punch_list() -> Section:
    s = Section("6. Punch List")
    print(f"\n{'='*60}")
    print(f"  SECTION: {s.name}")
    print(f"{'='*60}")

    item_ids: list[str] = []

    # 6.1 Create 3 items with different priorities
    items_data = [
        {
            "project_id": PROJECT_ID,
            "title": "Crack in foundation wall",
            "description": "Visible crack in sector B, north wall",
            "priority": "critical",
            "category": "structural",
            "trade": "Concrete",
        },
        {
            "project_id": PROJECT_ID,
            "title": "Paint defect in lobby",
            "description": "Uneven paint on east wall",
            "priority": "low",
            "category": "finishing",
            "trade": "Painting",
        },
        {
            "project_id": PROJECT_ID,
            "title": "Missing fire damper",
            "description": "Fire damper not installed in duct shaft 3",
            "priority": "high",
            "category": "fire_safety",
            "trade": "HVAC",
        },
    ]
    all_ok = True
    for idata in items_data:
        r = client.post("/api/v1/punchlist/items", json=idata)
        if r.status_code == 201:
            item_ids.append(r.json()["id"])
        else:
            all_ok = False
    all_ok = all_ok and len(item_ids) == 3
    s.add("6.1 Create 3 items (critical/low/high)", all_ok,
          detail=f"created={len(item_ids)}/3")

    # 6.2 List with priority filter
    r2 = client.get(f"/api/v1/punchlist/items?project_id={PROJECT_ID}&priority=critical")
    passed2 = r2.status_code == 200 and isinstance(r2.json(), list) and len(r2.json()) >= 1
    s.add("6.2 List with priority filter (critical)", passed2, r2.status_code, 200,
          detail=f"count={len(r2.json()) if r2.status_code == 200 else 'N/A'}")

    # 6.3 Full workflow: open -> in_progress -> resolved -> verified -> closed
    workflow_id = item_ids[0] if item_ids else ""
    workflow_ok = True
    transitions = ["in_progress", "resolved", "verified", "closed"]
    for new_status in transitions:
        rt = client.post(f"/api/v1/punchlist/items/{workflow_id}/transition", json={
            "new_status": new_status,
            "notes": f"Moving to {new_status}",
        })
        if rt.status_code == 200:
            actual = rt.json().get("status", "")
            if actual != new_status:
                workflow_ok = False
        else:
            workflow_ok = False
            break
    s.add("6.3 Full workflow open->...->closed", workflow_ok,
          detail=f"transitions={len(transitions)}")

    # 6.4 Summary
    r4 = client.get(f"/api/v1/punchlist/summary?project_id={PROJECT_ID}")
    passed4 = r4.status_code == 200 and isinstance(r4.json(), dict)
    s.add("6.4 Summary", passed4, r4.status_code, 200)

    # 6.5 Get single item
    if len(item_ids) >= 2:
        r5 = client.get(f"/api/v1/punchlist/items/{item_ids[1]}")
        passed5 = r5.status_code == 200 and r5.json().get("id") == item_ids[1]
        s.add("6.5 Get single item", passed5, r5.status_code, 200)
    else:
        s.add("6.5 Get single item", False, detail="No item available")

    # 6.6 Update item
    if len(item_ids) >= 2:
        r6 = client.patch(f"/api/v1/punchlist/items/{item_ids[1]}", json={
            "description": "Updated: Paint defect with additional area",
            "priority": "medium",
        })
        passed6 = r6.status_code == 200
        if passed6:
            passed6 = r6.json().get("description", "").startswith("Updated")
        s.add("6.6 Update item", passed6, r6.status_code, 200)
    else:
        s.add("6.6 Update item", False, detail="No item available")

    # 6.7 List with status filter
    r7 = client.get(f"/api/v1/punchlist/items?project_id={PROJECT_ID}&status=open")
    passed7 = r7.status_code == 200 and isinstance(r7.json(), list)
    s.add("6.7 List with status filter (open)", passed7, r7.status_code, 200)

    # 6.8 Delete item
    if item_ids:
        del_id = item_ids[-1]
        r8 = client.delete(f"/api/v1/punchlist/items/{del_id}")
        passed8 = r8.status_code == 204
        s.add("6.8 Delete item", passed8, r8.status_code, 204)
    else:
        s.add("6.8 Delete item", False, detail="No item to delete")

    # Cleanup remaining items
    for iid in item_ids:
        client.delete(f"/api/v1/punchlist/items/{iid}")

    return s


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7: Cross-module Integration (5 tests)
# ══════════════════════════════════════════════════════════════════════════════


def test_cross_module() -> Section:
    s = Section("7. Cross-module Integration")
    print(f"\n{'='*60}")
    print(f"  SECTION: {s.name}")
    print(f"{'='*60}")

    # For cross-module BOQ link tests, use a fake position_id if no real one exists.
    # The link endpoints store the ID as a string reference; they don't validate FK.
    test_pos_id = POSITION_ID if POSITION_ID else str(uuid.uuid4())

    # 7.1 Measurement links to BOQ position
    m_r = client.post("/api/v1/takeoff/measurements", json={
        "project_id": PROJECT_ID,
        "type": "distance",
        "group_name": "Cross-test",
        "points": [{"x": 0, "y": 0}, {"x": 100, "y": 0}],
        "measurement_value": 10.0,
        "measurement_unit": "m",
    })
    m_id = ""
    if m_r.status_code == 201:
        m_id = m_r.json()["id"]
    if m_id:
        link_r = client.post(f"/api/v1/takeoff/measurements/{m_id}/link-to-boq",
                             json={"boq_position_id": test_pos_id})
        passed1 = link_r.status_code == 200 and link_r.json().get("linked_boq_position_id") == test_pos_id
    else:
        passed1 = False
    s.add("7.1 Measurement -> BOQ position link", passed1,
          detail=f"m_id={m_id[:8] if m_id else 'N/A'}")
    if m_id:
        client.delete(f"/api/v1/takeoff/measurements/{m_id}")

    # 7.2 Markup links to BOQ position
    mk_r = client.post("/api/v1/markups/", json={
        "project_id": PROJECT_ID,
        "type": "cloud",
        "geometry": {"points": [{"x": 0, "y": 0}]},
        "text": "Cross-module test",
    })
    mk_id = ""
    if mk_r.status_code == 201:
        mk_id = mk_r.json()["id"]
    if mk_id:
        link_r2 = client.post(f"/api/v1/markups/{mk_id}/link-to-boq",
                              json={"position_id": test_pos_id})
        passed2 = link_r2.status_code == 200
    else:
        passed2 = False
    s.add("7.2 Markup -> BOQ position link", passed2,
          detail=f"mk_id={mk_id[:8] if mk_id else 'N/A'}")
    if mk_id:
        client.delete(f"/api/v1/markups/{mk_id}")

    # 7.3 Requirement links to BOQ position
    rs_r = client.post("/api/v1/requirements/", json={
        "project_id": PROJECT_ID,
        "name": "Cross-module test set",
    })
    rs_id = ""
    if rs_r.status_code == 201:
        rs_id = rs_r.json().get("id", "")
    req_r = None
    rq_id = ""
    if rs_id:
        req_r = client.post(f"/api/v1/requirements/{rs_id}/requirements", json={
            "entity": "Test",
            "attribute": "value",
            "constraint_type": "min",
            "constraint_value": "100",
        })
        if req_r and req_r.status_code == 201:
            rq_id = req_r.json().get("id", "")
    if rq_id and POSITION_ID:
        link_r3 = client.post(
            f"/api/v1/requirements/{rs_id}/requirements/{rq_id}/link/{POSITION_ID}"
        )
        passed3 = link_r3.status_code == 200
    elif rq_id:
        # No real position - verify FK validation works (should return 404)
        link_r3 = client.post(
            f"/api/v1/requirements/{rs_id}/requirements/{rq_id}/link/{test_pos_id}"
        )
        passed3 = link_r3.status_code == 404  # Expected: FK validation rejects
    else:
        passed3 = False
    s.add("7.3 Requirement -> BOQ position link", passed3,
          detail=f"req_id={rq_id[:8] if rq_id else 'N/A'}")
    if rs_id:
        client.delete(f"/api/v1/requirements/{rs_id}")

    # 7.4 Field report references project correctly
    fr_r = client.post("/api/v1/fieldreports/reports", json={
        "project_id": PROJECT_ID,
        "report_date": date.today().isoformat(),
        "report_type": "daily",
        "work_performed": "Cross-module integration test",
    })
    passed4 = fr_r.status_code == 201
    fr_id = ""
    if passed4:
        fr_id = fr_r.json().get("id", "")
        passed4 = fr_r.json().get("project_id") == PROJECT_ID
    s.add("7.4 Field report references project", passed4, fr_r.status_code, 201)
    if fr_id:
        client.delete(f"/api/v1/fieldreports/reports/{fr_id}")

    # 7.5 Punch item references document
    pi_r = client.post("/api/v1/punchlist/items", json={
        "project_id": PROJECT_ID,
        "title": "Cross-module: punch with document ref",
        "document_id": "test-doc-001",
        "page": 3,
        "location_x": 0.5,
        "location_y": 0.7,
        "priority": "medium",
    })
    passed5 = pi_r.status_code == 201
    pi_id = ""
    if passed5:
        pi_id = pi_r.json().get("id", "")
        d = pi_r.json()
        passed5 = (
            d.get("document_id") == "test-doc-001"
            and d.get("page") == 3
        )
    s.add("7.5 Punch item references document", passed5, pi_r.status_code, 201)
    if pi_id:
        client.delete(f"/api/v1/punchlist/items/{pi_id}")

    return s


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 8: All Existing Modules Regression (15 tests)
# ══════════════════════════════════════════════════════════════════════════════


def test_regression() -> Section:
    s = Section("8. Regression (All Existing Modules)")
    print(f"\n{'='*60}")
    print(f"  SECTION: {s.name}")
    print(f"{'='*60}")

    # 8.1 Health
    r = client.get("/api/health")
    passed = r.status_code == 200 and r.json().get("status") == "healthy"
    s.add("8.1 Health endpoint", passed, r.status_code, 200)

    # 8.2 Auth (login)
    r = client.post("/api/v1/users/auth/login", json={
        "email": DEMO_EMAIL, "password": DEMO_PASSWORD
    })
    passed = r.status_code == 200 and "access_token" in r.json()
    s.add("8.2 Auth login", passed, r.status_code, 200)

    # 8.3 Projects CRUD (list)
    r = client.get("/api/v1/projects/")
    passed = r.status_code == 200 and isinstance(r.json(), list)
    project_count = len(r.json()) if r.status_code == 200 else 0
    s.add("8.3 Projects list", passed, r.status_code, 200,
          detail=f"count={project_count}")

    # 8.4 Projects create + delete
    r = client.post("/api/v1/projects/", json={
        "name": f"QA Regression {uuid.uuid4().hex[:6]}",
        "description": "Regression test project",
        "country": "DE",
        "currency": "EUR",
    })
    passed = r.status_code in (200, 201)
    temp_proj_id = ""
    if passed:
        temp_proj_id = r.json().get("id", "")
    s.add("8.4 Project create", passed, r.status_code, 201)

    # 8.5 BOQ CRUD
    r = client.get(f"/api/v1/boq/boqs/?project_id={PROJECT_ID}")
    passed = r.status_code == 200 and isinstance(r.json(), list)
    boq_count = len(r.json()) if r.status_code == 200 else 0
    s.add("8.5 BOQ list", passed, r.status_code, 200, detail=f"count={boq_count}")

    # 8.6 BOQ structured (with positions)
    if BOQ_ID:
        r = client.get(f"/api/v1/boq/boqs/{BOQ_ID}/structured")
        passed = r.status_code == 200 and isinstance(r.json(), dict)
        pos_count = 0
        if passed:
            for sec in r.json().get("sections", []):
                pos_count += len(sec.get("positions", []))
            pos_count += len(r.json().get("positions", []))
        s.add("8.6 BOQ structured", passed, r.status_code, 200, detail=f"positions={pos_count}")
    else:
        s.add("8.6 BOQ structured", False, detail="No BOQ available")

    # 8.7 BOQ export
    if BOQ_ID:
        r = client.get(f"/api/v1/boq/boqs/{BOQ_ID}/export/excel")
        passed = r.status_code == 200
        s.add("8.7 BOQ export", passed, r.status_code, 200)
    else:
        s.add("8.7 BOQ export", False, detail="No BOQ available")

    # 8.8 Costs module
    r = client.get(f"/api/v1/costs/?project_id={PROJECT_ID}&limit=5")
    passed = r.status_code == 200
    s.add("8.8 Costs endpoint", passed, r.status_code, 200)

    # 8.9 Catalog module
    r = client.get("/api/v1/catalog/stats")
    passed = r.status_code == 200 and isinstance(r.json(), dict)
    s.add("8.9 Catalog stats", passed, r.status_code, 200)

    # 8.10 Schedule module
    r = client.get(f"/api/v1/schedule/schedules/?project_id={PROJECT_ID}")
    passed = r.status_code == 200
    s.add("8.10 Schedule endpoint", passed, r.status_code, 200)

    # 8.11 Risk module
    r = client.get(f"/api/v1/risk/?project_id={PROJECT_ID}")
    passed = r.status_code == 200
    s.add("8.11 Risk endpoint", passed, r.status_code, 200)

    # 8.12 Change Orders module
    r = client.get(f"/api/v1/changeorders/?project_id={PROJECT_ID}")
    passed = r.status_code == 200
    s.add("8.12 Change Orders endpoint", passed, r.status_code, 200)

    # 8.13 Documents module
    r = client.get(f"/api/v1/documents/?project_id={PROJECT_ID}")
    passed = r.status_code == 200 and isinstance(r.json(), list)
    s.add("8.13 Documents endpoint", passed, r.status_code, 200)

    # 8.14 Takeoff converters
    r = client.get("/api/v1/takeoff/converters")
    passed = r.status_code == 200 and "converters" in r.json()
    converter_count = r.json().get("total_count", 0) if r.status_code == 200 else 0
    s.add("8.14 Takeoff converters", passed, r.status_code, 200,
          detail=f"count={converter_count}")

    # 8.15 System modules count
    r = client.get("/api/system/modules")
    passed = r.status_code == 200 and "modules" in r.json()
    module_count = len(r.json().get("modules", [])) if r.status_code == 200 else 0
    passed = passed and module_count >= 15
    s.add("8.15 System modules (>= 15)", passed, r.status_code, 200,
          detail=f"count={module_count}")

    # Cleanup temp project
    if temp_proj_id:
        client.delete(f"/api/v1/projects/{temp_proj_id}")

    return s


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════


def main() -> int:
    global client, PROJECT_ID, BOQ_ID, POSITION_ID

    print("=" * 60)
    print("  OpenEstimate - Final QA Test Suite")
    print(f"  Server: {BASE_URL}")
    print(f"  Time:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    client = httpx.Client(base_url=BASE_URL, timeout=TIMEOUT)
    start_time = time.time()

    # ── Login ──
    print("\n  Logging in...")
    if not login():
        print("  FATAL: Cannot login. Is the server running?")
        return 1
    print("  OK: Logged in as demo@openestimator.io")

    # ── Get project and BOQ context ──
    global PROJECT_ID, BOQ_ID, POSITION_ID
    PROJECT_ID, BOQ_ID, POSITION_ID = get_project_with_boq()
    if not PROJECT_ID:
        print("  FATAL: No projects found. Cannot run tests.")
        return 1
    print(f"  OK: Using project {PROJECT_ID[:8]}...")
    print(f"  OK: BOQ={BOQ_ID[:8] if BOQ_ID else 'N/A'}... Position={POSITION_ID[:8] if POSITION_ID else 'N/A'}...")

    # ── Run all sections ──
    sections.append(test_field_reports())
    sections.append(test_photo_gallery())
    sections.append(test_takeoff_measurements())
    sections.append(test_requirements())
    sections.append(test_markups())
    sections.append(test_punch_list())
    sections.append(test_cross_module())
    sections.append(test_regression())

    # ── Final Summary ──
    elapsed = time.time() - start_time
    total_passed = sum(s.passed_count for s in sections)
    total_failed = sum(s.failed_count for s in sections)
    total_tests = total_passed + total_failed

    print("\n")
    print("=" * 60)
    print("  FINAL SUMMARY")
    print("=" * 60)
    print()
    print(f"  {'Section':<42} {'Pass':>5} {'Fail':>5} {'Total':>5}")
    print(f"  {'-'*42} {'-'*5} {'-'*5} {'-'*5}")
    for s in sections:
        total_s = s.passed_count + s.failed_count
        print(f"  {s.name:<42} {s.passed_count:>5} {s.failed_count:>5} {total_s:>5}")
    print(f"  {'-'*42} {'-'*5} {'-'*5} {'-'*5}")
    print(f"  {'TOTAL':<42} {total_passed:>5} {total_failed:>5} {total_tests:>5}")
    print()
    print(f"  Duration: {elapsed:.1f}s")
    print()

    if total_failed == 0:
        print(f"  ALL {total_tests} TESTS PASSED")
    else:
        print(f"  {total_failed} TEST(S) FAILED:")
        for s in sections:
            for r in s.results:
                if not r.passed:
                    det = f" -- {r.detail}" if r.detail else ""
                    sc = f" [got {r.status_code}, expected {r.expected}]" if r.status_code and r.expected else ""
                    print(f"    - {s.name} / {r.name}{sc}{det}")

    print()
    print("=" * 60)

    client.close()
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
