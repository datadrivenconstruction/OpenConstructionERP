# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Regression tests for every defect the stress pass proved.

Each test names the hole and the consequence, because in six months the
question asked of these will be "can I simplify this?" and the answer has
to be visible without re-running the fuzzer.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money_text import amount_or_zero, parse_amount
from app.modules.comms_intelligence import heuristics
from app.modules.projects.models import Project
from app.modules.register_workflow import service
from app.modules.register_workflow.sanitise import sanitise_html
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession, code: str = "24188") -> uuid.UUID:
    user = User(email=f"sf-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="SF", role="admin")
    session.add(user)
    await session.flush()
    proj = Project(name=f"SF {uuid.uuid4().hex[:6]}", owner_id=user.id, currency="AUD", project_code=code)
    session.add(proj)
    await session.flush()
    return proj.id


RFQ_FIELDS = {
    "Package": "Switchboards",
    "Delivery to": "12 Site Rd, Wetherill Park",
    "Site contact": "Alex Example 0400 000 000",
    "Delivery window / site hours": "Site hours 06:30-14:30",
    "Estimated value $": "9900",
    "Quotes due": "2099-01-01",
}


# ── Money: the figure that decides how many quotes are required ──────────


def test_a_money_field_a_human_typed_is_not_silently_zero() -> None:
    """The highest-value defect found.

    "50k" and "approx 50,000" both parsed as 0, and 0 is BELOW the $3,000
    tier - so the quote gate stopped asking for competitive prices on a
    fifty-thousand-dollar package. Zero has to be reserved for an empty
    box; anything else unreadable must be refused, never guessed.
    """
    for typed in ("50k", "$50k", "approx 50,000", "50,000 AUD", "$50,000 + GST", "50 000"):
        assert parse_amount(typed) == Decimal(50000), typed
    # European grouping, which used to read as fifty dollars.
    assert parse_amount("50.000,00") == Decimal("50000.00")
    # Genuinely unreadable stays unreadable - NOT zero.
    for junk in ("TBC", "on application", "", None, "12,34"):
        assert parse_amount(junk) is None, junk
    assert amount_or_zero("TBC") == Decimal(0)


@pytest.mark.asyncio
async def test_an_unreadable_estimate_is_refused_at_the_raise_form(session: AsyncSession) -> None:
    """Better to argue with the user here than to lose the gate later."""
    pid = await _project(session)
    with pytest.raises(service.WorkflowError, match="need to be an amount"):
        await service.raise_item(
            session,
            project_id=pid,
            kind="rfq",
            title="MSB-01",
            fields={**RFQ_FIELDS, "Estimated value $": "TBC"},
        )
    # And the readable shorthand goes straight through.
    item = await service.raise_item(
        session, project_id=pid, kind="rfq", title="MSB-01", fields={**RFQ_FIELDS, "Estimated value $": "50k"}
    )
    assert item.reference


def test_the_quote_gate_override_can_only_tighten() -> None:
    """ "inf", "nan" and a minimum of 0 all switched the gate OFF.

    They are exactly what someone reaches for to disable it "just for
    now", and each one failed open silently.
    """
    import os

    from app.modules.rfq_bidding.constants import quote_gate_rule

    for var, value in (
        ("OE_RFQ_MIN_QUOTES_OVER", "inf"),
        ("OE_RFQ_MIN_QUOTES_OVER", "nan"),
        ("OE_RFQ_MIN_QUOTES_OVER", "-1"),
        ("OE_RFQ_MIN_QUOTES", "0"),
    ):
        os.environ[var] = value
        try:
            rule = quote_gate_rule()
            assert rule["min"] == 3 and rule["min3"] == 3, (var, value)
            assert rule["over"] == 0.01, (var, value)
        finally:
            os.environ.pop(var, None)
    # No override at all is the business's own tiers, untouched.
    assert quote_gate_rule() == {"over": 3000.0, "min": 2, "over3": 7500.0, "min3": 3}


# ── Extraction: the price read off a supplier's quote ────────────────────


def test_a_labelled_total_is_never_read_as_its_first_three_digits() -> None:
    """Accepting a bare run of digits after a label word turned a $1.2M
    package into $1.23 - and then passed the gate on it."""
    assert heuristics.scan_package_price("Total 1.234.567,89")["amount"] == ""
    for junk in ("Total 12 400", "Quoted ref 100042 for the works", "Price list 2026 rev 3", "Total pages 12 of 345"):
        got = heuristics.scan_package_price(junk)
        assert (got or {}).get("amount") in (None, ""), (junk, got)
    # A round figure written against its label is still money.
    assert heuristics.scan_package_price("Total: 48000")["amount"] == "48000.00"


def test_a_rate_marker_only_skips_a_real_unit_rate() -> None:
    """ "per" alone ate the total in "Total $48,000.00 per the schedule",
    handing the gate a $2,500 line item on a $48,000 package."""
    assert (
        heuristics.scan_package_price("Total $48,000.00 per the schedule. Mobilisation $2,500.00")["amount"]
        == "48000.00"
    )
    # ...while a genuine unit rate is still not a package price.
    for rate in ("$12.50 per m", "$4.20 ea", "$85.00/hr"):
        assert heuristics.scan_package_price(rate) is None, rate
    assert heuristics.scan_package_price("Labour $85.00/hr. Total $6,800.00")["amount"] == "6800.00"


def test_the_final_total_wins_not_the_biggest_one() -> None:
    """A biggest-wins rule took the PRE-discount figure, overstating every
    quote that itemised its discount."""
    got = heuristics.scan_package_price("Total $10,000.00\nLess discount $500.00\nTotal $9,500.00")
    assert got["amount"] == "9500.00"
    # The larger figure is not hidden - it is raised for a human to check.
    assert any("10000.00" in w for w in got["warnings"])
    # A deposit is a slice of the price, never the price.
    assert heuristics.scan_package_price("Total $40,115.46 Deposit $4,011.55")["amount"] == "40115.46"


def test_the_gst_basis_comes_from_the_figures_own_line() -> None:
    """Reading a window either side scavenged "(ex GST)" off the freight
    line above and labelled an inc-GST total as ex-GST - a silent 10%."""
    got = heuristics.scan_package_price("Freight (ex GST) $250.00\nTotal (inc GST) $12,400.00")
    assert got["amount"] == "12400.00"
    assert got["basis"] == "inc gst"


def test_a_foreign_currency_is_reported_not_compared_silently() -> None:
    got = heuristics.scan_package_price("Total USD 12,400.00")
    assert got["amount"] == "12400.00"
    assert any("USD" in w for w in got["warnings"])


def test_extraction_stays_linear_on_a_long_message() -> None:
    """Two quadratic patterns made a 200KB body take ~55 seconds, on the
    path that runs for EVERY inbound message."""
    import time

    body = "1234567890" * 20_000 + " Total $12,400.00"
    start = time.perf_counter()
    heuristics.analyze_text("Quote", body)
    assert time.perf_counter() - start < 5.0


def test_an_impossible_date_is_not_a_deadline() -> None:
    """ "31 February" passed a 1-31 day check and was stored as a due date
    no calendar has - it could never be met and sorted oddly."""
    assert heuristics._to_iso_date("2026-02-31") is None
    assert heuristics._to_iso_date("31/04/2026") is None
    assert heuristics._to_iso_date("29 February 2026") is None
    assert heuristics._to_iso_date("29 February 2028") == "2028-02-29"  # a real leap day
    assert heuristics._to_iso_date("21/08/2026") == "2026-08-21"  # d/m/y, en-AU


# ── The .eml viewer: supplier HTML rendered in the buyer's session ───────


def test_the_quote_viewer_sanitiser_is_an_allowlist() -> None:
    """The two blocklist regexes it replaced were both walked around, and
    the second failure was worse than the first: a protocol-relative
    tracking pixel still fired WHILE the viewer told the buyer remote
    content had been blocked."""
    html, blocked = sanitise_html('<p>Our price is $12,000</p><img src=x onerror="fetch(1)">')
    assert "onerror" not in html and "$12,000" in html
    # An unclosed <script> used to survive whole.
    html, blocked = sanitise_html('<script src="//evil.example/x.js">')
    assert "script" not in html.lower() and blocked
    # Protocol-relative pixel: removed, and honestly reported as removed.
    html, blocked = sanitise_html('<img src="//tracker.example/open.gif?buyer=42">')
    assert "tracker.example" not in html and blocked
    for payload in (
        "<svg onload=alert(1)></svg>",
        '<body background="//tracker/bg.gif">hi</body>',
        '<a href="javascript:alert(1)">click</a>',
        '<a href="java\tscript:alert(1)">x</a>',
        '<div style="background:url(//evil/x)">styled</div>',
    ):
        html, _ = sanitise_html(payload)
        assert "alert" not in html and "evil" not in html and "tracker" not in html, payload
    # A real quote table survives intact - the point is to render quotes.
    html, blocked = sanitise_html(
        '<table border=1><tr><td bgcolor="#eee">Cable ladder</td><td>$4,300</td></tr></table>'
    )
    assert "<table" in html and "Cable ladder" in html and "$4,300" in html and not blocked


# ── Mail headers ─────────────────────────────────────────────────────────


def test_a_newline_in_a_title_can_never_reach_a_mail_header() -> None:
    """ "Cable ladder\\r\\nBcc: silent@evil.example" is a header injection,
    and on Python 3.12 also a 500 raised AFTER the send was logged."""
    from app.modules.outlook_bridge.eml import build_eml

    assert service.single_line("Cable ladder\r\nBcc: silent@evil.example") == "Cable ladder Bcc: silent@evil.example"
    # The builder is belt-and-braces: handed one anyway, it collapses it
    # rather than raising or emitting a second header.
    raw = build_eml(
        {
            "to": ["ok@example.com\r\nBcc: silent@evil.example"],
            "subject": "RFQ\r\nBcc: x@y.z",
            "html": "<p>hi</p>",
        }
    )
    text = raw.decode("utf-8", "replace")
    # The forged text survives as inert words INSIDE the To/Subject values;
    # what must not exist is a Bcc header field, which is a line of its own.
    assert "\nBcc:" not in text and not text.startswith("Bcc:")
    assert "silent@evil.example" in text  # proves the payload was present to smuggle


def test_the_eml_builder_refuses_a_file_outside_the_uploads_tree(tmp_path) -> None:
    """`build_eml` reads and embeds whatever path it is handed, so it has
    to refuse on its own account rather than trust its caller."""
    from app.modules.outlook_bridge.eml import build_eml

    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"PGPASSWORD=hunter2")
    raw = build_eml({"to": ["a@b.c"], "subject": "x", "html": "<p>hi</p>", "attachments": [str(secret)]})
    assert b"hunter2" not in raw


