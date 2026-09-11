# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The one place that turns a project's region into a classification standard.

Before this module the tree carried six hand-kept copies of the same
mapping: two tables plus a fallback table in the match pipeline, one in
the validation rules, one declared per row on the shipped CWICR
catalogues, and one keyed by region inside the BOQ rule-set builder. The
copies had drifted, and the drift was not academic. Australia, India and
South Africa were ranked against NRM by the match pipeline and against
MasterFormat by the catalogue the product ships for them; Brazil,
Morocco and Tunisia disagreed the other way round.

Worse, resolution depended on the *shape* of the region string rather
than its meaning. ``PL`` resolved to DIN 276 and ``PL_WARSAW`` to
MasterFormat, because the catalogue loop pre-loaded every catalogue
region id into the lookup with a default standard, which meant the
city-suffix safety net (``if head is None and "_" in region``) could
never fire for the very ids that needed it. Sixteen countries answered
two different ways depending on whether a city happened to be appended.

The shape of the fix:

* :data:`COUNTRY_TO_STANDARD` is the only table. It is keyed by ISO
  3166-1 alpha-2 and nothing else, so a country cannot be listed twice
  under two spellings.
* :func:`normalise_region` reduces any region string to that alpha-2
  code once, before any lookup happens. A catalogue region id resolves
  through the ``country_iso`` the catalogue *declares*, not through
  string surgery on the id - ``SV_STOCKHOLM`` is Sweden, ``ZH_CHINA``
  is China and ``VI_HANOI`` is Vietnam, none of which survive splitting
  on the underscore.
* Resolution is total. It never raises, because it runs on the BOQ
  section-path render path where an exception would trade a wrong
  standard for a broken page. It reports instead: every answer carries
  the country it matched and whether it matched at all.

When a region resolves to nothing the answer is
:data:`DEFAULT_CLASSIFICATION_STANDARD` with ``source="default"``, and
the fall-through is logged rather than swallowed. A blank region is the
schema default for ``ProjectCreate`` and is expected, so it logs at info;
a region that was filled in and still did not resolve is a data problem
and logs at warning. Both are deduplicated per process so a per-row
render path cannot flood the log.

Rule packs are a different axis and keep their own table. A country
picks one classification standard but can pull several validation rule
packs (Spain reads BC3 and MasterFormat, Germany reads GAEB and DIN
276), so folding the two together would lose information. What they
share is this module's normaliser, which is the part that was wrong.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType
from typing import Mapping

logger = logging.getLogger(__name__)

# The standard a caller gets when the region names no country we know.
# Kept at DIN 276 so the fall-through value itself is unchanged by the
# consolidation; what changed is that the caller can now tell it was a
# fall-through. Anything reading this must treat ``source == "default"``
# as "no answer", not as "the answer is Germany".
DEFAULT_CLASSIFICATION_STANDARD = "din276"

# The three the section-path renderer, the BOQ exporters and the older
# tests all assume are always available. They lead the preference order
# so a CostItem encoded against any of them still produces a path.
LEGACY_STANDARDS: tuple[str, ...] = ("din276", "masterformat", "nrm")

# Display labels, one place, so section paths, BOQ exports and the
# validation messages cannot drift apart on capitalisation.
CLASSIFICATION_STANDARD_LABELS: Mapping[str, str] = MappingProxyType(
    {
        "din276": "DIN276",
        "masterformat": "MasterFormat",
        "nrm": "NRM",
        "untec": "UNTEC",
        "voci": "VOCI",
        "bc3": "BC3",
        "gb50500": "GB50500",
        "sekisan": "SEKISAN",
        "kbim": "KBIM",
        "gesn": "GESN",
        "birimfiyat": "Birim Fiyat",
        "sinapi": "SINAPI",
        "onorm": "ÖNORM",
        "uniclass": "Uniclass",
        "omniclass": "OmniClass",
        "uniformat": "UniFormat",
        "gaeb": "GAEB",
        "tetelrend": "Tételrend",
    }
)

