# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The shipped statutory payment regimes, and an idempotent seeder for them.

This is where the law is written down. Every number here is a statutory default
and every entry names the sections it came from, because the one question a
quantity surveyor will ask about a computed date is which provision produced
it. Nothing here is a house rule.

Two modelling decisions run through the whole table and are worth stating once
rather than once per regime.

**The due date and the final date for payment are different dates, and only the
UK Act genuinely splits them.** The UK Act makes a sum fall due, then gives a
further period before it must be paid, and the notice deadlines hang off both.
The security-of-payment statutes have one date: the progress payment "becomes
due and payable" a set number of days after the claim. Those regimes are
therefore written with the due date on the application date and the statutory
period as the final date for payment, which is what the statute actually
imposes - a last day to pay - and which keeps the final date after the due date
in every regime shipped.

**A null deadline means the statute is silent, which is not the same as zero.**
Malaysia leaves the payment period to the contract, and the EU Late Payment
Directive and the German regimes have no notice sequence at all. The rules skip
what the regime does not set rather than treating it as an instant deadline.

Seed data lives here and not in a migration on purpose: a migration is a
schema change that runs once per deployment, and this table is content that
will be corrected as statutes are amended.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


#: A country_code declares itself here when PAYMENT_REGIMES has no row for it
#: and the reason is worth naming rather than left as a bare gap.
#:
#: Three values, not the two app.modules.property_dev.tax_engine uses for an
#: absent VAT block, and the difference is what each absence is a claim
#: about. VAT absence is a claim about a rate: a rate is a percentage
#: regardless of which country charges it, so NOT_MODELLED there is closable
#: by writing a row, with no change to the table's shape. A prompt payment
#: regime is a claim about the shape of a law. NO_STATUTE and NOT_MODELLED
#: are the same two ideas carried over, no such law, or a law we have not
#: yet reduced to a row, and both are closable the same way, by writing a
#: row once the research is done. DIFFERENT_SHAPE is not: Brazil Lei
#: 14.133/2021 art. 141 obliges the public buyer to pay invoices in the order
#: they were registered, which is an ordering rule, not a deadline measured
#: in days from an event. No amount of research turns "pay in registration
#: order" into a days-to-pay figure, because elapsed time since an event is
#: not the thing the statute regulates. That is a fact about what the law is,
#: not about how much of it we have modelled, and it is why this set carries
#: a third value the tax table does not: two of these three are gaps this
#: registry can close by adding a row, and one names a country whose statute
#: this registry row shape cannot express at all. Collapsing the three into
#: the tax engine two would erase exactly that distinction.
NO_REGIME_NO_STATUTE = "no_statute"
NO_REGIME_NOT_MODELLED = "not_modelled"
NO_REGIME_DIFFERENT_SHAPE = "different_shape"

#: All three, and only these three. _validate_no_regime_reasons refuses
#: anything outside this set at import time.
NO_REGIME_VALUES = frozenset({NO_REGIME_NO_STATUTE, NO_REGIME_NOT_MODELLED, NO_REGIME_DIFFERENT_SHAPE})

#: country_code to one of NO_REGIME_VALUES, for a country researched to a
#: category-assignable degree that turned up no row. Most of the world is
#: simply absent from this dict, which is not a violation: nobody has looked,
#: and the dict does not claim otherwise. A country present here has been
#: looked at and named; that is the entire difference between an entry and a
#: silent gap, and no_regime_reason() below is built to preserve it.
NO_REGIME_REASONS: dict[str, str] = {
    "BR": NO_REGIME_DIFFERENT_SHAPE,
}

#: country_code under active research whose search has not yet produced a
#: result category-assignable enough for NO_REGIME_REASONS. Deliberately not
#: a NO_REGIME_* value and deliberately not silence either: a wrong-instrument
#: search is not evidence of absence, so a country here earns no value rather
#: than a guessed one, but country_coverage.py can still say "held" instead of
#: an unqualified MISSING indistinguishable from a country nobody has looked
#: at yet.
#:
#: Empty today. CN and RU were held here until the search was run against the
#: right instrument in each case - the State Council SME payment regulation
#: rather than the Civil Code contract chapter, and the public procurement law
#: rather than a construction-specific payment act, neither of which exists in
#: the shape the earlier search assumed. Both now have rows of their own. The
#: set stays because the state it names is real and the next country to reach
#: it should land here rather than in silence.
NO_REGIME_HELD: frozenset[str] = frozenset()


