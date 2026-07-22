# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Single source of truth for the CWICR cost-base catalog.

The public DDC CWICR data repository publishes nine cost-base families. One of
them, the global CWICR base (derived from the GESN / FER / TER norm structure),
is fully built out: its work-item catalogue is localized and repriced into 30
markets and nine languages, and each market ships a complete work-item parquet.
The other eight are authentic national bases built directly from each country's
official norm system (China Dinge, Turkey Birim Fiyat, Brazil SINAPI, Spain
BCCA, Italy Prezzario Regione Toscana, Greece GGDE, Vietnam Dinh Muc, Indonesia
AHSP); each ships one full home-market work-item base.

This module is the one place that knows, for every loadable base, its platform
region id, the GitHub path of its work-item parquet, the folder holding its
resource-catalog CSV, and the work-item ("position") count shown in the base
browser before anything is loaded. Both the cost-item loader
(``app.modules.costs.router``) and the resource-catalog loader
(``app.modules.catalog.router``) resolve their GitHub download paths from here,
and the ``GET /api/v1/costs/base-catalog`` endpoint serializes it, so the three
user surfaces (import page, database setup, onboarding) never drift apart.

The repository was restructured so every market parquet now lives nested under
its national-base parent folder. Keeping the paths here, generated once, means a
future restructure is a one-file change rather than a hunt through three
hardcoded frontend arrays and two backend maps.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

#: ``owner/repo`` slug of the public CWICR data repository.
REPO = "datadrivenconstruction/OpenConstructionEstimate-DDC-CWICR"

#: Repo folder of the flagship global base. Every one of its 30 markets is a
#: full work-item parquet under ``<this>/<XX>___DDC_CWICR/``.
_GLOBAL_BASE_FOLDER = "CIS-Russia-GESN-FER-TER"

#: Number of work items (deduplicated positions) in the global CWICR base. The
#: figure is uniform across all 30 markets because a market is the same
#: catalogue repriced and relabeled, not a different set of works. Sourced from
#: the base's published README (55,719 work items / 27,672 resources).
_GLOBAL_POSITIONS = 55719


@dataclass(frozen=True)
class BaseVariant:
    """One loadable cost base: a full work-item catalogue for a single market.

    Attributes:
        region: Platform region id, the value stored in ``oe_costs_item.region``
            and the ``db_id`` path segment of ``POST /costs/load-cwicr/{db_id}``.
        market: Human market / country label (English).
        city: Representative city or ``"National"`` for country-wide bases.
        language: Display language label (ASCII-friendly, as shown in the UI).
        lang_code: ISO 639-1 language code.
        currency: ISO 4217 currency code the rates are expressed in.
        flag: ISO 3166-1 alpha-2 country code (lowercase) for the flag icon.
        positions: Work-item count shown before load.
        workitems_path: Path of the work-item parquet, relative to the repo raw
            root, used as the GitHub download fallback.
        catalog_folder: Repo folder holding this market's resource-catalog CSV.
        catalog_token: Region token embedded in the catalog CSV file name
            (``DDC_CWICR_<token>_Catalog.csv``); differs from ``region`` for the
            national bases whose export keeps a short country prefix.
        bundled: Whether the base ships locally (loads without any network).
        coefficient: Whether it is a codeless coefficient base (no priced
            resources of its own; estimable via a resource price sheet).
        variant_id: Unique UI id. Global and national HOME variants use their
            ``region``; a national MARKET variant uses
            ``f"{base_region}:{market_catalog}"`` (e.g. ``"ZH_CHINA:GB_LONDON_en"``)
            so many cards can share one ``base_region`` yet stay individually
            addressable. Defaults to ``region``.
        base_region: The ``oe_costs_item.region`` a load + reprice targets. Global
            and home variants use ``region``; a market variant uses its base's
            home region (e.g. ``ZH_CHINA``). All of a base's cards share it.
            Defaults to ``region``.
        market_catalog: The ``markets/`` catalog file token this card reprices
            into (e.g. ``"GB_LONDON_en"``); empty for global and home variants.
        active: Whether this market is the one the base is currently repriced
            into. Registry default is ``False``; the live value is tracked client
            side (localStorage) in this MVP.
    """

    region: str
    market: str
    city: str
    language: str
    lang_code: str
    currency: str
    flag: str
    positions: int
    workitems_path: str
    catalog_folder: str
    catalog_token: str
    bundled: bool = False
    coefficient: bool = False
    variant_id: str = ""
    base_region: str = ""
    market_catalog: str = ""
    active: bool = False

    def __post_init__(self) -> None:
        # Default variant_id and base_region to ``region`` so global variants and
        # national home variants are unchanged (they never pass these). Market
        # variants set both explicitly, so these fills are no-ops for them.
        if not self.variant_id:
            object.__setattr__(self, "variant_id", self.region)
        if not self.base_region:
            object.__setattr__(self, "base_region", self.region)


