"""Build the ``PartnerPackManifest`` instance for the modular-prefab pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="modular-prefab",
    partner_name="Modular & Prefab Pack",
    partner_url=None,
    pack_version="0.2.0",
    description=(
        "Pre-configured for modular construction, off-site fabrication and "
        "PMC contractors: factory-line scheduling, dimensional tolerance "
        "control, transport logistics (EU + US), inter-module assembly and "
        "phased handover. Standards: EN 1090, ICC/MBI 1200 + 1205, CSA A277, "
        "NEN 9090, AS 5104 / ISO 2394 reliability targets, ISO 19650 BIM, "
        "DfMA principles."
    ),
    default_locale="en",
    additional_locales={},
    cwicr_regions=[
        # A euro base for a pack that prices in euros; London loaded a
        # sterling catalogue into euro projects.
        "cwicr-de-berlin",
    ],
    default_currency="EUR",
    default_tax_template=None,
    validation_rule_packs=[
        "en_1090_steel",
        "as_5104_modular",
        "modular_standards",
        "factory_qc_schedule",
        "factory_qc_tolerances",
        "transport_logistics",
        "module_handover_protocol",
    ],
    default_modules=[],  # empty = show all
    hidden_modules=[],
    # Cross-region pack: no second demo shares the flagship's country, so pin
    # two EUR repeatable-housing projects. The Dutch volumetric modular-housing
    # flagship plus the 48-unit Berlin residential complex - the closest
    # repeatable, unit-based housing archetype in the same currency.
    demo_template_ids=["modular-housing", "residential-berlin"],
    branding=PartnerBranding(
        primary_color="#1F4E79",  # industrial blue
        accent_color="#FFB81C",  # modular yellow
        logo_path="logo.svg",
        favicon_path=None,
        powered_by_text=None,  # use default co-branding string
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "XX",
        "country_name_en": "Cross-region (Modular & Prefab)",
        "regulator_refs": [
            "EN 1090-1/-2/-3:2011",
            "ICC/MBI 1200-2021",
            "ICC/MBI 1205-2021",
            "CSA A277:2016",
            "NEN 9090",
            "AS 5104 / ISO 2394:2015",
            "ISO 3834 (welding)",
            "EN 1993-1-1 (Eurocode 3)",
            "EN 13670 (concrete execution)",
            "ISO 19650 (BIM information management)",
            "Buildoffsite DfMA",
        ],
        "support_email": "info@datadrivenconstruction.io",
    },
)
