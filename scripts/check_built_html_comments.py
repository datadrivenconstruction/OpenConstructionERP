#!/usr/bin/env python3
# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""No page this product serves may carry a comment, and the licence notice must.

An owner installing this product opened View Source on the sign-in page of a fresh
install and read a note to a developer:

    <!-- Analytics is injected by the VPS deployment script (not in the repo) -->

Two things were wrong with that line and they pull in opposite directions, which is
why this check has two halves.

The first is what the owner saw. A shipped page is not a place to leave a note about
a deployment, and this one named a script that edits the page after it ships. Nobody
reading the product should be told that analytics may be injected into it by
something outside the repository; nobody reading the repository can verify a claim
about a script that is not in it. Every other comment in the served pages is the
same kind of thing - a section label, a pointer to a test file, an explanation of a
button - written for a developer, served to a reader, and stripped by nothing: Vite
minifies the JavaScript and the CSS and leaves the HTML of ``public/`` exactly as it
is on disk.

The second half is the trap in "just delete the comments". One of them was the
attribution notice AGPL-3.0 section 5 asks a modified version to keep. A check that
only counted comments would pass on a page whose licence notice had been deleted,
which is the one way to satisfy this requirement by breaking a larger one. So the
same pass asserts the notice is present as document data - a ``rel="license"`` link
and the two ``meta`` elements that name the licence and the upstream project - and
fails a page that lost it.

The population is the built pages when a build exists, because that is what a
browser receives, and the sources otherwise, so a checkout that has not been built
is still judged on what it would ship. ``--dist-only`` insists on the built pages
and refuses to fall back: in CI it runs after the build, and reading the sources
there would pass on a job that produced nothing.

Standard library only. This runs in the frontend job beside ``npm``, on three
operating systems, before any Python dependency of the backend is installed.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "frontend" / "dist"
SHELL_SOURCES = (ROOT / "frontend" / "index.html",)
PUBLIC_SOURCES = ROOT / "frontend" / "public"

#: What the application shell must still carry after its comments are gone.
#:
#: The first three are the attribution AGPL-3.0 section 5 requires a modified
#: version to keep, stated as document data: the licence the product is under, a
#: link to the text served with it, and the upstream project it is based on. The
#: last is the product's own name, which is what makes the notice about this
#: product rather than a stray sentence.
SHELL_NEEDLES: tuple[str, ...] = (
    'rel="license"',
    'name="license"',
    "AGPL-3.0-or-later",
    'name="source"',
    "OpenConstructionERP",
    "DataDrivenConstruction",
)

#: A terminated comment, and the opening of one that was never closed.
COMMENT = re.compile(r"<!--.*?-->", re.S)
OPENING = re.compile(r"<!--")
CLOSING = re.compile(r"-->")


def _describe(root: Path) -> str:
    """Where a population came from, in words a reader can act on."""
    try:
        return str(root.relative_to(ROOT))
    except ValueError:
        # A selftest population lives in a temporary directory outside the checkout,
        # and crashing on it would turn a refusal into a traceback.
        return str(root)


def pages(dist_only: bool) -> tuple[list[Path], str]:
    """The HTML pages to judge, and the sentence naming where they came from.

    The built pages when a build is there, because that is what a browser receives.
    The sources otherwise, so an unbuilt checkout is still judged on what it would
    ship. ``dist_only`` refuses the fallback rather than taking it silently: a CI
    step that quietly reads the sources proves nothing about the artifact.
    """
    if DIST.is_dir():
        found = sorted(p for p in DIST.rglob("*.html") if p.is_file())
        if found:
            return found, f"built pages under {_describe(DIST)}"
        if dist_only:
            return [], f"built pages under {_describe(DIST)}"
    if dist_only:
        return [], f"built pages under {_describe(DIST)}"

    found = [p for p in SHELL_SOURCES if p.is_file()]
    found += sorted(p for p in PUBLIC_SOURCES.rglob("*.html") if p.is_file())
    return found, f"source pages under {_describe(ROOT / 'frontend')}"


def is_shell(path: Path) -> bool:
    """Whether this page is the application shell the attribution belongs in.

    The splash screen, the privacy policy and the terms a desktop install shows are
    pages of their own and carry no attribution; the shell is the one page whose
    licence notice this check defends. Judged on the name so it answers the same way
    for ``frontend/index.html`` and for ``frontend/dist/index.html``.
    """
    return path.name == "index.html"


def findings(path: Path, text: str) -> list[str]:
    """What is wrong with one page: every comment, and any licence notice it lost."""
    out: list[str] = []

    for match in COMMENT.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        body = " ".join(match.group(0).split())
        out.append(f"line {line}: comment {body[:120]}")

    # An opening with no closing is worse than a comment: it swallows the rest of the
    # page into a comment a browser will not render, and a check that only matched
    # terminated comments would report the page as clean.
    closed = sum(1 for _ in COMMENT.finditer(text))
    opened = sum(1 for _ in OPENING.finditer(text))
    if opened > closed:
        stray = list(CLOSING.finditer(text))
        line = text.count("\n", 0, (stray[-1].start() if stray else 0)) + 1
        out.append(f"line {line}: a comment opens and never closes ({opened} open, {closed} closed)")

    if is_shell(path):
        for needle in SHELL_NEEDLES:
            if needle not in text:
                out.append(f"the licence notice lost {needle!r}")

    return out