@dataclass(frozen=True)
class BaseFamily:
    """A cost-base family: a norm system and the markets available under it.

    Attributes:
        key: Stable machine key (``"global"``, ``"china"``, ...).
        name: Display name of the family.
        norm_system: The official norm / classification the base derives from.
        origin: Origin country label (``"Russia"`` for the flagship global base).
        origin_flag: ISO 3166-1 alpha-2 code for the origin flag.
        description: One-line plain-language summary for the browser.
        variants: Loadable market bases in this family.
        repriceable_markets: Count of additional markets the base can be
            repriced into via resource price sheets (0 when not applicable).
    """

    key: str
    name: str
    norm_system: str
    origin: str
    origin_flag: str
    description: str
    variants: list[BaseVariant] = field(default_factory=list)
    repriceable_markets: int = 0


@dataclass(frozen=True)
class MarketCatalog:
    """One market/language price level a national base can be repriced into.

    Each entry mirrors a ``markets/DDC_CWICR_<token>_Catalog.csv`` file that ships
    the base's own resources relabeled and repriced to that market. Because the
    resource ``code`` is language-independent and identical between the base
    parquet and every market catalog, repricing a base into a market is a clean
    join, so one shared region is repriced in place.

    Attributes:
        token: The market file token, ``<REGION>_<lang>`` (e.g. ``"GB_LONDON_en"``).
        market: Human market / country label (English).
        city: Representative city, or ``"National"`` for country-wide markets.
        language: Display language label (ASCII-friendly).
        lang_code: ISO 639-1 language code (the trailing token segment).
        currency: ISO 4217 currency of the market's rates (read from the CSV).
        flag: ISO 3166-1 alpha-2 country code (lowercase) for the flag icon.
    """

    token: str
    market: str
    city: str
    language: str
    lang_code: str
    currency: str
    flag: str

    @property
    def region_part(self) -> str:
        """The market's region id: the token without its trailing language tag.

        ``"GB_LONDON_en" -> "GB_LONDON"``. Used to skip the one market that would
        exactly duplicate a base's home region (e.g. ``ZH_CHINA_zh`` for China).
        """
        return self.token.removesuffix(f"_{self.lang_code}")


