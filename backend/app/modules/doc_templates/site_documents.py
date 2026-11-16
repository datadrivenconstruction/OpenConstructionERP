# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site correspondence in the firm's wording: RFI letter, meeting minutes, transmittal cover.

The registers keep their own record forms; these kinds print the outgoing
letter around the same record (question and answer, agenda and actions,
transmitted documents) through the generic generator, with labels from each
module's own document catalogue.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.core.doc_templates.pdf import TableSpec
from app.core.doc_templates.registry import DocumentKind, MergeField, RecordDocument
from app.modules.doc_templates.documents import _date, _project, _seller_values

__all__ = ["MINUTES_KEY", "RFI_KEY", "TRANSMITTAL_KEY", "minutes_kind", "rfi_kind", "transmittal_kind"]

RFI_KEY = "rfi.rfi"
MINUTES_KEY = "meetings.minutes"
TRANSMITTAL_KEY = "transmittals.transmittal"

_BASE_FIELDS = (
    MergeField("project.name", "text", "Haus B", "project"),
    MergeField("entity.legal_name", "text", "Muster Hochbau GmbH", "company"),
    MergeField("entity.address", "text", "Hauptstr. 1, 10115 Berlin", "company"),
    MergeField("entity.email", "text", "office@muster-hochbau.example", "company"),
    MergeField("entity.phone", "text", "+49 30 1234567", "company"),
    MergeField("doc.number", "text", "RFI-0042", "document"),
    MergeField("doc.subject", "text", "Footing depth at grid C4", "document"),
    MergeField("doc.date", "date", "16.11.2026", "document"),
    MergeField("doc.due_date", "date", "23.11.2026", "document"),
    MergeField("recipient.name", "text", "Planungsbüro Nord", "recipient"),
)

_RFI_DEFAULTS = {
    "en": {
        "title": "Request for information {{doc.number}}: {{doc.subject}}",
        "intro": "Dear Sir or Madam,\n\nfor {{project.name}} we ask for your answer to the question below "
        "by {{doc.due_date}}.",
        "closing": "Kind regards\n{{entity.legal_name}}",
    },
    "de": {
        "title": "Anfrage {{doc.number}}: {{doc.subject}}",
        "intro": "Sehr geehrte Damen und Herren,\n\nzum Bauvorhaben {{project.name}} bitten wir um Ihre Antwort "
        "auf die folgende Frage bis zum {{doc.due_date}}.",
        "closing": "Mit freundlichen Grüßen\n{{entity.legal_name}}",
    },
}
_MINUTES_DEFAULTS = {
    "en": {
        "title": "Minutes {{doc.number}}: {{doc.subject}}",
        "intro": "Meeting of {{doc.date}} on {{project.name}}.",
        "terms": "Objections to these minutes are to be raised in writing within 7 days of receipt; "
        "otherwise they are deemed accepted.",
        "closing": "Minutes taken by {{entity.legal_name}}",
    },
    "de": {
        "title": "Protokoll {{doc.number}}: {{doc.subject}}",
        "intro": "Besprechung vom {{doc.date}} zum Bauvorhaben {{project.name}}.",
        "terms": "Einwände gegen dieses Protokoll sind innerhalb von 7 Tagen nach Zugang schriftlich zu erheben; "
        "andernfalls gilt es als anerkannt.",
        "closing": "Protokoll: {{entity.legal_name}}",
    },
}
_TRANSMITTAL_DEFAULTS = {
    "en": {
        "title": "Transmittal {{doc.number}}: {{doc.subject}}",
        "intro": "Dear Sir or Madam,\n\nfor {{project.name}} we send you the documents listed below.",
        "terms": "Please confirm receipt by {{doc.due_date}}.",
        "closing": "Kind regards\n{{entity.legal_name}}",
    },
    "de": {
        "title": "Dokumentenübergabe {{doc.number}}: {{doc.subject}}",
        "intro": "Sehr geehrte Damen und Herren,\n\nzum Bauvorhaben {{project.name}} übersenden wir Ihnen die "
        "unten aufgeführten Unterlagen.",
        "terms": "Bitte bestätigen Sie den Eingang bis zum {{doc.due_date}}.",
        "closing": "Mit freundlichen Grüßen\n{{entity.legal_name}}",
    },
}


def _base(project: Any) -> dict[str, str]:
    return {**_seller_values(), "project.name": getattr(project, "name", "") or ""}


