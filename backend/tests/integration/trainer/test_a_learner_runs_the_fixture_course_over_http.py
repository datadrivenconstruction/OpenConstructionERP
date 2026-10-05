# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""HTTP: a paid order turns into a learner who passes task 1 of the fixture course.

The whole app runs on the embedded PostgreSQL cluster with the academy flag
on and the fixture course loaded at startup. Nothing below touches the
trainer tables to make progress: the order arrives as a signed webhook, the
learner works through the trainer routes, and the ERP is changed through the
BOQ API with the learner's own token. The database is read only to find ids
and to assert.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

pytestmark = pytest.mark.asyncio

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "trainer" / "course_fixture_v1.json"
SECRET = "whsec_integration_6f2a91"
PRODUCT = "prod-fx-quillmere"
API = "/api/v1/trainer"
T1 = "t1-direct-cost"

_ENV = {"OE_ACADEMY_MODE": "true", "OE_TRAINER_WEBHOOK_SECRET": SECRET}


def _apply_env(values: dict[str, str | None]) -> dict[str, str | None]:
    from app.config import get_settings

    previous = {key: os.environ.get(key) for key in values}
    for key, value in values.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    get_settings.cache_clear()
    return previous


@pytest_asyncio.fixture(scope="module")
async def app_instance(tmp_path_factory) -> AsyncIterator[Any]:
    courses = tmp_path_factory.mktemp("trainer_courses")
    shutil.copy(FIXTURE, courses / FIXTURE.name)
    previous = _apply_env({**_ENV, "OE_TRAINER_COURSES_DIR": str(courses)})
    try:
        from app.main import create_app

        app = create_app()
        async with app.router.lifespan_context(app):
            await _offer()
            yield app
    finally:
        from app.modules.trainer.events import cancel_pending_rechecks, drain_pending_rechecks

        cancel_pending_rechecks()
        await drain_pending_rechecks()
        _apply_env(previous)


@pytest_asyncio.fixture(scope="module")
async def client(app_instance) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
def _fresh_limits(monkeypatch) -> None:
    from app.modules.trainer import events, router

    router.check_limiter._requests.clear()
    router.webhook_limiter._requests.clear()
    monkeypatch.setattr(events, "RECHECK_DEBOUNCE_SECONDS", 0.0)


async def _offer() -> None:
    from app.database import async_session_factory
    from app.modules.trainer.models import TrainerCourse, TrainerOffer

    async with async_session_factory() as session:
        course = (
            await session.execute(select(TrainerCourse).where(TrainerCourse.source_file == FIXTURE.name))
        ).scalar_one()
        assert course.status == "active", course.validation_report.get("error_list")
        existing = (
            await session.execute(select(TrainerOffer).where(TrainerOffer.product_ref == PRODUCT))
        ).scalar_one_or_none()
        if existing is None:
            session.add(TrainerOffer(provider="generic", product_ref=PRODUCT, course_key=course.course_key))
        await session.commit()


def _signed(event_type: str, data: dict[str, Any]) -> tuple[bytes, dict[str, str]]:
    from app.modules.trainer.webhook import compute_signature

    body = json.dumps({"id": f"evt_{uuid.uuid4().hex}", "type": event_type, "data": data}).encode()
    stamp = str(int(time.time()))
    return body, {
        "X-OE-Timestamp": stamp,
        "X-OE-Signature": "sha256=" + compute_signature(SECRET, body, stamp),
        "Content-Type": "application/json",
    }


