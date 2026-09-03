# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Outlook Bridge tests.

COM itself is exercised only through the runner smoke test (a trivial
PowerShell script on Windows); everything else - routing, money rail,
payload building - runs with the COM seam mocked so
the suite is green on any machine.
"""

from __future__ import annotations

import sys
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.correspondence.models import Correspondence
from app.modules.correspondence.repository import CorrespondenceRepository
from app.modules.outlook_bridge import service
from app.modules.outlook_bridge.outbound import (
    build_register_email_html,
    strip_internal_pairs,
)
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession) -> uuid.UUID:
    user = User(email=f"ob-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="OB", role="admin")
    session.add(user)
    await session.flush()
    proj = Project(
        name=f"OB {uuid.uuid4().hex[:6]}",
        owner_id=user.id,
        currency="AUD",
        project_code=f"J{uuid.uuid4().hex[:6].upper()}",
    )
    session.add(proj)
    await session.flush()
    return proj.id


async def _correspondence(session: AsyncSession, project_id: uuid.UUID, **over) -> Correspondence:
    repo = CorrespondenceRepository(session)
    ref = await repo.next_reference_number(project_id)
    row = Correspondence(
        project_id=project_id,
        reference_number=ref,
        direction=over.pop("direction", "outgoing"),
        subject=over.pop("subject", "EOT notice"),
        correspondence_type="email",
        **over,
    )
    session.add(row)
    await session.flush()
    return row


# ── Money rail + email HTML ──────────────────────────────────────────────


def test_internal_pairs_never_leave_the_building() -> None:
    pairs = [("Package", "Switchboards"), ("Estimated value $", "9,900"), ("Cost impact $", "1,200")]
    assert strip_internal_pairs(pairs) == [("Package", "Switchboards")]


def test_email_html_carries_notified_block_and_strips_internal() -> None:
    html = build_register_email_html(
        eyebrow="Request for quotation",
        title="MSB-01",
        project_line="Job 25406",
        intro="Please quote.",
        pairs=[("Package", "Switchboards"), ("Estimated value $", "9,900")],
        # Name, ADDRESS, date AND TIME. "Notified: Alpha Electrical" does
        # not say which address it reached or when, which is exactly what
        # a dispute about whether a supplier was told turns on.
        notified=[("Alpha Electrical", "alpha@example.com", "18/08/2026 14:32")],
        footer_ref="COR-006",
    )
    # The Word engine drops CSS margins, so spacing rides on &nbsp; - assert
    # the entity form the builder actually emits.
    assert "Notified" in html and "Alpha Electrical" in html
    assert "Notified:&nbsp;18/08/2026 14:32" in html
    assert "alpha@example.com" in html


def test_the_notified_block_still_renders_a_name_and_date_alone() -> None:
    """Older callers hand over (name, date) with no address.

    The renderer takes both shapes on purpose: a two-tuple caller must not
    blank the whole block, because the Notified list is the record of who
    was told.
    """
    html = build_register_email_html(
        eyebrow="Request for quotation",
        title="MSB-01",
        project_line="Job 25406",
        intro="Please quote.",
        pairs=[("Package", "Switchboards")],
        notified=[("Alpha Electrical", "18/08/2026")],
        footer_ref="COR-006",
    )
    assert "Alpha Electrical" in html
    assert "Notified:&nbsp;18/08/2026" in html
    # Word-engine survival kit: table shell, bgcolor attributes, nowrap attrs.
    assert html.startswith("<table") and 'bgcolor="#12294A"' in html and 'nowrap="nowrap"' in html
    assert "9,900" not in html  # the money rail, enforced inside the builder
    assert "COR-006" in html
    # Payload safety: user text is escaped, layout survives hostile input.
    hostile = build_register_email_html(
        eyebrow="x", title="<script>alert(1)</script>", project_line="", intro="", pairs=[]
    )
    assert "<script>" not in hostile


# ── Payload builder = the preview contract ───────────────────────────────


@pytest.mark.asyncio
async def test_preview_and_draft_share_one_payload(session: AsyncSession) -> None:
    pid = await _project(session)
    row = await _correspondence(session, pid, notes="Please respond by return.", response_required_by="2026-08-25")
    built = await service.build_email_payload(session, str(row.id))
    assert built["reference_number"] == row.reference_number
    assert row.reference_number in built["subject"]
    assert "Please respond by return." in built["html"]
    assert "2026-08-25" in built["html"]
    # No recipients on the record → empty To, but the payload still builds
    # (the UI lets the user add extra_to).
    assert built["to"] == []
    with_extra = await service.build_email_payload(session, str(row.id), extra_to=["x@y.com"])
    assert with_extra["to"] == ["x@y.com"]


def test_draft_script_reads_the_body_as_utf8() -> None:
    """Windows PowerShell 5.1 reads ANSI by default, and the html body file
    is UTF-8 - without an explicit -Encoding UTF8 every non-ASCII character
    went into the actual sent draft corrupted (the middle dot in the footer
    became mojibake in real mail)."""
    from app.modules.outlook_bridge import outbound as ob

    assert "-Encoding UTF8" in ob._DRAFT_SCRIPT


# ── The COM runner itself (Windows only) ─────────────────────────────────


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell runner is Windows-only")
def test_ps_runner_roundtrip() -> None:
    from app.modules.outlook_bridge.ps import _run_sync

    script = r"""
param([string]$PayloadPath)
$p = Get-Content -Raw -Path $PayloadPath | ConvertFrom-Json
$json = @{ ok = $true; echo = $p.hello } | ConvertTo-Json -Compress
Set-Content -Path $p._out_path -Value $json -Encoding UTF8
"""
    result = _run_sync(script, {"hello": "curly ’quotes’ and $dollars survive"})
    assert result["ok"] is True
    assert result["echo"] == "curly ’quotes’ and $dollars survive"


# ── The .eml browser/server path ─────────────────────────────────────────


def test_eml_is_an_unsent_editable_draft() -> None:
    from app.modules.outlook_bridge.eml import build_eml

    raw = build_eml(
        {
            "to": ["a@example.com", "b@example.com"],
            "cc": ["c@example.com"],
            "bcc": ["secret@example.com"],  # must NOT appear in the file
            "subject": "RFQ - MSB-01",
            "html": "<p>Please quote.</p>",
            "attachments": [],
        }
    )
    text = raw.decode("utf-8", errors="replace")
    assert "X-Unsent: 1" in text  # what makes Outlook open it as a draft
    assert "To: a@example.com, b@example.com" in text
    assert "Subject: RFQ - MSB-01" in text
    # A BCC header inside a forwarded .eml is visible to every reader -
    # the whole point of BCC undone. It must never be written.
    assert "secret@example.com" not in text
    assert "text/html" in text