# ── Global CWICR base: 30 full-work-item markets ────────────────────────────
# (region, XX folder, market, city, language label, lang code, currency, flag)
_GLOBAL_MARKETS: tuple[tuple[str, str, str, str, str, str, str, str], ...] = (
    ("USA_USD", "US", "United States", "New York", "English", "en", "USD", "us"),
    ("UK_GBP", "UK", "United Kingdom", "London", "English", "en", "GBP", "gb"),
    ("DE_BERLIN", "DE", "Germany / DACH", "Berlin", "Deutsch", "de", "EUR", "de"),
    ("ENG_TORONTO", "EN", "Canada / International", "Toronto", "English", "en", "CAD", "ca"),
    ("FR_PARIS", "FR", "France", "Paris", "Francais", "fr", "EUR", "fr"),
    ("SP_BARCELONA", "ES", "Spain / Latin America", "Barcelona", "Espanol", "es", "EUR", "es"),
    ("PT_SAOPAULO", "PT", "Brazil / Portugal", "Sao Paulo", "Portugues", "pt", "BRL", "br"),
    ("RU_STPETERSBURG", "RU", "Russia / CIS", "St. Petersburg", "Russian", "ru", "RUB", "ru"),
    ("AR_DUBAI", "AR", "Middle East / Gulf", "Dubai", "Arabic", "ar", "AED", "ae"),
    ("HI_MUMBAI", "HI", "India / South Asia", "Mumbai", "Hindi", "hi", "INR", "in"),
    ("AU_SYDNEY", "AU", "Australia", "Sydney", "English", "en", "AUD", "au"),
    ("NZ_AUCKLAND", "NZ", "New Zealand", "Auckland", "English", "en", "NZD", "nz"),
    ("IT_ROME", "IT", "Italy", "Rome", "Italiano", "it", "EUR", "it"),
    ("NL_AMSTERDAM", "NL", "Netherlands", "Amsterdam", "Nederlands", "nl", "EUR", "nl"),
    ("PL_WARSAW", "PL", "Poland", "Warsaw", "Polski", "pl", "PLN", "pl"),
    ("CS_PRAGUE", "CS", "Czech Republic", "Prague", "Cestina", "cs", "CZK", "cz"),
    ("HR_ZAGREB", "HR", "Croatia", "Zagreb", "Hrvatski", "hr", "EUR", "hr"),
    ("BG_SOFIA", "BG", "Bulgaria", "Sofia", "Balgarski", "bg", "BGN", "bg"),
    ("RO_BUCHAREST", "RO", "Romania", "Bucharest", "Romana", "ro", "RON", "ro"),
    ("SV_STOCKHOLM", "SV", "Sweden", "Stockholm", "Svenska", "sv", "SEK", "se"),
    ("JA_TOKYO", "JA", "Japan", "Tokyo", "Nihongo", "ja", "JPY", "jp"),
    ("KO_SEOUL", "KO", "South Korea", "Seoul", "Hangugeo", "ko", "KRW", "kr"),
    ("TH_BANGKOK", "TH", "Thailand", "Bangkok", "Thai", "th", "THB", "th"),
    ("VI_HANOI", "VI", "Vietnam", "Hanoi", "Tieng Viet", "vi", "VND", "vn"),
    ("ID_JAKARTA", "ID", "Indonesia", "Jakarta", "Bahasa Indonesia", "id", "IDR", "id"),
    ("MX_MEXICOCITY", "MX", "Mexico", "Mexico City", "Espanol", "es", "MXN", "mx"),
    ("ZA_JOHANNESBURG", "ZA", "South Africa", "Johannesburg", "English", "en", "ZAR", "za"),
    ("NG_LAGOS", "NG", "Nigeria", "Lagos", "English", "en", "NGN", "ng"),
    ("ZH_SHANGHAI", "ZH", "China", "Shanghai", "Chinese", "zh", "CNY", "cn"),
    ("TR_ISTANBUL", "TR", "Turkiye", "Istanbul", "Turkce", "tr", "TRY", "tr"),
)


def _global_variant(row: tuple[str, str, str, str, str, str, str, str]) -> BaseVariant:
    region, xx, market, city, language, lang_code, currency, flag = row
    folder = f"{_GLOBAL_BASE_FOLDER}/{xx}___DDC_CWICR"
    return BaseVariant(
        region=region,
        market=market,
        city=city,
        language=language,
        lang_code=lang_code,
        currency=currency,
        flag=flag,
        positions=_GLOBAL_POSITIONS,
        workitems_path=f"{folder}/{region}_workitems_costs_resources_DDC_CWICR.parquet",
        catalog_folder=folder,
        catalog_token=region,
        bundled=False,
    )


_GLOBAL_FAMILY = BaseFamily(
    key="global",
    name="Russia",
    norm_system="GESN / FER / TER",
    origin="Russia",
    origin_flag="ru",
    description=(
        "One comprehensive work-item catalogue, localized and repriced into 30 "
        "markets and nine languages. Pick your market to get it in your language, "
        "currency and local price level."
    ),
    variants=[_global_variant(r) for r in _GLOBAL_MARKETS],
)


