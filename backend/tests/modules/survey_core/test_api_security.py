# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Roles, project boundaries and hostile or odd input on the survey register API, against a real database."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests.modules.survey_core.conftest import login

BASE = "/api/v1/survey-core"
CSV = "CP1,389000.000,5819000.000,34.000,CP\nCP2,389110.000,5818990.000,35.100,CP\n"
FORBIDDEN = (403, 404)


async def _member(client: AsyncClient, owner: dict, project_id: str, role: str) -> dict:
    """A new user of ``role`` on the owner's project team."""
    headers = await login(client, role)
    me = await client.get("/api/v1/users/me", headers=headers)
    response = await client.post(
        f"/api/v1/projects/{project_id}/members", json={"user_id": me.json()["id"], "role": "member"}, headers=owner
    )
    assert response.status_code in (200, 201), response.text
    return headers


async def _crs(client: AsyncClient, who: dict, project_id: str, epsg: int = 32633, **extra):
    return await client.put(f"{BASE}/projects/{project_id}/crs", json={"horizontal_epsg": epsg, **extra}, headers=who)


async def _import(client: AsyncClient, who: dict, project_id: str, text: str = CSV, **extra):
    body = {"text": text, "column_preset": "PENZD", "delimiter": ",", "filename": "f.csv", **extra}
    return await client.post(f"{BASE}/projects/{project_id}/import", json=body, headers=who)


# -- sign-in -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/projects/{p}/crs"),
        ("PUT", "/projects/{p}/crs"),
        ("POST", "/projects/{p}/crs/confirm"),
        ("POST", "/projects/{p}/import"),
        ("POST", "/projects/{p}/import/preview"),
        ("GET", "/projects/{p}/points"),
        ("GET", "/projects/{p}/point-sets"),
        ("GET", "/projects/{p}/summary"),
        ("POST", "/projects/{p}/validate"),
        ("GET", "/crs/search?q=utm"),
        ("POST", "/transform"),
    ],
)
async def test_every_route_needs_a_sign_in(client: AsyncClient, method: str, path: str) -> None:
    response = await client.request(method, BASE + path.format(p=uuid.uuid4()), json={})
    assert response.status_code in (401, 403)


# -- who confirms ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("role", "status"), [("viewer", 403), ("editor", 403), ("manager", 200), ("surveyor", 200), ("admin", 200)]
)
async def test_who_may_confirm_the_project_crs(
    client: AsyncClient, header: dict, project_id: str, role: str, status: int
) -> None:
    assert (await _crs(client, header, project_id, source="detected", detected_confidence=0.9)).status_code == 200
    who = await _member(client, header, project_id, role)
    response = await client.post(f"{BASE}/projects/{project_id}/crs/confirm", headers=who)
    assert response.status_code == status, response.text
    if status == 200:
        assert response.json()["confirmed_at"] is not None


