# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Regression tests pinning the v3 universality sweep behaviour.

Each finding from the 2026-05-09 audit gets one test below — the goal
is to catch any future regression that re-introduces the hardcoded /
project-specific behaviour the sweep just removed.

Findings tracked here:

* #2  — region prefix table auto-derived from REGION_LANGUAGE so new
        countries never need a manual ``boosts/region.py`` edit.
* #15 — CJK / Hangul / Thai tokens of length 1 survive the lexical
        ``_meaningful_tokens`` gate (Latin/Cyrillic still need ≥3).
* #1  — currency rollup no longer hardcodes "EUR" when ``cost_item.currency``
        is empty; the empty string propagates so the rollup picks the
        dominant currency from siblings.
"""

from __future__ import annotations

import pytest

from app.core.match_service.boosts.region import (
    _AUTO_COUNTRY_PREFIXES,
    _REGION_GROUP_ALIASES,
    _project_region_prefixes,
)

# NOTE: ``matchers.lexical`` was removed in v3 — sparse matching now
# happens inside the Qdrant ranker via the BAAI/bge-m3 sparse vector. The
# CJK-aware token gate tests that lived here covered that module's
# helpers and have been removed alongside it. New CJK-token regressions
# should target ``ranker_qdrant``'s query-builder layer instead.


# ── #2: region prefix auto-derivation ────────────────────────────────────


@pytest.mark.parametrize(
    ("region_input", "must_resolve_to_prefix"),
    [
        # Single-country regions that the *old* hand-curated table missed.
        # Each of these has a row in REGION_LANGUAGE; the auto-derivation
        # must surface them without a manual map edit.
        ("HR", ("HR_",)),  # Croatia — Zagreb
        ("HR_ZAGREB", ("HR_ZAGREB",)),  # full COUNTRY_CITY pin
        ("IE", ("IE_",)),  # Ireland — Dublin
        ("SV", ("SV_",)),  # Sweden — Stockholm  (REGION_LANGUAGE uses SV)
        ("LT", ("LT_",)),  # Lithuania — Vilnius
        ("ID", ("ID_",)),  # Indonesia — Jakarta
        ("TH", ("TH_",)),  # Thailand — Bangkok
        ("VN", ("VN_",)),  # Vietnam — Hanoi
        ("KR", ("KR_",)),  # Korea — Seoul
        ("SA", ("SA_",)),  # Saudi Arabia
        ("HI", ("HI_",)),  # India / Hindi catalogue prefix
        ("NG", ("NG_",)),  # Nigeria — Lagos
    ],
)
def test_region_prefix_derived_from_REGION_LANGUAGE(region_input, must_resolve_to_prefix):
    """No manual table edit needed — every country in REGION_LANGUAGE is reachable."""

    class _Settings:
        class project:
            region = region_input

    prefixes = _project_region_prefixes(_Settings())
    assert prefixes == must_resolve_to_prefix, (
        f"region {region_input!r}: got {prefixes!r}, expected {must_resolve_to_prefix!r}"
    )


def test_region_group_aliases_still_win():
    """Macro-region aliases (DACH, UK, Iberia, …) take precedence over single-country."""

    class _Settings:
        class project:
            region = "DACH"

    prefixes = _project_region_prefixes(_Settings())
    assert prefixes == ("DE_", "AT_", "CH_")


def test_new_aliases_iberia_scandinavia_gulf_latam():
    """Group aliases added during the sweep — not mere allowlist sugar."""
    for alias, expected_first in [
        ("iberia", "ES_"),
        ("scandinavia", "SE_"),
        ("gulf", "AE_"),
        ("latam", "MX_"),
        ("benelux", "NL_"),
    ]:

        class _Settings:
            class project:
                pass

        _Settings.project.region = alias  # type: ignore[attr-defined]
        prefixes = _project_region_prefixes(_Settings())
        assert prefixes, f"{alias!r} resolved to empty"
        assert expected_first in prefixes, f"{alias!r} should include {expected_first!r}, got {prefixes!r}"


def test_auto_table_covers_REGION_LANGUAGE_completely():
    """No country in REGION_LANGUAGE may be missing from the auto table.

    A regression here would mean adding a new country to
    region_language.py would silently leave it without a region boost
    until someone remembers to also patch boosts/region.py.
    """
    from app.core.match_service.region_language import REGION_LANGUAGE

    heads = {k.split("_", 1)[0].lower() for k in REGION_LANGUAGE}
    missing = heads - set(_AUTO_COUNTRY_PREFIXES.keys())
    assert not missing, f"REGION_LANGUAGE heads missing from auto-prefix table: {missing}"


def test_region_group_aliases_are_uppercase_prefixes():
    """Sanity: every alias prefix ends with ``_`` so startswith works."""
    for name, prefixes in _REGION_GROUP_ALIASES.items():
        for p in prefixes:
            assert p.endswith("_"), f"alias {name!r} prefix {p!r} missing trailing underscore"
            assert p == p.upper(), f"alias {name!r} prefix {p!r} must be uppercase"


# ── #15: CJK-aware token length ──────────────────────────────────────────
# These tests covered ``app.modules.match_elements.matchers.lexical``
# which was removed in v3. Sparse / CJK-friendly matching now happens
# inside the Qdrant ranker's BAAI/bge-m3 sparse vector. CJK-token
# regression coverage migrated to ``ranker_qdrant`` test targets.


# ── #6: material bucket coverage across scripts ───────────────────────────


@pytest.mark.parametrize(
    ("text", "expected_bucket"),
    [
        # Concrete in 14 scripts/languages
        ("Concrete C30/37", "concrete"),
        ("Beton C30/37", "concrete"),
        ("Béton C30/37", "concrete"),
        ("Calcestruzzo armato", "concrete"),
        ("Hormigón C25/30", "concrete"),
        ("Concreto armado", "concrete"),
        ("Бетон C30/37", "concrete"),
        ("混凝土 C30/37", "concrete"),
        ("钢筋混凝土", "concrete"),
        ("コンクリート", "concrete"),
        ("鉄筋コンクリート", "concrete"),
        ("콘크리트 C30", "concrete"),
        ("خرسانة مسلحة", "concrete"),
        ("कंक्रीट", "concrete"),
        # Steel
        ("Steel S235", "steel"),
        ("Stahl S355", "steel"),
        ("Acero corrugado", "steel"),
        ("Сталь S235", "steel"),
        ("钢筋", "steel"),
        ("鉄筋", "steel"),
        ("강철 철근", "steel"),
        ("فولاذ", "steel"),
        ("Grade 60 rebar", "steel"),
        ("Fe500 reinforcement", "steel"),
        ("CA-50 vergalhão", "steel"),
        ("HRB400", "steel"),
        # Wood
        ("Timber beam", "wood"),
        ("Holzbalken", "wood"),
        ("Madera", "wood"),
        ("木材", "wood"),
        ("木造", "wood"),
        ("목재", "wood"),
        ("लकड़ी", "wood"),  # Hindi (Devanagari)
        # Glass
        ("Glass curtain wall", "glass"),
        ("玻璃幕墙", "glass"),
        ("ガラス", "glass"),
        ("유리", "glass"),
        ("زجاج", "glass"),
        # Aluminum
        ("Aluminum frame", "aluminum"),
        ("铝合金", "aluminum"),
        ("アルミニウム", "aluminum"),
        ("알루미늄", "aluminum"),
    ],
)
def test_material_bucket_resolves_across_scripts(text: str, expected_bucket: str) -> None:
    """Material bucket detection must work for any CWICR catalogue language."""
    from app.modules.match_elements.service import _normalise_material_class

    bucket = _normalise_material_class(text)
    assert bucket == expected_bucket, f"{text!r} → {bucket!r}, expected {expected_bucket!r}"


def test_material_bucket_returns_none_for_ambiguous():
    """Generic descriptions should NOT force a bucket — soft-boost only fires on clear signal."""
    from app.modules.match_elements.service import _normalise_material_class

    assert _normalise_material_class("Generic 200mm element") is None
    assert _normalise_material_class("") is None
    assert _normalise_material_class(None) is None


def test_material_bucket_does_not_trip_on_short_word_in_other_script():
    """Latin-only short words shouldn't accidentally pattern-match a CJK bucket marker."""
    from app.modules.match_elements.service import _normalise_material_class

    # "WC" is bathroom code, not concrete — make sure no bucket fires.
    assert _normalise_material_class("WC fixture") is None


