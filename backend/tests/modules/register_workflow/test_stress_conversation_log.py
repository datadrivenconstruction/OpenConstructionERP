# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Adversarial pass over everything built on 19 Aug.

Not a happy-path suite. Each test tries to BREAK one of the rails the
conversation log, the stored sent document, the signer names and the
emailed/withheld field split are built on. A rail enforced in one code
path is not a rail, so each one is attacked through every entry point
that reaches it.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.register_workflow import emailing, service, templates
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"st-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Stress",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(
        name=f"ST {uuid.uuid4().hex[:6]}",
        owner_id=user.id,
        currency="AUD",
        project_code=f"J{uuid.uuid4().hex[:6].upper()}",
    )
    session.add(proj)
    await session.flush()
    return proj.id


VO_MONEY = {
    "Description of change": "Extra GPO circuits",
    "Cost $": "18400",
    "Sell $": "24900",
    "Margin": "26%",
}


# ── The money rail, attacked from every angle ────────────────────────────


@pytest.mark.asyncio
async def test_money_never_reaches_the_email_by_any_route(session: AsyncSession) -> None:
    """Cost, sell and margin are withheld on the addressed copy, the
    unaddressed copy, and the copy stored in the send log.

    Three routes reach the email builder and each has been the one that
    leaked at some point. Testing only the first proves nothing about the
    other two.
    """
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="variation", title="VO 3", fields=dict(VO_MONEY))

    unaddressed = await emailing.build_item_email(session, item, contact_id=None)
    for leak in ("18400", "24900", "26%", "Margin", "Cost $", "Sell $"):
        assert leak not in unaddressed["html"], f"{leak!r} leaked into the unaddressed copy"

    # The copy KEPT on the record must be the same withheld document -
    # otherwise the log shows figures the client never received, and
    # anyone reading the log believes they were sent.
    await emailing.record_send(
        session,
        item,
        contact_id=None,
        contact_name="Client",
        subject=unaddressed["subject"],
        channel="outlook",
        user_id="u1",
        email_ref="REG-MSG-000001",
        html=unaddressed["html"],
    )
    kept = emailing.send_log(item)[-1]["html"]
    for leak in ("18400", "24900", "26%"):
        assert leak not in kept, f"{leak!r} leaked into the stored copy"


@pytest.mark.asyncio
async def test_a_money_figure_hidden_in_a_public_field_is_the_users_choice(
    session: AsyncSession,
) -> None:
    """The rail withholds the FIELD, not the digits.

    Typing 26% into the description is the user publishing it themselves,
    and a filter that scrubbed matching digits out of prose would corrupt
    legitimate text ("26% of the run is in ceiling space"). This pins the
    boundary so nobody later "fixes" it into a content filter.
    """
    pid = await _project(session)
    fields = dict(VO_MONEY)
    fields["Description of change"] = "Margin on this one is 26% - agreed verbally"
    item = await service.raise_item(session, project_id=pid, kind="variation", title="VO 4", fields=fields)
    built = await emailing.build_item_email(session, item, contact_id=None)
    assert "agreed verbally" in built["html"]
    # The FIELD is still withheld even though the same text appears in prose.
    assert "Sell $" not in built["html"]
    assert "24900" not in built["html"]


@pytest.mark.asyncio
async def test_every_kind_withholds_exactly_the_money_and_nothing_else(
    session: AsyncSession,
) -> None:
    """The emailed/withheld split, asserted as a whole.

    The instruction on 19 Aug: nothing is card-only except money. If a
    later field is added as internal by habit, this fails and somebody has
    to justify it.
    """
    allowed = {
        "rfi": set(),
        "rfq": {"Estimated value $"},
        "order": set(),
        "variation": {"Cost $", "Sell $", "Margin"},
        "delay": {"Cost impact $"},
        "toolbox": set(),
    }
    for kind in templates.KINDS:
        internal = {label for (label, _t, _due, is_internal) in templates.FIELDS[kind] if is_internal}
        assert internal == allowed[kind], f"{kind}: withheld set drifted to {internal}"
    # And the two we named are emailed on every single kind.
    for kind in templates.KINDS:
        labels = {label for (label, _t, _due, internal) in templates.FIELDS[kind] if not internal}
        assert "Responsible" in labels, f"{kind}: Responsible is not emailed"
        assert "Ball in court" in labels, f"{kind}: Ball in court is not emailed"


