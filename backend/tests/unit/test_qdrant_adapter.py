# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Unit tests for the CWICR Qdrant adapter — region→collection routing.

The heavy paths (encoder + Qdrant Query API + parquet lookup) need a
live Qdrant + parquet root and are exercised by the smoke endpoint
under ``/api/v1/costs/qdrant-search/``. These unit tests pin the pure
helpers so the routing contract can't drift silently.

Per MAPPING_PROCESS.md v3 (§2.1, §6.1) collections are keyed by
*language* (``cwicr_de_v3``, ``cwicr_ru_v3``), not by country. The
country lives in the payload and is filtered separately so a single
Spanish collection can carry rates for ES + MX + AR.
"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.modules.costs.qdrant_adapter import (
    _RELAX_TIERS,
    QdrantHit,
    _build_filter,
    _collection_vectors,
    _collection_vectors_cache,
    _dedup_hits,
    _dedup_hits_by_base_code,
    _enumerate_target_codes,
    _filters_after_relax,
    _normalise_unit_dim,
    base_code,
    country_filter_for,
    country_to_collection,
    cross_lang_lookup,
    cross_language_search,
    search_with_fallback,
    substitute_abstract_parents,
)


@pytest.fixture(autouse=True)
def _clear_settings_cache(monkeypatch: pytest.MonkeyPatch):
    """Isolate the pure region→collection routing contract.

    Two things are pinned here:

    * ``get_settings`` cache is cleared around every test so per-test
      ``CWICR_COLLECTION_VERSION`` overrides take effect.
    * ``CWICR_COLLECTION_PROBE=0`` disables the live-Qdrant availability
      probe in :func:`country_to_collection`. These unit tests assert the
      *pure* routing contract (``DE_BERLIN`` → ``cwicr_de_v3``); without
      the probe disabled they fail non-deterministically on any host with
      a reachable-but-sparsely-populated Qdrant (the production fallback
      would substitute whatever collection happens to be present). The
      probe-on fallback behaviour is covered separately by the
      ``test_probe_*`` tests which re-enable the probe and mock
      ``_available_cwicr_collections``.
    """
    monkeypatch.setenv("CWICR_COLLECTION_PROBE", "0")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ── Region id → language collection (v3 schema) ──────────────────────────


@pytest.mark.parametrize(
    ("region", "collection"),
    [
        # German-speaking regions all land in cwicr_de_v3
        ("DE_BERLIN", "cwicr_de_v3"),
        ("DE_MUNICH", "cwicr_de_v3"),
        ("AT_VIENNA", "cwicr_de_v3"),
        ("CH_ZURICH", "cwicr_de_v3"),
        # Spanish-speaking — ES + MX + AR collapse to cwicr_es_v3
        ("ES_MADRID", "cwicr_es_v3"),
        ("MX_MEXICO", "cwicr_es_v3"),
        ("MX_MEXICOCITY", "cwicr_es_v3"),
        ("AR_BUENOSAIRES", "cwicr_es_v3"),
        # Portuguese — PT + BR
        ("PT_LISBON", "cwicr_pt_v3"),
        ("BR_SAOPAULO", "cwicr_pt_v3"),
        # English-speaking — UK / US / CA / AU / NZ / ZA / NG / IN
        ("GB_LONDON", "cwicr_en_v3"),
        ("USA_USD", "cwicr_en_v3"),
        ("USA_NEWYORK", "cwicr_en_v3"),
        ("CA_TORONTO", "cwicr_en_v3"),
        ("AU_SYDNEY", "cwicr_en_v3"),
        ("NZ_AUCKLAND", "cwicr_en_v3"),
        ("ZA_JOHANNESBURG", "cwicr_en_v3"),
        ("NG_LAGOS", "cwicr_en_v3"),
        ("IN_MUMBAI", "cwicr_en_v3"),
        # Slavic / CIS
        ("RU_STPETERSBURG", "cwicr_ru_v3"),
        ("RU_MOSCOW", "cwicr_ru_v3"),
        ("PL_WARSAW", "cwicr_pl_v3"),
        ("CZ_PRAGUE", "cwicr_cs_v3"),
        ("BG_SOFIA", "cwicr_bg_v3"),
        ("RO_BUCHAREST", "cwicr_ro_v3"),
        ("HR_ZAGREB", "cwicr_hr_v3"),
        # Benelux
        ("NL_AMSTERDAM", "cwicr_nl_v3"),
        ("BE_BRUSSELS", "cwicr_nl_v3"),
        # Romance
        ("FR_PARIS", "cwicr_fr_v3"),
        ("IT_ROME", "cwicr_it_v3"),
        # Asian + MENA
        ("ZH_CHINA", "cwicr_zh_v3"),
        ("CN_SHANGHAI", "cwicr_zh_v3"),
        ("JP_TOKYO", "cwicr_ja_v3"),
        ("KR_SEOUL", "cwicr_ko_v3"),
        ("ID_JAKARTA", "cwicr_id_v3"),
        ("TH_BANGKOK", "cwicr_th_v3"),
        ("VN_HANOI", "cwicr_vi_v3"),
        ("AE_DUBAI", "cwicr_ar_v3"),
        ("SA_RIYADH", "cwicr_ar_v3"),
        ("TR_NATIONAL", "cwicr_tr_v3"),
        ("TR_ISTANBUL", "cwicr_tr_v3"),
        ("HI_MUMBAI", "cwicr_hi_v3"),
        ("SV_STOCKHOLM", "cwicr_sv_v3"),
        # Authentic national / regional official bases (2026-07 world-cost
        # -bases wave, task #31). ZH_CHINA and TR_NATIONAL above are the two
        # earlier members of this wave; the rest share a language collection
        # with a metro catalogue except GR_NATIONAL, whose Greek "el" head
        # opens the brand-new cwicr_el_v3 collection.
        ("BR_NATIONAL", "cwicr_pt_v3"),  # SINAPI, shares Portuguese collection
        ("ES_ANDALUCIA", "cwicr_es_v3"),  # BCCA Andalucia
        ("IT_TOSCANA", "cwicr_it_v3"),  # Prezzario Regione Toscana
        ("VN_NATIONAL", "cwicr_vi_v3"),  # Dinh Muc national norms
        ("ID_NATIONAL", "cwicr_id_v3"),  # AHSP national analyses
        ("GR_NATIONAL", "cwicr_el_v3"),  # GGDE - brand-new Greek collection
    ],
)
def test_region_id_resolves_to_language_collection(region: str, collection: str) -> None:
    """``DE_BERLIN`` → ``cwicr_de_v3`` — locality ignored, language picked."""
    assert country_to_collection(region) == collection


# ── Bare country code (head fallback) ────────────────────────────────────