# ── #5: classifier_hint emits MasterFormat + NRM, not only DIN 276 ───────


def test_ifc_class_carries_masterformat_and_nrm_hints():
    """Every safe-to-crosswalk IFC class must emit all three standards."""
    from app.modules.match_elements.ifc_labels import lookup

    # Walls — DACH, US, UK all expect a hint.
    wall = lookup("IfcWall")
    assert wall.din276_hint == "330"
    assert wall.masterformat_hint == "04 21 00"
    assert wall.nrm_hint == "2.5"

    # Slabs — concrete cast-in-place is 03 30 00 in CSI.
    slab = lookup("IfcSlab")
    assert slab.din276_hint == "350"
    assert slab.masterformat_hint == "03 30 00"
    assert slab.nrm_hint == "2.4"

    # Beams — structural concrete or steel.
    beam = lookup("IfcBeam")
    assert beam.din276_hint == "320"
    assert beam.masterformat_hint == "03 41 00"
    assert beam.nrm_hint == "2.5.1"

    # Doors and windows live in the same DIN bucket but split in CSI.
    door = lookup("IfcDoor")
    window = lookup("IfcWindow")
    assert door.masterformat_hint != window.masterformat_hint
    assert door.masterformat_hint.startswith("08")
    assert window.masterformat_hint.startswith("08")


