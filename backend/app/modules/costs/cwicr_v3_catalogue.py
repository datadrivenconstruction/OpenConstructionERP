# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Registry of DDC v3 BGE-M3 catalogues — the 30-region master list.

This is the single source of truth that the ``GET /catalogues-v3/``
endpoint serves to the frontend. Each entry describes one CWICR region
DDC publishes (or plans to publish) a BGE-M3 v3 snapshot for, together
with the metadata the UI needs to render a card:

* ``region``        — canonical CWICR region id (``RU_STPETERSBURG``)
* ``country_iso``   — ISO-3166 alpha-2 / alpha-3 head, used for the
                      flag component on the frontend
* ``city``          — city / locale qualifier for the display name
* ``language``      — ISO-639-1 code (drives the
                      ``cwicr_{lang}_v3`` collection name)
* ``currency``      — ISO 4217 of the rates inside the catalogue
* ``ddc_path``      — relative path inside the DDC GitHub repo
                      (``<LANG>___DDC_CWICR/<region>_workitems_…_BGEM3_V3_DDC_CWICR.snapshot``)
* ``size_mb``       — best-effort estimated size; used so the UI can
                      warn about download cost before starting
* ``available``     — ``True`` if DDC has actually published the v3
                      snapshot today. Regions still on the v3 backlog
                      ship as ``available=False`` so the frontend can
                      grey them out with a "Coming soon" badge instead
                      of erroring on click.

How this list grows:

* DDC publishes new v3 snapshots → flip ``available`` to ``True`` and
  fill in the real ``size_mb``. A nightly probe job is on the v4
  backlog; for now this is a manual, intentional curation.
* New regions enter CWICR (e.g. an Ireland catalogue) → add a row,
  mirror in :mod:`region_language` so the language collection routes,
  ship.

The registry is intentionally *not* derived from
:mod:`region_language` — that table grows for any catalogue someone
loads (BYO third-party rates, alias rows, deprecated cities) and we
don't want every alias to surface as a downloadable card on /setup.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass


@dataclass(frozen=True)
class CwicrV3Catalogue:
    """‌⁠‍One row in the v3 catalogue registry. Frozen so callers can't mutate."""

    region: str
    country_iso: str
    city: str
    language: str
    currency: str
    ddc_path: str
    size_mb: int
    available: bool
    # Hint for the match-elements pipeline when a project picks this
    # catalogue but has no explicit ``classification_standard`` set. The
    # field is intentionally optional (default empty string) so legacy
    # callers that construct ``CwicrV3Catalogue`` positionally don't
    # break. Populated for entries with an obvious 1:1 mapping (DACH →
    # din276, US/Anglo → masterformat, UK/IE → nrm, …); left empty when
    # the regional standard isn't a clean fit. See task #39 in the 2-day
    # universalisation plan.
    default_classification_standard: str = ""

    @property
    def collection(self) -> str:
        """‌⁠‍Target Qdrant collection — the search-time name."""
        return f"cwicr_{self.language}_v3"


# ── Master list ──────────────────────────────────────────────────────────
#
# Order: alphabetical by ``region`` — the UI sorts by ``country_iso`` /
# language anyway, but a stable backend order keeps diffs readable.
#
# ``size_mb`` for ``available=True`` rows is the actual file size
# observed on GitHub; for ``available=False`` it's the legacy 3072-dim
# size as a rough estimate so the UI can still say "~XXX MB expected".