PAYMENT_REGIMES: tuple[dict[str, Any], ...] = (
    {
        "code": "uk_hgcra",
        "jurisdiction": "United Kingdom",
        "country_code": "GB",
        "statute": "Housing Grants, Construction and Regeneration Act 1996",
        "statute_reference": (
            "sections 110, 110A, 110B and 111, as amended by the Local Democracy, Economic Development "
            "and Construction Act 2009; default periods from the Scheme for Construction Contracts"
        ),
        "due_date_basis": "period_end",
        "due_date_days": 7,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "due_date",
        "payment_notice_days": 5,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "due_date",
        "final_date_days": 17,
        "final_date_day_basis": "calendar",
        "pay_less_days": 7,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "applied_sum_becomes_notified_sum",
        "interest_basis": "reference_rate_plus_margin",
        "interest_reference_rate": "Bank of England base rate",
        "interest_margin_percent": Decimal("8.000"),
        "interest_fixed_percent": None,
        "interest_statute": "Late Payment of Commercial Debts (Interest) Act 1998",
        "notes": (
            "The periods are the Scheme's defaults and apply where the contract does not provide "
            "compliant ones; a contract may set shorter periods but may not remove the sequence. Under "
            "section 111 the notified sum must be paid in full by the final date unless a valid pay-less "
            "notice was served in time, and where the payer served no payment notice the sum the payee "
            "applied for is the notified sum. Section 110B lets the payee serve its own default payment "
            "notice when the payer missed the deadline, which postpones the final date for payment by the "
            "days between the missed deadline and that notice."
        ),
    },
    {
        "code": "ie_cca_2013",
        "jurisdiction": "Ireland",
        "country_code": "IE",
        "statute": "Construction Contracts Act 2013",
        "statute_reference": "section 4 and the Schedule",
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": 21,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 30,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "applied_sum_becomes_notified_sum",
        "interest_basis": "reference_rate_plus_margin",
        "interest_reference_rate": "European Central Bank main refinancing rate",
        "interest_margin_percent": Decimal("8.000"),
        "interest_fixed_percent": None,
        "interest_statute": "European Communities (Late Payment in Commercial Transactions) Regulations 2012",
        "notes": (
            "The Act does not split a due date from a final date the way the UK Act does, so the payment "
            "claim date is taken as the due date and the Act's thirty-day limit as the final date for "
            "payment. The response to a payment claim notice must state the amount proposed to be paid "
            "and the reason for any difference from the amount claimed; there is no separate pay-less "
            "notice. Unpaid amounts carry a right to suspend."
        ),
    },
    {
        "code": "au_nsw_sopa",
        "jurisdiction": "New South Wales, Australia",
        "country_code": "AU",
        "statute": "Building and Construction Industry Security of Payment Act 1999 (NSW)",
        "statute_reference": "sections 11, 13, 14 and 17",
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": 10,
        "payment_notice_day_basis": "business",
        "final_date_basis": "application_date",
        "final_date_days": 15,
        "final_date_day_basis": "business",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "applied_sum_becomes_notified_sum",
        "interest_basis": "prescribed_rate",
        "interest_reference_rate": "section 101 of the Civil Procedure Act 2005 (NSW)",
        "interest_margin_percent": None,
        "interest_fixed_percent": None,
        "interest_statute": "Building and Construction Industry Security of Payment Act 1999 (NSW), section 11(2)",
        "notes": (
            "The response to a payment claim is a payment schedule. Fifteen business days is the limit "
            "for a head contract and twenty for a subcontract; a contract may set a shorter period but "
            "not a longer one. Business days under this Act exclude 27 to 31 December as well as weekends "
            "and public holidays, so supply that calendar to reproduce the statutory dates exactly. Where "
            "no payment schedule is served in time the respondent becomes liable to pay the claimed "
            "amount on the due date. Interest runs at the greater of the prescribed rate and the rate the "
            "contract specifies."
        ),
    },
    {
        "code": "au_qld_bif",
        "jurisdiction": "Queensland, Australia",
        "country_code": "AU",
        "statute": "Building Industry Fairness (Security of Payment) Act 2017 (Qld)",
        "statute_reference": "sections 68, 75, 76 and 90",
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": 15,
        "payment_notice_day_basis": "business",
        "final_date_basis": "application_date",
        "final_date_days": 25,
        "final_date_day_basis": "business",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "applied_sum_becomes_notified_sum",
        "interest_basis": "prescribed_rate",
        "interest_reference_rate": "section 67P of the Queensland Building and Construction Commission Act 1991",
        "interest_margin_percent": None,
        "interest_fixed_percent": Decimal("10.000"),
        "interest_statute": "Queensland Building and Construction Commission Act 1991, section 67P",
        "notes": (
            "The response to a payment claim is a payment schedule. Twenty-five business days is the "
            "limit for a head contract and fifteen for a subcontract. Where no payment schedule is served "
            "in time the respondent becomes liable to pay the claimed amount on the due date. Interest "
            "runs at the greater of ten per cent a year and the prescribed rate."
        ),
    },
    {
        "code": "nz_cca_2002",
        "jurisdiction": "New Zealand",
        "country_code": "NZ",
        "statute": "Construction Contracts Act 2002",
        "statute_reference": "sections 18, 20, 21, 22 and 23",
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": 20,
        "payment_notice_day_basis": "business",
        "final_date_basis": "application_date",
        "final_date_days": 20,
        "final_date_day_basis": "business",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "applied_sum_becomes_notified_sum",
        "interest_basis": "contract",
        "interest_reference_rate": "",
        "interest_margin_percent": None,
        "interest_fixed_percent": None,
        "interest_statute": "",
        "notes": (
            "The response to a payment claim is a payment schedule. Both default periods run twenty "
            "working days from the payment claim, so on the default terms the payer must serve its "
            "schedule on the day payment falls due at the latest; a contract may set shorter periods. "
            "Working days under this Act exclude 24 December to 5 January as well as weekends and public "
            "holidays, so supply that calendar to reproduce the statutory dates exactly. Where no payment "
            "schedule is served the payer becomes liable for the claimed amount and it is recoverable as "
            "a debt. The Act sets no interest rate, so the contract rate applies."
        ),
    },
    {
        "code": "sg_sopa",
        "jurisdiction": "Singapore",
        "country_code": "SG",
        "statute": "Building and Construction Industry Security of Payment Act 2004",
        "statute_reference": "sections 8, 11 and 15",
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": 21,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 35,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "evidential_bar",
        "interest_basis": "contract",
        "interest_reference_rate": "",
        "interest_margin_percent": None,
        "interest_fixed_percent": None,
        "interest_statute": "",
        "notes": (
            "The response to a payment claim is a payment response, due twenty-one days after the claim "
            "for a construction contract and seven days for a supply contract. Payment falls due fourteen "
            "days after the payment response was required, which is where the thirty-five days comes "
            "from, unless the contract sets an earlier date. Failing to serve a payment response does not "
            "concede the claim: it bars the respondent from raising at adjudication any reason it did not "
            "put in the response."
        ),
    },
    {
        "code": "my_cipaa",
        "jurisdiction": "Malaysia",
        "country_code": "MY",
        "statute": "Construction Industry Payment and Adjudication Act 2012",
        "statute_reference": "sections 5, 6 and 36",
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": 10,
        "payment_notice_day_basis": "business",
        "final_date_basis": "application_date",
        "final_date_days": None,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "deemed_dispute",
        "interest_basis": "contract",
        "interest_reference_rate": "",
        "interest_margin_percent": None,
        "interest_fixed_percent": None,
        "interest_statute": "",
        "notes": (
            "The response to a payment claim is a payment response, due ten working days after the claim. "
            "The Act sets no payment period, so the final date for payment comes from the contract and "
            "has to be entered on the application; section 36 voids a clause making payment conditional "
            "on the payer itself being paid. Failing to respond within the ten working days is a deemed "
            "dispute of the whole claim rather than an admission of it, so the claimant's next step is "
            "adjudication and not a debt claim."
        ),
    },
    {
        "code": "eu_late_payment",
        "jurisdiction": "European Union",
        "country_code": "EU",
        "statute": "Directive 2011/7/EU on combating late payment in commercial transactions",
        "statute_reference": "articles 2, 3 and 4",
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": None,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 30,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "reference_rate_plus_margin",
        "interest_reference_rate": "European Central Bank reference rate",
        "interest_margin_percent": Decimal("8.000"),
        "interest_fixed_percent": None,
        "interest_statute": "Directive 2011/7/EU, article 2(6)",
        "notes": (
            "An interest basis rather than a notice regime: the Directive sets a payment period and the "
            "interest that runs when it is missed, and leaves notices to national law, so this regime has "
            "no payment notice and missing one has no consequence under it. Thirty days is the default "
            "period between undertakings; it may be extended to sixty by express agreement and beyond "
            "that only where the term is not grossly unfair to the creditor. Use this regime where a "
            "member state has no construction-specific payment statute, and the national regime where it "
            "has one."
        ),
    },
    # The three German regimes below carry the statutory deadlines of § 16
    # VOB/B (2016) and §§ 632a, 641, 650g BGB. The German contract-type and
    # invoice-template vocabulary (VOB_B_EINHEITSPREIS, ABSCHLAGSRECHNUNG,
    # SCHLUSSRECHNUNG, "per § 632a BGB / § 16 VOB/B") lives in
    # ``app.modules.dach_pack.config``; that module carries no deadline
    # arithmetic, so the numbers are written down here, sourced from the
    # provisions each entry names, and the wording follows dach_pack's. VOB/B
    # gives an Abschlagsrechnung and a Schlussrechnung two different clocks (21
    # and 30 days), and a regime in this table is one clock, so they are two
    # entries rather than one entry with a footnote a calculation cannot read.
    {
        "code": "de_vob_b_abschlag",
        "jurisdiction": "Germany",
        "country_code": "DE",
        "statute": "VOB/B § 16 Abs. 1 (Abschlagszahlungen)",
        "statute_reference": (
            "§ 16 Abs. 1 Nr. 3 VOB/B (2016); Nachfrist and default interest under § 16 Abs. 5 Nr. 3 "
            "VOB/B with § 288 Abs. 2 BGB"
        ),
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "due_date",
        "payment_notice_days": None,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 21,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "reference_rate_plus_margin",
        "interest_reference_rate": "Deutsche Bundesbank base rate (Basiszinssatz, § 247 BGB)",
        "interest_margin_percent": Decimal("9.000"),
        "interest_fixed_percent": None,
        "interest_statute": "§ 288 Abs. 2 BGB, applied by § 16 Abs. 5 Nr. 3 VOB/B",
        "notes": (
            "The clock for an interim payment invoice (Abschlagsrechnung) under a VOB/B contract. The claim "
            "falls due within 21 calendar days of the client receiving the verifiable statement of work "
            "(Zugang der Aufstellung), so enter that date of receipt as the application date; following the "
            "convention used for the other single-date regimes, the application date is taken as the due "
            "date and the 21-day limit as the final date for payment. VOB/B has no statutory payment or "
            "pay-less notice: an objection to the statement is informal and silence has no preclusive "
            "effect. If the client has not paid when the claim is due, § 16 Abs. 5 Nr. 3 VOB/B lets the "
            "contractor set a reasonable grace period (angemessene Nachfrist - two weeks is the customary "
            "yardstick), from whose expiry default interest under § 288 Abs. 2 BGB runs and the "
            "contractor may suspend the works until payment; at the latest, the client is in default 30 "
            "days after receipt of the invoice or statement. This module has no grace-period step, so the "
            "interest warning runs from the final date for payment and the Nachfrist has to be minded by "
            "hand."
        ),
    },
    {
        "code": "de_vob_b_schluss",
        "jurisdiction": "Germany",
        "country_code": "DE",
        "statute": "VOB/B § 16 Abs. 3 (Schlusszahlung)",
        "statute_reference": (
            "§ 16 Abs. 3 Nr. 1 VOB/B (2016); reservation of claims under § 16 Abs. 3 Nr. 2 and Nr. 5 "
            "VOB/B; Nachfrist and default interest under § 16 Abs. 5 Nr. 3 VOB/B with § 288 Abs. 2 BGB"
        ),
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "due_date",
        "payment_notice_days": None,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 30,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "reference_rate_plus_margin",
        "interest_reference_rate": "Deutsche Bundesbank base rate (Basiszinssatz, § 247 BGB)",
        "interest_margin_percent": Decimal("9.000"),
        "interest_fixed_percent": None,
        "interest_statute": "§ 288 Abs. 2 BGB, applied by § 16 Abs. 5 Nr. 3 VOB/B",
        "notes": (
            "The clock for the final invoice (Schlussrechnung) under a VOB/B contract. The final payment "
            "falls due promptly after examination and determination of the invoice, and at the latest "
            "within 30 calendar days of the client receiving it, so enter the date of receipt (Zugang der "
            "Schlussrechnung) as the application date. The period extends to at most 60 days only where "
            "that is objectively justified by the particular nature or features of the agreement and was "
            "expressly agreed (§ 16 Abs. 3 Nr. 1 sentence 2 VOB/B); record such a contract by stating "
            "the agreed final date on the application, which marks the dates as overridden. Accepting the "
            "final payment without reservation excludes further claims where the client gave written "
            "notice of the payment and of that preclusive effect; the contractor's reservation (Vorbehalt) "
            "must be declared within 28 calendar days of that notice and substantiated within a further 28 "
            "(§ 16 Abs. 3 Nr. 2 and Nr. 5 VOB/B) - a payee-side sequence this clock does not compute. "
            "Late payment carries the same Nachfrist and interest mechanics as the interim regime."
        ),
    },
    {
        "code": "de_bgb_632a",
        "jurisdiction": "Germany",
        "country_code": "DE",
        "statute": "BGB § 632a (Abschlagszahlungen)",
        "statute_reference": (
            "§ 632a Abs. 1 BGB; default without a reminder under § 286 Abs. 3 BGB; interest under "
            "§ 288 Abs. 2 BGB; final payment due on acceptance with a verifiable final invoice under "
            "§ 641 Abs. 1 and § 650g Abs. 4 BGB"
        ),
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "due_date",
        "payment_notice_days": None,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 30,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "reference_rate_plus_margin",
        "interest_reference_rate": "Deutsche Bundesbank base rate (Basiszinssatz, § 247 BGB)",
        "interest_margin_percent": Decimal("9.000"),
        "interest_fixed_percent": None,
        "interest_statute": "§ 288 Abs. 2 BGB",
        "notes": (
            "The clock for interim payments under a plain BGB construction contract, where the parties did "
            "not agree the VOB/B. § 632a Abs. 1 BGB entitles the contractor to interim payments in the "
            "amount of the value of the work performed and owed. The BGB sets no payment period - the "
            "claim is due on demand with a verifiable statement (§ 271 BGB) - so the 30 days written "
            "here are § 286 Abs. 3 BGB: the client is in default at the latest 30 days after receiving "
            "the invoice, without any reminder, and that outer limit is taken as the final date for "
            "payment. Between businesses it applies of itself; against a consumer only where the invoice "
            "said so. Interest runs at nine percentage points over the base rate for commercial debts "
            "(§ 288 Abs. 2 BGB). The final payment is a different clock: it falls due on acceptance of "
            "the works plus a verifiable final invoice (§ 641 Abs. 1, § 650g Abs. 4 BGB), which is a "
            "condition this module cannot compute from a date alone."
        ),
    },
    # The United States regimes below are split public/private per state,
    # because that is where American prompt payment law actually divides: the
    # public duty is owed by a governmental entity under one statute and the
    # private duty is owed by an owner under another, with different periods and
    # different interest. Where a state gives its own agencies and its local
    # governments different periods, the public side is split again by payer.
    # The federal row covers work for a federal agency in every state.
    #
    # Every US row ends its statute_reference with the URL of the official text
    # the figures were read from, and the notes say when that text was read
    # through an archived capture because the live site refused the request. The
    # owner-to-contractor leg is the clock; the contractor-to-subcontractor leg
    # each statute adds is a second clock, written into the notes and not
    # computed, the same as every other regime in this table.
    #
    # The Texas and California state pack configs (``app.modules.us_tx_pack.config``
    # and ``app.modules.us_ca_pack.config``) name their four codes under
    # ``payment_clock_regimes`` and carry the same provisions as reference data;
    # the deadline arithmetic is written down here and nowhere else. The other
    # states have no state pack yet, so no config names their codes.
    #
    # All but one take the application date as the due date and the statutory
    # period as the final date for payment, the convention set out at the top of
    # this file. Where a statute gives the owner N days to approve and then M days
    # to pay, and both count the same kind of day, the final date is written as
    # N plus M and the approval window as the payment notice deadline. New York's
    # private act is the exception: its twelve business days to approve and
    # thirty calendar days to pay cannot be added into one count, so it carries
    # the approval deadline as the due date and the final date thirty days after
    # it, the way the UK Act splits the two. Four rows make an application that
    # is not answered in time deemed approved (Illinois private, Pennsylvania
    # private and both Arizona rows), and only those four carry
    # applied_sum_becomes_notified_sum.
    {
        "code": "us_tx_public_2251",
        "jurisdiction": "Texas, United States (public)",
        "country_code": "US",
        "statute": "Texas Prompt Payment Act, Government Code Chapter 2251",
        "statute_reference": (
            "sections 2251.021, 2251.022 and 2251.025; https://statutes.capitol.texas.gov/Docs/GV/htm/GV.2251.htm"
        ),
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "due_date",
        "payment_notice_days": None,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 30,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "reference_rate_plus_margin",
        "interest_reference_rate": "Wall Street Journal prime rate",
        "interest_margin_percent": Decimal("1.000"),
        "interest_fixed_percent": None,
        "interest_statute": "Texas Government Code § 2251.025",
        "notes": (
            "The clock for a payment owed by a governmental entity on public work. The payment becomes "
            "overdue on the 31st day after the later of the date the entity received the goods or the "
            "services were completed and the date it received the invoice, which is the 30 days written "
            "here; enter the later of those two dates as the application date. A political subdivision "
            "whose governing body meets only once a month or less often has until the 46th day instead, so "
            "state the final date for payment on the application for those bodies rather than using the "
            "computed one. The statute has no payment notice and no pay-less notice, so silence has no "
            "preclusive effect. Interest is one percent above the Wall Street Journal prime rate; the rate "
            "is fixed on 1 September for the whole fiscal year from the prime rate published on the first "
            "business day of the preceding July, is simple rather than compounded, and stops on the date "
            "the payment is sent. A prime contractor paid under this chapter must pass the appropriate "
            "share to each subcontractor by the 10th day after it receives the payment (§ 2251.022), which "
            "is a second clock this regime does not compute."
        ),
    },
    {
        "code": "us_tx_private_ch28",
        "jurisdiction": "Texas, United States (private)",
        "country_code": "US",
        "statute": "Texas Prompt Payment to Contractors and Subcontractors Act, Property Code Chapter 28",
        "statute_reference": (
            "sections 28.002, 28.004 and 28.006; https://statutes.capitol.texas.gov/Docs/PR/htm/PR.28.htm"
        ),
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "due_date",
        "payment_notice_days": None,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 35,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "fixed_rate",
        "interest_reference_rate": "",
        "interest_margin_percent": None,
        "interest_fixed_percent": Decimal("18.000"),
        "interest_statute": "Texas Property Code § 28.004(b)",
        "notes": (
            "The clock for private work in Texas. The owner must pay by the 35th day after it receives the "
            "contractor's written request for payment, so enter the date the owner received the request as "
            "the application date. The contractor must then pay its subcontractor by the seventh day after "
            "it receives the owner's payment (§ 28.002(b)), a downstream clock this regime does not "
            "compute. The statute states the interest monthly, at one and a half percent each month, which "
            "is the 18 percent a year written here. There is no notice sequence. An attempted waiver of the "
            "chapter is void under § 28.006, with a limited exception for certain single-family residential "
            "contracts, so a subcontract clause purporting to lengthen these periods generally does not."
        ),
    },
    {
        "code": "us_ca_public_20104",
        "jurisdiction": "California, United States (public)",
        "country_code": "US",
        "statute": "California Public Contract Code § 20104.50 (Local Agency Public Construction Act)",
        "statute_reference": (
            "section 20104.50; legal rate under Code of Civil Procedure § 685.010(a); "
            "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=PCC&sectionNum=20104.50"
        ),
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": 7,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 30,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "fixed_rate",
        "interest_reference_rate": "",
        "interest_margin_percent": None,
        "interest_fixed_percent": Decimal("10.000"),
        "interest_statute": "Public Contract Code § 20104.50, applying Code of Civil Procedure § 685.010(a)",
        "notes": (
            "The clock for a progress payment owed by a Californian local agency, which includes a city, a "
            "charter city, a county, and a city and county. The agency owes interest if it fails to pay "
            "within 30 days of receiving an undisputed and properly submitted payment request. A progress "
            "payment here means everything due except the portion of the final payment the contract "
            "designates as retention, so retention release runs on its own clock under Public Contract Code "
            "§ 7107 (60 days after completion, then 7 days to pass a subcontractor's share on) and is not "
            "computed by this regime. The seven days recorded as the payment notice deadline are the "
            "agency's own: it must return an improper payment request as soon as practicable and no later "
            "than the seventh day after receipt. Missing that does not make the applied sum payable, which "
            "is why the no-notice effect is none; instead the 30 day window shrinks by however many days "
            "the agency ran over the seven, an adjustment this module does not apply, so reduce the final "
            "date by hand where a request came back late. Interest runs at the legal rate on judgments, "
            "10 percent a year for these claims."
        ),
    },
    {
        "code": "us_ca_private_8800",
        "jurisdiction": "California, United States (private)",
        "country_code": "US",
        "statute": "California prompt payment on private works, Civil Code § 8800",
        "statute_reference": (
            "Civil Code §§ 8800 and 8812; Business and Professions Code § 7108.5; "
            "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=CIV&sectionNum=8800"
        ),
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "due_date",
        "payment_notice_days": None,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 30,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "fixed_rate",
        "interest_reference_rate": "",
        "interest_margin_percent": None,
        "interest_fixed_percent": Decimal("24.000"),
        "interest_statute": "California Civil Code § 8800",
        "notes": (
            "The clock for private work in California. The owner must pay a progress payment within 30 days "
            "after notice demanding payment is given under the contract, so enter the date that notice was "
            "given as the application date. This period is a default rather than a floor: § 8800 opens with "
            "an exception for what the owner and the direct contractor agree in writing, so a contract may "
            "lengthen it, and where it does the agreed final date should be stated on the application. Where "
            "there is a good faith dispute the owner may withhold up to 150 percent of the disputed amount "
            "and the rest still has to be paid. What § 8800 imposes is a penalty rather than interest, two "
            "percent a month on the amount wrongfully withheld in place of any interest otherwise due, "
            "written here as the 24 percent a year it comes to; the prevailing party in an action to collect "
            "it recovers costs and a reasonable attorney's fee. Downstream, a prime must pay a subcontractor "
            "within seven days of receiving a progress payment under Business and Professions Code § 7108.5 "
            "at the same two percent a month, and retention on private work is released within 45 days of "
            "completion under § 8812; neither is computed by this regime."
        ),
    },
    {
        "code": "us_fed_ppa_construction",
        "jurisdiction": "United States (federal)",
        "country_code": "US",
        "statute": "Prompt Payment Act, 31 U.S.C. chapter 39, and FAR 52.232-27 Prompt Payment for Construction Contracts",
        "statute_reference": (
            "31 U.S.C. §§ 3902(a)-(b), 3903(a)(6)-(7) and 3905(b); FAR 52.232-27(a)(1)(i), (a)(2) and (c) "
            "(Jan 2017); https://www.law.cornell.edu/uscode/text/31/3903 and "
            "https://www.acquisition.gov/far/52.232-27"
        ),
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": 7,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 14,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "prescribed_rate",
        "interest_reference_rate": (
            "the Secretary of the Treasury for interest under 41 U.S.C. 7109, as published in the Federal Register"
        ),
        "interest_margin_percent": None,
        "interest_fixed_percent": None,
        "interest_statute": "31 U.S.C. § 3902(a)",
        "notes": (
            "The clock for a progress payment owed by a federal agency on a construction contract, in any "
            "state. FAR 52.232-27(a)(1)(i)(A) makes the payment due 14 days after the designated billing "
            "office receives a proper payment request, so enter that date of receipt as the application date. "
            "The clause counts calendar days, and where the due date falls on a Saturday, Sunday or legal "
            "holiday the agency may pay on the next working day without a penalty (FAR 52.232-27(a)(3)), which "
            "this count does not move. The solicitation may lengthen the 14 days where the agency needs the "
            "time to inspect the work (31 U.S.C. § 3903(a)(6)(A)(ii)); state the final date for payment on the "
            "application where it does. The seven days recorded as the payment notice deadline are the "
            "agency's own: a request that is not a proper one must be returned within 7 days of receipt with "
            "the reasons (§ 3903(a)(7)(B), FAR 52.232-27(a)(2)). Missing that does not make the applied sum "
            "payable, which is why the no-notice effect is none; instead the days the agency has to pay without "
            "interest shrink by however many days it ran over (§ 3903(a)(7)(C)), an adjustment this module "
            "does not apply. Interest runs from the day after the due date to the day of payment (§ 3902(b)) "
            "at the rate the Treasury sets for Contract Disputes Act interest, and the agency pays it without "
            "being asked. Retained amounts approved for release fall due on the date the contract sets or, "
            "failing one, 30 days after the contracting officer approves their release (FAR "
            "52.232-27(a)(1)(i)(B)); the final payment falls due on the later of the 30th day after a proper "
            "invoice and the 30th day after acceptance (FAR 52.232-27(a)(1)(ii)(A)); neither is computed here. "
            "Downstream, the prime contractor must pay each subcontractor within 7 days of receiving the "
            "agency's payment (§ 3905(b)(1), FAR 52.232-27(c)(1)), with interest at the same rate from the "
            "day after that date, and the clause has to be passed to every lower tier; that second clock is "
            "not computed either. Title 31 was read on law.cornell.edu and the January 2017 clause on "
            "acquisition.gov."
        ),
    },
    {
        "code": "us_ny_public_state_179f",
        "jurisdiction": "New York, United States (public, state agencies)",
        "country_code": "US",
        "statute": "New York State Finance Law § 139-f and Article 11-A (prompt payment by state agencies)",
        "statute_reference": (
            "State Finance Law §§ 139-f(1), (1-b) and (2), 179-e, 179-f(2)-(3) and 179-g; "
            "https://www.nysenate.gov/legislation/laws/STF/139-F and "
            "https://www.nysenate.gov/legislation/laws/STF/179-F"
        ),
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": 15,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 30,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "prescribed_rate",
        "interest_reference_rate": (
            "the Commissioner of Taxation and Finance as the overpayment rate under Tax Law § 1096(e)"
        ),
        "interest_margin_percent": None,
        "interest_fixed_percent": None,
        "interest_statute": "New York State Finance Law § 179-g",
        "notes": (
            "The clock for a progress payment owed by a New York state agency on a public construction "
            "contract. Section 139-f(1-b) sends the payment to Article 11-A, where the required payment date is "
            "thirty calendar days, excluding legal holidays, after the invoice is received (§ 179-f(2)), and "
            "§ 179-e counts from the later of the day a proper invoice reached the designated payment office "
            "and the day the agency received the work; enter the later of the two as the application date. "
            "Legal holidays are left out of the count, which a calendar count here does not do, so move the "
            "final date one day later for each legal holiday inside the window. A small business is owed "
            "payment within fifteen calendar days on the same terms, so state the final date for payment on the "
            "application for one. The fifteen days recorded as the payment notice deadline are the agency's "
            "own: it has fifteen calendar days after receiving the invoice to notify the contractor of defects "
            "in the work or in the invoice, seven for a small business (§ 179-f(3)). A late notice does not "
            "make the applied sum payable; it shortens the time allowed for paying the corrected invoice by the "
            "days of the delay, an adjustment this module does not apply. Interest runs at the overpayment "
            "rate the Commissioner of Taxation and Finance sets (§ 179-g) and is not paid when it would come to "
            "less than ten dollars. Downstream, the contractor must pay each subcontractor within seven "
            "calendar days of receiving a payment from the public owner, with interest at the rate in General "
            "Business Law § 756-b(1)(b) (§ 139-f(2)), a second clock this regime does not compute. The public "
            "owner may retain no more than five percent of each progress payment, or up to ten percent where it "
            "requires no performance bond and no labor and material bond (§ 139-f(1)). Public authorities are "
            "sent to Public Authorities Law § 2880 instead, which was not read for this row. Read on "
            "nysenate.gov, § 139-f as revised on 18 June 2021 and § 179-f as revised on 14 April 2017."
        ),
    },
    {
        "code": "us_ny_public_local_106b",
        "jurisdiction": "New York, United States (public, local)",
        "country_code": "US",
        "statute": "New York General Municipal Law § 106-b (prompt payment by political subdivisions)",
        "statute_reference": (
            "General Municipal Law § 106-b(1)(a), (1)(c) and (2); https://www.nysenate.gov/legislation/laws/GMU/106-B"
        ),
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "due_date",
        "payment_notice_days": None,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 30,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "prescribed_rate",
        "interest_reference_rate": (
            "the Commissioner of Taxation and Finance as the overpayment rate under Tax Law § 1096(e)"
        ),
        "interest_margin_percent": None,
        "interest_fixed_percent": None,
        "interest_statute": "New York General Municipal Law § 106-b(1)(c)",
        "notes": (
            "The clock for a progress payment owed by a New York political subdivision other than the city of "
            "New York, which the section leaves out. To promptly pay means payment within thirty days, "
            "excluding legal holidays, of receipt of the requisition, so enter the date the requisition was "
            "received as the application date. Legal holidays are left out of the count, which a calendar count "
            "here does not do, so move the final date one day later for each legal holiday inside the window. "
            "Where the municipal corporation requires an elected official to approve progress payments the "
            "period is forty-five days on the same terms, so state the final date for payment on the "
            "application for those bodies. A requisition that is not approvable under the contract does not "
            "start the clock, but the section sets no deadline for saying so, so there is no payment notice "
            "and silence has no consequence. Interest runs at the overpayment rate the Commissioner of Taxation "
            "and Finance sets and is not paid when it would come to less than ten dollars. Downstream, the "
            "contractor must pay each subcontractor within seven calendar days of receiving a payment from the "
            "public owner, with interest at the rate in General Business Law § 756-b(1)(b) (§ 106-b(2)), a "
            "second clock this regime does not compute. The public owner may retain no more than five percent "
            "of each progress payment, or up to ten percent where it requires no performance bond and no labor "
            "and material bond. Read on nysenate.gov as revised on 18 June 2021."
        ),
    },
    {
        "code": "us_ny_private_756a",
        "jurisdiction": "New York, United States (private)",
        "country_code": "US",
        "statute": "New York General Business Law Article 35-E (prompt payment on private construction)",
        "statute_reference": (
            "General Business Law §§ 756(1), 756-a(2)(a) and (3), 756-b(1) and 756-c; "
            "https://www.nysenate.gov/legislation/laws/GBS/756-A and "
            "https://www.nysenate.gov/legislation/laws/GBS/756-B"
        ),
        "due_date_basis": "application_date",
        "due_date_days": 12,
        "due_date_day_basis": "business",
        "payment_notice_basis": "application_date",
        "payment_notice_days": 12,
        "payment_notice_day_basis": "business",
        "final_date_basis": "due_date",
        "final_date_days": 30,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "fixed_rate",
        "interest_reference_rate": "",
        "interest_margin_percent": None,
        "interest_fixed_percent": Decimal("12.000"),
        "interest_statute": "New York General Business Law § 756-b(1)(a)",
        "notes": (
            "The clock for private construction in New York under a contract of one hundred fifty thousand "
            "dollars or more (§ 756(1)); public works and the one to three family, small residential and "
            "assisted residential projects the section lists are excluded. The owner must approve or "
            "disapprove the invoice within twelve business days of receiving it with all the documentation the "
            "contract requires, and must give a written statement of the items it does not approve "
            "(§ 756-a(2)(a)); payment of an approved interim or final invoice is then due not later than thirty "
            "days after the approval (§ 756-a(3)(a)). Enter the date the invoice and its documentation were "
            "delivered as the application date. The two periods count different days, so this is the one US "
            "regime that splits the due date from the final date: the due date here is the last day for the "
            "approval decision, twelve business days on, and the final date is thirty days after it, which is "
            "the latest the statute allows when the owner uses its whole approval window. Where the owner "
            "approved sooner, payment falls due thirty days after that approval, so state the final date for "
            "payment on the application. Business days need the New York holiday calendar to reproduce the "
            "statutory date. The section does not say what an owner's silence past the twelve business days "
            "does, so the no-notice effect is none. Interest runs from the next day at one "
            "percent a month on the unpaid balance, or a higher rate the contract sets (§ 756-b(1)(a)), written "
            "here as the 12 percent a year it comes to. Downstream, the contractor has the same twelve business "
            "days to approve a subcontractor's invoice and must pay within seven days of receiving good funds "
            "(§ 756-a(3)(b)), at the same rate notwithstanding any contrary agreement (§ 756-b(1)(b)); that "
            "second clock is not computed. Retainage may not exceed five percent of the contract sum and must "
            "be released within thirty days after final approval of the work (§ 756-c). Read on nysenate.gov, "
            "§§ 756-a and 756-c as revised on 26 November 2023; a contract signed before that revision may be "
            "governed by the earlier text, which was not read."
        ),
    },
    {
        "code": "us_fl_public_local_218735",
        "jurisdiction": "Florida, United States (public, local government)",
        "country_code": "US",
        "statute": "Florida Local Government Prompt Payment Act, Florida Statutes § 218.735 (construction services)",
        "statute_reference": (
            "Florida Statutes § 218.735(1)(b), (2), (6), (8)(a) and (9) (2026); "
            "https://www.flsenate.gov/Laws/Statutes/2026/218.735"
        ),
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": 20,
        "payment_notice_day_basis": "business",
        "final_date_basis": "application_date",
        "final_date_days": 20,
        "final_date_day_basis": "business",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "fixed_rate",
        "interest_reference_rate": "",
        "interest_margin_percent": None,
        "interest_fixed_percent": Decimal("24.000"),
        "interest_statute": "Florida Statutes § 218.735(9)",
        "notes": (
            "The clock for construction services bought by a Florida county, municipality, school board, "
            "special taxing district or other local governmental entity. Payment is due 20 business days after the "
            "payment request is stamped as received, or 25 business days where an agent must approve it before "
            "it reaches the entity (§ 218.735(1)); enter the stamped date as the application date and state "
            "the final date for payment on the application in the agent case. Business days need the Florida "
            "holiday calendar to reproduce the statutory date. The twenty business days recorded as the payment "
            "notice deadline are the entity's window to reject an improper request in writing, naming the "
            "deficiency and what would cure it (§ 218.735(2)); a corrected request then has to be paid or "
            "rejected within ten business days of being stamped, or later where the entity must approve it at a "
            "meeting (§ 218.735(3)). In the agent case a request not rejected within "
            "4 business days after the contractor's overdue notice is deemed accepted, a step this module does "
            "not model, so the no-notice effect is none. Late payments bear interest at 2 percent a month or the "
            "contract rate, whichever is greater (§ 218.735(9)), written here as the 24 percent a year it comes "
            "to. Downstream, the contractor must pay its subcontractors and suppliers within 10 days of "
            "receiving payment, and a subcontractor its own within 7 days (§ 218.735(6)); that second clock is "
            "not computed. Retainage may not exceed 5 percent of each progress payment (§ 218.735(8)(a)), a rule "
            "that does not apply to construction services of $200,000 or less. Read on flsenate.gov in the 2026 "
            "Florida Statutes, last amended by chapter 2023-134. The state-agency leg (§§ 255.0705 to 255.078) "
            "is not shipped: it leaves the general timing to § 215.422 and fixes 20 business days only for the "
            "undisputed part of a disputed request, which is not one clock. Florida private work (§ 715.12) "
            "leaves the payment date to the contract."
        ),
    },
    {
        "code": "us_il_public_state_540",
        "jurisdiction": "Illinois, United States (public, state agencies)",
        "country_code": "US",
        "statute": "Illinois State Prompt Payment Act, 30 ILCS 540",
        "statute_reference": (
            "30 ILCS 540/3-2(1.05) and (1.1) and 540/7(a-5) and (b); "
            "https://www.ilga.gov/Documents/legislation/ilcs/documents/003005400K3-2.htm"
        ),
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": 30,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 90,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "fixed_rate",
        "interest_reference_rate": "",
        "interest_margin_percent": None,
        "interest_fixed_percent": Decimal("12.000"),
        "interest_statute": "30 ILCS 540/3-2(1.05)",
        "notes": (
            "The clock for a payment owed by an Illinois state official or agency, construction included. For "
            "state fiscal year 2012 and later a bill approved for payment must be paid within 90 days of receipt "
            "of a proper bill or invoice (§ 3-2(1.05)), which displaces the 60 days still written in § 3-2(1); "
            "enter the date the proper bill was received as the application date. The approval step inside "
            "those 90 days follows rules made under § 3-3, which were not read for this row. The thirty days "
            "recorded as the payment notice deadline are the agency's own: notice of a defect in a construction "
            "bill must be given not later than 30 days after it was first submitted (§ 3-2(1.1)), and the "
            "section gives a late notice no consequence for the sum, so the no-notice effect is none. Interest "
            "is 1.0 percent a month, or one-thirtieth of one percent a day, after the 90-day period, written "
            "here as the 12 percent a year it comes to. Downstream, a contractor must pay each subcontractor "
            "and supplier within 10 business days or 15 calendar days of receiving payment, whichever is "
            "earlier, with interest of 2 percent a month after that (§ 7(a-5) and (b)); that second clock is "
            "not computed. The official ilga.gov pages refused the request, so the text was read from the "
            "Internet Archive's January 2026 captures of them; § 3-2 carries P.A. 100-1064, effective 24 "
            "August 2018, and § 7 P.A. 101-524, effective 1 January 2020."
        ),
    },
    {
        "code": "us_il_public_local_505",
        "jurisdiction": "Illinois, United States (public, local government)",
        "country_code": "US",
        "statute": "Illinois Local Government Prompt Payment Act, 50 ILCS 505",
        "statute_reference": (
            "50 ILCS 505/3, 505/4 and 505/9; https://www.ilga.gov/Documents/legislation/ilcs/documents/005005050K4.htm"
        ),
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": 30,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 60,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "fixed_rate",
        "interest_reference_rate": "",
        "interest_margin_percent": None,
        "interest_fixed_percent": Decimal("12.000"),
        "interest_statute": "50 ILCS 505/4",
        "notes": (
            "The clock for a payment owed by an Illinois county, township, municipality, school district or "
            "other local governmental unit; the Act does not apply to the State. The local official or agency "
            "must approve or disapprove a bill within 30 days after receiving it or the goods or services, "
            "whichever is later (§ 3), and an approved bill must be paid within 30 days after the approval "
            "(§ 4), so enter the later of the two receipts as the application date. The sixty days written here "
            "are the two windows end to end, the latest date when the approval takes its whole window; where "
            "the bill was approved sooner, payment falls due 30 days after that approval, so state the final "
            "date for payment on the application. The thirty-day approval window is recorded as the payment "
            "notice deadline. A disapproval must be sent to the contractor in writing immediately, and the part "
            "of a construction bill that is not disapproved still has to be paid; the Act attaches no "
            "consequence to silence, so the no-notice effect is none. Interest is 1 percent of the unpaid amount "
            "for each month or fraction of a month after the payment period, written here as the 12 percent a "
            "year it comes to, although a part month counts as a whole one. Downstream, a contractor who "
            "without reasonable cause fails to pay its subcontractors and suppliers within 15 days of receiving "
            "payment owes them interest of 2 percent a month (§ 9); that second clock is not computed. The "
            "official ilga.gov pages refused the request, so the text was read from the Internet Archive's "
            "January 2026 captures of them; § 3 and § 9 carry P.A. 94-972, effective 1 July 2007."
        ),
    },
    {
        "code": "us_il_private_603",
        "jurisdiction": "Illinois, United States (private)",
        "country_code": "US",
        "statute": "Illinois Contractor Prompt Payment Act, 815 ILCS 603",
        "statute_reference": (
            "815 ILCS 603/5, 603/10(1) and (2), 603/15(a) and 603/20; "
            "https://www.ilga.gov/Documents/legislation/ilcs/documents/081506030K10.htm"
        ),
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": 25,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 40,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "applied_sum_becomes_notified_sum",
        "interest_basis": "fixed_rate",
        "interest_reference_rate": "",
        "interest_margin_percent": None,
        "interest_fixed_percent": Decimal("10.000"),
        "interest_statute": "815 ILCS 603/15(a)",
        "notes": (
            "The clock for private construction in Illinois. The Act excludes contracts that spend public funds "
            "and work on single family homes or buildings of 12 or fewer residential units (§ 5(b)). The owner "
            "must pay not more than 15 calendar days after approving the payment application, and the "
            "application is deemed approved 25 days after the owner receives it unless before then the owner "
            "gives a written statement of the amount withheld and the reason (§ 10(1)); enter the date the "
            "owner received the application as the application date. That written statement is recorded as the "
            "payment notice, and because an application nobody answered in time is deemed approved, the "
            "no-notice effect is that the applied sum becomes payable. The forty days written here are the "
            "25-day approval window and the 15 days to pay end to end, the latest date the Act allows; where "
            "the owner approved sooner, payment falls due 15 calendar days after that approval, so state the "
            "final date for payment on the application. Telling a lender or architect to process the "
            "application is not approval under the Act. Late payments carry interest at 10 percent a year "
            "(§ 15(a)), and after 7 calendar days' written notice an unpaid contractor may suspend work "
            "(§ 15(b)). Downstream, the contractor must pay its subcontractor within 15 calendar days of its "
            "own receipt of each periodic payment, final payment or retainage (§ 10(2)); that second clock is "
            "not computed. Retainage may not exceed 10 percent of any payment before the contract is half "
            "complete, and no more than 5 percent may be held after that (§ 20, P.A. 101-432, effective 20 "
            "August 2019). The official ilga.gov pages refused the request, so the text was read from the "
            "Internet Archive's January 2026 captures of them."
        ),
    },
    {
        "code": "us_wa_public_3976",
        "jurisdiction": "Washington, United States (public)",
        "country_code": "US",
        "statute": "Washington interest on unpaid public contracts, RCW 39.76, and RCW 39.04.250",
        "statute_reference": (
            "RCW 39.76.011(1) and (2)(a)-(d) and RCW 39.04.250(1); "
            "https://app.leg.wa.gov/RCW/default.aspx?cite=39.76.011 and "
            "https://app.leg.wa.gov/RCW/default.aspx?cite=39.04.250"
        ),
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": 8,
        "payment_notice_day_basis": "business",
        "final_date_basis": "application_date",
        "final_date_days": 30,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "fixed_rate",
        "interest_reference_rate": "",
        "interest_margin_percent": None,
        "interest_fixed_percent": Decimal("12.000"),
        "interest_statute": "RCW 39.76.011(1)",
        "notes": (
            "The clock for a payment owed by any Washington public body - a state agency, county, city, town, "
            "school district or other - on a public works contract. Payment is timely if it is made on the date "
            "the contract specifies but not later than thirty days of receipt of a properly completed invoice "
            "or receipt of the goods or services, whichever is later (RCW 39.76.011(2)(a)), so enter the later "
            "of the two as the application date. Where the contract is funded by grant or federal money the "
            "thirty calendar days run instead from the later of a compliant payment request and the day the "
            "public body actually receives that money. The eight days recorded as the payment notice deadline "
            "are working days: when the public body withholds any part of a payment on a public works contract "
            "it must say so in writing within eight working days of the request, stating why and what the "
            "contractor has to do (§ 2(b)); Washington holidays are not shipped, so supply them. A notice that "
            "lacks those contents makes interest run from the ninth working day (§ 2(c)), and a withheld amount "
            "is due thirty calendar days after the remedial work is done (§ 2(d)); neither is computed, and "
            "missing the notice does not make the applied sum payable, so the no-notice effect is none. "
            "Interest is one percent a month, at least one dollar a month (§ 1), written here as the 12 percent "
            "a year it comes to; a claim disputed in good faith, with notice given before the payment date as "
            "RCW 39.76.020 requires, carries none. Downstream, "
            "the contractor must pay a subcontractor not later than ten days after receiving payment for its "
            "work, and may hold back no more than 150 percent of an amount disputed in good faith (RCW "
            "39.04.250); that second clock is not computed. These sections apply to public works contracts "
            "entered into on or after 1 September 1992 and were read on app.leg.wa.gov. Washington has no "
            "statute setting an owner's payment period on private work, so no private regime is shipped."
        ),
    },
    {
        "code": "us_pa_public_3932",
        "jurisdiction": "Pennsylvania, United States (public)",
        "country_code": "US",
        "statute": "Pennsylvania Commonwealth Procurement Code, 62 Pa.C.S. Chapter 39 Subchapter D (prompt payment)",
        "statute_reference": (
            "62 Pa.C.S. §§ 3902, 3921(a), 3932(b)-(d), 3933(c) and 3934(b); "
            "https://www.legis.state.pa.us/WU01/LI/LI/CT/HTM/62/62.HTM"
        ),
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": 15,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 45,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "prescribed_rate",
        "interest_reference_rate": (
            "the Secretary of Revenue for overdue taxes under sections 806 and 806.1 of The Fiscal Code"
        ),
        "interest_margin_percent": None,
        "interest_fixed_percent": None,
        "interest_statute": "62 Pa.C.S. § 3932(c)",
        "notes": (
            "The clock for a progress payment owed by a Pennsylvania government agency - a Commonwealth agency, "
            "a political subdivision or a local authority - on a construction contract over $50,000 let by "
            "competitive sealed bidding or proposals; Department of Transportation contracts are excluded "
            "(§§ 3901 and 3902). The agency must pay strictly in accordance with the contract (§ 3932(a)), and "
            "the 45 calendar days from receipt of the application written here apply only where the contract "
            "has no term governing the time for payment (§ 3932(b)); where it has one, state the final date for "
            "payment on the application. Enter the date the application was received as the application date. "
            "The fifteen days recorded as the payment notice deadline are the agency's: it must tell the "
            "contractor of a deficiency item within the period the contract sets or 15 calendar days of "
            "receiving the application (§ 3934(b)); the section attaches no consequence for the sum to a late "
            "notice, so the no-notice effect is none. Interest runs at the rate the Secretary of Revenue sets "
            "for overdue taxes (§ 3932(c)), but where the contract has no grace period none is owed if payment "
            "is made on or before the 15th calendar day after the payment date (§ 3932(d)), so the overdue "
            "warning from the final date runs ahead of any interest actually due. Downstream, the contractor "
            "must pay each subcontractor 14 days after receiving a progress payment (§ 3933(c)); that second "
            "clock is not computed. Retainage may not exceed 10 percent until the contract is half complete, "
            "when half of it is returned, and 5 percent after that (§ 3921(a)). The official page refused the "
            "request, so the Legislative Reference Bureau text was read from the Internet Archive's capture of "
            "12 February 2026."
        ),
    },
    {
        "code": "us_pa_private_caspa",
        "jurisdiction": "Pennsylvania, United States (private)",
        "country_code": "US",
        "statute": "Pennsylvania Contractor and Subcontractor Payment Act, Act of 17 February 1994, P.L. 73, No. 7",
        "statute_reference": (
            "sections 3(a), 5(c)-(d), 6(b), 7(c) and 9(a) of Act 1994-7 as amended by Act 2018-27; "
            "https://www.legis.state.pa.us/WU01/LI/LI/US/PDF/1994/0/0007..PDF"
        ),
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": 14,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 20,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "applied_sum_becomes_notified_sum",
        "interest_basis": "fixed_rate",
        "interest_reference_rate": "",
        "interest_margin_percent": None,
        "interest_fixed_percent": Decimal("12.000"),
        "interest_statute": "Contractor and Subcontractor Payment Act, section 5(d)",
        "notes": (
            "The clock for private construction in Pennsylvania; the Act does not apply to a project of six or "
            "fewer residential units under construction at the same time (§ 3(a)) and may not be waived by "
            "contract except where it says so (§ 3(c)). Except as the parties otherwise agree, an interim or "
            "final invoice is due from the owner 20 days after the end of the billing period or 20 days after "
            "delivery of the invoice, whichever is later (§ 5(c)), so enter the later of the two as the "
            "application date and state the final date for payment on the application where the contract "
            "sets its own. The fourteen days recorded as the payment notice deadline are the owner's window "
            "to give a written explanation of a deficiency it withholds for, counted in calendar days from "
            "receipt of the invoice (§ 6(b)(1)); failing to do so waives the basis to withhold and requires "
            "payment of the invoice in full (§ 6(b)(2)), which is why the no-notice effect is that the applied "
            "sum becomes payable. Interest is 1 percent a month, but only from the eighth day where the payment "
            "is not made within seven days of the due date (§ 5(d)), so the overdue warning from the final date "
            "runs a week ahead of the interest; it is written here as the 12 percent a year it comes to. A "
            "separate penalty of 1 percent a month on an amount wrongfully withheld (§ 12) is not computed. "
            "Downstream, the contractor must pay its subcontractor 14 days after receiving each progress or "
            "final payment or 14 days after receiving the subcontractor's invoice, whichever is later "
            "(§ 7(c)); that second clock is not computed. Retainage has no percentage cap in the Act and must "
            "be paid within 30 days after final acceptance of the work (§ 9(a)). The official page refused the "
            "request, so the Legislative Reference Bureau's compiled text was read from the Internet Archive's "
            "capture of 19 February 2024, which shows the amendments of 12 June 2018 (P.L. 131, No. 27); an "
            "amendment after that capture has not been checked."
        ),
    },
    # Massachusetts writes both public periods into the same sentence - fifteen
    # days, thirty in the case of the commonwealth - so a local awarding
    # authority and the commonwealth get one row each, the same split the
    # Chinese regulation's two payers take.
    {
        "code": "us_ma_public_local_39k",
        "jurisdiction": "Massachusetts, United States (public, local)",
        "country_code": "US",
        "statute": "Massachusetts General Laws chapter 30 §§ 39K and 39G (periodic payments on public construction)",
        "statute_reference": (
            "M.G.L. c. 30 §§ 39F(1)(a), 39G and 39K; "
            "https://malegislature.gov/Laws/GeneralLaws/PartI/TitleIII/Chapter30/Section39K and "
            "https://malegislature.gov/Laws/GeneralLaws/PartI/TitleIII/Chapter30/Section39G"
        ),
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "due_date",
        "payment_notice_days": None,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 15,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "reference_rate_plus_margin",
        "interest_reference_rate": "Federal Reserve Bank of Boston rediscount rate",
        "interest_margin_percent": Decimal("3.000"),
        "interest_fixed_percent": None,
        "interest_statute": "M.G.L. c. 30 § 39K and § 39G",
        "notes": (
            "The clock for a periodic payment owed by a Massachusetts county, city, town, district, board, "
            "commission or other local public body: on a public building contract over two thousand dollars "
            "under § 39K, and on public ways, bridges, sewers, water mains, airports and other public works "
            "under § 39G, which sets the same period. The awarding authority must pay within fifteen days after "
            "receiving the contractor's periodic estimate for the preceding month, so enter the date the "
            "estimate was received at the place the authority designated as the application date; the "
            "commonwealth has thirty days and has its own row. Neither section sets a deadline for disputing an "
            "estimate - the authority deducts its own retention for claims against the contractor - so there is "
            "no payment notice and silence has no consequence. Daily interest is added at three percentage "
            "points above the rediscount rate charged by the Federal Reserve Bank of Boston from the first day "
            "after the payment is due. The authority may keep a retention of no more than five percent of the "
            "approved amount of a periodic payment, and under § 39K owes the final payment within sixty-five "
            "days after completion. Downstream, § 39F makes the general contractor pay each subcontractor "
            "forthwith after it is paid on a periodic estimate, which is not a number of days, so there is no "
            "second clock to compute. The official pages refused the request, so the text was read from the "
            "Internet Archive's captures of malegislature.gov (§ 39K of 30 March 2025, § 39G of 25 April 2025), "
            "which print no amendment history."
        ),
    },
    {
        "code": "us_ma_public_state_39k",
        "jurisdiction": "Massachusetts, United States (public, commonwealth)",
        "country_code": "US",
        "statute": "Massachusetts General Laws chapter 30 §§ 39K and 39G (periodic payments on public construction)",
        "statute_reference": (
            "M.G.L. c. 30 §§ 39F(1)(a), 39G and 39K; "
            "https://malegislature.gov/Laws/GeneralLaws/PartI/TitleIII/Chapter30/Section39K and "
            "https://malegislature.gov/Laws/GeneralLaws/PartI/TitleIII/Chapter30/Section39G"
        ),
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "due_date",
        "payment_notice_days": None,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 30,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "reference_rate_plus_margin",
        "interest_reference_rate": "Federal Reserve Bank of Boston rediscount rate",
        "interest_margin_percent": Decimal("3.000"),
        "interest_fixed_percent": None,
        "interest_statute": "M.G.L. c. 30 § 39K and § 39G",
        "notes": (
            "The clock for a periodic payment owed by the Commonwealth of Massachusetts, which § 39K extends to "
            "local housing authorities, on a public building contract over five thousand dollars, or on public "
            "ways, bridges, sewers, water mains, airports and other public works under § 39G. The awarding "
            "authority must pay within thirty days after receiving the contractor's periodic estimate for the "
            "preceding month, against fifteen for a local body, so enter the date the estimate was received as "
            "the application date. Everything else is as for us_ma_public_local_39k: no deadline for disputing "
            "an estimate and so no payment notice, daily interest at three percentage points above the Federal "
            "Reserve Bank of Boston rediscount rate from the first day after the payment is due, a retention of "
            "no more than five percent of each approved periodic payment, and a subcontractor paid forthwith "
            "under § 39F rather than within a number of days. Read from the same Internet Archive captures of "
            "malegislature.gov."
        ),
    },
    {
        "code": "us_ma_private_29e",
        "jurisdiction": "Massachusetts, United States (private)",
        "country_code": "US",
        "statute": "Massachusetts General Laws chapter 149 § 29E (prompt payment on private construction)",
        "statute_reference": (
            "M.G.L. c. 149 § 29E(a), (c) and (e); "
            "https://malegislature.gov/Laws/GeneralLaws/PartI/TitleXXI/Chapter149/Section29E"
        ),
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": 15,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 60,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "contract",
        "interest_reference_rate": "",
        "interest_margin_percent": None,
        "interest_fixed_percent": None,
        "interest_statute": "",
        "notes": (
            "The clock for a private project in Massachusetts on which a lien may be established under chapter "
            "254 and the prime contract's original price is $3,000,000 or more; projects of one to four "
            "dwelling units are excluded (§ 29E(a)). The section does not set the periods directly: it makes "
            "every such contract provide reasonable ones and caps them at 15 days after submission to approve "
            "or reject a periodic progress payment application and 45 days after approval to pay it (§ 29E(c)). "
            "Enter the date the application was submitted as the application date; the sixty days written here "
            "are the two caps end to end, and where the contract sets shorter periods or the owner approved "
            "sooner, state the final date for payment on the application. The fifteen-day approval window is "
            "recorded as the payment notice deadline; a rejection must be in writing, give the factual and "
            "contractual basis and be certified as made in good faith. An application neither approved nor "
            "rejected in time is deemed approved unless it is rejected before the date payment is due, so a "
            "rejection stays possible after the fifteen days and silence does not settle the sum; the no-notice "
            "effect is therefore none. Each tier below the owner may take 7 more days to approve than the tier "
            "above it, and a clause making payment conditional on the payer being paid is unenforceable except "
            "in the cases § 29E(e) lists. The section names no interest rate, so the contract rate applies. "
            "The official page refused the request, so the text was read from the Internet Archive's capture "
            "of malegislature.gov of 15 May 2026, word for word the same as its capture of June 2024."
        ),
    },
    {
        "code": "us_az_public_34221",
        "jurisdiction": "Arizona, United States (public)",
        "country_code": "US",
        "statute": "Arizona public works progress payments, A.R.S. § 34-221 and § 41-2577",
        "statute_reference": (
            "A.R.S. § 34-221(C), (G) and (J) and § 41-2577(A), (B) and (E); "
            "https://www.azleg.gov/ars/34/00221.htm and https://www.azleg.gov/ars/41/02577.htm"
        ),
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": 7,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 21,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "applied_sum_becomes_notified_sum",
        "interest_basis": "fixed_rate",
        "interest_reference_rate": "",
        "interest_margin_percent": None,
        "interest_fixed_percent": Decimal("12.000"),
        "interest_statute": "A.R.S. § 34-221(J) and § 41-2577(E)",
        "notes": (
            "The clock for a progress payment on Arizona public work: § 34-221 binds counties, cities, towns "
            "and the districts § 34-101 lists, and § 41-2577 the state under its procurement code, in the same "
            "terms. An estimate of the work is deemed approved and certified for payment seven days after it "
            "is submitted unless the owner first issues a specific written finding of the items it does not "
            "approve, and a certified estimate must be paid within fourteen days, so enter the date the "
            "estimate was submitted to the person the owner designated as the application date. That written "
            "finding is recorded as the payment notice, and because an estimate nobody answered in time is "
            "deemed certified, the no-notice effect is that the applied sum becomes payable. The twenty-one "
            "days written here are the two periods end to end, the latest date the sections allow; where the "
            "estimate was certified sooner, payment falls due fourteen days after that, so state the final date "
            "for payment on the application. Interest is one percent a month or fraction of a month on the "
            "unpaid balance, written here as the 12 percent a year it comes to. Downstream, the contractor must "
            "pay each subcontractor within seven days after receiving a progress payment unless they agreed "
            "otherwise in writing, with interest at one percent a month from the eighth day (§ 34-221(G) and "
            "(K), § 41-2577(B) and (F)); that second clock is not computed. The owner retains ten percent of "
            "each estimate, and once the contract is half complete no more than five percent of later payments "
            "while progress is satisfactory (§ 34-221(C), § 41-2576). School districts are not in the § 34-101 "
            "list and were not researched. Read on azleg.gov."
        ),
    },
    {
        "code": "us_az_private_1182",
        "jurisdiction": "Arizona, United States (private)",
        "country_code": "US",
        "statute": "Arizona prompt payment on private construction, A.R.S. §§ 32-1181 to 32-1188",
        "statute_reference": (
            "A.R.S. §§ 32-1182(A), (D) and (Q), 32-1183(B) and 32-1187; "
            "https://www.azleg.gov/ars/32/01182.htm and https://www.azleg.gov/ars/32/01183.htm"
        ),
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": 14,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 21,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "applied_sum_becomes_notified_sum",
        "interest_basis": "fixed_rate",
        "interest_reference_rate": "",
        "interest_margin_percent": None,
        "interest_fixed_percent": Decimal("18.000"),
        "interest_statute": "A.R.S. § 32-1182(Q)",
        "notes": (
            "The clock for private construction in Arizona; the payment sections do not apply to the state or "
            "its political subdivisions (§ 32-1187). A billing or estimate is deemed certified and approved "
            "fourteen days after the owner receives it unless the owner first issues a written statement of its "
            "reasons for not certifying all or part of it, and the owner must pay within seven days after the "
            "certification (§ 32-1182(A) and (D)), so enter the date the owner received the billing as the "
            "application date. That written statement is recorded as the payment notice, and because a billing "
            "nobody answered in time is deemed certified, the no-notice effect is that the applied sum becomes "
            "payable. The twenty-one days written here are the two periods end to end, the latest date the "
            "section allows; where the billing was certified sooner, payment falls due seven days after that. "
            "An owner may lengthen either period only through a clear and conspicuous contract term matched by a "
            "notice legend on every page of the plans (§ 32-1182(C) and (F)), and an owner-occupied dwelling is "
            "excluded unless the billing carries the legend § 32-1188 sets, so state the final date for payment "
            "on the application in either case. Interest is one and "
            "one-half percent a month or fraction of a month on the unpaid balance, or a higher agreed rate "
            "(§ 32-1182(Q)), written here as the 18 percent a year it comes to. Downstream, the contractor must "
            "pay each subcontractor within seven days of receiving each progress payment, retention release or "
            "final payment (§ 32-1183(B)), with interest at the same rate from the eighth day; that second "
            "clock is not computed. The section allows only a reasonable amount for retention and sets no "
            "percentage. Read on azleg.gov."
        ),
    },
    # Virginia's Public Procurement Act gives state agencies thirty days and
    # local governments forty-five in the same definition, with different notice
    # and interest rules, so the public side is two rows.
    {
        "code": "us_va_public_state_4347",
        "jurisdiction": "Virginia, United States (public, state agencies)",
        "country_code": "US",
        "statute": "Virginia Public Procurement Act, Article 4 (prompt payment by state agencies)",
        "statute_reference": (
            "Code of Virginia §§ 2.2-4347, 2.2-4350, 2.2-4351, 2.2-4354 and 2.2-4355; "
            "https://law.lis.virginia.gov/vacode/title2.2/chapter43/section2.2-4347/ and "
            "https://law.lis.virginia.gov/vacode/title2.2/chapter43/section2.2-4355/"
        ),
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": 15,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 30,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "prescribed_rate",
        "interest_reference_rate": (
            "the statute as the Wall Street Journal prime rate (the lower of a split rate), capped under § 58.1-1812"
        ),
        "interest_margin_percent": None,
        "interest_fixed_percent": None,
        "interest_statute": "Code of Virginia § 2.2-4355",
        "notes": (
            "The clock for a payment owed by a Virginia state agency, construction included. The payment date "
            "is the one the contract sets or, where it sets none, 30 days after the agency receives a proper "
            "invoice or the goods or services, whichever is later (§ 2.2-4347), so enter the later of the two "
            "as the application date and state the final date for payment on the application where the "
            "contract fixes one. The fifteen days recorded as the payment notice deadline are the agency's: it "
            "must notify the contractor of any defect or impropriety that would prevent payment within fifteen "
            "days after receiving the invoice or the work (§ 2.2-4351), and the section attaches no consequence "
            "for the sum to a late notice. Interest accrues only on amounts still unpaid seven days after the "
            "payment date (§ 2.2-4355(A)), so the overdue warning from the final date runs a week ahead of it; "
            "the rate is the prime rate The Wall Street Journal reports, the lower one where a split rate is "
            "published, and never more than the rate set under § 58.1-1812, a cap that was not read and is not "
            "encoded. A contract may provide a different rate, and no interest runs on the part of a payment "
            "held up by a genuine disagreement. Downstream, within seven days of being paid the contractor "
            "must either pay the subcontractor its share or notify the agency and the subcontractor in writing "
            "of what it withholds and why, with interest at one percent a month on late amounts, and it must "
            "pay a subcontractor within 60 days of a proper invoice even if it has not been paid itself, giving "
            "notice by the 50th day of anything it withholds (§ 2.2-4354); that second clock is not computed. "
            "Read on law.lis.virginia.gov; §§ 2.2-4347 and 2.2-4354 were last amended in 2023 (chapters 675 "
            "and 676)."
        ),
    },
    {
        "code": "us_va_public_local_4352",
        "jurisdiction": "Virginia, United States (public, local government)",
        "country_code": "US",
        "statute": "Virginia Public Procurement Act, Article 4 (prompt payment by local governments)",
        "statute_reference": (
            "Code of Virginia §§ 2.2-4347, 2.2-4352 and 2.2-4354; "
            "https://law.lis.virginia.gov/vacode/title2.2/chapter43/section2.2-4352/"
        ),
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": 20,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 45,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "contract",
        "interest_reference_rate": "",
        "interest_margin_percent": None,
        "interest_fixed_percent": None,
        "interest_statute": "Code of Virginia § 2.2-4352",
        "notes": (
            "The clock for a payment owed by a Virginia local government, construction included. The payment "
            "date is the one the contract sets or, where it sets none, not more than forty-five days after the "
            "goods or services are received or after the invoice is rendered, whichever is later (§ 2.2-4352; "
            "§ 2.2-4347 says 45 days after the local government receives the invoice), so enter the later of "
            "the two as the application date. The twenty days recorded as the payment notice deadline are the "
            "local government's: within twenty days after receiving the invoice or the work it must notify the "
            "contractor of any defect or impropriety that would prevent payment by the payment date, and the "
            "section attaches no consequence for the sum to a late notice. The section sets no interest rate of "
            "its own: a local government that pays late must pay the finance charges the contractor assesses, "
            "unless the contract provides otherwise, and those charges may not exceed one percent a month. That "
            "is a ceiling on the contractor's own charge rather than a statutory rate, so the interest basis "
            "is contract. Downstream, the contractor-to-subcontractor rules of § 2.2-4354 are the same as for a "
            "state agency (see us_va_public_state_4347) and are not computed. Read on law.lis.virginia.gov."
        ),
    },
    {
        "code": "us_va_private_1146",
        "jurisdiction": "Virginia, United States (private)",
        "country_code": "US",
        "statute": "Code of Virginia § 11-4.6 (required payment provisions in private construction contracts)",
        "statute_reference": (
            "Code of Virginia § 11-4.6(A) and (B)(1)-(2); "
            "https://law.lis.virginia.gov/vacode/title11/chapter1/section11-4.6/"
        ),
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": 45,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 60,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "prescribed_rate",
        "interest_reference_rate": (
            "the statute as the Wall Street Journal prime rate (the lower of a split rate), capped under § 58.1-1812"
        ),
        "interest_margin_percent": None,
        "interest_fixed_percent": None,
        "interest_statute": "Code of Virginia § 11-4.6(B)(1), applying § 2.2-4355",
        "notes": (
            "The clock for private construction in Virginia, where the owner is anyone other than a public "
            "body. A construction contract between an owner and a general contractor must include a provision "
            "requiring the owner to pay within 60 days of receiving an invoice following satisfactory "
            "completion of the work invoiced (§ 11-4.6(B)(1)), so enter the date the owner received that "
            "invoice as the application date. The forty-five days recorded as the payment notice deadline are "
            "the owner's: to withhold any of it, the owner must notify the general contractor in writing within "
            "45 days of receiving the invoice, naming the contractual noncompliance and the amount withheld. "
            "The section attaches no consequence for the sum to a missed notice, so the no-notice effect is "
            "none. Where the owner and general contractor leave the provision out, subdivision (B)(1) does not "
            "say whether it applies anyway, while (B)(2) deems its own terms included in the contract. Late "
            "payment carries interest penalties consistent with § 2.2-4355, the prime-rate rule of the "
            "state-agency row, whose cap under § 58.1-1812 was not read and is not encoded. Downstream, the "
            "general contractor must pay a subcontractor within the earlier of 60 days of the subcontractor's "
            "invoice and seven days after receiving the owner's payment for that work, must give notice by the "
            "50th day of anything it withholds, and may not make the owner's payment a condition of paying the "
            "subcontractor unless the owner is insolvent (§ 11-4.6(B)(2)); on projects over $500,000 other than "
            "single-family work the same terms must flow down every tier. That second clock is not computed. "
            "The section does not affect retainage provisions. Read on law.lis.virginia.gov; its history runs "
            "from 2020 (chapter 1038) to 2026 (chapter 1040), and the 2026 chapter added subsection C on "
            "subcontractor wage liability for contracts entered into on or after 1 July 2026 without changing "
            "any payment period."
        ),
    },
    {
        "code": "bg_commercial_act_303a",
        "jurisdiction": "Bulgaria",
        "country_code": "BG",
        "statute": "Commercial Act (Търговски закон)",
        "statute_reference": "Article 303a",
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": None,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 14,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "reference_rate_plus_margin",
        "interest_reference_rate": (
            "Bulgarian National Bank base rate (основен лихвен процент), fixed on 1 January and 1 July of the current year"
        ),
        "interest_margin_percent": Decimal("10.000"),
        "interest_fixed_percent": None,
        "interest_statute": "Article 303a",
        "notes": (
            "An interest basis rather than a notice regime, the same shape as the EU Late Payment "
            "Directive this article transposes: Article 303a sets a payment term and the interest that "
            "runs when it is missed, with no payment or pay-less notice, so no_notice_effect is none. "
            "Fourteen days from receipt of the invoice or of the goods or services is the term absent "
            "agreement, written here as the final date for payment; the parties may agree a longer term "
            "up to sixty days, and beyond that only by exception in duly justified circumstances or where "
            "the nature of the goods or services requires it, so state the agreed final date on the "
            "application where a contract sets one. The statutory interest is the BNB base rate in force "
            "on 1 January or 1 July of the current year plus ten percentage points, which exceeds the "
            "Directive's own floor of eight points over the ECB reference rate: Bulgaria's transposition "
            "is stricter than the minimum, not a restatement of it, which is why this is a national row "
            "rather than a case for the eu_late_payment regime. Sourced from two independent legal "
            "practice guides rather than from the Commercial Act's own text, which this module has not "
            "independently retrieved; a reader who needs the statute's wording rather than its effect "
            "should go back to Article 303a before relying on the figures here. Whether Bulgarian public "
            "procurement carries this same period or a separate one, the way the Directive's own Article "
            "4 treats public authorities differently from transactions between undertakings, has not been "
            "checked, so this row is not confirmed for a public Bulgarian contract specifically."
        ),
    },
    {
        "code": "ng_ppa_2007",
        "jurisdiction": "Nigeria (public)",
        "country_code": "NG",
        "statute": "Public Procurement Act 2007",
        "statute_reference": "section 37",
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": None,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 60,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "contract",
        "interest_reference_rate": "",
        "interest_margin_percent": None,
        "interest_fixed_percent": None,
        "interest_statute": "",
        "notes": (
            "The clock for a payment owed by a Nigerian Ministry, Extra-Ministerial Office, government "
            "agency, parastatal or corporation on the public procurement of goods, works or services, "
            "which includes construction. Section 37(2) deems a payment delayed once it runs more than "
            "sixty days from the submission of the invoice, valuation certificate, or confirmation or "
            "authentication by the procuring entity, so enter that submission date as the application "
            "date; the sixty days is written here as the final date for payment, following the convention "
            "used for the other single-date regimes. The Act does not say whether the sixty days are "
            "calendar or working days, and this entry assumes calendar days, the reading this table gives "
            "every other statute that is silent on the point. There is no payment notice or pay-less "
            "notice in the Act, so silence carries no consequence beyond the payment becoming delayed. "
            "Section 37(3) does not fix a rate itself, it says a delayed payment attracts interest at the "
            "rate specified in the contract document, and section 37(4) obliges every contract to carry "
            "such a term, so the interest basis is contract by statutory command rather than by the Act's "
            "own silence. No private-sector statutory payment clock was found for Nigeria: this Act "
            "reaches only the procuring entities section 37(2) names, and nothing else retrieved sets a "
            "statutory period for a private Nigerian construction contract. A private clock is therefore "
            "not shipped as a second row; add one if a statute is later found rather than assuming this "
            "public clock extends to it."
        ),
    },
    {
        # Yapım İşleri Genel Şartnamesi (Ek-8 of the Yapım İşleri İhaleleri
        # Uygulama Yönetmeliği, RG 4.3.2009 no. 27159 mükerrer), art. 39(4)(f),
        # as amended by RG 30.7.2025 no. 32971, art. 25, in force 1.9.2025:
        # "Hakediş raporu ... en geç otuz gün içinde onaylandıktan sonra onay
        # tarihini izleyen otuz gün içinde tahakkuka bağlanır. Tahakkuk
        # tarihinden başlamak üzere sözleşmesinde farklı bir süre belirtilmemiş
        # ise on beş gün içinde de ödeme yapılır." Read on resmigazete.gov.tr,
        # 2026-10-10.
        "code": "tr_yigs_hakedis",
        "jurisdiction": "Türkiye (public works)",
        "country_code": "TR",
        "statute": "Yapım İşleri Genel Şartnamesi (Public Works General Conditions)",
        "statute_reference": (
            "article 39(4)(f), as amended by Resmî Gazete 30.7.2025 no. 32971, in force 1 September 2025; "
            "Tip Sözleşme article 11.2 says the same"
        ),
        "due_date_basis": "application_date",
        "due_date_days": 60,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": 30,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "due_date",
        "final_date_days": 15,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "contract",
        "interest_reference_rate": "",
        "interest_margin_percent": None,
        "interest_fixed_percent": None,
        "interest_statute": "",
        "notes": (
            "The clock for a progress payment (hakediş) under a public works contract let under Kamu İhale "
            "Kanunu 4734 and Kamu İhale Sözleşmeleri Kanunu 4735. Enter the date the contractor signed and "
            "handed in the hakediş raporu as the application date. Three periods run one after another: the "
            "administration approves the report within 30 days, the approved sum is accrued (tahakkuk) within "
            "30 days after the approval date, and it is paid within 15 days of accrual unless the contract "
            "states another period. The approval deadline is shown as the payment notice deadline and the "
            "accrual as the due date. Both are counted from the last day approval may take, so the dates "
            "computed here are the latest the conditions allow; where the report was approved earlier, the "
            "accrual and payment deadlines run from the actual approval date and come sooner. Days are "
            "calendar days. The 2025 amendment did not change the three numbers; it fixed which date each "
            "one runs from, adding 'onay tarihini izleyen' and replacing 'Bu tarihten' with 'Tahakkuk "
            "tarihinden'. A tender announced before 1 September 2025 is finished under the earlier wording "
            "(transitional article 34). There is no pay-less notice; the administration corrects the report "
            "before accrual, and the contractor objects in writing at the latest when the final account is "
            "handed in. Neither 4734, 4735 nor the conditions set interest on a late hakediş, so the interest "
            "basis is the contract; the remedy the administration usually grants is an extension of time. "
            "Pending review by a Turkish quantity surveyor."
        ),
    },
    {
        # Türk Ticaret Kanunu 6102, art. 1530(4)(a), (5) and (7), consolidated
        # text read on mevzuat.gov.tr 2026-10-10.
        "code": "tr_ttk_1530",
        "jurisdiction": "Türkiye (commercial)",
        "country_code": "TR",
        "statute": "Türk Ticaret Kanunu 6102 (Turkish Commercial Code)",
        "statute_reference": "article 1530, paragraphs 4(a), 5 and 7",
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": None,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 30,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "prescribed_rate",
        "interest_reference_rate": (
            "the Central Bank of the Republic of Türkiye (TCMB), announced each January at least eight "
            "points above the law 3095 commercial rate"
        ),
        "interest_margin_percent": None,
        "interest_fixed_percent": None,
        "interest_statute": "Türk Ticaret Kanunu 6102, article 1530(7)",
        "notes": (
            "The late-payment rule for supplies of goods and services between commercial undertakings, "
            "the Turkish transposition of the EU Late Payment Directive. Enter the date the debtor received "
            "the invoice as the application date: without any reminder the debtor is in default at the end "
            "of 30 days from it, written here as the final date for payment. The parties may agree a longer "
            "term of up to 60 days, and that cap is absolute only where the creditor is a small or "
            "medium-sized enterprise or a farm producer, or the debtor is a large enterprise; otherwise "
            "paragraph 5 lets the parties expressly agree a longer one. State the agreed final date on the "
            "application where the contract sets one. Whether article 1530 reaches a works contract (eser "
            "sözleşmesi) rather than a supply of goods or services is not stated in the law, so this row is "
            "the commercial default and not a construction-specific clock. The rate is announced yearly and "
            "is not computed here. Public works payments run on tr_yigs_hakedis instead. Pending review by "
            "a Turkish quantity surveyor."
        ),
    },
    {
        "code": "ca_on_construction_act",
        "jurisdiction": "Ontario, Canada",
        "country_code": "CA",
        "statute": "Construction Act, R.S.O. 1990, c. C.30, Part I.1",
        "statute_reference": "sections 6.1, 6.3, 6.4, 6.5, 6.6 and 6.9",
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": 14,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 28,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "applied_sum_becomes_notified_sum",
        "interest_basis": "contract",
        "interest_reference_rate": (
            "Ontario Courts of Justice Act prejudgment interest rate, applied only where the contract "
            "does not itself specify a rate"
        ),
        "interest_margin_percent": None,
        "interest_fixed_percent": None,
        "interest_statute": "Construction Act, section 6.9",
        "notes": (
            "The clock runs from the owner's receipt of a proper invoice, defined in section 6.1 and "
            "meeting seven statutory requirements plus anything the contract adds, so enter that receipt "
            "date as the application date. Payment is due within 28 days of receipt unless the owner "
            "serves a notice of non-payment, stating the amount withheld and the reasons, within 14 days; "
            "missing that 14 day window and the proper invoice must be paid in full, which is why the "
            "no-notice effect is applied_sum_becomes_notified_sum. All references to days in this Part are "
            "to calendar days, not business or working days, confirmed directly rather than assumed. "
            "These timelines are mandatory and cannot be extended by contract (section 6.9 makes the "
            "whole Part apply notwithstanding any other agreement), and they apply to contracts entered "
            "into on or after 1 October 2019. A contractor paid by the owner must pay each subcontractor "
            "within 7 days of receiving that payment (section 6.5), a downstream clock this regime does "
            "not compute, and the same 7 day pass-through and its own notice-of-non-payment sequence "
            "repeat at every lower level of the contracting pyramid. Interest is where this regime does "
            "not fit the four interest bases cleanly: section 6.9 makes the contract rate govern where "
            "the contract specifies one, and supplies the Courts of Justice Act prejudgment rate only as "
            "the default when the contract is silent, which is a contract-primary-with-statutory-fallback "
            "shape, not a floor, a ceiling, or the two compared and the greater taken. interest_basis is "
            "written here as contract, the nearest of the four, but that undersells the fact that a real "
            "statutory number applies when the contract says nothing; there is no fifth basis to name it "
            "precisely without widening the vocabulary."
        ),
    },
    # The four Canadian regimes below are split by jurisdiction because each
    # province and the federal government enacted its own prompt payment or
    # lien statute with its own clock. Ontario's Construction Act was the
    # first to bring a statutory payment period; the federal act followed in
    # 2019, Alberta in 2020, and British Columbia's Builders Lien Act has its
    # own certificate-based period. A regime in this table is one clock, which
    # is why each jurisdiction is a separate entry rather than a single
    # "Canada" row with footnotes a calculation cannot read.
    {
        "code": "ca_fed_prompt_payment",
        "jurisdiction": "Canada (federal)",
        "country_code": "CA",
        "statute": "Federal Prompt Payment for Construction Work Act, S.C. 2019, c. 29, s. 387",
        "statute_reference": "sections 4, 6 and 10",
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": None,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 28,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "reference_rate_plus_margin",
        "interest_reference_rate": "Bank of Canada overnight rate",
        "interest_margin_percent": Decimal("1.500"),
        "interest_fixed_percent": None,
        "interest_statute": "Federal Prompt Payment for Construction Work Act, section 10",
        "notes": (
            "The clock for a payment owed by the Crown on federal construction work. The Act requires "
            "payment of a proper invoice within 28 calendar days of receipt, so enter the date the Crown "
            "received the proper invoice as the application date; following the convention used for the "
            "other single-date regimes, the application date is taken as the due date and the 28-day limit "
            "as the final date for payment. A proper invoice is defined in section 4 and must meet the "
            "requirements the contract specifies, including being in a form acceptable to the contracting "
            "authority. There is no statutory payment notice or pay-less notice in the Act, so silence has "
            "no preclusive effect. Interest on late payment runs at the Bank of Canada overnight rate plus "
            "one and a half percent, which is the reference_rate_plus_margin shape. The Act also creates "
            "a downstream clock: a contractor paid by the Crown must pay its subcontractor within 28 days "
            "of the subcontractor's proper invoice, and the same pass-through applies down the chain; this "
            "regime does not compute those downstream clocks. The Act applies to contracts entered into on "
            "or after the day the prompt payment provisions came into force, and only to federal real "
            "property and federal immovables as defined in the Federal Real Property and Federal "
            "Immovables Act."
        ),
    },
    {
        "code": "ca_ab_prompt_payment",
        "jurisdiction": "Alberta, Canada",
        "country_code": "CA",
        "statute": "Prompt Payment and Construction Lien Improvement Act, S.A. 2020, c. P-26.4",
        "statute_reference": "sections 32.1, 32.2 and 32.3 of the Builders' Lien Act as amended",
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": 14,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 28,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "applied_sum_becomes_notified_sum",
        "interest_basis": "contract",
        "interest_reference_rate": "",
        "interest_margin_percent": None,
        "interest_fixed_percent": None,
        "interest_statute": "",
        "notes": (
            "The clock for a payment on construction work in Alberta, introduced by the Prompt Payment "
            "and Construction Lien Improvement Act 2020, which amended the Builders' Lien Act to add a "
            "prompt payment Part. The owner must pay a proper invoice within 28 calendar days of receipt, "
            "so enter the date the owner received the proper invoice as the application date. A notice of "
            "non-payment, stating the amount disputed and the reasons, must be served within 14 days; "
            "missing that window and the invoiced amount must be paid in full, which is why the no-notice "
            "effect is applied_sum_becomes_notified_sum, the same shape as Ontario's Construction Act. The "
            "contractor must then pay each subcontractor within 7 days of receiving payment from the owner, "
            "a downstream clock this regime does not compute. The Act does not prescribe a statutory "
            "interest rate for late payment on its own terms, so the interest basis is contract; where the "
            "contract is silent the common-law rules on pre-judgment interest apply. These provisions apply "
            "to contracts entered into on or after the date the prompt payment provisions came into force."
        ),
    },
    {
        "code": "ca_bc_builders_lien",
        "jurisdiction": "British Columbia, Canada",
        "country_code": "CA",
        "statute": "Builders Lien Act, S.B.C. 1997, c. 45",
        "statute_reference": "sections 5 and 9",
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": None,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 55,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "contract",
        "interest_reference_rate": "",
        "interest_margin_percent": None,
        "interest_fixed_percent": None,
        "interest_statute": "",
        "notes": (
            "The clock derived from the lien period in British Columbia's Builders Lien Act. Unlike "
            "Ontario and Alberta, British Columbia does not have a standalone prompt payment statute with "
            "a fixed invoice-to-payment period; the relevant statutory deadline is the 55-day window from "
            "the issuance of a certificate of completion within which a subcontractor or supplier must "
            "file a lien, and which also serves as the outer boundary for payment. Enter the date the "
            "certificate of completion was issued as the application date; the 55 calendar days is written "
            "here as the final date for payment, following the convention used for the other single-date "
            "regimes. There is no statutory payment notice or pay-less notice in the Act, so silence has "
            "no preclusive effect. The Act does not prescribe a statutory interest rate for late payment, "
            "so the interest basis is contract; where the contract is silent the Court Order Interest Act "
            "pre-judgment rate applies. British Columbia has had discussions about introducing prompt "
            "payment legislation closer to the Ontario model, but as of the date this entry was written "
            "no such statute is in force, and this lien-period-based clock is the nearest statutory "
            "deadline the province provides."
        ),
    },
    {
        "code": "in_msmed_2006",
        "jurisdiction": "India",
        "country_code": "IN",
        "statute": "Micro, Small and Medium Enterprises Development Act, 2006",
        "statute_reference": "sections 15 and 16",
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": None,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 45,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "prescribed_rate",
        "interest_reference_rate": (
            "three times the bank rate notified by the Reserve Bank of India, compounded with monthly rests"
        ),
        "interest_margin_percent": None,
        "interest_fixed_percent": None,
        "interest_statute": "Micro, Small and Medium Enterprises Development Act, 2006, section 16",
        "notes": (
            "Buyer-size-scoped rather than construction-scoped: this Act reaches any buyer purchasing "
            "goods or services, construction included, from a supplier registered as a micro or small "
            "enterprise, and reaches nothing else, so it covers only that slice of a construction "
            "contract's parties rather than the contract as such. Enter the day of acceptance, or of "
            "deemed acceptance where no objection was raised within fifteen days of delivery, as the "
            "application date. Section 15 caps any agreed payment period at forty five days from that "
            "date; this row encodes that outer limit. Whether the Act sets a shorter period when no date "
            "was agreed at all has not been confirmed and is not encoded here. There is no payment or "
            "pay-less notice in the Act, so no_notice_effect is none. Section 16 interest is compound "
            "interest with monthly rests, not simple interest, at three times the bank rate the Reserve "
            "Bank of India notifies, running from the day after the statutory period expires, and it "
            "applies notwithstanding any contrary agreement between the parties. Neither the multiplier "
            "nor the monthly compounding has a field of its own here: interest_basis, interest_margin_"
            "percent and interest_fixed_percent were built for an additive margin, a single prescribed "
            "source, or a flat annual rate, none of which is three times a rate compounding monthly, so "
            "the mechanism is written into interest_reference_rate as text rather than decomposed into "
            "the numeric fields. This costs nothing today because interest_description() only renders a "
            "sentence and nothing in this module computes an interest amount from these fields; it would "
            "cost real accuracy the day something does."
        ),
    },
    {
        "code": "ru_44fz_public",
        "jurisdiction": "Russian Federation (public procurement)",
        "country_code": "RU",
        "statute": "Federal Law 44-FZ on the contract system in public procurement (Федеральный закон № 44-ФЗ)",
        "statute_reference": "article 34 part 13.1; default interest under article 34 part 5",
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": None,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 7,
        "final_date_day_basis": "business",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "prescribed_rate",
        "interest_reference_rate": (
            "one three-hundredth of the Bank of Russia key rate (ключевая ставка) for each day of delay"
        ),
        "interest_margin_percent": None,
        "interest_fixed_percent": None,
        "interest_statute": "Federal Law 44-ФЗ, article 34 part 5",
        "notes": (
            "The clock for a payment owed by a state or municipal customer under the public procurement "
            "contract system, which covers construction works alongside goods and services. Article 34 "
            "part 13.1 gives the customer no more than seven working days from the date it signed the "
            "acceptance document (документ о приемке) to pay, so enter that signature date as the "
            "application date; following the convention used for the other single-date regimes, the "
            "application date is taken as the due date and the seven working days as the final date for "
            "payment. Working days, not calendar days, so the Russian holiday calendar has to be supplied "
            "to reproduce the statutory date - and note that the Russian working year is moved about by "
            "government decree each year, with weekends transferred to bridge holidays, which a fixed "
            "weekday rule will not reproduce on its own. Two exceptions lengthen the period and this row "
            "does not compute them: ten working days where the acceptance document was issued outside the "
            "unified procurement information system, and ten working days where settlements under the "
            "contract are subject to treasury support (казначейское сопровождение). State the final date "
            "for payment on the application in either case rather than using the computed one. The period "
            "was reduced from fifteen working days to seven by a 2022 amendment; the sources retrieved "
            "disagree on whether the commencement was 1 January or 1 May 2022 and on whether it keys off "
            "the date the procurement notice was posted, so that transition rule is not stated here as "
            "settled. It does not affect a contract procured today, and it does affect an old contract, "
            "so check the commencement before applying this row to one. There is no payment notice and no "
            "pay-less notice in the law - the customer either signs the acceptance document or serves a "
            "reasoned refusal of acceptance, and the payment clock does not start until it has signed - "
            "so no_notice_effect is none. Late payment carries пеня under article 34 part 5 at one three-"
            "hundredth of the Bank of Russia key rate on the unpaid sum for each day of delay. That is a "
            "daily fraction of a floating reference rate, which is none of the shapes the four interest "
            "bases were built for - an additive margin, a single prescribed source, or a flat annual rate "
            "- so the mechanism is written into interest_reference_rate as text and the numeric fields are "
            "left empty, the same accommodation in_msmed_2006 makes for its own compound multiplier. This "
            "costs nothing while interest_description() only renders a sentence and nothing computes an "
            "interest amount from these fields; it would cost real accuracy the day something does. No "
            "private-sector row is shipped for Russia. The Civil Code chapter on works contracts makes "
            "payment fall due on acceptance of the result (articles 711 and 746) and leaves the period "
            "itself to the parties, so there is no statutory number of days to encode for a private "
            "Russian construction contract; this is the same stance ng_ppa_2007 takes for Nigeria, and a "
            "private clock should be added only if a statute is later found rather than by assuming this "
            "public one reaches further than the customers that article 34 governs. Sourced from legal "
            "practice commentary and procurement reference guides rather than from the text of 44-ФЗ "
            "itself, which this module has not independently retrieved; a reader who needs the statute's "
            "wording rather than its effect should go to article 34 before relying on these figures."
        ),
    },
    # The two Chinese regimes below are one regulation read twice, because it
    # sets two different periods for two different payers: thirty days for a
    # government organ or public institution and sixty for a large enterprise,
    # both owed to a small or medium-sized enterprise. A regime in this table is
    # one clock, which is why VOB/B is split into an interim and a final entry
    # and why the US rows are split public from private, so this is two entries
    # rather than one entry with a footnote a calculation cannot read.
    {
        "code": "cn_sme_802_public",
        "jurisdiction": "China (government and public institution buyers, SME payees)",
        "country_code": "CN",
        "statute": (
            "Regulation on Guaranteeing Payments to Small and Medium-sized Enterprises "
            "(保障中小企业款项支付条例), State Council Order No. 802"
        ),
        "statute_reference": "article 9 paragraph 1; acceptance under article 10; interest under article 17",
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": None,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 30,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "fixed_rate",
        "interest_reference_rate": "",
        "interest_margin_percent": None,
        "interest_fixed_percent": Decimal("18.250"),
        "interest_statute": "保障中小企业款项支付条例, article 17",
        "notes": (
            "The clock for a payment owed by a government organ or a public institution (机关、事业单位) "
            "to a small or medium-sized enterprise. Payee-size-scoped rather than construction-scoped, the "
            "same shape as in_msmed_2006: the regulation reaches a buyer of goods, construction works or "
            "services from an SME supplier and reaches nothing else, so it covers that slice of a "
            "construction contract's parties rather than the contract as such. Construction works (工程) "
            "are named in the operative text alongside goods and services, so this is not an analogy from "
            "a goods statute. Article 9 sets thirty days from delivery; the contract may agree otherwise "
            "but the period may not exceed sixty days, so state the agreed final date on the application "
            "where a contract sets one. Calendar days: the text says 日, not 工作日. Where the clock "
            "actually starts is article 10 rather than the bare delivery date - the period runs from the "
            "date inspection or acceptance was passed (检验或者验收合格之日), and where the buyer lets the "
            "inspection run over, from the date the agreed inspection period expired, so that a buyer "
            "cannot postpone its own clock by sitting on the acceptance. For a construction progress "
            "claim the relevant rule is the third paragraph of article 9: where the contract settles by "
            "progress or on a periodic basis, the period runs from the date both parties confirmed the "
            "settlement amount, and that confirmation date is what should be entered as the application "
            "date. There is no payment notice and no pay-less notice in the regulation, so silence has no "
            "preclusive effect and no_notice_effect is none. Article 17 gives the default interest as a "
            "daily rate of 0.05 percent (每日利率万分之五) on late payment, written here as the 18.25 "
            "percent a year it comes to, the same conversion us_tx_private_ch28 and us_ca_private_8800 "
            "make from their monthly statutory rates. That figure is the default that applies when the "
            "contract is silent; where the parties do agree a rate, article 17 requires it to be no lower "
            "than the one-year loan prime rate published at the time the contract was concluded, which is "
            "a floor on a floating rate and is not encoded in the numeric fields. This regulation was "
            "revised by the State Council on 18 October 2024 and the revised text applies from 1 June "
            "2025; the figures here are the revised ones and should not be applied to a dispute governed "
            "by the earlier version. Sourced from the official published text of Order No. 802 and "
            "cross-checked against a second official publication of the same articles; the module has not "
            "obtained a certified translation, and a reader who needs the operative Chinese wording "
            "rather than its effect should go to articles 9, 10 and 17."
        ),
    },
    {
        "code": "cn_sme_802_large",
        "jurisdiction": "China (large enterprise buyers, SME payees)",
        "country_code": "CN",
        "statute": (
            "Regulation on Guaranteeing Payments to Small and Medium-sized Enterprises "
            "(保障中小企业款项支付条例), State Council Order No. 802"
        ),
        "statute_reference": "article 9 paragraph 2; acceptance under article 10; interest under article 17",
        "due_date_basis": "application_date",
        "due_date_days": 0,
        "due_date_day_basis": "calendar",
        "payment_notice_basis": "application_date",
        "payment_notice_days": None,
        "payment_notice_day_basis": "calendar",
        "final_date_basis": "application_date",
        "final_date_days": 60,
        "final_date_day_basis": "calendar",
        "pay_less_days": None,
        "pay_less_day_basis": "calendar",
        "no_notice_effect": "none",
        "interest_basis": "fixed_rate",
        "interest_reference_rate": "",
        "interest_margin_percent": None,
        "interest_fixed_percent": Decimal("18.250"),
        "interest_statute": "保障中小企业款项支付条例, article 17",
        "notes": (
            "The clock for a payment owed by a large enterprise (大型企业) to a small or medium-sized "
            "enterprise, the private-sector half of the same regulation. Sixty days from delivery under "
            "the second paragraph of article 9, against thirty for a public buyer, which is why this is a "
            "separate regime rather than a note on the public one. The contract may agree a different "
            "period and here there is no numeric cap: the regulation instead requires the agreed period to "
            "be reasonable by reference to industry norms and trading practice, and separately forbids "
            "making payment to the SME conditional on the buyer having received payment from a third "
            "party, or paying it pro rata as that third party pays - a statutory ban on pay-when-paid that "
            "this clock does not model but which invalidates the contract term rather than the payment "
            "obligation. Because the cap is a standard rather than a number, a contract period longer than "
            "sixty days is not automatically void and is not automatically valid either, so where a "
            "contract sets one, state the agreed final date on the application rather than relying on the "
            "computed date. The acceptance rule in article 10 and the progress-settlement rule in the "
            "third paragraph of article 9 apply identically to this regime; see cn_sme_802_public for how "
            "they move the start of the clock, which is the paragraph a construction progress claim will "
            "actually turn on. Interest, the 2024 revision and the 1 June 2025 commencement are likewise "
            "the same as the public regime, and the sourcing caveat there applies here too."
        ),
    },
)

