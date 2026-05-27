# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BGE-M3 + Qdrant recall benchmark scaffold (Task #186, MAPPING_PROCESS §4/§5).

Companion to :mod:`tests.eval.test_v3_recall_benchmark` — *that* file
runs through the full ranker (high-level dispatch through the project
settings + boost stack), this one drives the underlying
:func:`qdrant_adapter.search` directly so we can attribute recall
purely to the embedding model + RRF fusion, with no boosts or
session-state coupling.

Why a separate harness?
-----------------------

Confidence-band recalibration (this task) hinges on the raw RRF score
distribution. The integrated ranker masks that distribution by adding
classifier / unit / region boosts and the soft-boost stack on top —
useful for production accuracy, useless when we want to know whether
the *bands* are correctly pinned. A direct ``qdrant_adapter.search``
call returns the unadulterated RRF score so band-floor calibration can
be checked numerically.

This is a **benchmark**, not a CI gate. It is gated behind the
``benchmark`` pytest marker AND a Qdrant-availability skipif, so:

* On dev machines without Qdrant → SKIP (collects clean, doesn't run).
* On CI without ``-m benchmark`` → DESELECTED.
* On a properly-provisioned VPS with ``pytest -m benchmark`` → RUNS,
  prints a per-language recall@1/5/10 markdown table to stdout.

Run (live infrastructure required):

    cd backend
    CWICR_QDRANT_URL=http://localhost:6333 \\
        python -m pytest tests/perf/test_recall_bge_m3_benchmark.py \\
        -m benchmark -v -s

The ``-s`` is essential — without it pytest captures stdout and the
markdown table is hidden.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.modules.costs.qdrant_adapter import country_to_collection

# ── Inline fallback queries ──────────────────────────────────────────────
#
# Used only when ``tests/eval/golden_set.yaml`` is missing or
# unparseable. Each entry mirrors the live golden_set.yaml schema so
# the benchmark loop is uniform regardless of source.
#
# Spread: 6 EN + 6 DE + 6 RU + 2 ES = 20 queries covering walls, slabs,
# foundations, MEP, finishing, and roofing — the bread-and-butter
# trades a misranked CWICR row would degrade the most.

_INLINE_FALLBACK_GOLDEN: list[dict[str, Any]] = [
    # English (target_language=en, expected to land in cwicr_en_v3)
    {
        "id": "fallback-en-001",
        "target_language": "en",
        "query": "Reinforced concrete wall, C30/37, 24cm thick, fire rating F90",
        "country": "USA_USD",
        "expected_codes": ["330.10.020", "330.10.021", "330.10.022"],
    },
    {
        "id": "fallback-en-002",
        "target_language": "en",
        "query": "Reinforced concrete slab, C25/30, 200mm thick, residential floor",
        "country": "USA_USD",
        "expected_codes": ["350.10.010", "350.10.011"],
    },
    {
        "id": "fallback-en-003",
        "target_language": "en",
        "query": "Strip foundation, concrete C20/25, 600mm wide, 800mm deep",
        "country": "USA_USD",
        "expected_codes": ["322.10.010", "322.10.020"],
    },
    {
        "id": "fallback-en-004",
        "target_language": "en",
        "query": "Drywall partition, double-sided 12.5mm gypsum, 100mm metal stud",
        "country": "GB_LONDON",
        "expected_codes": ["331.30.010", "331.30.020"],
    },
    {
        "id": "fallback-en-005",
        "target_language": "en",
        "query": "Triple-glazed aluminium window, Uw=0.9, 1.20x1.40m",
        "country": "GB_LONDON",
        "expected_codes": ["334.10.010", "334.10.020"],
    },
    {
        "id": "fallback-en-006",
        "target_language": "en",
        "query": "Bituminous roof waterproofing, 2-layer SBS membrane, with primer",
        "country": "USA_USD",
        "expected_codes": ["362.10.010", "362.10.020"],
    },
    # German (target_language=de, expected to land in cwicr_de_v3)
    {
        "id": "fallback-de-001",
        "target_language": "de",
        "query": "Stahlbetonwand C30/37, 24cm dick, Brandschutz F90",
        "country": "DE_BERLIN",
        "expected_codes": ["330.10.020", "330.10.021", "330.10.022"],
    },
    {
        "id": "fallback-de-002",
        "target_language": "de",
        "query": "Mauerwerk Kalksandstein KS 12-1.4, 17.5cm dick",
        "country": "DE_BERLIN",
        "expected_codes": ["331.20.010", "331.20.011"],
    },
    {
        "id": "fallback-de-003",
        "target_language": "de",
        "query": "Wandanstrich Dispersionsfarbe weiß, 2 Anstriche",
        "country": "DE_BERLIN",
        "expected_codes": ["363.10.010", "363.10.020"],
    },
    {
        "id": "fallback-de-004",
        "target_language": "de",
        "query": "Bodenbelag Linoleum 2.5 mm verklebt",
        "country": "DE_BERLIN",
        "expected_codes": ["352.40.010", "352.40.020"],
    },
    {
        "id": "fallback-de-005",
        "target_language": "de",
        "query": "Vakuumdämmpaneel VIP 20 mm",
        "country": "DE_BERLIN",
        "expected_codes": ["361.30.090", "361.30.091"],
    },
    {
        "id": "fallback-de-006",
        "target_language": "de",
        "query": "Aluminium-Fenster Dreifachverglasung Uw=0.9",
        "country": "AT_VIENNA",
        "expected_codes": ["334.10.010", "334.10.020"],
    },
    # Russian (target_language=ru, expected to land in cwicr_ru_v3)
    {
        "id": "fallback-ru-001",
        "target_language": "ru",
        "query": "Радиатор стальной панельный 22-500-1000, с подключением",
        "country": "RU_MOSCOW",
        "expected_codes": ["422.10.010", "422.10.020"],
    },
    {
        "id": "fallback-ru-002",
        "target_language": "ru",
        "query": "Бетонная стена C30/37, толщина 240 мм",
        "country": "RU_MOSCOW",
        "expected_codes": ["330.10.020", "330.10.021"],
    },
    {
        "id": "fallback-ru-003",
        "target_language": "ru",
        "query": "Кирпичная кладка из глиняного кирпича NF, 240 мм, раствор M10",
        "country": "RU_MOSCOW",
        "expected_codes": ["331.10.010", "331.10.020"],
    },
    {
        "id": "fallback-ru-004",
        "target_language": "ru",
        "query": "Армированная бетонная плита, толщина 200 мм, C25/30",
        "country": "RU_MOSCOW",
        "expected_codes": ["350.10.010", "350.10.011"],
    },
    {
        "id": "fallback-ru-005",
        "target_language": "ru",
        "query": "Воздуховод оцинкованный прямоугольный 400x200 мм",
        "country": "RU_STPETERSBURG",
        "expected_codes": ["432.10.010", "432.10.020"],
    },
    {
        "id": "fallback-ru-006",
        "target_language": "ru",
        "query": "Электрическая розетка двойная скрытой установки",
        "country": "RU_MOSCOW",
        "expected_codes": ["445.10.010", "445.10.020"],
    },
    # Spanish (target_language=es, expected to land in cwicr_es_v3)
    {
        "id": "fallback-es-001",
        "target_language": "es",
        "query": "Muro de hormigón armado C30/37, 24cm de espesor",
        "country": "ES_MADRID",
        "expected_codes": ["330.10.020", "330.10.021"],
    },
    {
        "id": "fallback-es-002",
        "target_language": "es",
        "query": "Aislamiento térmico panel rígido 60mm",
        "country": "MX_MEXICO",
        "expected_codes": ["361.10.010", "361.10.020"],
    },
]


# ── Golden set loading ───────────────────────────────────────────────────


def _golden_path() -> Path:
    return Path(__file__).resolve().parents[1] / "eval" / "golden_set.yaml"


def _load_yaml_golden() -> list[dict[str, Any]]:
    """Load and adapt :file:`tests/eval/golden_set.yaml` to the harness shape.

    The yaml file uses an ``element_info`` + ``ground_truth`` schema — we
    flatten it to the simpler ``query`` + ``expected_codes`` form the
    benchmark loop wants. Returns ``[]`` when the file is missing,
    empty, or malformed; the inline fallback then takes over.
    """

    p = _golden_path()
    if not p.exists():
        return []
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, list) or not raw:
        return []

    cases: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        info = entry.get("element_info") or {}
        gt = entry.get("ground_truth") or {}
        codes = gt.get("cwicr_position_codes") or []
        if not codes:
            continue
        # Synthesize a query string from element_info — prefer an
        # explicit description, otherwise stitch material + dims.
        desc = info.get("description") or info.get("material") or ""
        if not desc and "category" in info:
            desc = str(info["category"])
        if not desc:
            continue
        # Use the entry's target_language to drive the collection
        # selection. country is derived from target_language when the
        # yaml doesn't pin one (most don't).
        target_lang = (entry.get("target_language") or "en").lower()
        country = entry.get("country") or _country_for_language(target_lang)
        cases.append(
            {
                "id": entry.get("id") or "",
                "target_language": target_lang,
                "query": str(desc),
                "country": country,
                "expected_codes": [str(c) for c in codes],
            }
        )
    return cases


