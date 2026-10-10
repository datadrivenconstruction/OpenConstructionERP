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

This file lives in ``tests/unit`` and needs a named step in
``.github/workflows/ci-postgres.yml``. ``tests/integration`` runs in no
blocking lane, so a guard placed there would pass review and gate nothing.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.tax_withholding import repository, schemas, service
from app.modules.tax_withholding.data import REVERSE_CHARGE_RULES, WITHHOLDING_REGIMES, regime_by_scheme
from app.modules.tax_withholding.models import (
    PartyTaxStatus,
    ReverseChargeDetermination,
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

    def test_turkish_stopaj_is_taken_on_the_hakedis_net_of_kdv(self):
        # GVK art. 94/3 and KVK art. 15(1)(a): withholding on progress
        # payments for construction spanning more than one calendar year.
        regime = regime_by_scheme("TR_YILLARA_YAYGIN_INSAAT_STOPAJ")
        assert regime is not None
        assert regime["country_code"] == "TR"
        assert regime["currency_code"] == "TRY"
        assert regime["vat_excluded"] is True
        assert regime["materials_excluded"] is False
        rates = {band["code"]: Decimal(band["rate_pct"]) for band in regime["bands"]}
        assert rates == {"RAIL_AND_SHIP": Decimal("1"), "STANDARD": Decimal("5")}
        assert regime["default_band_code"] == "STANDARD"
        # The band follows the kind of work, not a verification of the party.
        assert not any(band["requires_verification"] for band in regime["bands"])

    def test_turkish_vat_withholding_is_not_shipped_as_a_reverse_charge(self):
        # KDV tevkifat withholds four tenths of the VAT and the invoice still
        # shows VAT, which is the opposite of what a reverse-charge rule
        # promises. It has no row until the module can express it.
        assert not any(rule["country_code"] == "TR" for rule in REVERSE_CHARGE_RULES)

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
    for model in (WithholdingRegime, PartyTaxStatus, WithholdingDeduction, ReverseChargeDetermination):
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
