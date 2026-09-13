#!/usr/bin/env python3
"""Fail when an installed dependency carries copyleft we have not accepted.

Why this exists
---------------
The repository already had a licence gate, ``.github/workflows/dependency-review.yml``.
It never ran and would not have caught anything if it had. It triggers on
``pull_request``, and this project commits directly to ``main``, so the event
never occurs. Its denylist read ``GPL-2.0, GPL-3.0, LGPL-2.1, LGPL-3.0,
AGPL-1.0``: it denied AGPL-1.0, which nothing anywhere uses, and omitted
AGPL-3.0, which is the licence of the one genuinely AGPL package we ship. A
denylist that omits the licence it exists to catch is not a control.

That workflow has been corrected, but it still only runs on an event this
project does not produce, and it cannot be run locally at all: it needs the
GitHub dependency-review API and a pull-request diff. This script is the part
that can be run before a push, which is the only kind of check that catches
anything here.

What it inspects
----------------
The **Python environment it is executing in**, through ``importlib.metadata``.
For every installed distribution it reads the licence declared in that
distribution's own metadata: the PEP 639 ``License-Expression`` field, the
legacy ``License`` field, and the ``License :: ...`` trove classifiers. It
compares the result against the policy below.

Run it with the interpreter whose closure you care about::

    .venv-run/Scripts/python scripts/check_dependency_licences.py
    python scripts/check_dependency_licences.py --verbose

What it is blind to, stated so nobody over-reads a green run
------------------------------------------------------------
1. **Packages that are not installed here.** This measures one environment. A
   dependency reachable only through an extra that is not installed, or only on
   another platform, is invisible. ``--require`` asserts that a package we know
   ships in every artefact was actually seen, so a green run against an empty or
   half-built environment cannot pass silently.
2. **Native libraries compiled into a wheel.** A package declares a licence for
   its own source. The C libraries statically linked into its extension module
   arrive with the wheel and are described by no metadata anywhere. PyMuPDF is
   exactly this case: its entire in-wheel licence disclosure is one line, and
   MuPDF links further upstream code beneath it. ``NOTICE`` covers this layer by
   hand, under "Native Binaries Inside Python Wheels", because no scanner can.
3. **Metadata that disagrees with the shipped licence text.** We read the
   declaration, not the ``LICENSE`` file.
4. **The frontend and the Rust desktop shell.** Python only.

Exit codes
----------
0  every installed distribution is permissively licensed or explicitly accepted
1  a copyleft licence was found that is not on the accepted list
2  the environment could not be inspected, or a ``--require`` package is missing
"""

from __future__ import annotations

import argparse
import re
import sys
from importlib import metadata

# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------
# Ordered most specific first. The first pattern that matches a licence string
# decides, so AGPL must be tested before GPL and LGPL before GPL, otherwise
# "LGPL-3.0" would be reported as GPL.
_COPYLEFT_PATTERNS: tuple[tuple[str, str], ...] = (
    ("AGPL", r"\bA\.?GPL\b|\bAffero\b"),
    ("LGPL", r"\bL\.?GPL\b|\bLesser General Public\b|\bLibrary General Public\b"),
    ("GPL", r"\bGPL\b|\bGeneral Public License\b"),
    ("MPL", r"\bMPL\b|\bMozilla Public\b"),
    ("EPL", r"\bEPL\b|\bEclipse Public\b"),
    ("CDDL", r"\bCDDL\b|\bCommon Development and Distribution\b"),
    ("SSPL", r"\bSSPL\b|\bServer Side Public\b"),
    ("OSL", r"\bOSL\b|\bOpen Software License\b"),
)

# Families that block the build unless the package is on ACCEPTED below.
# MPL, EPL and CDDL are file-level copyleft: they attach to the files of the
# package itself, which we do not modify, and they carry notice duties that
# NOTICE discharges. They are reported, not failed.
_BLOCKING = {"AGPL", "LGPL", "GPL", "SSPL", "OSL"}
_REPORT_ONLY = {"MPL", "EPL", "CDDL"}