# ── The table ────────────────────────────────────────────────────────────
#
# ISO 3166-1 alpha-2 to the classification standard a local estimator
# actually reads. Keys are countries only. Macro regions, language codes
# and catalogue region ids all reduce to one of these keys first, in
# :func:`normalise_region`, so no key here is ever a region id.
#
# Where the old copies disagreed, the merge rule was mechanical rather
# than inventive: the deliberate per-country heuristic that the match
# pipeline carried wins first, then the standard the shipped catalogue
# declares for the country, then the macro-cluster anchor the country
# used to hang off. That keeps Australia, India and South Africa on the
# Commonwealth NRM lineage their QS bodies are aligned to, and moves
# Brazil onto SINAPI, which is its actual national reference system and
# what its catalogue has been declaring all along.
COUNTRY_TO_STANDARD: Mapping[str, str] = MappingProxyType(
    {
        # ── DIN 276 cost-group hierarchy ─────────────────────────────
        # DACH proper.
        "DE": "din276",
        "AT": "din276",
        "CH": "din276",
        "LI": "din276",
        # Central Europe and the Low Countries. Belgium and Luxembourg
        # have no native cost-group standard in the product yet; DIN 276
        # is the nearest hierarchy their tender documents map onto.
        # The Netherlands now has its own pack declaring NL/SfB.
        "BE": "din276",
        "NL": "nlsfb",
        "LU": "din276",
        "PL": "din276",
        "CZ": "din276",
        "SK": "din276",
        "RO": "din276",
        "BG": "din276",
        "HR": "din276",
        "SI": "din276",
        "RS": "din276",
        "LT": "din276",
        "LV": "din276",
        "EE": "din276",
        # Nordics, same reasoning.
        "SE": "din276",
        "NO": "din276",
        "DK": "din276",
        "FI": "din276",
        "IS": "din276",
        # ── NRM, RICS-aligned local QS practice ──────────────────────
        "GB": "nrm",
        "IE": "nrm",
        "AU": "nrm",
        "NZ": "nrm",
        "ZA": "nrm",
        "IN": "nrm",
        "NG": "nrm",
        "KE": "nrm",
        "GH": "nrm",
        "UG": "nrm",
        "TZ": "nrm",
        "HK": "nrm",
        "SG": "nrm",
        "MY": "nrm",
        # ── MasterFormat, CSI-aligned ────────────────────────────────
        "US": "masterformat",
        "CA": "masterformat",
        # Latin America and Iberia outside Brazil. Their catalogues
        # align with CSI divisions more closely than with DIN.
        "MX": "masterformat",
        "AR": "masterformat",
        "CL": "masterformat",
        "CO": "masterformat",
        "PE": "masterformat",
        "EC": "masterformat",
        "UY": "masterformat",
        "PY": "masterformat",
        "BO": "masterformat",
        "VE": "masterformat",
        "PT": "masterformat",
        "AO": "masterformat",
        # Gulf and North African English-language tendering.
        "AE": "masterformat",
        "SA": "masterformat",
        "QA": "masterformat",
        "KW": "masterformat",
        "BH": "masterformat",
        "OM": "masterformat",
        "EG": "masterformat",
        "MA": "masterformat",
        "TN": "masterformat",
        "DZ": "masterformat",
        # Asia-Pacific markets with no native scheme in the product.
        "TW": "masterformat",
        "ID": "masterformat",
        "TH": "masterformat",
        "VN": "masterformat",
        "PH": "masterformat",
        # ── Native systems ───────────────────────────────────────────
        # France and the Francophone West African markets that tender
        # against the same DTU lineage.
        "FR": "untec",
        "SN": "untec",
        "CI": "untec",
        "CM": "untec",
        "IT": "voci",
        "ES": "bc3",
        "BR": "sinapi",
        "CN": "gb50500",
        "JP": "sekisan",
        "KR": "kbim",
        "TR": "birimfiyat",
        # Hungary. Hungarian bills are written against a sectoral item
        # order rather than a cost-group hierarchy: a chapter-and-item code
        # for building works, a per-project item number for infrastructure.
        # This read din276 until 2026-08, which was the Central European
        # default rather than a statement about Hungary.
        "HU": "tetelrend",
        # GESN family. Mongolia is here because its construction norms
        # descend from the same lineage as the CIS states around it,
        # not because a catalogue declares it.
        "RU": "gesn",
        "UA": "gesn",
        "BY": "gesn",
        "KZ": "gesn",
        "MN": "gesn",
    }
)

