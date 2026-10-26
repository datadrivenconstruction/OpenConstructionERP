# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tender​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ addenda: revisions, compliance, timeline, country rules, rules engine, email.

Pure helpers only; the database paths are covered in tests/pg/test_tender_addenda_pg.py.
"""

from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace

import pytest

from app.core.tender_rules import jurisdictions, rules_for
from app.core.validation.engine import ValidationContext
from app.modules.tendering import addenda as a
from app.modules.tendering.addendum_email import addendum_html, answer_html
from app.modules.tendering.validators import (
    AddendumAcknowledgedAtClosing,
    AddendumNotTooLate,
    BidBondCoversValidity,
    BidPricedCurrentRevision,
    QuestionAnsweredInTime,
)


def _bid(rev: int = 0, rid: str | None = None):
    meta = {"boq_revision_no": rev}
    if rid:
        meta["recipient_id"] = rid
    return SimpleNamespace(id=uuid.uuid4(), metadata_=meta)


def _meta(acks1: list[str], acks2: list[str], rev: int = 1) -> dict:
    return {
        "boq_revision_no": rev,
        "recipients": [{"id": r, "status": "sent"} for r in ("r1", "r2", "r3")],
        "addenda": [
            {
                "id": "a1",
                "revision_no": 1,
                "published_at": "2026-10-01T00:00:00+00:00",
                "acknowledged_by": [{"bidder_id": x} for x in acks1],
            },
            {
                "id": "a2",
                "revision_no": 2,
                "published_at": "2026-10-20T00:00:00+00:00",
                "acknowledged_by": [{"bidder_id": x} for x in acks2],
            },
            {"id": "a3", "revision_no": 3, "published_at": None, "acknowledged_by": []},
        ],
    }


def test_country_rules_are_data_with_neutral_default() -> None:
    assert {"DE", "FR"} <= set(jurisdictions())
    assert rules_for(None).country_code == "DEFAULT"
    assert rules_for("zz").country_code == "DEFAULT"
    de = rules_for("de")
    assert de.addendum_min_days_before_closing == 6 and de.bid_validity_days == 30
    assert rules_for("DE", {"bid_validity_days": 60}).bid_validity_days == 60


def test_compliance_flags_missing_ack_and_old_revision() -> None:
    meta = _meta(["r1", "r2", "r3"], ["r1", "r2"])
    ok, stale, unacked = _bid(1, "r1"), _bid(0, "r2"), _bid(1, "r3")
    out = a.bid_compliance(meta, [ok, stale, unacked])
    assert out[str(ok.id)]["compliant"] is True
    assert out[str(stale.id)]["revision_current"] is False
    assert out[str(unacked.id)]["missing_addenda"] == [2]
    assert out[str(unacked.id)]["compliant"] is False


def test_ack_by_bid_id_counts() -> None:
    bid = _bid(1)
    meta = _meta([str(bid.id)], [str(bid.id)])
    assert a.bid_compliance(meta, [bid])[str(bid.id)]["compliant"] is True


def test_boq_revision_and_scope() -> None:
    meta = {"scope_position_ids": ["p1", "p2"]}
    entry = {"id": "x", "revision_no": 1, "boq_changes": [{"op": "add", "position_id": "p3"}]}
    meta = a.next_boq_revision(meta, entry, "now")
    assert meta["boq_revision_no"] == 1 and entry["boq_revision_no"] == 1
    meta = a.apply_boq_changes_to_scope(
        meta, [{"op": "add", "position_id": "p3"}, {"op": "delete", "position_id": "p1"}]
    )
    assert meta["scope_position_ids"] == ["p2", "p3"]
    assert a.next_boq_revision(meta, {"id": "y"}, "now")["boq_revision_no"] == 2


def test_pending_recipients_only_for_published() -> None:
    meta = _meta(["r1"], [])
    assert a.pending_recipients(meta, meta["addenda"][0]) == ["r2", "r3"]
    assert a.pending_recipients(meta, meta["addenda"][2]) == []


def test_timeline_dates_from_country_rules() -> None:
    meta = {"issued_at": "2026-09-01", **_meta([], [])}
    events = a.timeline(meta, "2026-11-30", rules_for("DE"), date(2026, 10, 26))
    kinds = [e["kind"] for e in events]
    assert kinds[0] == "issued" and kinds[-1] == "closing"
    q = next(e for e in events if e["kind"] == "questions_closed")
    assert q["at"] == "2026-11-20"
    assert events[0]["past"] and not events[-1]["past"]


def _payload(**kw):
    meta = _meta(["r1", "r2", "r3"], ["r1", "r2"])
    q = SimpleNamespace(id=uuid.uuid4(), number=1, answer="", answered_at=None)
    return a.validation_payload(
        meta,
        kw.get("deadline", "2026-10-24"),
        [_bid(0, "r1")],
        [q],
        [{"guarantee_id": "g", "reference": "BB-1", "expiry_date": "2026-11-01"}],
        rules_for("DE"),
        kw.get("today", date(2026, 10, 26)),
    )


@pytest.mark.asyncio
async def test_rules_fire_on_payload() -> None:
    ctx = ValidationContext(data=_payload(), project_id="p")
    ack = await AddendumAcknowledgedAtClosing().validate(ctx)
    assert [r.passed for r in ack] == [True, False]
    assert not (await BidPricedCurrentRevision().validate(ctx))[0].passed
    late = await AddendumNotTooLate().validate(ctx)
    assert late[1].passed is False and str(late[1].severity).lower().endswith("warning")
    assert not (await QuestionAnsweredInTime().validate(ctx))[0].passed
    bond = await BidBondCoversValidity().validate(ctx)
    assert bond[0].passed is False  # validity runs to 2026-11-23


@pytest.mark.asyncio
async def test_ack_rule_silent_before_closing() -> None:
    ctx = ValidationContext(data=_payload(today=date(2026, 10, 1)), project_id="p")
    assert await AddendumAcknowledgedAtClosing().validate(ctx) == []


def test_emails_escape_and_never_name_the_asker() -> None:
    body = addendum_html(
        locale="de",
        company_name="<b>Firm</b>",
        package_name="Shell",
        entry={
            "revision_no": 2,
            "title": "T",
            "new_deadline": "2026-12-01",
            "previous_deadline": "2026-11-24",
            "boq_revision_no": 1,
        },
    )
    assert "<b>Firm</b>" not in body and "2026-12-01" in body
    ans = answer_html(locale="en", company_name="", package_name="Shell", question="Q?", answer="A.")
    assert "Q?" in ans and "A." in ans
