# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A derived deadline's title cannot be edited into something nobody reads.

``title_key`` is not stored. It is worked out from ``source``: a row this
module derived is named by its ``kind``, which is an enum and translates, and
a row somebody typed is named by their own words, which do not. That line only
ever held because this module wrote the titles of the rows it derives, and
nothing was keeping it true afterwards.

``PATCH /obligations/{id}`` was the door left open. It set whatever fields it
was given, so somebody's words could land on a ``programme_rule`` row. The row
kept that source, so it kept the key, so the next caller rendered the key and
put "Final proof of use" back over what they had written. The words were not
overridden on screen once - they were never read at all, on any client, in any
language, because a caller is told to render the key and ignore the prose.

Three ways out were weighed and the refusal is the one that holds:

* Promoting the row to a typed source would make the key stop firing, but
  ``source`` is not only the title's discriminator. ``delete_derived`` reads
  it to decide which rows this module may regenerate, the obligation table
  shows it to the reader as where the deadline came from, and the funding
  insights report pivots on it. Renaming a deadline would then quietly take
  it out of the programme's control, leave a second copy behind the next time
  an award was re-recorded, and move a row between buckets in somebody's
  report. A presentation fix would have rewritten provenance.
* Clearing the key on the row would need somewhere to remember it was
  cleared, and the key is derived precisely so that no second copy of it can
  drift. There is no such field, and the one stored key on this table exists
  only because one kind tells two different sentences.

