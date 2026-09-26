"""End-to-end proof that the three new rule sets actually run on a write.

The per-module rule tests next to this file drive ``validation_engine`` directly
and prove the rules are correct and reachable. They cannot prove the services
call them, because every service hook deliberately swallows its own exceptions:
a broken payload builder would produce no findings, log nothing, and leave every
one of those tests green. That is the same failure mode as a rule registered
into a rule set nobody passes - reachable on paper, dormant in practice.

So each test here drives the real service method on a deliberately incomplete
record and asserts the finding reached the caller's observation point:

* ``subcontractors`` - ``update_agreement`` into ``active`` -> ``logger.warning``;
* ``rfq_bidding``    - ``issue_rfq`` -> ``logger.warning``;
* ``submittals``     - ``submit_submittal`` -> the structured state-change line.

If a model attribute is renamed out from under a payload builder these fail;
without them the rename is silent.

The last test in the file covers the other half of the same problem: a rule id
that no longer matches its message key. ``translate`` answers a miss with a
humanised version of the key rather than an error, so a rename degrades the
message silently in every locale at once.
"""

from __future__ import annotations

import json
import logging
import pathlib
import uuid
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.validation.rules import register_builtin_rules
from app.modules.rfq_bidding.service import RFQService
from app.modules.subcontractors.schemas import AgreementUpdate
from app.modules.subcontractors.service import SubcontractorService
from app.modules.submittals.service import SubmittalService
from tests._pg import transactional_session


@pytest.fixture(autouse=True)
def _rules_registered() -> None:
    """Populate the rule registry before every test in this file.

    The app registers the built-in rules from its lifespan (``app/main.py``); a
    test process has no lifespan, and other suites in the same run replace or
    empty the registry deliberately. An unregistered set makes the engine log
    "unimplemented rule set" and hand back a clean report, which is the exact
    false green these tests exist to prevent. Registration is idempotent.
    """
    register_builtin_rules()


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session(disable_fks=True) as s:
        yield s


def _logged_payloads(caplog: pytest.LogCaptureFixture, needle: str) -> list[dict[str, Any]]:
    """Return the dict argument of every captured line whose message matches.

    The services log ``logger.warning("prefix %s", {...})``, so the dict is the
    argument and is read rather than the rendered string. ``logging`` collapses
    a lone Mapping argument onto ``record.args`` itself instead of wrapping it
    in a tuple, so both shapes have to be handled.
    """
    payloads: list[dict[str, Any]] = []
    for record in caplog.records:
        if needle not in record.getMessage():
            continue
        args = record.args
        candidates = [args] if isinstance(args, dict) else list(args or ())
        payloads.extend(arg for arg in candidates if isinstance(arg, dict))
    return payloads


# ── subcontractors ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_activating_a_hollow_agreement_logs_its_rule_ids(
    session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app.modules.subcontractors.models import SubcontractAgreement, Subcontractor

    sub = Subcontractor(legal_name="Acme Trades", prequalification_status="approved")
    session.add(sub)
    await session.flush()
    # No work packages, no value, no currency: three separate rules should fire.
    agreement = SubcontractAgreement(
        subcontractor_id=sub.id,
        project_id=uuid.uuid4(),
        title="Drywall package",
        status="draft",
        currency="",
        total_value=Decimal("0"),
    )
    session.add(agreement)
    await session.flush()

    svc = SubcontractorService(session)
    with caplog.at_level(logging.WARNING):
        await svc.update_agreement(agreement.id, AgreementUpdate(status="active"))

    payloads = _logged_payloads(caplog, "subcontract.agreement_activated_with_findings")
    assert payloads, "activation must log the findings it found"
    reported = set(payloads[0]["errors"]) | set(payloads[0]["warnings"])
    assert "subcontract.agreement_has_scope" in reported
    assert "subcontract.agreement_value_positive" in reported
    assert "subcontract.agreement_currency_set" in reported