# ── Aliases ──────────────────────────────────────────────────────────────
#
# Everything that is not an alpha-2 country code but that estimators,
# catalogues and older project rows actually put in ``project.region``.
# Each one names the country it stands for; the standard then comes from
# the single table above, so an alias can never carry a standard of its
# own and drift from it.
REGION_ALIAS_TO_COUNTRY: Mapping[str, str] = MappingProxyType(
    {
        # Alpha-3 and colloquial country spellings.
        "UK": "GB",
        "USA": "US",
        "UAE": "AE",
        # Macro regions. The anchor is chosen so the region answers what
        # it has always answered; the natively mapped countries inside
        # each cluster are keyed on their own ISO codes and never reach
        # the alias.
        "DACH": "DE",
        "EU": "DE",
        "BENELUX": "BE",
        "NORDIC": "SE",
        "SCANDINAVIA": "SE",
        "LATAM": "MX",
        "GULF": "AE",
        "GCC": "AE",
        "MIDDLE_EAST": "AE",
        "ASIA_PAC": "ID",
        # Language codes that lead a catalogue region id. These are the
        # rows where splitting the id on the underscore gives the wrong
        # country, so they are declared rather than derived.
        "SV": "SE",
        "ZH": "CN",
        "VI": "VN",
        "HI": "IN",
        # Long-form spellings. Deliberately not an attempt at every
        # country name in English - these are the spellings the product's
        # own shipped demo and seed projects use, and the test that keeps
        # them honest walks that data rather than this list. Before they
        # were here, the French demo project resolved to DIN 276, because
        # "France" matched nothing and its declared ``dpgf`` is a rule
        # pack rather than a standard the renderer knows.
        "FRANCE": "FR",
        "UNITED_STATES": "US",
        # ── The project region picker's vocabulary ────────────────────
        #
        # The second source of region strings, and the one that reaches
        # this module most often: ``REGION_GROUPS`` in
        # ``frontend/src/features/projects/CreateProjectPage.tsx``, whose
        # values a user writes into ``project.region`` every time a
        # project is created. It speaks neither ISO codes nor the macro
        # names above; it ships prose and glued CamelCase, so "Russia",
        # "Brazil" and "GulfStates" all matched nothing and every project
        # created through it outside DACH, the UK, France and the US was
        # classified against DIN 276 and picked up no country rule pack,
        # because ``boq.router._resolve_rule_sets`` reads the same
        # normaliser. Four of the thirty shipped options resolved.
        #
        # Teaching the resolver rather than changing the picker is what
        # repairs the rows already in the database: a project stored as
        # "Russia" last year starts resolving to GESN on its next read,
        # with no migration and nothing to backfill.
        #
        # Kept in this table rather than a picker-specific one on purpose.
        # An alias carries only a country, so it cannot hold a standard
        # of its own and drift from ``COUNTRY_TO_STANDARD``, which is the
        # drift this module was built to end.
        "SPAIN": "ES",
        "ITALY": "IT",
        "NETHERLANDS": "NL",
        "POLAND": "PL",
        "CZECH": "CZ",
        "TURKEY": "TR",
        "RUSSIA": "RU",
        "CANADA": "CA",
        "BRAZIL": "BR",
        "MEXICO": "MX",
        "CHINA": "CN",
        "JAPAN": "JP",
        "KOREA": "KR",
        "INDIA": "IN",
        "SOUTHAFRICA": "ZA",
        "AUSTRALIA": "AU",
        "NEWZEALAND": "NZ",
        # The picker's macro options, anchored the same way the macro
        # names above are: on a member country whose standard the whole
        # option can live with. Where the members agree the anchor is
        # merely a spelling - every Nordic state reads DIN 276, every
        # North African one MasterFormat, every East African one NRM - so
        # the choice of anchor changes no answer.
        #
        # Two of them cover members that genuinely disagree, and the
        # anchor is a decision rather than a lookup. Both are named with
        # their reason in
        # ``test_every_shipped_picker_option_reaches_the_registry.py`` so
        # the decision stays readable: WestAfrica anchors on Nigeria (NRM)
        # while Senegal, Ivory Coast and Cameroon read UNTEC, and
        # SoutheastAsia anchors on Indonesia (MasterFormat) while Malaysia
        # and Singapore read NRM. Anchoring is still strictly better than
        # the alternative, which is not neutrality but DIN 276: a Lagos or
        # a Jakarta project silently classified against German cost
        # groups. A user who needs the other answer names the standard
        # explicitly, which wins over the region.
        "NORDICS": "SE",
        "LATINAMERICA": "MX",
        "MIDDLEEAST": "AE",
        "GULFSTATES": "AE",
        "NORTHAFRICA": "EG",
        "EASTAFRICA": "KE",
        "WESTAFRICA": "NG",
        "SOUTHEASTASIA": "ID",
        # "INTL" is deliberately absent. It is the picker's
        # "International / Multi-region" option, it names no country, and
        # DIN 276 by fall-through is as good an answer as any other
        # guess. It is the one option that is meant to default, and the
        # gate names it as such.
    }
)