# ── Market/language catalogs a national base can reprice into ───────────────
# Derived from the real ``markets/`` folder of the public CWICR data repo (every
# national base ships an identical 48-file ``markets/`` set). Each row is
# (token, market, city, language, lang_code, currency, flag). Currencies were
# read from each market CSV's ``currency`` column (not guessed); flags use the
# ISO country prefix, overridden only where the prefix is not the ISO code
# (USA->us, ZH->cn, VI->vn, SV->se); language/city/lang_code come from the token.
_MARKET_ROWS: tuple[tuple[str, str, str, str, str, str, str], ...] = (
    ("AE_DUBAI_ar", "United Arab Emirates", "Dubai", "Arabic", "ar", "AED", "ae"),
    ("AO_LUANDA_pt", "Angola", "Luanda", "Portugues", "pt", "AOA", "ao"),
    ("AR_BUENOSAIRES_es", "Argentina", "Buenos Aires", "Espanol", "es", "ARS", "ar"),
    ("AT_VIENNA_de", "Austria", "Vienna", "Deutsch", "de", "EUR", "at"),
    ("AU_SYDNEY_en", "Australia", "Sydney", "English", "en", "AUD", "au"),
    ("BG_SOFIA_bg", "Bulgaria", "Sofia", "Balgarski", "bg", "BGN", "bg"),
    ("BR_SAOPAULO_pt", "Brazil", "Sao Paulo", "Portugues", "pt", "BRL", "br"),
    ("CA_TORONTO_en", "Canada", "Toronto", "English", "en", "CAD", "ca"),
    ("CH_ZURICH_de", "Switzerland", "Zurich", "Deutsch", "de", "CHF", "ch"),
    ("CI_ABIDJAN_fr", "Cote d'Ivoire", "Abidjan", "Francais", "fr", "XOF", "ci"),
    ("CM_DOUALA_fr", "Cameroon", "Douala", "Francais", "fr", "XAF", "cm"),
    ("CZ_PRAGUE_cs", "Czech Republic", "Prague", "Cestina", "cs", "CZK", "cz"),
    ("DE_BERLIN_de", "Germany", "Berlin", "Deutsch", "de", "EUR", "de"),
    ("DE_MUNICH_de", "Germany", "Munich", "Deutsch", "de", "EUR", "de"),
    ("EG_CAIRO_ar", "Egypt", "Cairo", "Arabic", "ar", "EGP", "eg"),
    ("ES_MADRID_es", "Spain", "Madrid", "Espanol", "es", "EUR", "es"),
    ("FR_PARIS_fr", "France", "Paris", "Francais", "fr", "EUR", "fr"),
    ("GB_LONDON_en", "United Kingdom", "London", "English", "en", "GBP", "gb"),
    ("GH_ACCRA_en", "Ghana", "Accra", "English", "en", "GHS", "gh"),
    ("HR_ZAGREB_hr", "Croatia", "Zagreb", "Hrvatski", "hr", "EUR", "hr"),
    ("ID_JAKARTA_id", "Indonesia", "Jakarta", "Bahasa Indonesia", "id", "IDR", "id"),
    ("IN_MUMBAI_en", "India", "Mumbai", "English", "en", "INR", "in"),
    ("IT_ROME_it", "Italy", "Rome", "Italiano", "it", "EUR", "it"),
    ("JP_TOKYO_ja", "Japan", "Tokyo", "Nihongo", "ja", "JPY", "jp"),
    ("KE_NAIROBI_en", "Kenya", "Nairobi", "English", "en", "KES", "ke"),
    ("KR_SEOUL_ko", "South Korea", "Seoul", "Hangugeo", "ko", "KRW", "kr"),
    ("MA_CASABLANCA_ar", "Morocco", "Casablanca", "Arabic", "ar", "MAD", "ma"),
    ("MN_ULAANBAATAR_mn", "Mongolia", "Ulaanbaatar", "Mongol", "mn", "MNT", "mn"),
    ("MX_MEXICO_es", "Mexico", "Mexico City", "Espanol", "es", "MXN", "mx"),
    ("NG_LAGOS_en", "Nigeria", "Lagos", "English", "en", "NGN", "ng"),
    ("NL_AMSTERDAM_nl", "Netherlands", "Amsterdam", "Nederlands", "nl", "EUR", "nl"),
    ("NZ_AUCKLAND_en", "New Zealand", "Auckland", "English", "en", "NZD", "nz"),
    ("PL_WARSAW_pl", "Poland", "Warsaw", "Polski", "pl", "PLN", "pl"),
    ("PT_LISBON_pt", "Portugal", "Lisbon", "Portugues", "pt", "EUR", "pt"),
    ("RO_BUCHAREST_ro", "Romania", "Bucharest", "Romana", "ro", "RON", "ro"),
    ("RU_MOSCOW_ru", "Russia", "Moscow", "Russian", "ru", "RUB", "ru"),
    ("RU_STPETERSBURG_ru", "Russia", "St. Petersburg", "Russian", "ru", "RUB", "ru"),
    ("SN_DAKAR_fr", "Senegal", "Dakar", "Francais", "fr", "XOF", "sn"),
    ("SV_STOCKHOLM_sv", "Sweden", "Stockholm", "Svenska", "sv", "SEK", "se"),
    ("TH_BANGKOK_th", "Thailand", "Bangkok", "Thai", "th", "THB", "th"),
    ("TN_TUNIS_ar", "Tunisia", "Tunis", "Arabic", "ar", "TND", "tn"),
    ("TR_NATIONAL_tr", "Turkiye", "National", "Turkce", "tr", "TRY", "tr"),
    ("TZ_DARESSALAAM_en", "Tanzania", "Dar es Salaam", "English", "en", "TZS", "tz"),
    ("UG_KAMPALA_en", "Uganda", "Kampala", "English", "en", "UGX", "ug"),
    ("USA_USD_en", "United States", "National", "English", "en", "USD", "us"),
    ("VI_HANOI_vi", "Vietnam", "Hanoi", "Tieng Viet", "vi", "VND", "vn"),
    ("ZA_JOHANNESBURG_en", "South Africa", "Johannesburg", "English", "en", "ZAR", "za"),
    ("ZH_CHINA_zh", "China", "National", "Chinese", "zh", "CNY", "cn"),
)

