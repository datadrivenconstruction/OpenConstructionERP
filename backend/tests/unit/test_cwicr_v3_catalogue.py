# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the CWICR v3 catalogue registry.

Covers:

* Master list invariants (30 rows, unique regions, every language has
  at least one available row OR all coming-soon).
* ``get_catalogue`` lookup — case-insensitive, exact match (no alias
  resolution to avoid silently-wrong restores).
* Each row maps to a real ``cwicr_{lang}_v3`` collection consistent
  with :mod:`region_language`.
"""

from __future__ import annotations

import pytest

from app.core.match_service.region_language import language_for
from app.modules.costs.cwicr_v3_catalogue import (
    CWICR_V3_CATALOGUES,
    CwicrV3Catalogue,
    get_catalogue,
)
from app.modules.costs.qdrant_adapter import country_to_collection


@pytest.fixture(autouse=True)
def _pure_routing(monkeypatch: pytest.MonkeyPatch):
    """Disable the live-collection availability probe (pure routing contract).

    A sparsely populated dev Qdrant (only ``cwicr_en_v3``) otherwise folds
    every non-English region into English and the registry-vs-adapter
    assertions go env-dependent. Empty probe = naive language-derived name.
    """
    from app.modules.costs import qdrant_adapter

    monkeypatch.setattr(qdrant_adapter, "_available_cwicr_collections", lambda: frozenset())


def test_registry_size_is_intentional():
    """Region target from v3 plan §2.1 + Africa pack + HF region expansion —
    guards against accidental drops."""
    assert len(CWICR_V3_CATALOGUES) == 48


def test_no_duplicate_regions():
    """Each region id must be unique — UI keys cards by region."""
    regions = [c.region for c in CWICR_V3_CATALOGUES]
    assert len(regions) == len(set(regions)), f"duplicate region(s): {regions}"


def test_every_row_has_required_fields():
    for cat in CWICR_V3_CATALOGUES:
        assert cat.region, f"empty region in {cat}"
        assert cat.country_iso, f"empty country_iso in {cat.region}"
        assert cat.city, f"empty city in {cat.region}"
        assert cat.language, f"empty language in {cat.region}"
        assert cat.currency, f"empty currency in {cat.region}"
        assert cat.ddc_path.endswith(".snapshot"), f"ddc_path missing .snapshot: {cat.region}"
        assert "BGEM3_V3" in cat.ddc_path, f"ddc_path missing BGEM3_V3 marker: {cat.region}"
        assert cat.size_mb > 0, f"non-positive size_mb: {cat.region}"


def test_collection_name_matches_adapter_routing():
    """Each catalogue's ``collection`` must match what country_to_collection() returns.

    Drift between the registry and the search adapter would mean the UI
    reports a collection installed but search misses it (or vice-versa).
    """
    for cat in CWICR_V3_CATALOGUES:
        adapter_collection = country_to_collection(cat.region)
        assert cat.collection == adapter_collection, (
            f"{cat.region}: registry says {cat.collection!r}, adapter routes to {adapter_collection!r}"
        )


def test_language_field_matches_region_language():
    """Registry's ``language`` must agree with :func:`region_language.language_for`."""
    for cat in CWICR_V3_CATALOGUES:
        expected = language_for(cat.region)
        assert cat.language == expected, (
            f"{cat.region}: registry lang={cat.language!r}, region_language says {expected!r}"
        )


def test_ddc_path_starts_with_lang_directory():
    """ddc_path must use one of the two supported layouts.

    Legacy GitHub: ``<LANG>___DDC_CWICR/<region>_workitems_…``
    HuggingFace v1+: ``<XX>/<region-or-legacy-id>_workitems_…``
    """
    for cat in CWICR_V3_CATALOGUES:
        first_segment = cat.ddc_path.split("/", 1)[0]
        legacy_github = first_segment.endswith("___DDC_CWICR")
        # HF folders are 2-letter language/locale codes (AR, EN, ZH, …).
        hf_layout = len(first_segment) == 2 and first_segment.isalpha()
        assert legacy_github or hf_layout, (
            f"{cat.region}: ddc_path first segment {first_segment!r} "
            "must be either '<XX>___DDC_CWICR' (GitHub) or '<XX>' (HF)"
        )


