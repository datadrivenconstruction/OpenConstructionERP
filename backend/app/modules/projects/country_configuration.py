# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Which pack fits out a new project with its country's configuration.

One pack is active on an installation, and a contractor works in more than one
country. Project creation used to copy the active pack's rule sets and its
estimating methodology onto every project, so a Hungarian project created
while the Turkish pack was active carried ``birimfiyat``, failed the poz-number
rule on every correctly coded Hungarian line, and was priced with the Turkish
cascade.

A country pack states two different kinds of thing. Its branding, company
profile and module presets describe the installation and apply to every
project. Its rule sets and its methodology describe one market, and belong
only to projects in that market. This module decides the second kind:

* a project in the active pack's own country is fitted out by the active pack,
  exactly as before, and so is every project under a pack that names no market
  (a sector pack has no country to differ from);
* a project in another country is fitted out by that country's own pack, read
  from the discovered manifests without activating it;
* a project in a country no pack is written for gets nothing country-specific
  from any pack, which is what an installation with no pack gives it: the
  caller's rule sets and the international methodology, with the national rule
  sets the BOQ router adds for the country at validation time.

Everything here is pure: manifests in, a manifest and a reason out. No
database, no registry, no pack state.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from app.core.classification_registry import is_macro_region, normalise_region
from app.core.partner_pack.manifest import PartnerPackManifest

#: The project is in the active pack's market, or the pack names no market.
SOURCE_ACTIVE_PACK = "active_pack"
#: The project is in another country, and that country's own pack fits it out.
SOURCE_COUNTRY_PACK = "country_pack"
#: The project is in another country that no discovered pack is written for.
SOURCE_COUNTRY_WITHOUT_PACK = "country_without_pack"

#: Project metadata keys recording the decision, written only when the
#: project's country is not the active pack's, so a project in the pack's own
#: country stores exactly what it stored before.
CONFIGURATION_SOURCE_METADATA_KEY = "country_configuration_source"
CONFIGURATION_PACK_METADATA_KEY = "country_configuration_pack"

#: Manifest metadata keys that narrow a country pack to part of its country: a
#: state pack (``us-texas``) or a regional programme (``bimhessen-de``). A
#: project elsewhere in the country is better served by the pack that narrows
#: nothing.
_NARROWING_METADATA_KEYS: tuple[str, ...] = ("subdivision", "region_focus")

#: The manifest metadata key a pack derived from another pack names its base
#: under (``turkey-tr-mep`` is derived from ``turkey-tr``).
_DERIVED_FROM_METADATA_KEY = "derived_from"


def validated_country(region: str | None, country_code: str | None) -> str | None:
    """The country a project's bills are validated as.

    The same decision the BOQ router and the working-week resolver make: a
    region that names one country wins over the country column, and a group
    label (``DACH``, ``GCC``) or a region that names no country gives way to
    it. The column is filled from the active pack when nobody names a country,
    so reading it alone would call a project filed under ``HU`` Turkish while
    its bills are validated as Hungarian.

    Args:
        region: The project's region label, free text.
        country_code: The project's settled ISO 3166-1 alpha-2 column.

    Returns:
        An upper-case alpha-2 code, or ``None`` when neither names a country.
    """
    if not is_macro_region(region):
        from_region = normalise_region(region)
        if from_region:
            return from_region
    return (country_code or "").strip().upper() or None


def _is_plain_country_pack(manifest: PartnerPackManifest, country: str) -> bool:
    """Whether ``manifest`` is a country pack for ``country`` in its own right."""
    if manifest.type != "country" or manifest.market_country_code != country:
        return False
    return not str((manifest.metadata or {}).get(_DERIVED_FROM_METADATA_KEY) or "").strip()


def _narrows_its_country(manifest: PartnerPackManifest) -> bool:
    metadata = manifest.metadata or {}
    return any(metadata.get(key) for key in _NARROWING_METADATA_KEYS)


def country_pack_for(country: str | None, shipped: Iterable[PartnerPackManifest]) -> PartnerPackManifest | None:
    """The one pack that speaks for ``country`` among the discovered manifests.

    Deterministic whatever order the manifests arrive in. Only a pack of type
    ``country`` whose market is this country counts: an industry pack and a
    pack derived from a country pack describe a trade or one installation, and
    are used only where they are the active pack. Among several country packs
    the one that narrows nothing comes first (``germany-de`` before
    ``bimhessen-de``, ``us-costdata`` before the state packs), and the slug
    breaks what is left (``batimatech-ca`` before ``canada-ca``).

    Args:
        country: ISO 3166-1 alpha-2 code, any case.
        shipped: The discovered pack manifests.

    Returns:
        The chosen manifest, or ``None`` when no country pack is written for
        ``country``.
    """
    wanted = (country or "").strip().upper()
    if not wanted:
        return None
    candidates = [m for m in shipped if _is_plain_country_pack(m, wanted)]
    if not candidates:
        return None
    return min(candidates, key=lambda m: (_narrows_its_country(m), m.slug))


def configuration_pack(
    *,
    region: str | None,
    country_code: str | None,
    active_pack: PartnerPackManifest | None,
    shipped: Callable[[], Iterable[PartnerPackManifest]],
) -> tuple[PartnerPackManifest | None, str]:
    """The pack whose rule sets and methodology a new project inherits.

    Args:
        region: The region label the project is created with.
        country_code: The project's settled country, after the caller, the
            address and the active pack have each had their say.
        active_pack: The pack active on the installation, or ``None``.
        shipped: Returns the discovered manifests. Called only when the
            project is in a country other than the active pack's, so a create
            in the pack's own country never pays for discovery.

    Returns:
        ``(pack, source)``. ``pack`` is the active pack, another country's
        pack, or ``None`` for no country-specific configuration at all;
        ``source`` is one of the ``SOURCE_*`` constants.
    """
    if active_pack is None:
        return None, SOURCE_ACTIVE_PACK
    market = active_pack.market_country_code
    country = validated_country(region, country_code)
    if market is None or country is None or country == market:
        return active_pack, SOURCE_ACTIVE_PACK
    own = country_pack_for(country, shipped())
    if own is None:
        return None, SOURCE_COUNTRY_WITHOUT_PACK
    return own, SOURCE_COUNTRY_PACK
