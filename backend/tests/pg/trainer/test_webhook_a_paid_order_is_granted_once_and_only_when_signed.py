# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: a signed ``order.paid`` grants one account, one enrolment, one seed and one email.

Every refusal has its granting twin in the same test: the forged, tampered,
stale or flag-off delivery grants nothing, and then the genuine delivery of
the same order grants everything. A handler that refused all deliveries, or
granted all of them, fails here.

Real users table, real trainer tables, real reset token. The seeder is
stream C's and is injected, so it is a recorder here; mail goes to a memory
backend.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from datetime import UTC, datetime

import pytest
from jose import jwt
from pydantic import SecretStr
from sqlalchemy import func, select

from app.config import get_settings
from app.core.email import EmailService, MemoryEmailBackend
from app.modules.trainer import provisioning, webhook
from app.modules.trainer.models import TrainerCourse, TrainerEnrolment, TrainerOffer, TrainerWebhookEvent
from app.modules.trainer.webhook import compute_signature, handle_webhook
from app.modules.users.models import User
from app.modules.users.schemas import ResetPasswordRequest
from app.modules.users.service import UserService, verify_password

pytestmark = pytest.mark.asyncio

SECRET = "whsec_pg_never_logged_5d1e8b"
PRODUCT = "prod-valuations-uk"
COURSE_KEY = "fixture_uk_v1"