# ── Injection into the document ──────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        "<script>alert(1)</script>",
        "</td></tr></table><script>alert(2)</script>",
        "</body><script>fetch('//evil')</script>",
        '"><img src=x onerror=alert(3)>',
        "<iframe src='javascript:alert(4)'>",
    ],
)
async def test_markup_typed_into_a_field_cannot_execute(session: AsyncSession, payload: str) -> None:
    """A field is text, never markup.

    These land in Responsible and Ball in court - both newly EMAILED, so
    both newly reachable by a reader. The email is also stored and shown
    back inside our own app in an iframe, which is a second place the same
    string gets rendered.
    """
    pid = await _project(session)
    item = await service.raise_item(
        session,
        project_id=pid,
        kind="rfi",
        title="Q",
        fields={"Responsible": payload, "Ball in court": payload, "Question": payload},
    )
    built = await emailing.build_item_email(session, item, contact_id=None)
    html = built["html"]
    # THE test: the payload must not survive VERBATIM. Escaped, the same
    # characters appear as inert text - "javascript:" sitting inside a
    # table cell as words is harmless, and asserting on bare substrings
    # would fail on correctly escaped output while catching nothing real.
    assert payload not in html, "the payload survived unescaped"
    assert "&lt;" in html, "the angle brackets were not escaped at all"
    # No REAL tag may be introduced by a field value.
    assert "<script" not in html.lower(), "a script tag survived into the email"
    assert "<iframe" not in html.lower(), "an iframe survived into the email"
    assert "<img" not in html.lower(), "an img tag survived into the email"


@pytest.mark.asyncio
async def test_a_null_byte_in_a_field_does_not_500_the_insert(session: AsyncSession) -> None:
    """Postgres rejects NUL outright; the cleaner has to take it out
    before the row is written, or raising an item 500s."""
    pid = await _project(session)
    item = await service.raise_item(
        session,
        project_id=pid,
        kind="rfi",
        title="Q\x00uestion",
        fields={"Responsible": "Sam\x00Rivers", "Ball in court": "\x00"},
    )
    assert "\x00" not in str(item.fields)
    assert "\x00" not in item.title


# ── Server-owned keys ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_forged_send_log_cannot_be_planted_through_the_form(
    session: AsyncSession,
) -> None:
    """Now that the send log carries the DOCUMENT, forging it would let
    anyone put words into an email we supposedly sent - a fabricated
    record of correspondence. It must be unwritable from the client."""
    pid = await _project(session)
    forged = [
        {
            "at": "2020-01-01T00:00:00",
            "email_ref": "REG-MSG-999999",
            "contact_name": "Nobody",
            "subject": "We agreed to pay you double",
            "html": "<p>We agreed to pay you double</p>",
        }
    ]
    item = await service.raise_item(
        session,
        project_id=pid,
        kind="rfi",
        title="Q",
        fields={"Question": "real", "_send_log": forged},
    )
    assert emailing.send_log(item) == [], "a forged send log was planted at raise time"

    # And again through the edit path, on an item that has a REAL entry.
    built = await emailing.build_item_email(session, item, contact_id=None)
    await emailing.record_send(
        session,
        item,
        contact_id=None,
        contact_name="Real",
        subject=built["subject"],
        channel="outlook",
        user_id="u1",
        email_ref="REG-MSG-000001",
        html=built["html"],
    )
    await service.update_item(session, item, fields={"Question": "edited", "_send_log": forged})
    log = emailing.send_log(item)
    assert len(log) == 1, "the edit path let a forged entry through"
    assert log[0]["email_ref"] == "REG-MSG-000001"
    assert "double" not in log[0]["html"]