REGIME_CODES: tuple[str, ...] = tuple(regime["code"] for regime in PAYMENT_REGIMES)


#: Country codes with a row of their own. Checked by _validate_no_regime_reasons
#: and no_regime_reason(), both of which need "does this country have a row"
#: answered without re-scanning PAYMENT_REGIMES on every call.
_COUNTRIES_WITH_A_REGIME: frozenset[str] = frozenset(
    r["country_code"] for r in PAYMENT_REGIMES if r.get("country_code")
)


def _validate_no_regime_reasons() -> None:
    """Refuse a NO_REGIME_REASONS or NO_REGIME_HELD table that contradicts itself.

    Called at import time, not deferred to seed_payment_regimes the way
    tax_engine._validate_vat_absence is deferred to _load_table. That
    precedent caution is about a table an operator can edit on disk without
    running tests, where deferring means a malformed file fails the first
    caller loudly instead of breaking import for everyone. Neither risk
    applies to a dict literal in this module: it cannot reach a deployment
    without passing ruff and the test suite first, and country_coverage.py
    probe reads NO_REGIME_REASONS directly, never through the seeder, so
    deferring the check there would leave that read path unvalidated. A
    Python literal that fails this check is broken code and should fail
    the same way a broken import does, immediately and for every caller.

    Three refusals. Unlike tax_engine, no refusal for "declares nothing":
    NO_REGIME_REASONS is opt-in for countries actually researched, not a
    closed table every country must take a stance in, so silence is the
    default for most of the world and is not an error.

    * a declared value outside NO_REGIME_VALUES;
    * a country_code that both has a row in PAYMENT_REGIMES and declares a
      reason for having none, which is the same shape of contradiction
      tax_engine._validate_vat_absence refuses, told about this table
      instead of that one, and the same check applied to NO_REGIME_HELD: a
      country with a row of its own cannot also be held;
    * a country_code in both NO_REGIME_REASONS and NO_REGIME_HELD, which
      would claim a country is simultaneously resolved and still being
      researched.

    Raises:
        ValueError: on any of the three, naming the country code.
    """
    for code, reason in NO_REGIME_REASONS.items():
        if reason not in NO_REGIME_VALUES:
            raise ValueError(
                f"country {code!r} declares a no-regime reason of {reason!r}, which is not one of "
                f"{sorted(NO_REGIME_VALUES)}"
            )
    contradicts_a_row = (set(NO_REGIME_REASONS) | NO_REGIME_HELD) & _COUNTRIES_WITH_A_REGIME
    if contradicts_a_row:
        raise ValueError(
            f"country code(s) {sorted(contradicts_a_row)} have a row in PAYMENT_REGIMES and also appear "
            f"in NO_REGIME_REASONS or NO_REGIME_HELD; those keys describe an absent row"
        )
    both = set(NO_REGIME_REASONS) & NO_REGIME_HELD
    if both:
        raise ValueError(
            f"country code(s) {sorted(both)} are in both NO_REGIME_REASONS and NO_REGIME_HELD; a country "
            f"cannot be both resolved and held"
        )


