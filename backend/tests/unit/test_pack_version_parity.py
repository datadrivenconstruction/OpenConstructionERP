# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A pack carries its version twice and nothing kept the two in step.

``pyproject.toml`` holds the version the wheel is built and published under.
``manifest.py`` holds ``pack_version``, which is what the application reports
in the pack list, in the install audit record and over the API. They are two
literals for one fact, and every pack in the tree had them equal by convention
alone.

Convention held until it did not: raising the uk-jct manifest to 0.3.0 for a
substantial rewrite left the wheel at 0.2.0, so an installed pack would have
reported a version its own distribution never carried. That is the kind of
drift nobody notices from the inside, because both numbers look plausible on
their own and neither file mentions the other.

Pure filesystem work, no database and no imports from ``app``, so it cannot be
skipped by a database marker.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# backend/tests/unit/<this file> -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_PACKS_DIR = _REPO_ROOT / "packs"

_PYPROJECT_VERSION_RX = re.compile(r"""^\s*version\s*=\s*["'](?P<version>[^"']+)["']""", re.MULTILINE)
_MANIFEST_VERSION_RX = re.compile(r"""pack_version\s*=\s*["'](?P<version>[^"']+)["']""")

#: Packs with a ``pyproject.toml`` and no manifest at all. ``aus-nzs`` was
#: split into ``aus`` and ``nzs``; what is left is a stub carrying a
#: DEPRECATED.txt, and it has no ``pack_version`` to disagree with. Named
#: rather than skipped by a wildcard so a pack that loses its manifest by
#: accident still fails.
_NO_MANIFEST = {"aus-nzs"}


def _pack_dirs() -> list[Path]:
    return sorted(p.parent for p in _PACKS_DIR.glob("*/pyproject.toml"))


def _manifest_path(pack: Path) -> Path | None:
    return next(iter(sorted((pack / "src").glob("*/manifest.py"))), None)


def test_the_sweep_reaches_every_pack() -> None:
    """A sweep that reached no pack is not a clean sweep.

    The count is asserted as a floor rather than an equality so adding a pack
    does not fail an unrelated test, but a glob that silently stops matching
    does.
    """
    packs = _pack_dirs()
    assert len(packs) >= 20, f"only {len(packs)} packs found under {_PACKS_DIR}"
    with_manifest = [p for p in packs if _manifest_path(p) is not None]
    assert len(with_manifest) == len(packs) - len(_NO_MANIFEST), (
        "the set of packs shipping no manifest changed; expected only "
        f"{sorted(_NO_MANIFEST)}, found {sorted(p.name for p in packs if _manifest_path(p) is None)}"
    )


@pytest.mark.parametrize("pack", _pack_dirs(), ids=lambda p: p.name)
def test_pyproject_and_manifest_state_the_same_version(pack: Path) -> None:
    """The published wheel and the running application agree on the version."""
    pyproject = (pack / "pyproject.toml").read_text(encoding="utf-8")
    wheel_match = _PYPROJECT_VERSION_RX.search(pyproject)
    assert wheel_match, f"{pack.name}: no version in pyproject.toml"

    manifest = _manifest_path(pack)
    if manifest is None:
        assert pack.name in _NO_MANIFEST, f"{pack.name} ships no manifest.py and is not on the known list"
        return

    manifest_match = _MANIFEST_VERSION_RX.search(manifest.read_text(encoding="utf-8"))
    assert manifest_match, f"{pack.name}: no pack_version in manifest.py"

    wheel = wheel_match.group("version")
    declared = manifest_match.group("version")
    assert wheel == declared, (
        f"{pack.name} publishes {wheel} and reports {declared}. Raise both, or the version a "
        "user sees in the pack list is not the version they installed."
    )
