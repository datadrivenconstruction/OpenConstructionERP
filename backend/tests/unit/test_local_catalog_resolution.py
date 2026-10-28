# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Where the catalogue directory resolves, in an install as well as a checkout.

``app/modules/catalog/router.py`` located the locally generated catalogue CSVs
by counting five parent directories up from its own file. That reaches the repo
root in a source checkout and the virtualenv's ``Lib`` in a pip or desktop
install, where no ``data`` directory has ever existed. Measured on the installed
venv in this tree, the old expression produced
``.venv-run/Lib/data/catalog/regions``.

Unlike the packs defect this mirrors, the consequence was not an empty page: the
lookup falls through to a GitHub download, so an online host kept working and
nothing ever complained. An offline or air-gapped host got nothing at all, and
every install silently spent a network round trip on data it was supposed to
find on disk.

The second half of the same tuple was wrong for a different reason.
``Path.cwd()`` was evaluated once, at import, so a process that changed
directory afterwards kept answering for the directory it no longer ran in.
Resolving per call is what fixes that, and it is asserted here directly.

Deliberately not here: any claim that a released artefact carries the data. It
does not, by decision. ``desktop/pyinstaller.spec`` records that at the top of
the file and NOTICE carries the reason, and
``test_catalog_offline_lookup.test_catalog_regions_are_not_bundled_in_the_package``
already pins it. This file is about the resolver only, which is why the
installed-layout cases build their own synthetic tree rather than looking for
one in the wheel.

Every case below is filesystem work against a synthetic layout, so the source
checkout this runs in cannot supply the answer by accident.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.catalog.router import (
    _is_local_catalog_dir,
    _local_catalog_dirs,
    _local_catalog_dirs_for,
)

# The dotted name router.py is imported under. The resolver reads its depth from
# this string, so the synthetic layouts below have to use the real one.
_ROUTER_MODULE = "app.modules.catalog.router"


def _plant_catalog(catalog_dir: Path, region: str = "DE_BERLIN") -> Path:
    """Create the smallest tree that counts as a real catalogue directory."""
    catalog_dir.mkdir(parents=True, exist_ok=True)
    csv = catalog_dir / f"DDC_CWICR_{region}_Catalog.csv"
    csv.write_bytes(b"resource_code,name\r\n" + b"x" * 2000)
    return csv


def _router_at(package_root: Path) -> Path:
    """Path router.py would occupy under a root holding the ``app`` package."""
    return package_root / "app" / "modules" / "catalog" / "router.py"


def test_the_repository_catalogue_directory_is_readable_at_all() -> None:
    """Guard the instrument before the comparisons that lean on it.

    Several assertions below are "this directory was accepted" and "that one was
    not", and a shape check that never accepts anything would satisfy half of
    them while measuring nothing. Prove the real tree passes first.
    """
    repo_root = Path(__file__).resolve().parents[3]
    real = repo_root / "data" / "catalog" / "regions"
    csvs = sorted(real.glob("DDC_CWICR_*_Catalog.csv")) if real.is_dir() else []
    print(f"\n{len(csvs)} catalogue CSV(s) under {real}")
    assert _is_local_catalog_dir(real), (
        f"{real} is not recognised as a catalogue directory. Either the repository stopped carrying "
        f"the generated catalogues or the shape check no longer matches their file names, and every "
        f"other assertion in this file would then be comparing empty against empty."
    )


def test_the_catalogue_dir_resolves_in_an_installed_layout(tmp_path: Path) -> None:
    """The case that was broken for every install and that nothing measured.

    In a wheel install router.py sits at
    ``site-packages/app/modules/catalog/router.py`` and anything shipped beside
    the package sits at ``site-packages/<name>``, the way ``locales`` and
    ``alembic`` already do. The old arithmetic counted five parents from the
    file, walked out of site-packages entirely and landed on the virtualenv's
    ``Lib``. No source-tree test could see that.
    """
    site_packages = tmp_path / "Lib" / "site-packages"
    _plant_catalog(site_packages / "data" / "catalog" / "regions")

    resolved = _local_catalog_dirs_for(_router_at(site_packages), _ROUTER_MODULE, cwd=None)

    assert resolved == ((site_packages / "data" / "catalog" / "regions").resolve(),), (
        f"an installed layout resolved to {resolved}, not the catalogue directory sitting beside the "
        f"app package. This is the exact shape of the defect this test exists for."
    )