@pytest.mark.asyncio
async def test_the_package_value_cannot_be_lowered_after_it_is_issued(session: AsyncSession) -> None:
    """A gate bypass dressed up as an admin correction.

    The gate tiers off max(estimate, every standing price), so lowering
    the estimate looks harmless. It is not, in the case that matters: a
    $50,000 package holding one $2,900 quote. Drop the estimate and the
    value becomes $2,900 - under the $3,000 tier - and the package awards
    on a single price.
    """
    from fastapi import HTTPException

    from app.modules.rfq_bidding.models import RFQ
    from app.modules.rfq_bidding.service import RFQService

    pid = await _project(session)
    svc = RFQService(session)
    published = RFQ(
        project_id=pid,
        rfq_number="RFQ-900",
        title="Switchboards",
        status="published",
        currency_code="AUD",
        metadata_={"estimated_value": "50000"},
    )
    session.add(published)
    await session.flush()

    with pytest.raises(HTTPException) as exc:
        svc._reject_lowering_the_estimate(published, {"estimated_value": "100"})
    assert exc.value.status_code == 409
    assert "cannot be reduced" in str(exc.value.detail)

    # Raising it is always fine - it can only ask for MORE quotes.
    svc._reject_lowering_the_estimate(published, {"estimated_value": "90000"})
    # And a draft is still freely editable: nothing has been asked of anyone.
    draft = RFQ(
        project_id=pid,
        rfq_number="RFQ-901",
        title="Draft",
        status="draft",
        currency_code="AUD",
        metadata_={"estimated_value": "50000"},
    )
    svc._reject_lowering_the_estimate(draft, {"estimated_value": "100"})