@pytest.mark.parametrize(
    ("country", "collection"),
    [
        ("DE", "cwicr_de_v3"),
        ("FR", "cwicr_fr_v3"),
        ("IT", "cwicr_it_v3"),
        ("ES", "cwicr_es_v3"),
        ("PL", "cwicr_pl_v3"),
        ("RU", "cwicr_ru_v3"),
        ("CZ", "cwicr_cs_v3"),  # Czech Republic → Czech language
        ("BG", "cwicr_bg_v3"),
        ("RO", "cwicr_ro_v3"),
        ("NL", "cwicr_nl_v3"),
        ("PT", "cwicr_pt_v3"),
        ("HR", "cwicr_hr_v3"),
        ("AR", "cwicr_es_v3"),  # Argentina → Spanish (NOT Arabic — see overrides)
        ("CN", "cwicr_zh_v3"),
        ("JP", "cwicr_ja_v3"),
        ("KR", "cwicr_ko_v3"),
        ("ID", "cwicr_id_v3"),
        ("TR", "cwicr_tr_v3"),
        ("AE", "cwicr_ar_v3"),
        ("SA", "cwicr_ar_v3"),
        # Anglophone bare codes
        ("GB", "cwicr_en_v3"),
        ("USA", "cwicr_en_v3"),
        ("CA", "cwicr_en_v3"),
        ("AU", "cwicr_en_v3"),
        ("NZ", "cwicr_en_v3"),
        ("ZA", "cwicr_en_v3"),
        ("NG", "cwicr_en_v3"),
        ("IN", "cwicr_en_v3"),
    ],
)
def test_bare_country_code_resolves_via_head_fallback(country: str, collection: str) -> None:
    """``"DE"`` (no city) still routes to ``cwicr_de_v3`` via head fallback."""
    assert country_to_collection(country) == collection


# ── Edge cases ───────────────────────────────────────────────────────────


def test_empty_country_falls_back_to_english() -> None:
    """Empty / whitespace / None all collapse to the English collection."""
    assert country_to_collection("") == "cwicr_en_v3"
    assert country_to_collection(None) == "cwicr_en_v3"
    assert country_to_collection("   ") == "cwicr_en_v3"


def test_input_is_case_insensitive() -> None:
    assert country_to_collection("de_berlin") == "cwicr_de_v3"
    assert country_to_collection("De_Berlin") == "cwicr_de_v3"
    assert country_to_collection("DE_BERLIN") == "cwicr_de_v3"


def test_unknown_country_falls_back_to_english() -> None:
    """Unknown two-letter prefixes fall back to English instead of
    making up a collection name. Pre-v3 we lowercased through, but
    since the v3 collections are language-keyed and there's no
    ``cwicr_zz_v3`` to query, sending such requests to ``cwicr_en_v3``
    at least produces graceful degradation instead of a 404 from
    Qdrant."""
    assert country_to_collection("ZZ_TEST") == "cwicr_en_v3"
    assert country_to_collection("XX") == "cwicr_en_v3"


# ── Collection version override ──────────────────────────────────────────


def test_collection_version_overridable_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Setting ``CWICR_COLLECTION_VERSION=v4`` flips the suffix so the app
    can read a future-schema index without a code change."""
    monkeypatch.setenv("CWICR_COLLECTION_VERSION", "v4")
    get_settings.cache_clear()
    assert country_to_collection("DE_BERLIN") == "cwicr_de_v4"


def test_empty_collection_version_strips_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    """Legacy installs that vectorised before the v3 cutover can pin
    ``CWICR_COLLECTION_VERSION=`` to read pre-v3 ``cwicr_<lang>``
    collections without renaming them."""
    monkeypatch.setenv("CWICR_COLLECTION_VERSION", "")
    get_settings.cache_clear()
    assert country_to_collection("DE_BERLIN") == "cwicr_de"


# ── country_filter_for ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("region", "expected"),
    [
        ("DE_BERLIN", "DE"),
        ("MX_MEXICO", "MX"),
        ("BR_SAOPAULO", "BR"),
        ("AT_VIENNA", "AT"),  # different country in same lang collection
        ("CH_ZURICH", "CH"),
        # v3.0.5: 3-letter heads remap to the 2-letter code DDC writes
        # into the snapshot's ``country`` payload. ``USA_USD`` would
        # otherwise filter to literal ``"USA"`` and exclude every US
        # rate (the snapshot has ``country: "US"``).
        ("USA_USD", "US"),
        ("ENG_TORONTO", "CA"),  # Canadian-English file DDC ships
        ("GBR_LONDON", "GB"),  # defensive
        ("ZH_CHINA", "CN"),
        # National bases (2026-07 wave, task #31): the region prefix already is
        # the ISO-3166 alpha-2 code DDC writes into the ``country`` payload, so
        # none of these needs a head alias. ZH_CHINA above is the sole
        # language-prefixed exception (ZH -> CN via _REGION_HEAD_ALIASES).
        ("TR_NATIONAL", "TR"),
        ("BR_NATIONAL", "BR"),
        ("ES_ANDALUCIA", "ES"),
        ("IT_TOSCANA", "IT"),
        ("VN_NATIONAL", "VN"),
        ("ID_NATIONAL", "ID"),
        ("GR_NATIONAL", "GR"),
        ("ru_stpetersburg", "RU"),  # case-normalisation
    ],
)
def test_country_filter_pins_specific_region_within_language_collection(region: str, expected: str) -> None:
    """``MX_MEXICO`` → ``country_filter_for`` returns ``"MX"`` so the
    Spanish collection only surfaces Mexican rates, not ES + AR rates."""
    assert country_filter_for(region) == expected


@pytest.mark.parametrize("bare", ["DE", "ES", "FR", "RU", "IT", "PT", "EN"])
def test_country_filter_skipped_for_bare_language_codes(bare: str) -> None:
    """A bare ISO-639 language input means "search the whole language
    collection" — no country payload pin so all regions sharing the
    language stay reachable."""
    assert country_filter_for(bare) is None


def test_country_filter_returns_none_for_empty() -> None:
    assert country_filter_for("") is None
    assert country_filter_for(None) is None
    assert country_filter_for("   ") is None


def test_country_filter_drops_pin_when_head_absent_from_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-US English projects fix: a region head the resolved collection
    doesn't actually carry must NOT be pinned, or every candidate is filtered
    out. ``CA_TORONTO`` → head ``"CA"``, but the English CWICR snapshot
    ``cwicr_en_v3`` holds only ``country="US"`` rows. The guard drops the pin
    so the whole collection is searched (best available rates) rather than
    returning an empty list - the user-reported "/match-elements returns
    nothing" for Canadian / UK / non-US English projects."""
    from app.modules.costs import qdrant_adapter as qa

    monkeypatch.setattr(qa, "_country_head_present", lambda _collection, _head: False)
    assert qa.country_filter_for("CA_TORONTO") is None
    assert qa.country_filter_for("GBR_LONDON") is None
    assert qa.country_filter_for("DE_BERLIN") is None


def test_country_filter_keeps_pin_when_head_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the resolved collection genuinely carries the region's country
    (e.g. ``MX`` rows inside ``cwicr_es_v3``), the pin is preserved so the
    search correctly narrows to that country - the data-driven guard never
    weakens a legitimate per-country catalogue."""
    from app.modules.costs import qdrant_adapter as qa

    monkeypatch.setattr(qa, "_country_head_present", lambda _collection, _head: True)
    assert qa.country_filter_for("MX_MEXICO") == "MX"
    assert qa.country_filter_for("USA_USD") == "US"
    assert qa.country_filter_for("ENG_TORONTO") == "CA"


def test_country_head_present_true_when_probe_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Probe-disabled escape hatch keeps the pure pinning contract and issues
    no network I/O - mirrors ``_available_cwicr_collections``."""
    from app.modules.costs import qdrant_adapter as qa

    # autouse fixture already sets CWICR_COLLECTION_PROBE=0; assert the
    # escape hatch returns True without touching Qdrant.
    monkeypatch.setenv("CWICR_COLLECTION_PROBE", "0")
    get_settings.cache_clear()
    assert qa._country_head_present("cwicr_en_v3", "CA") is True