# Every entry needs a reason. An allowlist without reasons rots into a list of
# things somebody once silenced, and the next reader cannot tell an accepted
# risk from an unexamined one.
ACCEPTED: dict[str, str] = {
    "pymupdf": (
        "AGPL-3.0-or-later, Artifex, dual sold. Accepted deliberately: it is a base "
        "dependency so PDF takeoff works on a stock install. This is the exception the "
        "whole gate exists to keep visible, not to hide. Documented for customers in "
        "NOTICE 'AGPL Cascade' and docs/legal/COMMERCIAL-LICENSE.md section 4a, which tell a "
        "commercial deployment it must either replace it or hold an Artifex licence. "
        "Removing this entry is how you make the gate red on purpose to test it."
    ),
    "psycopg2-binary": (
        "LGPL-3.0-or-later with the OpenSSL linking exception. Base dependency, used "
        "unmodified through its published Python API. Note the frozen desktop build "
        "links it statically, which carries an LGPL section 4 relinking duty; that is "
        "tracked separately and is not what this gate measures."
    ),
    "python-bidi": "LGPL, reached only through paddleocr in the optional [cv] extra. Unmodified library.",
    "crc32c": "LGPL-2.0-or-later, reached only through paddleocr in the optional [cv] extra. Unmodified library.",
    "pyinstaller": (
        "GPL-2.0-or-later carrying the PyInstaller bootloader exception, which exists "
        "precisely to permit freezing and distributing software under other terms. In "
        "the [dev] extra, so it is present in CI and on developer machines and in no "
        "artefact a user installs. The frozen desktop app does ship its bootloader, "
        "which is the case the exception was written for."
    ),
    "pyinstaller-hooks-contrib": (
        "Declares no License field and two classifiers, Apache Software License and "
        "GNU General Public License v2, so this gate reads it as GPL. Measured from "
        "2026.7. It is a dependency of pyinstaller and shares its position exactly: "
        "[dev] only, present in CI and on developer machines, in no artefact a user "
        "installs. Contributed hook data, not linked into anything."
    ),
}
# chardet was on this list as LGPL-2.1. It is not: 7.6.0 declares
# License-Expression: 0BSD, measured rather than assumed, so the entry said we
# tolerated something that was never copyleft. Removed. Nothing else needs to be
# added for the [dev,server] closure: altgraph, macholib, pefile, mypy,
# pre-commit and lxml are MIT or BSD, celery is BSD-3-Clause and boto3 is
# Apache-2.0, all read from their own metadata.

# Packages that must be present for a run to count. Without this a green result
# from an environment where nothing is installed looks identical to a clean one.
_REQUIRED_BY_DEFAULT = ("pymupdf", "pdfplumber", "fastapi", "sqlalchemy")

# We are AGPL-3.0-or-later ourselves, and an editable install puts us in the
# same environment we are inventorying. Our own licence is the premise of this
# gate, not a finding of it. Skipped by name rather than allowlisted, because an
# entry in ACCEPTED would read as "we tolerate this dependency".
_SELF = {"openconstructionerp", "openestimate"}

_NORMALISE = re.compile(r"[-_.]+")


def _canonical(name: str) -> str:
    """PEP 503 normalisation, so `PyMuPDF` and `pymupdf` are one package."""
    return _NORMALISE.sub("-", name).lower()


def _licence_strings(dist: metadata.Distribution) -> list[str]:
    """Every place a distribution can declare its licence, in one list."""
    meta = dist.metadata
    found: list[str] = []

    # PEP 639 replaces the free-text License field with an SPDX expression.
    for field in ("License-Expression", "License"):
        value = meta.get(field)
        if value and value.strip():
            # Some packages paste their entire licence text into this field.
            # The first line carries the name; the rest is noise that produces
            # false hits (a BSD text that happens to mention the GPL).
            found.append(value.strip().splitlines()[0][:200])

    found.extend(
        classifier.split("::")[-1].strip()
        for classifier in meta.get_all("Classifier") or []
        if classifier.startswith("License ::")
    )
    return found