CWICR_V3_CATALOGUES: tuple[CwicrV3Catalogue, ...] = (
    # ── German-speaking (DACH) ────────────────────────────────────────
    CwicrV3Catalogue(
        region="DE_BERLIN",
        country_iso="DE",
        city="Berlin",
        language="de",
        currency="EUR",
        ddc_path="DE___DDC_CWICR/DE_BERLIN_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
        default_classification_standard="din276",
    ),
    CwicrV3Catalogue(
        region="DE_MUNICH",
        country_iso="DE",
        city="Munich",
        language="de",
        currency="EUR",
        ddc_path="DE___DDC_CWICR/DE_MUNICH_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
        default_classification_standard="din276",
    ),
    CwicrV3Catalogue(
        region="AT_VIENNA",
        country_iso="AT",
        city="Vienna",
        language="de",
        currency="EUR",
        ddc_path="AT___DDC_CWICR/AT_VIENNA_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
        default_classification_standard="din276",
    ),
    CwicrV3Catalogue(
        region="CH_ZURICH",
        country_iso="CH",
        city="Zurich",
        language="de",
        currency="CHF",
        ddc_path="CH___DDC_CWICR/CH_ZURICH_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
        default_classification_standard="din276",
    ),
    # ── English-speaking ─────────────────────────────────────────────
    CwicrV3Catalogue(
        region="USA_USD",
        country_iso="US",
        city="National (USD)",
        language="en",
        currency="USD",
        ddc_path="EN___DDC_CWICR/USA_USD_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
        default_classification_standard="masterformat",
    ),
    CwicrV3Catalogue(
        region="GB_LONDON",
        country_iso="GB",
        city="London",
        language="en",
        currency="GBP",
        ddc_path="EN___DDC_CWICR/GB_LONDON_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
        default_classification_standard="nrm",
    ),
    CwicrV3Catalogue(
        region="CA_TORONTO",
        country_iso="CA",
        city="Toronto",
        language="en",
        currency="CAD",
        # DDC publishes this snapshot under the legacy `ENG_TORONTO_*`
        # filename (region_language treats ENG_TORONTO as an alias for
        # CA_TORONTO). Pulls the real file from GitHub LFS; the row stays
        # keyed to CA_TORONTO so cwicr_en_v3 routing is unchanged.
        ddc_path="EN___DDC_CWICR/ENG_TORONTO_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=415,
        available=True,
        default_classification_standard="masterformat",
    ),
    CwicrV3Catalogue(
        region="AU_SYDNEY",
        country_iso="AU",
        city="Sydney",
        language="en",
        currency="AUD",
        ddc_path="EN___DDC_CWICR/AU_SYDNEY_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
        default_classification_standard="masterformat",
    ),
    CwicrV3Catalogue(
        region="IN_MUMBAI",
        country_iso="IN",
        city="Mumbai",
        language="en",
        currency="INR",
        ddc_path="EN___DDC_CWICR/IN_MUMBAI_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
        default_classification_standard="masterformat",
    ),
    CwicrV3Catalogue(
        region="NG_LAGOS",
        country_iso="NG",
        city="Lagos",
        language="en",
        currency="NGN",
        ddc_path="EN___DDC_CWICR/NG_LAGOS_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
        default_classification_standard="nrm",
    ),
    CwicrV3Catalogue(
        region="ZA_JOHANNESBURG",
        country_iso="ZA",
        city="Johannesburg",
        language="en",
        currency="ZAR",
        ddc_path="EN___DDC_CWICR/ZA_JOHANNESBURG_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
        default_classification_standard="masterformat",
    ),
    CwicrV3Catalogue(
        region="KE_NAIROBI",
        country_iso="KE",
        city="Nairobi",
        language="en",
        currency="KES",
        ddc_path="EN___DDC_CWICR/KE_NAIROBI_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
        default_classification_standard="nrm",
    ),
    CwicrV3Catalogue(
        region="GH_ACCRA",
        country_iso="GH",
        city="Accra",
        language="en",
        currency="GHS",
        ddc_path="EN___DDC_CWICR/GH_ACCRA_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
        default_classification_standard="nrm",
    ),
    CwicrV3Catalogue(
        region="UG_KAMPALA",
        country_iso="UG",
        city="Kampala",
        language="en",
        currency="UGX",
        ddc_path="EN___DDC_CWICR/UG_KAMPALA_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
        default_classification_standard="nrm",
    ),
    CwicrV3Catalogue(
        region="TZ_DARESSALAAM",
        country_iso="TZ",
        city="Dar es Salaam",
        language="en",
        currency="TZS",
        ddc_path="EN___DDC_CWICR/TZ_DARESSALAAM_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
        default_classification_standard="nrm",
    ),
    # ── Romance ──────────────────────────────────────────────────────
    CwicrV3Catalogue(
        region="FR_PARIS",
        country_iso="FR",
        city="Paris",
        language="fr",
        currency="EUR",
        ddc_path="FR___DDC_CWICR/FR_PARIS_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
        default_classification_standard="untec",
    ),
    CwicrV3Catalogue(
        region="SN_DAKAR",
        country_iso="SN",
        city="Dakar",
        language="fr",
        currency="XOF",
        ddc_path="FR___DDC_CWICR/SN_DAKAR_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
        default_classification_standard="untec",
    ),
    CwicrV3Catalogue(
        region="CI_ABIDJAN",
        country_iso="CI",
        city="Abidjan",
        language="fr",
        currency="XOF",
        ddc_path="FR___DDC_CWICR/CI_ABIDJAN_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
        default_classification_standard="untec",
    ),
    CwicrV3Catalogue(
        region="CM_DOUALA",
        country_iso="CM",
        city="Douala",
        language="fr",
        currency="XAF",
        ddc_path="FR___DDC_CWICR/CM_DOUALA_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
        default_classification_standard="untec",
    ),
    CwicrV3Catalogue(
        region="ES_MADRID",
        country_iso="ES",
        city="Madrid",
        language="es",
        currency="EUR",
        ddc_path="ES___DDC_CWICR/ES_MADRID_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
        default_classification_standard="bc3",
    ),
    CwicrV3Catalogue(
        region="IT_ROME",
        country_iso="IT",
        city="Rome",
        language="it",
        currency="EUR",
        ddc_path="IT___DDC_CWICR/IT_ROME_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
        default_classification_standard="voci",
    ),
    CwicrV3Catalogue(
        region="PT_LISBON",
        country_iso="PT",
        city="Lisbon",
        language="pt",
        currency="EUR",
        ddc_path="PT___DDC_CWICR/PT_LISBON_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
    ),
    CwicrV3Catalogue(
        region="BR_SAOPAULO",
        country_iso="BR",
        city="São Paulo",
        language="pt",
        currency="BRL",
        ddc_path="PT___DDC_CWICR/BR_SAOPAULO_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
        # Brazil's de-facto reference cost base is Caixa/IBGE SINAPI; pin it
        # so a project that picks the São Paulo catalogue without an explicit
        # standard still gets the right validation pack at import time.
        default_classification_standard="sinapi",
    ),
    CwicrV3Catalogue(
        region="AO_LUANDA",
        country_iso="AO",
        city="Luanda",
        language="pt",
        currency="AOA",
        ddc_path="PT___DDC_CWICR/AO_LUANDA_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
        default_classification_standard="masterformat",
    ),
    CwicrV3Catalogue(
        region="MX_MEXICO",
        country_iso="MX",
        city="Mexico City",
        language="es",
        currency="MXN",
        ddc_path="ES___DDC_CWICR/MX_MEXICO_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
    ),
    CwicrV3Catalogue(
        region="AR_BUENOSAIRES",
        country_iso="AR",
        city="Buenos Aires",
        language="es",
        currency="ARS",
        ddc_path="ES___DDC_CWICR/AR_BUENOSAIRES_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
    ),
    # ── Slavic / CIS ─────────────────────────────────────────────────
    CwicrV3Catalogue(
        region="RU_STPETERSBURG",
        country_iso="RU",
        city="St. Petersburg",
        language="ru",
        currency="RUB",
        ddc_path="RU___DDC_CWICR/RU_STPETERSBURG_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=415,
        available=True,
        default_classification_standard="gesn",
    ),
    CwicrV3Catalogue(
        region="RU_MOSCOW",
        country_iso="RU",
        city="Moscow",
        language="ru",
        currency="RUB",
        ddc_path="RU___DDC_CWICR/RU_MOSCOW_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=415,
        available=False,
        default_classification_standard="gesn",
    ),
    CwicrV3Catalogue(
        region="PL_WARSAW",
        country_iso="PL",
        city="Warsaw",
        language="pl",
        currency="PLN",
        ddc_path="PL___DDC_CWICR/PL_WARSAW_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
    ),
    CwicrV3Catalogue(
        region="CZ_PRAGUE",
        country_iso="CZ",
        city="Prague",
        language="cs",
        currency="CZK",
        ddc_path="CZ___DDC_CWICR/CZ_PRAGUE_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
    ),
    CwicrV3Catalogue(
        region="RO_BUCHAREST",
        country_iso="RO",
        city="Bucharest",
        language="ro",
        currency="RON",
        ddc_path="RO___DDC_CWICR/RO_BUCHAREST_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
    ),
    # ── Benelux / Nordic ─────────────────────────────────────────────
    CwicrV3Catalogue(
        region="NL_AMSTERDAM",
        country_iso="NL",
        city="Amsterdam",
        language="nl",
        currency="EUR",
        ddc_path="NL___DDC_CWICR/NL_AMSTERDAM_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
    ),
    CwicrV3Catalogue(
        region="SV_STOCKHOLM",
        country_iso="SE",
        city="Stockholm",
        language="sv",
        currency="SEK",
        ddc_path="SV___DDC_CWICR/SV_STOCKHOLM_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
    ),
    # ── Asia / MENA ──────────────────────────────────────────────────
    CwicrV3Catalogue(
        region="CN_SHANGHAI",
        country_iso="CN",
        city="Shanghai",
        language="zh",
        currency="CNY",
        ddc_path="ZH___DDC_CWICR/CN_SHANGHAI_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
        default_classification_standard="gb50500",
    ),
    CwicrV3Catalogue(
        region="JP_TOKYO",
        country_iso="JP",
        city="Tokyo",
        language="ja",
        currency="JPY",
        ddc_path="JA___DDC_CWICR/JP_TOKYO_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
        default_classification_standard="sekisan",
    ),
    CwicrV3Catalogue(
        region="KR_SEOUL",
        country_iso="KR",
        city="Seoul",
        language="ko",
        currency="KRW",
        ddc_path="KO___DDC_CWICR/KR_SEOUL_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
        default_classification_standard="kbim",
    ),
    CwicrV3Catalogue(
        region="TR_ISTANBUL",
        country_iso="TR",
        city="Istanbul",
        language="tr",
        currency="TRY",
        ddc_path="TR___DDC_CWICR/TR_ISTANBUL_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
        default_classification_standard="birimfiyat",
    ),
    CwicrV3Catalogue(
        region="AE_DUBAI",
        country_iso="AE",
        city="Dubai",
        language="ar",
        currency="AED",
        ddc_path="AR___DDC_CWICR/AE_DUBAI_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
    ),
    CwicrV3Catalogue(
        region="MA_CASABLANCA",
        country_iso="MA",
        city="Casablanca",
        language="ar",
        currency="MAD",
        ddc_path="AR___DDC_CWICR/MA_CASABLANCA_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
        default_classification_standard="masterformat",
    ),
    CwicrV3Catalogue(
        region="EG_CAIRO",
        country_iso="EG",
        city="Cairo",
        language="ar",
        currency="EGP",
        ddc_path="AR___DDC_CWICR/EG_CAIRO_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
        default_classification_standard="masterformat",
    ),
    CwicrV3Catalogue(
        region="TN_TUNIS",
        country_iso="TN",
        city="Tunis",
        language="ar",
        currency="TND",
        ddc_path="AR___DDC_CWICR/TN_TUNIS_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
        default_classification_standard="masterformat",
    ),
    CwicrV3Catalogue(
        region="ID_JAKARTA",
        country_iso="ID",
        city="Jakarta",
        language="id",
        currency="IDR",
        ddc_path="ID___DDC_CWICR/ID_JAKARTA_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
    ),
    # ── Newly published on HF 2026-05-14 ────────────────────────────────
    # All six rows below are flipped to ``available=True`` via the
    # ``_HF_PUBLISHED`` mapping after construction, so the ``ddc_path``
    # here is the legacy GitHub path used for documentation only.
    CwicrV3Catalogue(
        region="MN_ULAANBAATAR",
        country_iso="MN",
        city="Ulaanbaatar",
        language="mn",
        currency="MNT",
        ddc_path="MN___DDC_CWICR/MN_ULAANBAATAR_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=916,
        available=False,
    ),
    CwicrV3Catalogue(
        region="BG_SOFIA",
        country_iso="BG",
        city="Sofia",
        language="bg",
        currency="BGN",
        ddc_path="BG___DDC_CWICR/BG_SOFIA_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
    ),
    CwicrV3Catalogue(
        region="HR_ZAGREB",
        country_iso="HR",
        city="Zagreb",
        language="hr",
        currency="EUR",
        ddc_path="HR___DDC_CWICR/HR_ZAGREB_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
    ),
    CwicrV3Catalogue(
        region="NZ_AUCKLAND",
        country_iso="NZ",
        city="Auckland",
        language="en",
        currency="NZD",
        ddc_path="NZ___DDC_CWICR/NZ_AUCKLAND_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
        default_classification_standard="nrm",
    ),
    CwicrV3Catalogue(
        region="TH_BANGKOK",
        country_iso="TH",
        city="Bangkok",
        language="th",
        currency="THB",
        ddc_path="TH___DDC_CWICR/TH_BANGKOK_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
    ),
    CwicrV3Catalogue(
        region="VI_HANOI",
        country_iso="VN",
        city="Hanoi",
        language="vi",
        currency="VND",
        ddc_path="VI___DDC_CWICR/VI_HANOI_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot",
        size_mb=420,
        available=False,
    ),
)


