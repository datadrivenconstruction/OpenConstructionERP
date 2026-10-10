# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A notification e-mail is written in its recipient's language.

The deadline e-mail used to be English for everybody: the dispatcher loaded
the user, kept the address and the name, and threw the language away. A
Turkish site engineer and an English-speaking consultant on the same project
now each get the same reminder in their own language, with the date in their
own order, under a subject that names the project and the record so it can be
found in a mailbox.

No database: the recipient lookup and the mail transport are replaced.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.email import EmailService
from app.core.email.memory import MemoryEmailBackend
from app.core.events import Event
from app.modules.deadlines import sweeper
from app.modules.deadlines.schemas import DeadlineItem
from app.modules.notifications import dispatcher
from app.modules.notifications.dispatcher import render_email_parts
from app.modules.notifications.email_render import render_notification_email

# (locale, date_format) as the dispatcher reads them off the user.
_TURKISH = ("tr", "auto")
_ENGLISH = ("en", "auto")
_BASE = "https://erp.example.com"


def _item(module: str = "rfi", **overrides: object) -> DeadlineItem:
    fields: dict[str, object] = {
        "id": f"{module}:1",
        "module": module,
        "entity_type": module,
        "entity_id": "1",
        "project_id": str(uuid.uuid4()),
        "project_name": "Kule Projesi",
        "title": "Şaft detayı",
        "reference": "RFI-007",
        "due_date": "2026-10-10",
        "owner_user_id": None,
        "status": "open",
        "classification": "overdue",
        "days_overdue": 4,
        "severity": "critical",
        "action_url": "/rfi",
    }
    fields.update(overrides)
    return DeadlineItem(**fields)


def _payload(item: DeadlineItem, kind: str, reader: sweeper.Reader) -> dict[str, object]:
    title_key, body_key = sweeper._keys(item, kind)
    context = sweeper._overdue_context(item, reader)
    return {"title_key": title_key, "body_key": body_key, "body_context": context, "action_url": item.action_url}


def test_the_same_reminder_is_turkish_for_one_recipient_and_english_for_the_other() -> None:
    # Written while sweeping for the Turkish recipient; the English one is
    # mailed from the very same stored params.
    payload = _payload(_item(), "overdue", sweeper.Reader(locale="tr"))

    subject_tr, body_tr = render_email_parts("deadlines.rfi.overdue", payload, *_TURKISH)
    subject_en, body_en = render_email_parts("deadlines.rfi.overdue", payload, *_ENGLISH)

    assert subject_tr == "[Kule Projesi] Gecikmiş: Bilgi Talebi (RFI) RFI-007"
    assert "son tarih 10.10.2026" in body_tr
    assert "Yanıt bekleniyor." in body_tr
    assert subject_en == "[Kule Projesi] Overdue: RFI RFI-007"
    assert "was due on 2026-10-10" in body_en
    assert "Response required." in body_en
    # Nothing of one language in the other.
    assert "Overdue" not in subject_tr + body_tr
    assert "Gecikmiş" not in subject_en + body_en


@pytest.mark.parametrize(
    ("module", "reference", "noun"),
    [
        ("rfi", "RFI-007", "Bilgi Talebi (RFI)"),
        ("submittals", "SUB-014", "Onay Belgesi"),
        ("correspondence", "COR-031", "Yazışma"),
        ("variations", "VR-012", "İlave İş"),
    ],
)
@pytest.mark.parametrize("kind", ["overdue", "escalated", "approaching"])
def test_every_register_names_the_project_the_record_and_the_date(
    module: str, reference: str, noun: str, kind: str
) -> None:
    item = _item(module, reference=reference)
    subject, body = render_email_parts(f"deadlines.{module}.{kind}", _payload(item, kind, sweeper.Reader()), *_TURKISH)
    assert subject.startswith("[Kule Projesi] ")
    assert reference in subject and noun in subject
    assert reference in body and noun in body
    assert "Kule Projesi" in body and "10.10.2026" in body and "Şaft detayı" in body
    assert "{" not in subject + body


def test_an_explicit_date_format_beats_the_language() -> None:
    american = ("en", "MM/DD/YYYY")
    item = _item(due_date="2026-10-09")
    _, body = render_email_parts(
        "deadlines.rfi.approaching", _payload(item, "approaching", sweeper.Reader(locale="tr")), *american
    )
    assert "is due on 10/09/2026" in body


def test_a_source_without_wording_of_its_own_keeps_the_plain_sentence() -> None:
    item = _item("punchlist", reference=None)
    assert sweeper._keys(item, "overdue") == (
        "notifications.deadline.overdue.title",
        "notifications.deadline.overdue.body",
    )
    assert sweeper._overdue_context(item) == {"module": "punchlist", "title": "Şaft detayı", "days_overdue": 4}
    # A register item that lost its number or its project falls back too,
    # rather than print a sentence with a hole in it.
    assert sweeper._keys(_item(reference=None), "overdue")[0] == "notifications.deadline.overdue.title"
    assert sweeper._keys(_item(project_name=None), "overdue")[0] == "notifications.deadline.overdue.title"


