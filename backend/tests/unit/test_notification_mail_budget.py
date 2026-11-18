# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Automatic notification mail has a daily ceiling; mail a person asks for has none.

Every de-duplication rule upstream is local to one entity and one table, and
the public demo lost all of them every night when its data was restored. The
budget is the bound that holds when they do not. Its other half matters as
much: a cap that also caught verification and password-reset mail would turn
a runaway sweeper into users who cannot sign in.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.config import Settings
from app.core.email import EmailService
from app.core.email.budget import NotificationMailBudget, notification_mail_budget
from app.core.email.memory import MemoryEmailBackend
from app.core.events import Event
from app.modules.notifications import dispatcher


class _Clock:
    def __init__(self) -> None:
        self.day = date(2026, 11, 18)

    def __call__(self) -> date:
        return self.day


def test_a_recipient_gets_at_most_the_cap_per_day() -> None:
    budget = NotificationMailBudget(per_recipient=20, per_instance=300, today=_Clock())

    admitted = [budget.admit("site@example.com") for _ in range(25)]

    assert admitted.count(True) == 20
    assert admitted[20:] == [False] * 5
    assert budget.dropped_today == 5


def test_the_instance_cap_holds_across_recipients() -> None:
    """47 items to a dozen people each must not add up past the instance cap."""
    budget = NotificationMailBudget(per_recipient=20, per_instance=300, today=_Clock())

    admitted = sum(budget.admit(f"user{i % 40}@example.com") for i in range(468))

    assert admitted == 300
    assert budget.sent_today == 300


def test_case_and_padding_count_as_the_same_recipient() -> None:
    budget = NotificationMailBudget(per_recipient=2, per_instance=0, today=_Clock())

    assert budget.admit("Site@Example.com")
    assert budget.admit(" site@example.com ")
    assert not budget.admit("SITE@EXAMPLE.COM")


def test_a_new_day_opens_a_new_budget() -> None:
    clock = _Clock()
    budget = NotificationMailBudget(per_recipient=1, per_instance=1, today=clock)
    assert budget.admit("a@example.com")
    assert not budget.admit("a@example.com")

    clock.day = date(2026, 11, 19)

    assert budget.admit("a@example.com")


def test_zero_means_no_cap() -> None:
    budget = NotificationMailBudget(per_recipient=0, per_instance=0, today=_Clock())

    assert all(budget.admit("a@example.com") for _ in range(1000))


def test_the_defaults_are_twenty_per_recipient_and_three_hundred_per_instance() -> None:
    settings = Settings()

    assert settings.notification_email_daily_cap_per_recipient == 20
    assert settings.notification_email_daily_cap_per_instance == 300


async def _dispatch(user_id: str = "") -> None:
    await dispatcher._on_dispatch_email(
        Event(
            name="notifications.dispatch.email",
            data={
                "user_id": user_id or str(uuid.uuid4()),
                "event_type": "deadlines.punchlist.overdue",
                "payload": {"title_key": "notifications.deadline.overdue.title", "body_context": {}},
            },
        )
    )


@pytest.mark.asyncio
async def test_the_dispatcher_drops_notification_mail_over_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    mem = MemoryEmailBackend()
    monkeypatch.setattr("app.core.email.get_email_service", lambda: EmailService(mem))

    async def owner(_user_id: str) -> tuple[str, str, str]:
        return "site@example.com", "Site Engineer", "en"

    monkeypatch.setattr(dispatcher, "_resolve_user_email", owner)
    budget = notification_mail_budget()
    monkeypatch.setattr(budget, "per_recipient", 3)

    for _ in range(5):
        await _dispatch()

    assert len(mem.sent) == 3
    assert budget.dropped_today == 2


@pytest.mark.asyncio
async def test_a_seeded_login_does_not_use_up_the_shared_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """The transport refuses it anyway; counting it would starve real recipients."""
    mem = MemoryEmailBackend()
    monkeypatch.setattr("app.core.email.get_email_service", lambda: EmailService(mem))

    async def demo(_user_id: str) -> tuple[str, str, str]:
        return "demo@openconstructionerp.com", "Demo", "en"

    monkeypatch.setattr(dispatcher, "_resolve_user_email", demo)
    for _ in range(5):
        await _dispatch()

    assert mem.sent == []
    assert notification_mail_budget().sent_today == 0


@pytest.mark.asyncio
async def test_transactional_mail_ignores_an_exhausted_budget() -> None:
    """Verification and password reset go through EmailService directly and are never capped."""
    budget = notification_mail_budget()
    budget.per_instance = 1
    budget.per_recipient = 1
    assert budget.admit("someone@example.com")
    assert not budget.admit("someone@example.com"), "precondition: the day's budget is spent"

    mem = MemoryEmailBackend()
    service = EmailService(mem)
    reset = await service.send_password_reset("someone@example.com", "https://erp.example.com/reset?token=t")

    from app.core.email import EmailMessage, template_email_verification

    subject, html = template_email_verification("Someone", "https://erp.example.com/verify?token=t", 24)
    verify = await service.send(EmailMessage(to="someone@example.com", subject=subject, html_body=html))

    assert reset.ok and verify.ok
    assert len(mem.sent) == 2
