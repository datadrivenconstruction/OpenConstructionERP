# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Decode a P6 XER schedule export whose code page the file never declares.

An ``.xer`` is written in the Windows ANSI code page of the machine that
exported it and says so nowhere. The route used to try UTF-8 and then fall back
to Latin-1, which is the worst possible second guess, because Latin-1 accepts
every byte there is. An export from an Arabic, Russian, Greek or Hebrew Windows
install therefore imported without an error, without a warning and without a log
line, and every activity, WBS and resource name reached the database as
mojibake. Nothing downstream can recover it: by then the original bytes are
gone.

Latin-1 was also the wrong first guess for the Western files it was meant for.
P6's Western default is cp1252, whose 0x80 to 0x9F range holds the curly quotes,
the en dash and the euro sign. Latin-1 maps that range to C1 control characters,
so ``Crane Operator 'Day Shift'`` imported with invisible control bytes inside
the name.

The ladder here is utf-8-sig, then strict utf-8, then a sniffed code page, then
cp1252, then Latin-1 as the floor that cannot fail. Every step but the last can
decline, which is what makes the order meaningful.

How the sniff decides, and why it is not the obvious thing
---------------------------------------------------------

The obvious test is "decode the high bytes and see whether they came out as that
code page's own script". Measured against real bytes, that test does not
discriminate poorly, it does not discriminate at all: cp1251 maps every byte
from 0xC0 to 0xFF onto a Cyrillic letter, so Arabic text scores a perfect 1.00
as Cyrillic, and Greek and Hebrew samples score 1.00 under three of the four
candidates. The margin between the right answer and the best wrong one was
exactly zero on all four languages. Anything built on script membership is a
coin flip wearing a lab coat.

What does separate them is how often the six most frequent letters of a language
turn up. Under the right page they are about half of everything; under a wrong
one the same bytes land on letters that language rarely uses. Measured on
construction vocabulary in all four languages, the right page scored 0.49 to
0.53 and the best wrong page never passed 0.38, the narrowest gap being Hebrew
against Greek at 0.12. Six letters rather than the whole alphabet is the point:
a set large enough to cover most of a script saturates and stops telling the two
apart.

How little evidence is too little
---------------------------------

The scores above were calibrated on running text and none of them is aware of
how small a sample it may be dividing. A schedule is mostly ASCII, so a file
carrying one short activity name puts five or six high bytes on the table; every
score is then a multiple of 0.2 and a lead of 0.2 clears the margin without
meaning anything. Measured over 7476 name-shaped windows of the same
construction vocabulary, the largest sample that still named the wrong page
carried 25 high bytes, and the failure was not evenly spread: Hebrew lost 11 of
its 33 whole-word names to Greek and Arabic. A real export carries hundreds of
high bytes, so a floor between those two numbers costs nothing and removes the
whole regime. Raising the margin instead was measured and rejected: it never
reaches zero wrong answers at any value, and by 0.12 it has started throwing
away correct verdicts on whole files, because Hebrew's own margin on a full
export is 0.117.

A Western file must never reach that scoring at all, and the guard is the shape
of the high bytes rather than their count. Accented Latin letters arrive alone
between ASCII, non-Latin scripts arrive in runs. Measured: the longest run in
``Straße``, ``Größe``, ``Façade`` and a line of curly quotes was two bytes, and
the share of high bytes sitting in runs of three or more was 0.00; for the four
non-Latin samples that share was 0.98 to 1.00, with runs up to twelve. The
threshold sits in the middle of a gap that wide, so it is not a tuned number.

What this deliberately does not do
----------------------------------