async def test_confirming_before_any_crs_exists_is_a_404_not_a_500(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    assert (await client.post(f"{BASE}/projects/{project_id}/crs/confirm", headers=header)).status_code == 404


async def test_a_refused_confirmation_leaves_the_crs_unconfirmed(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    await _crs(client, header, project_id, source="detected", detected_confidence=0.9)
    # detected by the admin counts as confirmed by the admin; an editor's acceptance does not.
    editor = await _member(client, header, project_id, "editor")
    await _crs(client, editor, project_id, 25833, source="detected", detected_confidence=0.7)
    await client.post(f"{BASE}/projects/{project_id}/crs/confirm", headers=editor)
    state = (await client.get(f"{BASE}/projects/{project_id}/crs", headers=header)).json()
    assert state["crs"]["confirmed_at"] is None


async def test_an_editor_cannot_move_a_register_that_has_points_but_a_manager_can_with_the_code(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    editor = await _member(client, header, project_id, "editor")
    manager = await _member(client, header, project_id, "manager")
    assert (await _crs(client, editor, project_id)).status_code == 200
    assert (await _import(client, editor, project_id)).status_code == 201
    assert (await _crs(client, editor, project_id, 25833, confirm_text="25833")).status_code == 403
    assert (await _crs(client, manager, project_id, 25833)).status_code == 409
    assert (await _crs(client, manager, project_id, 25833, confirm_text="wrong")).status_code == 409
    assert (await _crs(client, manager, project_id, 25833, confirm_text=" 25833 ")).status_code == 200
    # the same system again is not a change
    assert (await _crs(client, editor, project_id, 25833)).status_code == 200


# -- viewer ------------------------------------------------------------------------------------------------------


async def test_a_viewer_reads_everything_and_changes_nothing(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    await _crs(client, header, project_id)
    result = (await _import(client, header, project_id)).json()
    set_id = result["point_set"]["id"]
    viewer = await _member(client, header, project_id, "viewer")
    for path in ("crs", "points", "point-sets", "summary"):
        assert (await client.get(f"{BASE}/projects/{project_id}/{path}", headers=viewer)).status_code == 200, path
    assert (await client.post(f"{BASE}/projects/{project_id}/validate", headers=viewer)).status_code == 200
    assert (await client.get(f"{BASE}/crs/search", params={"q": "utm"}, headers=viewer)).status_code == 200
    body = {"text": CSV, "column_preset": "PENZD"}
    refused = [
        await _crs(client, viewer, project_id, 25833),
        await client.post(f"{BASE}/projects/{project_id}/import", json=body, headers=viewer),
        await client.post(f"{BASE}/projects/{project_id}/import/preview", json=body, headers=viewer),
        await client.post(f"{BASE}/point-sets/{set_id}/declare-crs", json={"epsg": 4326}, headers=viewer),
        await client.delete(f"{BASE}/point-sets/{set_id}", headers=viewer),
    ]
    assert [r.status_code for r in refused] == [403] * 5
    sets = (await client.get(f"{BASE}/projects/{project_id}/point-sets", headers=header)).json()["items"]
    assert [s["id"] for s in sets] == [set_id]
    assert sets[0]["stored_epsg"] == 32633


# -- another project, another tenant -----------------------------------------------------------------------------


async def test_a_user_outside_the_project_reaches_nothing_of_it(
    client: AsyncClient, header: dict, project_id: str, stranger: dict
) -> None:
    await _crs(client, header, project_id)
    set_id = (await _import(client, header, project_id)).json()["point_set"]["id"]
    p = f"{BASE}/projects/{project_id}"
    body = {"text": CSV, "column_preset": "PENZD"}
    calls = [
        await client.get(f"{p}/crs", headers=stranger),
        await _crs(client, stranger, project_id, 25833),
        await client.post(f"{p}/crs/confirm", headers=stranger),
        await client.post(f"{p}/import", json=body, headers=stranger),
        await client.post(f"{p}/import/preview", json=body, headers=stranger),
        await client.get(f"{p}/points", headers=stranger),
        await client.get(f"{p}/point-sets", headers=stranger),
        await client.get(f"{p}/summary", headers=stranger),
        await client.post(f"{p}/validate", headers=stranger),
        await client.post(f"{BASE}/point-sets/{set_id}/declare-crs", json={"epsg": 4326}, headers=stranger),
        await client.delete(f"{BASE}/point-sets/{set_id}", headers=stranger),
    ]
    assert [c.status_code for c in calls if c.status_code not in FORBIDDEN] == []
    assert all("CP1" not in c.text and "389000" not in c.text for c in calls)
    # nothing changed
    assert (await client.get(f"{p}/crs", headers=header)).json()["crs"]["horizontal_epsg"] == 32633
    assert (await client.get(f"{p}/points", headers=header)).json()["total"] == 2
    assert (await client.get(f"{p}/point-sets", headers=header)).json()["items"][0]["stored_epsg"] == 32633


async def test_a_missing_project_and_someone_elses_look_the_same(
    client: AsyncClient, header: dict, project_id: str, stranger: dict
) -> None:
    other = await client.get(f"{BASE}/projects/{project_id}/points", headers=stranger)
    missing = await client.get(f"{BASE}/projects/{uuid.uuid4()}/points", headers=stranger)
    assert other.status_code == missing.status_code
    assert other.json() == missing.json()
    set_other = await client.delete(f"{BASE}/point-sets/{uuid.uuid4()}", headers=stranger)
    assert set_other.status_code == 404


async def test_a_member_of_project_b_cannot_touch_project_a(client: AsyncClient, header: dict, project_id: str) -> None:
    owner_b = await login(client, "editor")
    made = await client.post(
        "/api/v1/projects/", json={"name": f"B {uuid.uuid4().hex[:5]}", "currency": "EUR"}, headers=owner_b
    )
    assert made.status_code in (200, 201), made.text
    project_b = made.json()["id"]
    assert (await _crs(client, owner_b, project_b)).status_code == 200
    assert (await _import(client, owner_b, project_b)).status_code == 201
    await _crs(client, header, project_id)
    set_a = (await _import(client, header, project_id, "A1,1.0,2.0,3.0\n")).json()["point_set"]["id"]

    assert (await client.get(f"{BASE}/projects/{project_id}/points", headers=owner_b)).status_code in FORBIDDEN
    assert (await client.delete(f"{BASE}/point-sets/{set_a}", headers=owner_b)).status_code in FORBIDDEN
    assert (
        await client.post(f"{BASE}/point-sets/{set_a}/declare-crs", json={"epsg": 4326}, headers=owner_b)
    ).status_code in FORBIDDEN
    # A's set id used as a filter on B's register finds nothing of A.
    leak = await client.get(f"{BASE}/projects/{project_b}/points", params={"set_id": set_a}, headers=owner_b)
    assert leak.status_code == 200
    assert leak.json()["total"] == 0
    # B's owner keeps the full workflow on B and the two registers stay apart.
    assert (await client.get(f"{BASE}/projects/{project_b}/points", headers=owner_b)).json()["total"] == 2
    assert (await client.get(f"{BASE}/projects/{project_id}/points", headers=header)).json()["total"] == 1


async def test_the_same_point_ids_in_two_projects_are_not_duplicates(client: AsyncClient, header: dict) -> None:
    ids = []
    for _ in range(2):
        made = await client.post("/api/v1/projects/", json={"name": f"P {uuid.uuid4().hex[:5]}"}, headers=header)
        pid = made.json()["id"]
        ids.append(pid)
        await _crs(client, header, pid)
        assert (await _import(client, header, pid, "CP1,1.0,2.0,3.0\n")).json()["problems"] == []
        report = (await client.post(f"{BASE}/projects/{pid}/validate", headers=header)).json()
        assert report["findings"] == []
    # the same id elsewhere in the same project is a conflict; the other project never sees it
    second = await _import(client, header, ids[1], "CP1,500.0,2.0,3.0\n")
    assert second.json()["problems"][0]["rule_id"] == "SRV-003"
    assert (await _import(client, header, ids[0], "CP1,1.0,2.0,3.0\n")).json()["problems"] == []


# -- roles that do not exist yet ---------------------------------------------------------------------------------


async def test_an_admin_can_give_a_user_the_surveyor_role(client: AsyncClient, header: dict) -> None:
    """The role is honoured at run time (survey.confirm) but user admin must be able to assign it."""
    tag = uuid.uuid4().hex[:8]
    created = await client.post(
        "/api/v1/users/",
        json={"email": f"surveyor-{tag}@test.io", "password": f"Surveyor{tag}99", "full_name": "S", "role": "surveyor"},
        headers=header,
    )
    assert created.status_code == 201, created.text
    assert created.json()["role"] == "surveyor"
    changed = await client.patch(f"/api/v1/users/{created.json()['id']}", json={"role": "editor"}, headers=header)
    assert changed.status_code == 200, changed.text
    back = await client.patch(f"/api/v1/users/{created.json()['id']}", json={"role": "surveyor"}, headers=header)
    assert back.status_code == 200, back.text


async def test_a_surveyor_imports_and_confirms(client: AsyncClient, header: dict, project_id: str) -> None:
    surveyor = await _member(client, header, project_id, "surveyor")
    assert (await _crs(client, surveyor, project_id, source="detected", detected_confidence=0.6)).status_code == 200
    assert (await _import(client, surveyor, project_id)).status_code == 201
    assert (await client.post(f"{BASE}/projects/{project_id}/crs/confirm", headers=surveyor)).status_code == 200


# -- input the register must survive -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"text": ""},
        {"text": "# nothing\n\n"},
        {"text": "@@@\n;;;\n", "column_preset": "PENZD"},
        {"text": "a,b\n", "columns": ["point_id", "e"]},
        {"text": "{}", "file_format": "geojson"},
        {"text": "[]", "file_format": "geojson"},
    ],
)
async def test_an_unreadable_file_is_a_422_with_nothing_saved(
    client: AsyncClient, header: dict, project_id: str, body: dict
) -> None:
    await _crs(client, header, project_id)
    response = await client.post(f"{BASE}/projects/{project_id}/import", json=body, headers=header)
    assert response.status_code == 422, response.text
    assert (await client.get(f"{BASE}/projects/{project_id}/point-sets", headers=header)).json()["items"] == []


@pytest.mark.parametrize(
    "extra",
    [
        {"duplicate_policy": "keep_all"},
        {"default_kind": "fence"},
        {"file_format": "dxf"},
        {"delimiter": "abc"},
        {"source_epsg": 12},
        {"source_epsg": 10_000_000},
        {"columns": ["point_id", "e", "n", "bogus"]},
        {"text": "x" * 6_000_001},
    ],
)
async def test_bad_options_are_refused_before_anything_is_read(
    client: AsyncClient, header: dict, project_id: str, extra: dict
) -> None:
    response = await client.post(
        f"{BASE}/projects/{project_id}/import/preview", json={"text": CSV, **extra}, headers=header
    )
    assert response.status_code == 422


async def test_an_unknown_source_system_is_a_422_not_a_500(client: AsyncClient, header: dict, project_id: str) -> None:
    await _crs(client, header, project_id)
    response = await _import(client, header, project_id, source_epsg=999999)
    assert response.status_code == 422


async def test_a_file_over_five_megabytes_is_a_422_in_preview_and_import(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    text = "P1,389000.123,5819000.456,34.1\n" * 180_000
    for path in ("import/preview", "import"):
        response = await client.post(f"{BASE}/projects/{project_id}/{path}", json={"text": text}, headers=header)
        assert response.status_code == 422, (path, response.status_code)


async def test_a_coordinate_beyond_the_column_is_a_422_not_a_500(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    await _crs(client, header, project_id)
    response = await _import(client, header, project_id, "P1,1e12,5.0,3.0\nP2,1.0,2.0,3.0\n")
    assert response.status_code in (201, 422)
    if response.status_code == 201:
        assert response.json()["imported"] == 1
        assert response.json()["problems"][0]["rule_id"] == "IMP-001"


async def test_coordinates_come_back_with_at_most_four_decimals(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    await _crs(client, header, project_id)
    await _import(client, header, project_id, "P1,389000.12349,5819000.98761,34.00004\n")
    item = (await client.get(f"{BASE}/projects/{project_id}/points", headers=header)).json()["items"][0]
    for key, exact in (("e", "389000.12349"), ("n", "5819000.98761"), ("z", "34.00004")):
        shown = Decimal(str(item[key]))
        assert shown.as_tuple().exponent >= -4, key
        assert abs(shown - Decimal(exact)) <= Decimal("0.00005"), key


async def test_zero_and_negative_values_survive_the_round_trip(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    await _crs(client, header, project_id, is_local_grid=True, horizontal_epsg=None, local_origin_e=0, local_origin_n=0)
    await _import(client, header, project_id, "O,0,0,0\nW,-120.25,-35.5,-2.125\n")
    items = {
        i["point_id"]: i
        for i in (await client.get(f"{BASE}/projects/{project_id}/points", headers=header)).json()["items"]
    }
    assert (items["O"]["e"], items["O"]["n"], items["O"]["z"]) == (0.0, 0.0, 0.0)
    assert (items["W"]["e"], items["W"]["n"], items["W"]["z"]) == (-120.25, -35.5, -2.125)


async def test_a_local_grid_project_needs_no_epsg_on_its_point_sets(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    refused = await _crs(client, header, project_id, is_local_grid=True, horizontal_epsg=None)
    assert refused.status_code == 422
    ok = await _crs(
        client, header, project_id, is_local_grid=True, horizontal_epsg=None, local_origin_e=1000, local_origin_n=2000
    )
    assert ok.status_code == 200
    assert ok.json()["horizontal_epsg"] is None
    result = (await _import(client, header, project_id)).json()
    assert result["point_set"]["stored_epsg"] is None
    report = (await client.post(f"{BASE}/projects/{project_id}/validate", headers=header)).json()
    assert report["findings"] == []


@pytest.mark.parametrize(
    "extra",
    [
        {"local_scale_factor": 1.5},
        {"local_scale_factor": 0},
        {"local_rotation_deg": 400},
        {"vertical_mode": "epsg"},
        {"vertical_mode": "epsg", "vertical_epsg": 999999},
        {"horizontal_epsg": 5778},
        {"horizontal_epsg": 999999},
        {"horizontal_epsg": 12},
        {"source": "guess"},
        {"detected_confidence": 1.5},
    ],
)
async def test_a_bad_crs_is_refused(client: AsyncClient, header: dict, project_id: str, extra: dict) -> None:
    response = await client.put(
        f"{BASE}/projects/{project_id}/crs", json={"horizontal_epsg": 32633, **extra}, headers=header
    )
    assert response.status_code == 422, response.text


async def test_a_vertical_system_can_be_added(client: AsyncClient, header: dict, project_id: str) -> None:
    response = await _crs(client, header, project_id, vertical_mode="epsg", vertical_epsg=5778)
    assert response.status_code == 200
    assert response.json()["vertical_epsg"] == 5778


async def test_transform_in_us_survey_feet_matches_the_published_example(client: AsyncClient, header: dict) -> None:
    response = await client.post(
        f"{BASE}/transform", json={"source_epsg": 4267, "target_epsg": 32040, "points": [[-96.0, 28.5]]}, headers=header
    )
    body = response.json()
    assert body["target"]["unit"] == "US survey foot"
    assert body["points"][0][0] == pytest.approx(2963503.91, abs=0.01)
    assert body["points"][0][1] == pytest.approx(254759.80, abs=0.01)


async def test_transform_refuses_a_point_that_cannot_be_projected_and_an_oversized_list(
    client: AsyncClient, header: dict
) -> None:
    far = await client.post(
        f"{BASE}/transform", json={"source_epsg": 4326, "target_epsg": 32633, "points": [[105.0, 0.0]]}, headers=header
    )
    assert far.status_code == 422
    big = await client.post(
        f"{BASE}/transform",
        json={"source_epsg": 4326, "target_epsg": 32633, "points": [[13.0, 52.0]] * 10_001},
        headers=header,
    )
    assert big.status_code == 422


async def test_paging_and_filters_on_a_large_register(client: AsyncClient, header: dict, project_id: str) -> None:
    await _crs(client, header, project_id)
    text = "".join(
        f"P{i},{389000 + i % 500}.5,{5819000 + i // 500}.5,{30 + i % 9}.1,{'CP' if i % 100 == 0 else 'TREE'}\n"
        for i in range(20_000)
    )
    result = await _import(client, header, project_id, text)
    assert result.status_code == 201, result.text
    assert result.json()["imported"] == 20_000
    points = f"{BASE}/projects/{project_id}/points"
    page = (await client.get(points, params={"limit": 1000, "offset": 19_500}, headers=header)).json()
    assert (page["total"], len(page["items"])) == (20_000, 500)
    assert (await client.get(points, params={"limit": 1000, "offset": 20_000}, headers=header)).json()["items"] == []
    assert (await client.get(points, params={"kind": "control"}, headers=header)).json()["total"] == 200
    assert (await client.get(points, params={"code": "TREE"}, headers=header)).json()["total"] == 19_800
    assert (await client.get(points, params={"q": "P19999"}, headers=header)).json()["total"] == 1
    for bad in ({"limit": 1001}, {"limit": 0}, {"offset": -1}, {"kind": "fence"}):
        assert (await client.get(points, params=bad, headers=header)).status_code == 422, bad
    summary = (await client.get(f"{BASE}/projects/{project_id}/summary", headers=header)).json()
    assert (summary["points"], summary["control"], summary["findings"]) == (20_000, 200, 0)


async def test_filters_treat_wildcards_and_quotes_as_plain_text(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    await _crs(client, header, project_id)
    await _import(client, header, project_id, "CP1,1.0,2.0,3.0\nCP_2,4.0,5.0,6.0\n")
    points = f"{BASE}/projects/{project_id}/points"
    for q in ("%", "_", "' OR 1=1 --", "\\"):
        response = await client.get(points, params={"q": q}, headers=header)
        assert response.status_code == 200
        assert response.json()["total"] <= 1, q


async def test_right_to_left_names_round_trip_through_the_register(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    await _crs(client, header, project_id)
    text = "نقطة-١,389000.0,5819000.0,34.0,CP,عمود\nנקודה-2,389010.0,5819010.0,35.0,BM,מפלס\n"
    result = await _import(
        client,
        header,
        project_id,
        text,
        columns=["point_id", "e", "n", "z", "code", "description"],
        column_preset="",
        name="مسح الموقع",
        instrument="محطة شاملة",
        surveyed_by="דנה",
    )
    assert result.status_code == 201, result.text
    sets = (await client.get(f"{BASE}/projects/{project_id}/point-sets", headers=header)).json()["items"]
    assert (sets[0]["name"], sets[0]["instrument"], sets[0]["surveyed_by"]) == ("مسح الموقع", "محطة شاملة", "דנה")
    items = (await client.get(f"{BASE}/projects/{project_id}/points", params={"q": "نقطة"}, headers=header)).json()[
        "items"
    ]
    assert [(i["point_id"], i["description"], i["kind"]) for i in items] == [("نقطة-١", "عمود", "control")]
    report = (
        await client.post(f"{BASE}/projects/{project_id}/validate", params={"locale": "ar"}, headers=header)
    ).json()
    assert report["findings"] == []


async def test_the_validation_report_speaks_the_requested_language(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    await _import(client, header, project_id)
    for locale, word in (("de", "Koordinatensystem"), ("en", "CRS")):
        report = (
            await client.post(f"{BASE}/projects/{project_id}/validate", params={"locale": locale}, headers=header)
        ).json()
        assert report["findings"][0]["rule_id"] == "SRV-001"
        assert word in report["findings"][0]["message"], locale
    assert (
        await client.post(f"{BASE}/projects/{project_id}/validate", params={"locale": "x" * 11}, headers=header)
    ).status_code == 422


async def test_an_empty_project_has_an_empty_register(client: AsyncClient, header: dict, project_id: str) -> None:
    p = f"{BASE}/projects/{project_id}"
    state = (await client.get(f"{p}/crs", headers=header)).json()
    assert (state["crs"], state["point_count"]) == (None, 0)
    assert (await client.get(f"{p}/points", headers=header)).json() == {"items": [], "total": 0}
    assert (await client.get(f"{p}/point-sets", headers=header)).json()["items"] == []
    summary = (await client.get(f"{p}/summary", headers=header)).json()
    assert (summary["points"], summary["point_sets"], summary["findings"], summary["last_import"]) == (0, 0, 0, None)
    report = (await client.post(f"{p}/validate", headers=header)).json()
    assert (report["error_count"], report["warning_count"], report["findings"]) == (0, 0, [])


async def test_deleting_a_set_twice_and_declaring_on_a_deleted_set(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    await _crs(client, header, project_id)
    set_id = (await _import(client, header, project_id)).json()["point_set"]["id"]
    assert (await client.delete(f"{BASE}/point-sets/{set_id}", headers=header)).status_code == 204
    assert (await client.delete(f"{BASE}/point-sets/{set_id}", headers=header)).status_code == 404
    assert (
        await client.post(f"{BASE}/point-sets/{set_id}/declare-crs", json={"epsg": 4326}, headers=header)
    ).status_code == 404
    unknown = await client.post(f"{BASE}/point-sets/{uuid.uuid4()}/declare-crs", json={"epsg": 999999}, headers=header)
    assert unknown.status_code == 404


async def test_declaring_an_unknown_system_on_a_set_is_a_422(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    set_id = (await _import(client, header, project_id)).json()["point_set"]["id"]
    assert (
        await client.post(f"{BASE}/point-sets/{set_id}/declare-crs", json={"epsg": 999999}, headers=header)
    ).status_code == 422
    assert (
        await client.post(f"{BASE}/point-sets/{set_id}/declare-crs", json={"epsg": 5}, headers=header)
    ).status_code == 422