def test_unknown_ifc_class_emits_no_hints():
    """A made-up IFC class falls back to bare label without hints."""
    from app.modules.match_elements.ifc_labels import lookup

    fake = lookup("IfcUnobtanium")
    assert fake.din276_hint is None
    assert fake.masterformat_hint is None
    assert fake.nrm_hint is None


def test_classifier_hint_dict_includes_all_present_standards():
    """The envelope's classifier_hint must surface every standard that
    has a non-empty hint, not just DIN 276 — that's what makes a US
    project narrow on MasterFormat correctly without losing the DIN
    fallback for a DACH catalogue.
    """
    from app.modules.match_elements.ifc_labels import lookup

    wall = lookup("IfcWall")
    parts: dict[str, str] = {}
    if wall.din276_hint:
        parts["din276"] = wall.din276_hint
    if wall.masterformat_hint:
        parts["masterformat"] = wall.masterformat_hint
    if wall.nrm_hint:
        parts["nrm"] = wall.nrm_hint
    assert set(parts.keys()) == {"din276", "masterformat", "nrm"}


# ── #4: classification preferred-order is region-aware ───────────────────


@pytest.mark.parametrize(
    ("region", "expected_head"),
    [
        ("DACH", "din276"),
        ("DE", "din276"),
        ("AT", "din276"),
        ("CH", "din276"),
        ("EU", "din276"),
        ("UK", "nrm"),
        ("GB", "nrm"),
        ("IE", "nrm"),
        ("US", "masterformat"),
        ("USA", "masterformat"),
        ("CA", "masterformat"),
        ("LATAM", "masterformat"),
        ("BR", "masterformat"),
        ("MX", "masterformat"),
        ("ES", "bc3"),  # Spain — native BC3 standard
        ("PT", "masterformat"),
        ("ASIA_PAC", "masterformat"),
        # ── CIS — GESN family via Russia anchor ─────────────────────
        ("RU", "gesn"),
        ("RU_STPETERSBURG", "gesn"),
        ("RU_MOSCOW", "gesn"),
        ("UA", "gesn"),
        ("BY", "gesn"),
        ("KZ", "gesn"),
        # ── Asia-Pacific single countries — native standards ────────
        ("JP", "sekisan"),
        ("CN", "gb50500"),
        ("KR", "kbim"),
        ("IN", "nrm"),  # India — RICS heritage
        ("HI", "nrm"),  # India Hindi region — same default
        ("HK", "nrm"),  # ex-British, RICS heritage
        ("SG", "nrm"),  # ex-British, RICS heritage
        ("MY", "nrm"),  # ex-British, RICS heritage
        ("AU", "nrm"),  # Australia — AIQS RICS-aligned
        ("NZ", "nrm"),  # New Zealand — NZIQS
        # ── Gulf English-language tendering ─────────────────────────
        ("AE", "masterformat"),
        ("SA", "masterformat"),
        ("QA", "masterformat"),
        ("GULF", "masterformat"),
        # ── Romance — native standards ──────────────────────────────
        ("FR", "untec"),  # France — UNTEC
        ("IT", "voci"),  # Italy — VOCI
        ("NL", "din276"),  # Benelux clusters to DACH/DIN-276
        ("BE", "din276"),
        ("BENELUX", "din276"),
        # ── Latin America extras ────────────────────────────────────
        ("AR", "masterformat"),
        ("CL", "masterformat"),
        ("CO", "masterformat"),
        ("PE", "masterformat"),
        # ── Eastern Europe (din276 fallback hierarchy) ──────────────
        ("PL", "din276"),
        ("CZ", "din276"),
        ("BG", "din276"),
        ("RO", "din276"),
        ("HR", "din276"),
        # ── Nordic ──────────────────────────────────────────────────
        ("SE", "din276"),
        ("NO", "din276"),
        ("DK", "din276"),
        ("FI", "din276"),
        ("NORDIC", "din276"),
        # ── Africa ──────────────────────────────────────────────────
        ("EG", "masterformat"),
        ("MA", "din276"),
        ("ZA", "nrm"),
        ("NG", "nrm"),
        ("KE", "nrm"),
        # ── Türkiye — native Birim Fiyat ────────────────────────────
        ("TR", "birimfiyat"),
    ],
)
def test_classification_order_prefers_region_native_standard(region, expected_head):
    """Region drives the section-path standard when no explicit choice."""
    from app.modules.match_elements.service import _resolve_classification_order

    order = _resolve_classification_order(None, region)
    assert order[0] == expected_head, f"region {region!r}: expected {expected_head!r} first, got {order!r}"