No confidence is reported to the caller and no free-text guess is made beyond
these four pages. A code page that is not here (Thai cp874, the East Asian
multi-byte pages, Turkish cp1254, which differs from cp1252 in six positions and
so cannot be told apart by shape) falls through to cp1252, exactly as before.
That is a smaller promise than a general charset detector and it is kept.
"""

from __future__ import annotations

import re

__all__ = ["decode_xer", "sniff_code_page"]

# Share of decoded characters that must be among a language's six most frequent
# letters before its page is preferred, and the lead it must hold over the
# runner-up. The observed spread was 0.49-0.53 for the right page against at
# most 0.38 for the best wrong one, so both numbers sit well inside the gap
# rather than on the edge of one sample.
_MIN_SCORE = 0.30
_MIN_MARGIN = 0.05

# Share of high bytes that must sit in a run of three or more before the file is
# treated as non-Latin at all. Observed: 0.00 for Western text, 0.98-1.00 for
# the four non-Latin scripts.
_MIN_RUN_SHARE = 0.50

# How many high bytes must be on the table before the vote may reach a verdict.
# Below this the scores are too coarse to mean anything and the margin is
# cleared by arithmetic rather than by evidence. Measured: the largest sample
# that still named a wrong page carried 25 high bytes; the smallest whole export
# in the same vocabulary carried 60. The floor sits between them, nearer the low
# end, because declining costs a file only the answer it used to get anyway.
_MIN_HIGH_BYTES = 32

# The six most frequent letters of each language, which is the whole of the
# evidence this module weighs. Cyrillic and Greek carry their own alphabets;
# Arabic and Hebrew are unpointed, as construction schedules are written.
_CANDIDATES: dict[str, str] = {
    "cp1256": "العيمن",  # Arabic
    "cp1251": "оеаинт",  # Russian
    "cp1253": "αοιεντ",  # Greek
    "cp1255": "יולאהת",  # Hebrew
}

_HIGH_RUN = re.compile(rb"[\x80-\xff]+")

# Long enough that a run's shape means something, short enough that a two-word
# activity name in Arabic still qualifies.
_RUN_FLOOR = 3


def _high_byte_run_share(raw: bytes) -> tuple[int, float]:
    """Total high bytes, and the share of them sitting in runs of three or more."""
    runs = _HIGH_RUN.findall(raw)
    total = sum(len(r) for r in runs)
    if total == 0:
        return 0, 0.0
    in_runs = sum(len(r) for r in runs if len(r) >= _RUN_FLOOR)
    return total, in_runs / total


def sniff_code_page(raw: bytes) -> str | None:
    """Name the Windows code page these bytes look like, or ``None``.

    ``None`` means "no opinion", not "Western": the caller decides what to do
    with an absent answer, and today it falls back to cp1252. Returning a page
    only on a clear lead, and only when there is enough to have a lead about, is
    what keeps a Western file, a file with one short non-Latin name and a code
    page this module has never heard of out of the four-way vote.
    """
    total, run_share = _high_byte_run_share(raw)
    if total < _MIN_HIGH_BYTES or run_share < _MIN_RUN_SHARE:
        return None

    high = bytes(b for b in raw if b >= 0x80)
    scores: dict[str, float] = {}
    for page, frequent in _CANDIDATES.items():
        # errors="replace" rather than strict: a wrong page must be allowed to
        # produce a bad score instead of an exception, or the vote would be
        # decided by which candidate happens to have undefined bytes.
        decoded = high.decode(page, errors="replace")
        if not decoded:
            continue
        scores[page] = sum(1 for ch in decoded if ch in frequent) / len(decoded)
    if not scores:
        return None

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best, best_score = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
    if best_score < _MIN_SCORE or best_score - runner_up < _MIN_MARGIN:
        return None
    return best


def decode_xer(raw: bytes) -> tuple[str, str]:
    """Decode P6 export bytes, returning the text and the code page used.

    The name of the page is returned rather than logged here so the route can
    put it in front of the person doing the import. A file that came back as
    cp1256 when they expected English is worth their attention, and a silent
    correct answer teaches them nothing about the file they are holding.
    """
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass

    sniffed = sniff_code_page(raw)
    if sniffed is not None:
        try:
            return raw.decode(sniffed), sniffed
        except UnicodeDecodeError:
            # The sniff reads high bytes only; a stray undefined byte elsewhere
            # should not throw away an otherwise well-supported answer.
            return raw.decode(sniffed, errors="replace"), sniffed

    try:
        return raw.decode("cp1252"), "cp1252"
    except UnicodeDecodeError:
        # cp1252 leaves five bytes undefined (0x81, 0x8D, 0x8F, 0x90, 0x9D).
        # Latin-1 defines all 256 and so ends the ladder by construction.
        return raw.decode("latin-1"), "latin-1"