#: The 48 markets every national base can be repriced into.
_MARKET_CATALOGS: tuple[MarketCatalog, ...] = tuple(MarketCatalog(*row) for row in _MARKET_ROWS)


def _market_variant(base: BaseVariant, m: MarketCatalog) -> BaseVariant:
    """Build a market-repriced card off a base's home variant.

    Inherits everything from the home variant (positions, workitems_path,
    catalog_folder, bundled, coefficient) except the market-facing labels and
    the identity fields. ``region`` is intentionally kept as the home region so
    all of a base's cards resolve to the same ``oe_costs_item`` rows; the card is
    distinguished by ``variant_id`` and carries the ``market_catalog`` token the
    reprice endpoint downloads.
    """
    return replace(
        base,
        variant_id=f"{base.region}:{m.token}",
        base_region=base.region,
        market=m.market,
        city=m.city,
        language=m.language,
        lang_code=m.lang_code,
        currency=m.currency,
        flag=m.flag,
        market_catalog=m.token,
    )


def _national(
    key: str,
    name: str,
    norm_system: str,
    origin: str,
    origin_flag: str,
    description: str,
    *,
    region: str,
    market: str,
    language: str,
    lang_code: str,
    currency: str,
    flag: str,
    positions: int,
    base_folder: str,
    file_token: str,
    catalog_token: str,
    coefficient: bool = False,
    repriceable_markets: int = 0,
    has_market_reprice: bool = True,
) -> BaseFamily:
    """Build a national family: one bundled, offline-ready home market plus, when
    ``has_market_reprice`` is set, one repriced card per market/language.

    The market cards are generated from :data:`_MARKET_CATALOGS`, skipping only
    the market whose ``region_part`` exactly equals the base's home ``region``
    (the true home duplicate, e.g. ``ZH_CHINA_zh`` for China / ``TR_NATIONAL_tr``
    for Turkiye). Bases whose home region does not appear as a market token keep
    every market card. ``has_market_reprice`` is ``False`` only for Vietnam,
    whose ``resource_code`` is a translated resource name rather than a stable
    code, so a market reprice would not join.
    """
    home = BaseVariant(
        region=region,
        market=market,
        city="National",
        language=language,
        lang_code=lang_code,
        currency=currency,
        flag=flag,
        positions=positions,
        workitems_path=f"{base_folder}/{file_token}_workitems_costs_resources_DDC_CWICR.parquet",
        catalog_folder=base_folder,
        catalog_token=catalog_token,
        bundled=True,
        coefficient=coefficient,
    )
    variants = [home]
    if has_market_reprice:
        variants.extend(_market_variant(home, m) for m in _MARKET_CATALOGS if m.region_part != region)
    return BaseFamily(
        key=key,
        name=name,
        norm_system=norm_system,
        origin=origin,
        origin_flag=origin_flag,
        description=description,
        variants=variants,
        repriceable_markets=repriceable_markets,
    )