# ── World cost bases 2026-07 wave: GR_NATIONAL headline (task #31) ────────
#
# Eight national/regional bases route transitively through
# ``region_language.language_for`` - the adapter keeps no per-region table of
# its own, so the extended parametrize lists above already lock the full
# region -> collection and region -> head contract. GR_NATIONAL earns its own
# guard because it is the only base that opens a brand-new language collection
# (Greek ``el`` -> ``cwicr_el_v3``): if the language table ever drops it,
# ``language_for`` falls back to English and Greek estimates silently search
# ``cwicr_en_v3`` with no error to signal the miss.


def test_greek_national_base_opens_the_new_el_collection() -> None:
    """``GR_NATIONAL`` must resolve to the brand-new ``cwicr_el_v3``."""
    assert country_to_collection("GR_NATIONAL") == "cwicr_el_v3"
    # Bare ``"GR"`` resolves the same way via the auto-built head map.
    assert country_to_collection("GR") == "cwicr_el_v3"
    # The head pin is the ISO-3166 alpha-2 code, no alias needed.
    assert country_filter_for("GR_NATIONAL") == "GR"


# ── _build_filter — 29 indexed payload fields per MAPPING_PROCESS.md §2.2 ──


def _conditions_by_key(qdrant_filter: object) -> dict[str, object]:
    """Flatten a built Filter into ``{payload_key: match}`` for assertion."""
    if qdrant_filter is None:
        return {}
    return {cond.key: cond.match for cond in qdrant_filter.must}


def test_build_filter_returns_none_for_empty_dict() -> None:
    assert _build_filter({}) is None
    # A non-empty dict (even of unknown keys) walks past the early return into
    # the qdrant_client import, so guard the optional [semantic] extra.
    pytest.importorskip("qdrant_client")
    assert _build_filter({"unknown_key": "ignored"}) is None


def test_build_filter_drops_none_values() -> None:
    """``None`` means "no preference", not "match null"."""
    # Non-empty dict reaches the qdrant_client import inside _build_filter.
    pytest.importorskip("qdrant_client")
    assert _build_filter({"ifc_class": None, "ost_category": None}) is None


@pytest.mark.parametrize(
    "bool_key",
    [
        "is_abstract",
        "is_external",
        "is_loadbearing",
        "is_structural",
        "is_machine",
        "is_material",
        "is_finishing",
        "is_temporary",
        "is_compound",
    ],
)
def test_build_filter_recognises_all_nine_boolean_payload_fields(bool_key: str) -> None:
    """Every Pset-derived boolean from §2.2 must produce a MatchValue(bool)."""
    # _build_filter constructs qdrant_client model objects, so this path needs
    # the optional [semantic] extra. Skip cleanly when it is absent.
    MatchValue = pytest.importorskip("qdrant_client.http.models").MatchValue

    qf = _build_filter({bool_key: True})
    by_key = _conditions_by_key(qf)
    assert by_key.keys() == {bool_key}
    assert by_key[bool_key] == MatchValue(value=True)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (True, True),
        (False, False),
        ("true", True),  # truthy string coerced
        ("false", True),  # non-empty string is truthy by Python rules
        (1, True),
        (0, False),
        (1.0, True),
        (0.0, False),
    ],
)
def test_build_filter_coerces_boolean_inputs_with_python_bool(raw: object, expected: bool) -> None:
    """Defensive coercion: stray "1" / 0.0 from JSON should not become a
    type-mismatched MatchValue that Qdrant silently rejects."""
    MatchValue = pytest.importorskip("qdrant_client.http.models").MatchValue

    qf = _build_filter({"is_abstract": raw})
    by_key = _conditions_by_key(qf)
    assert by_key["is_abstract"] == MatchValue(value=expected)


@pytest.mark.parametrize(
    ("scalar_key", "value"),
    [
        ("country", "DE"),
        ("ifc_class", "IfcWallStandardCase"),
        ("ifc_predefined_type", "STANDARD"),
        ("ost_category", "OST_Walls"),
        ("applies_to_ifc_classes", "IfcWall"),
        ("masterformat_division", "03"),
        ("csi_division_2", "03 30"),
        ("category_type", "structural"),
        ("collection_name", "DE-2024"),
        ("department_code", "330"),
        ("subsection_code", "330.10"),
        ("unit_type", "volume"),
        ("unit_dim", "m3"),
        ("rate_unit", "m3"),
        ("material_class", "concrete"),
        ("installation_method", "cast-in-place"),
        ("construction_stage", "structure"),
        ("uniformat_group", "B1010"),
        ("equipment_class", "crane"),
        ("classification_confidence", "high"),
        ("rate_code", "03.330.10"),
        ("nominal_size_mm", 240),
    ],
)
def test_build_filter_recognises_all_22_scalar_payload_fields(scalar_key: str, value: object) -> None:
    """All scalar fields from §2.2 must produce MatchValue(value) predicates."""
    MatchValue = pytest.importorskip("qdrant_client.http.models").MatchValue

    qf = _build_filter({scalar_key: value})
    by_key = _conditions_by_key(qf)
    assert by_key.keys() == {scalar_key}
    assert by_key[scalar_key] == MatchValue(value=value)


@pytest.mark.parametrize("collection_type", [list, tuple, set])
def test_build_filter_routes_collections_to_match_any(collection_type: type) -> None:
    """List/tuple/set values become OR-of-values via MatchAny — required
    for trade-bucket filters like ``department_code IN (330, 340)``."""
    MatchAny = pytest.importorskip("qdrant_client.http.models").MatchAny

    raw = collection_type(["330", "340", "350"])
    qf = _build_filter({"department_code": raw})
    by_key = _conditions_by_key(qf)
    match = by_key["department_code"]
    assert isinstance(match, MatchAny)
    assert sorted(match.any) == ["330", "340", "350"]


def test_build_filter_combines_boolean_and_scalar_predicates() -> None:
    """Realistic SearchPlan call — IfcWall + structural + concrete + cubic
    metres + DE country + non-abstract — must produce one Filter with all
    six predicates in ``must``."""
    # _build_filter builds qdrant_client Filter objects (optional [semantic]).
    pytest.importorskip("qdrant_client")
    qf = _build_filter(
        {
            "is_abstract": False,
            "is_structural": True,
            "ifc_class": "IfcWallStandardCase",
            "material_class": "concrete",
            "unit_dim": "m3",
            "country": "DE",
        }
    )
    by_key = _conditions_by_key(qf)
    assert set(by_key.keys()) == {
        "is_abstract",
        "is_structural",
        "ifc_class",
        "material_class",
        "unit_dim",
        "country",
    }