# ── RFI ─────────────────────────────────────────────────────────────────────


async def _rfi_records(session: Any, project_ids: set[Any] | None) -> list[tuple[str, str]]:
    from sqlalchemy import select

    from app.modules.rfi.models import RFI

    stmt = select(RFI.id, RFI.rfi_number, RFI.subject).order_by(RFI.rfi_number.desc()).limit(50)
    if project_ids is not None:
        stmt = stmt.where(RFI.project_id.in_(project_ids))
    return [(str(i), f"{n} {s}") for i, n, s in (await session.execute(stmt)).all()]


async def _rfi_document(session: Any, record_id: str, lang: str) -> RecordDocument:
    from app.core.party_names import resolve_party_names
    from app.modules.rfi.models import RFI
    from app.modules.rfi.pdf_translations import tr

    rfi = await session.get(RFI, uuid.UUID(record_id))
    if rfi is None:
        raise LookupError(record_id)
    project = await _project(session, rfi.project_id)
    names = await resolve_party_names(session, [rfi.assigned_to])
    recipient = names.get(str(rfi.assigned_to), "") if rfi.assigned_to else ""
    values = {
        **_base(project),
        "doc.number": rfi.rfi_number or "",
        "doc.subject": rfi.subject or "",
        "doc.date": _date(rfi.created_at, lang),
        "doc.due_date": _date(rfi.response_due_date or rfi.date_required, lang),
        "recipient.name": "" if recipient == str(rfi.assigned_to) else recipient,
    }
    meta = [
        (tr(lang, "question"), rfi.question or ""),
        (tr(lang, "response"), rfi.official_response or ""),
        (tr(lang, "response_due"), values["doc.due_date"]),
    ]
    return RecordDocument(
        values=values,
        meta=[m for m in meta if m[1]],
        project_id=rfi.project_id,
        filename=f"rfi-{rfi.rfi_number or rfi.id}",
        locale=getattr(project, "locale", None),
    )


def rfi_kind() -> DocumentKind:
    """The RFI letter sent to the designer."""
    return DocumentKind(
        key=RFI_KEY,
        channel="pdf",
        module="rfi",
        label="RFI letter",
        blocks=("title", "intro", "closing", "signature", "footer"),
        fields=_BASE_FIELDS,
        defaults=lambda lang: _RFI_DEFAULTS.get(lang, {}),
        languages=("en", "de"),
        required_blocks=("title",),
        appearance_type="rfi",
        records=_rfi_records,
        record_document=_rfi_document,
    )


# ── Meeting minutes ─────────────────────────────────────────────────────────


async def _minutes_records(session: Any, project_ids: set[Any] | None) -> list[tuple[str, str]]:
    from sqlalchemy import select

    from app.modules.meetings.models import Meeting

    stmt = select(Meeting.id, Meeting.meeting_number, Meeting.title).order_by(Meeting.meeting_date.desc()).limit(50)
    if project_ids is not None:
        stmt = stmt.where(Meeting.project_id.in_(project_ids))
    return [(str(i), f"{n} {t}") for i, n, t in (await session.execute(stmt)).all()]


async def _minutes_document(session: Any, record_id: str, lang: str) -> RecordDocument:
    from app.core.party_names import resolve_party_names
    from app.modules.meetings.models import Meeting
    from app.modules.meetings.pdf import minutes_label

    meeting = await session.get(Meeting, uuid.UUID(record_id))
    if meeting is None:
        raise LookupError(record_id)
    project = await _project(session, meeting.project_id)
    actions = [a for a in (meeting.action_items or []) if isinstance(a, dict)]
    agenda = [a for a in (meeting.agenda_items or []) if isinstance(a, dict)]
    owners = await resolve_party_names(session, [a.get("owner_id") for a in actions])
    values = {
        **_base(project),
        "doc.number": meeting.meeting_number or "",
        "doc.subject": meeting.title or "",
        "doc.date": _date(meeting.meeting_date, lang),
        "doc.due_date": "",
        "recipient.name": "",
    }
    meta = [
        (minutes_label(lang, "date"), values["doc.date"]),
        (minutes_label(lang, "location"), meeting.location or ""),
        (minutes_label(lang, "agenda"), "\n".join(str(a.get("topic") or "") for a in agenda if a.get("topic"))),
        (minutes_label(lang, "summary"), meeting.minutes or ""),
    ]
    table = TableSpec(
        header=[
            minutes_label(lang, "col_number"),
            minutes_label(lang, "col_action"),
            minutes_label(lang, "col_owner"),
            minutes_label(lang, "col_due"),
        ],
        rows=[
            [
                str(n),
                str(a.get("description") or ""),
                owners.get(str(a.get("owner_id")), "") if a.get("owner_id") else "",
                _date(a.get("due_date"), lang),
            ]
            for n, a in enumerate(actions, 1)
        ],
        col_widths_mm=(10, 100, 35, 25),
    )
    return RecordDocument(
        values=values,
        meta=[m for m in meta if m[1]],
        table=table if actions else None,
        project_id=meeting.project_id,
        filename=f"minutes-{meeting.meeting_number or meeting.id}",
        locale=getattr(project, "locale", None),
    )