# ── HuggingFace overrides ─────────────────────────────────────────────────
#
# DDC publishes the production v3 BGE-M3 snapshots on HF dataset
# `DataDrivenConstruction/cwicr-vector-db-bgem3-v3`. Folder layout uses
# 2-letter language/locale codes; some filenames use legacy region IDs that
# differ from our internal ``region`` keys (e.g. our CA_TORONTO maps to
# the legacy ENG_TORONTO file). Where DDC publishes only one snapshot per
# language, every region in that language family reuses it — same pattern
# as PT_LISBON sharing PT_SAOPAULO. Cross-locale BGE-M3 embeddings make
# the lexical drift (e.g. "vidrio templado" vs "cristal") tolerable; pricing
# differences are folded in by the FX layer at match time.
HF_CWICR_DATASET = "DataDrivenConstruction/cwicr-vector-db-bgem3-v3"
HF_CWICR_BASE_URL = f"https://huggingface.co/datasets/{HF_CWICR_DATASET}/resolve/main"

_HF_PUBLISHED: dict[str, tuple[str, str]] = {
    # internal region id -> (hf_folder, hf_filename_stem)
    "AE_DUBAI": ("AR", "AR_DUBAI"),
    "MA_CASABLANCA": ("AR", "AR_DUBAI"),
    "EG_CAIRO": ("AR", "AR_DUBAI"),
    "TN_TUNIS": ("AR", "AR_DUBAI"),
    "AU_SYDNEY": ("AU", "AU_SYDNEY"),
    "CZ_PRAGUE": ("CS", "CS_PRAGUE"),
    "DE_BERLIN": ("DE", "DE_BERLIN"),
    "DE_MUNICH": ("DE", "DE_BERLIN"),
    "AT_VIENNA": ("DE", "DE_BERLIN"),
    "CH_ZURICH": ("DE", "DE_BERLIN"),
    "CA_TORONTO": ("EN", "ENG_TORONTO"),
    "KE_NAIROBI": ("EN", "ENG_TORONTO"),
    "GH_ACCRA": ("EN", "ENG_TORONTO"),
    "UG_KAMPALA": ("EN", "ENG_TORONTO"),
    "TZ_DARESSALAAM": ("EN", "ENG_TORONTO"),
    "ES_MADRID": ("ES", "SP_BARCELONA"),
    "AR_BUENOSAIRES": ("ES", "SP_BARCELONA"),
    "FR_PARIS": ("FR", "FR_PARIS"),
    "SN_DAKAR": ("FR", "FR_PARIS"),
    "CI_ABIDJAN": ("FR", "FR_PARIS"),
    "CM_DOUALA": ("FR", "FR_PARIS"),
    "IN_MUMBAI": ("HI", "HI_MUMBAI"),
    "ID_JAKARTA": ("ID", "ID_JAKARTA"),
    "IT_ROME": ("IT", "IT_ROME"),
    "JP_TOKYO": ("JA", "JA_TOKYO"),
    "KR_SEOUL": ("KO", "KO_SEOUL"),
    "MX_MEXICO": ("MX", "MX_MEXICOCITY"),
    "NG_LAGOS": ("NG", "NG_LAGOS"),
    "NL_AMSTERDAM": ("NL", "NL_AMSTERDAM"),
    "PL_WARSAW": ("PL", "PL_WARSAW"),
    "BR_SAOPAULO": ("PT", "PT_SAOPAULO"),
    "PT_LISBON": ("PT", "PT_SAOPAULO"),
    "AO_LUANDA": ("PT", "PT_SAOPAULO"),
    "RO_BUCHAREST": ("RO", "RO_BUCHAREST"),
    "RU_STPETERSBURG": ("RU", "RU_STPETERSBURG"),
    "RU_MOSCOW": ("RU", "RU_STPETERSBURG"),
    "SV_STOCKHOLM": ("SV", "SV_STOCKHOLM"),
    "TR_ISTANBUL": ("TR", "TR_ISTANBUL"),
    "GB_LONDON": ("UK", "UK_GBP"),
    "USA_USD": ("US", "USA_USD"),
    "ZA_JOHANNESBURG": ("ZA", "ZA_JOHANNESBURG"),
    "CN_SHANGHAI": ("ZH", "ZH_SHANGHAI"),
    # Newly published 2026-05-14 — folder/stem match the HF tree directly.
    "MN_ULAANBAATAR": ("MN", "MN_ULAANBAATAR"),
    "BG_SOFIA": ("BG", "BG_SOFIA"),
    "HR_ZAGREB": ("HR", "HR_ZAGREB"),
    "NZ_AUCKLAND": ("NZ", "NZ_AUCKLAND"),
    "TH_BANGKOK": ("TH", "TH_BANGKOK"),
    "VI_HANOI": ("VI", "VI_HANOI"),
}


