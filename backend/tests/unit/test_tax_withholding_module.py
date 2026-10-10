"""Unit + service tests for the Tax Withholding module.

Four layers:
  * Arithmetic and band resolution - no DB. This is the layer that decides how
    much money leaves the business, so it is tested as plain functions over
    plain values.
  * Service and repository against the shared PostgreSQL unit DB with per-test
    transaction isolation (same fixture style as ``test_cases_module.py``).
  * Validation rules, which gate a deduction leaving draft and a
    reverse-charge determination being applied.
  * Permissions, including the router walk that catches a key nothing
    registered.

The statutory tax lines of a payment document follow the same four layers
further down. Their rate rows are synthetic and injected, so none of those
tests depends on a shipped rate.

This file lives in ``tests/unit`` and needs a named step in
``.github/workflows/ci-postgres.yml``. ``tests/integration`` runs in no
blocking lane, so a guard placed there would pass review and gate nothing.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy import UniqueConstraint, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.payment_taxes import Choice, RateRow, compute_payment_taxes
from app.modules.projects.models import Project
from app.modules.tax_withholding import repository, schemas, service, source_owners
from app.modules.tax_withholding.data import REVERSE_CHARGE_RULES, WITHHOLDING_REGIMES
from app.modules.tax_withholding.models import (
    STATUTORY_LINE_KINDS,
    PartyTaxStatus,
    ReverseChargeDetermination,
    StatutoryTaxCalc,
    StatutoryTaxLine,
    WithholdingDeduction,
    WithholdingRegime,
)
from app.modules.tax_withholding.permissions import register_tax_withholding_permissions
from app.modules.tax_withholding.validators import (
    blocking_findings,
    evaluate_record,
    register_tax_withholding_rules,
)
from app.modules.users.models import User
from tests._pg import transactional_session

TODAY = date(2026, 8, 5)


def _uk_regime(**overrides) -> WithholdingRegime:
    """A UK-CIS-shaped scheme: deducts on labour, three bands, two verified.

    Every field the arithmetic reads is set explicitly. Column defaults are
    applied at flush time, so an unflushed instance carries ``None`` for
    anything left out - and ``None`` for ``materials_excluded`` would silently
    leave the materials in the base, which is the exact failure under test.
    """
    values = {
        "country_code": "GB",
        "scheme_code": "UK_CIS",
        "scheme_name": "Construction Industry Scheme",
        "currency_code": "GBP",
        "default_band_code": "HIGHER",
        "materials_excluded": True,
        "vat_excluded": True,
        "verification_validity_months": 36,
        "threshold_amount": None,
        "is_active": True,
        "bands": [
            {"code": "GROSS", "label": "Gross payment status", "rate_pct": "0", "requires_verification": True},
            {"code": "STANDARD", "label": "Registered", "rate_pct": "20", "requires_verification": True},
            {"code": "HIGHER", "label": "Unverified", "rate_pct": "30", "requires_verification": False},
        ],
    }
    values.update(overrides)
    return WithholdingRegime(**values)


def _de_regime(**overrides) -> WithholdingRegime:
    """A Bauabzugsteuer-shaped scheme: deducts on the whole consideration."""
    values = {
        "country_code": "DE",
        "scheme_code": "DE_BAUABZUGSTEUER",
        "scheme_name": "Bauabzugsteuer",
        "currency_code": "EUR",
        "default_band_code": "STANDARD",
        "materials_excluded": False,
        "vat_excluded": False,
        "verification_validity_months": 36,
        "threshold_amount": Decimal("5000.00"),
        "is_active": True,
        "bands": [
            {"code": "EXEMPT", "label": "Certificate held", "rate_pct": "0", "requires_verification": True},
            {"code": "STANDARD", "label": "No certificate", "rate_pct": "15", "requires_verification": False},
        ],
    }
    values.update(overrides)
    return WithholdingRegime(**values)


def _standing(**overrides) -> PartyTaxStatus:
    values = {
        "party_id": uuid.uuid4(),
        "party_type": "subcontractor",
        "party_name": "Groundworks contractor",
        "regime_id": uuid.uuid4(),
        "band_code": "STANDARD",
        "verification_reference": "V1234567890",
        "valid_from": date(2026, 1, 1),
        "valid_to": date(2026, 12, 31),
        "status": "active",
    }
    values.update(overrides)
    return PartyTaxStatus(**values)


# ── The arithmetic (no DB) ───────────────────────────────────────────────────


class TestTaxableBase:
    """The base is the gross less what the scheme takes out of it, and no more."""

    def test_materials_leave_the_base_where_the_scheme_excludes_them(self):
        base = service.compute_taxable_base(
            Decimal("10000.00"),
            Decimal("2500.00"),
            Decimal("0"),
            materials_excluded=True,
            vat_excluded=True,
        )
        assert base == Decimal("7500.00")

    def test_materials_stay_in_where_the_scheme_does_not_exclude_them(self):
        # Section 48 EStG deducts from the whole consideration. A module that
        # hardcoded the UK rule would under-withhold on every German payment.
        base = service.compute_taxable_base(
            Decimal("10000.00"),
            Decimal("2500.00"),
            Decimal("1900.00"),
            materials_excluded=False,
            vat_excluded=False,
        )
        assert base == Decimal("10000.00")

    def test_vat_leaves_the_base_where_the_scheme_excludes_it(self):
        base = service.compute_taxable_base(
            Decimal("12000.00"),
            Decimal("0"),
            Decimal("2000.00"),
            materials_excluded=True,
            vat_excluded=True,
        )
        assert base == Decimal("10000.00")

    def test_the_base_never_goes_negative(self):
        # Materials booked above the gross is a data error; a negative base
        # would turn a deduction into a payment to the subcontractor.
        base = service.compute_taxable_base(
            Decimal("100.00"),
            Decimal("500.00"),
            Decimal("0"),
            materials_excluded=True,
            vat_excluded=True,
        )
        assert base == Decimal("0.00")

    def test_leaving_materials_in_over_withholds_by_the_rate_on_them(self):
        # The whole point of the module, stated as a number: 20 percent of
        # 2500 of materials is 500 taken from the subcontractor every month
        # that nobody notices.
        correct = service.compute_tax_withheld(Decimal("7500.00"), Decimal("20"))
        wrong = service.compute_tax_withheld(Decimal("10000.00"), Decimal("20"))
        assert correct == Decimal("1500.00")
        assert wrong - correct == Decimal("500.00")


class TestWithheldRounding:
    def test_rounds_half_away_from_zero_at_two_places(self):
        assert service.compute_tax_withheld(Decimal("333.33"), Decimal("20")) == Decimal("66.67")

    def test_a_zero_rate_withholds_nothing(self):
        assert service.compute_tax_withheld(Decimal("10000.00"), Decimal("0")) == Decimal("0")

    def test_a_zero_base_withholds_nothing(self):
        assert service.compute_tax_withheld(Decimal("0"), Decimal("30")) == Decimal("0")


class TestVerificationIsCurrent:
    def test_an_unexpired_reference_holds(self):
        assert service.verification_is_current(_standing(), TODAY) is True

    def test_an_open_ended_window_holds(self):
        assert service.verification_is_current(_standing(valid_to=None), TODAY) is True

    def test_an_expired_window_does_not(self):
        assert service.verification_is_current(_standing(valid_to=date(2026, 7, 31)), TODAY) is False

    def test_a_window_that_has_not_started_does_not(self):
        assert service.verification_is_current(_standing(valid_from=date(2026, 9, 1)), TODAY) is False

    def test_a_revoked_standing_does_not(self):
        assert service.verification_is_current(_standing(status="revoked"), TODAY) is False

    def test_a_standing_with_no_reference_does_not(self):
        # Marked active with nothing from the authority behind it is somebody's
        # intention, not a verification.
        assert service.verification_is_current(_standing(verification_reference=""), TODAY) is False

    def test_no_standing_at_all_does_not(self):
        assert service.verification_is_current(None, TODAY) is False


class TestBandResolution:
    def test_a_live_verification_keeps_the_reduced_band(self):
        decision = service.resolve_band(_uk_regime(), party_status=_standing(), as_of=TODAY)
        assert decision.band_code == "STANDARD"
        assert decision.rate_pct == Decimal("20")
        assert decision.downgraded_from == ""

    def test_an_expired_verification_moves_the_party_to_the_higher_band(self):
        decision = service.resolve_band(
            _uk_regime(),
            party_status=_standing(valid_to=date(2026, 6, 30)),
            as_of=TODAY,
        )
        assert decision.band_code == "HIGHER"
        assert decision.rate_pct == Decimal("30")
        assert decision.downgraded_from == "STANDARD"
        assert decision.reasons, "a downgrade that says nothing is a surprise, not a decision"

    def test_no_recorded_standing_at_all_moves_the_party_to_the_higher_band(self):
        decision = service.resolve_band(_uk_regime(), requested_band="GROSS", as_of=TODAY)
        assert decision.band_code == "HIGHER"
        assert decision.downgraded_from == "GROSS"

    def test_the_higher_band_needs_no_verification(self):
        decision = service.resolve_band(_uk_regime(), requested_band="HIGHER", as_of=TODAY)
        assert decision.band_code == "HIGHER"
        assert decision.downgraded_from == ""
        assert decision.reasons == []

    def test_an_unknown_band_falls_back_to_the_scheme_default(self):
        decision = service.resolve_band(_uk_regime(), requested_band="NOT_A_BAND", as_of=TODAY)
        assert decision.band_code == "HIGHER"
        assert decision.reasons

    def test_an_explicit_band_outranks_the_standing(self):
        decision = service.resolve_band(
            _uk_regime(),
            requested_band="GROSS",
            party_status=_standing(band_code="STANDARD"),
            as_of=TODAY,
        )
        assert decision.band_code == "GROSS"
        assert decision.rate_pct == Decimal("0")


class TestComputeDeduction:
    def test_a_uk_payment_end_to_end(self):
        figures = service.compute_deduction(
            _uk_regime(),
            gross_amount=Decimal("10000.00"),
            currency_code="GBP",
            qualifying_materials=Decimal("2500.00"),
            party_status=_standing(),
            as_of=TODAY,
        )
        assert figures.band_code == "STANDARD"
        assert figures.taxable_base == Decimal("7500.00")
        assert figures.tax_withheld == Decimal("1500.00")
        assert figures.net_payable == Decimal("8500.00")

    def test_the_same_payment_with_a_lapsed_certificate(self):
        figures = service.compute_deduction(
            _uk_regime(),
            gross_amount=Decimal("10000.00"),
            currency_code="GBP",
            qualifying_materials=Decimal("2500.00"),
            party_status=_standing(valid_to=date(2026, 6, 30)),
            as_of=TODAY,
        )
        assert figures.band_code == "HIGHER"
        assert figures.tax_withheld == Decimal("2250.00")
        assert figures.downgraded_from == "STANDARD"

    def test_a_german_payment_keeps_materials_and_vat_in_the_base(self):
        figures = service.compute_deduction(
            _de_regime(),
            gross_amount=Decimal("20000.00"),
            currency_code="EUR",
            qualifying_materials=Decimal("8000.00"),
            vat_amount=Decimal("3192.00"),
            as_of=TODAY,
        )
        assert figures.band_code == "STANDARD"
        assert figures.taxable_base == Decimal("20000.00")
        assert figures.tax_withheld == Decimal("3000.00")

    def test_a_payment_under_the_exemption_limit_is_flagged_not_zeroed(self):
        # The limit is an annual figure per payee, and one payment cannot see
        # the year. Reporting the possibility is honest; zeroing it is not.
        figures = service.compute_deduction(
            _de_regime(), gross_amount=Decimal("4000.00"), currency_code="EUR", as_of=TODAY
        )
        assert figures.below_threshold is True
        assert figures.tax_withheld == Decimal("600.00")
        assert any("exemption limit" in reason for reason in figures.reasons)

    def test_the_limit_is_not_applied_to_a_payment_in_another_currency(self):
        # The scheme's limit is 5000 EUR. Holding 4000 USD up against it
        # compares two different units and answers with whichever way the rate
        # happened to fall that morning.
        figures = service.compute_deduction(
            _de_regime(), gross_amount=Decimal("4000.00"), currency_code="USD", as_of=TODAY
        )
        assert figures.below_threshold is False
        # Not applying it silently would be its own defect: the payment may
        # well be under the limit once converted, and the reader has to be told
        # that the question was left open rather than answered no.
        assert any("has not been applied" in reason for reason in figures.reasons)
        assert any("5000.00 EUR" in reason and "USD" in reason for reason in figures.reasons)
        # The deduction itself is unaffected either way - the flag never was a
        # rate change.
        assert figures.tax_withheld == Decimal("600.00")

    def test_currency_is_matched_case_and_space_insensitively(self):
        figures = service.compute_deduction(
            _de_regime(), gross_amount=Decimal("4000.00"), currency_code=" eur ", as_of=TODAY
        )
        assert figures.below_threshold is True

    def test_a_scheme_with_no_limit_says_nothing_about_currency(self):
        # UK CIS has no exemption limit, so a payment in any currency should
        # not collect a note about a limit that does not exist.
        figures = service.compute_deduction(
            _uk_regime(),
            gross_amount=Decimal("100.00"),
            currency_code="USD",
            party_status=_standing(),
            as_of=TODAY,
        )
        assert figures.below_threshold is False
        assert not any("exemption limit" in reason for reason in figures.reasons)


class TestShippedData:
    def test_every_shipped_scheme_names_a_band_it_actually_defines(self):
        for regime in WITHHOLDING_REGIMES:
            codes = {band["code"] for band in regime["bands"]}
            assert regime["default_band_code"] in codes, regime["scheme_code"]

    def test_every_shipped_default_band_is_the_highest_rate(self):
        # An unverified party is deducted at the punitive rate. A default that
        # was not the top of the table would quietly under-withhold.
        for regime in WITHHOLDING_REGIMES:
            rates = {band["code"]: Decimal(str(band["rate_pct"])) for band in regime["bands"]}
            assert rates[regime["default_band_code"]] == max(rates.values()), regime["scheme_code"]

    def test_every_shipped_scheme_names_its_currency_and_statute(self):
        for regime in WITHHOLDING_REGIMES:
            assert len(regime["currency_code"]) == 3, regime["scheme_code"]
            assert regime["legal_reference"], regime["scheme_code"]

    def test_every_reverse_charge_rule_carries_wording_to_print(self):
        # A rule with no wording is a rule that cannot be complied with: the
        # wording on the invoice is the whole obligation.
        for rule in REVERSE_CHARGE_RULES:
            assert rule["invoice_wording"].strip(), rule["rule_code"]
            assert rule["legal_reference"].strip(), rule["rule_code"]


# ── Service and repository (PostgreSQL) ──────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session() as s:
        yield s


async def _user(session: AsyncSession, email: str) -> User:
    user = User(email=email, hashed_password="x", full_name=email.split("@")[0])
    session.add(user)
    await session.flush()
    return user


async def _project(session: AsyncSession, owner: User, name: str = "Test project") -> Project:
    project = Project(name=name, owner_id=owner.id)
    session.add(project)
    await session.flush()
    return project


async def _stored_regime(session: AsyncSession, **overrides) -> WithholdingRegime:
    regime = _uk_regime(**overrides)
    return await repository.add_regime(session, regime)


@pytest.mark.asyncio
class TestSeeding:
    async def test_seeding_installs_every_shipped_scheme(self, session):
        created, existing, codes = await service.seed_regimes(session)
        assert created == len(WITHHOLDING_REGIMES)
        assert existing == 0
        assert len(codes) == len(WITHHOLDING_REGIMES)
        assert {r.scheme_code for r in await repository.list_regimes(session)} == set(codes)

    async def test_seeding_twice_does_not_duplicate(self, session):
        await service.seed_regimes(session)
        created, existing, _ = await service.seed_regimes(session)
        assert created == 0
        assert existing == len(WITHHOLDING_REGIMES)

    async def test_seeding_does_not_overwrite_an_edited_rate(self, session):
        # An operator who changed a rate did so for a reason. An upgrade
        # restoring the shipped figure would change what the next return says.
        await service.seed_regimes(session)
        stored = await repository.get_regime_by_scheme(session, country_code="GB", scheme_code="UK_CIS")
        assert stored is not None
        stored.bands = [{"code": "HIGHER", "label": "Local ruling", "rate_pct": "25"}]
        await session.flush()

        await service.seed_regimes(session)
        again = await repository.get_regime_by_scheme(session, country_code="GB", scheme_code="UK_CIS")
        assert again is not None
        assert again.bands == [{"code": "HIGHER", "label": "Local ruling", "rate_pct": "25"}]


@pytest.mark.asyncio
class TestPartyStandings:
    async def test_the_standing_covering_a_date_is_the_one_returned(self, session):
        regime = await _stored_regime(session)
        party = uuid.uuid4()
        await repository.add_party_status(
            session,
            _standing(
                party_id=party,
                regime_id=regime.id,
                valid_from=date(2025, 1, 1),
                valid_to=date(2025, 12, 31),
                verification_reference="OLD",
            ),
        )
        await repository.add_party_status(
            session,
            _standing(
                party_id=party,
                regime_id=regime.id,
                valid_from=date(2026, 1, 1),
                valid_to=date(2026, 12, 31),
                verification_reference="CURRENT",
            ),
        )

        found = await repository.current_party_status(session, party_id=party, regime_id=regime.id, on_date=TODAY)
        assert found is not None
        assert found.verification_reference == "CURRENT"

    async def test_the_same_standing_holds_on_one_date_and_not_on_another(self, session):
        # The lookup is by date, not by a stored flag. The same row backs a
        # reduced rate for a payment inside its window and does not back one for
        # a payment after it, which is exactly the drop nobody is told about.
        regime = await _stored_regime(session)
        party = uuid.uuid4()
        await repository.add_party_status(
            session,
            _standing(
                party_id=party,
                regime_id=regime.id,
                valid_from=date(2026, 1, 1),
                valid_to=date(2026, 6, 30),
            ),
        )
        inside = date(2026, 3, 1)
        found = await repository.current_party_status(session, party_id=party, regime_id=regime.id, on_date=inside)
        assert found is not None
        assert service.verification_is_current(found, inside) is True
        assert service.verification_is_current(found, TODAY) is False
        # And after the window there is simply no standing to find.
        assert (
            await repository.current_party_status(session, party_id=party, regime_id=regime.id, on_date=TODAY) is None
        )

    async def test_a_standing_marked_expired_does_not_back_a_rate_inside_its_own_window(self, session):
        # Somebody wrote "expired" on the record. That is a statement about the
        # certificate and it outranks the dates typed beside it.
        regime = await _stored_regime(session)
        party = uuid.uuid4()
        await repository.add_party_status(
            session,
            _standing(
                party_id=party,
                regime_id=regime.id,
                valid_from=date(2026, 1, 1),
                valid_to=date(2026, 12, 31),
                status="expired",
            ),
        )
        found = await repository.current_party_status(session, party_id=party, regime_id=regime.id, on_date=TODAY)
        # Returned rather than hidden: "this certificate was withdrawn" and
        # "this party was never verified" are answered differently.
        assert found is not None
        assert service.verification_is_current(found, TODAY) is False

    async def test_the_expiry_sweep_finds_what_lapses_inside_the_window(self, session):
        regime = await _stored_regime(session)
        inside = await repository.add_party_status(
            session,
            _standing(regime_id=regime.id, valid_to=TODAY + timedelta(days=20)),
        )
        await repository.add_party_status(
            session,
            _standing(regime_id=regime.id, valid_to=TODAY + timedelta(days=400)),
        )
        await repository.add_party_status(session, _standing(regime_id=regime.id, valid_to=None))

        found = await repository.expiring_party_statuses(session, from_date=TODAY, through=TODAY + timedelta(days=60))
        assert [row.id for row in found] == [inside.id]

    async def test_expiry_view_is_computed_not_stored(self, session):
        regime = await _stored_regime(session)
        row = await repository.add_party_status(
            session, _standing(regime_id=regime.id, valid_to=TODAY - timedelta(days=1))
        )
        expired, days = service.expiry_view(row, TODAY)
        assert expired is True
        assert days == -1
        # The row itself still says "active": the state on the record is what
        # somebody typed, and the answer is what the calendar says.
        assert row.status == "active"

    async def test_a_standing_recorded_expired_with_no_end_date_reads_as_expired(self, session):
        # The calendar wins over a record left at "active", but here there is no
        # calendar to consult and the record is the only evidence there is.
        # Answering "not expired" would have put a current-looking row on the
        # screen for a standing verification_is_current already refuses.
        regime = await _stored_regime(session)
        row = await repository.add_party_status(
            session, _standing(regime_id=regime.id, status="expired", valid_to=None)
        )
        expired, days = service.expiry_view(row, TODAY)
        assert expired is True
        # Nothing to count down to, so no countdown is offered.
        assert days is None
        assert service.verification_is_current(row, TODAY) is False

    async def test_an_open_ended_active_standing_is_not_expired(self, session):
        # The ordinary case for a standing with no end date, and the control
        # that keeps the check above from swallowing it.
        regime = await _stored_regime(session)
        row = await repository.add_party_status(session, _standing(regime_id=regime.id, valid_to=None))
        assert service.expiry_view(row, TODAY) == (False, None)
        assert service.verification_is_current(row, TODAY) is True

    async def test_a_revoked_standing_is_refused_without_being_called_expired(self, session):
        # Revocation is not expiry. Both are refused, but printing "expired" on
        # a standing an authority withdrew would send somebody looking for a
        # renewal date that was never the problem.
        regime = await _stored_regime(session)
        row = await repository.add_party_status(
            session, _standing(regime_id=regime.id, status="revoked", valid_to=None)
        )
        assert service.expiry_view(row, TODAY) == (False, None)
        assert service.verification_is_current(row, TODAY) is False


@pytest.mark.asyncio
class TestDeductionPersistence:
    async def test_a_deduction_round_trips_with_its_derived_net(self, session):
        user = await _user(session, "wh-owner@example.com")
        project = await _project(session, user)
        regime = await _stored_regime(session)
        row = await repository.add_deduction(
            session,
            WithholdingDeduction(
                project_id=project.id,
                regime_id=regime.id,
                period_start=date(2026, 8, 1),
                period_end=date(2026, 8, 31),
                gross_amount=Decimal("10000.00"),
                qualifying_materials=Decimal("2500.00"),
                taxable_base=Decimal("7500.00"),
                rate_pct=Decimal("20"),
                tax_withheld=Decimal("1500.00"),
                band_code="STANDARD",
                currency_code="GBP",
            ),
        )
        assert row.net_payable == Decimal("8500.00")
        assert isinstance(row.tax_withheld, Decimal)

    async def test_deductions_are_listed_by_project_and_overlapping_period(self, session):
        user = await _user(session, "wh-list@example.com")
        project = await _project(session, user)
        other = await _project(session, user, name="Other project")
        regime = await _stored_regime(session)

        def _row(project_id, start, end):
            return WithholdingDeduction(
                project_id=project_id,
                regime_id=regime.id,
                period_start=start,
                period_end=end,
                gross_amount=Decimal("100.00"),
                taxable_base=Decimal("100.00"),
                rate_pct=Decimal("20"),
                tax_withheld=Decimal("20.00"),
                currency_code="GBP",
            )

        await repository.add_deduction(session, _row(project.id, date(2026, 8, 1), date(2026, 8, 31)))
        await repository.add_deduction(session, _row(project.id, date(2026, 6, 1), date(2026, 6, 30)))
        await repository.add_deduction(session, _row(other.id, date(2026, 8, 1), date(2026, 8, 31)))

        august = await repository.list_deductions(
            session,
            project_id=project.id,
            period_start=date(2026, 8, 1),
            period_end=date(2026, 8, 31),
        )
        assert len(august) == 1
        assert august[0].period_start == date(2026, 8, 1)

        all_on_project = await repository.list_deductions(session, project_id=project.id)
        assert len(all_on_project) == 2

    async def test_a_project_gets_one_determination_per_invoice(self, session):
        user = await _user(session, "wh-rc@example.com")
        project = await _project(session, user)

        def _row():
            return ReverseChargeDetermination(
                project_id=project.id,
                invoice_reference="INV-2026-0042",
                country_code="GB",
                buyer_accounts_for_vat=True,
                invoice_wording="Reverse charge: VAT Act 1994 Section 55A applies.",
                net_amount=Decimal("10000.00"),
                vat_amount=Decimal("0"),
                currency_code="GBP",
            )

        await repository.add_determination(session, _row())
        found = await repository.get_determination_for_invoice(
            session, project_id=project.id, invoice_reference="INV-2026-0042"
        )
        assert found is not None
        assert found.buyer_accounts_for_vat is True


# ── Validation rules ─────────────────────────────────────────────────────────


def _deduction_request(**overrides) -> schemas.DeductionCreateRequest:
    body = {
        "project_id": uuid.uuid4(),
        "regime_id": uuid.uuid4(),
        "period_start": date(2026, 8, 1),
        "period_end": date(2026, 8, 31),
        "gross_amount": Decimal("10000.00"),
        "qualifying_materials": Decimal("2500.00"),
        "vat_amount": Decimal("0"),
        "taxable_base": Decimal("7500.00"),
        "tax_withheld": Decimal("1500.00"),
        "rate_pct": Decimal("20"),
        "band_code": "STANDARD",
        "currency_code": "GBP",
    }
    body.update(overrides)
    return schemas.DeductionCreateRequest(**body)


def _determination_request(**overrides) -> schemas.ReverseChargeCreateRequest:
    body = {
        "project_id": uuid.uuid4(),
        "invoice_reference": "INV-2026-0042",
        "country_code": "GB",
        "buyer_accounts_for_vat": True,
        "legal_reference": "VAT Act 1994 section 55A",
        "invoice_wording": "Reverse charge: VAT Act 1994 Section 55A applies. Customer to pay the VAT to HMRC.",
        "net_amount": Decimal("10000.00"),
        "vat_amount": Decimal("0"),
        "currency_code": "GBP",
    }
    body.update(overrides)
    return schemas.ReverseChargeCreateRequest(**body)


async def _findings(body, *, regime=None, party_status=None):
    register_tax_withholding_rules()
    if isinstance(body, schemas.ReverseChargeCreateRequest):
        return await evaluate_record(service.determination_payload(body))
    return await evaluate_record(service.deduction_payload(body, regime=regime, party_status=party_status))


def _ids(findings) -> set[str]:
    return {finding.rule_id for finding in findings}


@pytest.mark.asyncio
class TestBaseRule:
    async def test_a_correct_base_does_not_block(self):
        findings = await _findings(_deduction_request(), regime=_uk_regime(), party_status=_standing())
        assert blocking_findings(findings) == []

    async def test_materials_left_in_the_base_is_an_error(self):
        findings = await _findings(
            _deduction_request(taxable_base=Decimal("10000.00"), tax_withheld=Decimal("2000.00")),
            regime=_uk_regime(),
            party_status=_standing(),
        )
        assert "tax_withholding.taxable_base" in {f.rule_id for f in blocking_findings(findings)}

    async def test_the_error_says_what_it_costs_on_this_payment(self):
        findings = await _findings(
            _deduction_request(taxable_base=Decimal("10000.00"), tax_withheld=Decimal("2000.00")),
            regime=_uk_regime(),
            party_status=_standing(),
        )
        base_finding = next(f for f in findings if f.rule_id == "tax_withholding.taxable_base")
        # 20 percent of the 2500 of materials that should have come out.
        assert base_finding.details.get("over_withheld") == "500.00"

    async def test_a_german_base_equal_to_the_gross_is_correct(self):
        # Same numbers, different scheme, opposite verdict. Hardcoding the UK
        # rule would make this an error on every German payment.
        findings = await _findings(
            _deduction_request(
                taxable_base=Decimal("10000.00"),
                tax_withheld=Decimal("1500.00"),
                rate_pct=Decimal("15"),
                band_code="STANDARD",
                currency_code="EUR",
            ),
            regime=_de_regime(),
        )
        assert "tax_withholding.taxable_base" not in _ids(findings)

    async def test_a_base_that_is_simply_wrong_is_an_error(self):
        findings = await _findings(
            _deduction_request(taxable_base=Decimal("7000.00")),
            regime=_uk_regime(),
            party_status=_standing(),
        )
        assert "tax_withholding.taxable_base" in {f.rule_id for f in blocking_findings(findings)}


@pytest.mark.asyncio
class TestWithheldWithinBaseRule:
    async def test_withholding_more_than_the_base_is_an_error(self):
        findings = await _findings(
            _deduction_request(tax_withheld=Decimal("8000.00")),
            regime=_uk_regime(),
            party_status=_standing(),
        )
        assert "tax_withholding.withheld_within_base" in {f.rule_id for f in blocking_findings(findings)}

    async def test_withholding_the_whole_base_is_allowed(self):
        findings = await _findings(
            _deduction_request(tax_withheld=Decimal("7500.00"), rate_pct=Decimal("100")),
            regime=_uk_regime(),
            party_status=_standing(),
        )
        assert "tax_withholding.withheld_within_base" not in _ids(findings)


@pytest.mark.asyncio
class TestVerificationRule:
    async def test_an_expired_verification_blocks_the_reduced_band(self):
        findings = await _findings(
            _deduction_request(),
            regime=_uk_regime(),
            party_status=_standing(valid_to=date(2026, 6, 30)),
        )
        assert "tax_withholding.verification_required" in {f.rule_id for f in blocking_findings(findings)}

    async def test_a_missing_verification_blocks_the_reduced_band(self):
        findings = await _findings(_deduction_request(), regime=_uk_regime())
        assert "tax_withholding.verification_required" in {f.rule_id for f in blocking_findings(findings)}

    async def test_a_verification_with_no_reference_blocks_the_reduced_band(self):
        findings = await _findings(
            _deduction_request(),
            regime=_uk_regime(),
            party_status=_standing(verification_reference=""),
        )
        assert "tax_withholding.verification_required" in {f.rule_id for f in blocking_findings(findings)}

    async def test_the_higher_band_needs_no_verification(self):
        findings = await _findings(
            _deduction_request(band_code="HIGHER", rate_pct=Decimal("30"), tax_withheld=Decimal("2250.00")),
            regime=_uk_regime(),
        )
        assert "tax_withholding.verification_required" not in _ids(findings)
        assert blocking_findings(findings) == []

    async def test_a_certificate_lapsing_inside_the_period_warns_without_blocking(self):
        # Judged at the start of the period, so the payment itself is covered;
        # what lapses mid-period is a warning about the next one.
        findings = await _findings(
            _deduction_request(),
            regime=_uk_regime(),
            party_status=_standing(valid_to=date(2026, 8, 20)),
        )
        assert "tax_withholding.verification_expiring" in _ids(findings)
        assert "tax_withholding.verification_required" not in _ids(findings)
        assert blocking_findings(findings) == []


@pytest.mark.asyncio
class TestRateRule:
    async def test_a_rate_that_is_not_the_bands_rate_warns_without_blocking(self):
        findings = await _findings(
            _deduction_request(rate_pct=Decimal("18"), tax_withheld=Decimal("1350.00")),
            regime=_uk_regime(),
            party_status=_standing(),
        )
        assert "tax_withholding.rate_matches_band" in _ids(findings)
        assert blocking_findings(findings) == []


@pytest.mark.asyncio
class TestReverseChargeRule:
    async def test_a_well_formed_reverse_charge_invoice_does_not_block(self):
        assert blocking_findings(await _findings(_determination_request())) == []

    async def test_missing_wording_is_an_error(self):
        findings = await _findings(_determination_request(invoice_wording=""))
        assert "tax_withholding.reverse_charge_invoice" in {f.rule_id for f in blocking_findings(findings)}

    async def test_a_vat_amount_on_a_reverse_charge_invoice_is_an_error(self):
        findings = await _findings(_determination_request(vat_amount=Decimal("2000.00")))
        blocking = blocking_findings(findings)
        assert "tax_withholding.reverse_charge_invoice" in {f.rule_id for f in blocking}
        assert any("twice" in f.message for f in blocking)

    async def test_both_faults_are_reported_separately(self):
        # Fixing one of the two and being told the invoice is still wrong is
        # better than being told once and having to guess which half.
        findings = await _findings(_determination_request(invoice_wording="", vat_amount=Decimal("2000.00")))
        assert len([f for f in findings if f.rule_id == "tax_withholding.reverse_charge_invoice"]) == 2

    async def test_wording_without_the_decision_behind_it_is_an_error(self):
        findings = await _findings(_determination_request(buyer_accounts_for_vat=False))
        assert "tax_withholding.reverse_charge_invoice" in {f.rule_id for f in blocking_findings(findings)}

    async def test_an_ordinary_vat_invoice_is_not_touched(self):
        findings = await _findings(
            _determination_request(
                buyer_accounts_for_vat=False,
                invoice_wording="",
                vat_amount=Decimal("2000.00"),
            )
        )
        assert blocking_findings(findings) == []

    async def test_the_deduction_rules_ignore_a_determination(self):
        # One rule set, two record shapes. A rule that read the wrong one would
        # report a missing taxable base on every reverse-charge invoice.
        findings = await _findings(_determination_request())
        assert "tax_withholding.taxable_base" not in _ids(findings)
        assert "tax_withholding.withheld_within_base" not in _ids(findings)


# ── Permissions ──────────────────────────────────────────────────────────────


class TestTaxWithholdingPermissions:
    """Every permission the router names has to exist in the registry.

    ``RequirePermission`` denies an unregistered key rather than waving it
    through, and admin short-circuits above the check, so a module that forgets
    its ``permissions.py`` ships endpoints only an admin can reach and no test
    that calls them as an admin notices.
    """

    @staticmethod
    def _router_permissions() -> set[str]:
        from app.modules.tax_withholding.router import router

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

        register_tax_withholding_permissions()
        asked = self._router_permissions()
        assert asked, "no route declared a permission; the guard would be vacuous"
        registered = set(permission_registry.list_all())
        assert asked <= registered, f"unregistered: {sorted(asked - registered)}"

    def test_every_route_declares_a_permission(self):
        from app.modules.tax_withholding.router import router

        undeclared = [
            getattr(route, "path", "?")
            for route in router.routes
            if not [
                dep
                for dep in (getattr(route, "dependencies", []) or [])
                if isinstance(getattr(getattr(dep, "dependency", None), "permission", None), str)
            ]
        ]
        assert undeclared == [], f"routes with no permission gate: {undeclared}"

    def test_the_roles_match_what_each_key_can_do(self):
        from app.core.permissions import Role, permission_registry

        register_tax_withholding_permissions()
        assert permission_registry.role_has_permission(Role.VIEWER, "tax_withholding.read") is True
        assert permission_registry.role_has_permission(Role.VIEWER, "tax_withholding.write") is False
        assert permission_registry.role_has_permission(Role.EDITOR, "tax_withholding.write") is True
        # Editing a scheme changes the rate on every future deduction across
        # every project, and deleting one removes the evidence behind money
        # already remitted. Neither is an editor's call.
        assert permission_registry.role_has_permission(Role.EDITOR, "tax_withholding.manage") is False
        assert permission_registry.role_has_permission(Role.MANAGER, "tax_withholding.manage") is True


# ── Naming ───────────────────────────────────────────────────────────────────


def test_tables_are_named_by_convention():
    assert WithholdingRegime.__tablename__ == "oe_tax_withholding_regime"
    assert PartyTaxStatus.__tablename__ == "oe_tax_withholding_party"
    assert WithholdingDeduction.__tablename__ == "oe_tax_withholding_deduction"
    assert ReverseChargeDetermination.__tablename__ == "oe_tax_withholding_reverse_charge"


def test_no_column_here_reuses_the_name_retainage_already_has():
    """``withholding_amount`` means retainage in ``finance`` and ``subcontractors``.

    Retainage is held back from a certified claim and released to the payee
    later; tax withheld goes to the state and never comes back. Two obligations
    sharing one English word is already one collision too many, so this module
    names its money column for what it is.
    """
    taken = {"withholding_amount", "withholding_release_date", "retention_amount", "retention_percent"}
    for model in (
        WithholdingRegime,
        PartyTaxStatus,
        WithholdingDeduction,
        ReverseChargeDetermination,
        StatutoryTaxCalc,
        StatutoryTaxLine,
    ):
        clashes = {column.name for column in model.__table__.columns} & taken
        assert clashes == set(), f"{model.__tablename__} reuses {sorted(clashes)}"
    assert "tax_withheld" in {column.name for column in WithholdingDeduction.__table__.columns}


# ── The two install routes ───────────────────────────────────────────────────


def _revision_module():
    """Load the revision file without running it - it is read, not executed."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "v3283_withholding.py"
    spec = importlib.util.spec_from_file_location("_v3283_withholding", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_revision_is_chained_where_the_wave_put_it():
    revision = _revision_module()
    assert revision.revision == "v3283_withholding"
    assert revision.down_revision == "v3282_einvoicing"


def test_the_migration_builds_the_same_indexes_as_a_fresh_install():
    """A schema built by walking the chain must match one built by ``create_all``.

    ``app.core.pg_optimizations`` hangs performance indexes off the tables on
    the ``create_all`` path only, and it does not run under alembic. A revision
    that omits them is a real divergence between an upgraded deployment and a
    fresh one, and nothing else in the tree would notice: both schemas hold the
    same rows and answer the same queries, just at different speeds.
    """
    from app.core.pg_optimizations import _desired_indexes

    revision = _revision_module()
    declared = {name for name, _, _ in revision._MODEL_INDEXES} | {name for name, _, _ in revision._PERFORMANCE_INDEXES}
    built: set[str] = set()
    for model in (WithholdingRegime, PartyTaxStatus, WithholdingDeduction, ReverseChargeDetermination):
        table = model.__table__
        built |= {index.name for index in table.indexes}
        built |= {index.name for index in _desired_indexes(table)}

    assert built - declared == set(), (
        f"a fresh install has indexes the migration never creates: {sorted(built - declared)}"
    )
    assert declared - built == set(), (
        f"the migration creates indexes a fresh install never has: {sorted(declared - built)}"
    )
    # PostgreSQL truncates an identifier past 63 bytes, and SQLAlchemy hashes
    # rather than chops - so an over-long name would differ between the two
    # routes rather than simply being ugly.
    assert [name for name in declared if len(name) > 63] == []


# ── Statutory tax lines: synthetic rate rows ─────────────────────────────────
#
# Every rate row below is invented. No statutory value of any country appears
# in these tests, so correcting a shipped rate cannot break one of them, and
# none of them can become the place a rate was "filled in". The rows reach the
# service through its ``row_source`` argument, never through the shipped data.

DOC_DATE = date(2026, 3, 10)


def _stat_row(**changes) -> RateRow:
    base = RateRow(
        country_code="XX",
        kind="vat_withholding",
        code="W1",
        labels={"en": "Synthetic work"},
        base="vat",
        rate_pct=None,
        numerator=3,
        denominator=10,
        threshold_amount=None,
        threshold_currency="",
        threshold_scope="",
        threshold_measure="",
        cap_amount=None,
        effective_from=date(2020, 1, 1),
        effective_to=None,
        legal_reference="Synthetic Act art. 1",
        source_url="https://example.invalid/act/1",
        read_date="2026-01-01",
        review_status="confirmed",
    )
    return replace(base, **changes)


def _stat_rows(**w1_changes) -> tuple[RateRow, ...]:
    percent = {"base": "net", "numerator": None, "denominator": None}
    return (
        _stat_row(**w1_changes),
        _stat_row(code="W2", numerator=7, review_status="unconfirmed", legal_reference="Synthetic Act art. 2"),
        _stat_row(code="W3", buyer_scope="designated_only", legal_reference="Synthetic Act art. 3"),
        _stat_row(kind="income_withholding", code="I1", rate_pct=Decimal("4"), **percent),
        _stat_row(
            kind="income_withholding",
            code="I2",
            rate_pct=Decimal("4"),
            threshold_amount=Decimal("500"),
            threshold_currency="EUR",
            threshold_scope="per_payee_year",
            threshold_measure="net",
            **percent,
        ),
        _stat_row(kind="stamp_duty", code="S1", rate_pct=Decimal("0.25"), **percent),
    )


def _source(rows: tuple[RateRow, ...] | None = None):
    """A row source that hands out the given synthetic rows for any country."""
    table = _stat_rows() if rows is None else rows
    return lambda country: table


def _inputs(**changes) -> service.StatutoryInputs:
    values = {
        "country_code": "XX",
        "currency_code": "EUR",
        "document_date": DOC_DATE,
        "net_amount": Decimal("100000.00"),
        "vat_rate_pct": Decimal("20"),
        "vat_withholding": Choice("selected", code="W1"),
        "income_withholding": Choice("selected", code="I1"),
        "stamp_duty": Choice("not_applicable", reason="Private contract, no taxable paper"),
    }
    values.update(changes)
    return service.StatutoryInputs(**values)


def _unstored_lines(result, inputs: service.StatutoryInputs, rows) -> list[StatutoryTaxLine]:
    """Lines built in memory from a result, the way the service fills them."""
    return [StatutoryTaxLine(**values) for values in service.result_line_values(result, inputs, rows)]


class TestStatutoryFiguresToRows:
    """The plain functions that turn a result into rows and back. No database."""

    def test_preview_is_the_shared_calculation_and_nothing_else(self):
        inputs = _inputs()
        rows = _stat_rows()
        assert service.preview_statutory(inputs, rows) == compute_payment_taxes(service.build_tax_input(inputs), rows)

    def test_the_two_buyer_inputs_reach_the_calculation(self):
        inputs = _inputs(buyer_is_designated=True, work_value_incl_vat=Decimal("750000.00"))
        tax_input = service.build_tax_input(inputs)
        assert tax_input.buyer_is_designated is True
        assert tax_input.work_value_incl_vat == Decimal("750000.00")

    def test_an_unknown_vat_rate_is_passed_on_as_unknown(self):
        result = service.preview_statutory(_inputs(vat_rate_pct=None), _stat_rows())
        assert service.build_tax_input(_inputs(vat_rate_pct=None)).vat_rate_pct is None
        assert result.vat_computed.status == "held"
        assert result.vat_computed.amount is None

    def test_a_result_survives_the_trip_through_rows(self):
        inputs = _inputs()
        rows = _stat_rows()
        result = service.preview_statutory(inputs, rows)
        assert result.complete, "the fixture is meant to compute every figure"
        assert service.result_from_lines(_unstored_lines(result, inputs, rows)) == result

    def test_a_held_figure_is_stored_with_no_amount(self):
        inputs = _inputs(vat_withholding=Choice("unset"))
        rows = _stat_rows()
        values = {
            line["kind"]: line
            for line in service.result_line_values(service.preview_statutory(inputs, rows), inputs, rows)
        }
        assert values["vat_withheld"]["calc_status"] == "held"
        assert values["vat_withheld"]["tax_amount"] is None
        assert values["vat_payable"]["tax_amount"] is None

    def test_a_not_applicable_figure_is_stored_with_no_amount(self):
        inputs = _inputs()
        rows = _stat_rows()
        values = {
            line["kind"]: line
            for line in service.result_line_values(service.preview_statutory(inputs, rows), inputs, rows)
        }
        assert values["stamp_duty"]["calc_status"] == "not_applicable"
        assert values["stamp_duty"]["tax_amount"] is None

    def test_a_real_zero_is_a_value_and_not_an_absence(self):
        inputs = _inputs(net_amount=Decimal("0.00"))
        rows = _stat_rows()
        values = {
            line["kind"]: line
            for line in service.result_line_values(service.preview_statutory(inputs, rows), inputs, rows)
        }
        assert values["vat_withheld"]["calc_status"] == "value"
        assert values["vat_withheld"]["tax_amount"] is not None
        assert values["vat_withheld"]["tax_amount"] == Decimal("0")

    def test_the_row_end_date_and_source_are_kept_beside_the_figure(self):
        rows = _stat_rows(effective_to=date(2026, 12, 31))
        inputs = _inputs()
        values = {
            line["kind"]: line
            for line in service.result_line_values(service.preview_statutory(inputs, rows), inputs, rows)
        }
        assert values["vat_withheld"]["rate_effective_to"] == date(2026, 12, 31)
        assert values["vat_withheld"]["source_url"] == "https://example.invalid/act/1"
        # Computed VAT comes from the caller's rate, not from a row.
        assert values["vat_computed"]["rate_effective_from"] is None

    def test_missing_lines_are_not_filled_in(self):
        inputs = _inputs()
        rows = _stat_rows()
        lines = _unstored_lines(service.preview_statutory(inputs, rows), inputs, rows)
        with pytest.raises(service.StatutoryDataError, match="incomplete"):
            service.result_from_lines([line for line in lines if line.kind != "stamp_duty"])

    def test_a_value_line_without_an_amount_is_refused_on_read(self):
        inputs = _inputs()
        rows = _stat_rows()
        lines = _unstored_lines(service.preview_statutory(inputs, rows), inputs, rows)
        next(line for line in lines if line.kind == "vat_withheld").tax_amount = None
        with pytest.raises(service.StatutoryDataError):
            service.result_from_lines(lines)

    @pytest.mark.parametrize(
        ("stored", "currency", "expected"),
        [
            (Decimal("8000.0000"), "EUR", "8000.00"),
            (Decimal("8000.1250"), "KWD", "8000.125"),
            (Decimal("8000.0000"), "JPY", "8000"),
            (Decimal("0.0000"), "EUR", "0.00"),
        ],
    )
    def test_a_stored_amount_comes_back_on_its_currency_precision(self, stored, currency, expected):
        assert str(service.money_as_stored(stored, currency)) == expected

    def test_a_missing_amount_stays_missing_on_read(self):
        assert service.money_as_stored(None, "EUR") is None

    def test_a_stored_amount_finer_than_the_currency_is_not_rounded(self):
        with pytest.raises(service.StatutoryDataError):
            service.money_as_stored(Decimal("8000.1250"), "EUR")

    def test_a_net_amount_finer_than_the_currency_is_refused(self):
        with pytest.raises(service.StatutoryRefusal) as caught:
            service.preview_statutory(_inputs(net_amount=Decimal("100.005")), _stat_rows())
        assert caught.value.code == "amount_finer_than_currency"
        assert caught.value.http_status == 422

    def test_a_rate_that_would_be_rounded_by_the_column_is_refused(self):
        with pytest.raises(service.StatutoryRefusal) as caught:
            service.preview_statutory(_inputs(vat_rate_pct=Decimal("20.1234567")), _stat_rows())
        assert caught.value.code == "rate_not_storable"

    def test_plain_decimal_drops_padding_and_exponents(self):
        assert str(service.plain_decimal(Decimal("20.000000"))) == "20"
        assert str(service.plain_decimal(Decimal("0.250000"))) == "0.25"
        assert str(service.plain_decimal(Decimal("0"))) == "0"


class TestStampDutyHasItsOwnBase:
    """Stamp duty is charged on a base of its own. The VAT base is never reused in silence."""

    SELECTED = Choice("selected", code="S1")

    def test_a_selected_stamp_duty_with_no_stated_base_is_held(self):
        result = service.compute_statutory(_inputs(stamp_duty=self.SELECTED), _stat_rows())
        assert result.stamp_duty.status == "held"
        assert result.stamp_duty.amount is None
        assert result.stamp_duty.reason_key == "stamp_duty_base_unknown"
        assert result.stamp_duty.code == "S1"
        # The other four figures are untouched by the missing base.
        assert result.vat_withheld.amount == Decimal("6000.00")
        assert result.income_withheld.amount == Decimal("4000.00")

    def test_an_entered_base_is_the_base_of_the_stamp_duty_and_of_nothing_else(self):
        inputs = _inputs(stamp_duty=self.SELECTED, stamp_duty_base=Decimal("80000.00"))
        result = service.compute_statutory(inputs, _stat_rows())
        assert result.stamp_duty.status == "value"
        assert result.stamp_duty.base == Decimal("80000.00")
        # 0.25 percent of 80000.00, the synthetic row.
        assert result.stamp_duty.amount == Decimal("200.00")
        assert result.vat_computed.base == Decimal("100000.00")
        assert result.income_withheld.base == Decimal("100000.00")

    def test_the_net_amount_is_the_base_only_when_a_person_says_so(self):
        inputs = _inputs(stamp_duty=self.SELECTED, stamp_duty_base_same_as_net=True)
        result = service.compute_statutory(inputs, _stat_rows())
        assert result.stamp_duty.base == Decimal("100000.00")
        assert result.stamp_duty.amount == Decimal("250.00")

    def test_a_base_and_the_statement_together_are_refused(self):
        inputs = _inputs(
            stamp_duty=self.SELECTED, stamp_duty_base=Decimal("80000.00"), stamp_duty_base_same_as_net=True
        )
        with pytest.raises(service.StatutoryRefusal) as caught:
            service.compute_statutory(inputs, _stat_rows())
        assert caught.value.code == "stamp_duty_base_contradiction"
        with pytest.raises(ValidationError):
            schemas.StatutoryPreviewRequest(
                country_code="XX",
                currency_code="EUR",
                document_date="2026-03-10",
                net_amount="1.00",
                vat_rate_pct=None,
                stamp_duty_base="1.00",
                stamp_duty_base_same_as_net=True,
            )

    def test_an_amount_entered_for_stamp_duty_goes_to_the_stamp_duty_call(self):
        inputs = _inputs(stamp_duty=self.SELECTED, stamp_duty_base=Decimal("80000.00"))
        entered = {"stamp_duty": service.StoredOverride(Decimal("199.00"), "Per the tax office receipt", None, None)}
        result = service.compute_statutory(inputs, _stat_rows(), entered)
        assert result.stamp_duty.overridden is True
        assert result.stamp_duty.amount == Decimal("199.00")
        assert result.stamp_duty.base == Decimal("80000.00")

    def test_a_stamp_duty_not_chosen_asks_for_no_base(self):
        result = service.compute_statutory(_inputs(stamp_duty=Choice("unset")), _stat_rows())
        assert result.stamp_duty.reason_key == "not_chosen"

    def test_the_override_request_accepts_the_row_kind_as_a_name(self):
        parsed = schemas.StatutoryOverrideRequest(
            project_id=uuid.uuid4(), kind="vat_withholding", amount="1.00", reason="x"
        )
        assert parsed.kind == "vat_withheld"


class TestShippedRowsAreListable:
    """Structure only. No value of a shipped row is asserted, so a corrected rate breaks nothing here."""

    @pytest.mark.asyncio
    async def test_every_shipped_category_can_be_listed_today(self):
        from app.core.payment_taxes import rows_for, validate_rows
        from app.modules.tax_withholding.router import list_statutory_categories

        rows = rows_for("TR")
        assert rows, "no rows ship for TR, so the loop below would pass over nothing"
        assert validate_rows(rows) == []
        # A date taken from the table itself: the newest row is in force on the
        # day it starts, so the listing is never empty and never depends on the
        # day the test runs.
        on = max(row.effective_from for row in rows)
        in_force = {
            (row.kind, row.code)
            for row in rows
            if row.effective_from <= on and (row.effective_to is None or on <= row.effective_to)
        }
        page = await list_statutory_categories(
            row_source=service.shipped_rows, country="TR", on=on, kind=None, offset=0, limit=500
        )
        listed = page.items
        assert listed
        assert (page.total, page.offset, page.limit) == (len(listed), 0, 500)
        assert {(c.kind, c.code) for c in listed} == in_force
        assert len({(c.kind, c.code) for c in listed}) == len(listed)
        for category in listed:
            dumped = category.model_dump(mode="json")
            assert dumped["code"]
            assert dumped["legal_reference"]
            assert dumped["review_status"] in {"confirmed", "unconfirmed"}
            assert dumped["kind"] in {"vat_withholding", "income_withholding", "stamp_duty"}

    @pytest.mark.asyncio
    async def test_a_page_of_categories_says_how_many_there_are_in_all(self):
        from app.core.payment_taxes import rows_for
        from app.modules.tax_withholding.router import list_statutory_categories

        on = max(row.effective_from for row in rows_for("TR"))

        async def page(offset: int, limit: int):
            return await list_statutory_categories(
                row_source=service.shipped_rows, country="TR", on=on, kind=None, offset=offset, limit=limit
            )

        everything = await page(0, 500)
        assert everything.total >= 2, "one category cannot show a page being cut"
        first = await page(0, 1)
        rest = await page(1, 500)
        # A short page still reports the whole count, which is the point of the envelope.
        assert (len(first.items), first.total, first.limit) == (1, everything.total, 1)
        assert [(c.kind, c.code) for c in [*first.items, *rest.items]] == [(c.kind, c.code) for c in everything.items]
        assert (await page(everything.total, 500)).items == []

    @pytest.mark.asyncio
    async def test_no_listed_category_is_refused_as_a_broken_or_ambiguous_row(self):
        from app.core.payment_taxes import rows_for
        from app.modules.tax_withholding.router import list_statutory_categories

        rows = rows_for("TR")
        on = max(row.effective_from for row in rows)
        page = await list_statutory_categories(
            row_source=service.shipped_rows, country="TR", on=on, kind=None, offset=0, limit=500
        )
        listed = page.items
        assert listed
        idle = Choice("not_applicable", reason="Not the figure under test")
        for category in listed:
            choices = {"vat_withholding": idle, "income_withholding": idle, "stamp_duty": idle}
            choices[category.kind] = Choice("selected", code=category.code)
            inputs = service.StatutoryInputs(
                country_code="TR",
                currency_code="TRY",
                document_date=on,
                net_amount=Decimal("100000.00"),
                vat_rate_pct=Decimal("20"),
                buyer_is_designated=True,
                stamp_duty_base_same_as_net=True,
                **choices,
            )
            result = service.compute_statutory(inputs, rows, {})
            reasons = {values["reason_key"] for values in service.result_line_values(result, inputs, rows)}
            assert not reasons & {"rate_row_invalid", "rate_ambiguous"}, (category.kind, category.code)


class TestStatutoryConfirmationGuard:
    """What stops a signature, checked without the rule engine."""

    @staticmethod
    def _values(**changes):
        inputs = _inputs(**changes)
        rows = _stat_rows()
        return service.result_line_values(service.preview_statutory(inputs, rows), inputs, rows)

    def test_complete_confirmed_figures_may_be_confirmed(self):
        assert service.confirmation_refusal(self._values(), acknowledged=False) is None

    def test_a_held_figure_stops_confirmation_even_when_acknowledged(self):
        refusal = service.confirmation_refusal(self._values(income_withholding=Choice("unset")), acknowledged=True)
        assert refusal is not None
        assert refusal.code == "statutory_held"
        assert refusal.details["held"] == ["income_withheld"]

    def test_an_unconfirmed_rate_stops_confirmation_until_acknowledged(self):
        values = self._values(vat_withholding=Choice("selected", code="W2"))
        refusal = service.confirmation_refusal(values, acknowledged=False)
        assert refusal is not None
        assert refusal.code == "statutory_unconfirmed_rates"
        assert refusal.details["codes"] == ["W2"]
        assert service.confirmation_refusal(values, acknowledged=True) is None

    def test_an_unconfirmed_row_counts_even_when_it_only_decided_not_applicable(self):
        rows = (_stat_row(code="W3", buyer_scope="designated_only", review_status="unconfirmed"),) + _stat_rows()[3:]
        inputs = _inputs(vat_withholding=Choice("selected", code="W3"), buyer_is_designated=False)
        values = service.result_line_values(service.preview_statutory(inputs, rows), inputs, rows)
        by_kind = {line["kind"]: line for line in values}
        assert by_kind["vat_withheld"]["calc_status"] == "not_applicable"
        assert service.unconfirmed_codes(values) == ["W3"]


class TestStatutorySchemas:
    def _body(self, **changes) -> dict:
        body = {
            "country_code": "xx",
            "currency_code": "eur",
            "document_date": "2026-03-10",
            "net_amount": "100000.00",
            "vat_rate_pct": "20",
        }
        body.update(changes)
        return body

    def test_the_vat_rate_has_no_default(self):
        body = self._body()
        del body["vat_rate_pct"]
        with pytest.raises(ValidationError) as caught:
            schemas.StatutoryPreviewRequest(**body)
        assert [error["loc"] for error in caught.value.errors()] == [("vat_rate_pct",)]

    def test_an_unknown_vat_rate_is_stated_as_null(self):
        assert schemas.StatutoryPreviewRequest(**self._body(vat_rate_pct=None)).vat_rate_pct is None

    def test_choices_default_to_undecided(self):
        parsed = schemas.StatutoryPreviewRequest(**self._body())
        assert parsed.vat_withholding.state == "unset"
        assert parsed.country_code == "XX"
        assert parsed.currency_code == "EUR"

    def test_not_applicable_needs_a_reason(self):
        with pytest.raises(ValidationError):
            schemas.StatutoryChoice(state="not_applicable", reason="   ")

    def test_selected_needs_a_code(self):
        with pytest.raises(ValidationError):
            schemas.StatutoryChoice(state="selected")

    def test_an_override_needs_a_reason(self):
        with pytest.raises(ValidationError):
            schemas.StatutoryOverrideRequest(project_id=uuid.uuid4(), kind="vat_withheld", amount="1.00", reason=" ")

    def test_payable_vat_cannot_be_named_for_an_override(self):
        with pytest.raises(ValidationError):
            schemas.StatutoryOverrideRequest(project_id=uuid.uuid4(), kind="vat_payable", amount="1.00", reason="x")

    def test_a_missing_amount_serialises_as_null_and_never_as_zero(self):
        figure = schemas.StatutoryFigureResponse(
            kind="vat_withheld",
            status="held",
            amount=None,
            base=None,
            rate_pct=None,
            numerator=None,
            denominator=None,
            code="",
            currency_code="EUR",
            legal_reference="",
            effective_from=None,
            review_status="",
            overridden=False,
            reason_key="not_chosen",
        )
        dumped = figure.model_dump(mode="json")
        assert dumped["amount"] is None
        assert dumped["base"] is None

    def test_an_amount_serialises_as_the_string_it_is(self):
        figure = schemas.StatutoryFigureResponse(
            kind="vat_withheld",
            status="value",
            amount=Decimal("6000.00"),
            base=Decimal("20000.00"),
            rate_pct=None,
            numerator=3,
            denominator=10,
            code="W1",
            currency_code="EUR",
            legal_reference="Synthetic Act art. 1",
            effective_from=date(2020, 1, 1),
            review_status="confirmed",
            overridden=False,
            reason_key="",
        )
        dumped = figure.model_dump(mode="json")
        assert dumped["amount"] == "6000.00"
        assert dumped["base"] == "20000.00"


# ── Statutory tax lines: storage (PostgreSQL) ────────────────────────────────


#: Which project each source document of these tests belongs to. A real
#: document has an owner in its own module; here the first project a document
#: is saved under is its owner, which is what makes filing it under a second
#: project a refusal.
_SOURCE_OWNERS: dict[tuple[str, uuid.UUID], uuid.UUID] = {}


@pytest.fixture(autouse=True)
def _source_owners():
    """Stand in for the modules that own the source documents."""
    before = dict(source_owners._resolvers)
    _SOURCE_OWNERS.clear()
    for kind in service.STATUTORY_SOURCE_KINDS:
        source_owners.register_source_owner(
            kind, lambda _session, source_id, kind=kind: _SOURCE_OWNERS.get((kind, source_id))
        )
    yield
    source_owners._resolvers.clear()
    source_owners._resolvers.update(before)
    _SOURCE_OWNERS.clear()


async def _stat_setup(session: AsyncSession, tag: str) -> tuple[User, Project]:
    owner = await _user(session, f"{tag}-{uuid.uuid4().hex[:8]}@test.io")
    return owner, await _project(session, owner, name=f"Statutory {tag}")


async def _save(session: AsyncSession, owner: User, project: Project, source_id: uuid.UUID, **changes):
    arguments = {
        "project_id": project.id,
        "source_kind": "progress_claim",
        "source_id": source_id,
        "inputs": _inputs(),
        "direction": "borne_by_us",
        "user_id": owner.id,
        "source_reference": "PC-007",
        "row_source": _source(),
    }
    arguments.update(changes)
    _SOURCE_OWNERS.setdefault((arguments["source_kind"], arguments["source_id"]), project.id)
    return await service.upsert_statutory(session, **arguments)


async def _null_amount_kinds(session: AsyncSession, calc_id: uuid.UUID) -> set[str]:
    """Kinds whose amount is NULL in the table, asked of the database itself."""
    stmt = select(StatutoryTaxLine.kind).where(
        StatutoryTaxLine.calc_id == calc_id, StatutoryTaxLine.tax_amount.is_(None)
    )
    return set((await session.execute(stmt)).scalars().all())


@pytest.mark.asyncio
class TestStatutoryPersistence:
    async def test_compute_store_load_gives_back_the_same_result(self, session: AsyncSession):
        owner, project = await _stat_setup(session, "roundtrip")
        source_id = uuid.uuid4()
        calc, lines = await _save(session, owner, project, source_id)
        session.expire_all()

        loaded = await service.as_payment_tax_result(session, source_kind="progress_claim", source_id=source_id)
        expected = compute_payment_taxes(service.build_tax_input(_inputs()), _stat_rows())
        assert loaded == expected
        assert [line.kind for line in lines] == list(STATUTORY_LINE_KINDS)
        assert calc.status == "draft"
        assert calc.direction == "borne_by_us"

    async def test_the_stored_inputs_reproduce_the_calculation(self, session: AsyncSession):
        owner, project = await _stat_setup(session, "inputs")
        source_id = uuid.uuid4()
        inputs = _inputs(
            vat_withholding=Choice("selected", code="W3"),
            buyer_is_designated=True,
            work_value_incl_vat=Decimal("750000.00"),
            work_value_note="Value of the main contract, not of this subcontract",
            stamp_duty=Choice("selected", code="S1"),
            stamp_duty_base=Decimal("80000.00"),
        )
        calc, lines = await _save(session, owner, project, source_id, inputs=inputs)
        session.expire_all()
        calc = await repository.get_statutory_calc(session, source_kind="progress_claim", source_id=source_id)
        lines = await repository.list_statutory_lines(session, calc.id)

        assert service.inputs_from_stored(calc, lines) == inputs
        # Loaded, the rows give back what the two calls computed.
        loaded = service.result_from_lines(lines)
        assert loaded == service.compute_statutory(inputs, _stat_rows())
        assert loaded.stamp_duty.base == Decimal("80000.00")

    async def test_an_undecided_buyer_class_is_stored_as_unknown(self, session: AsyncSession):
        owner, project = await _stat_setup(session, "buyer")
        source_id = uuid.uuid4()
        inputs = _inputs(vat_withholding=Choice("selected", code="W3"))
        calc, _ = await _save(session, owner, project, source_id, inputs=inputs)
        session.expire_all()
        calc = await repository.get_statutory_calc(session, source_kind="progress_claim", source_id=source_id)

        assert calc.buyer_is_designated is None
        assert calc.work_value_incl_vat is None
        assert calc.stamp_duty_base is None
        assert calc.stamp_duty_base_same_as_net is False
        result = await service.as_payment_tax_result(session, source_kind="progress_claim", source_id=source_id)
        assert result.vat_withheld.status == "held"
        assert result.vat_withheld.reason_key == "buyer_class_unknown"

    async def test_held_and_not_applicable_are_null_in_the_table(self, session: AsyncSession):
        owner, project = await _stat_setup(session, "nulls")
        calc, _ = await _save(session, owner, project, uuid.uuid4(), inputs=_inputs(income_withholding=Choice("unset")))
        # income_withheld is held, stamp_duty is not applicable.
        assert await _null_amount_kinds(session, calc.id) == {"income_withheld", "stamp_duty"}

    async def test_an_unknown_vat_rate_stores_no_vat_amounts(self, session: AsyncSession):
        owner, project = await _stat_setup(session, "novat")
        calc, _ = await _save(session, owner, project, uuid.uuid4(), inputs=_inputs(vat_rate_pct=None))
        assert {"vat_computed", "vat_withheld", "vat_payable"} <= await _null_amount_kinds(session, calc.id)
        assert calc.vat_rate_pct is None

    async def test_saving_twice_keeps_one_header_and_five_lines(self, session: AsyncSession):
        owner, project = await _stat_setup(session, "idem")
        source_id = uuid.uuid4()
        first_calc, first_lines = await _save(session, owner, project, source_id)
        second_calc, second_lines = await _save(session, owner, project, source_id)

        assert second_calc.id == first_calc.id
        assert {line.id for line in second_lines} == {line.id for line in first_lines}
        count = await session.scalar(
            select(func.count()).select_from(StatutoryTaxLine).where(StatutoryTaxLine.source_id == source_id)
        )
        assert count == 5

    async def test_two_source_kinds_with_one_id_are_two_documents(self, session: AsyncSession):
        owner, project = await _stat_setup(session, "kinds")
        shared = uuid.uuid4()
        claim, _ = await _save(session, owner, project, shared)
        invoice, _ = await _save(
            session,
            owner,
            project,
            shared,
            source_kind="invoice",
            inputs=_inputs(net_amount=Decimal("500.00")),
            direction="withheld_by_us",
        )
        assert claim.id != invoice.id
        on_claim = await service.as_payment_tax_result(session, source_kind="progress_claim", source_id=shared)
        on_invoice = await service.as_payment_tax_result(session, source_kind="invoice", source_id=shared)
        assert on_claim.vat_computed.amount == Decimal("20000.00")
        assert on_invoice.vat_computed.amount == Decimal("100.00")

    async def test_a_document_filed_under_another_project_reads_as_not_found(self, session: AsyncSession):
        owner, project = await _stat_setup(session, "mine")
        _, other_project = await _stat_setup(session, "theirs")
        source_id = uuid.uuid4()
        await _save(session, owner, project, source_id)

        with pytest.raises(service.StatutoryRefusal) as caught:
            await _save(session, owner, other_project, source_id)
        assert caught.value.http_status == 404
        assert caught.value.code == "statutory_not_found"

    @pytest.mark.parametrize(
        ("currency", "net", "computed", "withheld", "payable"),
        [
            ("KWD", "1000.555", "200.111", "60.033", "140.078"),
            ("JPY", "100005", "20001", "6000", "14001"),
        ],
    )
    async def test_amounts_keep_the_precision_of_their_currency(
        self, session: AsyncSession, currency, net, computed, withheld, payable
    ):
        owner, project = await _stat_setup(session, f"cur{currency.lower()}")
        source_id = uuid.uuid4()
        inputs = _inputs(currency_code=currency, net_amount=Decimal(net), income_withholding=Choice("unset"))
        await _save(session, owner, project, source_id, inputs=inputs)
        session.expire_all()
        calc = await repository.get_statutory_calc(session, source_kind="progress_claim", source_id=source_id)
        values = {
            line.kind: service.stored_line_values(line)
            for line in await repository.list_statutory_lines(session, calc.id)
        }

        assert str(values["vat_computed"]["tax_amount"]) == computed
        assert str(values["vat_withheld"]["tax_amount"]) == withheld
        assert str(values["vat_payable"]["tax_amount"]) == payable
        assert str(values["vat_computed"]["base_amount"]) == net

    async def test_the_rows_come_from_the_injected_source(self, session: AsyncSession):
        owner, project = await _stat_setup(session, "inject")
        _, lines = await _save(session, owner, project, uuid.uuid4(), row_source=_source(_stat_rows(numerator=5)))
        withheld = next(line for line in lines if line.kind == "vat_withheld")
        assert (withheld.numerator, withheld.denominator) == (5, 10)
        assert service.money_as_stored(withheld.tax_amount, "EUR") == Decimal("10000.00")


@pytest.mark.asyncio
class TestStatutoryOverride:
    async def test_an_override_replaces_the_amount_and_payable_follows(self, session: AsyncSession):
        owner, project = await _stat_setup(session, "ovr")
        source_id = uuid.uuid4()
        calc, _ = await _save(session, owner, project, source_id)

        lines = await service.override_statutory(
            session,
            calc=calc,
            kind="vat_withheld",
            amount=Decimal("5000.00"),
            reason="Agreed with the client's accountant",
            user_id=owner.id,
            row_source=_source(),
        )
        values = {line.kind: service.stored_line_values(line) for line in lines}
        assert values["vat_withheld"]["overridden"] is True
        assert values["vat_withheld"]["tax_amount"] == Decimal("5000.00")
        assert values["vat_withheld"]["override_reason"] == "Agreed with the client's accountant"
        assert values["vat_withheld"]["overridden_by"] == owner.id
        assert values["vat_withheld"]["overridden_at"] is not None
        # 20000.00 computed less 5000.00 withheld.
        assert values["vat_payable"]["tax_amount"] == Decimal("15000.00")
        # The basis of the computed figure stays for display.
        assert (values["vat_withheld"]["numerator"], values["vat_withheld"]["denominator"]) == (3, 10)

    async def test_an_override_needs_a_reason(self, session: AsyncSession):
        owner, project = await _stat_setup(session, "ovrreason")
        calc, _ = await _save(session, owner, project, uuid.uuid4())
        with pytest.raises(service.StatutoryRefusal) as caught:
            await service.override_statutory(
                session, calc=calc, kind="vat_withheld", amount=Decimal("1.00"), reason="  ", user_id=owner.id
            )
        assert caught.value.code == "override_reason_required"

    async def test_payable_vat_is_never_overridden(self, session: AsyncSession):
        owner, project = await _stat_setup(session, "ovrpay")
        calc, _ = await _save(session, owner, project, uuid.uuid4())
        with pytest.raises(service.StatutoryRefusal) as caught:
            await service.override_statutory(
                session, calc=calc, kind="vat_payable", amount=Decimal("1.00"), reason="x", user_id=owner.id
            )
        assert caught.value.code == "override_not_allowed"

    async def test_an_override_finer_than_the_currency_is_refused(self, session: AsyncSession):
        owner, project = await _stat_setup(session, "ovrprec")
        calc, _ = await _save(session, owner, project, uuid.uuid4())
        with pytest.raises(service.StatutoryRefusal) as caught:
            await service.override_statutory(
                session,
                calc=calc,
                kind="vat_withheld",
                amount=Decimal("5000.005"),
                reason="x",
                user_id=owner.id,
                row_source=_source(),
            )
        assert caught.value.code == "amount_finer_than_currency"

    async def test_an_amount_for_a_tax_nobody_chose_is_refused_and_not_stored(self, session: AsyncSession):
        owner, project = await _stat_setup(session, "ovrunset")
        calc, _ = await _save(session, owner, project, uuid.uuid4(), inputs=_inputs(income_withholding=Choice("unset")))
        with pytest.raises(service.StatutoryRefusal) as caught:
            await service.override_statutory(
                session,
                calc=calc,
                kind="income_withheld",
                amount=Decimal("10.00"),
                reason="x",
                user_id=owner.id,
                row_source=_source(),
            )
        assert caught.value.code == "override_not_applied"
        lines = await repository.list_statutory_lines(session, calc.id)
        assert service.overrides_from_stored(lines) == {}

    async def test_an_override_survives_a_recalculation(self, session: AsyncSession):
        owner, project = await _stat_setup(session, "ovrkeep")
        source_id = uuid.uuid4()
        calc, _ = await _save(session, owner, project, source_id)
        await service.override_statutory(
            session,
            calc=calc,
            kind="vat_withheld",
            amount=Decimal("5000.00"),
            reason="Agreed",
            user_id=owner.id,
            row_source=_source(),
        )
        _, lines = await _save(session, owner, project, source_id, inputs=_inputs(net_amount=Decimal("200000.00")))
        values = {line.kind: service.stored_line_values(line) for line in lines}
        assert values["vat_withheld"]["tax_amount"] == Decimal("5000.00")
        assert values["vat_withheld"]["overridden"] is True
        assert values["vat_payable"]["tax_amount"] == Decimal("35000.00")

    async def test_a_change_that_strands_an_override_is_refused(self, session: AsyncSession):
        owner, project = await _stat_setup(session, "ovrstrand")
        source_id = uuid.uuid4()
        calc, _ = await _save(session, owner, project, source_id)
        await service.override_statutory(
            session,
            calc=calc,
            kind="vat_withheld",
            amount=Decimal("5000.00"),
            reason="Agreed",
            user_id=owner.id,
            row_source=_source(),
        )
        with pytest.raises(service.StatutoryRefusal) as caught:
            await _save(session, owner, project, source_id, inputs=_inputs(vat_withholding=Choice("unset")))
        assert caught.value.code == "override_not_applied"

    async def test_clearing_an_override_goes_back_to_the_computed_amount(self, session: AsyncSession):
        owner, project = await _stat_setup(session, "ovrclear")
        calc, _ = await _save(session, owner, project, uuid.uuid4())
        await service.override_statutory(
            session,
            calc=calc,
            kind="vat_withheld",
            amount=Decimal("5000.00"),
            reason="Agreed",
            user_id=owner.id,
            row_source=_source(),
        )
        lines = await service.clear_statutory_override(
            session, calc=calc, kind="vat_withheld", user_id=owner.id, row_source=_source()
        )
        values = {line.kind: service.stored_line_values(line) for line in lines}
        assert values["vat_withheld"]["overridden"] is False
        assert values["vat_withheld"]["override_amount"] is None
        assert values["vat_withheld"]["tax_amount"] == Decimal("6000.00")


@pytest.mark.asyncio
class TestStatutoryConfirmation:
    async def test_confirmation_records_who_and_when(self, session: AsyncSession):
        register_tax_withholding_rules()
        owner, project = await _stat_setup(session, "confirm")
        calc, _ = await _save(session, owner, project, uuid.uuid4())

        await service.confirm_statutory(session, calc=calc, user_id=owner.id)

        assert calc.status == "confirmed"
        assert calc.confirmed_by == owner.id
        assert calc.confirmed_at is not None
        # No unconfirmed rate was used, so nothing was acknowledged.
        assert calc.unconfirmed_rates_acknowledged_by is None

    async def test_a_held_figure_refuses_confirmation(self, session: AsyncSession):
        register_tax_withholding_rules()
        owner, project = await _stat_setup(session, "held")
        calc, _ = await _save(session, owner, project, uuid.uuid4(), inputs=_inputs(income_withholding=Choice("unset")))
        with pytest.raises(service.StatutoryRefusal) as caught:
            await service.confirm_statutory(session, calc=calc, user_id=owner.id, acknowledge_unconfirmed_rates=True)
        assert caught.value.code == "statutory_held"
        assert calc.status == "draft"
        assert "tax_withholding.statutory_line_held" in {f.rule_id for f in blocking_findings(caught.value.findings)}

    async def test_a_held_figure_refuses_confirmation_even_when_no_rule_runs(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ):
        """The guard is the service's own. A rule engine that reports nothing must not let a signature through."""
        from app.modules.tax_withholding import validators

        async def nothing(*args, **kwargs):
            return []

        monkeypatch.setattr(validators, "evaluate_record", nothing)
        owner, project = await _stat_setup(session, "norules")
        calc, _ = await _save(session, owner, project, uuid.uuid4(), inputs=_inputs(income_withholding=Choice("unset")))
        with pytest.raises(service.StatutoryRefusal) as caught:
            await service.confirm_statutory(session, calc=calc, user_id=owner.id)
        assert caught.value.code == "statutory_held"

    async def test_an_unconfirmed_rate_needs_an_explicit_acknowledgement(self, session: AsyncSession):
        register_tax_withholding_rules()
        owner, project = await _stat_setup(session, "unconf")
        calc, _ = await _save(
            session, owner, project, uuid.uuid4(), inputs=_inputs(vat_withholding=Choice("selected", code="W2"))
        )
        with pytest.raises(service.StatutoryRefusal) as caught:
            await service.confirm_statutory(session, calc=calc, user_id=owner.id)
        assert caught.value.code == "statutory_unconfirmed_rates"
        assert calc.status == "draft"

        await service.confirm_statutory(session, calc=calc, user_id=owner.id, acknowledge_unconfirmed_rates=True)
        assert calc.status == "confirmed"
        assert calc.unconfirmed_rates_acknowledged_by == owner.id
        assert calc.unconfirmed_rates_acknowledged_at is not None

    async def test_confirmed_figures_are_not_recalculated(self, session: AsyncSession):
        register_tax_withholding_rules()
        owner, project = await _stat_setup(session, "frozen")
        source_id = uuid.uuid4()
        calc, _ = await _save(session, owner, project, source_id)
        await service.confirm_statutory(session, calc=calc, user_id=owner.id)

        with pytest.raises(service.StatutoryRefusal) as caught:
            await _save(session, owner, project, source_id, inputs=_inputs(net_amount=Decimal("1.00")))
        assert caught.value.code == "statutory_confirmed"
        with pytest.raises(service.StatutoryRefusal) as caught:
            await service.override_statutory(
                session, calc=calc, kind="vat_withheld", amount=Decimal("1.00"), reason="x", user_id=owner.id
            )
        assert caught.value.code == "statutory_confirmed"

    async def test_a_later_rate_change_does_not_rewrite_a_confirmed_document(self, session: AsyncSession):
        register_tax_withholding_rules()
        owner, project = await _stat_setup(session, "ratechange")
        source_id = uuid.uuid4()
        calc, _ = await _save(session, owner, project, source_id)
        await service.confirm_statutory(session, calc=calc, user_id=owner.id)
        before = await service.as_payment_tax_result(session, source_kind="progress_claim", source_id=source_id)

        # The table now says 5/10 where the document was confirmed at 3/10.
        changed = _source(_stat_rows(numerator=5))
        with pytest.raises(service.StatutoryRefusal):
            await _save(session, owner, project, source_id, row_source=changed)
        session.expire_all()
        after = await service.as_payment_tax_result(session, source_kind="progress_claim", source_id=source_id)

        assert after == before
        assert after.vat_withheld.amount == Decimal("6000.00")
        assert (after.vat_withheld.numerator, after.vat_withheld.denominator) == (3, 10)

    async def test_reopening_needs_a_reason_and_is_audited(self, session: AsyncSession):
        from app.core.audit import AuditEntry

        register_tax_withholding_rules()
        owner, project = await _stat_setup(session, "reopen")
        source_id = uuid.uuid4()
        calc, _ = await _save(session, owner, project, source_id)
        await service.confirm_statutory(session, calc=calc, user_id=owner.id)

        with pytest.raises(service.StatutoryRefusal) as caught:
            await service.reopen_statutory(session, calc=calc, user_id=owner.id, reason="   ")
        assert caught.value.code == "reopen_reason_required"
        assert calc.status == "confirmed"

        await service.reopen_statutory(session, calc=calc, user_id=owner.id, reason="Net amount was corrected")
        assert calc.status == "draft"
        assert calc.confirmed_by is None
        assert calc.reopened_by == owner.id
        assert calc.reopen_reason == "Net amount was corrected"

        entries = (
            (
                await session.execute(
                    select(AuditEntry).where(
                        AuditEntry.entity_type == service.STATUTORY_ENTITY,
                        AuditEntry.entity_id == str(calc.id),
                        AuditEntry.action == "reopen",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(entries) == 1
        assert entries[0].details["reason"] == "Net amount was corrected"
        assert entries[0].details["confirmed_by"] == str(owner.id)
        assert entries[0].user_id == owner.id

        # Reopened, the document picks up the table as it stands now.
        _, lines = await _save(session, owner, project, source_id, row_source=_source(_stat_rows(numerator=5)))
        withheld = next(line for line in lines if line.kind == "vat_withheld")
        assert service.money_as_stored(withheld.tax_amount, "EUR") == Decimal("10000.00")

    async def test_a_draft_cannot_be_reopened(self, session: AsyncSession):
        owner, project = await _stat_setup(session, "reopendraft")
        calc, _ = await _save(session, owner, project, uuid.uuid4())
        with pytest.raises(service.StatutoryRefusal) as caught:
            await service.reopen_statutory(session, calc=calc, user_id=owner.id, reason="x")
        assert caught.value.code == "statutory_already_draft"

    async def test_void_takes_the_figures_out_of_use_and_keeps_the_rows(self, session: AsyncSession):
        owner, project = await _stat_setup(session, "void")
        source_id = uuid.uuid4()
        calc, _ = await _save(session, owner, project, source_id)

        with pytest.raises(service.StatutoryRefusal):
            await service.void_statutory(session, calc=calc, user_id=owner.id, reason="")
        lines = await service.void_statutory(session, calc=calc, user_id=owner.id, reason="Claim withdrawn")

        assert calc.status == "void"
        assert calc.void_reason == "Claim withdrawn"
        assert len(lines) == 5
        assert await service.as_payment_tax_result(session, source_kind="progress_claim", source_id=source_id) is None
        with pytest.raises(service.StatutoryRefusal) as caught:
            await _save(session, owner, project, source_id)
        assert caught.value.code == "statutory_void"

        await service.reopen_statutory(session, calc=calc, user_id=owner.id, reason="Claim reinstated")
        assert calc.status == "draft"
        assert calc.voided_by is None


@pytest.mark.asyncio
class TestCertificateTaxProvider:
    async def test_nothing_stored_answers_none(self, session: AsyncSession):
        assert await service.certificate_tax_provider(session, "progress_claim", uuid.uuid4()) is None

    async def test_an_unknown_source_kind_answers_none(self, session: AsyncSession):
        assert await service.certificate_tax_provider(session, "purchase_order", uuid.uuid4()) is None

    async def test_a_draft_is_answered_from_its_rows(self, session: AsyncSession):
        owner, project = await _stat_setup(session, "provider")
        source_id = uuid.uuid4()
        await _save(session, owner, project, source_id)
        answer = await service.certificate_tax_provider(session, "progress_claim", str(source_id))
        assert answer.result == compute_payment_taxes(service.build_tax_input(_inputs()), _stat_rows())
        # And the header the figures were stored under, which is what lets a
        # certificate notice that its own amount has moved since.
        assert answer.status == "draft"
        assert answer.net_amount == _inputs().net_amount
        assert answer.vat_rate_pct == _inputs().vat_rate_pct
        assert answer.document_date == _inputs().document_date
        assert answer.choices["vat_withholding"] == _inputs().vat_withholding

    async def test_a_document_nobody_owns_cannot_be_filed(self, session: AsyncSession):
        owner, project = await _stat_setup(session, "unowned")
        source_id = uuid.uuid4()
        # No owner recorded for this id: the owning module does not know it.
        with pytest.raises(service.StatutoryRefusal) as caught:
            await service.upsert_statutory(
                session,
                project_id=project.id,
                source_kind="progress_claim",
                source_id=source_id,
                inputs=_inputs(),
                direction="borne_by_us",
                user_id=owner.id,
                row_source=_source(),
            )
        assert (caught.value.http_status, caught.value.code) == (404, "statutory_not_found")
        assert await service.get_statutory(session, source_kind="progress_claim", source_id=source_id) is None

    async def test_a_kind_with_no_owner_module_cannot_be_filed(self, session: AsyncSession):
        owner, project = await _stat_setup(session, "ownerless")
        source_id = uuid.uuid4()
        source_owners.unregister_source_owner("invoice")
        with pytest.raises(service.StatutoryRefusal) as caught:
            await _save(session, owner, project, source_id, source_kind="invoice")
        assert (caught.value.http_status, caught.value.code) == (404, "statutory_not_found")

    async def test_the_registry_receives_the_provider(self, session: AsyncSession):
        certificate_taxes = pytest.importorskip("app.modules.contracts.certificate_taxes")
        owner, project = await _stat_setup(session, "registry")
        source_id = uuid.uuid4()
        await _save(session, owner, project, source_id)
        try:
            assert service.register_certificate_tax_provider() is True
            collected = await certificate_taxes.collect_certificate_taxes(session, "progress_claim", source_id)
        finally:
            certificate_taxes.unregister_certificate_tax_provider()
        assert collected is not None
        assert collected.vat_withheld.amount == Decimal("6000.00")


class TestCertificateTaxProviderRegistration:
    def test_an_install_without_the_registry_still_starts(self):
        def absent(name: str):
            raise ModuleNotFoundError(f"No module named '{name}'", name=name)

        assert service.register_certificate_tax_provider(importer=absent) is False

    def test_a_broken_import_inside_the_registry_is_not_read_as_absence(self):
        def broken(name: str):
            raise ModuleNotFoundError("No module named 'something_else'", name="something_else")

        with pytest.raises(ModuleNotFoundError):
            service.register_certificate_tax_provider(importer=broken)


# ── Statutory tax lines: validation rules ────────────────────────────────────


def _stat_line(kind: str, **changes) -> dict:
    line = {
        "kind": kind,
        "calc_status": "value",
        "tax_amount": Decimal("0.00"),
        "base_amount": None,
        "rate_pct": None,
        "numerator": None,
        "denominator": None,
        "code": "",
        "currency_code": "EUR",
        "legal_reference": "",
        "source_url": "",
        "rate_effective_from": None,
        "rate_effective_to": None,
        "review_status": "",
        "overridden": False,
        "reason_key": "",
        "reason_params": {},
    }
    line.update(changes)
    return line


def _stat_lines(**by_kind) -> list[dict]:
    """Five consistent lines: 20000.00 computed, 6000.00 withheld, 14000.00 payable."""
    lines = {
        "vat_computed": _stat_line("vat_computed", tax_amount=Decimal("20000.00")),
        "vat_withheld": _stat_line(
            "vat_withheld",
            tax_amount=Decimal("6000.00"),
            code="W1",
            review_status="confirmed",
            rate_effective_from=date(2020, 1, 1),
        ),
        "vat_payable": _stat_line("vat_payable", tax_amount=Decimal("14000.00")),
        "income_withheld": _stat_line("income_withheld", tax_amount=Decimal("4000.00")),
        "stamp_duty": _stat_line("stamp_duty", calc_status="not_applicable", tax_amount=None),
    }
    for kind, changes in by_kind.items():
        lines[kind].update(changes)
    return list(lines.values())


async def _stat_findings(lines: list[dict], *, action: str = "save", acknowledged: bool = False):
    register_tax_withholding_rules()
    return await evaluate_record(
        service.statutory_payload(
            lines, currency_code="EUR", document_date=DOC_DATE, action=action, acknowledged=acknowledged
        )
    )


def _severity_of(findings, rule_id: str) -> list[str]:
    return [str(finding.severity) for finding in findings if finding.rule_id == rule_id]


@pytest.mark.asyncio
class TestStatutoryRules:
    async def test_consistent_figures_raise_nothing(self):
        assert await _stat_findings(_stat_lines(), action="confirm") == []

    async def test_an_unconfirmed_rate_warns_on_a_draft_and_blocks_a_confirmation(self):
        lines = _stat_lines(vat_withheld={"review_status": "unconfirmed"})
        rule = "tax_withholding.statutory_rate_unconfirmed"
        assert _severity_of(await _stat_findings(lines), rule) == ["warning"]
        assert _severity_of(await _stat_findings(lines, action="confirm"), rule) == ["error"]
        assert _severity_of(await _stat_findings(lines, action="confirm", acknowledged=True), rule) == ["warning"]

    async def test_one_unconfirmed_row_is_reported_once(self):
        lines = _stat_lines(
            vat_withheld={"review_status": "unconfirmed"},
            vat_payable={"review_status": "unconfirmed", "code": "W1"},
        )
        assert len(_severity_of(await _stat_findings(lines), "tax_withholding.statutory_rate_unconfirmed")) == 1

    async def test_a_held_figure_warns_on_a_draft_and_blocks_a_confirmation(self):
        lines = _stat_lines(income_withheld={"calc_status": "held", "tax_amount": None, "reason_key": "not_chosen"})
        rule = "tax_withholding.statutory_line_held"
        assert _severity_of(await _stat_findings(lines), rule) == ["warning"]
        assert _severity_of(await _stat_findings(lines, action="confirm"), rule) == ["error"]

    async def test_vat_that_does_not_add_up_is_an_error(self):
        findings = await _stat_findings(_stat_lines(vat_payable={"tax_amount": Decimal("14000.01")}))
        assert "tax_withholding.statutory_vat_identity" in {f.rule_id for f in blocking_findings(findings)}

    async def test_the_identity_is_not_tested_against_a_held_figure(self):
        lines = _stat_lines(
            vat_withheld={"calc_status": "held", "tax_amount": None, "reason_key": "not_chosen"},
            vat_payable={"calc_status": "held", "tax_amount": None, "reason_key": "not_chosen"},
        )
        assert "tax_withholding.statutory_vat_identity" not in _ids(await _stat_findings(lines))

    async def test_nothing_withheld_means_the_whole_vat_is_payable(self):
        not_withheld = {"calc_status": "not_applicable", "tax_amount": None}
        agreeing = _stat_lines(vat_withheld=not_withheld, vat_payable={"tax_amount": Decimal("20000.00")})
        differing = _stat_lines(vat_withheld=not_withheld, vat_payable={"tax_amount": Decimal("14000.00")})
        assert "tax_withholding.statutory_vat_identity" not in _ids(await _stat_findings(agreeing))
        assert "tax_withholding.statutory_vat_identity" in _ids(await _stat_findings(differing))

    async def test_a_value_with_no_amount_fails_the_identity_instead_of_reading_as_zero(self):
        findings = await _stat_findings(_stat_lines(vat_withheld={"tax_amount": None}))
        assert "tax_withholding.statutory_vat_identity" in {f.rule_id for f in blocking_findings(findings)}

    async def test_an_override_without_a_reason_is_an_error(self):
        lines = _stat_lines(income_withheld={"overridden": True, "override_reason": ""})
        findings = await _stat_findings(lines)
        assert "tax_withholding.statutory_override_reason" in {f.rule_id for f in blocking_findings(findings)}
        explained = _stat_lines(income_withheld={"overridden": True, "override_reason": "Agreed"})
        assert "tax_withholding.statutory_override_reason" not in _ids(await _stat_findings(explained))

    async def test_a_rate_row_not_in_force_on_the_document_date_is_an_error(self):
        rule = "tax_withholding.statutory_rate_not_effective"
        ended = _stat_lines(vat_withheld={"rate_effective_to": DOC_DATE - timedelta(days=1)})
        not_started = _stat_lines(vat_withheld={"rate_effective_from": DOC_DATE + timedelta(days=1)})
        last_day = _stat_lines(vat_withheld={"rate_effective_to": DOC_DATE})
        assert rule in {f.rule_id for f in blocking_findings(await _stat_findings(ended))}
        assert rule in {f.rule_id for f in blocking_findings(await _stat_findings(not_started))}
        assert rule not in _ids(await _stat_findings(last_day))

    @pytest.mark.parametrize("reason_key", ["threshold_currency_mismatch", "threshold_needs_year_total"])
    async def test_a_threshold_that_could_not_be_judged_is_a_warning(self, reason_key):
        lines = _stat_lines(income_withheld={"calc_status": "held", "tax_amount": None, "reason_key": reason_key})
        findings = await _stat_findings(lines)
        assert _severity_of(findings, "tax_withholding.statutory_threshold_unevaluated") == ["warning"]

    async def test_the_rules_ignore_the_other_record_types(self):
        findings = await _findings(_deduction_request(), regime=_uk_regime(), party_status=_standing())
        assert not [f for f in findings if f.rule_id.startswith("tax_withholding.statutory_")]

    async def test_a_yearly_threshold_from_the_calculation_reaches_the_rule(self):
        """End to end on one case: the reason key the calculation emits is one the rule knows."""
        inputs = _inputs(income_withholding=Choice("selected", code="I2"))
        rows = _stat_rows()
        values = service.result_line_values(service.preview_statutory(inputs, rows), inputs, rows)
        findings = await _stat_findings(values)
        assert "tax_withholding.statutory_threshold_unevaluated" in _ids(findings)
        assert "tax_withholding.statutory_line_held" in _ids(findings)


def test_the_statutory_permissions_separate_view_edit_and_confirm():
    from app.core.permissions import Role, permission_registry

    register_tax_withholding_permissions()
    has = permission_registry.role_has_permission
    assert has(Role.VIEWER, "tax_withholding.statutory_view") is True
    assert has(Role.VIEWER, "tax_withholding.statutory_edit") is False
    assert has(Role.EDITOR, "tax_withholding.statutory_edit") is True
    # Confirming freezes what a certificate and an e-invoice print.
    assert has(Role.EDITOR, "tax_withholding.statutory_confirm") is False
    assert has(Role.MANAGER, "tax_withholding.statutory_confirm") is True


def test_the_statutory_routes_ask_for_the_permission_their_verb_implies():
    from app.modules.tax_withholding.router import router

    asked: dict[tuple[str, str], str] = {}
    for route in router.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/statutory/"):
            continue
        keys = [
            getattr(getattr(dep, "dependency", None), "permission", None)
            for dep in (getattr(route, "dependencies", []) or [])
        ]
        for method in route.methods:
            asked[(method, path)] = next(key for key in keys if isinstance(key, str))

    stem = "/statutory/{source_kind}/{source_id}"
    assert asked == {
        ("POST", "/statutory/preview"): "tax_withholding.statutory_view",
        ("GET", "/statutory/categories"): "tax_withholding.statutory_view",
        ("GET", stem): "tax_withholding.statutory_view",
        ("PUT", stem): "tax_withholding.statutory_edit",
        ("POST", f"{stem}/override"): "tax_withholding.statutory_edit",
        ("DELETE", f"{stem}/override/{{kind}}"): "tax_withholding.statutory_edit",
        ("POST", f"{stem}/confirm"): "tax_withholding.statutory_confirm",
        ("POST", f"{stem}/reopen"): "tax_withholding.statutory_confirm",
        ("POST", f"{stem}/void"): "tax_withholding.statutory_confirm",
    }


def test_the_statutory_tables_are_named_and_keyed_as_designed():
    assert StatutoryTaxCalc.__tablename__ == "oe_tax_withholding_statutory_calc"
    assert StatutoryTaxLine.__tablename__ == "oe_tax_withholding_statutory_line"

    def unique_keys(model) -> set[tuple[str, ...]]:
        return {
            tuple(column.name for column in constraint.columns)
            for constraint in model.__table__.constraints
            if isinstance(constraint, UniqueConstraint)
        }

    assert ("source_kind", "source_id") in unique_keys(StatutoryTaxCalc)
    assert ("source_kind", "source_id", "kind") in unique_keys(StatutoryTaxLine)
    # The source document lives in another module: indexed, never a foreign key.
    for model in (StatutoryTaxCalc, StatutoryTaxLine):
        column = model.__table__.c.source_id
        assert not column.foreign_keys
        assert any(list(index.columns)[0].name == "source_id" for index in model.__table__.indexes)


def test_statutory_amounts_are_nullable_and_have_no_default():
    """A held figure is NULL. A default of zero would be the fallback this table must not have."""
    for name in ("tax_amount", "base_amount", "rate_pct", "override_amount"):
        column = StatutoryTaxLine.__table__.c[name]
        assert column.nullable is True, name
        assert column.default is None and column.server_default is None, name
    for name in ("vat_rate_pct", "work_value_incl_vat", "buyer_is_designated"):
        column = StatutoryTaxCalc.__table__.c[name]
        assert column.nullable is True, name
        assert column.default is None and column.server_default is None, name
    assert StatutoryTaxCalc.__table__.c.net_amount.server_default is None


def test_the_statutory_index_names_fit_postgresql():
    from app.core.pg_optimizations import _desired_indexes

    names: set[str] = set()
    for model in (StatutoryTaxCalc, StatutoryTaxLine):
        table = model.__table__
        names |= {index.name for index in table.indexes}
        names |= {index.name for index in _desired_indexes(table)}
        names |= {constraint.name for constraint in table.constraints if isinstance(constraint.name, str)}
    assert [name for name in names if len(name) > 63] == []
