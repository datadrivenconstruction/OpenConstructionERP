#!/usr/bin/env python3
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Fail the build if a corrected foreign spelling reverts to its stripped form.

The demo packs ship German, Portuguese, Spanish and French text to users who
read those languages. Several packs were authored without the marks - umlauts
written out as vowel-plus-e ("Koecherfundamente", "Lueftungskanaele"), eszett as
ss ("Erschliessung", "Strasse"), Portuguese and Spanish accents deleted outright
("Instalacoes", "construccion"), French likewise ("Batiment", "securite"). To a
German or Brazilian reader that is visibly broken text on a marketing page.

Non-ASCII is allowed as data here and always was; see constraint 10 in
CLAUDE.md. The rule bans Russian prose in a comment, not accented characters in
a string, so "Köcherfundamente" and "Fundações" are simply the correct
spellings.

What this gate is
-----------------
A denylist of the exact spellings that were found broken in this repository,
recorded per file. It is deliberately not a rule about German or Portuguese
orthography, because such a rule cannot be written without false positives:
"Wasser", "muss" and "Anschluss" are correct with ss, "Bauer" and "Feuer"
contain a legitimate "ue", "aerodynamisch" a legitimate "ae", "agua" is correct
Spanish while "água" is correct Portuguese, and "nivel" is correct Spanish while
"nível" is correct Portuguese. Only a list can tell those apart, so this is a
list.

Consequently the gate catches a regression - a corrected word going back the way
it was - and does not catch a brand-new mangled word in a brand-new file. That
is the honest limit of it. A new pack needs a human to read it.

Only string literals are examined. The data is what ships; a comment or an
identifier is not.

Exit codes:
    0  every corrected spelling is still correct
    1  at least one reverted (with file:line and the spelling it should be)

Usage::

    python scripts/check_seed_diacritics.py            # every file in the denylist
    python scripts/check_seed_diacritics.py path/a.py  # only these (pre-commit)
"""

from __future__ import annotations

import json
import re
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DENYLIST = Path(__file__).resolve().parent / "seed_diacritics.json"

# Letter boundaries rather than \b: a demo document is called
# "D26_ML-2026-01_Maengelliste_Rohbau.pdf" and an underscore is a word
# character, so \b would step over exactly the strings a reader sees.
BOUND = r"(?<![A-Za-zÀ-ɏ])%s(?![A-Za-zÀ-ɏ])"

# An email address inside a string literal is exempt, because there the stripped
# spelling is the correct one. A local part and a DNS label are ASCII by
# convention, so "vergabe@kurpfalz-kaelte.de" is right and the accented form
# would be a broken address. The packs already apply that distinction
# deliberately: of the twenty-nine occurrences this exemption covers, twenty sit
# on a line that also carries the accented display form, as in
# ("Kurpfalz Kältetechnik GmbH", "vergabe@kurpfalz-kaelte.de", ...). Without the
# exemption the gate reports a company whose name is spelled correctly, and the
# instruction it prints - write the accented form - breaks the address if
# followed. A gate that goes green only once the data is wrong is worse than no
# gate.
#
# Scoped to addresses rather than to hostnames generally, because that is what
# the denylisted files contain today. A bare hostname or a URL carrying a
# stripped spelling would need the same treatment and none appears yet; add it
# to this pattern when one does, rather than widening it now on speculation.
ADDRESS = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def outside_addresses(text: str, bad: str) -> bool:
    """True if *bad* occurs in *text* somewhere other than inside an address.

    A literal can hold both at once - the display name and the contact address
    for the same firm - so the question is per occurrence rather than per
    literal, and one exempt occurrence must not excuse a second that is real.
    """
    spans = [m.span() for m in ADDRESS.finditer(text)]
    return any(
        not any(start <= m.start() and m.end() <= end for start, end in spans)
        for m in re.finditer(BOUND % re.escape(bad), text)
    )


def string_literals(path: Path) -> list[tuple[int, str]]:
    """Every string literal in a Python file, as (line number, text)."""
    with open(path, encoding="utf-8") as fh:
        try:
            return [
                (tok.start[0], tok.string)
                for tok in tokenize.generate_tokens(fh.readline)
                if tok.type == tokenize.STRING
            ]
        except (tokenize.TokenError, SyntaxError) as exc:
            print(f"{path}: cannot tokenize ({exc})", file=sys.stderr)
            raise SystemExit(1) from exc


def main(argv: list[str]) -> int:
    # The whole report is about accented characters, and the default console
    # encoding on a Windows dev box is cp1252, which renders every one of them
    # as a replacement glyph. A gate that cannot print the spelling it is asking
    # for is not much of a gate.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    denylist: dict[str, dict[str, str]] = json.loads(DENYLIST.read_text(encoding="utf-8"))

    wanted = {str(Path(a).as_posix()) for a in argv}
    targets = {k: v for k, v in denylist.items() if not wanted or k in wanted}

    scanned = 0
    entries = 0
    failures: list[str] = []
    for rel, mapping in sorted(targets.items()):
        path = ROOT / rel
        if not path.exists():
            # A pack can legitimately be deleted; that is not this gate's business.
            continue
        scanned += 1
        entries += len(mapping)
        for lineno, text in string_literals(path):
            for bad, good in mapping.items():
                if bad in text and outside_addresses(text, bad):
                    failures.append(f"{rel}:{lineno}: {bad!r} should be {good!r}")

    # Print the denominator. "0 reverted" over nothing scanned reads exactly like
    # "0 reverted" over eleven files, and only one of those is a clean bill.
    print(f"seed diacritics: {scanned} file(s) scanned against {entries} recorded spelling(s)")
    sys.stdout.flush()
    if not scanned and denylist:
        print(
            "nothing was scanned - none of the given paths is in the denylist",
            file=sys.stderr,
        )
        return 0
    if failures:
        print(
            f"\n{len(failures)} spelling(s) reverted to a stripped form:\n",
            file=sys.stderr,
        )
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        print(
            "\nThese are shipped strings in German, Portuguese, Spanish or French. "
            "Write the accented form; non-ASCII is allowed as data.",
            file=sys.stderr,
        )
        return 1
    print("no reverted spellings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