_TOKEN_SEPARATORS = re.compile(r"[^A-Z0-9]+")

# Regions already reported as unresolvable, so a render loop over a
# thousand BOQ positions logs once rather than a thousand times.
_reported_defaults: set[str] = set()
_REPORTED_DEFAULTS_CAP = 512


@dataclass(frozen=True, slots=True)
class StandardResolution:
    """What a region resolved to, and whether it resolved at all.

    Attributes:
        standard: The classification standard slug to use. Always set.
        country: ISO 3166-1 alpha-2 the region reduced to, or ``None``
            when nothing matched.
        source: ``"explicit"`` when the project named the standard
            itself, ``"region"`` when the region matched a country, and
            ``"default"`` when neither did and the caller is holding
            :data:`DEFAULT_CLASSIFICATION_STANDARD`.
    """

    standard: str
    country: str | None
    source: str

    @property
    def matched(self) -> bool:
        """Whether the standard was chosen rather than fallen back to."""
        return self.source != "default"


@lru_cache(maxsize=1)
def _catalogue_region_to_country() -> Mapping[str, str]:
    """Catalogue region id to the country the catalogue declares for it.

    Read from the shipped CWICR registry so a region id resolves through
    its declared ``country_iso`` rather than through string surgery. The
    import is deliberately lazy and defensive: this module must stay
    loadable if the catalogue module ever fails to import, and losing the
    mapping costs only the four ids whose leading segment is a language
    code, all of which are also declared in
    :data:`REGION_ALIAS_TO_COUNTRY`.

    Returns:
        Upper-cased region id to upper-cased alpha-2 country code.
    """
    try:
        from app.modules.costs.cwicr_v3_catalogue import CWICR_V3_CATALOGUES
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "classification registry: CWICR catalogue import failed (%s); "
            "catalogue region ids will resolve by alias and prefix only",
            exc,
        )
        return MappingProxyType({})

    mapping: dict[str, str] = {}
    for catalogue in CWICR_V3_CATALOGUES:
        region = (catalogue.region or "").upper().strip()
        country = (catalogue.country_iso or "").upper().strip()
        if not region or not country:
            continue
        mapping[region] = REGION_ALIAS_TO_COUNTRY.get(country, country)
    return MappingProxyType(mapping)


def _canonical_token(raw: str | None) -> str:
    """Fold a free-text region into an upper-case underscore token."""
    return _TOKEN_SEPARATORS.sub("_", (raw or "").upper()).strip("_")


def normalise_region(raw: str | None) -> str | None:
    """Reduce any region string to the ISO 3166-1 alpha-2 it names.

    This is the single place a region string is interpreted. Everything
    downstream works on the alpha-2 code, which is why ``PL`` and
    ``PL_WARSAW`` cannot answer differently: they are the same country by
    construction, not because both happen to be listed.

    Resolution walks, in order, the catalogue region ids (so a declared
    ``country_iso`` wins over the id's spelling), the alias table, the
    country table, and finally the segment before the first separator,
    which is retried the same way. A region nobody claims returns
    ``None`` rather than a guess.

    Args:
        raw: Region as stored on the project. May be empty or ``None``.

    Returns:
        Alpha-2 country code, or ``None`` if the region names no country
        the registry knows.

    Examples:
        >>> normalise_region("PL_WARSAW")
        'PL'
        >>> normalise_region("SV_STOCKHOLM")
        'SE'
        >>> normalise_region("dach")
        'DE'
        >>> normalise_region("") is None
        True
    """
    token = _canonical_token(raw)
    catalogue = _catalogue_region_to_country()
    seen: set[str] = set()
    while token and token not in seen:
        seen.add(token)
        declared = catalogue.get(token)
        if declared:
            return declared
        alias = REGION_ALIAS_TO_COUNTRY.get(token)
        if alias:
            return alias
        if token in COUNTRY_TO_STANDARD:
            return token
        head, separator, _rest = token.partition("_")
        if not separator:
            return None
        token = head
    return None