_validate_no_regime_reasons()


def regime_by_code(code: str) -> dict[str, Any] | None:
    """The shipped catalogue entry for ``code``, or ``None`` when unknown."""
    for regime in PAYMENT_REGIMES:
        if regime["code"] == code:
            return dict(regime)
    return None


def no_regime_reason(country_code: str) -> str | None:
    """Why country_code has no row in PAYMENT_REGIMES, if that is known.

    Returns one of NO_REGIME_NO_STATUTE, NO_REGIME_NOT_MODELLED or
    NO_REGIME_DIFFERENT_SHAPE for a country researched to a
    category-assignable degree with no row to show for it. Returns None for
    a country simply unresolved, which includes most of the world and, for
    now, every entry in NO_REGIME_HELD: a wrong-instrument search is not
    evidence of absence and earns no value here rather than a guessed one.

    Raises:
        ValueError: country_code has a row of its own in PAYMENT_REGIMES, so
            the question of why it has none does not apply. Mirrors
            app.modules.property_dev.tax_engine.vat_absence refusal to
            answer the same question about a jurisdiction that has a block.
    """
    code = (country_code or "").strip().upper()
    if code in _COUNTRIES_WITH_A_REGIME:
        raise ValueError(
            f"country {code!r} has a row of its own in PAYMENT_REGIMES, so its absence is not something to explain"
        )
    return NO_REGIME_REASONS.get(code)