def judge(paths: list[Path]) -> list[tuple[Path, list[str]]]:
    """Read every page and return the ones with something to answer for."""
    judged: list[tuple[Path, list[str]]] = []
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        found = findings(path, text)
        if found:
            judged.append((path, found))
    return judged


SELFTEST_CASES: tuple[tuple[str, str, str], ...] = (
    (
        "a developer note about a deployment",
        "<!DOCTYPE html>\n<html>\n  <head>\n    <!-- Analytics is injected by the deploy script -->\n"
        '    <meta name="license" content="AGPL-3.0-or-later" />\n    <link rel="license" href="/legal/LICENSE.txt" />\n'
        '    <meta name="source" content="Based on OpenConstructionERP by DataDrivenConstruction" />\n'
        '  </head>\n  <body><div id="root"></div></body>\n</html>\n',
        "comment",
    ),
    (
        "a comment that never closes",
        "<!DOCTYPE html>\n<html>\n  <head>\n    <!-- an unfinished thought\n"
        '    <meta name="license" content="AGPL-3.0-or-later" />\n    <link rel="license" href="/legal/LICENSE.txt" />\n'
        '    <meta name="source" content="Based on OpenConstructionERP by DataDrivenConstruction" />\n'
        '  </head>\n  <body><div id="root"></div></body>\n</html>\n',
        "never closes",
    ),
    (
        "a shell whose attribution was deleted with them",
        "<!DOCTYPE html>\n<html>\n  <head>\n    <title>Product</title>\n  </head>\n"
        '  <body><div id="root"></div></body>\n</html>\n',
        "the licence notice lost",
    ),
    (
        "a shell that kept the licence but lost the upstream name",
        '<!DOCTYPE html>\n<html>\n  <head>\n    <link rel="license" href="/legal/LICENSE.txt" />\n'
        '    <meta name="license" content="AGPL-3.0-or-later" />\n'
        '    <meta name="source" content="A self-hosted product." />\n  </head>\n'
        '  <body><div id="root"></div></body>\n</html>\n',
        "OpenConstructionERP",
    ),
    (
        "a secondary page carrying a section label",
        "<!DOCTYPE html>\n<html>\n  <head>\n    <!-- One-time launch choice -->\n    <title>Splash</title>\n"
        "  </head>\n  <body></body>\n</html>\n",
        "comment",
    ),
)


def selftest() -> int:
    """Prove the check can fail, on pages built for the occasion.

    A gate only ever seen passing is indistinguishable from one that cannot fail.
    Each case is a whole page written to a temporary directory under the name it
    would be served under, so the shell rules and the secondary-page rules are each
    exercised, and the last page proves a clean one is accepted rather than refused
    for a reason nobody intended.
    """
    import tempfile

    refused = 0
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        for index, (name, body, needle) in enumerate(SELFTEST_CASES, 1):
            page = root / f"case-{index}" / "index.html"
            page.parent.mkdir(parents=True, exist_ok=True)
            page.write_text(body, encoding="utf-8")
            found = findings(page, body)
            if not found:
                print(f"::error::selftest case {index} ({name}) was accepted and must be refused")
                return 1
            if not any(needle in item for item in found):
                print(
                    f"::error::selftest case {index} ({name}) was refused for {' | '.join(found)}, not for {needle!r}"
                )
                return 1
            refused += 1

        clean = root / "clean" / "index.html"
        clean.parent.mkdir(parents=True, exist_ok=True)
        clean.write_text(SELFTEST_CASES[0][1].replace("    <!-- Analytics is injected by the deploy script -->\n", ""))
        accepted = findings(clean, clean.read_text(encoding="utf-8"))
        if accepted:
            print(f"::error::the clean page was refused: {' | '.join(accepted)}")
            return 1

    print(
        f"built HTML comments: selftest OK - {refused} case(s) refused for the reason each was "
        f"written for, and the clean page accepted"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dist-only",
        action="store_true",
        help="judge only frontend/dist and refuse to fall back to the sources",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="refuse five seeded pages and accept a clean one, then exit",
    )
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    paths, source = pages(args.dist_only)
    if not paths:
        # The failure a check like this most often has: an empty population reads as
        # a clean one. There is always at least one served page, so finding none
        # means the wrong directory was read, and that is a refusal.
        message = f"no HTML page to judge in {source}"
        if args.dist_only:
            message += "; the build this step follows did not produce one"
        print(f"::error::{message}")
        return 1

    judged = judge(paths)
    for path, found in judged:
        for item in found:
            print(f"::error file={path.relative_to(ROOT).as_posix()}::{item}")

    if judged:
        print(
            f"built HTML comments: read {len(paths)} page(s) from {source}; "
            f"{len(paths) - len(judged)} clean, {len(judged)} with findings"
        )
        return 1

    print(f"built HTML comments: read {len(paths)} page(s) from {source}; {len(paths)} clean, 0 with findings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
