# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: provisioning on real ``oe_users_user`` rows, the role audit and the permission registry.

A paid order for an email that already has an account reuses it. A viewer is
raised to manager (audited); an admin or a manager is left exactly as it was
(no audit row). The permission ``bid_management.award`` tells the two apart:
a viewer lacks it, a learner needs it.

One course runs at a time: a second course is ``queued`` and not seeded.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.config import get_settings
from app.core.audit_log import ActivityLog
from app.core.email import EmailService, MemoryEmailBackend
from app.core.permissions import permission_registry
from app.modules.bid_management.permissions import register_bid_management_permissions
from app.modules.trainer.models import TrainerCourse, TrainerEnrolment, TrainerOffer
from app.modules.trainer.provisioning import complete_provisioning, provision_learner
from app.modules.trainer.webhook import compute_signature, handle_webhook
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

SECRET = "whsec_pg_roles_3c7d"
_FAKE_HASH = "$2b$12$abcdefghijklmnopqrstuuWfZ1Q3n3o6f5r0o8C2c1m9Yq4l5bS6"


class _Seeder:
    def __init__(self) -> None:
        self.calls: list[uuid.UUID] = []

    async def __call__(self, enrolment_id: uuid.UUID) -> None:
        self.calls.append(enrolment_id)


def _settings(*, academy_mode: bool = True):
    return get_settings().model_copy(update={"academy_mode": academy_mode, "trainer_webhook_secret": SecretStr(SECRET)})


async def _course(session, key: str) -> TrainerCourse:
    course = TrainerCourse(
        course_key=key,
        version="1",
        country="DE",
        language="de",
        currency="EUR",
        title=f"Kurs {key}",
        source_file=f"{key}.json",
        sha256="b" * 64,
        spec={},
        validation_report={},
        status="active",
        loaded_at=datetime.now(UTC),
    )
    session.add(course)
    await session.flush()
    return course


async def _offer(session, product: str, *keys: str) -> None:
    for key in keys:
        await _course(session, key)
        session.add(TrainerOffer(provider="generic", product_ref=product, course_key=key, is_active=True))
    await session.flush()


async def _account(session, *, role: str, is_active: bool = True) -> User:
    user = User(
        email=f"{role}-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password=_FAKE_HASH,
        full_name=f"Existing {role}",
        role=role,
        is_active=is_active,
    )
    session.add(user)
    await session.flush()
    return user


async def _pay(session, email: str, product: str, seeder: _Seeder | None = None, mail: EmailService | None = None):
    body = json.dumps(
        {
            "id": f"evt_{uuid.uuid4().hex}",
            "type": "order.paid",
            "data": {"offer_code": product, "email": email, "name": "Buyer", "paid_at": "2026-10-05T10:00:00Z"},
        }
    ).encode()
    ts = str(int(time.time()))
    return await handle_webhook(
        session,
        _settings(),
        raw_body=body,
        headers={"X-OE-Timestamp": ts, "X-OE-Signature": compute_signature(SECRET, body, ts)},
        seed_on_enrol=seeder or _Seeder(),
        email_service=mail or EmailService(MemoryEmailBackend()),
    )


async def _role_audits(session, user_id: uuid.UUID) -> list[ActivityLog]:
    rows = await session.execute(
        select(ActivityLog).where(ActivityLog.entity_id == str(user_id), ActivityLog.action == "role_changed")
    )
    return list(rows.scalars().all())


async def _enrolments(session, user_id: uuid.UUID) -> list[TrainerEnrolment]:
    rows = await session.execute(
        select(TrainerEnrolment).where(TrainerEnrolment.user_id == user_id).order_by(TrainerEnrolment.created_at)
    )
    out = list(rows.scalars().all())
    for row in out:
        await session.refresh(row)
    return out


@pytest.fixture
def award_permission():
    register_bid_management_permissions()
    assert permission_registry.has("bid_management.award"), "an empty registry would make the checks vacuous"
    return "bid_management.award"


async def test_an_existing_admin_is_enrolled_and_keeps_admin(pg_session, award_permission) -> None:
    await _offer(pg_session, "prod-admin", "course_admin")
    admin = await _account(pg_session, role="admin")

    outcome = await _pay(pg_session, admin.email.upper(), "prod-admin")

    assert outcome.status == "processed"
    await pg_session.refresh(admin)
    assert admin.role == "admin"
    assert await _role_audits(pg_session, admin.id) == []
    assert permission_registry.role_has_permission(admin.role, award_permission)
    assert [e.status for e in await _enrolments(pg_session, admin.id)] == ["active"]


async def test_an_existing_manager_is_left_exactly_as_it_was(pg_session) -> None:
    await _offer(pg_session, "prod-mgr", "course_mgr")
    manager = await _account(pg_session, role="manager")

    await _pay(pg_session, manager.email, "prod-mgr")

    await pg_session.refresh(manager)
    assert manager.role == "manager"
    assert await _role_audits(pg_session, manager.id) == []


