#!/usr/bin/env python3
"""Every font binary we ship carries its licence text into the artefact.

Fonts are the one dependency class our attribution pipeline is structurally
blind to. ``pip-licenses`` and ``license-checker`` both enumerate *installed
packages*; a font committed into our own source tree is not a package and has
no metadata to enumerate, so it can never appear in either output no matter how
long it ships. That is not a bug someone introduced, it is a blind spot by
construction, and it swallowed DejaVu, Instrument Serif and Plus Jakarta Sans
without a single check going red.

The obligations are real and they are not the same obligation:

* The Bitstream Vera Fonts License requires "The above copyright and trademark
  notices and this permission notice shall be included in all copies of one or
  more of the Font Software typefaces." It binds the *trademark* notice too,
  not only the copyright, which is why a Bitstream row cannot be reduced to a
  copyright line.
* The Arev Fonts License, which governs glyphs imported into the same DejaVu
  binaries, carries its own separately binding notice clause under a different
  rightsholder. ``LICENSE_DEJAVU`` is three statements, not one licence, and an
  inventory row reading "DejaVu, Bitstream Vera Fonts License" loses two.
* SIL OFL 1.1 clause 2 permits bundling "provided that each copy contains the
  above copyright notice and this license", and explicitly blesses shipping it
  as a stand-alone text file, which is the mechanism we use.

All three are satisfied today by a licence file travelling in the artefact
beside the fonts. This guard exists so that stays true for a font added next
year by somebody who never read any of the above.

WHAT THIS CHECKS, AND WHY IT IS NOT "a licence file sits next to the font"

That weaker check is the one this codebase keeps getting bitten by, and here it
would reintroduce the exact failure it exists to prevent. ``backend/pyproject
.toml`` carries ``exclude = ["**/_*.md", "**/_*.txt", ...]``. ``LICENSE_DEJAVU``
reaches the wheel only because it happens to have no extension. A future
licence arriving beside a new face as ``_LICENSE.txt`` would sit right next to
its font, pass a tree-presence check, and be silently dropped from the wheel.

So the assertion is about the packaged result rather than the tree: each
resolved licence path must survive the wheel's own exclude patterns, read out
of ``pyproject.toml`` at run time so this updates itself when someone edits
that list. On the frontend side the licence must live under ``public/``, which
is the directory Vite copies verbatim into ``dist``.

It also asserts every family appears in ``NOTICE``. ``NOTICE`` is hand
maintained and presents itself as a complete inventory, so nothing generated
can keep it honest; this check is what makes the one hand edit a one-time cost
rather than a recurring one.

TWO MODES, ONE INVENTORY

``--markdown`` emits the ``## Bundled assets`` section that
``.github/workflows/sbom-and-licenses.yml`` appends to docs/legal/THIRD_PARTY_LICENSES.md.
The gate and the generator therefore build their inventory with the same code
and cannot disagree about what we ship. A separate generator that walked the
tree its own way would be a second source of truth, and the point of the whole
exercise is that there is one.

The emitted section carries the licence *text*, not a licence label. Neither
frontend family declares a Reserved Font Name today; the next OFL font somebody
adds may, and a label would drop that.

WHAT IT CANNOT SEE

A font fetched at runtime, a font inside another package's wheel, and a font
embedded in a binary blob are all invisible here. This walks tracked source.

    python scripts/check_bundled_font_licences.py
    python scripts/check_bundled_font_licences.py --markdown
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FONT_SUFFIXES = {".ttf", ".otf", ".ttc", ".woff", ".woff2"}

# Where a shipped font may live, and how its licence reaches the artefact.
# ``public`` marks a root whose licence files must sit under a directory Vite
# copies verbatim; ``wheel`` marks one whose licence files must survive the
# wheel exclude patterns. A new asset root is one line here.
# The third root carries fonts that no artefact ships: they are committed so the
# build scripts render the same picture on anyone's machine. The obligation is
# still real, because publishing the repository publishes the binary, but the
# "does it survive the wheel exclude" and "is it under public/" assertions have
# nothing to bite on, so the channel is named and those two branches skip it.
# Without this root the guard is blind to a whole directory of fonts, which is
# the exact blind spot its own docstring is about.
ASSET_ROOTS = (
    ("backend/app", "wheel"),
    ("frontend/public", "public"),
    ("scripts/assets", "repo"),
)

# A licence file, by name. Deliberately broad: the point is to find the text
# wherever a font vendor happened to put it, not to impose our own convention
# on files we did not write.
LICENCE_NAMES = re.compile(
    r"^(.*(licen[cs]e|copying|ofl).*|licen[cs]e|copying)$",
    re.IGNORECASE,
)

# A copyright *holder* line, as opposed to licence prose that merely contains
# the word. Anchoring on a four-digit year is what separates them, and it was
# checked against the real files rather than assumed: it catches
# LICENSE_DEJAVU lines 7 and 54 and OFL line 1, and rejects both section
# headers plus all seven OFL body mentions ("the Copyright Holder(s)", "the
# above copyright notice") which carry no year.
HOLDER = re.compile(r"copyright", re.IGNORECASE)
YEAR = re.compile(r"\b(19|20)\d{2}\b")


def _fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)


def wheel_exclude_patterns() -> list[str]:
    """The wheel's own exclude list, read at run time rather than copied here.

    Copying the patterns into this file would mean a future edit to
    pyproject.toml silently stops being enforced, which is the same class of
    drift the guard exists to catch.
    """
    with (ROOT / "backend" / "pyproject.toml").open("rb") as handle:
        data = tomllib.load(handle)
    targets = data.get("tool", {}).get("hatch", {}).get("build", {}).get("targets", {})
    return list(targets.get("wheel", {}).get("exclude", []))


def survives_wheel_exclude(relative_to_backend: str, patterns: list[str]) -> str | None:
    """Return the pattern that would drop this path from the wheel, or None.

    ``fnmatchcase`` rather than ``fnmatch``. The latter normalises case through
    ``os.path.normcase``, which does nothing on Linux and lowercases on
    Windows, so a ``_LICENSE.TXT`` would fail this guard on a developer's
    machine and pass it in CI. A gate that returns two verdicts for one tree is
    worse than no gate, because the disagreement is invisible until someone
    compares. This approximates hatchling's own glob handling, which remains
    the authority on what the wheel actually contains.
    """
    for pattern in patterns:
        if fnmatch.fnmatchcase(relative_to_backend, pattern):
            return pattern
        # ``**/_*.txt`` has to match a bare basename too: fnmatch treats the
        # path as a flat string, so a file directly under the package root
        # would otherwise slip past a pattern written with a leading ``**/``.
        if pattern.startswith("**/") and fnmatch.fnmatchcase(Path(relative_to_backend).name, pattern[3:]):
            return pattern
    return None


def _closest(font: Path, candidates: list[Path]) -> Path | None:
    """Pick the licence governing this font when a directory holds several.

    Our own webfonts directory forces this and is why the naive version was
    caught: eight font files beside two OFL texts. Taking the first match
    alphabetically filed all four Plus Jakarta Sans faces under the Instrument
    Serif licence, crediting the wrong authors in a legal document, and no
    count in the output looked wrong. Longest shared filename prefix resolves
    it. Several candidates sharing nothing with the font name is genuine
    ambiguity, and it is reported rather than guessed at.
    """
    if len(candidates) == 1:
        return candidates[0]
    stem = font.stem.lower()

    def shared(candidate: Path) -> int:
        other = candidate.stem.lower()
        size = 0
        while size < min(len(stem), len(other)) and stem[size] == other[size]:
            size += 1
        return size

    ranked = sorted(candidates, key=shared, reverse=True)
    return None if shared(ranked[0]) == 0 else ranked[0]


def find_licence(font: Path) -> Path | None:
    """Resolve the licence text governing one font file.

    Walks up from the font, checking each ancestor directory and any
    ``licenses``/``licence`` subdirectory of it. The two-level form is not
    hypothetical: our own webfonts sit in ``fonts/webfonts/`` while their OFL
    texts sit in ``fonts/licenses/``, so a same-directory-only rule would
    report both frontend families as unlicensed.
    """
    for parent in list(font.parents):
        if not str(parent).startswith(str(ROOT)):
            break
        pool = [p for p in sorted(parent.iterdir()) if p.is_file()]
        for holder in ("licenses", "licences", "license", "licence"):
            nested = parent / holder
            if nested.is_dir():
                pool.extend(p for p in sorted(nested.iterdir()) if p.is_file())
        found = [p for p in pool if LICENCE_NAMES.match(p.name) and p.suffix.lower() not in FONT_SUFFIXES]
        if found:
            return _closest(font, found)
        if parent == ROOT:
            break
    return None


def holders(licence: Path) -> list[str]:
    """Every distinct rightsholder named in the licence text.

    Returns a list because ``LICENSE_DEJAVU`` names two under separately
    binding notice clauses, and an inventory that reports one is wrong about
    who has to be credited.
    """
    found: list[str] = []
    for line in licence.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if HOLDER.search(stripped) and YEAR.search(stripped) and stripped not in found:
            found.append(stripped)
    return found


def collect() -> tuple[dict[Path, list[Path]], list[Path]]:
    """Group every shipped font by the licence file governing it.

    Grouping by licence rather than by guessed family name is deliberate: a
    family name has to be inferred from filenames and would be wrong for at
    least one of the three sets we ship today, whereas the governing licence is
    a fact on disk. The second return value is the fonts with no licence at
    all, which is the condition this guard exists to make impossible.
    """
    groups: dict[Path, list[Path]] = {}
    orphans: list[Path] = []
    for root_name, _channel in ASSET_ROOTS:
        root = ROOT / root_name
        if not root.is_dir():
            continue
        for font in sorted(root.rglob("*")):
            if not font.is_file() or font.suffix.lower() not in FONT_SUFFIXES:
                continue
            licence = find_licence(font)
            if licence is None:
                orphans.append(font)
            else:
                groups.setdefault(licence, []).append(font)
    return groups, orphans


def channel_for(path: Path) -> str:
    relative = path.relative_to(ROOT).as_posix()
    for root_name, channel in ASSET_ROOTS:
        if relative.startswith(root_name + "/"):
            return channel
    return "wheel"


def check() -> int:
    groups, orphans = collect()
    failures = 0

    if not groups and not orphans:
        _fail(
            "no font files found under any asset root. Either the roots in "
            "ASSET_ROOTS are stale or the fonts moved; both mean this guard is "
            "now checking nothing, which is worse than failing."
        )
        return 1

    for font in orphans:
        _fail(
            f"{font.relative_to(ROOT).as_posix()} has no licence text this guard can "
            "resolve: either none sits anywhere above it, or several do and none "
            "shares a name with the font, which makes attribution a guess. Put the "
            "vendor's licence beside the font, or in a sibling licenses/ directory "
            "under a filename carrying the family name."
        )
        failures += 1

    patterns = wheel_exclude_patterns()
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8", errors="replace").lower()

    for licence, fonts in sorted(groups.items()):
        relative = licence.relative_to(ROOT).as_posix()
        channel = channel_for(licence)

        if channel == "wheel":
            # The path the wheel walk sees is relative to backend/, because
            # that is the directory hatchling packages from.
            inside_backend = licence.relative_to(ROOT / "backend").as_posix()
            dropped = survives_wheel_exclude(inside_backend, patterns)
            if dropped:
                _fail(
                    f"{relative} governs {len(fonts)} shipped font(s) but matches the "
                    f"wheel exclude pattern {dropped!r} in backend/pyproject.toml, so it "
                    "is dropped from the wheel and the installer. The fonts would ship "
                    "without their licence text. Rename it so it survives the walk."
                )
                failures += 1
        elif channel == "public" and "/public/" not in f"/{relative}":
            _fail(
                f"{relative} governs {len(fonts)} shipped font(s) but does not live "
                "under frontend/public/, which is the only directory Vite copies "
                "verbatim into dist. It would not reach the built frontend."
            )
            failures += 1

        if not holders(licence):
            _fail(
                f"{relative} names no copyright holder this guard can find (a line "
                "carrying both 'copyright' and a four-digit year). Attribution "
                "cannot be generated from it."
            )
            failures += 1

        if licence.name.lower() not in notice:
            _fail(
                f"NOTICE does not mention {licence.name}, which governs "
                f"{len(fonts)} font file(s) we ship, first being "
                f"{fonts[0].relative_to(ROOT).as_posix()}. NOTICE presents itself as a "
                "complete inventory, so add an entry naming the font and this file."
            )
            failures += 1

    if failures:
        print(
            f"\n{failures} problem(s) across {len(groups)} bundled font licence(s).",
            file=sys.stderr,
        )
        return 1

    total = sum(len(f) for f in groups.values())
    print(f"OK: {total} bundled font file(s) under {len(groups)} licence(s), all attributed.")
    return 0


def markdown() -> int:
    groups, orphans = collect()
    if orphans:
        _fail("refusing to generate a section while fonts have no licence text.")
        return 1

    out: list[str] = [
        "## Bundled assets",
        "",
        "Font binaries committed into this repository and shipped inside the wheel and",
        "the desktop installer. They are files rather than packages, so no dependency",
        "scanner can enumerate them and they appear in neither section above. Each",
        "licence text below also travels in the artefact beside the fonts it governs.",
        "",
    ]
    for licence, fonts in sorted(groups.items()):
        out.append(f"### {licence.relative_to(ROOT).as_posix()}")
        out.append("")
        out.append("Governs:")
        out.append("")
        for font in fonts:
            out.append(f"- `{font.relative_to(ROOT).as_posix()}`")
        out.append("")
        out.append("Named rightsholders:")
        out.append("")
        for holder in holders(licence):
            out.append(f"- {holder}")
        out.append("")
        out.append("<details><summary>Full licence text</summary>")
        out.append("")
        out.append("```")
        out.append(licence.read_text(encoding="utf-8", errors="replace").rstrip())
        out.append("```")
        out.append("")
        out.append("</details>")
        out.append("")
    print("\n".join(out))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--markdown",
        action="store_true",
        help="emit the docs/legal/THIRD_PARTY_LICENSES.md section instead of checking",
    )
    args = parser.parse_args()
    return markdown() if args.markdown else check()


if __name__ == "__main__":
    raise SystemExit(main())