# ── Eight authentic national bases (each bundled, single home market) ────────
# Position counts are the real, deduplicated work-item counts of the bundled
# parquets (verified against the loaded relational store).
_NATIONAL_FAMILIES: tuple[BaseFamily, ...] = (
    _national(
        "china",
        "China (Dinge)",
        "Dinge",
        "China",
        "cn",
        "Authentic Chinese base built from the official Dinge norm system.",
        region="ZH_CHINA",
        market="China",
        language="Chinese",
        lang_code="zh",
        currency="CNY",
        flag="cn",
        positions=10486,
        base_folder="Asia-China-Dinge",
        file_token="ZH_CHINA",
        catalog_token="ZH_CHINA",
        repriceable_markets=49,
    ),
    _national(
        "turkey",
        "Turkiye (Birim Fiyat)",
        "Birim Fiyat",
        "Turkiye",
        "tr",
        "Authentic Turkish base built from the official Birim Fiyat unit-price list.",
        region="TR_NATIONAL",
        market="Turkiye",
        language="Turkce",
        lang_code="tr",
        currency="TRY",
        flag="tr",
        positions=22494,
        base_folder="Europe-Turkey-Birim-Fiyat",
        file_token="TR",
        catalog_token="TR",
        repriceable_markets=49,
    ),
    _national(
        "brazil",
        "Brazil (SINAPI)",
        "SINAPI",
        "Brazil",
        "br",
        "Authentic Brazilian base built from the official SINAPI reference system.",
        region="BR_NATIONAL",
        market="Brazil",
        language="Portugues",
        lang_code="pt",
        currency="BRL",
        flag="br",
        positions=9723,
        base_folder="SouthAmerica-Brazil-SINAPI",
        file_token="BR",
        catalog_token="BR",
        repriceable_markets=49,
    ),
    _national(
        "spain",
        "Spain (BCCA)",
        "BCCA",
        "Spain",
        "es",
        "Authentic Spanish base built from the BCCA construction cost database.",
        region="ES_ANDALUCIA",
        market="Spain (Andalucia)",
        language="Espanol",
        lang_code="es",
        currency="EUR",
        flag="es",
        positions=6453,
        base_folder="Europe-Spain-BCCA",
        file_token="ES_ANDALUCIA",
        catalog_token="ES_ANDALUCIA",
        repriceable_markets=49,
    ),
    _national(
        "italy",
        "Italy (Prezzario Toscana)",
        "Prezzario Regione Toscana",
        "Italy",
        "it",
        "Authentic Italian base built from the Prezzario Regione Toscana.",
        region="IT_TOSCANA",
        market="Italy (Toscana)",
        language="Italiano",
        lang_code="it",
        currency="EUR",
        flag="it",
        positions=5836,
        base_folder="Europe-Italy-Prezzario-Toscana",
        file_token="IT_TOSCANA",
        catalog_token="IT_TOSCANA",
        repriceable_markets=49,
    ),
    _national(
        "greece",
        "Greece (GGDE)",
        "GGDE",
        "Greece",
        "gr",
        "Authentic Greek base built from the official GGDE analytical prices.",
        region="GR_NATIONAL",
        market="Greece",
        language="Ellinika",
        lang_code="el",
        currency="EUR",
        flag="gr",
        positions=2647,
        base_folder="Europe-Greece-GGDE",
        file_token="GR",
        catalog_token="GR",
        repriceable_markets=49,
    ),
    _national(
        "vietnam",
        "Vietnam (Dinh Muc)",
        "Dinh Muc",
        "Vietnam",
        "vn",
        "Authentic Vietnamese coefficient base from the official Dinh Muc norms; "
        "estimable by applying a market resource price sheet.",
        region="VN_NATIONAL",
        market="Vietnam",
        language="Tieng Viet",
        lang_code="vi",
        currency="VND",
        flag="vn",
        positions=4299,
        base_folder="Asia-Vietnam-Dinh-Muc",
        file_token="VN",
        catalog_token="VN",
        coefficient=True,
        repriceable_markets=49,
        # Home-only: Vietnam's resource_code is the (translated) resource NAME,
        # not a stable code, so a market reprice would not join (prices -> 0).
        has_market_reprice=False,
    ),
    _national(
        "indonesia",
        "Indonesia (AHSP)",
        "AHSP",
        "Indonesia",
        "id",
        "Authentic Indonesian coefficient base from the official AHSP norms; "
        "estimable by applying a market resource price sheet.",
        region="ID_NATIONAL",
        market="Indonesia",
        language="Bahasa Indonesia",
        lang_code="id",
        currency="IDR",
        flag="id",
        positions=2784,
        base_folder="Asia-Indonesia-AHSP",
        file_token="ID",
        catalog_token="ID",
        coefficient=True,
        repriceable_markets=49,
    ),
)