def test_build_filter_preserves_v3_field_count_invariant() -> None:
    """Regression guard: §2.2 lists 29 indexed payload fields. Adding or
    removing one without updating ``_BUILD_FILTER_KNOWN_KEYS`` here forces
    a code review of MAPPING_PROCESS.md."""
    # 9 booleans + 22 scalars = 31 total recognised keys.
    # (Two non-§2.2 keys — ``unit_dim`` legacy alias and ``rate_code``
    # operational lookup — are deliberately accepted in addition to the
    # 29 indexed ones documented in MAPPING_PROCESS.md.)
    expected_known = {
        # Booleans
        "is_abstract",
        "is_external",
        "is_loadbearing",
        "is_structural",
        "is_machine",
        "is_material",
        "is_finishing",
        "is_temporary",
        "is_compound",
        # Scalars / lists
        "country",
        "ifc_class",
        "ifc_predefined_type",
        "ost_category",
        "applies_to_ifc_classes",
        "masterformat_division",
        "csi_division_2",
        "category_type",
        "collection_name",
        "department_code",
        "subsection_code",
        "unit_type",
        "unit_dim",
        "rate_unit",
        "material_class",
        "installation_method",
        "construction_stage",
        "uniformat_group",
        "equipment_class",
        "classification_confidence",
        "rate_code",
        "nominal_size_mm",
    }
    # _build_filter builds qdrant_client Filter objects (optional [semantic]).
    pytest.importorskip("qdrant_client")
    payload = {key: (False if key.startswith("is_") else "x") for key in expected_known}
    qf = _build_filter(payload)
    assert set(_conditions_by_key(qf).keys()) == expected_known
    assert len(expected_known) == 31  # 9 booleans + 22 scalars


# ── v3-P7: Search hardening — unit aliases, dedup, relax tiers ───────────


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("m³", "m3"),
        ("м³", "m3"),
        ("M3", "m3"),  # case-insensitive
        ("cubic_meter", "m3"),
        ("m²", "m2"),
        ("square_metre", "m2"),
        ("kg", "kg"),
        ("кг", "kg"),
        ("KILOGRAM", "kg"),
        ("pcs", "pcs"),
        ("шт", "pcs"),
        ("PIECE", "pcs"),
        ("lsum", "lsum"),
        ("ls", "lsum"),
        ("lump_sum", "lsum"),
        ("t", "t"),
        ("TONNE", "t"),
    ],
)
def test_normalise_unit_dim_canonicalises_known_aliases(raw: str, canonical: str) -> None:
    assert _normalise_unit_dim(raw) == canonical


def test_normalise_unit_dim_preserves_unknown_values_lowercased() -> None:
    """Unknown vendor units pass through unchanged (lowercased) — we'd
    rather pin a vendor-specific filter than silently drop it."""
    assert _normalise_unit_dim("hour") == "hour"
    assert _normalise_unit_dim("HOUR") == "hour"
    assert _normalise_unit_dim("kw·h") == "kw·h"


def test_normalise_unit_dim_handles_empty_inputs() -> None:
    assert _normalise_unit_dim(None) is None
    assert _normalise_unit_dim("") is None
    assert _normalise_unit_dim("   ") is None


def test_dedup_hits_keeps_first_occurrence_per_rate_code() -> None:
    hits = [
        QdrantHit(rate_code="03.330.10", country="DE", score=0.9),
        QdrantHit(rate_code="03.330.20", country="DE", score=0.85),
        QdrantHit(rate_code="03.330.10", country="DE", score=0.6),  # dup
        QdrantHit(rate_code="03.330.30", country="DE", score=0.5),
    ]
    out = _dedup_hits(hits)
    assert [h.rate_code for h in out] == ["03.330.10", "03.330.20", "03.330.30"]
    # First occurrence wins so the highest score (0.9) is preserved
    assert out[0].score == 0.9


def test_dedup_hits_handles_empty_input() -> None:
    assert _dedup_hits([]) == []


def test_relax_tiers_progressively_widen_filter_relaxation() -> None:
    """Each successive tier must drop a strict superset of the previous —
    no relax tier should re-add a filter the prior tier dropped."""
    for prev, curr in zip(_RELAX_TIERS, _RELAX_TIERS[1:], strict=False):
        assert set(prev).issubset(set(curr))


def test_relax_tiers_starts_with_full_filter_set() -> None:
    """Tier 0 is the no-op baseline so callers always start with the
    full hard_filters from the SearchPlan."""
    assert _RELAX_TIERS[0] == ()


def test_relax_tiers_preserve_bedrock_filters() -> None:
    """Even at the most-relaxed tier, ``country``, ``ifc_class``, and
    ``is_abstract`` must NOT be in the drop list — those define the
    bedrock semantics of "this rate is in the right ballpark"."""
    bedrock = {"country", "ifc_class", "is_abstract"}
    most_relaxed = set(_RELAX_TIERS[-1])
    assert bedrock.isdisjoint(most_relaxed)


def test_filters_after_relax_drops_listed_keys() -> None:
    src = {
        "country": "DE",
        "ifc_class": "IfcWall",
        "ifc_predefined_type": "STANDARD",
        "construction_stage": "structure",
        "is_loadbearing": True,
    }
    out = _filters_after_relax(src, ("ifc_predefined_type", "construction_stage"))
    assert out == {"country": "DE", "ifc_class": "IfcWall", "is_loadbearing": True}
    # Original is not mutated — pure-function semantics
    assert "ifc_predefined_type" in src


def test_filters_after_relax_handles_none_input() -> None:
    assert _filters_after_relax(None, ("foo",)) == {}
    assert _filters_after_relax({}, ("foo",)) == {}


# ── v3-P7: search_with_fallback walking the relax ladder ──────────────────


@pytest.mark.asyncio
async def test_search_with_fallback_returns_tier_zero_when_full_filters_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: the full filter set already returns enough hits, so
    ``search_with_fallback`` stops at tier 0 and never relaxes."""
    calls: list[dict[str, object]] = []

    async def fake_search(*, country, core_query, resources_query=None, filters=None, limit=30, prefetch_limit=50):
        calls.append({"filters": filters, "limit": limit})
        return [QdrantHit(rate_code=f"R{i}", country="DE", score=0.9 - i * 0.01) for i in range(10)]

    monkeypatch.setattr("app.modules.costs.qdrant_adapter.search", fake_search)

    hits, tier = await search_with_fallback(
        country="DE_BERLIN",
        core_query="Stahlbetonwand",
        filters={"ifc_class": "IfcWall", "construction_stage": "structure"},
        limit=10,
    )
    assert tier == 0
    assert len(hits) == 10
    assert len(calls) == 1
    assert calls[0]["filters"] == {"ifc_class": "IfcWall", "construction_stage": "structure"}


@pytest.mark.asyncio
async def test_search_with_fallback_walks_until_threshold_satisfied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tier 0 returns nothing; tier 1 drops ifc_predefined_type and
    surfaces enough rows. Verify the second call's filters reflect the
    relax."""
    call_filters: list[dict | None] = []

    async def fake_search(*, country, core_query, resources_query=None, filters=None, limit=30, prefetch_limit=50):
        call_filters.append(dict(filters or {}))
        # Empty result until ifc_predefined_type is dropped
        if "ifc_predefined_type" in (filters or {}):
            return []
        return [QdrantHit(rate_code=f"R{i}", country="DE", score=0.9) for i in range(5)]

    monkeypatch.setattr("app.modules.costs.qdrant_adapter.search", fake_search)

    hits, tier = await search_with_fallback(
        country="DE_BERLIN",
        core_query="wand",
        filters={"ifc_class": "IfcWall", "ifc_predefined_type": "STANDARD"},
        limit=10,
        min_results=3,
    )
    assert tier == 1
    assert len(hits) == 5
    assert len(call_filters) == 2
    assert "ifc_predefined_type" in call_filters[0]
    assert "ifc_predefined_type" not in call_filters[1]
    assert call_filters[1]["ifc_class"] == "IfcWall"  # bedrock preserved