def _country_for_language(lang: str) -> str:
    """Pick a representative country code for the given ISO-639-1 lang.

    The benchmark just needs a region the adapter will route to the
    matching language collection; the specific country head doesn't
    affect recall as long as it lines up with ``country_to_collection``.
    """

    return {
        "en": "USA_USD",
        "de": "DE_BERLIN",
        "ru": "RU_MOSCOW",
        "es": "ES_MADRID",
        "fr": "FR_PARIS",
        "pt": "BR_SAOPAULO",
        "tr": "TR_ISTANBUL",
        "pl": "PL_WARSAW",
        "ja": "JP_TOKYO",
        "zh": "CN_BEIJING",
    }.get(lang.lower(), "USA_USD")


def _load_cases() -> list[dict[str, Any]]:
    """Resolve the golden set, falling back to the inline list if needed."""

    cases = _load_yaml_golden()
    if cases:
        return cases
    return list(_INLINE_FALLBACK_GOLDEN)


# ── Qdrant availability gate ─────────────────────────────────────────────


def _qdrant_available() -> bool:
    """Best-effort probe — never imports heavy deps when they're missing.

    Returns True only when both:

    * Qdrant client + a reachable URL or embedded path are configured,
    * The client can answer ``get_collections`` without raising.

    Any failure (missing wheel, bad URL, network error) returns False so
    the test SKIPs cleanly on dev boxes without surfacing a confusing
    import error.
    """

    if not (os.environ.get("CWICR_QDRANT_URL") or os.environ.get("CWICR_QDRANT_PATH")):
        return False
    try:
        from app.modules.costs.qdrant_adapter import _get_client

        client = _get_client()
        client.get_collections()
        return True
    except Exception:
        return False