#: All base families, global first, then the national bases largest-first.
BASE_FAMILIES: tuple[BaseFamily, ...] = (_GLOBAL_FAMILY, *_NATIONAL_FAMILIES)


# ── Lookups shared by both routers ──────────────────────────────────────────


def iter_variants() -> list[BaseVariant]:
    """Return every loadable variant across all families (flat list)."""
    return [v for fam in BASE_FAMILIES for v in fam.variants]


# Only the canonical (home / global) variant per region: those have
# ``variant_id == region``. Market cards share their base's region but are not
# the loadable base themselves, so they are excluded and ``variant_by_region``
# always returns the home base for a region.
_BY_REGION: dict[str, BaseVariant] = {v.region: v for v in iter_variants() if v.variant_id == v.region}

#: Every known market token (the ``markets/`` file tokens), for endpoint validation.
_MARKET_TOKENS: frozenset[str] = frozenset(m.token for m in _MARKET_CATALOGS)

#: Home regions of the national bases - each ships per-language work-item parquets.
_NATIONAL_REGIONS: frozenset[str] = frozenset(fam.variants[0].region for fam in _NATIONAL_FAMILIES)


def variant_by_region(region: str) -> BaseVariant | None:
    """Return the canonical (home) variant for a platform region id, or ``None``."""
    return _BY_REGION.get(region)


def is_known_market(market_token: str) -> bool:
    """Return True when ``market_token`` names a real ``markets/`` catalog file."""
    return market_token in _MARKET_TOKENS


#: Market token -> its language code (the trailing token segment, e.g. ``ru``).
_MARKET_LANG: dict[str, str] = {m.token: m.lang_code for m in _MARKET_CATALOGS}


def market_lang_code(market_token: str) -> str | None:
    """Return a market's language code (e.g. ``RU_MOSCOW_ru`` -> ``ru``), or None."""
    return _MARKET_LANG.get(market_token)


def github_workitems_files() -> dict[str, str]:
    """Map region id to its work-item parquet path (repo-root relative).

    Only the real, user-loadable regions (home + global markets). The national
    bases' per-language parquets are a separate map,
    :func:`national_language_workitems_files`, so they resolve for a market-switch
    language swap without appearing in the ``/available-databases`` listing.
    """
    return {v.region: v.workitems_path for v in iter_variants()}


# ── Per-language work-item parquets for the national bases ──────────────────
# Every national base is translated into all app languages; each language ships
# a work-item parquet under ``<base_folder>/<LANG>___DDC_CWICR/`` mirroring the
# global base's per-market layout. A national base's market cards pick a language
# via the market's ``lang_code``; loading that market swaps the region's text to
# the language parquet (translated descriptions, categories and resources), then
# the existing market reprice sets the market's price level on top. Text follows
# the language; price follows the market - the two are orthogonal.
NATIONAL_TRANSLATION_LANGS: tuple[str, ...] = (
    "ar",
    "bg",
    "cs",
    "da",
    "de",
    "es",
    "fi",
    "fr",
    "hi",
    "hr",
    "id",
    "it",
    "ja",
    "ko",
    "mn",
    "nl",
    "no",
    "pl",
    "pt",
    "ro",
    "ru",
    "sv",
    "th",
    "tr",
    "vi",
    "zh",
)

_WORKITEMS_SUFFIX = "_workitems_costs_resources_DDC_CWICR.parquet"


def _national_base_parts(base_region: str) -> tuple[str, str] | None:
    """Return ``(base_folder, file_token)`` for a national base, else ``None``.

    Derived from the home variant's ``workitems_path``
    (``<base_folder>/<file_token>_workitems_costs_resources_DDC_CWICR.parquet``).
    """
    home = _BY_REGION.get(base_region)
    if home is None or base_region not in _NATIONAL_REGIONS:
        return None
    folder, _, filename = home.workitems_path.rpartition("/")
    if not filename.endswith(_WORKITEMS_SUFFIX):
        return None
    return folder, filename[: -len(_WORKITEMS_SUFFIX)]


