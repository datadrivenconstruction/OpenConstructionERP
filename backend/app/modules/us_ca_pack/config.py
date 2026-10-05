# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Regional configuration for the State of California.

Ownership note, so the tree carries one number per rule rather than two.
The national US layer lives in ``app.modules.us_pack.config`` and owns the
things that are federal or nationwide: the specification division numbering,
the elemental classification, the owner-contractor contract families, the
progress payment application, imperial units, the federal holiday list and the
national ``US_SALES_TAX`` / ``US_USE_TAX`` reference entries. This pack does
NOT re-declare any of them, and it declares ``vat_rates`` empty for the same
reason ``us_pack`` does: there is no federal VAT, so the empty dict is the
explicit opt-out signal the cross-pack completeness check reads.

The national pack carries an indicative ``7.250`` for California under
``tax_rules.examples`` and labels it the state minimum, which it is. The
authoritative treatment - that a contractor is the consumer of what it installs
as *materials* but the retailer of what it installs as a *fixture* - lives
here, because the rate does not answer the question a California bid asks.

Every rule below carries a ``statute_reference``. That field is mandatory and
the test suite fails a rule without one: an unsourced number in a tax or
retainage field is worse than silence, because a user will price work on it.

``effective_date`` follows the convention the payment-clock table already uses
for its null deadlines - the field is always present, and ``None`` is a
statement rather than an omission. A value is an ISO date (``2026-01-01``), an
ISO year-month, or a bare year where only the year of commencement is
established. ``None`` means the provision is long-standing and its commencement
was not established when this pack was written; it never means "today".