def test_classification_order_explicit_choice_beats_region():
    """An explicit project.classification_standard always wins."""
    from app.modules.match_elements.service import _resolve_classification_order

    # US project explicitly set to NRM (rare but legal — e.g. a UK firm
    # working on a US project keeps their own template).
    assert _resolve_classification_order("nrm", "US")[0] == "nrm"
    # DACH project explicitly set to MasterFormat (uncommon but supported).
    assert _resolve_classification_order("masterformat", "DACH")[0] == "masterformat"


def test_classification_order_unknown_region_falls_back_to_din276():
    """An exotic region we haven't mapped still gets a non-empty result.

    The resolver's terminal fallback is DIN-276 (line 450 in
    ``_resolve_classification_order``) — the heuristic in
    ``_COUNTRY_TO_STANDARD`` may say masterformat for countries we
    haven't bridged via the macro map, but the safety net for completely
    unknown region codes is still DIN-276.
    """
    from app.modules.match_elements.service import _resolve_classification_order

    order = _resolve_classification_order(None, "ZZ_FAKE_REGION")
    assert order[0] == "din276"
    # Tail must still include the three legacy giants so a catalogue
    # encoded against any of them produces a valid section path.
    assert {"din276", "masterformat", "nrm"}.issubset(set(order))


def test_classification_order_empty_inputs_safe():
    """Defensive: None/empty don't crash."""
    from app.modules.match_elements.service import _resolve_classification_order

    assert _resolve_classification_order(None, None)[0] == "din276"
    assert _resolve_classification_order("", "")[0] == "din276"


def test_classification_order_unknown_explicit_falls_through_to_region():
    """When the explicit standard isn't one we render, region wins."""
    from app.modules.match_elements.service import _resolve_classification_order

    # "uniformat" is a real CSI standard but we don't render it yet —
    # so the helper falls back to the region's preferred standard.
    order = _resolve_classification_order("uniformat", "US")
    assert order[0] == "masterformat"
    order = _resolve_classification_order("omniclass", "UK")
    assert order[0] == "nrm"


# ── #8: rare-token boost recognises non-EU steel/rebar/concrete ──────────
# NOTE: the ``rare_token`` boost was removed in v3 — the BAAI/bge-m3
# sparse vector inside the Qdrant ranker rewards verbatim technical
# tokens (W12x40, ASTM A36, Q235, HRB400, SD345, …) natively via RRF
# fusion, so the dedicated regex extractor and its tests are no longer
# needed.


