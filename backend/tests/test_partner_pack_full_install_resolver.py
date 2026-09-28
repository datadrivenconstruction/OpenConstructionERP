"""Pure-logic unit tests for the partner-pack full-install CWICR resolver.

These exercise only the §5.1 slug → ``load-cwicr`` db_id resolution and the
demo install-list ordering. No database, no embedding model, no HTTP — the
functions under test read in-memory registries only.
"""

from __future__ import annotations

import pytest

from app.core.partner_pack.full_install import (
    _build_city_index,
    _demo_install_list,
    _pack_country,
    resolve_cwicr_db_id,
)


class TestCityIndex:
    def test_index_drops_country_prefix(self) -> None:
        idx = _build_city_index()
        # ``DE_BERLIN`` -> token ``berlin`` -> back to the full db_id.
        assert idx["berlin"] == "DE_BERLIN"
        assert idx["toronto"] == "CA_TORONTO"
        # National catalogues keep their suffix as the token.
        assert idx["usd"] == "USA_USD"
        # Multi-word city tokens stay joined (no underscores in the suffix).
        assert idx["saopaulo"] == "PT_SAOPAULO"

    def test_the_index_only_answers_with_bases_the_loader_can_load(self) -> None:
        """A city token must never resolve to a market id the loader has no file for.

        The index used to be built from the currency table, which also lists
        market ids (``AE_DUBAI``, ``IN_MUMBAI``, ``JP_TOKYO``, ``GB_LONDON``,
        ...) that name a price level, not a downloadable base. Where a market
        and a base shared a city token the market won, so ten packs resolved to
        an id ``load_cwicr_region`` answers with "no GitHub mapping", and the
        install reported the cost step as skipped.
        """
        from app.modules.costs.router import _GITHUB_CWICR_FILES

        unloadable = {token: db for token, db in _build_city_index().items() if db not in _GITHUB_CWICR_FILES}
        assert not unloadable, f"city tokens resolving to ids with no base file: {unloadable}"
        from app.core.partner_pack.full_install import _CITY_TOKEN_ALIASES

        bad_alias = {t: db for t, db in _CITY_TOKEN_ALIASES.items() if db not in _GITHUB_CWICR_FILES}
        assert not bad_alias, f"aliases naming ids with no base file: {bad_alias}"


class TestResolveCwicrDbId:
    @pytest.mark.parametrize(
        ("slug", "expected"),
        [
            ("cwicr-de-berlin", "DE_BERLIN"),
            ("cwicr-eng-toronto", "CA_TORONTO"),
            ("cwicr-eng-sydney", "AU_SYDNEY"),
            ("cwicr-eng-auckland", "NZ_AUCKLAND"),
            ("cwicr-hi-mumbai", "HI_MUMBAI"),
            ("cwicr-ar-dubai", "AR_DUBAI"),
            ("cwicr-ja-tokyo", "JA_TOKYO"),
            ("cwicr-ko-seoul", "KO_SEOUL"),
            ("cwicr-pt-saopaulo", "PT_SAOPAULO"),
            ("cwicr-usa-usd", "USA_USD"),
        ],
    )
    def test_native_city_match(self, slug: str, expected: str) -> None:
        assert resolve_cwicr_db_id(slug) == expected

    @pytest.mark.parametrize(
        ("slug", "expected"),
        [
            # The UK base is published under its currency, UK_GBP, and it is
            # the London price level; both spellings a pack uses reach it.
            ("cwicr-uk-gbp", "UK_GBP"),
            ("cwicr-eng-london", "UK_GBP"),
            # Mexico's base is published as Mexico City.
            ("cwicr-es-mexico", "MX_MEXICOCITY"),
            # Spain's base is published under Barcelona; Madrid is only a market.
            ("cwicr-es-madrid", "SP_BARCELONA"),
        ],
    )
    def test_alias_match(self, slug: str, expected: str) -> None:
        assert resolve_cwicr_db_id(slug) == expected

    @pytest.mark.parametrize(
        "slug",
        [
            "cwicr-fra-montreal",  # no Montreal CWICR data yet
            "cwicr-eng-wellington",
            "cwicr-eng-christchurch",
            "cwicr-de-duesseldorf",
            "cwicr-eng-melbourne",
            "cwicr-eng-bangalore",
            # Markets with a price level and no base of their own.
            "cwicr-eng-riyadh",
            "cwicr-de-munich",
            "cwicr-de-muenchen",
            "",
        ],
    )
    def test_unresolved_returns_none(self, slug: str) -> None:
        assert resolve_cwicr_db_id(slug) is None

    def test_lang_token_is_ignored(self) -> None:
        # ``eng`` and ``fra`` both mean Canada — resolution keys off the city,
        # never the language token.
        assert resolve_cwicr_db_id("cwicr-eng-toronto") == "CA_TORONTO"
        assert resolve_cwicr_db_id("cwicr-fra-toronto") == "CA_TORONTO"


class TestDemoOrdering:
    def test_pack_country_from_flagship(self) -> None:
        # batimatech-ca's flagship is office-montreal (country CA).
        assert _pack_country("batimatech-ca") == "CA"
        assert _pack_country("uk-jct") == "GB"
        assert _pack_country("us-costdata") == "US"

    def test_pack_country_unknown_pack(self) -> None:
        assert _pack_country("does-not-exist") is None

    def test_install_list_flagship_first_and_truncated(self) -> None:
        ids = _demo_install_list("uk-jct", 2)
        assert ids  # at least the flagship
        # uk-jct flagship is commercial-london; it must lead.
        assert ids[0] == "commercial-london"
        assert len(ids) <= 2
        assert len(ids) == len(set(ids))  # de-duplicated

    def test_install_list_zero_count(self) -> None:
        assert _demo_install_list("uk-jct", 0) == []

    def test_install_list_unknown_pack(self) -> None:
        assert _demo_install_list("does-not-exist", 2) == []


def test_every_shipped_pack_region_resolves_to_a_loadable_base_or_to_nothing() -> None:
    """The property the one-click cost step depends on, asked of the real packs.

    ``None`` is an honest answer (the step reports the slug as skipped); an id
    the loader cannot load is not, it fails at download time.
    """
    import importlib.util
    import pathlib
    import sys

    from app.modules.costs.router import _GITHUB_CWICR_FILES

    packs = pathlib.Path(__file__).resolve().parents[2] / "packs"
    wrong: dict[str, str] = {}
    seen = 0
    for path in sorted(packs.glob("*/src/openconstructionerp_*/manifest.py")):
        name = f"_resolver_manifest_{path.parts[-2]}"
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        for slug in module.MANIFEST.cwicr_regions:
            seen += 1
            db_id = resolve_cwicr_db_id(slug)
            if db_id is not None and db_id not in _GITHUB_CWICR_FILES:
                wrong[f"{module.MANIFEST.slug}:{slug}"] = db_id
    assert seen > 30, f"read only {seen} region slugs from {packs}"
    assert not wrong, f"pack regions resolving to ids the loader cannot load: {wrong}"