def _classify(strings: list[str]) -> tuple[str, str] | None:
    """Return (family, the string that matched), or None if nothing copyleft."""
    for family, pattern in _COPYLEFT_PATTERNS:
        for text in strings:
            # "OSI Approved" is a classifier prefix, not a licence, and
            # "GPL-compatible" describes a permissive licence rather than a
            # copyleft one. Neither should trip the gate.
            if re.search(r"GPL[- ]compatible", text, re.IGNORECASE):
                continue
            if re.search(pattern, text, re.IGNORECASE):
                return family, text
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verbose", action="store_true", help="list every distribution and its licence")
    parser.add_argument(
        "--require",
        action="append",
        default=None,
        help="package that must be installed for the run to count (repeatable)",
    )
    args = parser.parse_args()

    try:
        dists = list(metadata.distributions())
    except Exception as exc:  # pragma: no cover - environment failure
        print(f"[FAIL] cannot inspect the environment: {exc}", file=sys.stderr)
        return 2

    seen: dict[str, tuple[str, str]] = {}
    blocking: list[tuple[str, str, str]] = []
    reported: list[tuple[str, str, str]] = []
    accepted: list[tuple[str, str, str]] = []

    for dist in dists:
        raw_name = dist.metadata.get("Name")
        if not raw_name:
            continue
        name = _canonical(raw_name)
        if name in seen or name in _SELF:
            continue

        verdict = _classify(_licence_strings(dist))
        seen[name] = (raw_name, verdict[0] if verdict else "permissive")
        if verdict is None:
            continue

        family, matched = verdict
        row = (raw_name, family, matched)
        if name in ACCEPTED:
            accepted.append(row)
        elif family in _BLOCKING:
            blocking.append(row)
        elif family in _REPORT_ONLY:
            reported.append(row)

    required = [_canonical(p) for p in (args.require or _REQUIRED_BY_DEFAULT)]
    missing = [p for p in required if p not in seen]
    if missing:
        print(
            "[FAIL] this environment is not the one to measure: "
            f"{', '.join(missing)} not installed. A green run here would mean nothing.",
            file=sys.stderr,
        )
        return 2

    if args.verbose:
        for name in sorted(seen):
            raw_name, family = seen[name]
            print(f"  {raw_name:<40} {family}")

    print(f"scanned {len(seen)} installed distributions")

    if accepted:
        print(f"\n{len(accepted)} accepted copyleft dependenc(y/ies), each recorded with a reason:")
        for raw_name, family, matched in sorted(accepted):
            print(f"  {raw_name} ({family}: {matched})")
            print(f"      {ACCEPTED[_canonical(raw_name)]}")

    if reported:
        print(f"\n{len(reported)} file-level copyleft dependenc(y/ies), notice duties only, not a failure:")
        for raw_name, family, matched in sorted(reported):
            print(f"  {raw_name} ({family}: {matched})")

    if blocking:
        print(f"\n[FAIL] {len(blocking)} dependenc(y/ies) carry copyleft that is not on the accepted list:")
        for raw_name, family, matched in sorted(blocking):
            print(f"  {raw_name} -- {family} ({matched})")
        print(
            "\nEach of these has to be a decision, not an oversight. Either drop the "
            "package, or add it to ACCEPTED in this file with the reason it is "
            "acceptable, and say so in NOTICE where a customer will read it. If it is "
            "AGPL or GPL and reaches a shipped artefact, docs/legal/COMMERCIAL-LICENSE.md has to "
            "say what a commercial deployment must do about it.",
        )
        return 1

    print("\n[OK] no unaccepted copyleft in this environment")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
