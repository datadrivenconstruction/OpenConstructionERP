# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PartnerPackManifest - the Pydantic schema each partner pack exports."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Shape of a validation rule-set identifier as the engine registers it: a
# lower-case name, digits and underscores allowed after the first letter.
# Project-scoped sets (``ids_custom:{project_id}``) exist in the registry but
# are never something a pack can name, so the colon form is not accepted here.
_RULE_SET_NAME = re.compile(r"[a-z][a-z0-9_]*")

# The four pack "types" under the Packs umbrella. A pack is one of:
#   country   - a country/region preset (locale, currency, cost regions, rules)
#   industry  - a trade/sector preset (formwork, renewables, modular, ...)
#   partner   - a co-branded preset for a named partner organisation
#   showcase  - an internal demo/showcase preset
# The old "Partner Packs" feature is now just the ``partner`` type; ``country``
# and ``industry`` already shipped as partner packs and keep working unchanged.
PackType = Literal["country", "industry", "partner", "showcase"]

#: The value a pack puts in ``metadata["country"]`` to say it spans regions
#: rather than to name one. It reads like a country code and means the opposite
#: of one, so both readers below go through this name rather than the literal.
_CROSS_REGION_MARKER = "XX"


class PartnerBranding(BaseModel):
    """Branding overrides applied at runtime when a pack is active."""

    primary_color: str = Field(
        default="#0F2C5F",
        description="Hex (#RRGGBB). Replaces --oe-primary at boot.",
    )
    accent_color: str | None = Field(
        default=None,
        description="Optional secondary brand colour. Replaces --oe-accent.",
    )
    favicon_path: str | None = Field(
        default=None,
        description="Path inside the pack package to a favicon. Streamed via /api/v1/partner-pack/favicon.",
    )
    logo_path: str | None = Field(
        default=None,
        description=(
            "Path inside the pack package to the partner logo. Streamed via "
            "/api/v1/partner-pack/logo. None means the pack ships no logo and "
            "the UI draws its monogram instead. This defaulted to 'logo.svg', "
            "which made 'no logo' impossible to express: a pack that omitted "
            "the field declared the same path as one that wrote it out, so a "
            "pack without the file could not stop promising it."
        ),
    )
    powered_by_text: str | None = Field(
        default=None,
        description=(
            "Co-branding line shown next to the partner logo. "
            "Defaults to 'Powered by OpenConstructionERP · In partnership with {partner_name}'."
        ),
    )