async def seed_payment_regimes(session: AsyncSession, *, refresh: bool = False) -> dict[str, int]:
    """Insert the shipped regimes that are not in the table yet.

    Idempotent, so it is safe on every startup and safe to call from a read
    path: a regime already present is left alone unless ``refresh`` is set, in
    which case its statutory fields are rewritten from the catalogue. Refresh is
    off by default because an operator may have corrected a period to match a
    contract's own compliant terms, and a silent overwrite on next boot would
    change every date computed afterwards.

    Args:
        session: Active async session. The caller owns the transaction.
        refresh: Rewrite regimes that already exist from the shipped catalogue.

    Returns:
        Counts under ``created``, ``updated`` and ``unchanged``.
    """
    from pydantic import ValidationError
    from sqlalchemy import select

    from app.modules.payment_clock.models import PaymentRegime
    from app.modules.payment_clock.schemas import RegimeSeedRow

    existing_rows = (await session.execute(select(PaymentRegime))).scalars().all()
    existing = {row.code: row for row in existing_rows}

    created = updated = unchanged = 0
    for entry in PAYMENT_REGIMES:
        # Validated here, not only at the API boundary. seed_payment_regimes is
        # the path our own shipped catalogue takes into the table, and until
        # this line it took PaymentRegime(**entry) straight from the dict,
        # unchecked by the Literal vocabulary the API rejects submitted data
        # on. A bad value here would have seeded silently and only surfaced
        # downstream, in whichever rule happened to read it.
        try:
            RegimeSeedRow(**entry)
        except ValidationError as exc:
            raise ValueError(
                f"payment regime {entry.get('code')!r} failed schema validation and was not seeded: {exc}"
            ) from exc
        row = existing.get(entry["code"])
        if row is None:
            session.add(PaymentRegime(**entry))
            created += 1
            continue
        if not refresh:
            unchanged += 1
            continue
        for key, value in entry.items():
            setattr(row, key, value)
        updated += 1

    await session.flush()
    logger.info(
        "Payment regimes seeded: %d created, %d updated, %d unchanged",
        created,
        updated,
        unchanged,
    )
    return {"created": created, "updated": updated, "unchanged": unchanged}


__all__ = [
    "NO_REGIME_DIFFERENT_SHAPE",
    "NO_REGIME_HELD",
    "NO_REGIME_NOT_MODELLED",
    "NO_REGIME_NO_STATUTE",
    "NO_REGIME_REASONS",
    "NO_REGIME_VALUES",
    "PAYMENT_REGIMES",
    "REGIME_CODES",
    "no_regime_reason",
    "regime_by_code",
    "seed_payment_regimes",
]
