# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Regional configuration for the State of Texas.

Ownership note, so the tree carries one number per rule rather than two.
The national US layer lives in ``app.modules.us_pack.config`` and owns the
things that are federal or nationwide: the specification division numbering,
the elemental classification, the owner-contractor contract families, the
progress payment application, imperial units, the federal holiday list and the
national ``US_SALES_TAX`` / ``US_USE_TAX`` reference entries. This pack does
NOT re-declare any of them. It adds the Texas depth an estimator actually gets
wrong, and it deliberately omits ``vat_rates`` content for the same reason
``us_pack`` does: there is no federal VAT, so the empty dict is the explicit
opt-out signal the cross-pack completeness check reads.

The national pack carries an *indicative* ``6.250`` for Texas under
``tax_rules.examples``. That entry stays what it is, a headline state rate for
a comparison table. The authoritative Texas treatment - who owes the tax on
materials, and how that flips between a lump sum and a separated contract -
lives here, because the rate alone does not answer the question a bid asks.

Every rule below carries a ``statute_reference``. That field is mandatory and
the test suite fails a rule without one: an unsourced number in a tax or
retainage field is worse than silence, because a user will price work on it.

``effective_date`` follows the convention the payment-clock table already uses
for its null deadlines - the field is always present, and ``None`` is a
statement rather than an omission. A value is an ISO date (``2021-06-15``), an
ISO year-month, or a bare year where only the year of commencement is
established. ``None`` means the provision is long-standing and its commencement
was not established when this pack was written; it never means "today".