Money and rates are strings, in line with the platform money convention.
"""

from typing import Any

# The statewide base is 6.00 state plus 1.00 local jurisdiction plus 0.25 local
# transportation fund. District taxes stack on top of that base, they do not
# replace it, which is why the base is the floor and never the answer.
CA_STATE_SALES_TAX_PCT = "6.00"
CA_LOCAL_JURISDICTION_PCT = "1.00"
CA_LOCAL_TRANSPORT_FUND_PCT = "0.25"
CA_STATEWIDE_BASE_SALES_TAX_PCT = "7.25"

# Public works prevailing wage thresholds.
CA_PREVAILING_WAGE_THRESHOLD_USD = "1000"
CA_PREVAILING_WAGE_LCP_CONSTRUCTION_EXEMPTION_USD = "25000"
CA_PREVAILING_WAGE_LCP_ALTERATION_EXEMPTION_USD = "15000"

STATE_RULES: dict[str, list[dict[str, Any]]] = {
    # ── Sales and use tax ────────────────────────────────────────────────────
    "sales_tax": [
        {
            "code": "ca_statewide_base_rate",
            "name": "Statewide base sales and use tax rate",
            "description": (
                "The base rate applies everywhere in California and is made up of 6.00 percent state, "
                "1.00 percent local jurisdiction and 0.25 percent local transportation fund. It fell to "
                "7.25 percent on 1 January 2017 when the temporary quarter-percent added by the 2012 ballot "
                "measure expired. It is a floor, not a rate to quote: almost no California address pays only "
                "the base."
            ),
            "value": CA_STATEWIDE_BASE_SALES_TAX_PCT,
            "unit": "percent",
            "components": {
                "state": CA_STATE_SALES_TAX_PCT,
                "local_jurisdiction": CA_LOCAL_JURISDICTION_PCT,
                "local_transportation_fund": CA_LOCAL_TRANSPORT_FUND_PCT,
            },
            "statute_reference": "California Revenue and Taxation Code, Parts 1, 1.5 and 1.6",
            "effective_date": "2017-01-01",
        },
        {
            "code": "ca_district_tax_add_on",
            "name": "District taxes stack on the base",
            "description": (
                "Voter-approved district taxes are added to the statewide base and can themselves stack, so "
                "a single delivery address can carry several. The combined rate is a property of the address, "
                "not of the county, and the tax authority republishes the rate tables quarterly with effect "
                "from 1 January, 1 April, 1 July and 1 October. A California estimate should resolve the rate "
                "per jobsite at the quarter it will be billed in, and should not carry a single statewide "
                "figure. No district rate is hard-coded in this pack for that reason."
            ),
            "value": None,
            "unit": "percent",
            "rate_source": "tax_authority_quarterly_rate_table_by_address",
            "republished_quarterly_on": ["01-01", "04-01", "07-01", "10-01"],
            "statute_reference": "California Revenue and Taxation Code, Part 1.6 (Transactions and Use Taxes)",
            "effective_date": None,
        },
        {
            "code": "ca_contractor_is_consumer_of_materials",
            "name": "The contractor is the consumer of materials",
            "description": (
                "A construction contractor that furnishes and installs materials is the consumer of them, not "
                "the retailer. It owes tax measured by its own purchase price of the materials and charges "
                "the customer no tax on them. This is the opposite of the Texas separated contract and it is "
                "not something the parties can change by how they word the price."
            ),
            "value": None,
            "unit": None,
            "contractor_role": "consumer",
            "tax_measured_by": "contractor_purchase_price",
            "statute_reference": "18 California Code of Regulations § 1521 (Construction Contractors)",
            "effective_date": None,
        },
        {
            "code": "ca_contractor_is_retailer_of_fixtures",
            "name": "The contractor is the retailer of fixtures",
            "description": (
                "The same contractor on the same job is the retailer of the fixtures it furnishes and "
                "installs, and owes tax measured by the retail selling price. Under a lump sum contract the "
                "measure is the contractor's cost price of the fixture. The materials-versus-fixtures line is "
                "the California rule an estimator gets wrong, because it splits one invoice into two tax "
                "treatments and the split follows what the item is rather than what the contract says."
            ),
            "value": None,
            "unit": None,
            "contractor_role": "retailer",
            "tax_measured_by": "retail_selling_price",
            "lump_sum_measure": "contractor_cost_price_of_fixture",
            "statute_reference": "18 California Code of Regulations § 1521 (Construction Contractors)",
            "effective_date": None,
        },
        {
            "code": "ca_labor_excluded_from_tax_base",
            "name": "Construction labor is outside the tax base",
            "description": "The price of the labor on a construction job is excluded from the measure of tax.",
            "value": None,
            "unit": None,
            "labor_taxable": False,
            "statute_reference": "18 California Code of Regulations § 1521 (Construction Contractors)",
            "effective_date": None,
        },
    ],
    # ── Prevailing wage ──────────────────────────────────────────────────────
    "prevailing_wage": [
        {
            "code": "ca_prevailing_wage_threshold",
            "name": "Prevailing wage applies to public works over 1,000 dollars",
            "description": (
                "Workers on public works must be paid the general prevailing rate of per diem wages. The duty "
                "does not attach to a public works project of one thousand dollars or less, which is a real "
                "threshold and far lower than most people assume."
            ),
            "value": CA_PREVAILING_WAGE_THRESHOLD_USD,
            "unit": "usd",
            "statute_reference": "California Labor Code § 1771",
            "effective_date": None,
        },
        {
            "code": "ca_prevailing_wage_state_regime_distinct_from_federal",
            "name": "The state regime is its own regime",
            "description": (
                "California's prevailing wage comes from state law and the state labour department's own "
                "determinations, not from the federal construction wage statute. A federally funded "
                "California job can carry both, and where the two differ the higher rate governs. Treating a "
                "federal determination as satisfying California is the mistake this entry exists to prevent."
            ),
            "value": None,
            "unit": None,
            "rate_setting_authority": "state_industrial_relations_department",
            "statute_reference": "California Labor Code §§ 1720 to 1861, in particular § 1773",
            "effective_date": None,
        },
        {
            "code": "ca_prevailing_wage_lcp_exemption",
            "name": "Labour compliance programme exemption thresholds",
            "description": (
                "An awarding body that has been approved to run its own labour compliance programme may "
                "choose not to require prevailing wage on a public works project of 25 thousand dollars or "
                "less for construction, or 15 thousand dollars or less for alteration, demolition, repair or "
                "maintenance. The exemption is the awarding body's to elect; it is not automatic and it does "
                "not exist without the approved programme."
            ),
            "value": CA_PREVAILING_WAGE_LCP_CONSTRUCTION_EXEMPTION_USD,
            "unit": "usd",
            "construction_threshold_usd": CA_PREVAILING_WAGE_LCP_CONSTRUCTION_EXEMPTION_USD,
            "alteration_repair_maintenance_threshold_usd": CA_PREVAILING_WAGE_LCP_ALTERATION_EXEMPTION_USD,
            "requires_approved_labour_compliance_programme": True,
            "statute_reference": "California Labor Code § 1771.5",
            "effective_date": None,
        },
    ],
    # ── Retainage ────────────────────────────────────────────────────────────
    # A rule that carries ``per_payment_percent`` and ``works`` is a ceiling on
    # the retention withheld from each payment, and the contracts module reads
    # it into the rate a new contract starts from
    # (``app.modules.contracts.country_defaults.statutory_retention_ceiling``).
    # For these rules ``effective_date`` is the day from which a contract
    # ENTERED INTO binds, which is how both statutes word their reach, so it is
    # always a full ISO date. ``works`` says which regime the rule belongs to;
    # a contract does not record whether it is public or private, so a ceiling
    # reaches its defaults only on a date when every kind of works is capped.
    "retainage": [
        {
            # Pub. Contract Code § 7201(b)(1): "The retention proceeds withheld
            # from any payment by a public entity from the original contractor,
            # by the original contractor from any subcontractor, and by a
            # subcontractor from any subcontractor thereunder shall not exceed
            # 5 percent of the payment." The section "shall apply with respect
            # to all contracts entered into on or after January 1, 2012"; (b)(3)
            # and (b)(4) allow more on a project found substantially complex
            # before the bid. Source, read 2026-10-05:
            # https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=PCC&sectionNum=7201
            "code": "ca_public_retention_cap",
            "name": "Public works retention cap",
            "description": (
                "Retention proceeds withheld by a public entity from the original contractor may not exceed "
                "5 percent of the payment. The cap applies to contracts entered into on or after "
                "1 January 2012."
            ),
            "value": "5",
            "unit": "percent",
            "per_payment_percent": "5",
            "works": "public",
            "statute_reference": "California Public Contract Code § 7201",
            "effective_date": "2012-01-01",
        },
        {
            "code": "ca_public_retention_substantially_complex_exception",
            "name": "The substantially complex exception",
            "description": (
                "Retention may exceed 5 percent only where the public entity's governing body, or the "
                "department director for a state entity, made a finding before the bid that the project is "
                "substantially complex and needs a higher retention, and the bid documents set out the basis "
                "for that finding and the actual retention amount. The finding has to describe why the "
                "project is not one the agency or licensed contractors regularly perform. Where the bid "
                "documents carry no such finding, retention above 5 percent has no basis."
            ),
            "value": None,
            "unit": None,
            "requires_pre_bid_finding": True,
            "statute_reference": "California Public Contract Code § 7201",
            "effective_date": "2012-01-01",
        },
        {
            # Civ. Code § 8811, added by Stats. 2025, ch. 49 (SB 61), effective
            # January 1, 2026. (a): "This section is applicable to a contract
            # relating to a private work of improvement entered into on or after
            # January 1, 2026." (b)(1)(A): retention "withheld from a payment by
            # an owner from the direct contractor, by the direct contractor from
            # any subcontractor, and by a subcontractor from any subcontractor
            # thereunder, for a private work of improvement, shall not exceed 5
            # percent of the payment." (b)(1)(B): in total not over 5 percent of
            # the contract price. Exceptions in (b)(2) and (b)(3), carried by the
            # next rule. Source, read 2026-10-05:
            # https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=CIV&sectionNum=8811
            "code": "ca_private_retention_cap",
            "name": "Private works retention cap",
            "description": (
                "California now caps retention on private work as well. Retention may not exceed 5 percent of "
                "each individual payment, and the aggregate may not exceed 5 percent of the total contract "
                "price. The cap runs down the whole chain: owner to contractor, contractor to subcontractor, "
                "and subcontractor to lower tier. It applies to construction agreements entered into on or "
                "after 1 January 2026, so a job under an earlier agreement is not governed by it, and that is "
                "why the date is carried rather than assumed."
            ),
            "value": "5",
            "unit": "percent",
            "per_payment_percent": "5",
            "aggregate_percent": "5",
            "works": "private",
            "statute_reference": "California Civil Code § 8811, added by Senate Bill 61",
            "effective_date": "2026-01-01",
        },
        {
            "code": "ca_private_retention_cap_exclusions",
            "name": "Where the private retention cap does not reach",
            "description": (
                "The private cap does not apply to a contract for a purely residential building of four "
                "storeys or fewer; a mixed-use building, or one above four storeys, stays inside the cap. It "
                "also does not apply to a downstream contract where written notice of the bond requirement "
                "was given before bidding and the subcontractor then failed to furnish performance and "
                "payment bonds from an admitted surety insurer. The prevailing party in an action to enforce "
                "the section may recover reasonable attorney's fees."
            ),
            "value": "4",
            "unit": "storeys",
            "statute_reference": "California Civil Code § 8811, added by Senate Bill 61",
            "effective_date": "2026-01-01",
        },
        {
            "code": "ca_public_retention_release",
            "name": "Release of retention on public work",
            "description": (
                "The public entity must release the retention within 60 days after the date of completion of "
                "the work of improvement. The original contractor must then pay each subcontractor its share "
                "within seven days of receiving it, unless a bona fide dispute exists with that "
                "subcontractor. Failing to pass it on in time carries a charge of 2 percent a month on the "
                "amount wrongfully withheld."
            ),
            "value": "60",
            "unit": "days",
            "subcontractor_pass_through_days": "7",
            "penalty_percent_per_month": "2",
            "statute_reference": "California Public Contract Code § 7107",
            "effective_date": None,
        },
    ],
    # ── Prompt payment ───────────────────────────────────────────────────────
    # The day counts are also seeded as payment-clock regimes (us_ca_public_7107
    # and us_ca_private_8800) so the clock can compute real dates from them.
    "prompt_payment": [
        {
            "code": "ca_private_owner_payment",
            "name": "Owner to direct contractor, private work",
            "description": (
                "The owner must pay a progress payment within 30 days after notice demanding payment is "
                "given under the contract, where there is no good faith dispute. This one is a default rather "
                "than a floor: the owner and the direct contractor may agree a different period in writing, "
                "which the downstream deadlines do not allow. Where there is a good faith dispute the owner "
                "may withhold no more than 150 percent of the disputed amount."
            ),
            "value": "30",
            "unit": "days",
            "can_be_varied_by_written_agreement": True,
            "disputed_withholding_cap_percent": "150",
            "payment_clock_regime": "us_ca_private_8800",
            "statute_reference": "California Civil Code § 8800",
            "effective_date": None,
        },
        {
            "code": "ca_private_retention_release",
            "name": "Release of retention, private work",
            "description": "Retention on private work must be released within 45 days of completion of the work of improvement.",
            "value": "45",
            "unit": "days",
            "statute_reference": "California Civil Code § 8812",
            "effective_date": None,
        },
        {
            "code": "ca_contractor_to_subcontractor",
            "name": "Contractor to subcontractor",
            "description": (
                "A prime contractor must pay a subcontractor its share within seven days of receiving a "
                "progress payment. Violation carries a penalty of 2 percent of the amount due per month, "
                "payable to the subcontractor, on top of any other remedy, and is a ground for discipline "
                "against the licence. Where there is a good faith dispute the withholding is capped at 150 "
                "percent of the disputed amount. The section reaches private work and public work alike."
            ),
            "value": "7",
            "unit": "days",
            "penalty_percent_per_month": "2",
            "disputed_withholding_cap_percent": "150",
            "statute_reference": "California Business and Professions Code § 7108.5",
            "effective_date": None,
        },
        {
            "code": "ca_public_progress_payment",
            "name": "Local agency to contractor, public work",
            "description": (
                "A local agency that fails to make a progress payment within 30 days of receiving an "
                "undisputed and properly submitted payment request owes interest at the legal rate on "
                "judgments. Local agency covers a city, a charter city, a county, and a city and county. "
                "The agency must return an improper payment request within seven days of receipt, and every "
                "day it runs over the seven comes off the 30 it has to pay in, so a late rejection shortens "
                "the agency's own window. Progress payment here excludes the portion of the final payment "
                "the contract designates as retention, which runs on the separate clock below."
            ),
            "value": "30",
            "unit": "days",
            "improper_request_return_days": "7",
            "interest_percent_per_year": "10",
            "payment_clock_regime": "us_ca_public_20104",
            "statute_reference": (
                "California Public Contract Code § 20104.50; legal rate under Code of Civil Procedure § 685.010(a)"
            ),
            "effective_date": None,
        },
        {
            "code": "ca_public_retention_pass_through",
            "name": "Retention pass-through on public work",
            "description": (
                "Within seven days of receiving any portion of the retention proceeds the original contractor "
                "must pay each subcontractor from whom retention was withheld its share, subject to a bona "
                "fide dispute, with a 2 percent per month charge for failing to do so."
            ),
            "value": "7",
            "unit": "days",
            "penalty_percent_per_month": "2",
            "statute_reference": "California Public Contract Code § 7107",
            "effective_date": None,
        },
    ],
    # ── Mechanics lien ───────────────────────────────────────────────────────
    "lien": [
        {
            "code": "ca_preliminary_notice",
            "name": "Preliminary notice",
            "description": (
                "A claimant that has no direct contract with the owner must give preliminary notice to "
                "preserve its lien rights, and the notice reaches back only 20 days: work performed more "
                "than 20 days before the notice is given is outside what the lien can secure. Late notice "
                "therefore shortens the claim rather than destroying it."
            ),
            "value": "20",
            "unit": "days",
            "statute_reference": "California Civil Code § 8200",
            "effective_date": None,
        },
        {
            "code": "ca_lien_recording_no_notice_of_completion",
            "name": "Recording deadline where no notice of completion is recorded",
            "description": (
                "Where the owner records no notice of completion or cessation, a claimant has 90 days after "
                "completion of the work of improvement to record its claim of lien."
            ),
            "value": "90",
            "unit": "days",
            "statute_reference": "California Civil Code §§ 8412 and 8414",
            "effective_date": None,
        },
        {
            "code": "ca_lien_recording_after_notice_of_completion",
            "name": "Recording deadline where a notice of completion is recorded",
            "description": (
                "Recording a notice of completion or cessation shortens the window sharply and unevenly: the "
                "direct contractor has 60 days from the recording, every other claimant has 30. A "
                "subcontractor that is counting the 90 day period without watching for the notice will miss "
                "its lien."
            ),
            "value": "30",
            "unit": "days",
            "direct_contractor_days": "60",
            "other_claimant_days": "30",
            "statute_reference": "California Civil Code § 8414",
            "effective_date": None,
        },
        {
            "code": "ca_lien_foreclosure_suit",
            "name": "Deadline to sue to enforce the lien",
            "description": (
                "An action to enforce the lien must be commenced within 90 days after the claim of lien is "
                "recorded. The lien expires and becomes unenforceable if it is not."
            ),
            "value": "90",
            "unit": "days",
            "statute_reference": "California Civil Code § 8460",
            "effective_date": None,
        },
    ],
}

PACK_CONFIG: dict[str, Any] = {
    # ── Identity ─────────────────────────────────────────────────────────────
    # region_code follows the house form the other packs use (MX_MEXICO,
    # ZA_JOHANNESBURG); subdivision_code carries the ISO 3166-2 code, which is
    # what an external consumer matching on a standard will be looking for.
    "region_code": "US_CA",
    "subdivision_code": "US-CA",
    "subdivision_name": "California",
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
        "state_general_contractor_licence": True,
        "note": (
            "California licenses contractors at state level through its contractors licensing board, and a "
            "licence is required to bid. Contractors and subcontractors working on public works must also "
            "register separately with the state labour department before they may bid or be listed, which is "
            "a second registration and not the same thing as the licence."
        ),
        "statute_reference": "California Business and Professions Code § 7000 et seq.; California Labor Code § 1725.5",
        "effective_date": None,
    },
    # ── State rules ──────────────────────────────────────────────────────────
    "state_rules": STATE_RULES,
    # ── Payment clock regimes this state seeds ───────────────────────────────
    "payment_clock_regimes": ["us_ca_public_20104", "us_ca_private_8800"],
    # ── VAT rates ────────────────────────────────────────────────────────────
    # No federal VAT in the United States. Empty dict is the explicit opt-out
    # signal the cross-pack completeness check reads, same as us_pack.
    "vat_rates": {},
}
