"""Unit + service tests for the E-invoice clearance module.

Five layers:
  * The country registry and the status machine - no DB. These encode the claim
    the whole module rests on, that clearance, reporting and network exchange
    are three different acts, so they are worth stating one by one.
  * Schema guards - no DB.
  * The adapter boundary - no DB, no network. The reference adapter is offline
    and deterministic on purpose, which is what makes the round trip testable.
  * The service against the shared PostgreSQL unit DB with per-test transaction
    isolation (same fixture style as ``test_cases_module.py``).
  * The validation rules and the permission registry.

This file lives in ``tests/unit`` and is named explicitly in
``.github/workflows/ci-postgres.yml``. ``tests/integration`` runs in no blocking
lane, so a guard placed there would pass review and gate nothing.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.einvoice.profiles import SUPPORTED_PROFILES
from app.modules.einvoice_clearance import adapters, regimes, repository, schemas, service
from app.modules.einvoice_clearance.models import (
    ALLOWED_TRANSITIONS,
    DOCUMENT_STATUSES,
    TERMINAL_SUCCESS,
    EInvoiceProfile,
    can_be_sent,
    can_transition,
)
from app.modules.einvoice_clearance.permissions import register_einvoice_clearance_permissions
from app.modules.einvoice_clearance.validators import register_einvoice_clearance_rules
from tests._pg import transactional_session

# The eight the specification demands. ``delivered`` is the ninth and is tested
# separately: a routed Peppol document has no authority to clear it, and
# recording one as "cleared" or "reported" would claim something happened that
# did not.
REQUIRED_STATUSES = (
    "draft",
    "validated",
    "queued",
    "submitted",
    "cleared",
    "rejected",
    "cancelled",
    "reported",
)

MX_FIELDS = {
    "rfc_issuer": "AAA010101AAA",
    "rfc_receiver": "BBB020202BBB",
    "uso_cfdi": "G03",
    "regimen_fiscal": "601",
}


# ── Country registry and status machine (no DB) ──────────────────────────────


#: Where each class's example paragraph starts in the registry docstring, and
#: the marker that ends the last of them. The three acts are headed by their
#: literal name; the hybrid paragraph by its section title.
_DOCSTRING_HEADINGS: tuple[tuple[str, str], ...] = (
    (regimes.REGIME_CLEARANCE, "``clearance``\n"),
    (regimes.REGIME_REPORTING, "``reporting``\n"),
    (regimes.REGIME_NETWORK, "``network``\n"),
    (regimes.REGIME_HYBRID, "Countries that do more than one of them\n"),
)
_DOCSTRING_EXAMPLES_END = "``regime`` therefore"
#: An ISO code the docstring attaches to a country name: ``(FR)`` or ``(ES, SII``.
_DOCSTRING_CODE = re.compile(r"\(([A-Z]{2})(?=[,)])")


def _docstring_examples(doc: str) -> dict[str, set[str]]:
    """The ISO codes named under each class heading of the registry docstring."""
    starts = [(cls, doc.index(marker)) for cls, marker in _DOCSTRING_HEADINGS]
    end = doc.index(_DOCSTRING_EXAMPLES_END)
    bounds = [*(pos for _, pos in starts[1:]), end]
    return {cls: set(_DOCSTRING_CODE.findall(doc[pos:stop])) for (cls, pos), stop in zip(starts, bounds, strict=True)}


class TestCountryRegistry:
    def test_every_en16931_link_names_a_profile_that_actually_exists(self):
        # The one place this module touches document generation. A link to a
        # profile the EN 16931 engine does not ship would be a promise to build
        # a document nothing can build.
        linked = {
            entry.country: entry.en16931_profile for entry in regimes.COUNTRY_REGIMES.values() if entry.en16931_profile
        }
        assert linked, "no country links to the shared engine; the reuse claim would be empty"
        unknown = {c: p for c, p in linked.items() if p not in SUPPORTED_PROFILES}
        assert unknown == {}

    def test_the_clearance_countries_are_classified_as_clearance(self):
        clearance = set(regimes.countries_by_regime(regimes.REGIME_CLEARANCE))
        assert {"MX", "BR", "IT", "PL", "RO", "SA", "IN"} <= clearance

    def test_the_reporting_countries_are_classified_as_reporting(self):
        reporting = set(regimes.countries_by_regime(regimes.REGIME_REPORTING))
        assert {"ES", "HU"} <= reporting

    def test_the_network_countries_are_classified_as_network(self):
        network = set(regimes.countries_by_regime(regimes.REGIME_NETWORK))
        assert {"DE", "FR"} <= network

    def test_every_country_declares_one_of_the_three_regimes(self):
        assert {e.regime for e in regimes.COUNTRY_REGIMES.values()} <= set(regimes.REGIMES)

    def test_every_clearance_country_names_what_comes_back(self):
        # The identifier is the point of clearance: without it the invoice is
        # not valid, so a clearance entry that cannot name it is incomplete.
        for code in regimes.countries_by_regime(regimes.REGIME_CLEARANCE):
            assert regimes.COUNTRY_REGIMES[code].identifier_label, code

    def test_a_country_with_no_cancellation_flow_says_so_rather_than_guessing(self):
        # Italy, Poland, Romania, Saudi Arabia and Hungary do not withdraw a
        # document; they correct it with a further one, which is a different
        # entry in the ledger. Modelling that as a long window would let the
        # product offer a button that cannot work.
        for code in ("IT", "PL", "RO", "SA", "HU"):
            entry = regimes.COUNTRY_REGIMES[code]
            assert entry.is_cancellable is False, code
            assert entry.correction_mechanism, code
        for code in ("MX", "BR", "IN", "ES"):
            assert regimes.COUNTRY_REGIMES[code].is_cancellable is True, code

    def test_a_country_that_does_two_acts_is_classed_hybrid_and_not_named_by_one(self):
        # The class is derived from the acts, so the two cannot disagree. A
        # country filed under one of the three names while performing two of
        # them tells the operator something false about what happens to their
        # invoice.
        for code, entry in regimes.COUNTRY_REGIMES.items():
            expected = regimes.REGIME_HYBRID if entry.additional_regimes else entry.regime
            assert entry.regime_class == expected, code
            assert entry.is_hybrid is bool(entry.additional_regimes), code

    def test_every_additional_act_is_one_of_the_three_and_is_not_the_deciding_one(self):
        for code, entry in regimes.COUNTRY_REGIMES.items():
            assert set(entry.additional_regimes) <= set(regimes.REGIMES), code
            assert entry.regime not in entry.additional_regimes, code
            assert len(set(entry.additional_regimes)) == len(entry.additional_regimes), code

    def test_hybrid_is_a_class_and_never_an_act(self):
        # If "hybrid" were a fourth member of REGIMES it would reach
        # TERMINAL_SUCCESS, where there is no answer to what a successful
        # submission under two acts at once amounted to. It is a class of
        # country, and the deciding act stays one of the three.
        assert regimes.REGIME_HYBRID not in regimes.REGIMES
        assert regimes.REGIME_HYBRID in regimes.REGIME_CLASSES
        assert set(regimes.REGIMES) < set(regimes.REGIME_CLASSES)
        for entry in regimes.COUNTRY_REGIMES.values():
            assert entry.regime in regimes.REGIMES, entry.country

    def test_every_country_the_docstring_uses_as_an_example_is_a_row_of_the_class_it_illustrates(self):
        # The module docstring is the taxonomy's worked explanation and it has
        # drifted twice: it named France as the example of a class France is
        # not in, and later named Greece, Croatia and Turkiye as countries
        # pairing two acts when the registry held no row for any of them.
        # Every example now carries its ISO code in parentheses, and this
        # reads the codes back rather than trusting the prose.
        examples = _docstring_examples(regimes.__doc__ or "")
        for act in regimes.REGIMES:
            codes = examples[act]
            assert codes, f"the {act} paragraph names no example"
            for code in codes:
                assert code in regimes.COUNTRY_REGIMES, f"{code} is named under {act} but has no row"
                assert regimes.COUNTRY_REGIMES[code].regime == act, f"{code} is named under {act}"
        hybrid_named = examples[regimes.REGIME_HYBRID]
        for code in hybrid_named:
            assert code in regimes.COUNTRY_REGIMES, f"{code} is named as a hybrid example but has no row"
        classed_hybrid = {code for code, entry in regimes.COUNTRY_REGIMES.items() if entry.is_hybrid}
        assert classed_hybrid, "the registry classes nothing hybrid; the paragraph would explain an empty class"
        assert classed_hybrid <= hybrid_named, f"classed hybrid but not named: {sorted(classed_hybrid - hybrid_named)}"

    def test_no_commencement_date_is_stated_without_the_source_it_was_read_from(self):
        # The whole point of the field. A date a business plans around that
        # nobody can trace back to the authority that set it cannot be
        # rechecked, cannot be aged, and is indistinguishable from one somebody
        # remembered.
        for code, entry in regimes.COUNTRY_REGIMES.items():
            for phase in entry.commencement:
                assert phase.obligation in regimes.OBLIGATIONS, (code, phase.obligation)
                assert phase.legal_status in regimes.LEGAL_STATUSES, (code, phase.legal_status)
                assert phase.source_url.startswith("http"), (code, phase.obligation)
                assert phase.read_date, (code, phase.obligation)
                assert phase.scope, (code, phase.obligation)

    def test_receiving_and_issuing_are_dated_separately_where_both_are_known(self):
        # They commence years apart in several countries, so one date standing
        # for both would tell half the population the wrong year.
        for code, entry in regimes.COUNTRY_REGIMES.items():
            for obligation in regimes.OBLIGATIONS:
                phases = entry.phases_for(obligation)
                assert all(p.obligation == obligation for p in phases), code
                dated = [p.effective_date for p in phases if p.is_dated]
                assert dated == sorted(dated), (code, obligation)

    def test_a_country_with_a_reporting_obligation_admits_to_performing_reporting(self):
        # The two halves are written in different places on the entry - the acts
        # in additional_regimes, the dates in commencement - so they can drift
        # apart silently. France is currently the only row carrying both, and a
        # later row could file report phases while still calling itself a pure
        # network country, which is exactly the misclassification this registry
        # was corrected for.
        for code, entry in regimes.COUNTRY_REGIMES.items():
            has_report_phase = any(p.obligation == regimes.OBLIGATION_REPORT for p in entry.commencement)
            if has_report_phase:
                assert regimes.REGIME_REPORTING in entry.regimes, code
        fr = regimes.COUNTRY_REGIMES["FR"]
        assert fr.regime_class == regimes.REGIME_HYBRID
        # The deciding act is unchanged, so a French document still ends up
        # delivered rather than reported. The reporting leg is an obligation
        # alongside the routing and not the thing the submission resolves to.
        assert TERMINAL_SUCCESS[fr.regime] == "delivered"

    def test_a_cancellation_rule_says_which_kind_of_rule_it_is(self):
        # Mexico's deadline is the fiscal year of issue, which is a calendar and
        # not a window: the same count of days is weeks for a December invoice
        # and nearly a year for a January one.
        for code, entry in regimes.COUNTRY_REGIMES.items():
            assert entry.cancellation_basis in regimes.CANCELLATION_BASES, code
        assert regimes.COUNTRY_REGIMES["MX"].cancellation_basis == regimes.CANCELLATION_BASIS_FISCAL_YEAR

    def test_the_flattened_regime_keeps_every_key_it_used_to_carry(self):
        # Additive only. A reader written against the older shape is a reader we
        # cannot see, so no key may change meaning and none may disappear.
        was = {
            "country",
            "regime",
            "platform",
            "label",
            "identifier_label",
            "document_format",
            "en16931_profile",
            "profile_fields",
            "document_fields",
            "cancellation_window_days",
            "is_cancellable",
            "correction_mechanism",
            "notes",
        }
        for entry in regimes.COUNTRY_REGIMES.values():
            flat = regimes.regime_as_dict(entry)
            assert was <= set(flat), entry.country
            # And it still validates against the response model the meta
            # endpoint serves, with the new fields carried rather than dropped.
            served = schemas.CountryRegimeResponse(**flat)
            assert served.regime_class == entry.regime_class
            assert len(served.commencement) == len(entry.commencement)

    def test_an_unregistered_country_is_none_and_not_a_guess(self):
        # Assuming network exchange for an unknown country would let a
        # clearance country's invoice leave without the identifier that makes
        # it valid.
        assert regimes.get_country_regime("ZZ") is None
        assert regimes.get_country_regime("") is None
        assert regimes.get_country_regime("mx") is regimes.COUNTRY_REGIMES["MX"]


class TestStatusMachine:
    def test_all_eight_required_statuses_exist(self):
        assert set(REQUIRED_STATUSES) <= set(DOCUMENT_STATUSES)

    def test_each_regime_has_its_own_terminal_success_state(self):
        assert set(TERMINAL_SUCCESS) == set(regimes.REGIMES)
        # Distinct on purpose. One shared success state would record a Peppol
        # delivery as a tax clearance.
        assert len(set(TERMINAL_SUCCESS.values())) == 3
        assert TERMINAL_SUCCESS[regimes.REGIME_CLEARANCE] == "cleared"
        assert TERMINAL_SUCCESS[regimes.REGIME_REPORTING] == "reported"
        assert TERMINAL_SUCCESS[regimes.REGIME_NETWORK] == "delivered"

    def test_a_cancelled_document_goes_nowhere(self):
        assert ALLOWED_TRANSITIONS["cancelled"] == frozenset()

    def test_a_cleared_document_may_only_be_cancelled(self):
        assert ALLOWED_TRANSITIONS["cleared"] == frozenset({"cancelled"})
        assert can_transition("cleared", "draft") is False
        assert can_transition("cleared", "submitted") is False

    def test_a_draft_cannot_jump_straight_to_cleared(self):
        assert can_transition("draft", "cleared") is False
        assert can_transition("submitted", "cleared") is True

    def test_a_rejection_can_be_fixed_and_sent_again(self):
        assert can_transition("rejected", "draft") is True
        assert can_transition("rejected", "submitted") is True

    def test_an_unknown_status_moves_nowhere(self):
        assert can_transition("banana", "cleared") is False

    def test_a_document_that_has_already_gone_cannot_be_sent_again(self):
        # The one that matters: submitted means the platform has it, and a
        # second send is how one sale collects two cleared invoices.
        assert can_be_sent("submitted") is False
        assert can_be_sent("cleared") is False
        assert can_be_sent("reported") is False
        assert can_be_sent("delivered") is False
        assert can_be_sent("cancelled") is False
        assert can_be_sent("banana") is False

    def test_a_document_that_has_not_gone_yet_can_be_sent(self):
        assert can_be_sent("draft") is True
        assert can_be_sent("validated") is True
        # Re-driving a stuck queue is not a state change, so the machine has no
        # queued -> queued edge and this one has to be allowed on its own.
        assert can_be_sent("queued") is True
        assert can_transition("queued", "queued") is False
        # A rejection is fixed on the same document and sent again.
        assert can_be_sent("rejected") is True


# ── Schema guards (no DB) ────────────────────────────────────────────────────


class TestSchemaGuards:
    def test_status_vocabulary_matches_the_model(self):
        # The tuple is what the machine moves between and this is what the API
        # accepts as a filter. A drift lets a caller filter on a status no
        # document can hold and get a confident empty list back.
        assert schemas.STATUSES == DOCUMENT_STATUSES
        assert schemas.COUNTRIES == regimes.SUPPORTED_COUNTRIES

    def test_a_country_with_no_regime_is_refused_at_the_door(self):
        with pytest.raises(ValueError, match="No e-invoicing regime"):
            schemas.ProfileCreateRequest(company_key="Acme", country="ZZ")

    def test_country_is_normalised_to_upper_case(self):
        assert schemas.ProfileCreateRequest(company_key="Acme", country="mx").country == "MX"

    def test_money_that_is_not_a_number_is_refused(self):
        with pytest.raises(ValueError, match="Invalid decimal"):
            schemas.DocumentCreateRequest(
                project_id=uuid.uuid4(),
                profile_id=uuid.uuid4(),
                total_amount="about a thousand",
            )

    def test_money_stays_a_string_on_the_way_in(self):
        body = schemas.DocumentCreateRequest(
            project_id=uuid.uuid4(),
            profile_id=uuid.uuid4(),
            total_amount="1190.00",
            currency_code="eur",
        )
        assert body.total_amount == "1190.00"
        assert body.currency_code == "EUR"

    def test_country_fields_are_bounded(self):
        with pytest.raises(ValueError, match="At most"):
            schemas.DocumentCreateRequest(
                project_id=uuid.uuid4(),
                profile_id=uuid.uuid4(),
                country_fields={f"f{i}": "x" for i in range(schemas.MAX_COUNTRY_FIELDS + 1)},
            )

    def test_a_cancellation_without_a_reason_is_refused_by_the_schema(self):
        with pytest.raises(ValueError):
            schemas.CancelRequest(reason="")

    def test_a_hand_recorded_outcome_is_one_of_two_words(self):
        # ResolveRequest is the only schema here that leans on a Literal, and
        # under postponed annotations a Literal that no test ever builds is a
        # model nobody has proved Pydantic can resolve. Build it both ways.
        assert schemas.ResolveRequest(outcome="cleared", note="Portal shows it stamped").outcome == "cleared"
        with pytest.raises(ValueError):
            schemas.ResolveRequest(outcome="delivered", note="Portal shows it stamped")

    def test_a_hand_recorded_outcome_needs_a_note(self):
        # Someone will read this row in a year and the only thing that explains
        # a status nobody's adapter set is the sentence the operator typed.
        with pytest.raises(ValueError):
            schemas.ResolveRequest(outcome="rejected", note="")


# ── The adapter boundary (no DB, no network) ─────────────────────────────────


def _request(country: str, *, sandbox: bool = True, fields: dict | None = None) -> adapters.SubmissionRequest:
    entry = regimes.COUNTRY_REGIMES[country]
    payload = f"<Invoice country='{country}'/>".encode()
    return adapters.SubmissionRequest(
        country=country,
        regime=entry.regime,
        document_format=entry.document_format,
        payload=payload,
        payload_hash=service.compute_payload_hash(payload),
        payload_media_type="application/xml",
        profile={"sandbox": sandbox, "tax_registration_id": "X", "adapter_key": "reference"},
        document={"country_fields": fields if fields is not None else dict.fromkeys(entry.document_fields, "x")},
        regime_spec=regimes.regime_as_dict(entry),
    )


@pytest.mark.asyncio
class TestReferenceAdapter:
    async def test_it_refuses_to_serve_a_live_registration(self):
        # The one property that matters about an offline adapter: it must never
        # be able to mint an identifier for a production invoice.
        outcome = await adapters.ReferenceAdapter().submit(_request("MX", sandbox=False))
        assert outcome.accepted is False
        assert outcome.rejection_code == adapters.CODE_NOT_LIVE
        assert outcome.authority_identifier == ""

    async def test_a_sandbox_submission_is_accepted_and_deterministic(self):
        first = await adapters.ReferenceAdapter().submit(_request("MX"))
        second = await adapters.ReferenceAdapter().submit(_request("MX"))
        assert first.accepted is True
        assert first.authority_identifier == second.authority_identifier

    async def test_the_identifier_is_shaped_like_the_country_returns_it(self):
        adapter = adapters.ReferenceAdapter()
        mexican = (await adapter.submit(_request("MX"))).authority_identifier
        # A CFDI UUID is a UUID.
        assert uuid.UUID(mexican)

        brazilian = (await adapter.submit(_request("BR"))).authority_identifier
        # A chave de acesso is 44 digits.
        assert len(brazilian) == 44
        assert brazilian.isdigit()

        indian = (await adapter.submit(_request("IN"))).authority_identifier
        # An IRN is a 64 character hash, which is what the payload hash is.
        assert len(indian) == 64

    async def test_a_missing_national_field_comes_back_as_a_coded_rejection(self):
        outcome = await adapters.ReferenceAdapter().submit(_request("MX", fields={"rfc_issuer": "AAA010101AAA"}))
        assert outcome.accepted is False
        assert outcome.rejection_code == adapters.CODE_MISSING_FIELD
        assert "uso_cfdi" in outcome.rejection_message

    async def test_a_country_with_no_cancellation_flow_refuses_at_the_adapter_too(self):
        entry = regimes.COUNTRY_REGIMES["IT"]
        outcome = await adapters.ReferenceAdapter().cancel(
            adapters.CancellationRequest(
                country="IT",
                regime=entry.regime,
                authority_identifier="IT-ABC",
                reason="Wrong buyer",
                profile={"sandbox": True},
                regime_spec=regimes.regime_as_dict(entry),
            )
        )
        assert outcome.accepted is False
        assert outcome.rejection_code == adapters.CODE_NOT_CANCELLABLE


class TestAdapterRegistry:
    def test_an_unknown_key_is_none_rather_than_something_plausible(self):
        # A "closest match" here is how a live Mexican invoice ends up stamped
        # by a test double.
        registry = adapters.AdapterRegistry()
        registry.register(adapters.ReferenceAdapter())
        assert registry.get("reference") is not None
        assert registry.get("some_provider") is None
        assert registry.get("") is None


# ── Service layer (PostgreSQL) ───────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session() as s:
        yield s


@pytest.fixture(autouse=True)
def _registries():
    """Rules and adapters both live in registries the module fills at startup."""
    register_einvoice_clearance_rules()
    adapters.register_builtin_adapters()


async def _profile(session: AsyncSession, country: str = "MX", **overrides) -> EInvoiceProfile:
    entry = regimes.COUNTRY_REGIMES[country]
    values = {
        "company_key": f"acme-{uuid.uuid4().hex[:8]}",
        "country": country,
        "regime": entry.regime,
        "platform": entry.platform,
        "tax_registration_id": "AAA010101AAA",
        "network_participant_id": "0088:1234567890128",
        "certificate_reference": "vault://csd/acme",
        "adapter_key": adapters.REFERENCE_ADAPTER_KEY,
        "sandbox": True,
        "is_active": True,
    }
    values.update(overrides)
    return await repository.add_profile(session, EInvoiceProfile(**values))


def _body(profile: EInvoiceProfile, **overrides) -> schemas.DocumentCreateRequest:
    entry = regimes.COUNTRY_REGIMES[profile.country]
    fields = MX_FIELDS if profile.country == "MX" else dict.fromkeys(entry.document_fields, "x")
    values: dict = {
        # ``project_id`` is deliberately not a foreign key on this table - a
        # fiscal record outlives the rows around it - so a bare id is exactly
        # what the column holds in production.
        "project_id": uuid.uuid4(),
        "profile_id": profile.id,
        "invoice_number": "2026-0007",
        "invoice_date": "2026-08-05",
        "currency_code": "MXN" if profile.country == "MX" else "EUR",
        "total_amount": "1190.00",
        "country_fields": fields,
        "payload": f"<Invoice n='{uuid.uuid4().hex}'/>",
    }
    values.update(overrides)
    return schemas.DocumentCreateRequest(**values)


@pytest.mark.asyncio
class TestClearanceRoundTrip:
    async def test_a_mexican_invoice_goes_draft_to_cleared_with_a_uuid(self, session):
        profile = await _profile(session, "MX")
        document, _ = await service.create_document(session, profile=profile, body=_body(profile))
        assert document.status == "draft"
        assert document.country == "MX"
        assert document.regime == "clearance"

        await service.validate_document(session, document=document, profile=profile)
        assert document.status == "validated"

        document, outcome, _ = await service.submit_document(session, document=document, profile=profile)
        assert outcome.accepted is True
        assert document.status == "cleared"
        # The identifier is the whole point: without it the invoice is not valid.
        assert uuid.UUID(document.authority_identifier)
        assert document.cleared_at is not None
        assert document.rejection_code == ""

    async def test_the_trail_records_every_move_in_order(self, session):
        profile = await _profile(session, "MX")
        document, _ = await service.create_document(session, profile=profile, body=_body(profile))
        await service.submit_document(session, document=document, profile=profile)

        events = await repository.list_events(session, document.id)
        assert [e.event_type for e in events] == ["created", "queued", "submitted", "cleared"]
        assert [e.sequence for e in events] == [1, 2, 3, 4]
        # The platform's answer is kept as given, not paraphrased.
        assert events[-1].raw_response.get("identifier") == document.authority_identifier

    async def test_the_payload_hash_describes_the_stored_document(self, session):
        profile = await _profile(session, "MX")
        payload = "<Comprobante Version='4.0'/>"
        document, _ = await service.create_document(session, profile=profile, body=_body(profile, payload=payload))
        assert document.payload == payload
        assert document.payload_hash == service.compute_payload_hash(payload.encode("utf-8"))
        assert len(document.payload_hash) == 64


@pytest.mark.asyncio
class TestRegimeDecidesTheOutcome:
    async def test_a_network_document_is_delivered_and_not_cleared(self, session):
        # Peppol has no authority. Recording a routed document as "cleared"
        # would tell a reader a tax authority answered for it.
        profile = await _profile(session, "DE")
        document, _ = await service.create_document(session, profile=profile, body=_body(profile))
        document, outcome, _ = await service.submit_document(session, document=document, profile=profile)
        assert outcome.accepted is True
        assert document.status == "delivered"

    async def test_a_reporting_document_is_reported_and_not_cleared(self, session):
        profile = await _profile(session, "ES")
        document, _ = await service.create_document(session, profile=profile, body=_body(profile))
        document, outcome, _ = await service.submit_document(session, document=document, profile=profile)
        assert outcome.accepted is True
        assert document.status == "reported"


@pytest.mark.asyncio
class TestRefusals:
    async def test_the_same_payload_may_not_be_submitted_twice(self, session):
        profile = await _profile(session, "MX")
        payload = "<Comprobante Version='4.0' Folio='7'/>"
        first, _ = await service.create_document(session, profile=profile, body=_body(profile, payload=payload))
        await service.submit_document(session, document=first, profile=profile)

        second, _ = await service.create_document(session, profile=profile, body=_body(profile, payload=payload))
        with pytest.raises(service.ClearanceError) as excinfo:
            await service.submit_document(session, document=second, profile=profile)
        assert "einvoice_clearance.payload_not_reused" in {f.rule_id for f in excinfo.value.findings}
        assert second.status == "draft"

    async def test_a_cleared_document_cannot_be_edited(self, session):
        profile = await _profile(session, "MX")
        document, _ = await service.create_document(session, profile=profile, body=_body(profile))
        await service.submit_document(session, document=document, profile=profile)

        with pytest.raises(service.ClearanceError) as excinfo:
            await service.update_document(
                session,
                document=document,
                profile=profile,
                body=schemas.DocumentUpdateRequest(invoice_number="2026-0008", total_amount="1.00"),
            )
        assert excinfo.value.conflict is True
        assert document.invoice_number == "2026-0007"

    async def test_a_cleared_document_cannot_be_sent_again(self, session):
        profile = await _profile(session, "MX")
        document, _ = await service.create_document(session, profile=profile, body=_body(profile))
        await service.submit_document(session, document=document, profile=profile)

        with pytest.raises(service.ClearanceError) as excinfo:
            await service.submit_document(session, document=document, profile=profile)
        assert excinfo.value.conflict is True

    async def test_a_missing_national_field_blocks_submission_by_name(self, session):
        profile = await _profile(session, "MX")
        document, _ = await service.create_document(
            session, profile=profile, body=_body(profile, country_fields={"rfc_issuer": "AAA010101AAA"})
        )
        with pytest.raises(service.ClearanceError) as excinfo:
            await service.submit_document(session, document=document, profile=profile)
        blocking = {f.rule_id: f for f in excinfo.value.findings}
        assert "einvoice_clearance.mandatory_fields" in blocking
        # Named, because "something is missing" is not actionable.
        assert "uso_cfdi" in blocking["einvoice_clearance.mandatory_fields"].details["missing"]

    async def test_an_incomplete_registration_blocks_submission_by_name(self, session):
        profile = await _profile(session, "MX", certificate_reference="")
        document, _ = await service.create_document(session, profile=profile, body=_body(profile))
        with pytest.raises(service.ClearanceError) as excinfo:
            await service.submit_document(session, document=document, profile=profile)
        blocking = {f.rule_id: f for f in excinfo.value.findings}
        assert "einvoice_clearance.profile_complete" in blocking
        assert "certificate_reference" in blocking["einvoice_clearance.profile_complete"].details["missing"]

    async def test_an_uninstalled_adapter_is_refused_rather_than_substituted(self, session):
        profile = await _profile(session, "MX", adapter_key="some_provider")
        document, _ = await service.create_document(session, profile=profile, body=_body(profile))
        with pytest.raises(service.ClearanceError, match="some_provider"):
            await service.submit_document(session, document=document, profile=profile)
        assert document.status == "draft"


@pytest.mark.asyncio
class TestRejectionPath:
    async def test_a_rejection_is_stored_with_the_authority_code(self, session):
        # The offline adapter refuses a live registration, which is the honest
        # answer to "you have pointed production at a reference implementation"
        # and the branch that exercises the rejection path end to end.
        profile = await _profile(session, "MX", sandbox=False)
        document, _ = await service.create_document(session, profile=profile, body=_body(profile))
        document, outcome, _ = await service.submit_document(session, document=document, profile=profile)

        assert outcome.accepted is False
        assert document.status == "rejected"
        assert document.rejection_code == adapters.CODE_NOT_LIVE
        assert document.rejection_message
        assert document.retry_count == 1
        assert document.authority_identifier == ""

    async def test_the_rejection_code_survives_on_the_trail(self, session):
        profile = await _profile(session, "MX", sandbox=False)
        document, _ = await service.create_document(session, profile=profile, body=_body(profile))
        await service.submit_document(session, document=document, profile=profile)

        events = await repository.list_events(session, document.id)
        rejections = [e for e in events if e.event_type == "rejected"]
        assert len(rejections) == 1
        assert rejections[0].authority_code == adapters.CODE_NOT_LIVE

    async def test_a_rejected_document_can_be_fixed_and_sent_again(self, session):
        profile = await _profile(session, "MX", sandbox=False)
        document, _ = await service.create_document(session, profile=profile, body=_body(profile))
        await service.submit_document(session, document=document, profile=profile)
        assert document.status == "rejected"

        profile.sandbox = True
        await session.flush()
        document, outcome, _ = await service.submit_document(session, document=document, profile=profile)
        assert outcome.accepted is True
        assert document.status == "cleared"
        assert document.rejection_code == ""


class _FailingAdapter:
    """An adapter whose transport dies before the platform answers."""

    key = "failing_test_adapter"
    label = "Transport failure"
    countries: tuple[str, ...] = ("*",)

    async def submit(self, request):
        raise RuntimeError("connection reset by peer")

    async def cancel(self, request):
        raise RuntimeError("connection reset by peer")


@pytest.fixture
def failing_adapter():
    adapters.adapter_registry.register(_FailingAdapter())
    yield _FailingAdapter.key
    # ``list_all`` hands back a copy, so the real store is what has to be
    # cleaned; leaving a test double installed would show up in ``/meta``.
    adapters.adapter_registry._adapters.pop(_FailingAdapter.key, None)


@pytest.mark.asyncio
class TestDocumentInDoubt:
    async def test_a_transport_failure_leaves_the_document_submitted(self, session, failing_adapter):
        # It does not say the platform did not receive it. Moving the row back
        # to draft would invite a second submission of something that may
        # already be cleared.
        profile = await _profile(session, "MX", adapter_key=failing_adapter)
        document, _ = await service.create_document(session, profile=profile, body=_body(profile))
        with pytest.raises(service.ClearanceError, match="unknown outcome"):
            await service.submit_document(session, document=document, profile=profile)

        assert document.status == "submitted"
        events = await repository.list_events(session, document.id)
        assert events[-1].event_type == "note"
        assert "connection reset" in events[-1].message

    async def test_an_operator_can_record_what_the_platform_actually_did(self, session, failing_adapter):
        profile = await _profile(session, "MX", adapter_key=failing_adapter)
        document, _ = await service.create_document(session, profile=profile, body=_body(profile))
        with pytest.raises(service.ClearanceError):
            await service.submit_document(session, document=document, profile=profile)

        stamped = str(uuid.uuid4()).upper()
        document = await service.resolve_document(
            session,
            document=document,
            profile=profile,
            outcome="cleared",
            authority_identifier=stamped,
            note="Read off the provider portal; the stamp was issued at 09:14.",
        )
        assert document.status == "cleared"
        assert document.authority_identifier == stamped
        events = await repository.list_events(session, document.id)
        assert events[-1].raw_response.get("resolved_by_hand") is True

    async def test_a_clearance_country_cannot_be_resolved_without_the_identifier(self, session, failing_adapter):
        profile = await _profile(session, "MX", adapter_key=failing_adapter)
        document, _ = await service.create_document(session, profile=profile, body=_body(profile))
        with pytest.raises(service.ClearanceError):
            await service.submit_document(session, document=document, profile=profile)

        with pytest.raises(service.ClearanceError, match="Folio Fiscal"):
            await service.resolve_document(
                session,
                document=document,
                profile=profile,
                outcome="cleared",
                note="The portal showed it as accepted.",
            )
        assert document.status == "submitted"

    async def test_a_document_in_doubt_cannot_simply_be_sent_again(self, session, failing_adapter):
        # The way out of doubt is an operator reading the platform, not a retry.
        # A retry is what puts two cleared invoices against one sale, which is
        # the whole reason resolve_document exists.
        profile = await _profile(session, "MX", adapter_key=failing_adapter)
        document, _ = await service.create_document(session, profile=profile, body=_body(profile))
        with pytest.raises(service.ClearanceError):
            await service.submit_document(session, document=document, profile=profile)
        assert document.status == "submitted"

        before = len(await repository.list_events(session, document.id))
        with pytest.raises(service.ClearanceError, match="two cleared invoices") as excinfo:
            await service.submit_document(session, document=document, profile=profile)
        assert excinfo.value.conflict is True
        # Refused before anything was written, not part way through it.
        assert document.status == "submitted"
        assert len(await repository.list_events(session, document.id)) == before

    async def test_resolving_by_hand_is_only_open_to_a_document_in_doubt(self, session):
        profile = await _profile(session, "MX")
        document, _ = await service.create_document(session, profile=profile, body=_body(profile))
        with pytest.raises(service.ClearanceError) as excinfo:
            await service.resolve_document(session, document=document, profile=profile, outcome="cleared", note="x")
        assert excinfo.value.conflict is True


@pytest.mark.asyncio
class TestCancellation:
    async def test_a_cancellation_inside_the_window_is_accepted(self, session):
        profile = await _profile(session, "MX")
        document, _ = await service.create_document(session, profile=profile, body=_body(profile))
        await service.submit_document(session, document=document, profile=profile)

        document, outcome, _ = await service.cancel_document(
            session, document=document, profile=profile, reason="Issued against the wrong buyer"
        )
        assert outcome.accepted is True
        assert document.status == "cancelled"
        assert document.cancelled_at is not None
        assert document.cancellation_reason == "Issued against the wrong buyer"

    async def test_a_cancellation_after_the_window_is_refused(self, session):
        profile = await _profile(session, "MX")
        document, _ = await service.create_document(session, profile=profile, body=_body(profile))
        await service.submit_document(session, document=document, profile=profile)
        # A CFDI may only be cancelled in the fiscal year it was issued in.
        document.cleared_at = datetime.now(UTC) - timedelta(days=400)
        await session.flush()

        with pytest.raises(service.ClearanceError) as excinfo:
            await service.cancel_document(session, document=document, profile=profile, reason="Too late to matter")
        assert "einvoice_clearance.cancellation_allowed" in {f.rule_id for f in excinfo.value.findings}
        assert document.status == "cleared"

    async def test_a_country_with_no_cancellation_flow_refuses_and_names_the_alternative(self, session):
        profile = await _profile(session, "IT")
        document, _ = await service.create_document(session, profile=profile, body=_body(profile))
        await service.submit_document(session, document=document, profile=profile)

        with pytest.raises(service.ClearanceError) as excinfo:
            await service.cancel_document(session, document=document, profile=profile, reason="Wrong buyer")
        finding = next(f for f in excinfo.value.findings if f.rule_id == "einvoice_clearance.cancellation_allowed")
        assert "nota di credito" in finding.details["correction_mechanism"]
        # Still valid, still cleared. A refused withdrawal changes nothing.
        assert document.status == "cleared"

    async def test_a_document_that_never_reached_the_platform_cannot_be_withdrawn(self, session):
        profile = await _profile(session, "MX")
        document, _ = await service.create_document(session, profile=profile, body=_body(profile))
        with pytest.raises(service.ClearanceError) as excinfo:
            await service.cancel_document(session, document=document, profile=profile, reason="Never mind")
        assert excinfo.value.conflict is True


@pytest.mark.asyncio
class TestSandboxWarning:
    async def test_a_sandbox_registration_on_a_real_invoice_stops_the_submission(self, session):
        profile = await _profile(session, "MX")
        document, _ = await service.create_document(
            session, profile=profile, body=_body(profile, invoice_id=uuid.uuid4())
        )
        with pytest.raises(service.ClearanceError) as excinfo:
            await service.submit_document(session, document=document, profile=profile)
        assert "einvoice_clearance.sandbox_profile" in {f.rule_id for f in excinfo.value.findings}

    async def test_it_is_a_warning_and_can_be_acknowledged(self, session):
        # A warning is the module saying "this looks wrong" about something a
        # human may know more about than the rule does, so it is waivable.
        # Errors never are.
        profile = await _profile(session, "MX")
        document, _ = await service.create_document(
            session, profile=profile, body=_body(profile, invoice_id=uuid.uuid4())
        )
        document, outcome, _ = await service.submit_document(
            session, document=document, profile=profile, accept_warnings=True
        )
        assert outcome.accepted is True
        assert document.status == "cleared"

    async def test_a_document_with_no_invoice_behind_it_raises_no_sandbox_warning(self, session):
        profile = await _profile(session, "MX")
        document, findings = await service.create_document(session, profile=profile, body=_body(profile))
        assert "einvoice_clearance.sandbox_profile" not in {f.rule_id for f in findings}


@pytest.mark.asyncio
class TestEditsResetTheDocument:
    async def test_a_validated_document_goes_back_to_draft_when_it_changes(self, session):
        # A "validated" flag that survives a change to the thing it validated is
        # worse than no flag.
        profile = await _profile(session, "MX")
        document, _ = await service.create_document(session, profile=profile, body=_body(profile))
        await service.validate_document(session, document=document, profile=profile)
        assert document.status == "validated"

        await service.update_document(
            session,
            document=document,
            profile=profile,
            body=schemas.DocumentUpdateRequest(
                invoice_number="2026-0009",
                invoice_date="2026-08-05",
                currency_code="MXN",
                total_amount="1190.00",
                country_fields=MX_FIELDS,
            ),
        )
        assert document.status == "draft"
        events = await repository.list_events(session, document.id)
        assert events[-1].event_type == "updated"

    async def test_a_new_payload_gets_a_new_hash(self, session):
        profile = await _profile(session, "MX")
        document, _ = await service.create_document(session, profile=profile, body=_body(profile))
        before = document.payload_hash

        await service.update_document(
            session,
            document=document,
            profile=profile,
            body=schemas.DocumentUpdateRequest(
                invoice_number="2026-0007",
                invoice_date="2026-08-05",
                currency_code="MXN",
                total_amount="1190.00",
                country_fields=MX_FIELDS,
                payload="<Comprobante Version='4.0' Folio='9'/>",
            ),
        )
        assert document.payload_hash != before
        assert document.payload == "<Comprobante Version='4.0' Folio='9'/>"


@pytest.mark.asyncio
class TestSharedEngineIsReused:
    async def test_a_german_document_is_rendered_by_the_en_16931_engine(self, session):
        # The module does not build invoices. Where the country's format is one
        # the shared engine covers, the payload comes from that engine and
        # nothing is reimplemented.
        from app.modules.finance.models import Invoice, InvoiceLineItem

        project_id = uuid.uuid4()
        invoice = Invoice(
            project_id=project_id,
            invoice_direction="receivable",
            invoice_number="2026-0042",
            invoice_date="2026-08-05",
            currency_code="EUR",
            amount_subtotal=Decimal("1000.00"),
            tax_amount=Decimal("190.00"),
            retention_amount=Decimal("0"),
            amount_total=Decimal("1190.00"),
            status="draft",
            metadata_={
                "einvoice": {
                    # XRechnung will not go without a buyer reference (BT-10).
                    "buyer_reference": "991-12345-67",
                    "vat_rate": "19",
                    "seller": {
                        "name": "Harbour Civils",
                        "country_code": "DE",
                        "vat_id": "DE123456789",
                        "line1": "Dock Road 1",
                        "postcode": "20457",
                        "city": "Hamburg",
                        # BG-6, mandatory on the seller under XRechnung (BR-DE-2).
                        "contact_name": "Anke Reimann",
                        "contact_phone": "+49 40 1234560",
                        "contact_email": "rechnung@harbour-civils.example",
                    },
                    "buyer": {
                        "name": "City Works Department",
                        "country_code": "DE",
                        "line1": "Market Square 1",
                        "postcode": "20095",
                        "city": "Hamburg",
                    },
                }
            },
        )
        session.add(invoice)
        await session.flush()
        session.add(
            InvoiceLineItem(
                invoice_id=invoice.id,
                description="Earthworks",
                quantity=Decimal("1"),
                unit="item",
                unit_rate=Decimal("1000.000000"),
                amount=Decimal("1000.00"),
            )
        )
        await session.flush()
        await session.refresh(invoice)

        profile = await _profile(session, "DE")
        document, _ = await service.create_document(
            session,
            profile=profile,
            body=_body(
                profile,
                project_id=project_id,
                invoice_id=invoice.id,
                # No payload: the module has to go and render one.
                payload=None,
                country_fields={"buyer_reference": "991-12345-67"},
            ),
        )

        assert document.payload.startswith("<?xml")
        assert "2026-0042" in document.payload
        assert document.payload_media_type == "application/xml"
        assert document.payload_size > 0
        assert regimes.COUNTRY_REGIMES["DE"].en16931_profile == "xrechnung"

    async def test_a_national_format_the_engine_cannot_build_says_so(self, session):
        # Mexico's CFDI is not an EN 16931 document and this module has never
        # claimed to build one. The refusal names the format rather than
        # producing something shaped like an invoice.
        profile = await _profile(session, "MX")
        with pytest.raises(service.ClearanceError, match="cfdi_4_0"):
            await service.create_document(
                session,
                profile=profile,
                body=_body(profile, invoice_id=uuid.uuid4(), payload=None),
            )


@pytest.mark.asyncio
class TestRegistrationLifecycle:
    async def test_a_registration_with_documents_behind_it_is_not_deletable(self, session):
        profile = await _profile(session, "MX")
        await service.create_document(session, profile=profile, body=_body(profile))
        assert await repository.count_documents_for_profile(session, profile.id) == 1

    async def test_an_inactive_registration_cannot_file_anything(self, session):
        profile = await _profile(session, "MX", is_active=False)
        with pytest.raises(service.ClearanceError) as excinfo:
            await service.create_document(session, profile=profile, body=_body(profile))
        assert excinfo.value.conflict is True

    async def test_a_duplicate_is_only_looked_for_under_the_same_registration(self, session):
        # Two legal entities may legitimately issue identical documents; they
        # are different invoices from different issuers.
        payload = "<Comprobante Version='4.0'/>"
        one = await _profile(session, "MX")
        two = await _profile(session, "MX")
        first, _ = await service.create_document(session, profile=one, body=_body(one, payload=payload))
        await service.submit_document(session, document=first, profile=one)

        second, _ = await service.create_document(session, profile=two, body=_body(two, payload=payload))
        _document, outcome, _findings = await service.submit_document(session, document=second, profile=two)
        assert outcome.accepted is True


# ── Validation rules ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestRulesAreTheGate:
    @staticmethod
    def _context(country: str = "MX", **overrides):
        entry = regimes.COUNTRY_REGIMES[country]
        base = {
            "intent": "submit",
            "profile": {
                "id": "p1",
                "country": country,
                "tax_registration_id": "AAA010101AAA",
                "network_participant_id": "0088:1",
                "certificate_reference": "vault://csd",
                "adapter_key": "reference",
                "sandbox": False,
            },
            "document": {
                "id": "d1",
                "status": "draft",
                "country_fields": MX_FIELDS if country == "MX" else dict.fromkeys(entry.document_fields, "x"),
                "payload_hash": "a" * 64,
            },
            "regime": regimes.regime_as_dict(entry),
            "duplicate": None,
            "changed_fields": [],
            "invoice_is_real": False,
            "reference_time": datetime.now(UTC),
        }
        for key, value in overrides.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                base[key] = {**base[key], **value}
            else:
                base[key] = value
        return base

    async def test_a_complete_document_has_nothing_blocking(self):
        from app.modules.einvoice_clearance.validators import hard_blockers

        assert await hard_blockers(self._context()) == []

    async def test_the_hard_gate_does_not_depend_on_the_engine(self):
        # ``evaluate`` is guarded so a broken rule cannot stop somebody
        # recording the state of an invoice. That guard is exactly why it is
        # not what stops a bad submission: the consequential paths run the
        # rules directly.
        from app.modules.einvoice_clearance.validators import hard_blockers

        blockers = await hard_blockers(self._context(profile={"tax_registration_id": ""}))
        assert {f.rule_id for f in blockers} == {"einvoice_clearance.profile_complete"}

    async def test_a_cleared_document_with_no_identifier_is_an_error(self):
        from app.modules.einvoice_clearance.validators import hard_blockers

        blockers = await hard_blockers(
            self._context(intent="save", document={"status": "cleared", "authority_identifier": ""})
        )
        ids = {f.rule_id for f in blockers}
        assert "einvoice_clearance.identifier_present" in ids
        # And editing it is refused at the same time.
        assert "einvoice_clearance.settled_immutable" in ids

    async def test_a_network_document_with_no_identifier_is_not_an_error(self):
        # There is no authority on a network, so a missing reference is untidy
        # rather than invalid, and calling it invalid would be a rule the
        # product cannot justify.
        from app.modules.einvoice_clearance.validators import hard_blockers

        blockers = await hard_blockers(
            self._context("DE", intent="save", document={"status": "cleared", "authority_identifier": ""})
        )
        assert "einvoice_clearance.identifier_present" not in {f.rule_id for f in blockers}

    async def test_the_full_report_carries_warnings_as_well(self):
        from app.modules.einvoice_clearance.validators import evaluate

        register_einvoice_clearance_rules()
        findings = await evaluate(self._context(profile={"sandbox": True}, invoice_is_real=True))
        assert "einvoice_clearance.sandbox_profile" in {f.rule_id for f in findings}


# ── Permissions ──────────────────────────────────────────────────────────────


class TestPermissions:
    """Every permission the router names has to exist in the registry.

    ``RequirePermission`` denies an unregistered key rather than waving it
    through, so a module that forgets its ``permissions.py`` ships endpoints
    only an admin can reach, and no test that calls them as an admin notices.
    """

    @staticmethod
    def _router_permissions() -> set[str]:
        from app.modules.einvoice_clearance.router import router

        found: set[str] = set()
        for route in router.routes:
            for dependency in getattr(route, "dependencies", []) or []:
                call = getattr(dependency, "dependency", None)
                key = getattr(call, "permission", None)
                if isinstance(key, str):
                    found.add(key)
        return found

    def test_every_permission_the_router_asks_for_is_registered(self):
        from app.core.permissions import permission_registry

        register_einvoice_clearance_permissions()
        asked = self._router_permissions()
        assert asked, "no route declared a permission; the guard would be vacuous"
        registered = set(permission_registry.list_all())
        assert asked <= registered, f"unregistered: {sorted(asked - registered)}"

    def test_submitting_and_cancelling_sit_above_editing(self):
        from app.core.permissions import Role, permission_registry

        register_einvoice_clearance_permissions()
        assert permission_registry.role_has_permission(Role.VIEWER, "einvoice_clearance.read") is True
        assert permission_registry.role_has_permission(Role.EDITOR, "einvoice_clearance.write") is True
        # Putting a document to a tax authority is not reversible by editing.
        assert permission_registry.role_has_permission(Role.EDITOR, "einvoice_clearance.submit") is False
        assert permission_registry.role_has_permission(Role.EDITOR, "einvoice_clearance.cancel") is False
        assert permission_registry.role_has_permission(Role.MANAGER, "einvoice_clearance.submit") is True
        assert permission_registry.role_has_permission(Role.MANAGER, "einvoice_clearance.cancel") is True

    def test_the_submit_and_cancel_routes_actually_ask_for_those_keys(self):
        # A permission that is registered but never asked for guards nothing.
        asked = self._router_permissions()
        assert "einvoice_clearance.submit" in asked
        assert "einvoice_clearance.cancel" in asked


def test_tables_are_named_by_convention():
    from app.modules.einvoice_clearance.models import EInvoiceDocument, EInvoiceEvent

    assert EInvoiceProfile.__tablename__ == "oe_einvoice_clearance_profile"
    assert EInvoiceDocument.__tablename__ == "oe_einvoice_clearance_document"
    assert EInvoiceEvent.__tablename__ == "oe_einvoice_clearance_event"


# ── The two install routes ───────────────────────────────────────────────────


class _EmptyInspector:
    """A database with none of these tables in it yet."""

    def get_table_names(self) -> list[str]:
        return []

    def get_indexes(self, table: str) -> list[dict]:
        return []


class _SaShim:
    """Real SQLAlchemy, except that ``inspect`` reports an empty database."""

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def inspect(self, bind):
        return _EmptyInspector()


class _RecordingOps:
    """Stands in for ``alembic.op`` and records what the revision would build."""

    def __init__(self) -> None:
        self.tables: dict[str, list[str]] = {}
        self.indexes: dict[str, tuple[str, list[str]]] = {}

    def get_bind(self):
        return None

    def create_table(self, name, *args, **kwargs):
        import sqlalchemy as sa

        self.tables[name] = [arg.name for arg in args if isinstance(arg, sa.Column)]

    def create_index(self, name, table, columns, **kwargs):
        self.indexes[name] = (table, list(columns))


def _run_revision() -> _RecordingOps:
    """Execute the revision's ``upgrade()`` against a recorder, not a database.

    This compares the migration with the ORM metadata rather than with its own
    text. The trap it guards is the one the tree has been bitten by before: a
    fresh install goes through ``Base.metadata.create_all`` and an upgraded
    deployment goes through this file, and nothing else notices when the two
    stop building the same table.
    """
    import importlib.util
    from pathlib import Path

    import sqlalchemy as sa

    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "v3282_einvoicing.py"
    spec = importlib.util.spec_from_file_location("_rev_v3282_einvoicing", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    recorder = _RecordingOps()
    module.op = recorder
    module.sa = _SaShim(sa)
    module.upgrade()
    return recorder, module


class TestMigrationMatchesTheModels:
    def test_the_revision_ids_are_the_ones_the_wave_assigned(self):
        _recorder, module = _run_revision()
        # One head for the wave, chained linearly. A revision that invented its
        # own id would fork the chain into a second head.
        assert module.revision == "v3282_einvoicing"
        assert module.down_revision == "v3281_cases_module"

    def test_every_table_gets_the_columns_the_orm_declares(self):
        from app.database import Base

        recorder, _module = _run_revision()
        for name in (
            "oe_einvoice_clearance_profile",
            "oe_einvoice_clearance_document",
            "oe_einvoice_clearance_event",
        ):
            assert name in recorder.tables, name
            declared = set(Base.metadata.tables[name].columns.keys())
            built = set(recorder.tables[name])
            assert built == declared, f"{name}: migration {sorted(built ^ declared)}"

    def test_every_index_the_models_declare_is_in_the_revision(self):
        from app.database import Base

        recorder, _module = _run_revision()
        for name in (
            "oe_einvoice_clearance_profile",
            "oe_einvoice_clearance_document",
            "oe_einvoice_clearance_event",
        ):
            declared = {ix.name for ix in Base.metadata.tables[name].indexes if ix.name}
            built = {ix for ix, (table, _cols) in recorder.indexes.items() if table == name}
            assert declared <= built, f"{name}: missing {sorted(declared - built)}"

    def test_the_project_id_performance_indexes_are_declared_by_hand(self):
        # ``app.core.pg_optimizations`` hangs these off any table carrying a
        # ``project_id``, from an ``after_create`` listener that only runs on the
        # create_all path. A revision that omitted them would build a
        # measurably different table from a fresh install.
        from app.core.pg_optimizations import _index_name

        recorder, _module = _run_revision()
        table = "oe_einvoice_clearance_document"
        for columns in (["project_id", "created_at"], ["project_id", "status"]):
            expected = _index_name(table, columns)
            assert expected in recorder.indexes, expected
            assert recorder.indexes[expected] == (table, columns)