def national_language_workitems_path(base_region: str, lang_code: str) -> str | None:
    """Repo-relative path of a national base's per-language work-item parquet.

    ``None`` when ``base_region`` is not a national base or ``lang_code`` is not a
    translated language.
    """
    if lang_code not in NATIONAL_TRANSLATION_LANGS:
        return None
    parts = _national_base_parts(base_region)
    if parts is None:
        return None
    folder, token = parts
    return f"{folder}/{lang_code.upper()}___DDC_CWICR/{token}_{lang_code}{_WORKITEMS_SUFFIX}"


def national_language_region(base_region: str, lang_code: str) -> str | None:
    """Loader ``db_id`` (``<region>_<lang>``) for a national language parquet.

    ``None`` when there is no distinct language parquet to load for this base and
    language (not national, or unknown language). Callers treat ``None`` as
    "keep the home parquet already loaded for ``base_region``".
    """
    if national_language_workitems_path(base_region, lang_code) is None:
        return None
    return f"{base_region}_{lang_code}"


def national_language_workitems_files() -> dict[str, str]:
    """Map every ``<region>_<lang>`` pseudo-region to its language parquet path."""
    out: dict[str, str] = {}
    for region in _NATIONAL_REGIONS:
        for lang in NATIONAL_TRANSLATION_LANGS:
            path = national_language_workitems_path(region, lang)
            if path is not None:
                out[f"{region}_{lang}"] = path
    return out


def github_catalog_folder(region: str) -> str | None:
    """Return the repo folder holding a region's resource-catalog CSV."""
    v = _BY_REGION.get(region)
    return v.catalog_folder if v else None


def catalog_token(region: str) -> str | None:
    """Return the token used in ``DDC_CWICR_<token>_Catalog.csv`` for a region."""
    v = _BY_REGION.get(region)
    return v.catalog_token if v else None


def _variant_public(v: BaseVariant, loaded_counts: dict[str, int]) -> dict:
    # A base's load lands under its base_region, and every card of that base
    # shares it, so all cards of a loaded base read as loaded (the active card
    # is tracked client-side in this MVP; the registry reports active=False).
    loaded = loaded_counts.get(v.base_region, 0)
    return {
        "region": v.region,
        "variant_id": v.variant_id,
        "base_region": v.base_region,
        "market_catalog": v.market_catalog,
        "market": v.market,
        "city": v.city,
        "language": v.language,
        "lang_code": v.lang_code,
        "currency": v.currency,
        "flag": v.flag,
        "positions": v.positions,
        "bundled": v.bundled,
        "coefficient": v.coefficient,
        "active": v.active,
        "loaded": loaded > 10,
        "loaded_positions": loaded,
    }


def public_catalog(loaded_counts: dict[str, int] | None = None) -> dict:
    """Serialize the catalog for the API, merging live loaded counts.

    Args:
        loaded_counts: Region id to the number of currently loaded, active cost
            items, from ``oe_costs_item``. A region with more than 10 loaded
            items is marked ``loaded`` and carries its real count so the browser
            shows the true figure after import rather than only the estimate.

    Returns:
        A JSON-ready dict with a ``families`` list and roll-up totals.
    """
    counts = loaded_counts or {}
    families = []
    for fam in BASE_FAMILIES:
        variants = [_variant_public(v, counts) for v in fam.variants]
        families.append(
            {
                "key": fam.key,
                "name": fam.name,
                "norm_system": fam.norm_system,
                "origin": fam.origin,
                "origin_flag": fam.origin_flag,
                "description": fam.description,
                "market_count": len(fam.variants),
                "repriceable_markets": fam.repriceable_markets,
                # Representative catalogue size: markets in a family share the
                # same work-item count, so the first variant is representative.
                "positions": fam.variants[0].positions if fam.variants else 0,
                "loaded_count": sum(1 for v in variants if v["loaded"]),
                "variants": variants,
            }
        )
    all_variants = iter_variants()
    return {
        "repo": REPO,
        "families": families,
        "total_bases": len(all_variants),
        "total_families": len(BASE_FAMILIES),
        "loaded_regions": sorted(r for r, c in counts.items() if c > 10),
    }
