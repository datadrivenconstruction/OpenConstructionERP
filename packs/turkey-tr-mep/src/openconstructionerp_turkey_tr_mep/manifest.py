"""Build the ``PartnerPackManifest`` instance for the turkey-tr-mep pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.

This pack is the Türkiye country pack with one company shape laid over it: a
mechanical, electrical and plumbing contractor. One installation runs one pack
at a time, so the two cannot be installed side by side and this pack has to
carry the country configuration as well as the shape. It does not copy it. The
locale, currency, methodology, rule set, reference documents, cost region and
market metadata are read from the country pack's own manifest when this module
is imported, and only the fields named in ``_derive`` below are this pack's.
A correction made to the country pack reaches this one on the next start.
"""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from typing import Any

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

#: Slug and package of the pack this one is derived from.
COUNTRY_PACK_SLUG = "turkey-tr"
_COUNTRY_PACKAGE = "openconstructionerp_turkey_tr"


def _country_manifest() -> PartnerPackManifest:
    """Return the Türkiye country pack's manifest.

    Two layouts have to work. Installed from its own wheel, this pack depends
    on the country pack's distribution (see ``pyproject.toml``) and the
    package imports by name. In a source checkout, and in the community wheel
    where the pack tree sits beside the ``app`` package, no pack is on the
    import path: the core loads each ``manifest.py`` by file, so the country
    pack's is loaded the same way from its place two directories over.

    Raises:
        ImportError: If the country pack is in neither place. The core logs
            that and skips this pack, which is the correct outcome: a derived
            pack without its base has no configuration to offer.
    """
    try:
        module = importlib.import_module(f"{_COUNTRY_PACKAGE}.manifest")
    except ImportError:
        path = Path(__file__).resolve().parents[3] / COUNTRY_PACK_SLUG / "src" / _COUNTRY_PACKAGE / "manifest.py"
        spec = (
            importlib.util.spec_from_file_location("_oe_turkey_tr_mep_country_manifest", path)
            if path.is_file()
            else None
        )
        if spec is None or spec.loader is None:
            raise ImportError(
                f"The {COUNTRY_PACK_SLUG} pack is required by turkey-tr-mep and was not found "
                f"as an installed package or at {path}."
            ) from None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    manifest = module.MANIFEST
    return manifest if isinstance(manifest, PartnerPackManifest) else PartnerPackManifest(**manifest)


def _derive(base: PartnerPackManifest, **own: Any) -> PartnerPackManifest:
    """Build a manifest from ``base`` with the ``own`` fields replaced.

    Goes through the constructor rather than ``model_copy`` so every validator
    runs on the result, the profile key and the rule-set names among them.
    """
    return PartnerPackManifest(**{**base.model_dump(), **own})


_COUNTRY = _country_manifest()

MANIFEST = _derive(
    _COUNTRY,
    slug="turkey-tr-mep",
    partner_name="Turkey MEP Contractor Pack",
    # Stated here and not inherited: this is the field that decides whether a
    # pack may go out in a community artefact, and it is read from the source
    # of each manifest. No outside rights holder.
    partner_url=None,
    pack_version="0.1.0",
    # An industry pack: it describes a trade, and the Packs page files it
    # under Industry rather than as a second Türkiye country pack. The market
    # is still stated, in the inherited ``metadata["country"]``, and that is
    # the field projects, the calendar and number grouping read, not the type.
    pack_type="industry",
    description=(
        "For a mechanical, electrical and plumbing contractor in Türkiye. "
        "Carries the whole Türkiye country configuration (poz numbering, the "
        "25 percent profit and general expenses, KDV, lira, the Turkish "
        "interface) and opens every user on a short menu built around what "
        "an installer does: site records, approvals, procurement, progress "
        "claims and variations, quality and commissioning, safety, handover."
    ),
    # The menu. A user who has chosen no profile of their own opens on this
    # one's workspace: the installer's rows in the order the work runs, every
    # other screen folded under "More modules". The person who keeps the site
    # registers can pick the shorter "Site Records" profile for themselves.
    default_company_profile="mep_contractor",
    # Switched ON for the installation when the pack is applied. Every entry
    # is a non-core module the installer's menu opens, so a module an admin
    # switched off earlier comes back with the pack. Core modules cannot be
    # off and are not listed. This list is module state, not a menu.
    default_modules=[
        "oe_daily_diary",
        "oe_variations",
        "oe_contracts",
        "oe_subcontractors",
        "oe_commissioning",
        "oe_defects_liability",
        "oe_forms",
        "oe_hse_advanced",
        "oe_resources",
        "oe_equipment",
        "oe_field_time",
        "oe_site_logistics",
        "oe_site_inventory",
        "oe_cad",
        "oe_takeoff",
        "oe_dwg_takeoff",
        "oe_schedule_advanced",
        "oe_rfq_bidding",
        "oe_moc",
        "oe_claims_evidence",
    ],
    # Switched OFF for the installation, and only when the admin applying the
    # pack ticks "disable modules": the setup wizard's one-click install does
    # not send that confirmation, so there this list is reported as skipped
    # and nothing is switched off until the pack is applied from the Modules
    # page with the box ticked.
    #
    # What switching off does: the module's API is removed for every user of
    # the installation, and its menu row goes with it. What it does not do: it
    # does not shorten the menu in any way a user would notice (these 24
    # modules own nine rows between them), and it is not a per-user setting.
    # An admin switches a module back on under Modules > System Modules.
    #
    # The list is every module an installer has no use for that CAN be
    # switched off. Seventeen more are in the same class and stay on because
    # they are core modules the platform refuses to disable, and property
    # development stays on because the map module depends on it; those are
    # kept out of sight by the profile's workspace instead. Dependents come
    # before what they depend on (the two state packs before the national
    # one), because the modules are switched off in this order.
    hidden_modules=[
        # Estimating for other trades and for the client's side.
        "oe_formwork",
        "oe_rebar_schedule",
        "oe_cost_plan",
        "oe_temporary_works",
        # Public money, statutory regimes of other countries, sales rollups.
        "oe_funding",
        "oe_certified_payroll",
        "oe_payment_clock",
        "oe_carbon",
        "oe_value",
        "oe_webhook_leads",
        # A developer tool.
        "oe_architecture_map",
        # Regional data packs of markets this pack is not for. None of them
        # serves Türkiye, Hungary or Spain. Their configuration is still read
        # by the platform after the module is off; only the module's own API
        # goes.
        "oe_asia_pac_pack",
        "oe_china_pack",
        "oe_dach_pack",
        "oe_india_pack",
        "oe_latam_pack",
        "oe_mexico_pack",
        "oe_middle_east_pack",
        "oe_russia_pack",
        "oe_sa_pack",
        "oe_uk_pack",
        "oe_us_ca_pack",
        "oe_us_tx_pack",
        "oe_us_pack",
    ],
    branding=PartnerBranding(
        primary_color=_COUNTRY.branding.primary_color,
        accent_color=_COUNTRY.branding.accent_color,
        logo_path=None,  # no logo; the UI draws the monogram
        favicon_path=None,
        powered_by_text=None,
    ),
    # The country pack's onboarding script is a file in that pack, and nothing
    # in the product renders one yet. Naming it here would promise a file this
    # pack does not carry.
    onboarding_script_path=None,
    metadata={
        **_COUNTRY.metadata,
        "industry": "mep-contracting",
        "industry_name_en": "Mechanical, electrical and plumbing contracting",
        "industry_name_tr": "Mekanik ve elektrik tesisat taahhüdü",
        "derived_from": COUNTRY_PACK_SLUG,
    },
)