# ── The benchmark itself ─────────────────────────────────────────────────


@pytest.mark.benchmark
@pytest.mark.skipif(
    not _qdrant_available(),
    reason="Qdrant not reachable; BGE-M3 recall benchmark is opt-in via live infra.",
)
@pytest.mark.asyncio
async def test_bge_m3_recall_per_language() -> None:
    """Drive the golden set through ``qdrant_adapter.search`` directly.

    Records the rank of the first ``expected_codes`` hit for each query,
    then aggregates per-language and global recall@1/5/10. Prints a
    markdown table to stdout for the operator to inspect.
    """

    from app.modules.costs.qdrant_adapter import search

    cases = _load_cases()
    assert cases, "no golden cases available — fallback list is empty"

    # Bucket: language → list of ranks (0-indexed, -1 if not found in top 10)
    ranks_by_lang: dict[str, list[int]] = {}
    misses_by_id: dict[str, list[str]] = {}

    for case in cases:
        lang = case["target_language"]
        country = case["country"]
        query = case["query"]
        expected: set[str] = set(case["expected_codes"])

        try:
            hits = await search(
                country=country,
                core_query=query,
                limit=10,
            )
        except Exception as exc:  # pragma: no cover — defensive
            # Most likely a missing collection (cwicr_<lang>_v3 not
            # provisioned for this language yet). Record as a miss.
            misses_by_id[case["id"]] = [f"<error: {type(exc).__name__}: {exc}>"]
            ranks_by_lang.setdefault(lang, []).append(-1)
            continue

        rank = -1
        for idx, hit in enumerate(hits):
            from app.modules.costs.qdrant_adapter import base_code

            hit_code = hit.rate_code or ""
            if hit_code in expected or base_code(hit_code) in expected:
                rank = idx
                break

        ranks_by_lang.setdefault(lang, []).append(rank)
        if rank == -1:
            misses_by_id[case["id"]] = [h.rate_code for h in hits[:5]]

    # ── Print markdown ──────────────────────────────────────────────────
    print("\n\n## BGE-M3 + Qdrant recall benchmark\n")
    print("Collection scheme: `cwicr_<lang>_v3` (resolved via `country_to_collection`)")
    print(f"Total cases: {sum(len(v) for v in ranks_by_lang.values())}")
    print()
    print("| Language | N | recall@1 | recall@5 | recall@10 |")
    print("|----------|---|----------|----------|-----------|")

    total_hits_at_1 = 0
    total_hits_at_5 = 0
    total_hits_at_10 = 0
    total_n = 0

    for lang in sorted(ranks_by_lang):
        ranks = ranks_by_lang[lang]
        n = len(ranks)
        h1 = sum(1 for r in ranks if 0 <= r < 1)
        h5 = sum(1 for r in ranks if 0 <= r < 5)
        h10 = sum(1 for r in ranks if 0 <= r < 10)
        # Resolve which collection these queries actually hit so the
        # operator sees a misrouted lang immediately.
        sample_country = next(c["country"] for c in cases if c["target_language"] == lang)
        coll = country_to_collection(sample_country)
        print(f"| {lang} ({coll}) | {n} | {h1 / n:.2%} | {h5 / n:.2%} | {h10 / n:.2%} |")
        total_hits_at_1 += h1
        total_hits_at_5 += h5
        total_hits_at_10 += h10
        total_n += n

    if total_n:
        print(
            f"| **total** | **{total_n}** | "
            f"**{total_hits_at_1 / total_n:.2%}** | "
            f"**{total_hits_at_5 / total_n:.2%}** | "
            f"**{total_hits_at_10 / total_n:.2%}** |"
        )

    if misses_by_id:
        print("\n### Top-1 misses (first 5 hit codes per missed case):\n")
        for case_id, hit_codes in misses_by_id.items():
            print(f"* `{case_id}` → {hit_codes}")

    # The benchmark intentionally does NOT assert a recall floor —
    # ``tests.eval.test_v3_recall_benchmark`` is the gate that does
    # that. This harness only reports numbers so the operator can pin
    # the confidence-band thresholds against the observed distribution.