# ── Unit boost — locale alias coverage ────────────────────────────────


@pytest.mark.parametrize(
    ("locale_unit", "canonical"),
    [
        # ── Chinese (Simplified + Traditional) ──────────────────────
        ("立方米", "m3"),
        ("立方公尺", "m3"),
        ("平方米", "m2"),
        ("平方公尺", "m2"),
        ("米", "m"),
        ("公尺", "m"),
        ("千克", "kg"),
        ("公斤", "kg"),
        ("吨", "t"),
        ("件", "pcs"),
        ("个", "pcs"),
        ("個", "pcs"),
        # ── Japanese ────────────────────────────────────────────────
        ("立方メートル", "m3"),
        ("立米", "m3"),
        ("平方メートル", "m2"),
        ("平米", "m2"),
        ("メートル", "m"),
        ("キログラム", "kg"),
        ("トン", "t"),
        ("セット", "pcs"),
        ("式", "lsum"),
        ("時間", "h"),
        # ── Korean ──────────────────────────────────────────────────
        ("입방미터", "m3"),
        ("제곱미터", "m2"),
        ("미터", "m"),
        ("개", "pcs"),
        ("세트", "pcs"),
        ("시간", "h"),
        # ── Russian / Cyrillic ─────────────────────────────────────
        ("шт", "pcs"),
        ("шт.", "pcs"),
        ("кг", "kg"),
        ("м", "m"),
        ("м2", "m2"),
        ("м3", "m3"),
        ("куб.м", "m3"),
        ("кв.м", "m2"),
        ("комплект", "pcs"),
        ("ч", "h"),
        # ── Polish ──────────────────────────────────────────────────
        ("szt", "pcs"),
        ("szt.", "pcs"),
        ("kpl", "pcs"),
        ("godz", "h"),
        ("tona", "t"),
        # ── Turkish ─────────────────────────────────────────────────
        ("adet", "pcs"),
        ("takım", "pcs"),
        ("saat", "h"),
        # ── Spanish / Portuguese ───────────────────────────────────
        ("ud", "pcs"),
        ("ud.", "pcs"),
        ("uds", "pcs"),
        ("un", "pcs"),
        ("metro lineal", "m"),
        ("metro cúbico", "m3"),
        ("metro cuadrado", "m2"),
        ("hora", "h"),
        # ── French / Italian / German extras ───────────────────────
        ("stk", "pcs"),
        ("stück", "pcs"),
        ("std", "h"),
        ("stunde", "h"),
        ("unité", "pcs"),
        ("pièce", "pcs"),
        ("ora", "h"),
        ("pezzo", "pcs"),
        # ── Arabic ──────────────────────────────────────────────────
        ("متر", "m"),
        ("متر مكعب", "m3"),
        ("متر مربع", "m2"),
        ("كغ", "kg"),
        ("طن", "t"),
        ("قطعة", "pcs"),
        ("ساعة", "h"),
        # ── Hindi ───────────────────────────────────────────────────
        ("मीटर", "m"),
        ("वर्ग मीटर", "m2"),
        ("घन मीटर", "m3"),
        ("किलोग्राम", "kg"),
        ("टन", "t"),
        ("नग", "pcs"),
        ("घंटा", "h"),
        # ── English variants ───────────────────────────────────────
        ("cum", "m3"),
        ("sqm", "m2"),
        ("running meter", "m"),
        ("ea", "pcs"),
        ("nr", "pcs"),
    ],
)
def test_unit_boost_normalises_locale_aliases(locale_unit, canonical):
    """Locale-spelled units fold into canonical short codes for unit_match.

    Without this fold a Chinese CWICR row whose unit is ``立方米`` and an
    envelope inferred as ``m3`` from ``volume_m3`` quantity would fail the
    unit_match check (literal string compare) — even though they're the
    same dimension. The boost must emit ``unit_match`` for them, not
    ``unit_mismatch``.
    """
    from app.core.match_service.boosts.unit import _normalise_unit

    assert _normalise_unit(locale_unit) == canonical, (
        f"locale unit {locale_unit!r} should normalise to {canonical!r}, got {_normalise_unit(locale_unit)!r}"
    )