def test_installable_catalogues_never_keep_the_legacy_github_path():
    """A row the UI will actually download must point at a host still serving it.

    The two layouts in :func:`test_ddc_path_starts_with_lang_directory` are not
    interchangeable any more. DDC stopped publishing v3 snapshots to GitHub LFS
    when the bandwidth cap kept getting hit, and the flat
    ``<LANG>___DDC_CWICR/`` paths written into this file are dead there today -
    a HEAD on one answers 404 while the HF path for the same region answers
    302. What keeps that from being a live defect is ``_apply_hf_overrides``,
    which rewrites every published region's ``ddc_path`` to the HF layout at
    import time, so the literals above are documentation and the runtime value
    is what installs.

    That leaves exactly one way to break it: mark a row available without
    giving it an HF path. ``install_v3_catalogue`` picks its base URL by
    looking for ``___DDC_CWICR`` in the path, so such a row would send Qdrant
    to a GitHub URL that no longer exists and the install would fail at
    download with nothing in the registry looking wrong.

    No row carries a legacy path today. ZH_CHINA and TR_NATIONAL used to, and
    the 409 for an unpublished region was the only thing keeping them off a
    dead URL, until both turned out to have been published all along under
    their pre-rename ids. So this finds nothing at the moment and regains its
    force the first time a genuinely pending region is added, which is why it
    reads the tuple rather than naming regions.
    """
    stranded = [cat.region for cat in CWICR_V3_CATALOGUES if cat.available and "___DDC_CWICR" in cat.ddc_path]
    assert not stranded, (
        f"{stranded} are offered for install but still point at the retired GitHub LFS "
        "layout. Add them to _HF_PUBLISHED so _apply_hf_overrides rewrites the path, "
        "rather than flipping available on its own."
    )


def test_ddc_path_filename_starts_with_region_or_alias():
    """Filename inside the DDC dir must start with the region id OR its
    HF-published alias (e.g. CA_TORONTO → ENG_TORONTO, GB_LONDON → UK_GBP).
    """
    from app.modules.costs.cwicr_v3_catalogue import _HF_PUBLISHED

    for cat in CWICR_V3_CATALOGUES:
        filename = cat.ddc_path.rsplit("/", 1)[-1]
        ok = filename.startswith(cat.region + "_")
        if not ok:
            alias = _HF_PUBLISHED.get(cat.region)
            ok = bool(alias and filename.startswith(alias[1] + "_"))
        assert ok, (
            f"{cat.region}: filename {filename!r} should start with the region id or a registered HF-published alias"
        )


@pytest.mark.parametrize(
    ("lookup", "expected_region"),
    [
        ("RU_STPETERSBURG", "RU_STPETERSBURG"),
        ("ru_stpetersburg", "RU_STPETERSBURG"),  # case-insensitive input
        ("  DE_BERLIN  ", "DE_BERLIN"),  # whitespace-tolerant
        ("USA_USD", "USA_USD"),
    ],
)
def test_get_catalogue_resolves(lookup: str, expected_region: str):
    cat = get_catalogue(lookup)
    assert cat is not None
    assert cat.region == expected_region


@pytest.mark.parametrize(
    "lookup",
    [
        "",
        None,
        "UNKNOWN_REGION",
        "UK_GBP",  # legacy alias — explicitly NOT resolved (would mis-route)
        "ENG_TORONTO",  # mis-prefixed alias
    ],
)
def test_get_catalogue_returns_none_for_unknown(lookup):
    assert get_catalogue(lookup) is None


def test_at_least_one_catalogue_is_available_today():
    """Sanity check — the registry must reflect at least one published v3 snapshot.

    If this fails, DDC has either un-published the RU release or the
    registry's ``available`` flag drifted out of sync. Check the DDC
    repo before flipping more rows.
    """
    available = [c for c in CWICR_V3_CATALOGUES if c.available]
    assert available, "no v3 catalogues marked available — registry stale?"


def test_registry_is_immutable():
    """Frozen dataclass guards against accidental mutation by callers."""
    cat = CWICR_V3_CATALOGUES[0]
    with pytest.raises(Exception):
        cat.size_mb = 999  # type: ignore[misc]


def test_collection_property_consistent_across_same_language():
    """All catalogues sharing a language must resolve to the same collection."""
    by_lang: dict[str, list[CwicrV3Catalogue]] = {}
    for cat in CWICR_V3_CATALOGUES:
        by_lang.setdefault(cat.language, []).append(cat)
    for lang, group in by_lang.items():
        collections = {c.collection for c in group}
        assert len(collections) == 1, f"language {lang!r} has divergent collections: {collections}"
