# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The paper preference reaches the paper, measured on the sheet itself.

Two defects met in this generator. ``oe_users_user.paper_size`` was offered in
Settings, stored, and read by no generator in the tree; and the transmittal
cover sheet was fixed at US Letter for the whole world, the only document here
pinned to Letter that is not about the United States. Fixing the first without
the second would have moved the defect one layer down: a preference that
reaches a generator which ignores it is still a preference that changes
nothing.

**So every assertion below is about the MediaBox of the rendered PDF**, not
about the code path taken to produce it. A test that asserted
``cover_page_size`` was called, or that it returned the right tuple, would have
passed against the old generator unchanged, because the old generator took the
tuple nowhere. The two sheets have to actually differ, on paper, and the
numbers have to be the sizes those countries print on rather than merely two
different numbers.

The chain is exercised in the order it runs: the stored preference and the
project country go into ``TransmittalService.cover_page_size``, whose answer
goes into ``_build_cover_pdf``, whose bytes are then measured. The session is
stubbed rather than mocked away - it compiles the real statements and routes on
the table they name, so a query rewritten to read the wrong column fails here
instead of quietly answering for the wrong row.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime
from typing import Any

import pypdf
import pytest

from app.core.paper_size import PAPER_SIZES
from app.modules.file_transmittals.models import (
    FileTransmittal,
    FileTransmittalItem,
    FileTransmittalRecipient,
)
from app.modules.file_transmittals.service import TransmittalService, _build_cover_pdf

# Points, and the tolerance a PDF's own rounding of them earns. reportlab
# writes A4's 841.89 as 841.89, so half a point is generous and still far
# tighter than the 50pt that separates A4 from Letter in either dimension.
TOLERANCE = 0.5

A4 = PAPER_SIZES["A4"]
LETTER = PAPER_SIZES["LETTER"]

# Long enough to push a table that is not scaled to its frame off the narrower
# sheet. A file path with a discipline prefix and a revision is the ordinary
# shape of this column, not a stress input.
LONG_NAME = "ARC-BLD-A-DR-2401-Ground floor general arrangement and setting out-Rev-C.pdf"


class _StubResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


class _StubSession:
    """Answers the two lookups ``cover_page_size`` makes, by table name.

    Routing on the compiled statement rather than on call order is deliberate:
    call order is an implementation detail this test has no business pinning,
    while the table a query reads is the thing that would be wrong if someone
    pointed the preference lookup at the wrong row.
    """

    def __init__(self, *, country_code: str | None, paper_size: str | None) -> None:
        self.country_code = country_code
        self.paper_size = paper_size
        self.seen: list[str] = []

    async def execute(self, statement: Any) -> _StubResult:
        text = str(statement)
        self.seen.append(text)
        if "oe_projects_project" in text:
            assert "country_code" in text, f"the country lookup does not read country_code: {text}"
            return _StubResult(self.country_code)
        if "oe_users_user" in text:
            assert "paper_size" in text, f"the preference lookup does not read paper_size: {text}"
            return _StubResult(self.paper_size)
        raise AssertionError(f"cover_page_size read a table this test does not know about: {text}")


def _transmittal(*, with_sender: bool = True) -> FileTransmittal:
    """A sent transmittal with the content the cover sheet lays out."""
    transmittal = FileTransmittal(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        number="TR-2026-0041",
        subject="Issue for construction - ground floor",
        reason_code="for_construction",
        sender_id=uuid.uuid4() if with_sender else None,
        sent_at=datetime(2026, 3, 14, 9, 30, tzinfo=UTC),
        status="sent",
        notes="Superseding revision B. Setting out dimensions confirmed on site.",
    )
    transmittal.items = [
        FileTransmittalItem(
            file_kind="drawing",
            file_id=f"file-{index}",
            file_version_snapshot="C",
            canonical_name_snapshot=LONG_NAME,
            sort_order=index,
        )
        for index in range(3)
    ]
    transmittal.recipients = [
        FileTransmittalRecipient(
            email="site.manager@example.com",
            display_name="Site Manager",
            role="contractor",
        )
    ]
    return transmittal


async def _cover(*, country_code: str | None, paper_size: str | None) -> bytes:
    """Render the cover the way the send path does, end to end."""
    transmittal = _transmittal()
    session = _StubSession(country_code=country_code, paper_size=paper_size)
    service = TransmittalService(session)  # type: ignore[arg-type]
    pagesize = await service.cover_page_size(transmittal)
    assert len(session.seen) == 2, "cover_page_size no longer reads both the project and the sender"
    pdf = _build_cover_pdf(transmittal, pagesize)
    assert pdf is not None, "the cover sheet fell back to text, so there is no page to measure"
    return pdf