def minutes_kind() -> DocumentKind:
    """The minutes letter: wording around the agenda, summary and actions."""
    return DocumentKind(
        key=MINUTES_KEY,
        channel="pdf",
        module="meetings",
        label="Meeting minutes",
        blocks=("title", "intro", "terms", "closing", "footer"),
        fields=_BASE_FIELDS,
        defaults=lambda lang: _MINUTES_DEFAULTS.get(lang, {}),
        languages=("en", "de"),
        required_blocks=("title",),
        appearance_type="meeting_minutes",
        records=_minutes_records,
        record_document=_minutes_document,
    )


# ── Transmittal ─────────────────────────────────────────────────────────────


async def _transmittal_records(session: Any, project_ids: set[Any] | None) -> list[tuple[str, str]]:
    from sqlalchemy import select

    from app.modules.transmittals.models import Transmittal

    stmt = (
        select(Transmittal.id, Transmittal.transmittal_number, Transmittal.subject)
        .order_by(Transmittal.transmittal_number.desc())
        .limit(50)
    )
    if project_ids is not None:
        stmt = stmt.where(Transmittal.project_id.in_(project_ids))
    return [(str(i), f"{n} {s}") for i, n, s in (await session.execute(stmt)).all()]


async def _transmittal_document(session: Any, record_id: str, lang: str) -> RecordDocument:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.modules.transmittals.models import Transmittal
    from app.modules.transmittals.pdf_translations import tr

    tm = (
        await session.execute(
            select(Transmittal)
            .options(selectinload(Transmittal.items), selectinload(Transmittal.recipients))
            .where(Transmittal.id == uuid.UUID(record_id))
        )
    ).scalar_one_or_none()
    if tm is None:
        raise LookupError(record_id)
    project = await _project(session, tm.project_id)
    recipients = [r.recipient_name or r.recipient_email or "" for r in tm.recipients or []]
    values = {
        **_base(project),
        "doc.number": tm.transmittal_number or "",
        "doc.subject": tm.subject or "",
        "doc.date": _date(tm.issued_date or tm.created_at, lang),
        "doc.due_date": _date(tm.response_due_date, lang),
        "recipient.name": ", ".join(r for r in recipients if r),
    }
    items = sorted(tm.items or [], key=lambda i: i.item_number or 0)
    table = TableSpec(
        header=[tr(lang, "item_no"), tr(lang, "item_description"), tr(lang, "item_notes")],
        rows=[[str(i.item_number), i.description or "", i.notes or ""] for i in items],
        col_widths_mm=(14, 100, 56),
    )
    meta = [
        (tr(lang, "recipients"), values["recipient.name"]),
        (tr(lang, "cover_note"), tm.cover_note or ""),
    ]
    return RecordDocument(
        values=values,
        meta=[m for m in meta if m[1]],
        table=table if items else None,
        project_id=tm.project_id,
        filename=f"transmittal-{tm.transmittal_number or tm.id}",
        locale=getattr(project, "locale", None),
    )


def transmittal_kind() -> DocumentKind:
    """The transmittal cover letter around the list of documents sent."""
    return DocumentKind(
        key=TRANSMITTAL_KEY,
        channel="pdf",
        module="transmittals",
        label="Transmittal cover letter",
        blocks=("title", "intro", "terms", "closing", "signature", "footer"),
        fields=_BASE_FIELDS,
        defaults=lambda lang: _TRANSMITTAL_DEFAULTS.get(lang, {}),
        languages=("en", "de"),
        required_blocks=("title",),
        appearance_type="transmittal",
        records=_transmittal_records,
        record_document=_transmittal_document,
    )