@pytest.mark.asyncio
async def test_search_with_fallback_returns_last_tier_when_all_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All tiers under-return → return the most-relaxed result and the
    final tier index so the caller knows we exhausted the ladder."""

    async def fake_search(**_: object) -> list[QdrantHit]:
        return []

    monkeypatch.setattr("app.modules.costs.qdrant_adapter.search", fake_search)

    hits, tier = await search_with_fallback(
        country="DE_BERLIN",
        core_query="impossible",
        filters={"ifc_class": "IfcWall"},
        limit=10,
    )
    assert hits == []
    assert tier == len(_RELAX_TIERS) - 1


@pytest.mark.asyncio
async def test_search_with_fallback_dedupes_results(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even when a single tier returns duplicates (e.g., dense + sparse
    surface the same rate via RRF degeneracy), the output is deduped."""

    async def fake_search(**_: object) -> list[QdrantHit]:
        return [
            QdrantHit(rate_code="A", country="DE", score=0.9),
            QdrantHit(rate_code="B", country="DE", score=0.85),
            QdrantHit(rate_code="A", country="DE", score=0.7),
            QdrantHit(rate_code="C", country="DE", score=0.6),
        ]

    monkeypatch.setattr("app.modules.costs.qdrant_adapter.search", fake_search)

    hits, _ = await search_with_fallback(country="DE_BERLIN", core_query="wall", limit=10)
    assert [h.rate_code for h in hits] == ["A", "B", "C"]


@pytest.mark.asyncio
async def test_substitute_abstract_parents_replaces_section_header_with_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Top hit is a DIN section header (is_abstract=True). The function
    issues a follow-up call filtered to the same subsection_code with
    is_abstract=False and splices the children at the header's rank."""
    children_calls: list[dict | None] = []

    async def fake_search(*, country, core_query, resources_query=None, filters=None, limit=30, prefetch_limit=50):
        children_calls.append(dict(filters or {}))
        return [
            QdrantHit(rate_code="03.330.10", country="DE", score=0.85),
            QdrantHit(rate_code="03.330.11", country="DE", score=0.80),
        ]

    monkeypatch.setattr("app.modules.costs.qdrant_adapter.search", fake_search)

    hits = [
        QdrantHit(
            rate_code="03.330",
            country="DE",
            score=0.92,
            payload={"is_abstract": True, "subsection_code": "330", "department_code": "3"},
        ),
        QdrantHit(rate_code="03.340.50", country="DE", score=0.6, payload={}),
    ]

    out = await substitute_abstract_parents(country="DE_BERLIN", core_query="wand", hits=hits)
    assert children_calls == [{"is_abstract": False, "subsection_code": "330"}]
    rate_codes = [h.rate_code for h in out]
    assert rate_codes == ["03.330.10", "03.330.11", "03.340.50"]


@pytest.mark.asyncio
async def test_substitute_abstract_parents_keeps_concrete_only_lists_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No abstract hits → no follow-up calls, return list verbatim."""
    calls: list[object] = []

    async def fake_search(**kw: object) -> list[QdrantHit]:
        calls.append(kw)
        return []

    monkeypatch.setattr("app.modules.costs.qdrant_adapter.search", fake_search)

    hits = [
        QdrantHit(rate_code="A", country="DE", score=0.9, payload={"is_abstract": False}),
        QdrantHit(rate_code="B", country="DE", score=0.8, payload={}),
    ]
    out = await substitute_abstract_parents(country="DE", core_query="x", hits=hits)
    assert out == hits
    assert calls == []


@pytest.mark.asyncio
async def test_substitute_abstract_parents_caps_substitutions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``max_substitutions=1`` budget: only the first abstract hit is
    expanded; the second abstract is left in place."""
    call_count = {"n": 0}

    async def fake_search(**_: object) -> list[QdrantHit]:
        call_count["n"] += 1
        return [QdrantHit(rate_code=f"child-{call_count['n']}", country="DE", score=0.7)]

    monkeypatch.setattr("app.modules.costs.qdrant_adapter.search", fake_search)

    hits = [
        QdrantHit(
            rate_code="parent-A",
            country="DE",
            score=0.95,
            payload={"is_abstract": True, "subsection_code": "330"},
        ),
        QdrantHit(
            rate_code="parent-B",
            country="DE",
            score=0.9,
            payload={"is_abstract": True, "subsection_code": "340"},
        ),
    ]
    out = await substitute_abstract_parents(country="DE", core_query="x", hits=hits, max_substitutions=1)
    assert call_count["n"] == 1
    rate_codes = [h.rate_code for h in out]
    # First abstract → expanded; second → left in place
    assert "child-1" in rate_codes
    assert "parent-B" in rate_codes


@pytest.mark.asyncio
async def test_substitute_abstract_parents_keeps_parent_when_no_trade_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Abstract hit without subsection_code or department_code can't be
    expanded — keep the parent in-place rather than dropping it."""
    calls: list[object] = []

    async def fake_search(**kw: object) -> list[QdrantHit]:
        calls.append(kw)
        return []

    monkeypatch.setattr("app.modules.costs.qdrant_adapter.search", fake_search)

    hits = [
        QdrantHit(rate_code="orphan", country="DE", score=0.9, payload={"is_abstract": True}),
    ]
    out = await substitute_abstract_parents(country="DE", core_query="x", hits=hits)
    assert [h.rate_code for h in out] == ["orphan"]
    assert calls == []  # never issued the follow-up


@pytest.mark.asyncio
async def test_substitute_abstract_parents_prefers_subsection_over_department(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When both codes are present, the more specific subsection is used."""
    calls: list[dict] = []

    async def fake_search(*, country, core_query, resources_query=None, filters=None, limit=30, prefetch_limit=50):
        calls.append(dict(filters or {}))
        return []

    monkeypatch.setattr("app.modules.costs.qdrant_adapter.search", fake_search)

    hits = [
        QdrantHit(
            rate_code="parent",
            country="DE",
            score=0.9,
            payload={"is_abstract": True, "subsection_code": "330", "department_code": "3"},
        ),
    ]
    await substitute_abstract_parents(country="DE", core_query="x", hits=hits)
    assert calls == [{"is_abstract": False, "subsection_code": "330"}]
    assert "department_code" not in calls[0]


# ── v3-P8: Cross-language identity via base_code() ───────────────────────