So the words the server wrote stay the server's, and everything else on the
row stays editable. The tests below hold both directions: a typed row takes
the change and keeps its author's words, and a derived row refuses it and
still answers with its kind key.
"""

from __future__ import annotations

import pathlib
import re
import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.funding import router as funding_router
from app.modules.funding.router import _title_key, update_obligation
from app.modules.funding.schemas import ObligationUpdate
from app.modules.funding.service import (
    DERIVED_WORDING_MESSAGE,
    DERIVED_WORDING_MESSAGE_KEY,
    SERVER_AUTHORED_TEXT_FIELDS,
    FundingService,
    server_authored_fields_replaced,
)
from app.modules.projects.models import Project  # noqa: F401 - register ORM
from app.modules.users.models import User
from tests._pg import transactional_session

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
_LOCALE_DIR = _REPO_ROOT / "frontend" / "src" / "app" / "locales"

#: A key the client already renders for every obligation. The files that
#: answer it are exactly the files that have to answer a new funding key, so
#: the set is asked of the tree rather than listed here.
_SIBLING_KEY = "funding.obligation_kind.final_report"


def _row(**overrides: Any) -> Any:
    """A stand-in obligation. Only the fields the policy reads are set."""
    fields: dict[str, Any] = {
        "source": "programme_rule",
        "kind": "final_report",
        "title": "Final proof of use",
        "detail": "Due 180 days after the award period ends, under the terms of KFW",
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


# ── The policy itself ───────────────────────────────────────────────────


def test_replacing_the_words_on_a_derived_row_is_refused() -> None:
    assert server_authored_fields_replaced(_row(), {"title": "Report to the ministry, ref 2026/88"}) == ("title",)


def test_replacing_the_words_on_a_row_somebody_typed_is_allowed() -> None:
    """Their row, their words. Both typed sources, because both are a person.

    ``manual`` and ``award_notice`` are the two values this module forces a
    hand written obligation into, and the earlier fix turned on exactly that:
    asking whether a row was ``manual`` called an award notice condition the
    server's own sentence. A guard that asked the same narrow question would
    reintroduce it from the other side, by refusing an edit to words the
    server never wrote.
    """
    for source in ("manual", "award_notice"):
        row = _row(source=source, kind="condition", title="Keep the funding sign up until handover")
        assert server_authored_fields_replaced(row, {"title": "Keep the sign up until handover"}) == ()


def test_sending_the_same_words_back_is_not_a_replacement() -> None:
    """A client that reads a row, ticks it done and sends the whole object.

    Refusing that would break the only flow the shipped screens use, and it
    changes nothing: the title arrives identical to the one already stored.
    """
    row = _row()
    assert server_authored_fields_replaced(row, {"title": row.title, "status": "done"}) == ()
    assert server_authored_fields_replaced(row, {"title": f"  {row.title}  ", "status": "done"}) == ()


def test_a_field_the_caller_never_set_is_not_a_replacement() -> None:
    assert server_authored_fields_replaced(_row(), {"status": "done", "completed_on": "2026-05-01"}) == ()


def test_emptying_the_server_s_sentence_counts_as_replacing_it() -> None:
    """``null`` and ``""`` both ask for the sentence to be gone.

    Skipping them would leave the widest version of the hole open: a row whose
    title is blank and whose key still names the kind, which reads as the
    stock sentence with no way for anyone to tell it was emptied on purpose.
    """
    assert server_authored_fields_replaced(_row(), {"title": None}) == ("title",)
    assert server_authored_fields_replaced(_row(), {"title": "   "}) == ("title",)


def test_the_detail_is_guarded_beside_the_title() -> None:
    """The same defect, and on this field the key is stored rather than derived.

    A caller renders ``detail_key`` and ignores ``detail``, so prose typed into
    a derived row's detail is not read by anybody. Accepting it is a silent
    no-op; refusing it says so.
    """
    assert server_authored_fields_replaced(_row(), {"detail": "Ask Petra for the form"}) == ("detail",)
    both = server_authored_fields_replaced(_row(), {"title": "Ministry report", "detail": "Ask Petra"})
    assert both == ("title", "detail")


def test_every_guarded_field_is_one_a_caller_can_actually_send() -> None:
    """A guard naming a field the request body has no room for is theatre."""
    sendable = set(ObligationUpdate.model_fields)
    assert sendable, "ObligationUpdate declares no fields at all"
    assert set(SERVER_AUTHORED_TEXT_FIELDS) <= sendable, {
        "guarded": sorted(SERVER_AUTHORED_TEXT_FIELDS),
        "sendable": sorted(sendable),
    }


# ── The message the refusal carries ─────────────────────────────────────


def test_the_refusal_says_something_and_can_be_said_in_another_language() -> None:
    assert DERIVED_WORDING_MESSAGE.strip()
    assert DERIVED_WORDING_MESSAGE_KEY.startswith("funding.")
    assert DERIVED_WORDING_MESSAGE_KEY.count(".") >= 2


def test_the_refusal_key_interpolates_nothing() -> None:
    """Nothing fills a placeholder in it, so a locale must not add one."""
    assert not re.findall(r"\{\{?(\w+)\}?\}", DERIVED_WORDING_MESSAGE)


def test_the_refusal_key_reaches_either_every_locale_or_none_of_them() -> None:
    """One locale gaining a key alone is how a translation silently drifts.

    The key is minted here and the locale files are written separately, so
    this starts out satisfied by nobody answering it and becomes a real check
    the moment the translations land. What it will not tolerate is the half
    state, where some readers get the sentence and the rest get the raw key
    printed at them.
    """
    assert _LOCALE_DIR.is_dir(), f"the locale directory moved: {_LOCALE_DIR}"
    required = [
        path
        for path in sorted(_LOCALE_DIR.glob("*.ts"))
        if re.search(rf'"{re.escape(_SIBLING_KEY)}":', path.read_text("utf-8"))
    ]
    assert len(required) >= 40, [path.name for path in required]

    answering = [
        path.name
        for path in required
        if re.search(rf'"{re.escape(DERIVED_WORDING_MESSAGE_KEY)}":', path.read_text("utf-8"))
    ]
    # A gate nobody answers yet is vacuously true, and a vacuous green reads
    # exactly like a real one. So the empty case says so out loud, with the
    # population beside it, instead of passing quietly.
    if not answering:
        pytest.skip(f"population={len(required)}, answering=0: the refusal key is not in the locale files yet")
    assert len(answering) == len(required), {
        "population": len(required),
        "answering": len(answering),
        "missing": sorted({path.name for path in required} - set(answering)),
    }


# ── The endpoint, against a real database ───────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _awarded(session: AsyncSession) -> tuple[FundingService, Any, str]:
    """An approved application, its deadlines derived, and an admin to call as."""
    service = FundingService(session)
    user = User(
        email=f"funding-wording-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Funding",
        role="admin",
    )
    session.add(user)
    await session.flush()
    project = Project(name=f"Funding {uuid.uuid4().hex[:6]}", owner_id=user.id, currency="EUR")
    session.add(project)
    await session.flush()

    programme = await service.programmes.create(
        code=f"KFW-{uuid.uuid4().hex[:6].upper()}",
        name="Energy efficient refurbishment",
        country="DE",
        proof_of_use_due_days=180,
        retention_years=10,
        currency="EUR",
        status="open",
    )
    application = await service.applications.create(
        project_id=project.id,
        programme_id=programme.id,
        code=f"APP-{uuid.uuid4().hex[:6].upper()}",
        currency="EUR",
        status="draft",
        eligible_cost_base=Decimal("1000000"),
        requested_amount=Decimal("350000"),
    )
    await service.record_award(
        application,
        approved=True,
        approved_amount=Decimal("350000"),
        award_period_start="2026-04-01",
        award_period_end="2026-12-31",
    )
    return service, application, str(user.id)


async def _derived(service: FundingService, application: Any) -> Any:
    rows = await service.obligations.list_for_application(application.id)
    derived = [row for row in rows if row.source == "programme_rule" and row.kind == "final_report"]
    assert derived, "the award produced no derived deadline to test against"
    return derived[0]


async def _patch(session: AsyncSession, service: FundingService, row: Any, user_id: str, **fields: Any) -> Any:
    return await update_obligation(
        obligation_id=row.id,
        data=ObligationUpdate(**fields),
        session=session,
        user_id=user_id,
        today="2026-05-01",
        _perm=None,
        service=service,
    )


async def test_a_typed_obligation_keeps_the_words_its_author_gave_it(session: AsyncSession) -> None:
    """Direction one: the change lands, and no key comes back to overwrite it."""
    service, application, user_id = await _awarded(session)
    typed = await service.obligations.create(
        application_id=application.id,
        kind="condition",
        title="Keep the funding sign on the hoarding",
        detail="Paragraph 7 of the notice",
        due_on="2026-05-01",
        source="award_notice",
        status="open",
    )

    out = await _patch(session, service, typed, user_id, title="Keep the sign up until handover")

    assert out.title == "Keep the sign up until handover"
    assert out.title_key == ""
    assert typed.title == "Keep the sign up until handover"


async def test_a_derived_deadline_refuses_the_change_and_keeps_its_key(session: AsyncSession) -> None:
    """Direction two: the row this module wrote still answers with its kind."""
    service, application, user_id = await _awarded(session)
    row = await _derived(service, application)
    before = row.title

    with pytest.raises(HTTPException) as caught:
        await _patch(session, service, row, user_id, title="Report to the ministry, ref 2026/88")

    assert caught.value.status_code == 409
    detail = caught.value.detail
    assert detail["message_key"] == DERIVED_WORDING_MESSAGE_KEY
    assert detail["message"] == DERIVED_WORDING_MESSAGE
    assert detail["fields"] == ["title"]
    # Nothing was written on the way to the refusal.
    assert row.title == before
    assert _title_key(row) == "funding.obligation_kind.final_report"


async def test_without_the_guard_the_very_same_request_lands_on_the_key_s_row(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard is what refuses, and this is the defect it refuses.

    A test that only ever watches the endpoint say no cannot tell a working
    guard from a request that was being turned away for some other reason.
    With the policy neutered the same call lands, and the row it lands on
    still answers with the kind key - so a caller rendering that key puts
    "Final proof of use" back over the words just written. Restating the
    defect as a measurement is also what keeps this file failing in both
    directions rather than only in the comfortable one.
    """
    service, application, user_id = await _awarded(session)
    row = await _derived(service, application)
    monkeypatch.setattr(funding_router, "server_authored_fields_replaced", lambda *_args: ())

    out = await _patch(session, service, row, user_id, title="Report to the ministry, ref 2026/88")

    assert out.title == "Report to the ministry, ref 2026/88"
    assert out.title_key == "funding.obligation_kind.final_report"


async def test_a_derived_deadline_can_still_be_ticked_off(session: AsyncSession) -> None:
    """The one thing the shipped screens do with this endpoint still works."""
    service, application, user_id = await _awarded(session)
    row = await _derived(service, application)

    out = await _patch(session, service, row, user_id, status="done", completed_on="2026-05-01")

    assert out.status == "done"
    assert out.completed_on == "2026-05-01"
    assert out.title_key == "funding.obligation_kind.final_report"


async def test_a_derived_deadline_can_still_be_moved_and_handed_to_somebody(session: AsyncSession) -> None:
    """The refusal is about the words, not about the row.

    A deadline that moves is the ordinary case - an authority grants an
    extension and somebody records it - and refusing that would have made the
    guard a reason to stop using the endpoint.
    """
    service, application, user_id = await _awarded(session)
    row = await _derived(service, application)

    out = await _patch(session, service, row, user_id, due_on="2027-03-31", responsible_user_id=user_id)

    assert out.due_on == "2027-03-31"
    assert out.responsible_user_id == user_id
    assert out.title_key == "funding.obligation_kind.final_report"