class _Seeder:
    """Stands in for stream C's seed stage S0; records calls, can be told to fail."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[uuid.UUID] = []
        self.fail = fail

    async def __call__(self, enrolment_id: uuid.UUID) -> None:
        self.calls.append(enrolment_id)
        if self.fail:
            raise RuntimeError("seed exploded")


def _settings(*, academy_mode: bool = True):
    return get_settings().model_copy(update={"academy_mode": academy_mode, "trainer_webhook_secret": SecretStr(SECRET)})


def _mail() -> tuple[EmailService, MemoryEmailBackend]:
    backend = MemoryEmailBackend()
    return EmailService(backend), backend


async def _catalogue(session, *, course_keys: tuple[str, ...] = (COURSE_KEY,), product: str = PRODUCT) -> None:
    for key in course_keys:
        session.add(
            TrainerCourse(
                course_key=key,
                version="1",
                country="GB",
                language="en",
                currency="GBP",
                title=f"Course {key}",
                source_file=f"{key}.json",
                sha256="a" * 64,
                spec={},
                validation_report={},
                status="active",
                loaded_at=datetime.now(UTC),
            )
        )
        session.add(TrainerOffer(provider="generic", product_ref=product, course_key=key, is_active=True))
    await session.flush()


def _body(email: str, *, event_id: str | None = None, event_type: str = "order.paid", product: str = PRODUCT) -> bytes:
    return json.dumps(
        {
            "id": event_id or f"evt_{uuid.uuid4().hex}",
            "type": event_type,
            "data": {
                "offer_code": product,
                "order_ref": "ord-1",
                "email": email,
                "name": "Ada Learner",
                "locale": "en-GB",
                "paid_at": "2026-10-05T10:00:00Z",
                "phone": "+44 20 7946 0000",
                "billing_address": {"street": "1 High St"},
            },
        }
    ).encode()


def _headers(body: bytes, *, secret: str = SECRET, ts: int | None = None) -> dict[str, str]:
    stamp = str(int(time.time()) if ts is None else ts)
    return {"X-OE-Timestamp": stamp, "X-OE-Signature": "sha256=" + compute_signature(secret, body, stamp)}


async def _deliver(session, body: bytes, headers: dict[str, str], seeder: _Seeder, mail: EmailService, **kw):
    return await handle_webhook(
        session,
        kw.pop("settings", None) or _settings(),
        raw_body=body,
        headers=headers,
        seed_on_enrol=seeder,
        email_service=mail,
        **kw,
    )


async def _user(session, email: str) -> User | None:
    return (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()


async def _count(session, model, *where) -> int:
    return (await session.execute(select(func.count()).select_from(model).where(*where))).scalar_one()


def _email() -> str:
    return f"learner-{uuid.uuid4().hex[:10]}@example.com"


def _reset_token(html_body: str) -> str:
    match = re.search(r"/auth/reset\?token=([A-Za-z0-9_\-.]+)", html_body)
    assert match, "the welcome email must carry the reset link"
    return match.group(1)


async def test_a_signed_paid_order_creates_a_manager_with_an_active_course_and_one_email(pg_session) -> None:
    await _catalogue(pg_session)
    email, seeder = _email(), _Seeder()
    mail, outbox = _mail()
    body = _body(email.upper())

    outcome = await _deliver(pg_session, body, _headers(body), seeder, mail)

    assert (outcome.http_status, outcome.status) == (200, "processed")
    user = await _user(pg_session, email)
    assert user is not None and user.role == "manager" and user.is_active
    assert user.metadata_["trainer"] == {"provisioned_by": "webhook"}
    enrolment = (
        await pg_session.execute(select(TrainerEnrolment).where(TrainerEnrolment.user_id == user.id))
    ).scalar_one()
    await pg_session.refresh(enrolment)
    assert enrolment.status == "active" and enrolment.started_at is not None
    assert (enrolment.source, enrolment.order_ref, enrolment.course_sha256) == ("webhook", "ord-1", "a" * 64)
    assert seeder.calls == [enrolment.id]

    row = (await pg_session.execute(select(TrainerWebhookEvent).where(TrainerWebhookEvent.email == email))).scalar_one()
    assert (row.status, row.signature_ok, row.user_id, row.enrolment_id) == ("processed", True, user.id, enrolment.id)
    assert "phone" not in row.payload["data"] and "billing_address" not in row.payload["data"]

    [sent] = outbox.sent
    assert sent.to == email
    assert "trainer_welcome" in sent.tags
    token = _reset_token(sent.html_body)
    claims = jwt.decode(token, get_settings().jwt_secret, algorithms=[get_settings().jwt_algorithm])
    assert (claims["type"], claims["sub"]) == ("reset", str(user.id))
    assert "/forgot-password" in sent.html_body


async def test_the_welcome_link_lets_the_learner_choose_a_password_once(pg_session) -> None:
    await _catalogue(pg_session)
    email = _email()
    mail, outbox = _mail()
    body = _body(email)
    await _deliver(pg_session, body, _headers(body), _Seeder(), mail)
    token = _reset_token(outbox.sent[0].html_body)

    service = UserService(pg_session, get_settings())
    await service.reset_password(ResetPasswordRequest(token=token, new_password="Learner-pass-2026"))
    user = await _user(pg_session, email)
    await pg_session.refresh(user)
    assert verify_password("Learner-pass-2026", user.hashed_password)


async def test_the_same_event_delivered_twice_is_a_duplicate_that_writes_nothing(pg_session) -> None:
    await _catalogue(pg_session)
    email, seeder = _email(), _Seeder()
    mail, outbox = _mail()
    body = _body(email, event_id="evt_twice")

    first = await _deliver(pg_session, body, _headers(body), seeder, mail)
    second = await _deliver(pg_session, body, _headers(body), seeder, mail)

    assert first.status == "processed"
    assert (second.http_status, second.status, second.stored_status) == (200, "duplicate", "processed")
    assert second.body() == {"status": "duplicate", "outcome": "processed"}
    user = await _user(pg_session, email)
    assert await _count(pg_session, TrainerWebhookEvent, TrainerWebhookEvent.event_id == "evt_twice") == 1
    assert await _count(pg_session, User, User.email == email) == 1
    assert await _count(pg_session, TrainerEnrolment, TrainerEnrolment.user_id == user.id) == 1
    assert len(seeder.calls) == 1
    assert len(outbox.sent) == 1


async def test_a_forged_signature_grants_nothing_and_cannot_claim_the_real_event_id(pg_session) -> None:
    await _catalogue(pg_session)
    email, seeder = _email(), _Seeder()
    mail, outbox = _mail()
    body = _body(email, event_id="evt_forged_first")

    forged = await _deliver(pg_session, body, _headers(body, secret="whsec_attacker"), seeder, mail)

    assert (forged.http_status, forged.status) == (401, "rejected")
    assert await _user(pg_session, email) is None
    assert (seeder.calls, outbox.sent) == ([], [])
    rejected = (
        await pg_session.execute(select(TrainerWebhookEvent).where(TrainerWebhookEvent.signature_ok.is_(False)))
    ).scalar_one()
    assert rejected.event_id.startswith("rejected:")
    assert (rejected.payload, rejected.email) == (None, None)

    genuine = await _deliver(pg_session, body, _headers(body), seeder, mail)
    assert (genuine.http_status, genuine.status) == (200, "processed")
    assert (await _user(pg_session, email)).role == "manager"


async def test_a_body_changed_after_signing_grants_nothing(pg_session) -> None:
    await _catalogue(pg_session)
    victim, attacker, seeder = _email(), _email(), _Seeder()
    mail, outbox = _mail()
    signed = _body(victim, event_id="evt_tamper")
    tampered = signed.replace(victim.encode(), attacker.encode())

    outcome = await _deliver(pg_session, tampered, _headers(signed), seeder, mail)

    assert (outcome.http_status, outcome.status) == (401, "rejected")
    assert await _user(pg_session, attacker) is None
    assert await _user(pg_session, victim) is None
    assert outbox.sent == []

    untouched = await _deliver(pg_session, signed, _headers(signed), seeder, mail)
    assert untouched.status == "processed"
    assert await _user(pg_session, victim) is not None
    assert await _user(pg_session, attacker) is None


async def test_a_stale_delivery_grants_nothing_and_a_fresh_one_does(pg_session) -> None:
    await _catalogue(pg_session)
    email, seeder = _email(), _Seeder()
    mail, _ = _mail()
    body = _body(email, event_id="evt_stale")

    stale = await _deliver(pg_session, body, _headers(body, ts=int(time.time()) - 3600), seeder, mail)
    assert (stale.http_status, stale.status) == (401, "rejected")
    assert await _user(pg_session, email) is None

    fresh = await _deliver(pg_session, body, _headers(body), seeder, mail)
    assert fresh.status == "processed"


async def test_with_the_academy_flag_off_nothing_is_written(pg_session) -> None:
    await _catalogue(pg_session)
    email, seeder = _email(), _Seeder()
    mail, outbox = _mail()
    body = _body(email, event_id="evt_flag")
    before = await _count(pg_session, TrainerWebhookEvent)

    off = await _deliver(pg_session, body, _headers(body), seeder, mail, settings=_settings(academy_mode=False))

    assert (off.http_status, off.status) == (404, "disabled")
    assert await _count(pg_session, TrainerWebhookEvent) == before
    assert await _user(pg_session, email) is None
    assert (seeder.calls, outbox.sent) == ([], [])

    on = await _deliver(pg_session, body, _headers(body), seeder, mail, settings=_settings(academy_mode=True))
    assert on.status == "processed"
    assert await _count(pg_session, TrainerWebhookEvent) == before + 1


async def test_an_unknown_event_type_is_acknowledged_once_and_ignored(pg_session) -> None:
    await _catalogue(pg_session)
    email, seeder = _email(), _Seeder()
    mail, _ = _mail()
    # Not ``order.refunded``: decision 42 made that a known type (it suspends).
    body = _body(email, event_id="evt_refund", event_type="order.updated")

    first = await _deliver(pg_session, body, _headers(body), seeder, mail)
    again = await _deliver(pg_session, body, _headers(body), seeder, mail)

    assert (first.http_status, first.status) == (200, "ignored")
    assert (again.http_status, again.status, again.stored_status) == (200, "duplicate", "ignored")
    assert await _user(pg_session, email) is None
    assert await _count(pg_session, TrainerWebhookEvent, TrainerWebhookEvent.event_id == "evt_refund") == 1


async def test_a_signed_order_with_a_bad_field_is_recorded_failed_and_grants_nothing(pg_session) -> None:
    await _catalogue(pg_session)
    mail, outbox = _mail()
    body = _body("not-an-email", event_id="evt_badfield")

    first = await _deliver(pg_session, body, _headers(body), _Seeder(), mail)
    again = await _deliver(pg_session, body, _headers(body), _Seeder(), mail)

    assert (first.http_status, first.status) == (400, "invalid")
    assert (again.http_status, again.status) == (400, "invalid"), "a failed event is retried, and fails again"
    row = (
        await pg_session.execute(select(TrainerWebhookEvent).where(TrainerWebhookEvent.event_id == "evt_badfield"))
    ).scalar_one()
    assert (row.status, row.signature_ok) == ("failed", True)
    assert row.error == "invalid_payload: missing or invalid fields: email"
    assert "phone" not in row.payload["data"]
    assert outbox.sent == []

    not_json = b"{not json"
    assert (await _deliver(pg_session, not_json, _headers(not_json), _Seeder(), mail)).status == "invalid"


async def test_a_product_with_no_offer_is_ignored(pg_session) -> None:
    await _catalogue(pg_session)
    email = _email()
    mail, outbox = _mail()
    body = _body(email, product="some-other-product")

    outcome = await _deliver(pg_session, body, _headers(body), _Seeder(), mail)

    assert (outcome.http_status, outcome.status) == (200, "ignored")
    assert await _user(pg_session, email) is None
    assert outbox.sent == []


async def test_an_offer_whose_course_is_not_loaded_fails_for_the_admin(pg_session) -> None:
    pg_session.add(TrainerOffer(provider="generic", product_ref="prod-ghost", course_key="ghost_v1", is_active=True))
    await pg_session.flush()
    email = _email()
    mail, _ = _mail()
    body = _body(email, product="prod-ghost", event_id="evt_ghost")

    outcome = await _deliver(pg_session, body, _headers(body), _Seeder(), mail)

    assert (outcome.http_status, outcome.status) == (200, "failed")
    row = (
        await pg_session.execute(select(TrainerWebhookEvent).where(TrainerWebhookEvent.event_id == "evt_ghost"))
    ).scalar_one()
    assert row.error == "course_not_available: ghost_v1"
    assert await _user(pg_session, email) is None


async def test_a_crash_marks_the_event_failed_and_the_resend_retries_it(pg_session, monkeypatch) -> None:
    await _catalogue(pg_session)
    email, seeder = _email(), _Seeder()
    mail, outbox = _mail()
    body = _body(email, event_id="evt_crash")
    real = webhook.provision_order_paid

    async def crash_after_writing(session, settings, order, **kw):
        await real(session, settings, order, **kw)  # writes the user, then dies
        raise RuntimeError("boom")

    monkeypatch.setattr(webhook, "provision_order_paid", crash_after_writing)
    crashed = await _deliver(pg_session, body, _headers(body), seeder, mail)
    assert (crashed.http_status, crashed.status) == (500, "failed")
    assert await _user(pg_session, email) is None, "the provisioning savepoint must roll back"
    row = (
        await pg_session.execute(select(TrainerWebhookEvent).where(TrainerWebhookEvent.event_id == "evt_crash"))
    ).scalar_one()
    assert (row.status, row.error) == ("failed", "error: RuntimeError")

    monkeypatch.setattr(webhook, "provision_order_paid", real)
    retried = await _deliver(pg_session, body, _headers(body), seeder, mail)
    assert (retried.http_status, retried.status) == (200, "processed")
    await pg_session.refresh(row)
    assert row.status == "processed"
    assert await _count(pg_session, TrainerWebhookEvent, TrainerWebhookEvent.event_id == "evt_crash") == 1
    assert len(seeder.calls) == 1 and len(outbox.sent) == 1


async def test_a_seed_failure_still_acks_the_store_and_a_resend_reseeds_without_a_second_email(pg_session) -> None:
    await _catalogue(pg_session)
    email = _email()
    mail, outbox = _mail()
    body = _body(email, event_id="evt_seedfail")
    broken = _Seeder(fail=True)

    outcome = await _deliver(pg_session, body, _headers(body), broken, mail)

    assert (outcome.http_status, outcome.status) == (200, "failed")
    user = await _user(pg_session, email)
    enrolment = (
        await pg_session.execute(select(TrainerEnrolment).where(TrainerEnrolment.user_id == user.id))
    ).scalar_one()
    await pg_session.refresh(enrolment)
    assert enrolment.status == "failed"
    assert enrolment.metadata_["seed_error"] == "RuntimeError"
    assert len(outbox.sent) == 1, "the buyer still gets their account"
    # Decision 41: a failed seed gets the "being prepared" variant, never "ready".
    assert "prepared" in outbox.sent[0].subject

    fixed = _Seeder()
    retried = await _deliver(pg_session, body, _headers(body), fixed, mail)
    assert retried.status == "processed"
    await pg_session.refresh(enrolment)
    assert enrolment.status == "active"
    assert fixed.calls == [enrolment.id]
    # The "ready" email is still owed after "being prepared" (decision 41),
    # and it goes out once.
    assert len(outbox.sent) == 2
    assert outbox.sent[1].subject.startswith("Your course is ready")
    again = await _deliver(pg_session, body, _headers(body), fixed, mail)
    assert again.status == "duplicate"
    assert len(outbox.sent) == 2
    assert await _count(pg_session, TrainerEnrolment, TrainerEnrolment.user_id == user.id) == 1


async def test_no_secret_ever_reaches_the_log(pg_session, monkeypatch, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    await _catalogue(pg_session)
    password = "Throwaway-known-to-this-test-only-9"
    monkeypatch.setattr(provisioning, "_throwaway_password", lambda: password)
    email, seeder = _email(), _Seeder()
    mail, outbox = _mail()
    body = _body(email)
    good_headers = _headers(body)
    forged_headers = _headers(body, secret="whsec_attacker")

    await _deliver(pg_session, body, forged_headers, seeder, mail)
    await _deliver(pg_session, body, good_headers, seeder, mail)
    await _deliver(pg_session, body, good_headers, seeder, mail)

    token = _reset_token(outbox.sent[0].html_body)
    trainer_records = [r for r in caplog.records if r.name.startswith("app.modules.trainer")]
    assert len(trainer_records) >= 3, "the flow must log, or this test proves nothing"
    text = "\n".join(r.getMessage() + (r.exc_text or "") for r in caplog.records)
    for secret_value in (
        SECRET,
        password,
        token,
        good_headers["X-OE-Signature"].removeprefix("sha256="),
        forged_headers["X-OE-Signature"].removeprefix("sha256="),
    ):
        assert secret_value not in text