def standard_for_country(country: str | None) -> str | None:
    """The classification standard a country reads, or ``None``.

    Args:
        country: Alpha-2 country code, any casing.

    Returns:
        The standard slug, or ``None`` when the country has no entry.
    """
    return COUNTRY_TO_STANDARD.get((country or "").upper().strip())


def _report_default(token: str, region: str | None) -> None:
    """Log a fall-through once per distinct region string."""
    if token in _reported_defaults:
        return
    if len(_reported_defaults) < _REPORTED_DEFAULTS_CAP:
        _reported_defaults.add(token)
    if not token:
        logger.info(
            "classification standard defaulted to %s because the project names no region; "
            "this is the ProjectCreate default, not a match",
            DEFAULT_CLASSIFICATION_STANDARD,
        )
        return
    logger.warning(
        "classification standard defaulted to %s because region %r resolves to no country "
        "the registry knows; the project is being classified against a fallback, not a match",
        DEFAULT_CLASSIFICATION_STANDARD,
        region,
    )


def resolve_standard(
    explicit: str | None = None,
    region: str | None = None,
) -> StandardResolution:
    """Pick the classification standard for a project.

    An explicit choice on the project wins whenever it names a standard
    the product renders. Otherwise the region is normalised to a country
    and the country's standard is used. Failing both, the caller gets
    :data:`DEFAULT_CLASSIFICATION_STANDARD` with ``source="default"`` and
    the fall-through is logged, so a wrong standard can no longer reach a
    user with no signal anywhere.

    The function is total: it does not raise, because its callers include
    the BOQ section-path renderer, where an exception costs the page.

    Args:
        explicit: ``project.classification_standard``, possibly empty.
        region: ``project.region``, possibly empty.

    Returns:
        A :class:`StandardResolution`. Read ``matched`` before treating
        ``standard`` as an answer about the project.
    """
    chosen = (explicit or "").lower().strip()
    if chosen in KNOWN_CLASSIFICATION_STANDARDS:
        return StandardResolution(standard=chosen, country=normalise_region(region), source="explicit")

    country = normalise_region(region)
    standard = standard_for_country(country)
    if country and standard:
        return StandardResolution(standard=standard, country=country, source="region")

    _report_default(_canonical_token(region), region)
    return StandardResolution(standard=DEFAULT_CLASSIFICATION_STANDARD, country=None, source="default")


def _build_known_standards() -> tuple[str, ...]:
    """Every standard the product can render, legacy three first."""
    ordered = list(LEGACY_STANDARDS)
    seen = set(ordered)
    for standard in COUNTRY_TO_STANDARD.values():
        if standard not in seen:
            ordered.append(standard)
            seen.add(standard)
    return tuple(ordered)


KNOWN_CLASSIFICATION_STANDARDS: tuple[str, ...] = _build_known_standards()


def classification_order(
    explicit: str | None = None,
    region: str | None = None,
) -> tuple[str, ...]:
    """Standards ordered most-preferred first for a project.

    The head is what :func:`resolve_standard` picked; the tail is every
    other standard in a stable order, so a section path still renders
    when the project's first-choice standard is not populated on a given
    CostItem.

    Args:
        explicit: ``project.classification_standard``, possibly empty.
        region: ``project.region``, possibly empty.

    Returns:
        A non-empty tuple covering :data:`KNOWN_CLASSIFICATION_STANDARDS`.
    """
    head = resolve_standard(explicit, region).standard
    return (head, *(s for s in KNOWN_CLASSIFICATION_STANDARDS if s != head))