# ── Sanity guards (always run, even without -m benchmark) ────────────────


def test_inline_fallback_is_well_formed() -> None:
    """Belt-and-braces: every fallback case has the required keys.

    A typo in the inline list would silently skip queries during the
    benchmark run. Pinning the schema here makes the failure loud.
    """

    required = {"id", "target_language", "query", "country", "expected_codes"}
    for case in _INLINE_FALLBACK_GOLDEN:
        missing = required - set(case)
        assert not missing, f"case {case.get('id')!r} missing keys: {missing}"
        assert case["expected_codes"], f"case {case['id']!r} has empty expected_codes"
        assert case["query"], f"case {case['id']!r} has empty query"


def test_inline_fallback_covers_multiple_languages() -> None:
    """We want at least 3 languages so the per-language recall table is
    informative. A single-language fallback would mask BGE-M3's
    multilingual claim entirely."""

    langs = {c["target_language"] for c in _INLINE_FALLBACK_GOLDEN}
    assert len(langs) >= 3, f"only {len(langs)} languages in fallback: {langs}"


def test_country_for_language_routes_to_correct_collection() -> None:
    """Pin the helper so a future REGION_LANGUAGE refactor can't silently
    break the benchmark's collection routing."""

    assert country_to_collection(_country_for_language("en")).endswith("_en_v3") or country_to_collection(
        _country_for_language("en")
    ).endswith("_en")
    assert country_to_collection(_country_for_language("de")).endswith("_de_v3") or country_to_collection(
        _country_for_language("de")
    ).endswith("_de")
    assert country_to_collection(_country_for_language("ru")).endswith("_ru_v3") or country_to_collection(
        _country_for_language("ru")
    ).endswith("_ru")