async def test_an_existing_viewer_is_raised_to_manager_with_an_audit_row(pg_session, award_permission) -> None:
    await _offer(pg_session, "prod-viewer", "course_viewer")
    viewer = await _account(pg_session, role="viewer")
    assert not permission_registry.role_has_permission(viewer.role, award_permission)

    outcome = await _pay(pg_session, viewer.email, "prod-viewer")

    assert outcome.status == "processed"
    await pg_session.refresh(viewer)
    assert viewer.role == "manager"
    assert permission_registry.role_has_permission(viewer.role, award_permission)
    [audit] = await _role_audits(pg_session, viewer.id)
    assert (audit.from_status, audit.to_status) == ("viewer", "manager")
    assert viewer.hashed_password == _FAKE_HASH, "an existing account keeps its password"


async def test_a_new_learner_can_award_a_bid_package(pg_session, award_permission) -> None:
    await _offer(pg_session, "prod-new", "course_new")
    email = f"new-{uuid.uuid4().hex[:10]}@example.com"

    await _pay(pg_session, email, "prod-new")

    user = (await pg_session.execute(select(User).where(User.email == email))).scalar_one()
    assert user.role == "manager"
    assert permission_registry.role_has_permission(user.role, award_permission)
    assert user.hashed_password.startswith("$2b$"), "a bcrypt hash, so the login path can verify it"


async def test_a_deactivated_account_is_not_reactivated_by_a_purchase(pg_session) -> None:
    await _offer(pg_session, "prod-off", "course_off")
    dormant = await _account(pg_session, role="viewer", is_active=False)

    outcome = await _pay(pg_session, dormant.email, "prod-off")

    assert (outcome.http_status, outcome.status) == (200, "failed")
    await pg_session.refresh(dormant)
    assert (dormant.role, dormant.is_active) == ("viewer", False)
    assert await _enrolments(pg_session, dormant.id) == []


async def test_a_second_course_bought_while_one_runs_is_queued_and_not_seeded(pg_session) -> None:
    await _offer(pg_session, "prod-first", "course_first")
    await _offer(pg_session, "prod-second", "course_second")
    email = f"two-{uuid.uuid4().hex[:10]}@example.com"
    seeder = _Seeder()
    backend = MemoryEmailBackend()
    mail = EmailService(backend)

    await _pay(pg_session, email, "prod-first", seeder, mail)
    await _pay(pg_session, email, "prod-second", seeder, mail)

    user = (await pg_session.execute(select(User).where(User.email == email))).scalar_one()
    first, second = await _enrolments(pg_session, user.id)
    assert (first.status, second.status) == ("active", "queued")
    assert seeder.calls == [first.id]
    assert len(backend.sent) == 2
    assert "token=" in backend.sent[0].html_body
    assert "token=" not in backend.sent[1].html_body, "an existing account gets no reset link"
    # No order locale: the account took the course language, and both emails speak it.
    assert backend.sent[0].subject.startswith("Ihr Kurs ist bereit")
    assert backend.sent[1].subject.startswith("Ihr Kurs ist gebucht"), "the queued email says booked, not ready"


async def test_a_bundle_starts_one_course_and_queues_the_rest(pg_session) -> None:
    await _offer(pg_session, "prod-bundle", "bundle_a", "bundle_b")
    email = f"bundle-{uuid.uuid4().hex[:10]}@example.com"
    seeder = _Seeder()

    await _pay(pg_session, email, "prod-bundle", seeder)

    user = (await pg_session.execute(select(User).where(User.email == email))).scalar_one()
    statuses = sorted(e.status for e in await _enrolments(pg_session, user.id))
    assert statuses == ["active", "queued"]
    assert len(seeder.calls) == 1


async def test_buying_the_same_course_again_changes_nothing(pg_session) -> None:
    await _offer(pg_session, "prod-again", "course_again")
    email = f"again-{uuid.uuid4().hex[:10]}@example.com"
    seeder = _Seeder()
    backend = MemoryEmailBackend()

    await _pay(pg_session, email, "prod-again", seeder, EmailService(backend))
    second = await _pay(pg_session, email, "prod-again", seeder, EmailService(backend))

    assert second.status == "processed"
    user = (await pg_session.execute(select(User).where(User.email == email))).scalar_one()
    assert [e.status for e in await _enrolments(pg_session, user.id)] == ["active"]
    assert len(seeder.calls) == 1
    assert len(backend.sent) == 1


async def test_the_admin_path_with_the_flag_off_writes_nothing(pg_session) -> None:
    await _course(pg_session, "course_flag")
    email = f"flag-{uuid.uuid4().hex[:10]}@example.com"

    off = await provision_learner(
        pg_session,
        _settings(academy_mode=False),
        email=email,
        name="Admin Made",
        locale="de",
        course_keys=["course_flag"],
        source="admin",
    )
    assert off.status == "disabled"
    assert (await pg_session.execute(select(User).where(User.email == email))).scalar_one_or_none() is None

    on = await provision_learner(
        pg_session,
        _settings(),
        email=email,
        name="Admin Made",
        locale="de",
        course_keys=["course_flag"],
        source="admin",
    )
    await pg_session.commit()
    backend = MemoryEmailBackend()
    done = await complete_provisioning(
        pg_session, _settings(), on, seed_on_enrol=_Seeder(), email_service=EmailService(backend)
    )
    assert done.welcome_sent
    assert [e.status for e in done.enrolments] == ["active"]
    [enrolment] = await _enrolments(pg_session, on.user_id)
    assert enrolment.source == "admin"
    assert "Ihr Kurs" in backend.sent[0].subject, "the buyer's language, German here"