@pytest.mark.asyncio
async def test_activating_a_complete_agreement_logs_nothing(
    session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The hook must stay quiet on a clean record, or the log is noise."""
    from app.modules.subcontractors.models import (
        SubcontractAgreement,
        Subcontractor,
        WorkPackage,
    )

    sub = Subcontractor(legal_name="Acme Trades", prequalification_status="approved")
    session.add(sub)
    await session.flush()
    agreement = SubcontractAgreement(
        subcontractor_id=sub.id,
        project_id=uuid.uuid4(),
        title="Drywall package",
        status="draft",
        currency="CAD",
        total_value=Decimal("100000"),
        retention_percent=Decimal("5"),
        start_date=None,
        end_date=None,
    )
    session.add(agreement)
    await session.flush()
    session.add(
        WorkPackage(
            agreement_id=agreement.id,
            name="Level 1 partitions",
            scope="Metal stud and board to architect's drawings",
            planned_value=Decimal("100000"),
        ),
    )
    await session.flush()

    svc = SubcontractorService(session)
    with caplog.at_level(logging.WARNING):
        await svc.update_agreement(agreement.id, AgreementUpdate(status="active"))

    assert _logged_payloads(caplog, "subcontract.agreement_activated_with_findings") == []


@pytest.mark.asyncio
async def test_the_agreement_endpoint_chain_returns_the_same_findings(
    session: AsyncSession,
) -> None:
    """``validate_agreement`` backs the GET endpoint; prove it reports too."""
    from app.modules.subcontractors.models import SubcontractAgreement, Subcontractor

    sub = Subcontractor(legal_name="Acme Trades", prequalification_status="approved")
    session.add(sub)
    await session.flush()
    agreement = SubcontractAgreement(
        subcontractor_id=sub.id,
        project_id=uuid.uuid4(),
        title="Drywall package",
        status="draft",
        currency="",
        total_value=Decimal("0"),
    )
    session.add(agreement)
    await session.flush()

    report = await SubcontractorService(session).validate_agreement(agreement.id)
    failed = {row["rule_id"] for row in report["results"] if not row["passed"]}
    assert "subcontract.agreement_has_scope" in failed
    assert report["counts"]["errors"] > 0


# ── rfq_bidding ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_issuing_a_hollow_rfq_logs_its_rule_ids(
    session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app.modules.rfq_bidding.models import RFQ

    # No scope, no deadline, no recipients, no currency.
    rfq = RFQ(
        project_id=uuid.uuid4(),
        rfq_number="RFQ-001",
        title="Concrete works package",
        status="draft",
        currency_code="",
        issued_to_contacts=[],
    )
    session.add(rfq)
    await session.flush()
    rfq_id = rfq.id
    # See the note in the award test: the service must load the row itself, or
    # ``bids`` is an unpopulated collection on a hand-built instance.
    session.expunge_all()

    svc = RFQService(session)
    with caplog.at_level(logging.WARNING):
        await svc.issue_rfq(rfq_id, actor_id=str(uuid.uuid4()))

    payloads = _logged_payloads(caplog, "rfq.issue_with_findings")
    assert payloads, "issuing must log the findings it found"
    assert payloads[0]["rule_set"] == "rfq_issue"
    reported = set(payloads[0]["errors"]) | set(payloads[0]["warnings"])
    assert "rfq.scope_described" in reported
    assert "rfq.deadline_present" in reported
    assert "rfq.has_recipients" in reported


@pytest.mark.asyncio
async def test_the_rfq_endpoint_chain_reads_bids_without_blowing_up(
    session: AsyncSession,
) -> None:
    """The award payload walks ``rfq.bids``; prove the relationship loads.

    ``_report_rfq_validation`` swallows exceptions, so a ``MissingGreenlet`` on
    the bids relationship would look exactly like a clean RFQ. Asking the award
    set for a finding that can only come from a bid row proves it was read.
    """
    from app.modules.rfq_bidding.models import RFQ, RFQBid

    rfq = RFQ(
        project_id=uuid.uuid4(),
        rfq_number="RFQ-002",
        title="Concrete works package",
        scope_of_work="C30/37 to foundations",
        status="published",
        currency_code="EUR",
        submission_deadline="2026-08-01",
        issued_to_contacts=[str(uuid.uuid4())],
    )
    session.add(rfq)
    await session.flush()
    session.add(
        RFQBid(
            rfq_id=rfq.id,
            bidder_contact_id=str(uuid.uuid4()),
            bid_amount="125000.00",
            currency_code="USD",
        ),
    )
    await session.flush()
    rfq_id = rfq.id
    # Force a real load with its selectin loader. ``session.get`` would
    # otherwise hand back the instance this test just built, whose ``bids``
    # collection was never populated, and the assertion below would fail for
    # the wrong reason. In a request the service is the first thing to touch
    # the row, so this reproduces production rather than working around it.
    session.expunge_all()

    report = await RFQService(session).validate_rfq(rfq_id, stage="award")
    failed = {row["rule_id"] for row in report["results"] if not row["passed"]}
    assert "rfq.bid_currency_matches" in failed, (
        "a currency mismatch is only visible if the bid rows were actually read"
    )


# ── submittals ────────────────────────────────────────────────────────────


class _StubSession:
    async def refresh(self, obj: Any) -> None:
        pass


class _StubSubmittalRepo:
    def __init__(self, row: Any) -> None:
        self.row = row

    async def get_by_id(self, submittal_id: uuid.UUID) -> Any:
        return self.row

    async def update_fields(self, submittal_id: uuid.UUID, **fields: Any) -> None:
        for key, value in fields.items():
            setattr(self.row, key, value)


@pytest.mark.asyncio
async def test_submitting_a_hollow_submittal_logs_its_rule_ids(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app.modules.submittals.models import Submittal

    # No reviewer, no required date, no spec section, no linked scope.
    row = Submittal(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        submittal_number="SUB-001",
        title="Shop drawing - structural steel",
        submittal_type="shop_drawing",
        status="draft",
        current_revision=0,
        linked_boq_item_ids=[],
    )
    service = SubmittalService.__new__(SubmittalService)
    service.session = _StubSession()
    service.repo = _StubSubmittalRepo(row)

    with caplog.at_level(logging.INFO):
        await service.submit_submittal(row.id)

    payloads = _logged_payloads(caplog, "submittal.state_change")
    assert payloads, "submitting must emit the structured state-change line"
    payload = payloads[-1]
    assert payload["to_status"] == "submitted"
    reported = set(payload.get("validation_errors", [])) | set(payload.get("validation_warnings", []))
    assert "submittal.reviewer_assigned" in reported
    assert "submittal.required_date_present" in reported
    assert "submittal.spec_section_present" in reported


@pytest.mark.asyncio
async def test_submitting_a_complete_submittal_adds_no_finding_keys(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A clean submittal must not decorate the state-change line at all."""
    from app.modules.submittals.models import Submittal

    reviewer = uuid.uuid4()
    row = Submittal(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        submittal_number="SUB-002",
        title="Shop drawing - structural steel",
        submittal_type="shop_drawing",
        status="draft",
        current_revision=0,
        spec_section="05 12 00",
        reviewer_id=reviewer,
        approver_id=uuid.uuid4(),
        date_required="2099-01-01",
        linked_boq_item_ids=[str(uuid.uuid4())],
    )
    service = SubmittalService.__new__(SubmittalService)
    service.session = _StubSession()
    service.repo = _StubSubmittalRepo(row)

    with caplog.at_level(logging.INFO):
        await service.submit_submittal(row.id)

    payload = _logged_payloads(caplog, "submittal.state_change")[-1]
    assert "validation_errors" not in payload
    assert "validation_warnings" not in payload


# ── message keys ──────────────────────────────────────────────────────────

_MESSAGE_SECTIONS = {"subcontract", "submittal", "rfq"}
_RULE_SETS = ("subcontract", "submittal", "rfq_issue", "rfq_award")
#: Rules defined here render their findings through ``translate`` and the
#: message files. A module may register rules of its own into the same sets
#: (``rfq_bidding`` registers nine) that build their text in code instead; those
#: are a different mechanism and have no message keys to pin.
_CORE_RULES_MODULE = "app.core.validation.rules"


def test_every_rule_id_resolves_in_all_four_locales() -> None:
    """Pin rule id to message key for all three registers, in de/en/es/ru.

    ``translate`` renders a humanised version of the key when it misses, so a
    rule renamed without its messages does not raise, does not log and does not
    fail any behaviour test - it just starts answering in title-cased English
    everywhere. The rule ids in one of these sets are not uniformly prefixed
    (``subcontract.agreement_value_positive`` next to
    ``subcontract.packages_within_value``), which is exactly the shape that
    invites the mismatch.

    Reads the message files directly rather than asserting on rendered output,
    because a humanised fallback is a plausible-looking English sentence and
    cannot be told apart from a real one by inspection.

    The rule registry is process-global and a rule set is open: whoever else has
    started by now is in it. Registering the built-ins here rather than
    inheriting them, and counting only the rules this file defines, keeps the
    count a claim about the core rule file. Taking the length of the rule set
    instead made the pin depend on run order - 25 alone, 34 once anything had
    called ``register_rfq_validation_rules``.
    """
    from app.core.validation.engine import validation_engine
    from app.core.validation.rules import register_builtin_rules

    register_builtin_rules()

    rule_ids: set[str] = set()
    for rule_set in _RULE_SETS:
        rule_ids |= {
            rule.rule_id
            for rule in validation_engine.registry.get_rules_for_sets([rule_set])
            if type(rule).__module__ == _CORE_RULES_MODULE
        }
    rule_ids = {rid for rid in rule_ids if rid.split(".")[0] in _MESSAGE_SECTIONS}
    # 26 since subcontract.unlinked_contract_twin joined the subcontract set.
    assert len(rule_ids) == 26, f"expected 26 core rules across {_RULE_SETS}, found {len(rule_ids)}"

    base = pathlib.Path(__file__).resolve().parents[2] / "app" / "core" / "validation" / "messages"
    docs = {loc: json.loads((base / f"{loc}.json").read_text(encoding="utf-8")) for loc in ("en", "de", "es", "ru")}

    missing: list[str] = []
    echoed: list[str] = []
    for rule_id in sorted(rule_ids):
        section, suffix = rule_id.split(".", 1)
        for kind in ("fail", "suggestion"):
            values: dict[str, str] = {}
            for locale, doc in docs.items():
                value = doc.get(section, {}).get(suffix, {}).get(kind)
                if value:
                    values[locale] = value
                else:
                    missing.append(f"{locale}:{rule_id}.{kind}")
            if len(values) == len(docs):
                echoed.extend(
                    f"{locale}:{rule_id}.{kind}" for locale in ("de", "es", "ru") if values[locale] == values["en"]
                )

    assert missing == [], f"rule ids with no message: {missing}"
    assert echoed == [], f"untranslated copies of the English string: {echoed}"
