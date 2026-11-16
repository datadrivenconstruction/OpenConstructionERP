# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""RFI letter, meeting minutes and transmittal cover printed in the firm's wording."""

from __future__ import annotations

import io

import pytest

from app.modules.meetings.models import Meeting
from app.modules.projects.models import Project
from app.modules.rfi.models import RFI
from app.modules.transmittals.models import Transmittal, TransmittalItem
from tests.modules.doc_templates.test_doc_templates_api import _app, _http, _publish, _user, db_session  # noqa: F401


def _text(pdf: bytes) -> str:
    from pypdf import PdfReader

    return "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)


@pytest.fixture(autouse=True)
def _slow_fonts(monkeypatch):
    from app.modules.doc_templates import service as dt_service

    monkeypatch.setattr(dt_service, "PREVIEW_TIMEOUT", 120.0)


async def _project(session, owner_id) -> Project:
    project = Project(name="Haus B", owner_id=owner_id, locale="en")
    session.add(project)
    await session.flush()
    return project


@pytest.mark.asyncio
async def test_rfi_letter_carries_the_question_and_firm_wording(db_session) -> None:
    user = await _user(db_session)
    project = await _project(db_session, user.id)
    rfi = RFI(
        project_id=project.id,
        rfi_number="RFI-0042",
        subject="Footing depth at grid C4",
        question="Is 1.20 m below ground level sufficient at C4?",
        raised_by=user.id,
        response_due_date="2026-11-23",
    )
    db_session.add(rfi)
    await db_session.commit()
    async with _http(_app(db_session, str(user.id))) as c:
        await _publish(c, "rfi.rfi", "en", {"intro": "Please answer {{doc.number}} for {{project.name}} soon."})
        r = await c.get(f"/dt/rfi.rfi/records/{rfi.id}/pdf", params={"locale": "en"})
    assert r.status_code == 200, r.text
    text = _text(r.content)
    assert "Please answer RFI-0042 for Haus B soon." in text
    assert "1.20 m below ground level" in text


@pytest.mark.asyncio
async def test_minutes_list_the_actions(db_session) -> None:
    user = await _user(db_session)
    project = await _project(db_session, user.id)
    meeting = Meeting(
        project_id=project.id,
        meeting_number="M-007",
        meeting_type="progress",
        title="Site progress",
        meeting_date="2026-11-12",
        agenda_items=[{"topic": "Formwork level 2"}],
        action_items=[{"description": "Send revised rebar schedule", "due_date": "2026-11-19"}],
        minutes="Concrete pour moved by two days.",
    )
    db_session.add(meeting)
    await db_session.commit()
    async with _http(_app(db_session, str(user.id))) as c:
        r = await c.get(f"/dt/meetings.minutes/records/{meeting.id}/pdf", params={"locale": "de"})
    assert r.status_code == 200, r.text
    text = _text(r.content)
    assert "Protokoll M-007" in text
    assert "Send revised rebar schedule" in text and "Formwork level 2" in text


@pytest.mark.asyncio
async def test_transmittal_cover_lists_the_documents(db_session) -> None:
    user = await _user(db_session)
    project = await _project(db_session, user.id)
    tm = Transmittal(
        project_id=project.id, transmittal_number="TR-003", subject="Structural drawings", purpose_code="for_review"
    )
    db_session.add(tm)
    await db_session.flush()
    db_session.add(TransmittalItem(transmittal_id=tm.id, item_number=1, description="S-201 Rev C"))
    await db_session.commit()
    async with _http(_app(db_session, str(user.id))) as c:
        r = await c.get(f"/dt/transmittals.transmittal/records/{tm.id}/pdf", params={"locale": "en"})
    assert r.status_code == 200, r.text
    text = _text(r.content)
    assert "Transmittal TR-003: Structural drawings" in text and "S-201 Rev C" in text