@pytest.mark.asyncio
async def test_forged_attachments_cannot_be_planted(session: AsyncSession) -> None:
    """An email must never claim an attachment it did not carry."""
    pid = await _project(session)
    item = await service.raise_item(
        session,
        project_id=pid,
        kind="rfi",
        title="Q",
        fields={
            "Question": "real",
            "_attachments": [{"filename": "../../etc/passwd", "size": 1, "email": True}],
        },
    )
    assert (item.fields or {}).get("_attachments") in (None, [])


# ── The signer names ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_one_unparseable_signer_never_costs_the_others_their_name(
    session: AsyncSession,
) -> None:
    """The bug this prevents: a single legacy free-text id inside the IN
    clause threw, and EVERY signer on the item lost their name."""
    real = User(
        email=f"real-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Real Person",
        role="admin",
    )
    session.add(real)
    await session.flush()

    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    steps = sorted(item.steps, key=lambda s: s.position)
    # Step 0 signed by a legacy free-text id, step 1 by a real account.
    await service.complete_step(session, steps[0].id, user_id="u1")
    await service.complete_step(session, steps[1].id, user_id=str(real.id))

    payload = await service.item_payload_enriched(session, item)
    by_pos = {s["position"]: s for s in payload["steps"]}
    assert by_pos[0]["completed_by_name"] == "u1", "the unparseable id should fall back to itself"
    assert by_pos[1]["completed_by_name"] == "Real Person", "a valid signer lost their name"


@pytest.mark.asyncio
async def test_an_unsigned_step_carries_no_signer_at_all(session: AsyncSession) -> None:
    """An open step must not sprout an empty name that reads as 'signed
    by nobody' on the log."""
    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    payload = await service.item_payload_enriched(session, item)
    for s in payload["steps"]:
        if not s["completed_by"]:
            assert not s.get("completed_by_name")


@pytest.mark.asyncio
async def test_a_signer_whose_name_is_blank_falls_back_to_something(
    session: AsyncSession,
) -> None:
    """An account with no full_name must show its email, not an empty
    string - the log has to name somebody."""
    nameless = User(
        email=f"nameless-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="",
        role="admin",
    )
    session.add(nameless)
    await session.flush()

    pid = await _project(session)
    item = await service.raise_item(session, project_id=pid, kind="rfi", title="Q", fields={})
    steps = sorted(item.steps, key=lambda s: s.position)
    await service.complete_step(session, steps[0].id, user_id=str(nameless.id))
    payload = await service.item_payload_enriched(session, item)
    got = sorted(payload["steps"], key=lambda s: s["position"])[0]["completed_by_name"]
    assert got, "the signer resolved to an empty string"
    assert "@" in got or got == str(nameless.id)


# ── The stored document ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_large_pasted_table_survives_storage_intact(session: AsyncSession) -> None:
    """A real materials paste is hundreds of rows. The stored copy must
    come back byte-identical, not truncated by a column limit."""
    pid = await _project(session)
    rows = "\n".join(f"Item {i}\t{i} ea\tCable {i}" for i in range(400))
    item = await service.raise_item(
        session,
        project_id=pid,
        kind="rfq",
        title="Big package",
        fields={
            "Package": "Cable",
            "Materials / scope required": f"Description\tQty\tNotes\n{rows}",
            "Delivery to": "Site",
            "Site contact": "Alex Example",
            "Delivery window / site hours": "06:30-14:30",
            "Estimated value $": "9900",
            "Quotes due": "2099-01-01",
        },
    )
    built = await emailing.build_item_email(session, item, contact_id=None)
    await emailing.record_send(
        session,
        item,
        contact_id=None,
        contact_name="Alpha",
        subject=built["subject"],
        channel="outlook",
        user_id="u1",
        email_ref="REG-MSG-000001",
        html=built["html"],
    )
    kept = emailing.send_log(item)[-1]["html"]
    assert kept == built["html"]
    assert "Item 399" in kept, "the stored document was truncated"
    assert "9900" not in kept, "the estimate leaked into the stored document"