def test_the_catalogue_dir_resolves_in_a_source_checkout(tmp_path: Path) -> None:
    """The layout that worked before must keep working. Both, or neither."""
    repo = tmp_path / "repo"
    (repo / "backend").mkdir(parents=True)
    _plant_catalog(repo / "data" / "catalog" / "regions")

    resolved = _local_catalog_dirs_for(_router_at(repo / "backend"), _ROUTER_MODULE, cwd=None)

    assert resolved == ((repo / "data" / "catalog" / "regions").resolve(),), (
        f"a source checkout resolved to {resolved}, not the repo's catalogue directory. The fix for "
        f"the install layout must not cost the checkout the behaviour it already had."
    )


def test_a_directory_at_the_right_path_holding_nothing_is_not_accepted(tmp_path: Path) -> None:
    """Shape, not existence. Existence alone is how the original arithmetic lied.

    Accepting an empty directory is not a wrong read - the lookup is by exact
    file name and would simply miss - but it destroys the distinction the
    fallback message depends on. "We reach no catalogue at all" and "we reach one
    and this region is not in it" are different things to tell an operator, and
    only the shape check can tell them apart.
    """
    repo = tmp_path / "repo"
    (repo / "backend" / "data" / "catalog" / "regions").mkdir(parents=True)
    _plant_catalog(repo / "data" / "catalog" / "regions")

    resolved = _local_catalog_dirs_for(_router_at(repo / "backend"), _ROUTER_MODULE, cwd=None)

    assert resolved == ((repo / "data" / "catalog" / "regions").resolve(),), (
        f"resolved to {resolved}. An empty directory at the right path was accepted alongside the "
        f"real one, so the shape check is not doing its job."
    )


def test_no_catalogue_dir_anywhere_resolves_to_empty(tmp_path: Path) -> None:
    """An install carrying none must say so, not name a path that never existed."""
    resolved = _local_catalog_dirs_for(_router_at(tmp_path / "site-packages"), _ROUTER_MODULE, cwd=None)
    assert resolved == (), f"expected no directories for a layout carrying none, got {resolved}"


def test_every_reachable_directory_is_returned_not_only_the_first(tmp_path: Path) -> None:
    """A region missing from one directory is still found in another.

    The old code searched a tuple of two, so collapsing the resolver to a single
    best answer would quietly drop the operator's drop folder the moment an
    install also shipped a catalogue.
    """
    site_packages = tmp_path / "Lib" / "site-packages"
    _plant_catalog(site_packages / "data" / "catalog" / "regions", region="DE_BERLIN")
    work = tmp_path / "work"
    _plant_catalog(work / "data" / "catalog" / "regions", region="FR_PARIS")

    resolved = _local_catalog_dirs_for(_router_at(site_packages), _ROUTER_MODULE, cwd=work)

    assert resolved == (
        (site_packages / "data" / "catalog" / "regions").resolve(),
        (work / "data" / "catalog" / "regions").resolve(),
    ), (
        f"resolved to {resolved}. Both the shipped directory and the working-directory drop folder "
        f"carry a catalogue and both have to be searched, shipped one first."
    )


def test_the_resolver_reads_its_depth_from_the_module_name(tmp_path: Path) -> None:
    """Pin the derivation itself, which is what stops the arithmetic drifting again.

    Stated exactly, because the loose version of this claim is false, and the
    mutations that measured it are worth recording. The resolver tries the
    install root AND one directory above it, so a depth that is one level too
    SHALLOW is absorbed by that window: this test stays green, and only the
    source-checkout case notices. One level too DEEP is caught here, and so is
    the mutation that matters most - a depth written down as a literal that
    happens to be right for this module's real name and wrong for any other,
    which is the exact shape of the original defect and which nothing else in
    this file can see. That last one is why the synthetic module is nested two
    levels deeper rather than one.
    """
    site_packages = tmp_path / "site-packages"
    _plant_catalog(site_packages / "data" / "catalog" / "regions")

    deeper = site_packages / "app" / "modules" / "catalog" / "one" / "two" / "router.py"
    resolved = _local_catalog_dirs_for(deeper, "app.modules.catalog.one.two.router", cwd=None)

    assert resolved == ((site_packages / "data" / "catalog" / "regions").resolve(),), (
        f"a six-component module name resolved to {resolved}. The depth is supposed to come from the "
        f"module's own name rather than a written-down number of directory levels."
    )