class PartnerPackManifest(BaseModel):
    """Manifest exported by a partner pack via the entry-point group.

    The pack's ``pyproject.toml`` declares::

        [project.entry-points."openconstructionerp.partner_packs"]
        batimatech-ca = "openconstructionerp_batimatech_ca:MANIFEST"

    where ``MANIFEST`` is a module-level ``PartnerPackManifest`` instance
    (or a dict the loader coerces into one).
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    slug: str = Field(
        ...,
        description="Stable lowercase identifier, e.g. 'batimatech-ca'.",
        pattern=r"^[a-z][a-z0-9\-]{2,40}$",
    )
    partner_name: str = Field(
        ...,
        description="Display name of the partner organisation.",
        min_length=2,
        max_length=80,
    )
    partner_url: str | None = Field(
        default=None,
        description="Partner homepage. Used as the link target on the logo strip.",
    )
    pack_version: str = Field(
        default="0.1.0",
        description="Pack version (semver). Independent of core version.",
    )
    pack_type: PackType | None = Field(
        default=None,
        description=(
            "Pack type under the Packs umbrella: 'country', 'industry', "
            "'partner' or 'showcase'. Optional for backward compatibility: "
            "old manifests that omit it get a type inferred from their other "
            "fields (see ``_infer_pack_type``). The resolved value is always "
            "available via the ``type`` property."
        ),
    )
    description: str = Field(
        default="",
        description="One-paragraph human-readable description (English).",
        max_length=800,
    )

    # Locale & region presets
    default_locale: str = Field(
        default="en",
        description="BCP-47 locale code used as the new boot default.",
        min_length=2,
        max_length=10,
    )
    additional_locales: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Optional extra locales the pack ships. Mapping locale_code -> path inside the pack package to a JSON file."
        ),
    )

    # Cost DB presets
    cwicr_regions: list[str] = Field(
        default_factory=list,
        description="CWICR marketplace slugs to preload, e.g. ['cwicr-eng-toronto'].",
    )
    default_currency: str = Field(
        default="EUR",
        description="ISO 4217 default currency.",
        pattern=r"^[A-Z]{3}$",
    )
    default_tax_template: str | None = Field(
        default=None,
        description=(
            "Documentation only: a label for the tax regime the pack's market "
            "applies, e.g. 'ca_gst_pst'. Nothing resolves it. There is no "
            "registry of tax-template slugs anywhere in the platform, so the "
            "string travels to the pack preview panel and stops there, and "
            "applying the pack says as much in its warnings. It used to be "
            "described as a slug 'to set as default', which reads as a setting "
            "that will be applied and is why this note is long. The rate that "
            "actually reaches money is the tax line in the market's markup "
            "stack (app.modules.boq.markup_templates), overridable per project; "
            "changing this field changes no number anywhere."
        ),
    )
    default_methodology: str | None = Field(
        default=None,
        description=(
            "Slug of a built-in estimating-methodology template (see "
            "app.modules.methodology.templates - e.g. 'germany', "
            "'united_states', 'uzbekistan', 'railway_infrastructure'). When "
            "set, applying the pack activates this methodology on the pack's "
            "demo project, and every project created while the pack is active "
            "inherits it as its active methodology. None keeps the platform "
            "flat international default. An unknown slug is reported as a "
            "warning at apply time, never an error (validated against the live "
            "template catalogue, so this field carries no regex pattern)."
        ),
    )

    # Validation rule presets
    validation_rule_packs: list[str] = Field(
        default_factory=list,
        description=(
            "Ids of the reference documents the pack ships under "
            "``rule_packs/*.json``, one per file stem. These are "
            "documentation: the engine never executes them, and naming one "
            "here switches nothing on. To switch rules on, use "
            "``validation_rule_sets``."
        ),
    )
    validation_rule_sets: list[str] = Field(
        default_factory=list,
        description=(
            "Validation rule-set identifiers the engine registers, e.g. "
            "['din276', 'gaeb']. These are the names that make rules run: a "
            "project created while the pack is active inherits them into its "
            "``validation_rule_sets``, so the rules execute on its bills of "
            "quantities. Packs cannot ship new rule classes (Shape A); they "
            "only switch on rules that already exist in the core or in a "
            "module. Every entry is checked against the live registry when "
            "the pack is applied, and an unknown one is refused there rather "
            "than here: this object is built at import time, before any rule "
            "has been registered, so a check at construction would read an "
            "empty registry and wave everything through."
        ),
    )

    # Module presets
    default_modules: list[str] = Field(
        default_factory=list,
        description=(
            "Backend module names (the manifest name, e.g. 'oe_contracts') that "
            "applying the pack switches ON for the whole installation. Additive "
            "and always applied; enabling a module that is already on does "
            "nothing, so an empty list changes nothing. This is the server-side "
            "module state an admin sees under Modules > System Modules. It is "
            "not a menu: no sidebar code reads this list, and it neither adds "
            "nor orders a row. A name that is not an installed module is "
            "reported as a warning at apply time."
        ),
    )
    hidden_modules: list[str] = Field(
        default_factory=list,
        description=(
            "Backend module names that applying the pack switches OFF for the "
            "whole installation, and only when the admin applying it confirms "
            "the disables; without that confirmation the list is reported back "
            "as skipped. Switching a module off removes its API for every user, "
            "which is a much larger thing than hiding a menu row, and the row "
            "itself leaves the sidebar only when the sidebar knows which module "
            "backs its route. A module of category 'core' cannot be switched "
            "off, nor one that a module still on depends on: each such entry "
            "is recorded as failed and the rest are applied, so list dependents "
            "before what they depend on. An admin switches a module back on "
            "under Modules > System Modules, and un-applying the pack restores "
            "what it switched off. A user cannot, and the sidebar menu editor "
            "has nothing to do with this list. For a short menu use "
            "``default_company_profile``."
        ),
    )
    default_company_profile: str | None = Field(
        default=None,
        description=(
            "Key of the company profile (app.core.onboarding_presets."
            "COMPANY_PRESETS, e.g. 'mep_contractor') the users of this "
            "installation start in. A profile that has a workspace gives its "
            "users a short ordered menu with every other screen folded under "
            "'More modules', which is the one mechanism that shortens the "
            "sidebar. The field is a default and never a setting written on a "
            "user's behalf: it travels in the public manifest the way "
            "``default_locale`` does, the setup wizard saves it for the admin "
            "who installs the pack, and a user who has chosen no profile sees "
            "the menu of this one until they choose. Anyone can pick another "
            "profile on Modules > Company Profiles. None keeps the behaviour "
            "of a pack that says nothing. Unlike a rule set, the profile "
            "catalogue is plain data available at import time, so an unknown "
            "key is refused here, when the manifest is built."
        ),
    )

    # Branding (logo, colours, favicon)
    branding: PartnerBranding = Field(default_factory=PartnerBranding)

    # Demo project presets
    demo_template_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Optional explicit list of demo project ids (keys of "
            "``DEMO_TEMPLATES``) this pack installs. When set, the one-click "
            "installer seeds exactly these (in order, de-duplicated) instead of "
            "deriving the list from the flagship demo's country. Empty list "
            "keeps the default flagship + country-fill behaviour."
        ),
    )

    # Onboarding script - declarative YAML/JSON applied at first login
    onboarding_script_path: str | None = Field(
        default=None,
        description=(
            "Path inside the pack package to a YAML/JSON onboarding script. "
            "Replaces the default OnboardingWizard steps when set."
        ),
    )

    # Free-form metadata for partners who want to surface extra data
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def market_country_code(self) -> str | None:
        """The single market this pack is for, as ISO 3166-1 alpha-2, or ``None``.

        A country pack is an unambiguous statement of market, and several parts
        of the product need that statement rather than the pack's name: the
        markup region a bill is seeded with, the working calendar, the
        compliance-pack resolver and the measurement system all read a
        project's ``country_code`` and all answer "no opinion" when it is
        unset. A project created while a country pack is active used to inherit
        the pack's methodology and nothing else, so the cascade was national
        while every one of those still said nothing was known.

        ``None`` is returned for three different situations, and they are the
        same answer on purpose because none of them names a market:

        * the manifest carries no ``metadata["country"]`` at all, which is what
          a partner pack and an industry pack look like;
        * it carries ``"XX"``, the cross-region marker the sector packs use,
          which means explicitly that the pack is not for one country;
        * it carries something that is not a clean alpha-2. That is left alone
          rather than normalised or guessed at, because a pack that cannot
          state its market plainly is exactly the case where filling a country
          in on the user's behalf would be wrong.

        Returns:
            An upper-case alpha-2 code, or ``None`` when the pack names no
            single market.
        """
        code = str((self.metadata or {}).get("country", "")).strip().upper()
        if len(code) != 2 or not code.isalpha() or code == _CROSS_REGION_MARKER:
            return None
        return code

    # ------------------------------------------------------------------
    # Pack type resolution
    # ------------------------------------------------------------------
    def _infer_pack_type(self) -> PackType:
        """Infer a pack type for old manifests that omit ``pack_type``.

        The inference reads only fields old partner packs already author, so a
        manifest written before the Packs umbrella resolves to a sensible type
        without any change to the pack. Precedence (first match wins):

          1. ``industry`` - the manifest declares ``metadata.industry`` OR a
             cross-region marker (``metadata.country == "XX"``, used by the
             sector packs such as renewables-epc and modular-prefab).
          2. ``country`` - the manifest carries country metadata: a real
             ``metadata.country`` ISO code (anything other than the "XX"
             cross-region marker) or any ``country_name*`` key.
          3. ``partner`` - the manifest ships partner co-branding
             (``branding.powered_by_text``).
          4. ``partner`` (default) - the historical concept name, so a manifest
             that declares none of the above keeps the original behaviour.
        """
        meta = self.metadata
        country = str(meta.get("country", "")).strip()
        industry = str(meta.get("industry", "")).strip()
        has_country_name = any(k == "country" or k.startswith("country_name") for k in meta)

        if industry or country == _CROSS_REGION_MARKER:
            return "industry"
        if (country and country != _CROSS_REGION_MARKER) or has_country_name:
            return "country"
        if self.branding.powered_by_text:
            return "partner"
        return "partner"

    @field_validator("validation_rule_sets")
    @classmethod
    def _check_rule_set_shape(cls, value: list[str]) -> list[str]:
        """Reject anything that is not shaped like a registered set name.

        This is deliberately a check on the string and not on the registry.
        Pack manifests are module-level constants built at import time, long
        before ``register_builtin_rules`` runs, so asking the registry here
        would read an empty set and either refuse every pack or - because the
        reader returns an empty set on failure - accept every name in it. The
        registry check belongs at apply time and lives in
        :mod:`app.core.partner_pack.apply`.

        Args:
            value: The declared rule-set identifiers.

        Returns:
            The same list, unchanged.

        Raises:
            ValueError: If an entry is not a lower-case identifier, or repeats.
        """
        seen: set[str] = set()
        for name in value:
            if not _RULE_SET_NAME.fullmatch(name):
                raise ValueError(
                    f"validation_rule_sets entry {name!r} is not a rule-set identifier. "
                    "Rule sets are lower-case names like 'din276' or 'boq_quality', so a "
                    "file name such as 'din_276.json' is refused here and belongs in "
                    "validation_rule_packs instead. Only the shape is checked at this "
                    "point: a well-formed name the engine does not register - 'din_276' "
                    "for one - passes here and is refused when the pack is applied."
                )
            if name in seen:
                raise ValueError(f"validation_rule_sets repeats {name!r}")
            seen.add(name)
        return value

    @field_validator("default_company_profile")
    @classmethod
    def _check_company_profile(cls, value: str | None) -> str | None:
        """Refuse a profile key the onboarding catalogue does not carry.

        The catalogue is a module of literals with no imports of its own, so
        reading it here is safe at import time. That is the difference from
        ``validation_rule_sets``, whose registry is filled at start-up and can
        only be checked when the pack is applied. The size tiers
        (``size_small`` and the like) are a different catalogue and are
        refused: a tier names how many people a company has, not what its menu
        should hold.

        Args:
            value: The declared profile key, or None.

        Returns:
            The same value, unchanged.

        Raises:
            ValueError: If the key is not a company profile.
        """
        if value is None:
            return None
        from app.core.onboarding_presets import COMPANY_PRESETS

        if value not in COMPANY_PRESETS:
            raise ValueError(
                f"default_company_profile {value!r} is not a company profile. "
                f"Known profiles: {', '.join(sorted(COMPANY_PRESETS))}."
            )
        return value

    @model_validator(mode="after")
    def _resolve_pack_type(self) -> PartnerPackManifest:
        """Fill ``pack_type`` from inference when a manifest omits it."""
        if self.pack_type is None:
            # ``extra="forbid"`` + assignment validation is off by default, so a
            # plain attribute set is safe and avoids re-running this validator.
            object.__setattr__(self, "pack_type", self._infer_pack_type())
        return self

    @property
    def type(self) -> PackType:
        """The resolved pack type. Always one of the four ``PackType`` values."""
        # ``_resolve_pack_type`` guarantees ``pack_type`` is set post-validation;
        # fall back to inference defensively if a manifest is built another way.
        return self.pack_type or self._infer_pack_type()

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------
    @property
    def effective_powered_by(self) -> str:
        """Co-branding string. Default preserves AGPL attribution."""
        if self.branding.powered_by_text:
            return self.branding.powered_by_text
        return f"Powered by OpenConstructionERP · In partnership with {self.partner_name}"

    def _carries(self, relpath: str | None) -> bool:
        """Whether the pack actually ships the file it names at ``relpath``.

        Asks the same reader the streaming endpoints ask, rather than a second
        resolver of its own: ``read_pack_file`` resolves pip-installed packs,
        source-checkout packs and dropped packs in the data directory, and a
        parallel implementation here would answer differently from the endpoint
        the moment those three branches drift.

        This looks redundant for the packs in this repository, and is not.
        backend/tests/unit/test_community_packs_ship.py makes declared and
        carried the same thing for the fifteen packs the wheel force-includes,
        so for those the check can only ever say True. It exists for the packs
        that gate structurally cannot reach: a pack dropped into the data
        directory at runtime, and a third-party pack installed from PyPI by
        somebody else. Those are exactly the ones whose manifests nobody here
        reviewed, and the answer for them is a real question. Deleting this as
        dead code re-opens the hole for every pack we do not author.

        The import is deferred because ``discovery`` imports this module. The
        answer comes from ``pack_carries_file``, which asks ``read_pack_file``
        once per slug and path and keeps the yes/no until ``reset_cache()``:
        asked afresh, the flags cost about five seconds of CPU per
        ``GET /installed`` over 43 packs, a call the header makes on every page.

        Args:
            relpath: Declared path inside the pack package, or None.

        Returns:
            True when the pack names a file and that file can be read.
        """
        if not relpath:
            return False
        from app.core.partner_pack.discovery import pack_carries_file

        return pack_carries_file(self.slug, relpath)

    def to_public_dict(self) -> dict[str, Any]:
        """Serialise for the /api/v1/partner-pack/current endpoint.

        Strips internal-only fields (file paths inside the pack package
        are not useful to the frontend; they get exposed via dedicated
        streaming endpoints).
        """
        return {
            "slug": self.slug,
            "type": self.type,
            "partner_name": self.partner_name,
            "partner_url": self.partner_url,
            "pack_version": self.pack_version,
            "description": self.description,
            "default_locale": self.default_locale,
            "additional_locales": sorted(self.additional_locales.keys()),
            "cwicr_regions": self.cwicr_regions,
            "default_currency": self.default_currency,
            "default_tax_template": self.default_tax_template,
            "default_methodology": self.default_methodology,
            "validation_rule_packs": self.validation_rule_packs,
            "validation_rule_sets": self.validation_rule_sets,
            "demo_template_ids": self.demo_template_ids,
            "default_modules": self.default_modules,
            "hidden_modules": self.hidden_modules,
            "default_company_profile": self.default_company_profile,
            "branding": {
                "primary_color": self.branding.primary_color,
                "accent_color": self.branding.accent_color,
                # All three answer "does the pack carry this", not "does the
                # manifest mention it". has_logo was hardcoded True and the
                # other two read a path field for non-None, so a pack that
                # named a file it did not ship was advertised as having it.
                # The frontend fallbacks are good and kept the screen intact,
                # which is why this went unnoticed; they were covering for an
                # answer that was simply wrong.
                "has_logo": self._carries(self.branding.logo_path),
                "has_favicon": self._carries(self.branding.favicon_path),
                "powered_by_text": self.effective_powered_by,
            },
            "has_onboarding_script": self._carries(self.onboarding_script_path),
            "metadata": self.metadata,
        }
