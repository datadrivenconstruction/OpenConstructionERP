"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Construction-control deletion guards: evidence refuses to be deleted.

Every ``update_*`` in the module already refuses to edit a record the workflow has
locked. Not one ``delete_*`` refused anything, and because every cross-record link
in the module is a soft ``String(36)`` rather than a database foreign key,
PostgreSQL refused nothing either. A signed as-built, a released gate and an
issued completion certificate could all be removed outright, and an inspection
could be removed out from under the non-conformance report raised against it.

These tests pin both halves of the guard:

* **Locked by state** - a record acted on through the workflow refuses with 409.
* **Held by another record** - a record something still points at refuses with
  409 whose text names the holders by count and kind.

They also pin the negative: a draft nobody has touched still deletes cleanly, so
the guard does not turn the register read-only.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

BASE = "/api/v1/construction-control"


# -- Fixtures ---------------------------------------------------------------


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    """Boot the FastAPI app once per module."""
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.construction_control import models as _cc_models  # noqa: F401
        from app.modules.ncr import models as _ncr_models  # noqa: F401
        from app.modules.projects import models as _project_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _set_role(email: str, *, role: str) -> None:
    """Force ``role`` and ``is_active=True`` on a user via a direct DB write."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await s.commit()


@pytest_asyncio.fixture(scope="module")
async def world(http_client):
    """One manager with a project to hang records on.

    Manager, not editor: every ``cc.*.delete`` permission sits at ``Role.MANAGER``,
    as do verify, sign, release and issue. An editor is refused with 403 before the
    deletion guard is ever reached, so an editor fixture would measure the RBAC
    gate rather than the guard under test.
    """
    email = f"del-{uuid.uuid4().hex[:8]}@cc-test.io"
    password = f"CcDel{uuid.uuid4().hex[:6]}9"
    reg = await http_client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Deletion Guard"},
    )
    assert reg.status_code in (200, 201), reg.text
    uid = reg.json()["id"]
    await _set_role(email, role="manager")

    login = await http_client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    from app.database import async_session_factory
    from app.modules.projects.models import Project

    project_id = uuid.uuid4()
    async with async_session_factory() as s:
        s.add(
            Project(
                id=project_id,
                name="Deletion-Guard-Project",
                owner_id=uuid.UUID(uid),
                status="active",
                currency="EUR",
            )
        )
        await s.commit()

    return {"headers": headers, "project_id": str(project_id)}


# -- Helpers ----------------------------------------------------------------


async def _new_criterion(client: AsyncClient, world: dict, *, code: str | None = None) -> str:
    resp = await client.post(
        f"{BASE}/criteria",
        json={
            "project_id": world["project_id"],
            "code": code or f"AC-{uuid.uuid4().hex[:6].upper()}",
            "title": "Cube compressive strength",
            "acceptance_rule": "min",
            "unit": "MPa",
            "tolerance_lower": "30",
        },
        headers=world["headers"],
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _new_inspection(client: AsyncClient, world: dict, *, criterion_id: str | None = None) -> str:
    body: dict = {
        "project_id": world["project_id"],
        "inspection_type": "acceptance",
        "party_role": "qa",
        "title": "Acceptance of wall W-12",
    }
    if criterion_id is not None:
        body["criterion_id"] = criterion_id
    resp = await client.post(f"{BASE}/inspections", json=body, headers=world["headers"])
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _new_material(client: AsyncClient, world: dict) -> str:
    resp = await client.post(
        f"{BASE}/materials",
        json={
            "project_id": world["project_id"],
            "name": "Ready-mix concrete C30/37",
            "material_type": "concrete",
            "description": "C30/37 ready mix",
            "cert_type": "3.1",
        },
        headers=world["headers"],
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _new_test_result(client: AsyncClient, world: dict, **links: str) -> str:
    body: dict = {
        "project_id": world["project_id"],
        "title": "28-day cube compressive strength",
        "unit": "MPa",
    }
    body.update(links)
    resp = await client.post(f"{BASE}/test-results", json=body, headers=world["headers"])
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _new_asbuilt(client: AsyncClient, world: dict, *, criterion_id: str | None = None) -> str:
    body: dict = {
        "project_id": world["project_id"],
        "title": "Slab level survey, grid C4",
        "capture_method": "total_station",
        "accuracy_class": "survey",
    }
    if criterion_id is not None:
        body["criterion_id"] = criterion_id
    resp = await client.post(f"{BASE}/asbuilt", json=body, headers=world["headers"])
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _new_gate(client: AsyncClient, world: dict, **extra: object) -> str:
    body: dict = {
        "project_id": world["project_id"],
        "point_type": "hold",
        "title": "Pre-pour hold point",
    }
    body.update(extra)
    resp = await client.post(f"{BASE}/gates", json=body, headers=world["headers"])
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _new_handover(client: AsyncClient, world: dict) -> str:
    resp = await client.post(
        f"{BASE}/handover",
        json={
            "project_id": world["project_id"],
            "title": "Sectional completion, east wing",
            "completion_regime": "practical",
            "completion_type": "sectional",
        },
        headers=world["headers"],
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# -- A draft nobody acted on still deletes ----------------------------------


@pytest.mark.asyncio
async def test_untouched_drafts_delete_cleanly(http_client, world):
    """The guard must not turn the register read-only: fresh drafts still go."""
    h = world["headers"]
    for path, record_id in (
        ("criteria", await _new_criterion(http_client, world)),
        ("inspections", await _new_inspection(http_client, world)),
        ("materials", await _new_material(http_client, world)),
        ("test-results", await _new_test_result(http_client, world)),
        ("asbuilt", await _new_asbuilt(http_client, world)),
        ("gates", await _new_gate(http_client, world)),
        ("handover", await _new_handover(http_client, world)),
    ):
        resp = await http_client.delete(f"{BASE}/{path}/{record_id}", headers=h)
        assert resp.status_code == 204, f"a fresh draft {path} record must delete: {resp.status_code} {resp.text}"
        gone = await http_client.get(f"{BASE}/{path}/{record_id}", headers=h)
        assert gone.status_code == 404, f"{path} record survived its delete"


# -- Locked by state --------------------------------------------------------


@pytest.mark.asyncio
async def test_inspection_with_a_recorded_result_refuses_deletion(http_client, world):
    """A recorded verdict is the account of what was checked; it stays."""
    h = world["headers"]
    inspection_id = await _new_inspection(http_client, world)
    recorded = await http_client.post(
        f"{BASE}/inspections/{inspection_id}/record-result",
        json={"result": "pass", "measured_value": "34"},
        headers=h,
    )
    assert recorded.status_code == 200, recorded.text
    assert recorded.json()["status"] == "passed"

    resp = await http_client.delete(f"{BASE}/inspections/{inspection_id}", headers=h)
    assert resp.status_code == 409, f"a passed inspection must refuse deletion, got {resp.status_code}"
    detail = resp.json()["detail"]
    assert "passed" in detail
    assert "cannot be deleted" in detail

    still_there = await http_client.get(f"{BASE}/inspections/{inspection_id}", headers=h)
    assert still_there.status_code == 200, "the refused inspection must still be on the register"


@pytest.mark.asyncio
async def test_reviewed_material_refuses_deletion(http_client, world):
    """A conformity decision is evidence the material was accepted onto the works."""
    h = world["headers"]
    material_id = await _new_material(http_client, world)
    reviewed = await http_client.post(
        f"{BASE}/materials/{material_id}/review",
        json={"decision": "pass", "notes": "Certificate 3.1 checked against the order."},
        headers=h,
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["status"] == "accepted"

    resp = await http_client.delete(f"{BASE}/materials/{material_id}", headers=h)
    assert resp.status_code == 409, f"an accepted material must refuse deletion, got {resp.status_code}"
    assert "cannot be deleted" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_recorded_test_result_refuses_deletion(http_client, world):
    """A recorded laboratory result is superseded by a re-test, never removed."""
    h = world["headers"]
    result_id = await _new_test_result(http_client, world)
    recorded = await http_client.post(
        f"{BASE}/test-results/{result_id}/record-result",
        json={"result": "pass", "measured_value": "36"},
        headers=h,
    )
    assert recorded.status_code == 200, recorded.text
    assert recorded.json()["status"] == "recorded"

    resp = await http_client.delete(f"{BASE}/test-results/{result_id}", headers=h)
    assert resp.status_code == 409, f"a recorded test result must refuse deletion, got {resp.status_code}"
    assert "recorded" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_verified_asbuilt_refuses_deletion(http_client, world):
    """Deleting is refused a step earlier than editing: at the conformity verdict."""
    h = world["headers"]
    criterion_id = await _new_criterion(http_client, world)
    record_id = await _new_asbuilt(http_client, world, criterion_id=criterion_id)

    surveyed = await http_client.post(
        f"{BASE}/asbuilt/{record_id}/record-survey",
        json={"measured_value": "31", "survey_date": "2026-05-04"},
        headers=h,
    )
    assert surveyed.status_code == 200, surveyed.text

    # Still deletable at "surveyed" - the edit guard also still allows edits here.
    verified = await http_client.post(
        f"{BASE}/asbuilt/{record_id}/verify",
        json={"notes": "Level within tolerance."},
        headers=h,
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "verified"

    resp = await http_client.delete(f"{BASE}/asbuilt/{record_id}", headers=h)
    assert resp.status_code == 409, f"a verified as-built must refuse deletion, got {resp.status_code}"
    assert "verified" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_released_gate_refuses_deletion(http_client, world):
    """A released gate carries the signature that let the work carry on."""
    h = world["headers"]
    gate_id = await _new_gate(http_client, world, point_type="witness", required_party_role="qc")
    released = await http_client.post(
        f"{BASE}/gates/{gate_id}/release",
        json={"party_role": "qc", "notes": "Witnessed on site."},
        headers=h,
    )
    assert released.status_code == 200, released.text
    assert released.json()["status"] == "released"

    resp = await http_client.delete(f"{BASE}/gates/{gate_id}", headers=h)
    assert resp.status_code == 409, f"a released gate must refuse deletion, got {resp.status_code}"
    assert "released" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_issued_handover_package_refuses_deletion(http_client, world):
    """An issued completion certificate is the evidence behind a contractual date."""
    h = world["headers"]
    package_id = await _new_handover(http_client, world)
    issued = await http_client.post(
        f"{BASE}/handover/{package_id}/issue",
        json={"issued_to": "Employer's representative", "override_reason": "No open items."},
        headers=h,
    )
    if issued.status_code != 200:
        # The completion gate blocks issuing while the project has open items;
        # clear it explicitly so the test measures deletion, not gating.
        override = await http_client.post(
            f"{BASE}/handover/{package_id}/override-gate",
            json={"reason": "Cleared for the deletion-guard test."},
            headers=h,
        )
        assert override.status_code == 200, override.text
        issued = await http_client.post(
            f"{BASE}/handover/{package_id}/issue",
            json={"issued_to": "Employer's representative"},
            headers=h,
        )
    assert issued.status_code == 200, issued.text
    assert issued.json()["status"] == "issued"

    resp = await http_client.delete(f"{BASE}/handover/{package_id}", headers=h)
    assert resp.status_code == 409, f"an issued handover package must refuse deletion, got {resp.status_code}"
    assert "issued" in resp.json()["detail"]


# -- Held by another record -------------------------------------------------


@pytest.mark.asyncio
async def test_criterion_held_by_records_refuses_with_named_holders(http_client, world):
    """The 409 names the holders by count and kind, not just "no"."""
    h = world["headers"]
    criterion_id = await _new_criterion(http_client, world)
    await _new_inspection(http_client, world, criterion_id=criterion_id)
    await _new_inspection(http_client, world, criterion_id=criterion_id)
    await _new_test_result(http_client, world, criterion_id=criterion_id)
    await _new_asbuilt(http_client, world, criterion_id=criterion_id)

    resp = await http_client.delete(f"{BASE}/criteria/{criterion_id}", headers=h)
    assert resp.status_code == 409, f"a criterion in use must refuse deletion, got {resp.status_code}"
    detail = resp.json()["detail"]
    assert "2 inspections" in detail, detail
    assert "1 test result" in detail, detail
    assert "1 as-built record" in detail, detail
    # Singular and plural are chosen per count, never "1 test results".
    assert "1 test results" not in detail
    assert "2 inspection " not in detail


@pytest.mark.asyncio
async def test_inspection_held_by_a_test_result_refuses(http_client, world):
    """A test result naming the inspection keeps it on the register."""
    h = world["headers"]
    inspection_id = await _new_inspection(http_client, world)
    await _new_test_result(http_client, world, inspection_id=inspection_id)

    resp = await http_client.delete(f"{BASE}/inspections/{inspection_id}", headers=h)
    assert resp.status_code == 409, f"a held inspection must refuse deletion, got {resp.status_code}"
    assert "1 test result" in resp.json()["detail"], resp.text


@pytest.mark.asyncio
async def test_inspection_held_by_its_ncr_refuses(http_client, world):
    """The cross-module holder counts too, and it is the holder branch that refuses.

    A failed inspection raises an NCR that points back through
    ``linked_inspection_id``. Reopening that inspection for re-inspection is a
    real workflow, which is why ``update_inspection`` blocks only ``closed`` and
    ``void``, and it is what puts the record back into a status the delete lock
    does not cover. The NCR still points at it, so the delete must still be
    refused, this time because something holds the row rather than because the
    row carries a verdict of its own.

    The reopened status is asserted on purpose. Recording a fail sets the status
    to ``failed``, which the delete lock covers, so without the reopen this test
    never reaches the holder count at all. If the update path ever stops
    accepting ``in_progress`` the inspection stays ``failed``, the status lock
    refuses the delete, and a test that only checked for a 409 would keep
    passing while silently testing the wrong branch again.
    """
    h = world["headers"]
    criterion_id = await _new_criterion(http_client, world)
    inspection_id = await _new_inspection(http_client, world, criterion_id=criterion_id)
    failed = await http_client.post(
        f"{BASE}/inspections/{inspection_id}/record-result",
        json={"result": "fail", "measured_value": "21", "notes": "Below the 30 MPa minimum."},
        headers=h,
    )
    assert failed.status_code == 200, failed.text
    assert failed.json()["raised_ncr_id"], "a failed inspection must raise an NCR"

    reopened = await http_client.patch(
        f"{BASE}/inspections/{inspection_id}",
        json={"status": "in_progress"},
        headers=h,
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "in_progress", reopened.text

    resp = await http_client.delete(f"{BASE}/inspections/{inspection_id}", headers=h)
    assert resp.status_code == 409, f"an inspection with an NCR must refuse deletion, got {resp.status_code}"
    detail = resp.json()["detail"]
    # Only refuse_if_held can produce these two. refuse_if_locked says
    # "is {status} and cannot be deleted" and never names a holder.
    assert "is referenced by" in detail, detail
    assert "1 non-conformance report" in detail, detail


@pytest.mark.asyncio
async def test_reopened_inspection_without_an_ncr_deletes_cleanly(http_client, world):
    """Negative control for the holder branch above.

    Same record, same reopened status, no NCR. The previous test refuses and
    this one deletes, so the only difference between them is the NCR, which is
    what makes ``count_ncrs_on_inspection`` the thing under test rather than the
    status lock wearing its name. A count stuck at zero would turn the test
    above green and leave this one green too, so the pair has to be read
    together.
    """
    h = world["headers"]
    inspection_id = await _new_inspection(http_client, world)
    reopened = await http_client.patch(
        f"{BASE}/inspections/{inspection_id}",
        json={"status": "in_progress"},
        headers=h,
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "in_progress", reopened.text

    resp = await http_client.delete(f"{BASE}/inspections/{inspection_id}", headers=h)
    assert resp.status_code == 204, f"an unheld inspection must delete, got {resp.status_code}: {resp.text}"


@pytest.mark.asyncio
async def test_gate_attached_to_a_handover_package_refuses(http_client, world):
    """A gate attached through ``attached_kind`` holds the package it gates."""
    h = world["headers"]
    package_id = await _new_handover(http_client, world)
    await _new_gate(http_client, world, attached_kind="handover_package", attached_id=package_id)

    resp = await http_client.delete(f"{BASE}/handover/{package_id}", headers=h)
    assert resp.status_code == 409, f"a gated handover package must refuse deletion, got {resp.status_code}"
    assert "1 hold gate" in resp.json()["detail"], resp.text


@pytest.mark.asyncio
async def test_gate_attached_to_an_inspection_holds_it(http_client, world):
    """A gate names an inspection through two different columns; both count.

    ``attached_kind='inspection'`` + ``attached_id`` is the second one, and
    counting only ``inspection_id`` would leave this holder invisible.
    """
    h = world["headers"]
    inspection_id = await _new_inspection(http_client, world)
    await _new_gate(http_client, world, attached_kind="inspection", attached_id=inspection_id)

    resp = await http_client.delete(f"{BASE}/inspections/{inspection_id}", headers=h)
    assert resp.status_code == 409, f"an inspection gated by a hold point must refuse deletion, {resp.status_code}"
    assert "1 hold gate" in resp.json()["detail"], resp.text


@pytest.mark.asyncio
async def test_material_held_by_a_test_result_refuses(http_client, world):
    """A test result is the laboratory's statement about this material."""
    h = world["headers"]
    material_id = await _new_material(http_client, world)
    await _new_test_result(http_client, world, material_record_id=material_id)

    resp = await http_client.delete(f"{BASE}/materials/{material_id}", headers=h)
    assert resp.status_code == 409, f"a tested material must refuse deletion, got {resp.status_code}"
    assert "1 test result" in resp.json()["detail"], resp.text
