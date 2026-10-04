"""Build the ``PartnerPackManifest`` instance for the South Africa pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.

This is DataDrivenConstruction's first African market pack. It is built
entirely from public South African standards and regulations. The idea and
a reference implementation were contributed by Aidan Koetaan.
The implementation here is our own.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="south-africa",
    partner_name="South Africa Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for South African construction: SANS 1200 civil works "
        "and ASAQS building measurement, CIDB contractor grading (1 to 9), the "
        "PPPFA 80/20 and 90/10 preferential procurement scoring, National "
        "Treasury infrastructure delivery gates, nine province cost regions, "
        "and ZAR with 15 percent VAT. The first pack in DataDrivenConstruction's "
        "African coverage."
    ),
    default_locale="en-ZA",
    additional_locales={
        "en-ZA": "locales/en-ZA.json",
    },
    # ZA_JOHANNESBURG is the canonical CWICR region for South Africa (currency
    # ZAR). The data is published: cost rows download on demand from the CWICR
    # repo and the BGE-M3 vector snapshot loads via scripts.seed_cwicr_v3.
    cwicr_regions=[
        "cwicr-eng-johannesburg",
    ],
    default_currency="ZAR",
    default_tax_template="za_vat_15",
    # Absent until now, so the pack shipped the SANS and ASAQS measurement
    # rules and the CIDB grading and then priced with a method belonging to no
    # country. The template existed the whole time and nothing named it.
    #
    # The South African template is still the neutral international method
    # carrying ZAR and 15 percent VAT, by its own description, rather than the
    # ASAQS convention the rest of this pack is about. It is the right pointer
    # to hold today and becomes the national method without an edit here once
    # the markup table states the ZA stack.
    default_methodology="south_africa",
    validation_rule_packs=[
        "sans_1200_measurement",
        "asaqs_measurement",
        "cidb_grading",
        "pppfa_preferential_procurement",
        "ipdm_procurement_gates",
    ],
    # The documents above are reference text the engine never executes. This
    # is the list that switches rules on. ASAQS measurement is in the NRM
    # lineage, which is what the classification registry and the ZA country
    # row already give a South African project.
    validation_rule_sets=["nrm"],
    default_modules=[],  # empty = show all
    hidden_modules=[],
    # No bundled SA demo project yet: an empty list keeps the default
    # flagship plus country-fill behaviour rather than seeding a fabricated one.
    demo_template_ids=[],
    branding=PartnerBranding(
        primary_color="#007749",  # South African flag green
        accent_color="#FFB81C",  # South African gold
        logo_path="logo.svg",
        favicon_path=None,
        powered_by_text=None,  # use default co-branding string
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "ZA",
        "country_name_en": "South Africa",
        "iso_3166_1_alpha_2": "ZA",
        "vat_rate_pct": 15.0,
        "vat_effective_from": "2018-04-01",
        "measurement_system": "metric",
        "paper_size": "A4",
        # 12 official languages (South African Sign Language was added in 2023);
        # the pack ships English and lists the rest for future locale packs.
        "official_languages": [
            "English (en)",
            "isiZulu (zu)",
            "isiXhosa (xh)",
            "Afrikaans (af)",
            "Sepedi (nso)",
            "Setswana (tn)",
            "Sesotho (st)",
            "Xitsonga (ts)",
            "siSwati (ss)",
            "Tshivenda (ve)",
            "isiNdebele (nr)",
            "South African Sign Language (sasl)",
        ],
        "provinces": [
            "Eastern Cape",
            "Free State",
            "Gauteng",
            "KwaZulu-Natal",
            "Limpopo",
            "Mpumalanga",
            "North West",
            "Northern Cape",
            "Western Cape",
        ],
        "regulator_refs": [
            "SANS 1200 Standardized Specification for Civil Engineering Construction (SABS)",
            "ASAQS Standard System of Measuring Building Work (Association of South African Quantity Surveyors)",
            "Construction Industry Development Board Act 38 of 2000 (CIDB grading 1 to 9)",
            "Preferential Procurement Policy Framework Act 5 of 2000 and the 2022 Regulations (PPPFA 80/20 and 90/10)",
            "National Treasury Framework for Infrastructure Delivery and Procurement Management (FIDPM 2019)",
            "Value-Added Tax Act 89 of 1991 (SARS, standard rate 15 percent)",
        ],
        # CIDB endorses a contract suite; SA public works commonly uses GCC 2015
        # and the NEC suite, with JBCC on the building side and FIDIC on larger
        # international-style works.
        "endorsed_contract_suite": ["JBCC", "GCC 2015 (SAICE)", "NEC4", "FIDIC"],
        "default_contract": "GCC 2015",
        "support_email": "info@datadrivenconstruction.io",
        # Credit for the proposal and reference implementation. The shipped pack
        # is written from the public standards (see CONTRIBUTORS.md).
        "acknowledgements": [
            "Proposed by Aidan Koetaan",
        ],
    },
)