def _sheet(pdf_bytes: bytes) -> tuple[float, float]:
    box = pypdf.PdfReader(io.BytesIO(pdf_bytes)).pages[0].mediabox
    return (float(box.width), float(box.height))


def _assert_sheet(actual: tuple[float, float], expected: tuple[float, float], label: str) -> None:
    assert abs(actual[0] - expected[0]) < TOLERANCE and abs(actual[1] - expected[1]) < TOLERANCE, (
        f"{label}: the cover sheet came out {actual[0]:.0f} x {actual[1]:.0f}pt, "
        f"expected {expected[0]:.0f} x {expected[1]:.0f}pt"
    )


# ── The proof ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_two_preferences_produce_two_different_sheets() -> None:
    """The assertion the whole change exists for.

    Not "the resolver returned two tuples" and not "the generator was reached":
    two rendered documents, measured, whose pages are not the same size. Both
    of these rendered 612 x 792 before, because the generator ignored every
    input it had.
    """
    a4 = _sheet(await _cover(country_code="DE", paper_size="A4"))
    letter = _sheet(await _cover(country_code="DE", paper_size="Letter"))
    assert a4 != letter, "both preferences rendered the same sheet, so the preference reaches nothing"
    _assert_sheet(a4, A4, "an explicit A4")
    _assert_sheet(letter, LETTER, "an explicit Letter")


@pytest.mark.asyncio
async def test_an_unset_preference_follows_the_project_country_onto_paper() -> None:
    """``'auto'`` is the default, so this is what almost every real send does."""
    us = _sheet(await _cover(country_code="US", paper_size="auto"))
    de = _sheet(await _cover(country_code="DE", paper_size="auto"))
    assert us != de, "a US project and a German project got the same sheet under 'auto'"
    _assert_sheet(us, LETTER, "an unset preference on a US project")
    _assert_sheet(de, A4, "an unset preference on a German project")


@pytest.mark.asyncio
async def test_the_world_outside_the_letter_countries_is_where_this_used_to_be_wrong() -> None:
    """The defect, stated as the countries that used to get the wrong sheet.

    Every one of these was handed 612 x 792 by a module that has nothing to do
    with the United States. This is the population the change is for, so it is
    asserted as a population rather than as one representative country.
    """
    for country in ("DE", "GB", "FR", "JP", "BR", "IN", "RU", "CN", "ZA", "AU"):
        _assert_sheet(_sheet(await _cover(country_code=country, paper_size="auto")), A4, f"a project in {country}")


@pytest.mark.asyncio
async def test_a_us_project_still_gets_letter_when_nobody_chose() -> None:
    """The half that must not regress. A4 for the US would be this fix breaking
    the one country the old behaviour happened to suit."""
    for country in ("US", "CA", "MX"):
        _assert_sheet(_sheet(await _cover(country_code=country, paper_size="auto")), LETTER, f"a project in {country}")


@pytest.mark.asyncio
async def test_an_explicit_preference_outranks_the_project_country() -> None:
    """A sender who picked A4 while working a US job gets A4."""
    _assert_sheet(_sheet(await _cover(country_code="US", paper_size="A4")), A4, "A4 chosen on a US project")
    _assert_sheet(
        _sheet(await _cover(country_code="DE", paper_size="Legal")), PAPER_SIZES["LEGAL"], "Legal on a DE job"
    )


@pytest.mark.asyncio
async def test_an_unknown_country_renders_what_it_rendered_before_the_country_was_read() -> None:
    """``country_code`` is nullable and NULL means unknown, not neutral, so
    nothing is inferred from it: the sheet is the platform's metric-first
    default rather than a guess about where the project is."""
    _assert_sheet(_sheet(await _cover(country_code=None, paper_size="auto")), A4, "a project with no country")


@pytest.mark.asyncio
async def test_a_lookup_that_fails_still_produces_a_cover_sheet() -> None:
    """The never-break contract the rest of this generator is written on.

    A cover sheet a recipient is waiting for must not be lost because a row
    could not be read, so a failing session degrades to the default sheet
    rather than raising out of the send path.
    """

    class _BrokenSession:
        async def execute(self, statement: Any) -> Any:
            raise RuntimeError("database is away")

    transmittal = _transmittal()
    service = TransmittalService(_BrokenSession())  # type: ignore[arg-type]
    pdf = _build_cover_pdf(transmittal, await service.cover_page_size(transmittal))
    assert pdf is not None
    _assert_sheet(_sheet(pdf), A4, "a cover sheet rendered with no readable preference")