def test_unit_boost_locale_aliases_fire_match_not_mismatch():
    """End-to-end: a m3 envelope vs a Chinese 立方米 candidate emits unit_match."""

    from app.core.match_service.boosts.unit import boost
    from app.core.match_service.config import BOOST_WEIGHTS
    from app.core.match_service.envelope import ElementEnvelope, MatchCandidate

    envelope = ElementEnvelope(
        source="bim",
        ifc_class="IfcWall",
        description="bored wall",
        category="wall",
        unit_hint="m3",
        quantities={"volume_m3": 9.0},
    )
    candidate = MatchCandidate(
        code="C-001",
        description="Stahlbetonwand 钢筋混凝土墙",
        unit="立方米",  # Chinese m3 — without locale alias this would mismatch
    )

    deltas = boost(envelope, candidate, settings=None)
    assert deltas == {"unit_match": BOOST_WEIGHTS.unit_match}


# ── Language-family region aliases ───────────────────────────────────


@pytest.mark.parametrize(
    ("alias", "expected_member"),
    [
        # An ES-Madrid project that opts into ``hispanic`` should reward
        # MX_/AR_/CL_ rates as fallback when ES coverage is thin.
        ("hispanic", "MX_"),
        ("hispanic", "AR_"),
        ("hispanic", "CL_"),
        ("hispanic", "ES_"),
        # Lusophone — PT-Lisbon project willing to accept BR-Sao Paulo
        # rates as fallback. Symmetric: a BR project can opt into
        # PT_LISBON-priced rows the same way.
        ("lusophone", "PT_"),
        ("lusophone", "BR_"),
        ("lusophone", "AO_"),
        ("lusophone", "MZ_"),
        # Francophone, germanic, slavic — coverage check.
        ("francophone", "FR_"),
        ("francophone", "MA_"),
        ("francophone", "CA_"),
        ("germanic", "DE_"),
        ("germanic", "AT_"),
        ("germanic", "CH_"),
        ("slavic", "RU_"),
        ("slavic", "PL_"),
        ("slavic", "CZ_"),
        ("slavic", "BG_"),
        ("arabic", "AE_"),
        ("arabic", "SA_"),
        ("arabic", "EG_"),
        ("nordic", "SE_"),
        ("nordic", "DK_"),
        ("nordic", "FI_"),
        ("turkic", "TR_"),
        ("turkic", "KZ_"),
        ("sinic", "CN_"),
        ("sinic", "TW_"),
    ],
)
def test_language_family_aliases_resolve_correctly(alias, expected_member):
    """Operator opts into language coupling — the alias enumerates members."""

    class _Settings:
        class project:
            region = alias

    prefixes = _project_region_prefixes(_Settings())
    assert expected_member in prefixes, f"alias {alias!r} should include {expected_member!r}, got {prefixes!r}"


def test_bare_country_codes_stay_single_country():
    """Bare ISO codes don't auto-couple — operator must opt in explicitly.

    Ensures backward compatibility: a project pinned to ``"ES"`` continues
    to boost only ``ES_`` rows, NOT MX/AR. To get language-family
    coupling the operator picks ``"hispanic"`` explicitly.
    """

    for bare in ("ES", "PT", "FR", "DE", "RU", "TR"):

        class _Settings:
            class project:
                region = bare

        prefixes = _project_region_prefixes(_Settings())
        # Single-country = exactly one prefix tuple, matching the bare code.
        assert prefixes == (f"{bare}_",), f"bare {bare!r} should stay single-country, got {prefixes!r}"


# ── Confidence + auto-confirm thresholds env-overridable ─────────────