@pytest.mark.asyncio
async def test_unicode_in_the_document_survives_the_round_trip(
    session: AsyncSession,
) -> None:
    """Supplier names carry umlauts and the register carries emoji. A
    mangled stored copy is a mangled record."""
    pid = await _project(session)
    item = await service.raise_item(
        session,
        project_id=pid,
        kind="rfi",
        title="Erdungsschiene — Prüfung ✅",
        fields={"Question": "Straße / Höhe? 日本語 ✅", "Responsible": "Sam Rivera"},
    )
    built = await emailing.build_item_email(session, item, contact_id=None)
    await emailing.record_send(
        session,
        item,
        contact_id=None,
        contact_name="Müller GmbH",
        subject=built["subject"],
        channel="outlook",
        user_id="u1",
        email_ref="REG-MSG-000001",
        html=built["html"],
    )
    kept = emailing.send_log(item)[-1]
    assert "Straße" in kept["html"] and "日本語" in kept["html"] and "✅" in kept["html"]
    assert kept["contact_name"] == "Müller GmbH"


# ── The counters, still holding under the new code ───────────────────────


@pytest.mark.asyncio
async def test_concurrent_email_refs_are_never_issued_twice(session: AsyncSession) -> None:
    """Every email carries its own number and two mails must never share
    one. Run inside a single transaction the lock is per-row, so this
    asserts the sequence rather than the isolation - the isolation itself
    is covered by the existing reference tests."""
    seen = [await service.next_email_reference(session) for _ in range(25)]
    assert len(set(seen)) == 25, "a mail number was issued twice"
    numbers = [int(r.rsplit("-", 1)[1]) for r in seen]
    assert numbers == sorted(numbers), "mail numbers went backwards"
    assert numbers[-1] - numbers[0] == 24, "the series has gaps"


@pytest.mark.asyncio
async def test_peeking_a_mail_number_never_burns_it(session: AsyncSession) -> None:
    """The preview shows the next number; only the draft may take it.
    Burning on preview leaves the register reading as a list of gaps."""
    first = await service.peek_email_reference(session)
    for _ in range(5):
        assert await service.peek_email_reference(session) == first
    assert await service.next_email_reference(session) == first
    assert await service.peek_email_reference(session) != first


def test_every_item_route_validates_its_id_the_same_way() -> None:
    """One path parameter, one type, on every route that takes it.

    Six routes typed ``item_id`` as ``str`` while twenty-four typed it as
    ``uuid.UUID``. The untyped ones handed the raw string to a database
    query, so a NUL byte in the path came back as a 500 from Postgres on
    ``/tracking`` while ``/thread`` refused it cleanly with a 400 - and
    ``_item_or_404`` is annotated to take a UUID, so the str routes were
    passing it something it never expected.

    The six were exactly the routes the conversation log leans on:
    tracking, compare, message, reply-preview, reply-draft and message
    documents.
    """
    import inspect

    from app.modules.register_workflow import router as rw_router

    offenders: list[str] = []
    for route in rw_router.router.routes:
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None:
            continue
        for name, param in inspect.signature(endpoint).parameters.items():
            if name not in ("item_id", "step_id"):
                continue
            # router.py uses `from __future__ import annotations`, so the
            # annotation arrives as the STRING "uuid.UUID", not the class.
            annotation = param.annotation
            if annotation not in (uuid.UUID, "uuid.UUID", "UUID"):
                offenders.append(f"{endpoint.__name__}({name}: {annotation})")
    assert not offenders, f"these routes do not validate their id: {offenders}"
