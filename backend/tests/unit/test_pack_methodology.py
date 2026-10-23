# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pack -> estimating-methodology wiring (pure, no database).

Validates the contract added so applying a country/region pack opens its demo
project (and any project created while the pack is active) with the partner's
estimating methodology instead of the flat international default:

  * the ``default_methodology`` manifest field round-trips through
    ``PartnerPackManifest`` and ``to_public_dict`` and defaults to ``None``;
  * every in-repo pack that declares a methodology points at a slug that
    actually exists in the built-in template catalogue (catches typos before a
    pack ships a dangling slug that would be silently skipped at apply time);
  * the real on-disk pack manifests carry the expected slug.

Everything here imports only the pure manifest schema and the pure templates
catalogue (no SQLAlchemy / FastAPI), so it runs standalone on Python 3.11.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.core.partner_pack.manifest import PartnerPackManifest
from app.modules.methodology import templates as templates_mod

# Repo root is three levels above this file's package (backend/tests/unit).
_REPO_ROOT = Path(__file__).resolve().parents[3]

# pack slug -> (package directory under packs/<slug>/src, expected methodology slug)
PACK_METHODOLOGY: dict[str, tuple[str, str]] = {
    "us-costdata": ("openconstructionerp_us_costdata", "united_states"),
    "uk-jct": ("openconstructionerp_uk_jct", "united_kingdom"),
    "india-cpwd": ("openconstructionerp_india_cpwd", "india"),
    "bimhessen-de": ("openconstructionerp_bimhessen_de", "germany"),
    "aus": ("openconstructionerp_aus", "australia"),
    "retail-grocery-dach": ("openconstructionerp_retail_grocery_dach", "germany"),
    "mexico-mx": ("openconstructionerp_mexico_mx", "mexico"),
    "pakistan-pk": ("openconstructionerp_pakistan_pk", "pakistan"),
}


def _load_pack_manifest(pack_slug: str, package: str) -> PartnerPackManifest:
    """Import the real on-disk ``MANIFEST`` of a pack without installing it."""
    path = _REPO_ROOT / "packs" / pack_slug / "src" / package / "manifest.py"
    spec = importlib.util.spec_from_file_location(f"_packtest_{package}", path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MANIFEST


class TestManifestField:
    def test_default_methodology_defaults_to_none(self) -> None:
        m = PartnerPackManifest(slug="bare-pack", partner_name="Bare")
        assert m.default_methodology is None
        assert m.to_public_dict()["default_methodology"] is None

    def test_default_methodology_roundtrips(self) -> None:
        m = PartnerPackManifest(
            slug="some-pack",
            partner_name="Some Co",
            default_methodology="germany",
        )
        assert m.default_methodology == "germany"
        assert m.to_public_dict()["default_methodology"] == "germany"

    def test_underscore_slug_is_accepted(self) -> None:
        # Methodology slugs are snake_case (unlike hyphenated pack slugs); the
        # field must not reject them.
        m = PartnerPackManifest(
            slug="rail-pack",
            partner_name="Rail Co",
            default_methodology="railway_infrastructure",
        )
        assert m.default_methodology == "railway_infrastructure"


class TestPackMethodologySlugsAreReal:
    @pytest.mark.parametrize(("pack_slug", "spec"), list(PACK_METHODOLOGY.items()))
    def test_expected_slug_is_a_builtin_template(self, pack_slug: str, spec: tuple[str, str]) -> None:
        _package, methodology_slug = spec
        assert methodology_slug in templates_mod.TEMPLATES_BY_SLUG, (
            f"pack '{pack_slug}' points at methodology '{methodology_slug}' "
            "which is not a built-in template; it would be silently skipped at apply time"
        )


class TestRealManifestsCarryMethodology:
    @pytest.mark.parametrize(("pack_slug", "spec"), list(PACK_METHODOLOGY.items()))
    def test_on_disk_manifest_declares_expected_methodology(self, pack_slug: str, spec: tuple[str, str]) -> None:
        package, methodology_slug = spec
        manifest = _load_pack_manifest(pack_slug, package)
        assert manifest.slug == pack_slug
        assert manifest.default_methodology == methodology_slug