def test_confidence_and_auto_confirm_thresholds_are_env_overridable(
    monkeypatch,
):
    """Operators must be able to retune bands without a code deploy.

    Before this fix the thresholds were module-level literals, so a
    model cutover that shifted the score distribution forced a deploy
    just to nudge a band by a few points. Now they're ``_env_float()``
    reads — same machinery as boost weights — so a single env-var bump
    in the systemd unit file is enough to re-tune.

    The override values used here (0.81 / 0.65 / 0.92) intentionally
    differ from BOTH the v2 (0.85/0.70/0.95) and the v3 BGE-M3 defaults
    (0.78/0.62/0.88) so the assertion proves the env wins regardless of
    which set of defaults is active in the codebase at any time.
    """
    import importlib

    monkeypatch.setenv("MATCH_CONFIDENCE_HIGH", "0.81")
    monkeypatch.setenv("MATCH_CONFIDENCE_MEDIUM", "0.65")
    monkeypatch.setenv("MATCH_AUTO_CONFIRM_DEFAULT", "0.92")

    from app.core.match_service import config as cfg

    importlib.reload(cfg)

    assert pytest.approx(0.81) == cfg.CONFIDENCE_HIGH_THRESHOLD
    assert pytest.approx(0.65) == cfg.CONFIDENCE_MEDIUM_THRESHOLD
    assert pytest.approx(0.92) == cfg.DEFAULT_AUTO_CONFIRM_THRESHOLD

    # Restore default constants for downstream tests in this run.
    monkeypatch.delenv("MATCH_CONFIDENCE_HIGH", raising=False)
    monkeypatch.delenv("MATCH_CONFIDENCE_MEDIUM", raising=False)
    monkeypatch.delenv("MATCH_AUTO_CONFIRM_DEFAULT", raising=False)
    importlib.reload(cfg)


def test_unit_boost_locale_aliases_still_catch_real_mismatch():
    """Folding locale aliases must NOT mask genuine dimension mismatches.

    A m3 envelope vs a Russian ``м2`` candidate is still area-vs-volume —
    must produce unit_mismatch, not unit_match.
    """

    from app.core.match_service.boosts.unit import boost
    from app.core.match_service.config import BOOST_WEIGHTS
    from app.core.match_service.envelope import ElementEnvelope, MatchCandidate

    envelope = ElementEnvelope(
        source="bim",
        ifc_class="IfcWall",
        description="bored wall",
        category="wall",
        unit_hint="m3",
        quantities={"volume_m3": 9.0},
    )
    candidate = MatchCandidate(
        code="C-002",
        description="Опалубка стен м²",
        unit="м2",  # Russian m2 — must still trigger unit_mismatch
    )

    deltas = boost(envelope, candidate, settings=None)
    assert deltas == {"unit_mismatch": BOOST_WEIGHTS.unit_mismatch_penalty}


# ── Extractor source_lang inference (no "en" hardcode) ──────────────


def test_envelope_source_lang_default_is_empty_not_english():
    """A new ElementEnvelope without explicit source_lang must default to
    "" — NOT "en". The translation cascade short-circuits on empty
    source_lang, which is the right behaviour for an untagged element
    (don't pretend it's English; let BGE-M3 multilingual handle it).
    """
    from app.core.match_service.envelope import ElementEnvelope

    env = ElementEnvelope(source="bim")
    assert env.source_lang == "", (
        f"expected empty string default, got {env.source_lang!r} — "
        "an English default leaks an EN-source assumption to projects "
        "in any other language."
    )


def test_envelope_helpers_default_source_lang_to_empty():
    """The shared envelope builder respects empty input — no en fallback.

    A BIM extractor that fails to populate language must produce an
    envelope with source_lang="". The previous behaviour ("en" fallback)
    silently downgraded RU/DE/ES projects to English ranking.
    """
    from app.core.match_service.extractors._helpers import build_envelope_base

    env = build_envelope_base(
        source="bim",
        raw={},  # no language key
        description="Stahlbetonwand 24cm C30/37",
        category="wall",
    )
    assert env.source_lang == ""


def test_envelope_helpers_preserve_explicit_language():
    """When raw["language"] is set, we keep it verbatim (lower-cased)."""
    from app.core.match_service.extractors._helpers import build_envelope_base

    for lang in ("DE", "ru", "Es", "Ja", "zh"):
        env = build_envelope_base(
            source="bim",
            raw={"language": lang},
            description="бетонная стена",
            category="wall",
        )
        assert env.source_lang == lang.lower(), f"language {lang!r}: got {env.source_lang!r}"


# ── Match-defaults are env-overridable ──────────────────────────────