Money and rates are strings, in line with the platform money convention.
"""

from typing import Any

# The state rate has stood at 6.25 percent since 1990; local jurisdictions may
# stack up to 2 percent on top, which is why 8.25 is the ceiling a Texas bid
# ever has to price and 6.25 is the floor.
TX_STATE_SALES_TAX_PCT = "6.25"
TX_LOCAL_SALES_TAX_CAP_PCT = "2.00"
TX_MAX_COMBINED_SALES_TAX_PCT = "8.25"

# Public-works retainage caps turn on one contract-value threshold, and the
# subchapter itself does not reach small contracts at all.
TX_RETAINAGE_THRESHOLD_USD = "5000000"
TX_RETAINAGE_SUBCHAPTER_FLOOR_USD = "400000"

STATE_RULES: dict[str, list[dict[str, Any]]] = {
    # ── Sales and use tax ────────────────────────────────────────────────────
    "sales_tax": [
        {
            "code": "tx_state_sales_tax_rate",
            "name": "State sales and use tax rate",
            "description": "The Texas state rate applied to taxable sales and uses before any local rate.",
            "value": TX_STATE_SALES_TAX_PCT,
            "unit": "percent",
            "statute_reference": "Texas Tax Code § 151.051",
            "effective_date": "1990",
        },
        {
            "code": "tx_local_sales_tax_cap",
            "name": "Local sales and use tax ceiling",
            "description": (
                "Cities, counties, transit authorities and special purpose districts may impose local sales "
                "and use tax, but the combined local rate at any one location may not exceed 2 percent, so the "
                "combined state and local rate never exceeds 8.25 percent."
            ),
            "value": TX_LOCAL_SALES_TAX_CAP_PCT,
            "unit": "percent",
            "max_combined_percent": TX_MAX_COMBINED_SALES_TAX_PCT,
            "statute_reference": "Texas Tax Code Chapters 321, 322 and 323",
            "effective_date": None,
        },
        {
            "code": "tx_new_construction_lump_sum",
            "name": "New construction under a lump sum contract",
            "description": (
                "Under a lump sum contract the contractor is the consumer of the materials it incorporates "
                "into the customer's real property. It pays sales tax to its supplier when it buys them and "
                "collects no tax from the customer on any part of the contract price. The tax is therefore a "
                "cost inside the bid, not a line added to it."
            ),
            "value": None,
            "unit": None,
            "who_owes_tax_on_materials": "contractor",
            "tax_collected_from_customer": False,
            "statute_reference": "34 Texas Administrative Code § 3.291 (Comptroller rule, Contractors)",
            "effective_date": None,
        },
        {
            "code": "tx_new_construction_separated",
            "name": "New construction under a separated contract",
            "description": (
                "A separated contract divides the price into at least a charge for materials and a charge for "
                "skill and labor. The contractor is then the seller of the materials: it buys them tax free "
                "for resale and collects sales tax from the customer on the materials charge. Labor to build "
                "new real property is not taxable, so the labor charge carries no tax."
            ),
            "value": None,
            "unit": None,
            "who_owes_tax_on_materials": "customer",
            "tax_collected_from_customer": True,
            "statute_reference": "34 Texas Administrative Code § 3.291 (Comptroller rule, Contractors)",
            "effective_date": None,
        },
        {
            "code": "tx_residential_repair_remodel",
            "name": "Repair, remodeling and restoration of residential real property",
            "description": (
                "Labor to repair, remodel or restore residential real property is not taxable, and the "
                "contractor is the consumer of the materials it uses. Residential covers family dwellings, "
                "apartment complexes, nursing homes, condominiums and retirement homes, but not hotels or "
                "lettings of less than 30 days."
            ),
            "value": None,
            "unit": None,
            "labor_taxable": False,
            "statute_reference": "34 Texas Administrative Code § 3.357",
            "effective_date": None,
        },
        {
            "code": "tx_nonresidential_repair_remodel",
            "name": "Repair, remodeling and restoration of nonresidential real property",
            "description": (
                "The total amount charged to remodel, repair or restore nonresidential real property is "
                "taxable, labor included. This is the reverse of the new-construction rule and the reverse of "
                "the residential rule, and it is the single most common Texas mis-pricing: an office or retail "
                "fit-out that is a repair rather than new construction carries tax on the whole invoice, not "
                "just on the materials. Separately stated building permit fees are the usual exclusion."
            ),
            "value": None,
            "unit": None,
            "labor_taxable": True,
            "statute_reference": "34 Texas Administrative Code § 3.357",
            "effective_date": None,
        },
    ],
    # ── Income tax ───────────────────────────────────────────────────────────
    "income_tax": [
        {
            "code": "tx_no_individual_income_tax",
            "name": "No state tax on individual income",
            "description": (
                "The legislature may not impose a tax on the net incomes of individuals, including an "
                "individual's share of partnership and unincorporated association income. Proposition 4, "
                "approved on 5 November 2019, replaced the older referendum requirement with a flat "
                "prohibition. Labor burden built for a Texas project therefore carries no state income "
                "withholding line."
            ),
            "value": "0",
            "unit": "percent",
            "statute_reference": "Texas Constitution, Article VIII, Section 24-a",
            "effective_date": "2019-11-05",
        },
    ],
    # ── Prevailing wage ──────────────────────────────────────────────────────
    "prevailing_wage": [
        {
            "code": "tx_prevailing_wage_required",
            "name": "Prevailing wage on public work",
            "description": (
                "A worker employed on a public work by or on behalf of the state or a political subdivision "
                "must be paid not less than the general prevailing rate of per diem wages for the locality. "
                "The chapter reaches any public work paid for wholly or partly from public funds and states "
                "no minimum contract value, so there is no Texas equivalent of a dollar threshold below "
                "which the duty falls away."
            ),
            "value": None,
            "unit": None,
            "minimum_contract_value_usd": None,
            "statute_reference": "Texas Government Code §§ 2258.002 and 2258.021",
            "effective_date": None,
        },
        {
            "code": "tx_prevailing_wage_determination",
            "name": "Who sets the rate",
            "description": (
                "Texas runs a decentralised regime and this is the sharpest contrast with California. There "
                "is no state wage-determination body. The public body awarding the contract determines the "
                "rate itself, either by surveying wages paid on similar projects in the political "
                "subdivision, or by adopting the federal determination for the locality. Two Texas cities "
                "can therefore carry different rates for the same craft in the same month, and the rate has "
                "to be read from the awarding body's contract documents rather than from a state schedule."
            ),
            "value": None,
            "unit": None,
            "methods": ["local_wage_survey", "federal_locality_determination"],
            "statute_reference": "Texas Government Code § 2258.022(a)",
            "effective_date": None,
        },
        {
            "code": "tx_prevailing_wage_penalty",
            "name": "Underpayment penalty",
            "description": (
                "A contractor or subcontractor owes the public body 60 dollars for each worker employed for "
                "each calendar day, or part of a day, that the worker is paid less than the rate stipulated "
                "in the contract."
            ),
            "value": "60",
            "unit": "usd_per_worker_per_day",
            "statute_reference": "Texas Government Code § 2258.023(b)",
            "effective_date": None,
        },
    ],
    # ── Retainage ────────────────────────────────────────────────────────────
    "retainage": [
        {
            "code": "tx_public_retainage_cap_below_threshold",
            "name": "Public works retainage cap, contract under 5 million dollars",
            "description": (
                "A governmental entity may not withhold retainage exceeding 10 percent of the contract price "
                "where the contract price is less than 5 million dollars, and no line in a bid schedule or "
                "schedule of values may carry a higher rate than the contract cap."
            ),
            "value": "10",
            "unit": "percent",
            "applies_when_contract_value_usd_below": TX_RETAINAGE_THRESHOLD_USD,
            "statute_reference": "Texas Government Code § 2252.032",
            "effective_date": "2021-06-15",
        },
        {
            "code": "tx_public_retainage_cap_at_or_above_threshold",
            "name": "Public works retainage cap, contract of 5 million dollars or more",
            "description": (
                "Where the contract price is 5 million dollars or more the cap falls to 5 percent. The "
                "threshold is on the contract price, not on the individual payment, so a large job carries "
                "the lower cap from its first application."
            ),
            "value": "5",
            "unit": "percent",
            "applies_when_contract_value_usd_at_or_above": TX_RETAINAGE_THRESHOLD_USD,
            "statute_reference": "Texas Government Code § 2252.032",
            "effective_date": "2021-06-15",
        },
        {
            "code": "tx_public_retainage_dam_exception",
            "name": "Dam-related contracts",
            "description": (
                "A contract for work related to a dam carries a 10 percent cap whatever the contract price, "
                "so the 5 million dollar threshold does not pull it down to 5 percent."
            ),
            "value": "10",
            "unit": "percent",
            "statute_reference": "Texas Government Code § 2252.032",
            "effective_date": "2021-06-15",
        },
        {
            "code": "tx_public_retainage_interest_bearing_account",
            "name": "Retainage above 5 percent must earn interest",
            "description": (
                "Where a public works contract provides for retainage exceeding 5 percent of the periodic "
                "contract payments, the governmental entity must deposit the retainage in an interest-bearing "
                "account. A job under the 10 percent cap is therefore usually also an interest-bearing-account "
                "job, which is a cash-flow fact worth carrying into the forecast."
            ),
            "value": "5",
            "unit": "percent",
            "statute_reference": "Texas Government Code § 2252.032",
            "effective_date": "2021-06-15",
        },
        {
            "code": "tx_public_retainage_subchapter_exemptions",
            "name": "Where the retainage subchapter does not reach",
            "description": (
                "The subchapter does not apply to a public works contract whose total contract price estimate "
                "at execution is less than 400 thousand dollars, to contracts of the state transportation "
                "department, or to contracts executed before 31 August 1981. Below that floor the caps above "
                "are not the governing rule and the contract terms are."
            ),
            "value": TX_RETAINAGE_SUBCHAPTER_FLOOR_USD,
            "unit": "usd",
            "statute_reference": "Texas Government Code § 2252.033",
            "effective_date": "2021-06-15",
        },
    ],
    # ── Prompt payment ───────────────────────────────────────────────────────
    # The day counts are also seeded as payment-clock regimes (us_tx_public_2251
    # and us_tx_private_ch28) so the clock can compute real dates from them.
    "prompt_payment": [
        {
            "code": "tx_public_owner_payment",
            "name": "Governmental entity to prime contractor",
            "description": (
                "A payment by a governmental entity becomes overdue on the 31st day after the later of the "
                "date it receives the goods or the services are completed, and the date it receives the "
                "invoice. That is 30 days to pay."
            ),
            "value": "30",
            "unit": "days",
            "payment_clock_regime": "us_tx_public_2251",
            "statute_reference": "Texas Government Code § 2251.021(a)",
            "effective_date": None,
        },
        {
            "code": "tx_public_owner_payment_infrequent_body",
            "name": "Governmental entity whose governing body meets monthly or less",
            "description": (
                "Where the political subdivision's governing body meets only once a month or less often, the "
                "payment becomes overdue on the 46th day instead, which is 45 days to pay."
            ),
            "value": "45",
            "unit": "days",
            "statute_reference": "Texas Government Code § 2251.021(b)",
            "effective_date": None,
        },
        {
            "code": "tx_public_sub_payment",
            "name": "Prime contractor to subcontractor, public work",
            "description": (
                "A vendor paid by a governmental entity must pay each subcontractor its appropriate share "
                "not later than the 10th day after it receives the payment; the share is overdue on the 11th."
            ),
            "value": "10",
            "unit": "days",
            "statute_reference": "Texas Government Code § 2251.022",
            "effective_date": None,
        },
        {
            "code": "tx_public_interest",
            "name": "Interest on an overdue public payment",
            "description": (
                "Interest accrues at one percent above the prime rate published in the Wall Street Journal on "
                "the first business day of July of the preceding fiscal year. The rate is fixed on 1 September "
                "for the whole fiscal year, is simple rather than compounded, and stops on the date the payment "
                "is sent. The margin is the durable number here; the resulting rate changes every year and must "
                "be read from the comptroller's published figure rather than stored."
            ),
            "value": "1",
            "unit": "percent_above_reference",
            "reference_rate": "Wall Street Journal prime rate",
            "statute_reference": "Texas Government Code § 2251.025",
            "effective_date": None,
        },
        {
            "code": "tx_private_owner_payment",
            "name": "Owner to contractor, private work",
            "description": (
                "On private work the owner must pay the amount owed not later than the 35th day after it "
                "receives the contractor's written request for payment."
            ),
            "value": "35",
            "unit": "days",
            "payment_clock_regime": "us_tx_private_ch28",
            "statute_reference": "Texas Property Code § 28.002(a)",
            "effective_date": None,
        },
        {
            "code": "tx_private_sub_payment",
            "name": "Contractor to subcontractor, private work",
            "description": (
                "The contractor must pay its subcontractor not later than the seventh day after it receives "
                "the owner's payment."
            ),
            "value": "7",
            "unit": "days",
            "statute_reference": "Texas Property Code § 28.002(b)",
            "effective_date": None,
        },
        {
            "code": "tx_private_interest",
            "name": "Interest on an overdue private payment",
            "description": "An unpaid amount bears interest at one and a half percent each month, which is 18 percent a year.",
            "value": "1.5",
            "unit": "percent_per_month",
            "statute_reference": "Texas Property Code § 28.004(b)",
            "effective_date": None,
        },
        {
            "code": "tx_private_no_waiver",
            "name": "The private prompt payment chapter cannot be contracted away",
            "description": (
                "An attempted waiver of a provision of the chapter is void, with a limited exception for "
                "certain single-family residential contracts. A subcontract clause that purports to displace "
                "the 35 day and 7 day clocks does not do so."
            ),
            "value": None,
            "unit": None,
            "waivable": False,
            "statute_reference": "Texas Property Code § 28.006",
            "effective_date": None,
        },
    ],
    # ── Mechanic's lien ──────────────────────────────────────────────────────
    "lien": [
        {
            "code": "tx_lien_affidavit_residential",
            "name": "Lien affidavit deadline, residential construction",
            "description": (
                "The affidavit must be filed not later than the 15th day of the third calendar month after "
                "the month in which the original contractor's work was completed, terminated or abandoned, "
                "or, for any other claimant, the month it last provided labor or materials. The deadline "
                "is a day of a month rather than a count of days, so it cannot be computed by adding a "
                "period to a date."
            ),
            "value": "3",
            "unit": "months_to_fifteenth_day",
            "statute_reference": "Texas Property Code § 53.052",
            "effective_date": "2022-01-01",
        },
        {
            "code": "tx_lien_affidavit_nonresidential",
            "name": "Lien affidavit deadline, non-residential",
            "description": (
                "For non-residential work the affidavit must be filed not later than the 15th day of the "
                "fourth calendar month after the month in which the original contractor's work was completed, "
                "terminated or abandoned, or, for any other claimant, the month it last provided labor or "
                "materials."
            ),
            "value": "4",
            "unit": "months_to_fifteenth_day",
            "statute_reference": "Texas Property Code § 53.052",
            "effective_date": "2022-01-01",
        },
        {
            "code": "tx_lien_foreclosure_suit",
            "name": "Deadline to sue to foreclose the lien",
            "description": (
                "Suit must be brought not later than the first anniversary of the last day the claimant could "
                "have filed the lien affidavit. The parties may extend that to the second anniversary of the "
                "date the affidavit was filed, by a written agreement with the owner recorded before the "
                "original deadline runs out."
            ),
            "value": "1",
            "unit": "years",
            "extension_years": "2",
            "statute_reference": "Texas Property Code § 53.158",
            "effective_date": "2022-01-01",
        },
        {
            "code": "tx_lien_2022_amendments_scope",
            "name": "The 2022 amendments do not reach older contracts",
            "description": (
                "The 2021 rewrite of the lien chapter took effect on 1 January 2022 and is not retroactive: "
                "it applies to liens arising from an original contract executed on or after that date. A "
                "project running under an earlier original contract is still read against the previous "
                "deadlines, which is why the effective date is carried here rather than assumed."
            ),
            "value": None,
            "unit": None,
            "statute_reference": "Texas Property Code Chapter 53, as amended by Acts 2021, 87th Leg., H.B. 2237",
            "effective_date": "2022-01-01",
        },
    ],
}

PACK_CONFIG: dict[str, Any] = {
    # ── Identity ─────────────────────────────────────────────────────────────
    # region_code follows the house form the other packs use (MX_MEXICO,
    # ZA_JOHANNESBURG); subdivision_code carries the ISO 3166-2 code, which is
    # what an external consumer matching on a standard will be looking for.
    "region_code": "US_TX",
    "subdivision_code": "US-TX",
    "subdivision_name": "Texas",
    "countries": ["US"],
    "parent_pack": "oe_us_pack",
    "default_currency": "USD",
    "default_locale": "en-US",
    "measurement_system": "imperial",
    "paper_size": "Letter",
    "date_format": "MM/DD/YYYY",
    "number_format": "1,234.56",
    # ── Licensing ────────────────────────────────────────────────────────────
    "contractor_licensing": {
        "state_general_contractor_licence": False,
        "note": (
            "Texas issues no state general-contractor licence. Trades that carry real risk are licensed at "
            "state level, electrical and plumbing and HVAC among them, and general contracting is licensed by "
            "the city where a city licenses it at all. A Texas bid therefore has to name the municipality, not "
            "just the state, before the licensing position can be answered."
        ),
        "statute_reference": "Texas Occupations Code (trade-specific chapters)",
        "effective_date": None,
    },
    # ── State rules ──────────────────────────────────────────────────────────
    "state_rules": STATE_RULES,
    # ── Payment clock regimes this state seeds ───────────────────────────────
    "payment_clock_regimes": ["us_tx_public_2251", "us_tx_private_ch28"],
    # ── VAT rates ────────────────────────────────────────────────────────────
    # No federal VAT in the United States. Empty dict is the explicit opt-out
    # signal the cross-pack completeness check reads, same as us_pack.
    "vat_rates": {},
}
