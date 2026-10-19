"""The converter release is pinned by tag and by digest, and every copy agrees.

The installer downloads one package per format from a GitHub release and the
desktop release workflow bakes the IFC package into the Windows installer. Two
facts keep that safe, and this file keeps them true:

* The pin is a release **tag** (``v2026.10.0``) plus the **SHA-256** of each
  package, not a branch name. A branch means every install fetches whatever the
  tip is at that moment; a tag plus a digest names one file, and the installer
  refuses anything else (``test_converter_install_integrity`` covers that side).
* The pin is written in more than one place - the backend, the workflow, and the
  manual-install link on the DWG takeoff page. Asserting only that each looks
  right would let them drift to two different releases and stay green, which
  would ship a machine carrying the IFC package of one release and the DWG
  package of another. So the equality is the assertion.

No network here. Everything is read off disk.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core import converter_source as cs
from app.modules.takeoff import router

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "desktop-release.yml"
DWG_PAGE_PATH = REPO_ROOT / "frontend" / "src" / "features" / "dwg-takeoff" / "DwgTakeoffPage.tsx"

_TAG = re.compile(r"\Av\d{4}\.\d{2}\.\d+\Z")
_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")

# The workflow lines the gate reads, for example:
#   OE_CONVERTER_TAG: ${{ vars.OE_CONVERTER_TAG || 'v2026.10.0' }}
#   OE_CONVERTER_IFC_SHA256: 5776b6bd...
_WORKFLOW_TAG = re.compile(
    r"^\s*OE_CONVERTER_TAG:\s*\$\{\{\s*vars\.OE_CONVERTER_TAG\s*\|\|\s*'([^']*)'\s*\}\}\s*$", re.MULTILINE
)
_WORKFLOW_REPO = re.compile(
    r"^\s*OE_CONVERTER_REPO:\s*\$\{\{\s*vars\.OE_CONVERTER_REPO\s*\|\|\s*'([^']*)'\s*\}\}\s*$", re.MULTILINE
)
_WORKFLOW_ASSET = re.compile(r"^\s*OE_CONVERTER_IFC_ASSET:\s*(\S+)\s*$", re.MULTILINE)
_WORKFLOW_SHA = re.compile(r"^\s*OE_CONVERTER_IFC_SHA256:\s*(\S+)\s*$", re.MULTILINE)

_FRONTEND_LINK = re.compile(r"github\.com/([^/\s'\"]+/[^/\s'\"]+)/releases/tag/([^/\s'\"]+)")


def _workflow_text() -> str:
    """The workflow, failing loudly if it cannot be found.

    A hard failure and not a skip: a gate that skips when its input is missing
    reports the same green as one that passed, and the input going missing - a
    renamed workflow, a rewritten env block - is exactly the change that should
    wake somebody.
    """
    if not WORKFLOW_PATH.is_file():
        pytest.fail(f"{WORKFLOW_PATH} does not exist; point this test at the workflow's new path, do not delete it.")
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _only(pattern: re.Pattern[str], text: str, what: str) -> str:
    found = pattern.findall(text)
    if not found:
        pytest.fail(f"Could not find {what} in {WORKFLOW_PATH.name}. The bundling step or its env block was rewritten.")
    if len(set(found)) > 1:
        pytest.fail(f"{WORKFLOW_PATH.name} sets {what} to more than one value: {sorted(set(found))}")
    return found[0]


# ── The pin itself ────────────────────────────────────────────────────────


def test_the_converter_tag_is_a_release_tag() -> None:
    assert _TAG.match(cs.DEFAULT_CONVERTER_TAG), (
        f"DEFAULT_CONVERTER_TAG is {cs.DEFAULT_CONVERTER_TAG!r}; a branch name would make every install fetch an unknown tree."
    )


def test_every_package_pins_a_full_sha256_and_a_versioned_asset() -> None:
    assert set(cs.PACKAGES) == {"rvt", "ifc", "dwg"}, "DGN is discontinued in this release generation"
    for fmt, pkg in cs.PACKAGES.items():
        assert _SHA256.match(pkg.sha256), f"{fmt}: {pkg.sha256!r} is not a lowercase hex SHA-256"
        assert pkg.version.split("-")[0] in pkg.asset, (
            f"{fmt}: asset {pkg.asset!r} does not carry version {pkg.version}"
        )
        assert pkg.asset.endswith("-portable.zip")
        assert pkg.size_bytes > 0


def test_the_router_uses_the_pinned_tag_by_default() -> None:
    assert router._DDC_DEFAULT_TAG == cs.DEFAULT_CONVERTER_TAG


def test_the_tag_can_be_overridden_but_an_empty_value_is_not_an_override() -> None:
    assert cs.resolve_converter_tag({}) == cs.DEFAULT_CONVERTER_TAG
    assert cs.resolve_converter_tag({"OE_CONVERTER_TAG": ""}) == cs.DEFAULT_CONVERTER_TAG
    assert cs.resolve_converter_tag({"OE_CONVERTER_TAG": "v2027.01.0"}) == "v2027.01.0"
    assert cs.resolve_converter_repo({}) == cs.DEFAULT_CONVERTER_REPO
    assert cs.resolve_converter_repo({"OE_CONVERTER_REPO": "me/fork"}) == "me/fork"


def test_asset_urls_point_at_the_release_download() -> None:
    url = cs.release_asset_url("x.zip")
    assert url == f"https://github.com/{cs.DEFAULT_CONVERTER_REPO}/releases/download/{cs.DEFAULT_CONVERTER_TAG}/x.zip"


# ── The copies agree ──────────────────────────────────────────────────────


def test_the_release_workflow_pins_the_same_release_and_package_as_the_backend() -> None:
    """The workflow bakes the IFC package into the Windows installer while the
    backend downloads rvt/dwg at runtime; they must come from the same release."""
    text = _workflow_text()
    ifc = cs.PACKAGES["ifc"]
    assert _only(_WORKFLOW_TAG, text, "the OE_CONVERTER_TAG default") == cs.DEFAULT_CONVERTER_TAG
    assert _only(_WORKFLOW_REPO, text, "the OE_CONVERTER_REPO default") == cs.DEFAULT_CONVERTER_REPO
    assert _only(_WORKFLOW_ASSET, text, "OE_CONVERTER_IFC_ASSET") == ifc.asset
    assert _only(_WORKFLOW_SHA, text, "OE_CONVERTER_IFC_SHA256") == ifc.sha256


def test_the_workflow_bundles_from_a_release_asset_and_checks_the_digest() -> None:
    text = _workflow_text()
    assert "releases/download/$tag" in text
    assert "Get-FileHash -Algorithm SHA256" in text
    assert "SHA256SUMS.txt" in text


def test_the_manual_install_link_on_the_dwg_page_names_the_pinned_release() -> None:
    """The manual route must hand out the build the Install button fetches."""
    if not DWG_PAGE_PATH.is_file():
        pytest.fail(f"{DWG_PAGE_PATH} does not exist; point this test at the page's new path, do not delete it.")
    links = _FRONTEND_LINK.findall(DWG_PAGE_PATH.read_text(encoding="utf-8"))
    assert links, "the DWG takeoff page has no manual-install link to a release tag any more"
    assert {(repo, tag) for repo, tag in links} == {(cs.DEFAULT_CONVERTER_REPO, cs.DEFAULT_CONVERTER_TAG)}
