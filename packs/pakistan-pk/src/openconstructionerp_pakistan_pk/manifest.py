"""Build the ``PartnerPackManifest`` instance for the pakistan-pk pack."""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="pakistan-pk",
    partner_name="Pakistan Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for contractors working in Pakistan, private and public: the bill with the sales tax "
        "(federal GST on goods, provincial services tax by province) carried as a line of its own, income tax "
        "withheld from contractor payments by payee class, interim payment certificates with the 10 percent "
        "retention and the mobilization advance of the PEC standard bidding documents, the PPRA public works "
        "defaults and the Clause 70 price adjustment, marla, kanal, sft, cft and rft as units, the Pakistani "
        "public holidays, Pakistani rupee."
    ),
    default_locale="en",
    additional_locales={"ur": "locales/ur.json"},
    # No Pakistani cost base is shipped: the provincial schedules of rates are a separate decision.
    cwicr_regions=[],
    default_currency="PKR",
    default_tax_template=None,
    default_methodology="pakistan",
    validation_rule_packs=[
        "pakistan_tax",
        "pec_ppra",
    ],
    validation_rule_sets=["pakistan", "masterformat"],
    default_modules=[],
    hidden_modules=[],
    demo_template_ids=["bhu-punjab", "school-karachi"],
    branding=PartnerBranding(
        primary_color="#01411C",  # Pakistan green (flag)
        accent_color="#FFFFFF",
        logo_path=None,
        favicon_path=None,
        powered_by_text=None,
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "PK",
        "country_name_en": "Pakistan",
        "country_name_ur": "پاکستان",
        "classification_standard": "masterformat",
        "regulator_refs": [
            "Sales Tax Act, 1990 (federal, goods) and the provincial services tax laws: Punjab Sales Tax on Services Act 2012, Sindh Sales Tax on Services Act 2011, Khyber Pakhtunkhwa Sales Tax on Services Act 2022",
            "Income Tax Ordinance, 2001, section 153 (withholding on payments under a contract)",
            "Public Procurement Rules 2004 (PPRA) and the provincial procurement rules",
            "Pakistan Engineering Council Standard Bidding Documents for Procurement of Works",
        ],
        "vat_standard_rate": 18,
        "currency_decimals": 2,
        "retention_percent": 10,
        "review_status": (
            "Drawn from the published forms and the Federal Board of Revenue rate card. Every figure is "
            "flagged unconfirmed or provisional in the data tables. Pending review by a Pakistani quantity "
            "surveyor and a Pakistani tax adviser: do not rely on it for a tender or a tax filing before that review."
        ),
        "support_email": "info@datadrivenconstruction.io",
    },
)