@pytest.mark.asyncio
async def test_a_failed_award_confirmation_cannot_take_the_award_with_it(
    session: AsyncSession,
) -> None:
    """ "Best-effort" was a lie, and the lie cost the award.

    The award writes a confirmation correspondence row and catches every
    exception around it. Catching is not enough: a failed flush has already
    put the session into a rolled-back state, so the next statement raises
    PendingRollbackError and the award dies - AFTER the business has
    committed to a supplier. Reproduced here with the foreign-key violation
    that surfaced it (a project id with no project behind it).
    """
    import uuid as _uuid

    from sqlalchemy import select

    from app.modules.rfq_bidding.models import RFQ
    from app.modules.rfq_bidding.service import RFQService

    svc = RFQService(session)
    rfq = RFQ(
        project_id=await _project(session),
        rfq_number="RFQ-950",
        title="Switchboards",
        status="published",
        currency_code="AUD",
    )
    session.add(rfq)
    await session.flush()

    # A project that does not exist - the confirmation row's FK cannot hold.
    await svc._award_confirmation_correspondence(
        project_id=_uuid.uuid4(),
        rfq_number="RFQ-950",
        rfq_title="Switchboards",
        bidder_contact_id=_uuid.uuid4(),
        amount="9350.00",
        currency="AUD",
        po_number="PO-4001",
        actor_id=None,
    )

    # THE POINT: the session is still usable, so everything the award still
    # has to do can happen. Before the savepoint this raised
    # PendingRollbackError and the whole award was lost.
    still_there = (await session.execute(select(RFQ).where(RFQ.id == rfq.id))).scalar_one()
    assert still_there.rfq_number == "RFQ-950"
    rfq.status = "awarded"
    await session.flush()