def test_match_default_target_language_helper_reads_env(monkeypatch):
    """The _env_float_default helper (used for MATCH_DEFAULT_AUTO_LINK_THRESHOLD)
    must read from environment so a non-English deploy can lower the
    threshold without a code change.

    Reloading the projects.models module would fail because SQLAlchemy
    registers the Project table once per metadata. We test the helper
    directly instead — same code path, no metadata churn.
    """
    from app.modules.projects.models import _env_float_default

    monkeypatch.setenv("OE_TEST_FLOAT", "0.42")
    assert _env_float_default("OE_TEST_FLOAT", 99.0) == pytest.approx(0.42)

    monkeypatch.delenv("OE_TEST_FLOAT", raising=False)
    assert _env_float_default("OE_TEST_FLOAT", 99.0) == 99.0

    # Garbage values fall back to default (not crash).
    monkeypatch.setenv("OE_TEST_FLOAT", "not-a-float")
    assert _env_float_default("OE_TEST_FLOAT", 99.0) == 99.0


def test_match_default_constants_match_canonical_values():
    """Default constants must stay in sync with their fallback literals.

    If a future change altered the fallback in models.py, the rankers'
    transient settings would silently diverge. This test pins the
    expected pair so a drift surfaces immediately.
    """
    from app.modules.projects.models import (
        MATCH_DEFAULT_AUTO_LINK_THRESHOLD,
        MATCH_DEFAULT_TARGET_LANGUAGE,
    )

    # Default values when no env overrides set in the test runner.
    # Both are documented in CLAUDE.md as v2.8.0 calibration.
    assert MATCH_DEFAULT_TARGET_LANGUAGE == "en"
    assert pytest.approx(0.85) == MATCH_DEFAULT_AUTO_LINK_THRESHOLD


def test_bulk_confirm_threshold_uses_central_default():
    """BulkConfirmRequest.threshold reads from the same DEFAULT_AUTO_CONFIRM
    constant as SessionCreate.auto_confirm_threshold — no duplicate 0.95.
    """
    from app.core.match_service.config import DEFAULT_AUTO_CONFIRM_THRESHOLD
    from app.modules.match_elements.schemas import BulkConfirmRequest

    req = BulkConfirmRequest()
    assert req.threshold == pytest.approx(DEFAULT_AUTO_CONFIRM_THRESHOLD), (
        "BulkConfirmRequest.threshold drifted from DEFAULT_AUTO_CONFIRM_THRESHOLD; "
        "operators expecting one env override would have to set both."
    )


# ── iter-5: residual EUR fallbacks killed in catalog/procurement/risk/costs ─


def test_cost_item_create_default_currency_is_empty():
    """CostItemCreate must default to empty currency, not "EUR".

    The empty default propagates through the import pipeline so a
    catalogue lacking an explicit currency column doesn't get stamped
    with EUR — the row stays honest about its unknown denomination,
    and downstream FX/region resolution can fill it from project ctx.
    """
    from app.modules.costs.schemas import CostItemCreate

    item = CostItemCreate(code="C-001", unit="m3", rate=185.0)
    assert item.currency == ""


def test_match_result_currency_passthrough_is_empty_when_unknown():
    """Costs matcher's _to_match_result must mirror item.currency, not invent EUR.

    Without this passthrough, a US project querying a CWICR row that
    legitimately stored ``currency = ""`` (legacy parquet imports) gets
    its match record stamped EUR — leading the renderer to label a
    USD-equivalent rate as EUR.
    """
    from types import SimpleNamespace

    from app.modules.costs.matcher import _to_match_result

    item_no_currency = SimpleNamespace(id="abc", code="C-200", description="x", unit="m3", rate="185.0", currency="")
    res = _to_match_result(item_no_currency, score=0.9, channel="vector")
    assert res.currency == ""


def test_risk_stats_initial_currency_is_empty():
    """Risk stats currency must start empty so the first item with a real
    currency wins — the prior 'EUR' seed silently survived projects with
    no currency set.
    """
    import inspect

    from app.modules.risk.service import RiskService

    src = inspect.getsource(RiskService.get_summary)
    assert '"EUR"' not in src, (
        "Risk summary still seeds currency with 'EUR' — must resolve from the "
        "project so a USD/BRL/CNY project shows the right currency."
    )
    # Currency is data-driven: resolved from the owning project (empty string
    # when the project has none), not a hardcoded seed.
    assert "_get_project_currency" in src