async def _pay(client: AsyncClient, email: str) -> dict[str, Any]:
    body, headers = _signed(
        "order.paid",
        {
            "offer_code": PRODUCT,
            "order_ref": f"ord-{uuid.uuid4().hex[:6]}",
            "email": email,
            "name": "Ada Learner",
            "locale": "en-GB",
            "paid_at": "2026-10-05T10:00:00Z",
        },
    )
    response = await client.post(f"{API}/webhook/", content=body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def _token_for(email: str) -> dict[str, str]:
    from app.config import get_settings
    from app.database import async_session_factory
    from app.modules.users.models import User
    from app.modules.users.service import create_access_token

    async with async_session_factory() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        return {"Authorization": f"Bearer {create_access_token(user, get_settings())}"}


async def _admin_headers() -> dict[str, str]:
    from app.database import async_session_factory
    from app.modules.users.models import User

    email = f"trainer-admin-{uuid.uuid4().hex[:8]}@test.io"
    async with async_session_factory() as session:
        session.add(User(id=uuid.uuid4(), email=email, hashed_password="x", role="admin", is_active=True))
        await session.commit()
    return await _token_for(email)


async def _enrolment_of(email: str) -> Any:
    from app.database import async_session_factory
    from app.modules.trainer.models import TrainerEnrolment
    from app.modules.users.models import User

    async with async_session_factory() as session:
        return (
            await session.execute(
                select(TrainerEnrolment).join(User, User.id == TrainerEnrolment.user_id).where(User.email == email)
            )
        ).scalar_one()


async def _attempts(enrolment_id: uuid.UUID, trigger: str) -> list[Any]:
    from app.database import async_session_factory
    from app.modules.trainer.models import TrainerAttempt

    async with async_session_factory() as session:
        rows = await session.execute(
            select(TrainerAttempt).where(TrainerAttempt.enrolment_id == enrolment_id, TrainerAttempt.trigger == trigger)
        )
        return list(rows.scalars().all())


async def _answers(client: AsyncClient, auth: dict[str, str], revision: int) -> int:
    response = await client.put(
        f"{API}/tasks/{T1}/answers",
        json={
            "revision": revision,
            "answers": [
                {"name": "direct_cost", "value_text": "30414.00"},
                {"name": "t1-trace", "option_index": 0},
                {"name": "t1-explain", "option_index": 0},
            ],
        },
        headers=auth,
    )
    assert response.status_code == 200, response.text
    return response.json()["revision"]


async def _blockwork_position_id(boq_id: str) -> uuid.UUID:
    from app.database import async_session_factory
    from app.modules.boq.models import Position

    async with async_session_factory() as session:
        return (
            await session.execute(
                select(Position.id).where(Position.boq_id == uuid.UUID(boq_id), Position.ordinal == "01.002")
            )
        ).scalar_one()


# ── The whole path ───────────────────────────────────────────────────────────


async def test_a_paid_order_becomes_a_learner_who_passes_task_one(client: AsyncClient) -> None:
    from app.modules.trainer.events import drain_pending_rechecks

    email = f"ada-{uuid.uuid4().hex[:8]}@test.io"
    outcome = await _pay(client, email)
    assert outcome["status"] == "processed"

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        assert user.role == "manager"
    enrolment = await _enrolment_of(email)
    assert enrolment.status == "active"
    auth = await _token_for(email)

    me = await client.get(f"{API}/me", headers=auth)
    assert me.status_code == 200, me.text
    assert [t["status"] for t in me.json()["tasks"]][:2] == ["not_started", "locked"]

    view = await client.get(f"{API}/tasks/{T1}", headers=auth)
    assert view.status_code == 200, view.text
    assert view.json()["answers_revision"] == 0
    assert "30414" not in view.text
    assert (await client.get(f"{API}/tasks/t2-markups", headers=auth)).status_code == 409

    revision = await _answers(client, auth, 0)
    assert revision == 1

    failed = await client.post(
        f"{API}/tasks/{T1}/check", json={"client_attempt_id": str(uuid.uuid4()), "revision": revision}, headers=auth
    )
    assert failed.status_code == 200, failed.text
    assert failed.json()["verdict"] == "fail", "the ERP is untouched, so the right panel figures must not pass"
    assert failed.json()["revealed_hint"]

    readback = await client.get(f"{API}/tasks/{T1}/readback", headers=auth)
    assert readback.status_code == 200
    assert {i["state"] for i in readback.json()["items"]} == {"mismatch"}

    # The learner prices 01.002 through the BOQ API, as in the app.
    position_id = await _blockwork_position_id(enrolment.seeded_refs["boq.main"])
    patched = await client.patch(f"/api/v1/boq/positions/{position_id}", json={"unit_rate": "46.20"}, headers=auth)
    assert patched.status_code == 200, patched.text

    # The BOQ event marks the course stale and the recheck records a note.
    for _ in range(100):
        if await _attempts(enrolment.id, "event"):
            break
        await asyncio.sleep(0.05)
    await drain_pending_rechecks()
    notes = await _attempts(enrolment.id, "event")
    assert notes, "the BOQ change never reached the trainer's event handler"
    assert notes[-1].passed is True
    me = await client.get(f"{API}/me", headers=auth)
    assert me.json()["tasks"][0]["status"] == "needs_revision", "an event recheck never passes a task"

    attempt_id = str(uuid.uuid4())
    passed = await client.post(f"{API}/tasks/{T1}/check", json={"client_attempt_id": attempt_id}, headers=auth)
    assert passed.status_code == 200, passed.text
    body = passed.json()
    assert (body["verdict"], body["unlocked"]) == ("pass", ["boq.markups_panel"])

    retried = await client.post(f"{API}/tasks/{T1}/check", json={"client_attempt_id": attempt_id}, headers=auth)
    assert retried.status_code == 200
    assert retried.json()["attempt_id"] == body["attempt_id"], "a retried check returns the stored attempt"
    assert len(await _attempts(enrolment.id, "manual")) == 2

    me = await client.get(f"{API}/me", headers=auth)
    tasks = me.json()["tasks"]
    assert [t["status"] for t in tasks][:2] == ["passed", "not_started"]
    unlock = next(u for u in me.json()["unlocks"] if u["lock_id"] == "boq.markups_panel")
    assert (unlock["state"], unlock["seen"]) == ("open", False)
    assert (await client.get(f"{API}/tasks/t2-markups", headers=auth)).status_code == 200

    for _ in range(2):
        seen = await client.post(f"{API}/unlocks/boq.markups_panel/seen", headers=auth)
        assert seen.status_code == 204, seen.text
    me = await client.get(f"{API}/me", headers=auth)
    assert next(u for u in me.json()["unlocks"] if u["lock_id"] == "boq.markups_panel")["seen"] is True

    hint = await client.post(f"{API}/tasks/{T1}/hints/reveal", headers=auth)
    assert hint.status_code == 200, hint.text
    assert hint.json()["hints_total"] == 2


async def test_a_stale_revision_is_refused_and_a_stranger_has_no_course(client: AsyncClient) -> None:
    email = f"bea-{uuid.uuid4().hex[:8]}@test.io"
    await _pay(client, email)
    auth = await _token_for(email)
    await _answers(client, auth, 0)
    stale_put = await client.put(
        f"{API}/tasks/{T1}/answers",
        json={"revision": 0, "answers": [{"name": "direct_cost", "value_text": "1"}]},
        headers=auth,
    )
    assert stale_put.status_code == 409
    stale_check = await client.post(
        f"{API}/tasks/{T1}/check", json={"client_attempt_id": str(uuid.uuid4()), "revision": 0}, headers=auth
    )
    assert stale_check.status_code == 409

    stranger = await _admin_headers()
    assert (await client.get(f"{API}/me", headers=stranger)).status_code == 404
    assert (await client.get(f"{API}/me")).status_code == 401


async def test_a_failed_seed_mails_preparing_and_an_admin_reseed_mails_ready(client: AsyncClient, monkeypatch) -> None:
    import app.core.email as email_package
    from app.core.email import EmailService, MemoryEmailBackend
    from app.modules.trainer import service as service_module

    backend = MemoryEmailBackend()
    monkeypatch.setattr(email_package, "get_email_service", lambda *_a, **_k: EmailService(backend))
    real = service_module.execute_enrolment
    calls = {"n": 0}

    async def flaky(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            from app.modules.trainer.seeder import SeedError

            raise SeedError("project", "on_enrol", "failed on purpose")
        return await real(*args, **kwargs)

    monkeypatch.setattr(service_module, "execute_enrolment", flaky)
    admin = await _admin_headers()
    email = f"cid-{uuid.uuid4().hex[:8]}@test.io"
    from app.database import async_session_factory
    from app.modules.trainer.models import TrainerCourse

    async with async_session_factory() as session:
        course_key = (
            await session.execute(select(TrainerCourse.course_key).where(TrainerCourse.source_file == FIXTURE.name))
        ).scalar_one()

    created = await client.post(
        f"{API}/admin/enrolments/",
        json={"email": email, "full_name": "Cid Learner", "course_key": course_key, "locale": "en"},
        headers=admin,
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "failed"
    subjects = [m.subject for m in backend.sent if email in m.to]
    assert len(subjects) == 1 and "prepared" in subjects[0].lower()

    listed = await client.get(f"{API}/admin/enrolments/", params={"email": email}, headers=admin)
    assert listed.status_code == 200
    assert [e["status"] for e in listed.json()] == ["failed"]

    reseeded = await client.post(f"{API}/admin/enrolments/{created.json()['id']}/reseed", headers=admin)
    assert reseeded.status_code == 200, reseeded.text
    assert reseeded.json()["status"] == "active"
    assert reseeded.json()["project_id"] is not None
    subjects = [m.subject for m in backend.sent if email in m.to]
    assert len(subjects) == 2 and subjects[0] != subjects[1]

    again = await client.post(f"{API}/admin/enrolments/{created.json()['id']}/reseed", headers=admin)
    assert again.status_code == 200
    assert len([m for m in backend.sent if email in m.to]) == 2, "the ready email goes out once"

    learner = await _token_for(email)
    assert (await client.get(f"{API}/admin/enrolments/", headers=learner)).status_code == 403
    reload = await client.post(f"{API}/courses/reload/", headers=admin)
    assert reload.status_code == 200
    assert {r["status"] for r in reload.json()} <= {"unchanged", "loaded"}


async def test_a_refund_closes_the_course_and_a_new_payment_reopens_it(client: AsyncClient) -> None:
    email = f"dee-{uuid.uuid4().hex[:8]}@test.io"
    await _pay(client, email)
    auth = await _token_for(email)
    assert (await client.get(f"{API}/me", headers=auth)).status_code == 200

    body, headers = _signed("order.refunded", {"email": email, "offer_code": PRODUCT})
    refunded = await client.post(f"{API}/webhook/", content=body, headers=headers)
    assert refunded.status_code == 200, refunded.text
    assert refunded.json()["status"] == "processed"
    assert (await _enrolment_of(email)).status == "suspended"
    assert (await client.get(f"{API}/me", headers=auth)).status_code == 404

    await _pay(client, email)
    assert (await _enrolment_of(email)).status == "active"
    assert (await client.get(f"{API}/me", headers=auth)).status_code == 200


async def test_every_trainer_route_is_404_while_the_flag_is_off(client: AsyncClient) -> None:
    previous = _apply_env({"OE_ACADEMY_MODE": "false"})
    try:
        task = f"{API}/tasks/{T1}"
        calls = [
            ("GET", f"{API}/me"),
            ("GET", task),
            ("PUT", f"{task}/answers"),
            ("POST", f"{task}/check"),
            ("GET", f"{task}/readback"),
            ("POST", f"{task}/hints/reveal"),
            ("POST", f"{API}/unlocks/boq.markups_panel/seen"),
            ("POST", f"{API}/webhook/"),
            ("GET", f"{API}/admin/enrolments/"),
            ("POST", f"{API}/admin/enrolments/"),
            ("POST", f"{API}/admin/enrolments/{uuid.uuid4()}/reseed"),
            ("GET", f"{API}/admin/courses/"),
            ("POST", f"{API}/courses/reload/"),
        ]
        for method, path in calls:
            response = await client.request(method, path, json={})
            assert response.status_code == 404, f"{method} {path} -> {response.status_code}"
        status = await client.get(f"{API}/public/status/")
        assert status.status_code == 200
        assert status.json() == {"academy_mode": False, "store_url": None}

    finally:
        _apply_env(previous)
    on = await client.get(f"{API}/public/status/")
    assert on.json()["academy_mode"] is True


async def test_a_reseed_restarts_a_seed_that_died_and_refuses_one_that_is_running(client: AsyncClient) -> None:
    from sqlalchemy import text, update

    from app.database import async_session_factory
    from app.modules.trainer.models import TrainerCourse, TrainerEnrolment
    from app.modules.trainer.service import seed_lock_key

    admin = await _admin_headers()
    async with async_session_factory() as session:
        course_key = (
            await session.execute(select(TrainerCourse.course_key).where(TrainerCourse.source_file == FIXTURE.name))
        ).scalar_one()
    email = f"eve-{uuid.uuid4().hex[:8]}@test.io"
    created = await client.post(
        f"{API}/admin/enrolments/",
        json={"email": email, "full_name": "Eve Learner", "course_key": course_key, "locale": "en"},
        headers=admin,
    )
    assert created.status_code == 201, created.text
    enrolment_id = uuid.UUID(created.json()["id"])

    # The process died mid-seed: the row says provisioning, nobody holds the lock.
    async with async_session_factory() as session:
        await session.execute(
            update(TrainerEnrolment).where(TrainerEnrolment.id == enrolment_id).values(status="provisioning")
        )
        await session.commit()

    async with async_session_factory() as holder:
        await holder.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": seed_lock_key(enrolment_id)})
        running = await client.post(f"{API}/admin/enrolments/{enrolment_id}/reseed", headers=admin)
        assert running.status_code == 409, running.text
        assert running.json()["detail"] == "seed_running"
        await holder.rollback()

    restarted = await client.post(f"{API}/admin/enrolments/{enrolment_id}/reseed", headers=admin)
    assert restarted.status_code == 200, restarted.text
    assert restarted.json()["status"] == "active"


async def test_a_seed_that_waited_for_another_does_nothing_once_the_enrolment_is_active(client: AsyncClient) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.trainer.models import TrainerCourse, TrainerEnrolment
    from app.modules.trainer.service import seed_on_enrol

    admin = await _admin_headers()
    async with async_session_factory() as session:
        course_key = (
            await session.execute(select(TrainerCourse.course_key).where(TrainerCourse.source_file == FIXTURE.name))
        ).scalar_one()
    created = await client.post(
        f"{API}/admin/enrolments/",
        json={
            "email": f"finn-{uuid.uuid4().hex[:8]}@test.io",
            "full_name": "Finn Learner",
            "course_key": course_key,
            "locale": "en",
        },
        headers=admin,
    )
    assert created.status_code == 201, created.text
    enrolment_id = uuid.UUID(created.json()["id"])

    # Wipe the refs: a seed that ran again would write them back.
    async with async_session_factory() as session:
        await session.execute(
            update(TrainerEnrolment).where(TrainerEnrolment.id == enrolment_id).values(status="active", seeded_refs={})
        )
        await session.commit()

    await seed_on_enrol(enrolment_id)

    async with async_session_factory() as session:
        row = await session.get(TrainerEnrolment, enrolment_id)
        assert row is not None
        assert row.status == "active"
        assert row.seeded_refs == {}