@pytest.mark.parametrize(
    ("rate_code", "expected"),
    [
        # Both lang + unit suffix
        ("03.330.10.de.m3", "03.330.10"),
        ("03.330.10.en.m3", "03.330.10"),
        ("03.330.10.ru.m3", "03.330.10"),
        # Order-agnostic: unit then lang
        ("03.330.10.m3.de", "03.330.10"),
        # Only language suffix
        ("03.330.10.de", "03.330.10"),
        ("01.45.de", "01.45"),
        # Only unit suffix
        ("03.330.10.m3", "03.330.10"),
        ("01.20.kg", "01.20"),
        ("01.30.lsum", "01.30"),
        # Bare prefix (no suffixes to strip)
        ("03.330.10", "03.330.10"),
        # Edge: top-level segment not a suffix sentinel
        ("03", "03"),
        # Numeric SINAPI codes — no suffixes, pass through
        ("87437", "87437"),
        ("123456", "123456"),
        # BYO vendor codes — pass through
        ("CUSTOM-XYZ", "CUSTOM-XYZ"),
        ("ABC.DEF", "ABC.DEF"),  # neither segment is a sentinel
        # Unknown trailing segments — preserved
        ("03.330.10.xx.yy", "03.330.10.xx.yy"),
        # Mixed-known / unknown: only the known sentinel is stripped
        ("03.330.10.foo.de", "03.330.10.foo"),
        # Defensive: case-insensitive lang/unit matching
        ("03.330.10.DE.M3", "03.330.10"),
        ("03.330.10.De.m3", "03.330.10"),
    ],
)
def test_base_code_strips_lang_and_unit_suffixes(rate_code: str, expected: str) -> None:
    assert base_code(rate_code) == expected


def test_base_code_handles_falsy_input() -> None:
    assert base_code("") == ""
    assert base_code(None) == ""


def test_base_code_does_not_truncate_two_dotted_codes_completely() -> None:
    """A bare ``de.m3`` (no structural prefix) should not be reduced to
    empty — the dot-split pop loop preserves at least one segment so
    catalogues that mistakenly use language-only codes are still
    distinguishable."""
    out = base_code("de.m3")
    assert out  # non-empty
    # Either preserved as-is, or stripped to the head — never empty
    assert out in ("de", "de.m3")


def test_dedup_hits_by_base_code_keeps_highest_score() -> None:
    """Same base across DE + EN collections — highest score wins."""
    hits = [
        QdrantHit(rate_code="03.330.10.de.m3", country="DE", score=0.92),
        QdrantHit(rate_code="03.330.10.en.m3", country="GB", score=0.88),
        QdrantHit(rate_code="03.340.10.de.m3", country="DE", score=0.80),
    ]
    out = _dedup_hits_by_base_code(hits)
    rate_codes = [h.rate_code for h in out]
    # Highest-scoring representative for base 03.330.10 is the DE row
    assert "03.330.10.de.m3" in rate_codes
    assert "03.330.10.en.m3" not in rate_codes
    assert "03.340.10.de.m3" in rate_codes
    assert len(out) == 2


def test_dedup_hits_by_base_code_preserves_input_order() -> None:
    """RRF order must be respected — we keep the highest-scoring
    representative but don't re-sort by score."""
    hits = [
        QdrantHit(rate_code="03.340.10.de.m3", country="DE", score=0.80),  # base A
        QdrantHit(rate_code="03.330.10.de.m3", country="DE", score=0.92),  # base B
        QdrantHit(rate_code="03.330.10.en.m3", country="GB", score=0.88),  # dup of B
    ]
    out = _dedup_hits_by_base_code(hits)
    rate_codes = [h.rate_code for h in out]
    # Base A appears first in input → first in output, even though base B
    # has the higher max score
    assert rate_codes == ["03.340.10.de.m3", "03.330.10.de.m3"]


def test_dedup_hits_by_base_code_handles_codes_without_suffixes() -> None:
    """SINAPI numeric codes have no language/unit suffix — they should
    each be their own bucket and pass through unchanged."""
    hits = [
        QdrantHit(rate_code="87437", country="BR", score=0.9),
        QdrantHit(rate_code="87438", country="BR", score=0.85),
        QdrantHit(rate_code="87437", country="BR", score=0.7),  # exact dup
    ]
    out = _dedup_hits_by_base_code(hits)
    assert [h.rate_code for h in out] == ["87437", "87438"]
    # First-occurrence wins on exact dups (same score-rank assumption)
    assert out[0].score == 0.9


def test_dedup_hits_by_base_code_handles_empty_input() -> None:
    assert _dedup_hits_by_base_code([]) == []


# ── v3-P8: cross_language_search fan-out ─────────────────────────────────


@pytest.mark.asyncio
async def test_cross_language_search_fans_out_to_all_collections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Primary + 2 additional countries → 3 search calls in parallel.

    Each fake hit uses the *language* suffix (de/en/ru) — not the
    country prefix — so ``base_code`` correctly recognises the rates
    as the same logical item across language collections."""
    call_countries: list[str] = []
    # Map test country → language suffix to use in the fake rate code
    lang_for = {"DE_BERLIN": "de", "GB_LONDON": "en", "RU_MOSCOW": "ru"}

    async def fake_search(*, country, **_: object):
        call_countries.append(country)
        return [
            QdrantHit(
                rate_code=f"03.330.10.{lang_for[country]}.m3",
                country=country,
                score=0.9,
            ),
        ]

    monkeypatch.setattr("app.modules.costs.qdrant_adapter.search", fake_search)

    out = await cross_language_search(
        primary_country="DE_BERLIN",
        additional_countries=["GB_LONDON", "RU_MOSCOW"],
        core_query="wand",
    )
    assert sorted(call_countries) == sorted(["DE_BERLIN", "GB_LONDON", "RU_MOSCOW"])
    # 3 hits with the same base_code → deduped to 1
    assert len(out) == 1


@pytest.mark.asyncio
async def test_cross_language_search_dedups_same_base_across_languages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DE + EN return the same logical rate; dedup keeps highest score."""

    async def fake_search(*, country, **_: object):
        if country.startswith("DE"):
            return [QdrantHit(rate_code="03.330.10.de.m3", country="DE", score=0.92)]
        return [QdrantHit(rate_code="03.330.10.en.m3", country="GB", score=0.88)]

    monkeypatch.setattr("app.modules.costs.qdrant_adapter.search", fake_search)

    out = await cross_language_search(
        primary_country="DE_BERLIN",
        additional_countries=["GB_LONDON"],
        core_query="wall",
    )
    assert len(out) == 1
    # DE wins on score
    assert out[0].rate_code == "03.330.10.de.m3"


@pytest.mark.asyncio
async def test_cross_language_search_dedupes_country_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caller mistakenly passes the primary in additional_countries —
    only one search per language collection should fire."""
    call_count = {"n": 0}

    async def fake_search(**_: object):
        call_count["n"] += 1
        return [QdrantHit(rate_code="X", country="DE", score=0.9)]

    monkeypatch.setattr("app.modules.costs.qdrant_adapter.search", fake_search)

    await cross_language_search(
        primary_country="DE_BERLIN",
        # AT_VIENNA + CH_ZURICH all map to cwicr_de_v3, same as DE_BERLIN
        additional_countries=["DE_MUNICH", "AT_VIENNA", "CH_ZURICH"],
        core_query="x",
    )
    # All 4 inputs share the same collection — one call only
    assert call_count["n"] == 1


@pytest.mark.asyncio
async def test_cross_language_search_swallows_per_collection_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If one collection's search raises, the others' results are still
    returned — partial success is better than total failure."""

    async def fake_search(*, country, **_: object):
        if country == "RU_MOSCOW":
            raise RuntimeError("Qdrant down")
        return [QdrantHit(rate_code=f"R-{country}", country=country, score=0.9)]

    monkeypatch.setattr("app.modules.costs.qdrant_adapter.search", fake_search)

    out = await cross_language_search(
        primary_country="DE_BERLIN",
        additional_countries=["GB_LONDON", "RU_MOSCOW"],
        core_query="x",
    )
    rate_codes = [h.rate_code for h in out]
    assert "R-DE_BERLIN" in rate_codes
    assert "R-GB_LONDON" in rate_codes
    # RU collection's failure is swallowed
    assert not any("RU" in c for c in rate_codes)