def _apply_hf_overrides(
    entries: tuple[CwicrV3Catalogue, ...],
) -> tuple[CwicrV3Catalogue, ...]:
    """Rewrite ddc_path + available=True for catalogues HF actually hosts.

    Frozen dataclass means a new tuple of replaced rows is built; entries
    not in ``_HF_PUBLISHED`` pass through unchanged (still ``available=False``,
    still pointing at their legacy GitHub path).
    """

    out: list[CwicrV3Catalogue] = []
    for cat in entries:
        hf = _HF_PUBLISHED.get(cat.region)
        if hf is None:
            out.append(cat)
            continue
        folder, stem = hf
        # MN ships a far larger snapshot (~916 MB) than the average
        # 415 MB row; honour the per-region size declared in the
        # registry when it's been set above the default, otherwise
        # fall back to the HF-typical 415 MB.
        size_mb = cat.size_mb if cat.size_mb > 415 else 415
        out.append(
            dataclasses.replace(
                cat,
                ddc_path=(f"{folder}/{stem}_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot"),
                available=True,
                size_mb=size_mb,
            )
        )
    return tuple(out)


CWICR_V3_CATALOGUES = _apply_hf_overrides(CWICR_V3_CATALOGUES)


def get_catalogue(region: str) -> CwicrV3Catalogue | None:
    """Return the registry entry for ``region`` or ``None`` if unknown.

    Lookup is case-insensitive on the input but exact on the keys —
    aliases are NOT followed. A caller hitting the install endpoint
    with a legacy id (``UK_GBP``, ``ENG_TORONTO``) gets a clear 404
    instead of a silently-wrong restore. Convert via
    :mod:`region_language._ALIASES` upstream if alias support is
    needed.
    """

    if not region:
        return None
    key = region.strip().upper()
    for cat in CWICR_V3_CATALOGUES:
        if cat.region == key:
            return cat
    return None


__all__ = [
    "CWICR_V3_CATALOGUES",
    "CwicrV3Catalogue",
    "HF_CWICR_BASE_URL",
    "HF_CWICR_DATASET",
    "get_catalogue",
]
