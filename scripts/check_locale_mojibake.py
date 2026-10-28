#!/usr/bin/env python3
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Locale encoding guard: block text that was UTF-8 and got read as a code page.

When a UTF-8 string is handed to something that decodes one byte at a time as
CP1252, every non-ASCII character turns into two or three Latin ones. An em
dash is the bytes E2 80 94, and CP1252 reads those as "a with circumflex, euro
sign, right double quote". The string stays valid UTF-8 afterwards, quotes
correctly, parses correctly and renders without complaint. It is simply the
wrong text, and it is wrong in a way that survives every other check we run.

Measured 2026-09-01 across all 43 locale bundles: four occurrences, all of them
the same em dash in the same key, `takeoff.formats_detailed`, in ar, da, it and
no. One translation batch went through a byte-oriented tool and three others
did not. Nothing went red. The English source of that key carries a real em
dash and twelve other locales carry one too, so the correct spelling was
sitting in the same directory the whole time.

Every rule we have is blind to this class by construction:

  - both diacritic rules ask whether a word LOST a mark; this text has gained
    characters, and each one is a legitimate letter somewhere
  - `check_locale_mixed_script.py` asks about Cyrillic against Latin, and all
    of these characters are Latin
  - `check_locale_umlaut_folding.py` asks whether one word is spelled two ways,
    and the corrupted spelling usually occurs once, in one locale
  - `check_i18n_leak_baseline.py` asks whether a value equals the English one,
    and a corrupted translation equals nothing
  - the parse gate asks whether the file is valid TypeScript, and it is

The test is exact rather than heuristic, which is what keeps it at zero false
positives on real letters. A candidate must encode back to CP1252 as a lead
byte in C2..F4 followed by the right number of continuation bytes in 80..BF,
and then decode as UTF-8. That is the definition of the corruption rather than
a guess at it. Ordinary words never qualify: Portuguese "Âmbito" and "Âncora",
French "Âge", Romanian "ÂN" and Vietnamese "Âm" all put an ordinary letter
after the lead, and 0x67 is not a continuation byte. There are 108 such real
letters across five locales today and this rule passes over every one of them.

Because the corrupted forms are gone, this gate has no baseline and no declared
debt. It is zero and it stays zero: any hit is a new one.
"""

from __future__ import annotations

import pathlib
import re
import sys

LOCALES = pathlib.Path(__file__).resolve().parent.parent / "frontend" / "src" / "app" / "locales"

# The lead byte of a multi-byte UTF-8 sequence, as CP1252 renders it.
LEADS = "ÂÃÄÅÐÑàáâãäåð"
KEY_LINE = re.compile(r'^\s*"((?:[^"\\]|\\.)+)"\s*:\s*"((?:[^"\\]|\\.)*)"')


# How many continuation bytes each lead byte takes.
def _expected(lead: int) -> int:
    if 0xC2 <= lead <= 0xDF:
        return 1
    if 0xE0 <= lead <= 0xEF:
        return 2
    if 0xF0 <= lead <= 0xF4:
        return 3
    return 0


def _as_byte(char: str) -> int | None:
    """The CP1252 byte for one character, or None if it has none."""
    try:
        return char.encode("cp1252")[0]
    except (UnicodeEncodeError, IndexError):
        return None


def find_mojibake(value: str) -> list[tuple[str, str]]:
    """Return (corrupted run, what it decodes to) for each hit in ``value``."""
    hits: list[tuple[str, str]] = []
    i = 0
    while i < len(value):
        char = value[i]
        if char not in LEADS:
            i += 1
            continue
        lead = _as_byte(char)
        want = _expected(lead) if lead is not None else 0
        if not want or i + want >= len(value):
            i += 1
            continue
        run = value[i : i + want + 1]
        raw = bytearray()
        ok = True
        for pos, c in enumerate(run):
            b = _as_byte(c)
            if b is None or (pos and not 0x80 <= b <= 0xBF):
                ok = False
                break
            raw.append(b)
        if not ok:
            i += 1
            continue
        try:
            decoded = bytes(raw).decode("utf-8")
        except UnicodeDecodeError:
            i += 1
            continue
        hits.append((run, decoded))
        i += want + 1
    return hits


def main() -> int:
    paths = sorted(LOCALES.glob("*.ts"))
    if not paths:
        print(f"ERROR: no locale bundles under {LOCALES}", file=sys.stderr)
        return 1

    hits: list[tuple[str, int, str, str, str]] = []
    for path in paths:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = KEY_LINE.match(line)
            if not match:
                continue
            key, value = match.group(1), match.group(2)
            for run, decoded in find_mojibake(value):
                hits.append((path.name, lineno, key, run, decoded))

    if hits:
        print(
            f"ERROR: {len(hits)} run(s) of UTF-8 text decoded as a byte code page:",
            file=sys.stderr,
        )
        for name, lineno, key, run, decoded in hits:
            print(f"  {name}:{lineno}: {key}", file=sys.stderr)
            print(f"      {run!r} should be {decoded!r}", file=sys.stderr)
        print(
            "\nThis text was UTF-8 and something read it one byte at a time as "
            "CP1252. Replace each run with the character it decodes to; the "
            "message above already says which. Do not retranslate the string "
            "and do not delete the characters, because the rest of the value is "
            "intact and only these bytes are wrong. If a tool in the pipeline "
            "produced this, the string is evidence about the tool: the same "
            "batch usually corrupts several locales at once and leaves the rest "
            "of the file perfect, which is why nothing else here goes red.",
            file=sys.stderr,
        )
        return 1

    print(f"locale mojibake OK: {len(paths)} files, no UTF-8 run read as a code page")
    return 0


if __name__ == "__main__":
    sys.exit(main())