@pytest.mark.asyncio
async def test_cross_language_search_returns_empty_for_empty_country_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty primary_country + empty additional → no search calls."""
    call_count = {"n": 0}

    async def fake_search(**_: object):
        call_count["n"] += 1
        return []

    monkeypatch.setattr("app.modules.costs.qdrant_adapter.search", fake_search)

    out = await cross_language_search(
        primary_country="",
        additional_countries=[],
        core_query="x",
    )
    assert out == []
    assert call_count["n"] == 0


@pytest.mark.asyncio
async def test_cross_language_search_caps_output_at_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each collection returns 5 hits; with limit=3 the merged output
    is truncated to 3 after dedup."""

    async def fake_search(*, country, **_: object):
        return [QdrantHit(rate_code=f"R-{country}-{i}", country=country, score=0.9 - i * 0.05) for i in range(5)]

    monkeypatch.setattr("app.modules.costs.qdrant_adapter.search", fake_search)

    out = await cross_language_search(
        primary_country="DE_BERLIN",
        additional_countries=["GB_LONDON"],
        core_query="x",
        limit=3,
    )
    assert len(out) == 3


# ── cross_lang_lookup — §6.2 "точный подход" ──────────────────────────────


def test_enumerate_target_codes_emits_bare_lang_unit_and_combos() -> None:
    """For a clean base + target language, the enumeration must include
    (a) the bare base, (b) base + lang, (c) base + every canonical unit,
    (d) base + lang + unit, (e) base + unit + lang."""
    out = _enumerate_target_codes("03.330.10", "DE_BERLIN")
    # Always include the bare base and the lang-only suffix.
    assert "03.330.10" in out
    assert "03.330.10.de" in out
    # At least one canonical unit appears in all three combos.
    assert "03.330.10.m3" in out
    assert "03.330.10.de.m3" in out
    assert "03.330.10.m3.de" in out
    # Cardinality is bounded — never let it explode unboundedly.
    assert len(out) <= 32


def test_enumerate_target_codes_handles_empty_language_gracefully() -> None:
    """When the target country can't be mapped to a language, the helper
    still returns at minimum the bare base + per-unit suffixes — the
    Qdrant scroll then falls back to a unit-only match."""
    out = _enumerate_target_codes("03.330.10", "")
    assert "03.330.10" in out
    # No `.lang` segments when language_for() returns "".
    assert "03.330.10." not in [v.rstrip(".") for v in out]
    assert "03.330.10.m3" in out


class _FakeScrollPoint:
    """Minimal stand-in for qdrant_client's PointStruct response — only
    the ``payload`` attribute is read by :func:`cross_lang_lookup`."""

    def __init__(self, rate_code: str) -> None:
        self.payload = {"rate_code": rate_code}


class _FakeQdrantClient:
    """Records the single ``scroll`` call and replays a canned response."""

    def __init__(self, response: list[_FakeScrollPoint]) -> None:
        self._response = response
        self.calls: list[dict[str, object]] = []

    def scroll(self, **kwargs: object) -> tuple[list[_FakeScrollPoint], object]:
        self.calls.append(kwargs)
        return self._response, None


@pytest.mark.asyncio
async def test_cross_lang_lookup_returns_target_lang_rate_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EN code → RU code translation: base_code strips the EN+unit
    suffix, scroll on cwicr_ru_v3 finds the matching RU variant."""
    # cross_lang_lookup builds a qdrant_client Filter before calling scroll, so
    # the happy path needs the optional [semantic] extra. (The None-returning
    # tests below pass regardless, since a missing dep just yields None too.)
    pytest.importorskip("qdrant_client")
    fake = _FakeQdrantClient([_FakeScrollPoint("03.330.10.ru.m3")])
    monkeypatch.setattr(
        "app.modules.costs.qdrant_adapter._get_client",
        lambda: fake,
    )

    out = await cross_lang_lookup(
        source_rate_code="03.330.10.en.m3",
        target_country="RU_MOSCOW",
    )
    assert out == "03.330.10.ru.m3"
    # One scroll call against the RU collection.
    assert len(fake.calls) == 1
    assert fake.calls[0]["collection_name"] == "cwicr_ru_v3"
    assert fake.calls[0]["limit"] == 1


@pytest.mark.asyncio
async def test_cross_lang_lookup_returns_none_when_no_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty scroll response → None (caller can fall back to semantic)."""
    fake = _FakeQdrantClient([])
    monkeypatch.setattr(
        "app.modules.costs.qdrant_adapter._get_client",
        lambda: fake,
    )

    out = await cross_lang_lookup(
        source_rate_code="03.330.10.en.m3",
        target_country="DE_BERLIN",
    )
    assert out is None


@pytest.mark.asyncio
async def test_cross_lang_lookup_handles_qdrant_failure_gracefully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Qdrant connection error → None, no exception leaks to caller."""

    class _Boom:
        def scroll(self, **_: object):
            raise RuntimeError("Qdrant unreachable")

    monkeypatch.setattr(
        "app.modules.costs.qdrant_adapter._get_client",
        lambda: _Boom(),
    )

    out = await cross_lang_lookup(
        source_rate_code="03.330.10.en.m3",
        target_country="RU_MOSCOW",
    )
    assert out is None


@pytest.mark.asyncio
async def test_cross_lang_lookup_returns_none_on_empty_inputs() -> None:
    """Empty source code or target country → None without any I/O."""
    assert await cross_lang_lookup(source_rate_code="", target_country="RU") is None
    assert await cross_lang_lookup(source_rate_code="03.330.10.en.m3", target_country="") is None


@pytest.mark.asyncio
async def test_cross_lang_lookup_pins_country_for_multi_region_languages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ES collection mixes ES + MX + AR rates — when caller targets
    MX_MEXICO the scroll filter must include a country=MX predicate so
    the Mexican variant is returned, not a Spanish one."""
    # cross_lang_lookup builds a qdrant_client Filter before calling scroll.
    pytest.importorskip("qdrant_client")
    fake = _FakeQdrantClient([_FakeScrollPoint("03.330.10.es.m3")])
    monkeypatch.setattr(
        "app.modules.costs.qdrant_adapter._get_client",
        lambda: fake,
    )

    await cross_lang_lookup(
        source_rate_code="03.330.10.en.m3",
        target_country="MX_MEXICO",
    )
    # Inspect the Filter passed to scroll — it must contain MatchValue("MX")
    # on the ``country`` field. We only assert the filter has > 1 must clause
    # since the precise structure is qdrant_client's concern.
    scroll_filter = fake.calls[0]["scroll_filter"]
    must = list(getattr(scroll_filter, "must", []) or [])
    assert len(must) >= 2, "expected rate_code + country predicates"
    country_keys = [getattr(c, "key", None) for c in must]
    assert "country" in country_keys