def test_the_stored_params_carry_the_date_twice() -> None:
    context = sweeper._overdue_context(_item(), sweeper.Reader(locale="tr"))
    assert context["due_date_iso"] == "2026-10-10"
    assert context["due_date_display"] == "10.10.2026"
    assert context["reference"] == "RFI-007"
    assert context["project"] == "Kule Projesi"
    assert sweeper._overdue_context(_item(), sweeper.Reader(locale="en"))["due_date_display"] == "2026-10-10"


def test_correspondence_is_reminded_ahead_of_its_reply_date() -> None:
    assert sweeper.APPROACHING_NOTIFY["correspondence"] == 3
    item = _item("correspondence", reference="COR-031", classification="approaching", days_overdue=-2)
    assert sweeper._approaching_keys(item) == (
        "notifications.deadline.correspondence.approaching.title",
        "notifications.deadline.correspondence.approaching.body",
    )
    context = sweeper._approaching_context(item, sweeper.Reader(locale="tr"))
    assert context["due_date"] == "2026-10-10", "the ISO date older clients read must stay"
    assert context["due_date_display"] == "10.10.2026"


def _frame(name: str | None, locale: str | None) -> str:
    return render_notification_email(
        locale=locale, recipient_name=name, subject="Konu", body_text="Metin", action_url="/rfi", base_url=_BASE
    )


def test_the_frame_of_the_email_is_in_the_recipients_language() -> None:
    html_tr = _frame("Ayşe Yılmaz", "tr")
    assert "Merhaba Ayşe Yılmaz," in html_tr
    assert "OpenConstructionERP üzerinde aç" in html_tr
    assert "bildirim ayarlarınız" in html_tr
    assert 'href="https://erp.example.com/rfi"' in html_tr
    for english in ("Hello", "Open in", "You receive"):
        assert english not in html_tr, english
    assert "Merhaba," in _frame(None, "tr-TR")
    assert "Hello Sam Reed," in _frame("Sam Reed", "en")


def test_a_digest_is_written_in_the_recipients_language() -> None:
    item = _item()
    payload = {
        "channel": "email",
        "count": 2,
        "events": [
            {"event_type": "deadlines.rfi.overdue", "payload": _payload(item, "overdue", sweeper.Reader())},
            {
                "event_type": "variations.notify.approved",
                "payload": {
                    "title_key": "notifications.variation.approved.title",
                    "body_context": {"code": "VR-012", "title": "Ek kanal", "project": "Kule Projesi"},
                },
            },
        ],
    }
    subject, body = render_email_parts("notifications.digest", payload, *_TURKISH)
    assert subject == "OpenConstructionERP: Bildirim özeti (2)"
    assert "Son bildirimler:" in body
    assert "[Kule Projesi] Gecikmiş: Bilgi Talebi (RFI) RFI-007" in body
    assert "[Kule Projesi] İlave İş onaylandı: VR-012" in body
    assert "Recent notifications" not in body and "{" not in body

    subject_en, body_en = render_email_parts("notifications.digest", payload, *_ENGLISH)
    assert subject_en == "OpenConstructionERP: Notification digest (2)"
    assert "Recent notifications:" in body_en


@pytest.mark.asyncio
async def test_the_dispatcher_sends_what_it_rendered_for_that_recipient(monkeypatch: pytest.MonkeyPatch) -> None:
    mem = MemoryEmailBackend()
    monkeypatch.setattr("app.core.email.get_email_service", lambda: EmailService(mem))

    async def turkish(_user_id: str) -> tuple[str, str, str]:
        return "site@example.com", "Ayşe Yılmaz", "tr"

    monkeypatch.setattr(dispatcher, "_resolve_user_email", turkish)
    payload = _payload(_item(), "overdue", sweeper.Reader(locale="tr"))

    await dispatcher._on_dispatch_email(
        Event(
            name="notifications.dispatch.email",
            data={"user_id": str(uuid.uuid4()), "event_type": "deadlines.rfi.overdue", "payload": payload},
        )
    )

    assert [m.to for m in mem.sent] == ["site@example.com"]
    message = mem.sent[0]
    assert message.subject == "[Kule Projesi] Gecikmiş: Bilgi Talebi (RFI) RFI-007"
    assert "Merhaba Ayşe Yılmaz," in message.html_body
    assert "son tarih 10.10.2026" in message.html_body
    assert "Overdue" not in message.html_body and "Hello" not in message.html_body
