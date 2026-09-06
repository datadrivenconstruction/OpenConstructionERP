#!/usr/bin/env python3
"""A new case playbook must not silently un-finish a finished language.

Case playbooks live in ``frontend/src/features/cases/data/*.playbook.ts``. Each
one names its catalogue strings by key and carries the English inline as a
``*Default`` field, so English renders correctly the moment the file lands and
nothing looks wrong locally. Every other language renders that English instead,
and only in that language, which is why this went unnoticed: the person adding
the playbook is not the person who sees the gap.

That is what happened. One commit added thirty eight playbooks and touched no
locale file at all. The titles and descriptions arrived a day later in a batch
pass whose commit message described a different screen entirely, and the longer
text never arrived. Four of the languages affected had been complete before that
commit.

So this gate does not ask for every language. Requiring thirty one translations
before a playbook may land would stop the case library growing, and the library
growing is the point. It asks only that the languages which are *already*
finished stay finished. Those are the ``card_complete`` list in
``frontend/src/features/cases/case-coverage-manifest.json``, and the list grows
by itself: ``frontend/scripts/check-case-coverage.mjs --update`` promotes a
language the day it reaches full catalogue coverage and never takes one out, so
a language that got there can never quietly regress afterwards. The list used to
be a constant here; the step-level ratchet in that script is this gate's sibling
and needs the same list, and two copies of it would have drifted apart.

Scope is the catalogue only, meaning the title, the one line description and the
long description. Those are what a reader sees in the case list before opening
anything. Step level text is a much larger body of work and is deliberately not
gated here, because a gate nobody can satisfy gets switched off.

``longdesc`` is required only where English actually has one. Eighty two of the
playbooks have no ``longDescKey`` at all, which is a gap in the English copy
rather than in any translation, and asking a translator to supply what was never
written would send them looking for a field that does not exist.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "frontend", "src", "features", "cases", "data")
LOCALES = os.path.join(REPO, "frontend", "src", "app", "locales")
MANIFEST = os.path.join(REPO, "frontend", "src", "features", "cases", "case-coverage-manifest.json")

_Q = '"'
_BS = chr(92)
_STR = _Q + "((?:[^" + _Q + _BS + _BS + "]|" + _BS + _BS + ".)*)" + _Q
_KEY_FIELDS = ("titleKey", "descKey", "longDescKey")


def catalogue_keys(text: str) -> set[str]:
    """Every catalogue key a single playbook source declares."""
    found = set()
    for field in _KEY_FIELDS:
        m = re.search(field + r"\s*:\s*" + _STR, text)
        if m:
            found.add(m.group(1))
    return found


def playbook_keys(data_dir: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for path in sorted(glob.glob(os.path.join(data_dir, "*.playbook.ts"))):
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        keys = catalogue_keys(text)
        if keys:
            out[os.path.basename(path)] = keys
    return out


def reference_locales(manifest_path: str = MANIFEST) -> tuple[str, ...]:
    """The finished languages, as check-case-coverage.mjs last recorded them.

    Read from the manifest rather than held here so that there is one list. A
    manifest without the list is a broken tree and not a clean one, so this
    stops rather than falling back to a guess about which languages are done.
    """
    try:
        with open(manifest_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"cannot read card_complete from {manifest_path}: {exc}") from exc
    locales = tuple(data.get("card_complete") or ())
    if not locales:
        raise SystemExit(
            f"{manifest_path} lists no card_complete locale; "
            "record one with: node frontend/scripts/check-case-coverage.mjs --update"
        )
    return locales


def locale_keys(path: str) -> set[str]:
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    return set(re.findall(_Q + r"(cases\.[A-Za-z0-9_.]+)" + _Q + r"\s*:", text))


def check(data_dir: str, locales_dir: str, reference: tuple[str, ...]) -> list[str]:
    """Return one human readable line per missing key, empty when clean."""
    by_file = playbook_keys(data_dir)
    problems: list[str] = []
    for loc in reference:
        path = os.path.join(locales_dir, loc + ".ts")
        if not os.path.exists(path):
            problems.append(f"{loc}: locale file is missing at {path}")
            continue
        have = locale_keys(path)
        for filename, keys in by_file.items():
            for key in sorted(keys - have):
                problems.append(f"{loc}: {key}   (declared by {filename})")
    return problems


def _append(path: str, text: str) -> None:
    """Append to a selftest fixture. Only here so the handle closes deterministically."""
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(text)


def _write(path: str, text: str) -> None:
    """Write a selftest fixture. Only here so the handle closes deterministically."""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def selftest() -> int:
    """The gate must be able to fail, so prove it on data built to fail.

    A gate only ever seen passing is indistinguishable from a gate that cannot
    fail at all, so the negative control has to hit a place nothing else does.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        data = os.path.join(tmp, "data")
        locs = os.path.join(tmp, "locales")
        os.makedirs(data)
        os.makedirs(locs)
        _write(os.path.join(data, "a.playbook.ts"), 'titleKey: "cases.a.title",\ndescKey: "cases.a.desc",\n')
        # xx has the title and not the description.
        _write(os.path.join(locs, "xx.ts"), '  "cases.a.title": "t",\n')
        missing = check(data, locs, ("xx",))
        if len(missing) != 1 or "cases.a.desc" not in missing[0]:
            print("selftest FAILED: expected exactly the missing desc, got:")
            for line in missing:
                print("   ", line)
            return 1

        # And it must go quiet once the gap is filled, or it is just noise.
        _append(os.path.join(locs, "xx.ts"), '  "cases.a.desc": "d",\n')
        if check(data, locs, ("xx",)):
            print("selftest FAILED: still reporting after the key was added")
            return 1

    print("selftest ok: the gate fails on a missing key and passes once it is present")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true", help="prove the gate can fail")
    ap.add_argument("--json", action="store_true", help="machine readable output")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    reference = reference_locales()
    problems = check(DATA, LOCALES, reference)
    if args.json:
        print(json.dumps({"missing": problems}, indent=1))
        return 1 if problems else 0

    total = len(playbook_keys(DATA))
    if not problems:
        print(f"Every one of the {total} case playbooks has its catalogue text in {', '.join(reference)}.")
        return 0

    print(f"{len(problems)} catalogue strings are missing from a finished language.\n")
    for line in problems[:60]:
        print("  " + line)
    if len(problems) > 60:
        print(f"  ... and {len(problems) - 60} more")
    print(
        "\nA playbook added without these renders English to everyone who reads "
        f"{' or '.join(reference)}, and nothing else reports it.\n"
        "Translate the catalogue strings, or if a language genuinely is not "
        "finished, take it out of card_complete in the manifest by hand and "
        "deliberately, rather than to clear this message."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