# ── _collection_vectors capability cache ────────────────────────────────


class _FakeVectorsParams:
    """Stand-in for qdrant_client's CollectionInfo.config.params."""

    def __init__(self, vectors=None, sparse_vectors=None):
        self.vectors = vectors
        self.sparse_vectors = sparse_vectors


class _FakeCollectionInfo:
    def __init__(self, vectors=None, sparse_vectors=None):
        self.config = type("Cfg", (), {})()
        self.config.params = _FakeVectorsParams(vectors=vectors, sparse_vectors=sparse_vectors)


class _CapClient:
    """Records get_collection calls and returns canned CollectionInfo."""

    def __init__(self, info=None, raises=False):
        self._info = info
        self._raises = raises
        self.calls: list[str] = []

    def get_collection(self, name):
        self.calls.append(name)
        if self._raises:
            raise RuntimeError("collection missing")
        return self._info


@pytest.fixture(autouse=True)
def _clear_capability_cache():
    """Clear the per-collection capability cache between tests."""
    _collection_vectors_cache.clear()
    yield
    _collection_vectors_cache.clear()


def test_collection_vectors_returns_dense_sparse_for_v3_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DDC v3 snapshot exposes ``dense`` + ``sparse`` only — no ``resources``."""
    info = _FakeCollectionInfo(
        vectors={"dense": object()},
        sparse_vectors={"sparse": object()},
    )
    client = _CapClient(info=info)
    monkeypatch.setattr(
        "app.modules.costs.qdrant_adapter._get_client",
        lambda: client,
    )

    out = _collection_vectors("cwicr_en_v3")
    assert out == frozenset({"dense", "sparse"})
    assert "resources" not in out


def test_collection_vectors_includes_resources_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Locally-built catalogue carries dense + sparse + resources."""
    info = _FakeCollectionInfo(
        vectors={"dense": object(), "resources": object()},
        sparse_vectors={"sparse": object()},
    )
    client = _CapClient(info=info)
    monkeypatch.setattr(
        "app.modules.costs.qdrant_adapter._get_client",
        lambda: client,
    )

    out = _collection_vectors("cwicr_de_v3")
    assert out == frozenset({"dense", "sparse", "resources"})


def test_collection_vectors_caches_per_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Capability probe must hit Qdrant at most once per collection per boot."""
    info = _FakeCollectionInfo(vectors={"dense": object()}, sparse_vectors={"sparse": object()})
    client = _CapClient(info=info)
    monkeypatch.setattr(
        "app.modules.costs.qdrant_adapter._get_client",
        lambda: client,
    )

    _collection_vectors("cwicr_en_v3")
    _collection_vectors("cwicr_en_v3")
    _collection_vectors("cwicr_en_v3")
    # Three calls, one round-trip
    assert client.calls == ["cwicr_en_v3"]


def test_collection_vectors_returns_empty_on_qdrant_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unreachable Qdrant / missing collection → empty frozenset (no raise)."""
    client = _CapClient(raises=True)
    monkeypatch.setattr(
        "app.modules.costs.qdrant_adapter._get_client",
        lambda: client,
    )

    out = _collection_vectors("cwicr_xx_v9")
    assert out == frozenset()


# ── Collection availability-probe fallback (the /match "nothing happens" fix) ─
#
# When CWICR_COLLECTION_PROBE is on (production default) and a project's
# native-language collection is absent from a sparsely-populated Qdrant,
# country_to_collection substitutes the best present collection so the
# multilingual BGE-M3 encoder still returns real candidates instead of a
# dead collection name → empty result. These tests pin that contract AND
# the pure-routing escape hatch the autouse fixture relies on.


@pytest.fixture
def _enable_probe(monkeypatch: pytest.MonkeyPatch):
    """Re-enable the live-Qdrant availability probe for fallback tests.

    The module-level autouse ``_clear_settings_cache`` pins
    ``CWICR_COLLECTION_PROBE=0`` (pure routing); these tests opt back in.
    The ``_available_cwicr_cache`` is cleared so a stale entry from an
    earlier test can't leak the wrong collection set.
    """
    import app.modules.costs.qdrant_adapter as qa

    monkeypatch.setenv("CWICR_COLLECTION_PROBE", "1")
    get_settings.cache_clear()
    qa._available_cwicr_cache = None
    yield
    qa._available_cwicr_cache = None
    get_settings.cache_clear()


def test_probe_disabled_keeps_routing_pure(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the probe off the naive language name is returned verbatim —
    even if a live Qdrant would have only ``cwicr_en_v3``. This is the
    determinism / test-isolation guarantee the autouse fixture leans on."""

    def _boom():  # pragma: no cover — must never be called
        raise AssertionError("availability probe ran despite CWICR_COLLECTION_PROBE=0")

    # autouse fixture already set CWICR_COLLECTION_PROBE=0; assert no I/O.
    monkeypatch.setattr("app.modules.costs.qdrant_adapter._get_client", _boom)
    assert country_to_collection("DE_BERLIN") == "cwicr_de_v3"
    assert country_to_collection("RU_MOSCOW") == "cwicr_ru_v3"


@pytest.mark.usefixtures("_enable_probe")
def test_probe_falls_back_to_english_when_native_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``DE_BERLIN`` → ``cwicr_en_v3`` when only English is ingested."""
    monkeypatch.setattr(
        "app.modules.costs.qdrant_adapter._available_cwicr_collections",
        lambda: frozenset({"cwicr_en_v3", "cwicr_mn_v3"}),
    )
    assert country_to_collection("DE_BERLIN") == "cwicr_en_v3"
    assert country_to_collection("RU_MOSCOW") == "cwicr_en_v3"
    # Present collection is still routed to itself, not the fallback.
    assert country_to_collection("USA_USD") == "cwicr_en_v3"


@pytest.mark.usefixtures("_enable_probe")
def test_probe_unreachable_preserves_naive_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Qdrant down → empty set → naive language name unchanged (the
    historical down-state UI must keep firing, not silently re-route)."""
    monkeypatch.setattr(
        "app.modules.costs.qdrant_adapter._available_cwicr_collections",
        lambda: frozenset(),
    )
    assert country_to_collection("DE_BERLIN") == "cwicr_de_v3"


@pytest.mark.usefixtures("_enable_probe")
def test_country_filter_unpinned_when_language_fallback_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a cross-language fallback substituted ``cwicr_en_v3`` for a
    German project, ``country_filter_for`` must NOT pin ``"DE"`` — the
    English collection holds ``country="US"`` rows, so the pin would
    eliminate every candidate (the exact /match-elements regression)."""
    monkeypatch.setattr(
        "app.modules.costs.qdrant_adapter._available_cwicr_collections",
        lambda: frozenset({"cwicr_en_v3"}),
    )
    # Fallback active (de→en) ⇒ no country pin.
    assert country_filter_for("DE_BERLIN") is None
    # Native English region still pins normally (US head present).
    assert country_filter_for("USA_USD") == "US"