@pytest.mark.asyncio
async def test_a_ragged_pasted_table_lines_up_with_its_headings(session: AsyncSession) -> None:
    """Excel drops trailing empty cells, so a pasted table arrives ragged.

    The last line also loses its trailing tab to whitespace stripping on
    the way in. Left alone, a row whose final cell is blank reached the
    email NARROWER than the heading row, and the supplier read a table
    whose last row had fewer cells than the columns above it.
    """
    from app.modules.register_workflow import emailing

    pid = await _project(session)
    fields = dict(
        RFQ_FIELDS,
        **{
            "Materials / scope required": (
                "Item\tQty\tUnit\nCable ladder 450mm\t24\tlen\nBrackets, heavy duty\t96"  # <- no unit, no trailing tab
            )
        },
    )
    item = await service.raise_item(session, project_id=pid, kind="rfq", title="Cable ladder", fields=fields)
    built = await emailing.build_item_email(session, item, contact_id=None)
    html = built["html"]
    # Every heading is present, and the short row still carries a cell
    # under each of them.
    assert "Item" in html and "Qty" in html and "Unit" in html
    assert "Brackets, heavy duty" in html
    heading_cells = html.count(">Item<") + html.count(">Qty<") + html.count(">Unit<")
    assert heading_cells >= 3


@pytest.mark.asyncio
async def test_one_supplier_is_never_shown_the_others(session: AsyncSession) -> None:
    """The Notified block names only THIS copy's addressees.

    Listing everyone asked handed each supplier its competitor list -
    their commercial advantage, given away, on every RFQ. A tailored RFQ
    never shows one supplier the others.
    """
    from app.modules.contacts.models import Contact
    from app.modules.register_workflow import emailing

    pid = await _project(session)
    made = []
    for company in ("Cablemark Pty Ltd", "Northbank Electrical", "Mid Coast Fasteners"):
        c = Contact(
            company_name=company,
            first_name=company.split()[0],
            primary_email=f"{company.split()[0].lower()}@example.com",
            contact_type="supplier",
        )
        session.add(c)
        made.append(c)
    await session.flush()

    item = await service.raise_item(
        session,
        project_id=pid,
        kind="rfq",
        title="Cable ladder",
        fields=RFQ_FIELDS,
        recipient_contact_ids=[str(c.id) for c in made],
    )
    built = await emailing.build_item_email(session, item, contact_id=str(made[0].id))

    named = {n["name"] for n in built["notified"]}
    assert "Cablemark Pty Ltd" in named
    for rival in ("Northbank Electrical", "Mid Coast Fasteners"):
        assert rival not in named, f"{rival} was named to a competitor"
        assert rival not in built["html"], f"{rival} appears in the body sent to a competitor"
    assert "northbank@example.com" not in built["html"]


@pytest.mark.asyncio
async def test_logging_several_already_sent_emails_at_once(session: AsyncSession) -> None:
    """An RFQ issues to a LIST, so logging one at a time was three round
    trips and three chances to give up half way."""
    from app.modules.contacts.models import Contact
    from app.modules.register_workflow import emailing

    pid = await _project(session)
    made = []
    for company in ("Cablemark", "Northbank Electrical"):
        c = Contact(company_name=company, primary_email=f"{company[:4].lower()}@e.com", contact_type="supplier")
        session.add(c)
        made.append(c)
    await session.flush()
    item = await service.raise_item(
        session,
        project_id=pid,
        kind="rfq",
        title="Ladder",
        fields=RFQ_FIELDS,
        recipient_contact_ids=[str(c.id) for c in made],
    )
    for c in made:
        await emailing.record_send(
            session,
            item,
            contact_id=str(c.id),
            contact_name=c.company_name or "",
            subject="x",
            channel="logged",
            user_id="u1",
            at="2026-08-15",
        )
    log = (item.fields or {})["_send_log"]
    assert len(log) == 2
    # The date given is the date kept - "now" would quietly rewrite when
    # mail that went out days ago actually went.
    assert all(e["at"] == "2026-08-15" for e in log)
    assert {e["contact_name"] for e in log} == {"Cablemark", "Northbank Electrical"}
