# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Monitoring end to end on the Riverside Yard lessons, against a real database.

Lesson numbers come from ``demo/riverside/expected.json``: the course reads
the same file, so a change here that breaks a lesson fails this suite.
"""

from __future__ import annotations

import json
from pathlib import Path

from httpx import AsyncClient

BASE = "/api/v1/monitoring"
DEMO = Path(__file__).resolve().parents[3] / "app" / "modules" / "monitoring" / "demo" / "riverside"
EXPECTED = json.loads((DEMO / "expected.json").read_text(encoding="utf-8"))["monitoring"]


async def _setup(client: AsyncClient, header: dict, project_id: str, epochs: int = 0) -> list[dict]:
    response = await client.post(f"{BASE}/projects/{project_id}/demo/riverside?epochs={epochs}", headers=header)
    assert response.status_code == 200, response.text
    return response.json()


async def _import_file(client: AsyncClient, header: dict, project_id: str, name: str) -> dict:
    text = (DEMO / name).read_text(encoding="utf-8")
    response = await client.post(
        f"{BASE}/projects/{project_id}/readings", json={"text": text, "filename": name}, headers=header
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _points(client: AsyncClient, header: dict, project_id: str) -> dict[str, dict]:
    response = await client.get(f"{BASE}/projects/{project_id}/points", headers=header)
    assert response.status_code == 200, response.text
    return {p["code"]: p for p in response.json()["items"]}


async def test_demo_setup_is_idempotent_and_has_no_readings_yet(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    first = await _setup(client, header, project_id)
    again = await _setup(client, header, project_id)
    assert [p["code"] for p in first] == ["MP-01", "MP-02"] == [p["code"] for p in again]
    assert all(p["epochs"] == 0 and p["level"] == "none" for p in first)
    settings = (await client.get(f"{BASE}/projects/{project_id}/settings", headers=header)).json()
    assert settings["profile_key"] == "demo"
    assert settings["profile"]["name"] == EXPECTED["profile"]["name"]
    assert settings["profile"]["reference"] == "Demo values, not a standard"
    assert settings["profile"]["thresholds"]["alarm_mm"] == EXPECTED["profile"]["alarm_mm"]


async def test_lesson_1_import_three_epochs(client: AsyncClient, header: dict, project_id: str) -> None:
    lesson = EXPECTED["lesson_1"]
    await _setup(client, header, project_id)
    text = (DEMO / lesson["file"]).read_text(encoding="utf-8")
    preview = (
        await client.post(f"{BASE}/projects/{project_id}/readings/preview", json={"text": text}, headers=header)
    ).json()
    assert (preview["rows_read"], preview["readings"], preview["problem_count"]) == (lesson["rows_read"], 6, 0)
    assert len(preview["epochs"]) == lesson["epochs"]
    assert (await _points(client, header, project_id))["MP-01"]["epochs"] == 0  # a preview saves nothing

    result = await _import_file(client, header, project_id, lesson["file"])
    assert (result["readings_added"], result["epochs_added"], result["problem_count"]) == (6, lesson["epochs"], 0)
    assert [a["level"] for a in result["alerts"]] == [lesson["level"]]

    points = await _points(client, header, project_id)
    mp1, mp2 = points[lesson["point"]], points[lesson["other_point"]["point"]]
    assert (mp1["displacement_mm"], mp1["rate_mm_day"], mp1["level"]) == (
        lesson["displacement_mm"],
        lesson["rate_mm_day"],
        lesson["level"],
    )
    assert (mp2["displacement_mm"], mp2["level"]) == (
        lesson["other_point"]["displacement_mm"],
        lesson["other_point"]["level"],
    )
    assert (mp1["baseline_value"], mp1["latest_value"]) == (34.512, 34.497)

    again = await _import_file(client, header, project_id, lesson["file"])
    assert (again["readings_added"], again["readings_skipped"], again["alerts"]) == (0, 6, [])


async def test_a_file_imported_without_the_demo_setup_creates_its_points_and_no_levels(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    result = await _import_file(client, header, project_id, EXPECTED["lesson_1"]["file"])
    assert sorted(result["new_points"]) == ["MP-01", "MP-02"]
    assert result["alerts"] == []  # no profile, no judgement: "No profile, set one"
    points = await _points(client, header, project_id)
    assert {p["level"] for p in points.values()} == {"none"}
    assert points["MP-01"]["displacement_mm"] == -15.0
    assert (points["MP-01"]["point_type"], points["MP-01"]["axis"]) == ("settlement_pin", "z")


async def test_lesson_2_point_drawer_has_three_epochs_and_the_bands(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    lesson = EXPECTED["lesson_2"]
    await _setup(client, header, project_id, epochs=3)
    point = (await _points(client, header, project_id))[lesson["point"]]
    detail = (await client.get(f"{BASE}/points/{point['id']}", headers=header)).json()
    assert len(detail["series"]) == lesson["epochs"]
    assert [e["displacement_mm"] for e in detail["series"]] == lesson["displacements_mm"]
    t = detail["thresholds"]
    assert [t["alert_mm"], t["action_mm"], t["alarm_mm"]] == lesson["bands_mm"]
    assert detail["profile_label"] == EXPECTED["profile"]["name"]
    assert len(detail["alerts"]) == 1


async def test_lessons_3_to_5_action_notification_risk_acknowledge_report(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    l3, l4, l5 = EXPECTED["lesson_3"], EXPECTED["lesson_4"], EXPECTED["lesson_5"]
    await _setup(client, header, project_id, epochs=3)
    result = await _import_file(client, header, project_id, l3["file"])
    assert result["epochs_added"] == 1
    assert [a["level"] for a in result["alerts"]] == [l3["level"]]
    alert = result["alerts"][0]
    assert (alert["displacement_mm"], alert["rate_mm_day"]) == (l3["displacement_mm"], l3["rate_mm_day"])
    assert alert["notified"] is l3["notification"]
    assert bool(alert["risk_id"]) is l3["risk_draft"]
    assert alert["thresholds"]["action_mm"] == 20.0

    mp1 = (await _points(client, header, project_id))[l3["point"]]
    assert (mp1["displacement_mm"], mp1["level"], mp1["ack_state"]) == (l3["displacement_mm"], "action", "pending")

    bell = (await client.get("/api/v1/notifications/", headers=header)).json()["items"]
    mine = [n for n in bell if n["entity_id"] == mp1["id"]]
    assert {n["title_key"] for n in mine} >= {
        "notifications.monitoring.alert.title",
        "notifications.monitoring.action.title",
    }
    action = next(n for n in mine if n["title_key"].endswith("action.title"))
    assert action["body_default"] == "Point MP-01: -23.0 mm, -1.14 mm/day."

    risks = (await client.get(f"/api/v1/risk/?project_id={project_id}", headers=header)).json()["items"]
    draft = next(r for r in risks if r["id"] == alert["risk_id"])
    assert draft["metadata"]["source"] == "monitoring"
    assert draft["metadata"]["draft"] is True
    assert draft["category"] == "safety"
    assert draft["title"] == "Monitoring point MP-01 at Action"

    report = (await client.post(f"{BASE}/projects/{project_id}/validate", headers=header)).json()
    assert [f["rule_id"] for f in report["findings"]] == [l3["rule"]]
    assert report["findings"][0]["message"] == l3["finding"]
    assert report["findings"][0]["severity"] == "error"

    kpi = (await client.get(f"{BASE}/projects/{project_id}/summary", headers=header)).json()
    expected_kpi = EXPECTED["kpi_after_epoch_4"]
    assert {k: kpi[k] for k in ("points", "alarm", "action", "alert")} == {
        k: expected_kpi[k] for k in ("points", "alarm", "action", "alert")
    }
    assert kpi["last_epoch"].startswith(expected_kpi["last_epoch"])
    assert kpi["unacknowledged"] == 1

    done = await client.post(f"{BASE}/points/{mp1['id']}/acknowledge", json={"note": l4["note"]}, headers=header)
    assert done.status_code == 200, done.text
    detail = done.json()
    assert detail["ack_state"] == "done"
    assert {a["note"] for a in detail["alerts"]} == {l4["note"]}
    assert all(a["acknowledged_by_name"] and a["acknowledged_at"] for a in detail["alerts"])
    again = await client.post(f"{BASE}/points/{mp1['id']}/acknowledge", json={"note": "x"}, headers=header)
    assert again.status_code == 409

    points = await _points(client, header, project_id)
    counts = {lvl: sum(1 for p in points.values() if p["level"] == lvl) for lvl in ("alert", "action", "alarm", "ok")}
    assert counts == l5["report"]
    assert {c: points[c]["level"] for c in l5["points"]} == l5["points"]
    pdf = await client.get(f"{BASE}/projects/{project_id}/report.pdf?locale=de", headers=header)
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")


async def test_one_import_of_all_four_epochs_opens_both_crossings(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    await _setup(client, header, project_id)
    text = (DEMO / "monitoring_epochs_1-3.csv").read_text(encoding="utf-8") + (
        (DEMO / "monitoring_epoch_4.csv").read_text(encoding="utf-8").split("\n", 1)[1]
    )
    result = (await client.post(f"{BASE}/projects/{project_id}/readings", json={"text": text}, headers=header)).json()
    assert [a["level"] for a in result["alerts"]] == ["alert", "action"]


async def test_switching_the_profile_rejudges_the_history(client: AsyncClient, header: dict, project_id: str) -> None:
    await _setup(client, header, project_id, epochs=4)
    profile = await client.post(
        f"{BASE}/projects/{project_id}/profiles",
        json={"name": "Tight wall", "alert_mm": 2, "action_mm": 4, "alarm_mm": 8, "reference": "Designer's note"},
        headers=header,
    )
    assert profile.status_code == 201, profile.text
    key = profile.json()["key"]
    assert key.startswith("project:")
    keys = [p["key"] for p in (await client.get(f"{BASE}/projects/{project_id}/profiles", headers=header)).json()["items"]]
    assert keys[0] == "demo" and key in keys
    switched = await client.put(f"{BASE}/projects/{project_id}/settings", json={"profile_key": key}, headers=header)
    assert switched.status_code == 200
    points = await _points(client, header, project_id)
    assert (points["MP-01"]["level"], points["MP-02"]["level"]) == ("alarm", "alert")  # -23 mm, -3 mm
    unknown = await client.put(
        f"{BASE}/projects/{project_id}/settings", json={"profile_key": "pack:xx.none"}, headers=header
    )
    assert unknown.status_code == 422
    cleared = await client.put(f"{BASE}/projects/{project_id}/settings", json={"profile_key": ""}, headers=header)
    assert cleared.json()["profile"] is None
    assert {p["level"] for p in (await _points(client, header, project_id)).values()} == {"none"}


async def test_a_bad_profile_is_refused(client: AsyncClient, header: dict, project_id: str) -> None:
    for body in ({"name": "x", "alert_mm": 10, "action_mm": 5}, {"name": "x"}, {"name": "", "alert_mm": 1}):
        r = await client.post(f"{BASE}/projects/{project_id}/profiles", json=body, headers=header)
        assert r.status_code == 422, body


async def test_import_problems_are_counted_and_good_rows_still_land(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    await _setup(client, header, project_id)
    text = "point,date,z\nMP-01,2026-10-09,34.512\nMP-02,tomorrow,34.300\nMP-01,2026-10-16,abc\n"
    result = (await client.post(f"{BASE}/projects/{project_id}/readings", json={"text": text}, headers=header)).json()
    assert (result["rows_read"], result["readings_added"], result["problem_count"]) == (3, 1, 2)
    assert [p["line"] for p in result["problems"]] == [3, 4]


async def test_a_different_value_for_an_imported_date_is_a_problem_not_an_overwrite(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    await _setup(client, header, project_id, epochs=3)
    text = "point,date,z\nMP-01,2026-10-09,34.600\n"
    result = (await client.post(f"{BASE}/projects/{project_id}/readings", json={"text": text}, headers=header)).json()
    assert (result["readings_added"], result["problem_count"]) == (0, 1)
    assert "different reading" in result["problems"][0]["message"]
    assert (await _points(client, header, project_id))["MP-01"]["baseline_value"] == 34.512


async def test_a_row_without_the_numbers_the_axis_needs_is_a_problem(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    await _setup(client, header, project_id)
    text = "point,date,e,n\nMP-01,2026-10-09,100,200\n"
    result = (await client.post(f"{BASE}/projects/{project_id}/readings", json={"text": text}, headers=header)).json()
    assert (result["readings_added"], result["problem_count"]) == (0, 1)
    assert "no Z" in result["problems"][0]["message"]


async def test_prism_points_are_read_in_three_dimensions(client: AsyncClient, header: dict, project_id: str) -> None:
    text = "point,date,e,n,z\nPR-1,2026-10-09,100,200,10\nPR-1,2026-10-16,100.003,200.004,9.988\n"
    result = (await client.post(f"{BASE}/projects/{project_id}/readings", json={"text": text}, headers=header)).json()
    assert result["new_points"] == ["PR-1"]
    prism = (await _points(client, header, project_id))["PR-1"]
    assert (prism["point_type"], prism["axis"], prism["displacement_mm"]) == ("prism", "3d", 13.0)


async def test_points_can_be_added_edited_and_removed_with_their_readings(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    made = await client.post(
        f"{BASE}/projects/{project_id}/points",
        json={"code": "IN-1", "point_type": "inclinometer", "location": "Shaft 2"},
        headers=header,
    )
    assert made.status_code == 201, made.text
    assert made.json()["axis"] == "value"
    duplicate = await client.post(f"{BASE}/projects/{project_id}/points", json={"code": "IN-1"}, headers=header)
    assert duplicate.status_code == 409
    point_id = made.json()["id"]
    edited = await client.patch(f"{BASE}/points/{point_id}", json={"name": "Inclinometer 1"}, headers=header)
    assert edited.json()["name"] == "Inclinometer 1"
    text = "point,date,value\nIN-1,2026-10-09,1.0000\nIN-1,2026-10-16,1.0050\n"
    await client.post(f"{BASE}/projects/{project_id}/readings", json={"text": text}, headers=header)
    assert (await _points(client, header, project_id))["IN-1"]["displacement_mm"] == 5.0
    assert (await client.delete(f"{BASE}/points/{point_id}", headers=header)).status_code == 204
    assert await _points(client, header, project_id) == {}
    assert (await client.get(f"{BASE}/points/{point_id}", headers=header)).status_code == 404


async def test_roles_and_ownership(
    client: AsyncClient, header: dict, stranger: dict, viewer: dict, project_id: str
) -> None:
    await _setup(client, header, project_id, epochs=4)
    points = await _points(client, header, project_id)
    mp1 = points["MP-01"]["id"]
    text = "point,date,z\nMP-01,2026-11-06,34.480\n"
    # Not a member of the project: nothing is visible or writable.
    for call in (
        client.get(f"{BASE}/projects/{project_id}/points", headers=stranger),
        client.get(f"{BASE}/points/{mp1}", headers=stranger),
        client.post(f"{BASE}/projects/{project_id}/readings", json={"text": text}, headers=stranger),
        client.post(f"{BASE}/points/{mp1}/acknowledge", json={}, headers=stranger),
    ):
        assert (await call).status_code in (403, 404)
    # A viewer reads but never writes or acknowledges.
    assert (
        await client.post(f"{BASE}/projects/{project_id}/readings", json={"text": text}, headers=viewer)
    ).status_code == 403
    assert (await client.post(f"{BASE}/points/{mp1}/acknowledge", json={}, headers=viewer)).status_code == 403
    assert (await client.get(f"{BASE}/projects/{project_id}/summary", headers=viewer)).status_code in (200, 403, 404)
    # The anonymous caller gets nothing.
    assert (await client.get(f"{BASE}/projects/{project_id}/points")).status_code in (401, 403)