def test_the_working_directory_is_read_per_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The second defect in the same tuple, and the one a frozen value cannot pass.

    ``Path.cwd()`` used to be evaluated at import. Calling the live resolver from
    two different directories and getting the same answer is what an import-time
    capture looks like from the outside, so the assertion is that the two answers
    differ - a property only per-call resolution can produce.
    """
    first = tmp_path / "first"
    _plant_catalog(first / "data" / "catalog" / "regions")
    second = tmp_path / "second"
    _plant_catalog(second / "data" / "catalog" / "regions")

    monkeypatch.chdir(first)
    from_first = _local_catalog_dirs()
    monkeypatch.chdir(second)
    from_second = _local_catalog_dirs()

    assert (first / "data" / "catalog" / "regions").resolve() in from_first, (
        f"the working directory {first} carries a catalogue and the resolver did not return it: {from_first}"
    )
    assert (second / "data" / "catalog" / "regions").resolve() in from_second, (
        f"the working directory {second} carries a catalogue and the resolver did not return it: {from_second}"
    )
    assert from_first != from_second, (
        f"the resolver gave the same answer {from_first} from two different working directories. "
        f"That is what a value captured once at import time looks like, which is the defect."
    )


def test_the_reader_consumes_the_resolver(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A correct resolver nothing calls would leave the defect exactly where it was.

    Drives the real ``_read_region_catalog_csv`` with the download refused, so
    the only way it can answer is through the catalogue directories the resolver
    hands it. The resolver is asked for a synthetic INSTALLED layout, because in
    this checkout the repository's own directory would otherwise answer and the
    install case would go untested again.
    """
    import app.modules.catalog.router as catalog_router

    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access attempted while a local catalogue was available")

    monkeypatch.setattr("urllib.request.urlopen", _refuse)
    monkeypatch.setattr(catalog_router, "_CATALOG_CACHE_DIR", tmp_path / "empty-cache")

    site_packages = tmp_path / "Lib" / "site-packages"
    planted = _plant_catalog(site_packages / "data" / "catalog" / "regions", region="DE_BERLIN")
    monkeypatch.setattr(
        catalog_router,
        "_local_catalog_dirs",
        lambda: _local_catalog_dirs_for(_router_at(site_packages), _ROUTER_MODULE, cwd=None),
    )

    raw, source = catalog_router._read_region_catalog_csv("DE_BERLIN", "DE___DDC_CWICR")

    assert source == "local", f"expected the installed catalogue directory to answer, got {source!r}"
    assert raw == planted.read_bytes(), "the reader returned bytes from somewhere other than the planted CSV"


def test_the_fallback_tells_the_two_situations_apart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """ "No catalogue anywhere" and "a catalogue without this region" are not the same.

    Whoever reads the log needs different things from them: the first says this
    installation carries no catalogue by design and the download is the only
    source, the second says the directory is there and this one region is not in
    it. The whole justification for the shape check is that it can tell them
    apart, so a single message covering both would make the check pointless
    while leaving every other test in this file green.
    """
    import app.modules.catalog.router as catalog_router

    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_kw: (_ for _ in ()).throw(OSError("no network")))
    monkeypatch.setattr(catalog_router, "_CATALOG_CACHE_DIR", tmp_path / "empty-cache")

    monkeypatch.setattr(catalog_router, "_local_catalog_dirs", lambda: ())
    with caplog.at_level("INFO", logger=catalog_router.__name__), pytest.raises(RuntimeError):
        catalog_router._read_region_catalog_csv("DE_BERLIN", "DE___DDC_CWICR")
    carries_none = caplog.text
    caplog.clear()

    populated = tmp_path / "site-packages" / "data" / "catalog" / "regions"
    _plant_catalog(populated, region="FR_PARIS")
    monkeypatch.setattr(catalog_router, "_local_catalog_dirs", lambda: (populated.resolve(),))
    with caplog.at_level("INFO", logger=catalog_router.__name__), pytest.raises(RuntimeError):
        catalog_router._read_region_catalog_csv("DE_BERLIN", "DE___DDC_CWICR")
    carries_other_regions = caplog.text

    assert "carries no catalog directory" in carries_none, (
        f"an installation reaching no catalogue directory logged {carries_none!r}, which does not "
        f"say so. That is the case where the operator has to be told the download is the only source."
    )
    assert str(populated) in carries_other_regions, (
        f"an installation whose catalogue directory simply lacks the region logged "
        f"{carries_other_regions!r}, which does not name the directory that was searched."
    )
    assert "carries no catalog directory" not in carries_other_regions, (
        "a populated catalogue directory was reported as no catalogue directory at all, so the two "
        "situations are indistinguishable in the log and the shape check buys nothing."
    )
