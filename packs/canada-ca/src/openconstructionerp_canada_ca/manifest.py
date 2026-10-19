"""Build the ``PartnerPackManifest`` instance for the canada-ca pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="canada-ca",
    partner_name="Canada Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "CSI MasterFormat 2020 + UniFormat classification, CCDC standard-form "
        "contracts (CCDC 2/5A/14), National Building Code of Canada (NBC) 2020, "
        "CSA structural standards (A23.1/A23.3/S16), NMS National Master "
        "Specification. CAD with federal GST 5% plus provincial PST/HST. "
        "English + French UI."
    ),
    default_locale="en-CA",
    additional_locales={},
    cwicr_regions=[
        # Only cwicr-eng-toronto exists in the marketplace as of v5.6.0.
        # Vancouver, Calgary and Montreal are not yet published; when they
        # ship, add them here.
        "cwicr-eng-toronto",
    ],
    default_currency="CAD",
    default_tax_template=None,
    default_methodology="canada",
    validation_rule_packs=[
        # CSI MasterFormat 2020 division numbering
        "masterformat_2020",
        # National Building Code of Canada 2020
        "nbc_2020",
        # CCDC standard-form contracts
        "ccdc_2",
        "ccdc_5a",
        "ccdc_14",
        # CSA structural standards
        "csa_a23_1",
        "csa_a23_3",
        "csa_s16",
        # Provincial building code adoptions
        "ontario_obc",
        "quebec_ccq",
        "bc_bcbc",
        "alberta_abc",
    ],
    # The engine identifier behind the MasterFormat document above. This
    # activates the MasterFormat rule set that the core already ships.
    validation_rule_sets=[
        "masterformat",
    ],
    default_modules=[],  # empty = show all (no module hiding)
    hidden_modules=[],
    demo_template_ids=[
        "office-toronto",
        "residential-vancouver",
    ],
    branding=PartnerBranding(
        primary_color="#FF0000",  # Canadian red (flag)
        accent_color="#FFFFFF",  # Canadian white (flag)
        logo_path=None,  # no partner logo; the UI draws the country monogram
        favicon_path=None,
        powered_by_text=None,  # use default co-branding string
    ),
    # No onboarding script. This said "onboarding.yaml" and the file has never
    # existed, which is worse than it looks: the manifest reports
    # has_onboarding_script to the API, so a Canadian install was told a script
    # was there and the route then read a file that is not.
    onboarding_script_path=None,
    metadata={
        "country": "CA",
        "country_name_en": "Canada",
        "country_name_fr": "Canada",
        "classification_standard": "masterformat",
        "measurement_system": "metric",
        "regulator_refs": [
            "CSI MasterFormat 2020 (work-results classification)",
            "ASTM E1557 UniFormat II (elemental classification)",
            "National Building Code of Canada (NBC) 2020",
            "CCDC 2-2020 (Stipulated Price Contract)",
            "CCDC 5A-2025 (Construction Management - for services)",
            "CCDC 14-2013 (Design-Build Stipulated Price Contract)",
            "NMS National Master Specification",
            "CSA A23.1/A23.3 (Concrete materials and structural design)",
            "CSA S16 (Design of steel structures)",
            "CIQS Canadian Institute of Quantity Surveyors (professional practice)",
            "CCA Canadian Construction Association (industry guidance)",
        ],
        "provinces": {
            "ON": {
                "name": "Ontario",
                "building_code": "Ontario Building Code (OBC), O. Reg. 332/12",
                "tax": "HST 13% (combined GST + provincial)",
                "construction_act": "Construction Act, R.S.O. 1990, c. C.30",
            },
            "QC": {
                "name": "Quebec",
                "building_code": "Code de construction du Quebec (CCQ), chapter I",
                "tax": "GST 5% + QST 9.975%",
                "construction_act": "Act respecting labour relations, vocational training and workforce management in the construction industry (R-20)",
                "language_note": "All construction documents must be available in French (Charter of the French Language)",
            },
            "BC": {
                "name": "British Columbia",
                "building_code": "BC Building Code (BCBC) 2024",
                "tax": "GST 5% + PST 7%",
                "construction_act": "Builders Lien Act, SBC 1997, c. 45",
            },
            "AB": {
                "name": "Alberta",
                "building_code": "Alberta Building Code (ABC) 2019 (NBC 2015 adoption)",
                "tax": "GST 5% only (no provincial sales tax)",
                "construction_act": "Builders Lien Act, RSA 2000, c. B-7",
            },
        },
        "cwicr_regions_available": [
            "Toronto",
        ],
        "cwicr_regions_planned": [
            "Vancouver",
            "Calgary",
            "Montreal",
            "Ottawa",
            "Edmonton",
        ],
        "support_email": "info@datadrivenconstruction.io",
    },
)
