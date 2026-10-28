"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The vector-snapshot paths are derived from the registry, not kept by hand.

The snapshot map used to be a literal table next to the endpoint that reads it.
When the data repo nested every market under a common folder, the parquet map
moved with it because it is derived, and the snapshot table did not, so all
thirteen of its entries named files that no longer existed and every restore
returned a download error. These tests hold the two maps to the same source.
"""

from app.modules.costs import base_registry


def _global_variants() -> list:
    return [v for v in base_registry.iter_variants() if not v.bundled]


def test_every_downloadable_base_has_a_snapshot_and_no_other_one_does() -> None:
    """Only the global markets publish a snapshot, and all of them do."""
    files = base_registry.github_snapshot_files()
    expected = {v.region for v in _global_variants()}
    assert set(files) == expected
    # Anchored on _NATIONAL_FAMILIES rather than on ``bundled``. The two lines
    # above and the map itself all read ``bundled``, so an edit that changes what
    # that field says moves every side of the comparison together and this test
    # stays green through exactly the regression its message describes. That was
    # measured, not assumed: setting the eight national families to
    # ``bundled=False`` puts eight never-published snapshot paths into the map
    # and all three assertions here still pass. The national families are a
    # separate structure, so they hold still while the field moves.
    national = {v.region for family in base_registry._NATIONAL_FAMILIES for v in family.variants}
    assert len(national) == 8, f"the eight national bases became {len(national)}, so this guard needs rereading"
    assert not (set(files) & national), "a national base would point at a snapshot that was never published"


def test_a_snapshot_sits_in_the_same_folder_as_its_own_work_items() -> None:
    """The tie that makes a repo move break both maps together or neither.

    A snapshot and the parquet it was built from ship side by side. Asserting
    the folder rather than the literal path means the next restructuring shows
    up here instead of only at download time.
    """
    files = base_registry.github_snapshot_files()
    for variant in _global_variants():
        snapshot_folder = files[variant.region].rsplit("/", 1)[0]
        parquet_folder = variant.workitems_path.rsplit("/", 1)[0]
        assert snapshot_folder == parquet_folder, f"{variant.region} snapshot left its own folder"


def test_canada_keeps_the_short_token_its_snapshot_was_published_under() -> None:
    """The one market whose snapshot is not named after its region.

    Canada ships ENG_TORONTO work items and catalog beside an EN_TORONTO
    snapshot. Deriving the file name from the region is correct everywhere else,
    so dropping this override reads as a simplification and quietly breaks the
    only market it applies to.
    """
    files = base_registry.github_snapshot_files()
    canada = files["ENG_TORONTO"]
    assert canada.rsplit("/", 1)[1].startswith("EN_TORONTO_"), canada
    assert "ENG_TORONTO_workitems" not in canada
    others = [r for r in files if r != "ENG_TORONTO"]
    for region in others:
        assert files[region].rsplit("/", 1)[1].startswith(f"{region}_"), (
            f"{region} is not the documented exception yet does not match its own region"
        )


def test_the_internal_aliases_resolve_to_a_real_markets_snapshot() -> None:
    """CA_TORONTO and ZH_CHINA are ids the endpoint answers but nothing derives."""
    from app.modules.costs.router import _GITHUB_SNAPSHOT_FILES

    derived = base_registry.github_snapshot_files()
    assert _GITHUB_SNAPSHOT_FILES["CA_TORONTO"] == derived["ENG_TORONTO"]
    assert _GITHUB_SNAPSHOT_FILES["ZH_CHINA"] == derived["ZH_SHANGHAI"]
    assert set(derived) <= set(_GITHUB_SNAPSHOT_FILES)


def test_only_the_one_documented_national_base_reaches_the_snapshot_map() -> None:
    """Nobody may copy the ZH_CHINA line for the other seven national bases.

    Read the test above and this one together, because they disagree about the
    same line on purpose. That one says ZH_CHINA resolves to a real market's
    snapshot, which is true and is the problem: ZH_CHINA is the China Dinge
    base, so the market it resolves to is a different catalogue. None of the
    eight national bases has a published vector snapshot, which is why
    ``github_snapshot_files`` omits them, so an alias is the only way one gets
    into the map at all.

    Counting them rather than pinning what ZH_CHINA points at. Pinning the
    mismatch would have to be edited by whoever fixes it and would read as
    sanctioning it, while a count goes red on the copy-paste that would spread
    it and stays silent about how the one we have should end.
    """

    from app.modules.costs.router import _GITHUB_SNAPSHOT_FILES

    national = {v.region for family in base_registry._NATIONAL_FAMILIES for v in family.variants}
    present = sorted(national & set(_GITHUB_SNAPSHOT_FILES))
    assert present == ["ZH_CHINA"], (
        f"{present} are national base ids reachable in the snapshot map. Only ZH_CHINA is, "
        "for historical reasons recorded next to the alias in router.py. A national base has "
        "no snapshot of its own, so a new entry here would hand it another catalogue's vectors."
    )
