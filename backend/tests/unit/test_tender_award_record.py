# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The award record is assembled from the procedure and names what is missing.

German public procurement asks a contracting authority to keep a written record
of the award procedure while the procedure runs (VOB/A section 20 below the EU
threshold, VgV section 8 above it). Two properties are what make such a record
worth anything, and both are tested here.

*It is contemporaneous.* The record is readable from the first day and says what
it still owes at the stage it stands at, instead of appearing only once an award
exists. What it owes is read from what the procedure shows has happened, not
from the status column: a package may go from draft straight to closed, and a
procedure cancelled before it began does not owe an award reason.

*Its facts are the procedure's own.* Change a bid and the record changes,
because there is no stored copy of the bid to go stale. What is stored is only
what a person had to say, and storing that leaves everything else on the package
exactly as it was.

Pure over stub objects, no database, the same as the scope reader next door.
"""

from __future__ import annotations

import copy
import uuid
from types import SimpleNamespace

import pytest

from app.modules.tendering.award_record import (
    METADATA_KEY,
    REASONING_SECTIONS,
    append_note,
    build_award_record,
    read_notes,
)


class _Bid:
    """The fields the record takes off a bid."""

    def __init__(
        self,
        bid_id: str,
        company_name: str,
        total_amount: str,
        *,
        currency: str = "EUR",
        status: str = "pending",
        submitted_at: str | None = None,
    ) -> None:
        self.id = bid_id
        self.company_name = company_name
        self.total_amount = total_amount
        self.currency = currency
        self.status = status
        self.submitted_at = submitted_at


class _Leveled:
    """The fields the record takes off a levelling summary."""

    def __init__(self, company_name: str, leveled_amount: str, *, imputed_lines: int = 0) -> None:
        self.company_name = company_name
        self.leveled_amount = leveled_amount
        self.imputed_lines = imputed_lines
        self.currency = "EUR"


_DACH_SCOPE = {
    "sections_recorded": True,
    "covers_whole_bill": False,
    "included_position_count": 4,
    "boq_position_count": 12,
    "sections": [{"id": "s-1", "ordinal": "02", "description": "Dachabdichtung", "position_count": 4}],
}


def _sections(record: dict) -> dict[str, dict]:
    return {s["key"]: s for s in record["sections"]}


def _gap_keys(record: dict) -> list[str]:
    return [g["section"] for g in record["gaps"]]


def _fact(section: dict, key: str) -> dict | None:
    for fact in section["facts"]:
        if fact["key"] == key:
            return fact
    return None


def test_a_draft_record_names_the_decisions_it_already_owes() -> None:
    """The first thing an auditor asks is why this procedure type was chosen."""
    record = build_award_record(
        package_name="Dachabdichtung BA 2",
        status="draft",
        metadata={},
        bids=[],
        scope=_DACH_SCOPE,
        budget_total="812400.00",
        currency="EUR",
        boq_name="LV Neubau Halle 3",
    )

    assert record["started"] is False
    assert record["is_complete"] is False
    # Due from the first day, and nothing has answered them.
    assert _gap_keys(record) == ["procedure_type", "procedure_reason"]
    # The stages the procedure has not reached are not gaps, they are simply
    # not due; a draft that reported a missing award reason would be crying
    # wolf on every package in the register.
    sections = _sections(record)
    assert sections["award_reason"]["state"] == "not_due_yet"
    assert sections["award_decision"]["state"] == "not_due_yet"
    assert sections["participants"]["state"] == "not_due_yet"
    assert sections["bids_received"]["state"] == "not_due_yet"


def test_the_record_states_the_subject_and_the_value_from_the_bill() -> None:
    record = build_award_record(
        package_name="Dachabdichtung BA 2",
        status="draft",
        metadata={},
        bids=[],
        project_name="Neubau Halle 3",
        scope=_DACH_SCOPE,
        budget_total="812400.00",
        currency="EUR",
        boq_name="LV Neubau Halle 3",
    )
    sections = _sections(record)

    assert sections["subject"]["state"] == "recorded"
    assert _fact(sections["subject"], "scope_sections")["text"] == "02 Dachabdichtung"
    assert _fact(sections["subject"], "scope_positions")["count"] == 4
    assert _fact(sections["subject"], "bill_positions")["count"] == 12
    # A code the screen can word in the reader's language, never a word itself.
    scope = _fact(sections["subject"], "covers_whole_bill")
    assert scope["state"] == "part_of_bill"
    assert scope["text"] == ""

    value = _fact(sections["estimated_value"], "estimated_value")
    assert value["amount"] == "812400.00"
    assert value["currency"] == "EUR"
    assert sections["estimated_value"]["state"] == "recorded"


def test_a_bill_with_no_prices_leaves_the_estimated_value_as_a_gap() -> None:
    """An unpriced bill cannot state a value, and saying nothing would hide it."""
    record = build_award_record(
        package_name="Dachabdichtung BA 2",
        status="draft",
        metadata={},
        bids=[],
        budget_total="0",
        currency="EUR",
        boq_name="LV Neubau Halle 3",
    )
    assert "estimated_value" in _gap_keys(record)


def test_a_procedure_cancelled_at_draft_is_not_asked_for_an_award_reason() -> None:
    """draft -> closed is a legal transition and means nobody was ever invited.

    Reading due-ness off the status alone would make such a package owe an
    award reason, a bid opening and an invitation list, and the record would
    name four gaps that are not gaps.
    """
    record = build_award_record(
        package_name="Dachabdichtung BA 2",
        status="closed",
        metadata={},
        bids=[],
        budget_total="812400.00",
        currency="EUR",
        boq_name="LV Neubau Halle 3",
    )
    sections = _sections(record)
    assert sections["award_reason"]["state"] == "not_due_yet"
    assert sections["participants"]["state"] == "not_due_yet"
    assert sections["evaluation"]["state"] == "not_due_yet"
    assert _gap_keys(record) == ["procedure_type", "procedure_reason"]


def test_the_invitation_stage_comes_due_from_the_recipients_not_the_status() -> None:
    """A package with somebody on the distribution list has been put out."""
    record = build_award_record(
        package_name="Dachabdichtung BA 2",
        status="draft",
        metadata={
            "recipients": [
                {
                    "company_name": "Bedachungen Kreuzer",
                    "email": "a@example.com",
                    "sent_at": "2026-05-02T09:00:00+00:00",
                },
                {"company_name": "Flachdach Nord", "email": "b@example.com", "sent_at": None},
            ],
            "issued_at": "2026-05-02T09:00:00+00:00",
        },
        bids=[],
        budget_total="812400.00",
        currency="EUR",
    )
    sections = _sections(record)
    assert sections["participants"]["state"] == "recorded"
    assert _fact(sections["participants"], "invited_count")["count"] == 2
    assert _fact(sections["participants"], "issued_at")["at"] == "2026-05-02T09:00:00+00:00"
    # The criteria have to be known before the bidders price, so they come due
    # with the invitation rather than with the award.
    assert sections["evaluation_criteria"]["state"] == "missing"


def test_a_package_put_out_to_nobody_is_a_gap_not_a_silence() -> None:
    record = build_award_record(
        package_name="Dachabdichtung BA 2",
        status="issued",
        metadata={"issued_at": "2026-05-02T09:00:00+00:00"},
        bids=[],
        budget_total="812400.00",
        currency="EUR",
    )
    assert "participants" in _gap_keys(record)


def test_the_record_reads_the_bids_rather_than_a_copy_of_them() -> None:
    """Change a bid and the record changes, because it holds no copy.

    This is the whole reason the record is assembled instead of typed. A
    retyped sum agrees with the procedure on the day it is typed and is free to
    disagree with it forever after.
    """
    bid = _Bid("b-1", "Bedachungen Kreuzer", "798000.00", submitted_at="2026-05-20T11:00:00+00:00")
    kwargs = {
        "package_name": "Dachabdichtung BA 2",
        "status": "collecting",
        "metadata": {"issued_at": "2026-05-02T09:00:00+00:00"},
        "budget_total": "812400.00",
        "currency": "EUR",
    }

    before = build_award_record(bids=[bid], **kwargs)
    assert _fact(_sections(before)["bids_received"], "bid")["amount"] == "798000.00"

    bid.total_amount = "812750.00"
    after = build_award_record(bids=[bid], **kwargs)
    assert _fact(_sections(after)["bids_received"], "bid")["amount"] == "812750.00"


def test_the_evaluation_states_the_levelled_figures() -> None:
    """Bids were compared on the levelled sums, so that is what the record says."""
    record = build_award_record(
        package_name="Dachabdichtung BA 2",
        status="evaluating",
        metadata={"issued_at": "2026-05-02T09:00:00+00:00"},
        bids=[_Bid("b-1", "Bedachungen Kreuzer", "798000.00")],
        leveling=[_Leveled("Bedachungen Kreuzer", "845300.00", imputed_lines=3)],
        excluded_off_currency=1,
        budget_total="812400.00",
        currency="EUR",
    )
    section = _sections(record)["evaluation"]
    assert section["state"] == "recorded"
    assert _fact(section, "leveled_bid")["amount"] == "845300.00"
    assert _fact(section, "leveled_lines_imputed")["count"] == 3
    assert _fact(section, "off_currency_excluded")["count"] == 1


def test_the_ground_for_excluding_a_bid_is_asked_for_once_bids_are_in() -> None:
    """The formal examination is a stage of the procedure whatever it concluded.

    The bids and the status each one carries are shown as the evidence, so the
    person writing the ground is not retyping anything, but the ground itself
    is a judgement and only a person can supply it.
    """
    record = build_award_record(
        package_name="Dachabdichtung BA 2",
        status="evaluating",
        metadata={"issued_at": "2026-05-02T09:00:00+00:00"},
        bids=[
            _Bid("b-1", "Bedachungen Kreuzer", "798000.00"),
            _Bid("b-2", "Flachdach Nord", "0", status="rejected"),
        ],
        budget_total="812400.00",
        currency="EUR",
    )
    section = _sections(record)["exclusions"]
    assert section["source"] == "reasoning"
    assert section["state"] == "missing"
    assert _fact(section, "excluded_count")["count"] == 1
    assert [f["state"] for f in section["facts"] if f["key"] == "bid_status"] == ["pending", "rejected"]


def test_the_award_sections_come_due_with_the_award_stamp() -> None:
    record = build_award_record(
        package_name="Dachabdichtung BA 2",
        status="awarded",
        metadata={
            "issued_at": "2026-05-02T09:00:00+00:00",
            "awarded_at": "2026-06-01T10:00:00+00:00",
            "awarded_bid_id": "b-1",
            "awarded_by": "buyer-7",
        },
        bids=[
            _Bid("b-1", "Bedachungen Kreuzer", "798000.00", status="accepted"),
            _Bid("b-2", "Flachdach Nord", "836000.00", status="rejected"),
        ],
        budget_total="812400.00",
        currency="EUR",
    )
    sections = _sections(record)
    assert sections["award_decision"]["state"] == "recorded"
    assert _fact(sections["award_decision"], "awarded_to")["text"] == "Bedachungen Kreuzer"
    assert _fact(sections["award_decision"], "awarded_sum")["amount"] == "798000.00"
    assert _fact(sections["award_decision"], "awarded_by")["text"] == "buyer-7"
    # The one thing the procedure cannot supply.
    assert "award_reason" in _gap_keys(record)


def test_no_fact_states_a_word_the_screen_would_have_to_print_untranslated() -> None:
    """Facts carry status codes; the wording belongs to whoever displays them.

    A fact that carries "no" or "rejected" reaches a German buyer in English,
    because the screen prints the value the record handed it. Every code the
    assembler can emit therefore has to be one the export knows how to word.
    """
    from app.modules.tendering.pdf_documents import _RECORD_STATE_LABELS

    record = build_award_record(
        package_name="Dachabdichtung BA 2",
        status="awarded",
        metadata={
            "issued_at": "2026-05-02T09:00:00+00:00",
            "awarded_at": "2026-06-01T10:00:00+00:00",
            "awarded_bid_id": "b-1",
            "recipients": [{"company_name": "Bedachungen Kreuzer"}],
        },
        bids=[
            _Bid("b-1", "Bedachungen Kreuzer", "798000.00", status="accepted"),
            _Bid("b-2", "Flachdach Nord", "836000.00", status="rejected"),
        ],
        scope=_DACH_SCOPE,
        boq_name="LV Neubau Halle 3",
        budget_total="812400.00",
        currency="EUR",
    )

    states = {f["state"] for section in record["sections"] for f in section["facts"] if f["state"]}
    assert states, "the fixture has to exercise the facts that carry a state"
    for state in sorted(states):
        assert state == state.lower() and " " not in state, f"{state!r} reads as prose, not as a code"
        assert state in _RECORD_STATE_LABELS, f"the filed document cannot word {state!r}"


def test_building_a_record_leaves_the_package_metadata_untouched() -> None:
    """Reading the record must never dirty the package it describes."""
    metadata = {
        "issued_at": "2026-05-02T09:00:00+00:00",
        "recipients": [{"company_name": "Bedachungen Kreuzer", "email": "a@example.com"}],
        "addenda": [{"id": "a-1", "revision_no": 1, "title": "Anschluss Attika"}],
    }
    before = copy.deepcopy(metadata)

    build_award_record(
        package_name="Dachabdichtung BA 2",
        status="collecting",
        metadata=metadata,
        bids=[_Bid("b-1", "Bedachungen Kreuzer", "798000.00")],
        budget_total="812400.00",
        currency="EUR",
    )

    assert metadata == before


def test_a_package_that_never_opted_in_reads_and_stores_nothing() -> None:
    """A package with nothing to do with German public procurement is unchanged.

    It still has a readable record, because the facts were always there; what
    it does not have is a single byte written to it.
    """
    metadata = {"recipients": [], "some_other_module": {"kept": True}}
    record = build_award_record(
        package_name="Roof works phase 2",
        status="collecting",
        metadata=metadata,
        bids=[_Bid("b-1", "Kreuzer Roofing", "798000.00")],
        budget_total="812400.00",
        currency="GBP",
    )

    assert read_notes(metadata) == []
    assert record["started"] is False
    assert record["started_at"] is None
    assert METADATA_KEY not in metadata


def test_a_statement_supersedes_the_earlier_one_and_leaves_it_readable() -> None:
    """A record that can be quietly rewritten is not a contemporaneous record."""
    first = append_note(
        {},
        note_id="n-1",
        section="procedure_reason",
        text="Beschraenkte Ausschreibung, three suitable firms in the region.",
        recorded_at="2026-05-02T09:00:00+00:00",
        recorded_by="buyer-7",
    )
    second = append_note(
        first,
        note_id="n-2",
        section="procedure_reason",
        text="Beschraenkte Ausschreibung nach VOB/A, value below the threshold.",
        recorded_at="2026-05-04T09:00:00+00:00",
        recorded_by="buyer-7",
    )

    record = build_award_record(
        package_name="Dachabdichtung BA 2",
        status="draft",
        metadata=second,
        bids=[],
        budget_total="812400.00",
        currency="EUR",
    )
    section = _sections(record)["procedure_reason"]
    assert section["state"] == "recorded"
    assert section["statement"].endswith("value below the threshold.")
    assert section["recorded_at"] == "2026-05-04T09:00:00+00:00"
    assert [s["text"] for s in section["superseded"]] == [
        "Beschraenkte Ausschreibung, three suitable firms in the region."
    ]
    assert record["started"] is True
    assert record["started_at"] == "2026-05-02T09:00:00+00:00"


def test_a_chosen_procedure_type_is_carried_beside_its_prose() -> None:
    metadata = append_note(
        {},
        note_id="n-1",
        section="procedure_type",
        text="Beschraenkte Ausschreibung",
        value="restricted",
        recorded_at="2026-05-02T09:00:00+00:00",
    )
    record = build_award_record(
        package_name="Dachabdichtung BA 2",
        status="draft",
        metadata=metadata,
        bids=[],
        budget_total="812400.00",
        currency="EUR",
        boq_name="LV Neubau Halle 3",
    )
    section = _sections(record)["procedure_type"]
    assert section["value"] == "restricted"
    assert section["state"] == "recorded"
    assert _gap_keys(record) == ["procedure_reason"]


def test_writing_a_statement_keeps_every_other_key_on_the_package() -> None:
    metadata = {
        "recipients": [{"company_name": "Bedachungen Kreuzer"}],
        "addenda": [{"id": "a-1"}],
        "issued_at": "2026-05-02T09:00:00+00:00",
    }
    before = copy.deepcopy(metadata)

    written = append_note(
        metadata,
        note_id="n-1",
        section="award_reason",
        text="Levelled sum lowest and capacity confirmed for the programme.",
        recorded_at="2026-06-01T10:00:00+00:00",
    )

    assert metadata == before
    assert written["recipients"] == before["recipients"]
    assert written["addenda"] == before["addenda"]
    assert written["issued_at"] == before["issued_at"]
    assert [n["section"] for n in written[METADATA_KEY]["notes"]] == ["award_reason"]


def test_a_section_the_record_does_not_know_is_refused() -> None:
    """Only the statements a person has to make are accepted.

    Anything else the record says is assembled, and accepting a free-text
    override for it would be the retyped copy the design exists to avoid.
    """
    with pytest.raises(ValueError, match="Unknown award record section"):
        append_note(
            {}, note_id="n-1", section="estimated_value", text="900000", recorded_at="2026-05-02T09:00:00+00:00"
        )


def test_a_stored_note_for_an_unknown_section_is_ignored_rather_than_shown() -> None:
    """Metadata is a free-form store, so the reader trusts nothing it finds."""
    metadata = {METADATA_KEY: {"notes": [{"section": "estimated_value", "text": "900000"}, "not a note"]}}
    assert read_notes(metadata) == []


def test_every_reasoning_section_can_be_written_and_read_back() -> None:
    metadata: dict = {}
    for index, section in enumerate(REASONING_SECTIONS):
        metadata = append_note(
            metadata,
            note_id=f"n-{index}",
            section=section,
            text=f"statement for {section}",
            recorded_at="2026-05-02T09:00:00+00:00",
        )

    record = build_award_record(
        package_name="Dachabdichtung BA 2",
        status="awarded",
        metadata={
            **metadata,
            "issued_at": "2026-05-02T09:00:00+00:00",
            "recipients": [{"company_name": "Bedachungen Kreuzer", "email": "a@example.com"}],
            "awarded_at": "2026-06-01T10:00:00+00:00",
            "awarded_bid_id": "b-1",
        },
        bids=[_Bid("b-1", "Bedachungen Kreuzer", "798000.00", status="accepted")],
        leveling=[_Leveled("Bedachungen Kreuzer", "845300.00")],
        budget_total="812400.00",
        currency="EUR",
        boq_name="LV Neubau Halle 3",
        scope=_DACH_SCOPE,
    )
    sections = _sections(record)
    for section in REASONING_SECTIONS:
        assert sections[section]["state"] == "recorded", section
    assert record["gaps"] == []
    assert record["is_complete"] is True


def test_the_record_exports_at_the_draft_stage_with_its_gaps_printed() -> None:
    """The export cannot wait for the award, so it has to survive empty sections."""
    from app.modules.tendering.pdf_documents import generate_award_record_pdf

    record = build_award_record(
        package_name="Dachabdichtung BA 2",
        status="draft",
        metadata={},
        bids=[],
        budget_total="0",
        currency="EUR",
    )
    record["package_name"] = "Dachabdichtung BA 2"
    record["project_name"] = "Neubau Halle 3"

    pdf = generate_award_record_pdf(record=record, package_ref="ab12cd34")
    assert pdf.startswith(b"%PDF")


def test_the_export_escapes_what_a_bidder_wrote() -> None:
    """A company name is untrusted text, here as much as in the award letter."""
    from app.modules.tendering.pdf_documents import generate_award_record_pdf

    record = build_award_record(
        package_name="Dachabdichtung <b>BA 2</b>",
        status="collecting",
        metadata={"issued_at": "2026-05-02T09:00:00+00:00"},
        bids=[_Bid("b-1", "<para>Kreuzer</para>", "798000.00")],
        budget_total="812400.00",
        currency="EUR",
    )
    record["package_name"] = "Dachabdichtung <b>BA 2</b>"
    record["project_name"] = ""

    pdf = generate_award_record_pdf(record=record, package_ref="ab12cd34")
    assert pdf.startswith(b"%PDF")


# ── The service that feeds the assembler ─────────────────────────────────────
# Still no database: the service reads through ``get_package``,
# ``list_bids_for_package`` and the BOQ service, and all three are stubbed here
# the way the module's own security tests stub them.


class _Position:
    """The fields the scope reader and the value sum take off a bill position."""

    def __init__(
        self,
        pos_id: str,
        *,
        parent: str | None = None,
        ordinal: str = "",
        description: str = "",
        quantity: str = "0",
        unit_rate: str = "0",
        total: str = "0",
    ) -> None:
        self.id = pos_id
        self.parent_id = parent
        self.ordinal = ordinal
        self.description = description
        self.quantity = quantity
        self.unit_rate = unit_rate
        self.total = total
        self.unit = ""


def _service_with(package: SimpleNamespace, *, bids: list | None = None, writes_fail: bool = True):
    """A TenderingService whose only reachable dependencies are stubs."""
    from app.modules.tendering.service import TenderingService

    service = TenderingService.__new__(TenderingService)

    class _Repo:
        async def list_bids_for_package(self, _package_id: object) -> list:
            return list(bids or [])

        async def update_package_fields(self, *_args: object, **_kwargs: object) -> None:
            if writes_fail:
                raise AssertionError("reading the award record wrote to the package")

    async def _get_package(_package_id: object) -> SimpleNamespace:
        return package

    async def _project_name_and_currency(_package: object) -> tuple[str, str]:
        return "Neubau Halle 3", "EUR"

    service.repo = _Repo()
    service.session = SimpleNamespace()
    service.get_package = _get_package
    service._project_name_and_currency = _project_name_and_currency
    return service


def _package(**overrides: object) -> SimpleNamespace:
    base = {
        "id": uuid.UUID("11111111-0000-0000-0000-000000000001"),
        "project_id": uuid.UUID("22222222-0000-0000-0000-000000000002"),
        "boq_id": None,
        "name": "Dachabdichtung BA 2",
        "description": "Flat roof waterproofing, phase 2",
        "status": "draft",
        "deadline": None,
        "metadata_": {},
    }
    base.update(overrides)
    return SimpleNamespace(**base)


async def test_reading_the_record_never_writes_to_the_package() -> None:
    """The whole record is a read. A stamp written here would dirty a package
    that only wanted to be looked at, and the law's document would start editing
    the procedure it describes."""
    package = _package(metadata_={"recipients": [], "addenda": []})
    service = _service_with(package)

    record = await service.award_record(package.id)

    assert record.stage == "draft"
    assert record.started is False
    assert record.project_name == "Neubau Halle 3"
    assert package.metadata_ == {"recipients": [], "addenda": []}


async def test_the_estimated_value_is_summed_off_the_live_bill_in_scope(monkeypatch) -> None:
    """Not off the frozen template the package was created with.

    ``line_item_template`` is a copy taken on creation day and is free to
    disagree with the bill afterwards. It is still the thing that says which
    lines are in scope, so the record narrows by it and then sums the live
    positions, exactly as the comparison and the levelling do. Here the frozen
    copy says 1,999,998, the whole bill says 1,000,000 and the truth is 500,000.
    """
    roof = _Position("p-0", ordinal="02", description="Dachabdichtung")
    priced = [
        _Position("p-1", parent=roof.id, ordinal="02.01", quantity="100", unit_rate="2000", total="200000"),
        _Position("p-2", parent=roof.id, ordinal="02.02", quantity="100", unit_rate="3000", total="300000"),
    ]
    other_trade = _Position("p-3", ordinal="03", description="Ausbau", quantity="1", unit_rate="500000", total="500000")

    class _StubBOQService:
        def __init__(self, _session: object) -> None:
            pass

        async def get_boq_with_positions(self, _boq_id: object) -> SimpleNamespace:
            return SimpleNamespace(name="LV Neubau Halle 3", positions=[roof, *priced, other_trade])

    monkeypatch.setattr("app.modules.boq.service.BOQService", _StubBOQService)

    package = _package(
        boq_id=uuid.UUID("33333333-0000-0000-0000-000000000003"),
        metadata_={
            "line_item_template": [
                {"position_id": "p-1", "total": "999999"},
                {"position_id": "p-2", "total": "999999"},
            ]
        },
    )
    service = _service_with(package)

    record = await service.award_record(package.id)
    sections = {s.key: s for s in record.sections}
    value = next(f for f in sections["estimated_value"].facts if f.key == "estimated_value")

    assert value.amount == "500000"
    assert value.currency == "EUR"
    # And the subject names the trade the package was raised over.
    scope_sections = next(f for f in sections["subject"].facts if f.key == "scope_sections")
    assert scope_sections.text == "02 Dachabdichtung"


async def test_a_bill_that_cannot_be_read_leaves_a_gap_rather_than_an_error(monkeypatch) -> None:
    """A bill deleted since the package was raised is not a reason to refuse."""
    from fastapi import HTTPException

    class _StubBOQService:
        def __init__(self, _session: object) -> None:
            pass

        async def get_boq_with_positions(self, _boq_id: object) -> SimpleNamespace:
            raise HTTPException(status_code=404, detail="BOQ not found")

    monkeypatch.setattr("app.modules.boq.service.BOQService", _StubBOQService)

    package = _package(boq_id=uuid.UUID("33333333-0000-0000-0000-000000000003"))
    service = _service_with(package)

    record = await service.award_record(package.id)
    assert [g.section for g in record.gaps] == ["estimated_value", "procedure_type", "procedure_reason"]
