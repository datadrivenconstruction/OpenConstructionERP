"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The commodity-code seed must describe a hierarchy it actually contains.

``app/modules/supplier_catalogs/data/unspsc_construction.csv`` ships inside the
wheel and is loaded verbatim by ``SupplierCatalogsService.seed_commodity_codes``:
every column becomes a column of ``oe_supplier_catalogs_commodity_code``, and
``level`` and ``parent_code`` become the tree an integration walks. Nothing
between the CSV and the database recomputes either of them, so a wrong number in
the file is a wrong number in every customer's lookup table.

Until this test the module had nothing asserting the seed was well formed. The
census that prompted it found 27 of 48 UNSPSC rows declaring a ``level`` their
own code contradicts, rows declaring a ``parent_code`` that is not their
structural parent, and rows whose structural parent is absent from the file
altogether.

What is asserted, and why each one is a property rather than a list of rows
known to be bad. A list goes stale the moment a row is added; these four rules
are computed from the digits, so a row added tomorrow is checked on the same
terms as a row that shipped last year.

1. ``level`` agrees with the shape of the code. Both vocabularies encode depth
   in trailing zeros, but they do not encode it the same way, and the file's
   original defect was applying UNSPSC's rule to CPV. UNSPSC is a fixed
   four-level hierarchy of digit pairs - segment ``XX000000``, family
   ``XXXX0000``, class ``XXXXXX00``, commodity ``XXXXXXXX``. CPV under
   Regulation (EC) No 2195/2002 splits at odd positions - division (2 digits),
   group (3), class (4), category (5).
2. A declared ``parent_code`` names a row that is in the file. A parent nothing
   resolves to is a broken edge in the tree the API serves.
3. A declared ``parent_code`` is the *nearest declared ancestor* of its code: a
   strict structural prefix, with no nearer ancestor that the file also
   declares. This is what catches a flattened tree - a row parked directly on
   the segment while its real class sits two lines above it.
4. ``(scheme, code)`` is unique. ``models.CommodityCode`` carries exactly this
   as a ``UniqueConstraint``, but the loader upserts row by row, so a duplicate
   in the CSV does not raise: the later line silently overwrites the earlier
   one and the row count still reports both.

What is deliberately NOT asserted, stated here so nobody later reads this as a
completeness check. This file is a curated construction subset of two very large
vocabularies, not a closed tree, and it is not the place to decide it should
become one:

* That a code exists in the published vocabulary. That needs the vocabulary, it
  is not derivable from the file, and it is the question the census answered by
  hand against the official code list.
* That the label is the official title for the code.
* That every code's family or segment is itself present as a row. Requiring
  that would mean adding rows for ancestors whose official titles nobody here
  has, and inventing titles is how the file got into this state. Rule 3 gets
  the achievable half of it: an ancestor the file *does* declare may not be
  skipped.
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

CSV_PATH = (
    Path(__file__).resolve().parents[2] / "app" / "modules" / "supplier_catalogs" / "data" / "unspsc_construction.csv"
)

#: Digit widths at which each vocabulary starts a new level, broadest first.
#: UNSPSC splits on pairs; CPV splits on single digits after the division.
_ANCESTOR_WIDTHS: dict[str, tuple[int, ...]] = {
    "unspsc": (2, 4, 6),
    "cpv": (2, 3, 4, 5),
}


def _rows() -> list[dict[str, str]]:
    with CSV_PATH.open(encoding="utf-8", newline="") as fh:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(fh)]


def _level_from_shape(scheme: str, code: str) -> int:
    """Depth the code itself declares, by where its trailing zeros begin."""
    widths = _ANCESTOR_WIDTHS[scheme]
    for depth, width in enumerate(widths, start=1):
        if code[width:] == "0" * (len(code) - width):
            return depth
    return len(widths) + 1


def _ancestors(scheme: str, code: str) -> list[str]:
    """Structural ancestors of ``code``, broadest first, excluding itself."""
    out: list[str] = []
    for width in _ANCESTOR_WIDTHS[scheme]:
        candidate = code[:width].ljust(len(code), "0")
        if candidate != code and candidate not in out:
            out.append(candidate)
    return out


def test_the_seed_still_carries_the_rows_the_rules_below_are_about():
    """The positive half: every other test here passes on an empty file.

    The four rules below are all of the form "no row offends", and an empty
    ``_rows()`` offends nothing. Deleting the CSV, or shipping a wheel without
    it, would leave this whole file green while the lookup table customers get
    is blank. This is the one assertion that separates a working seed from a
    missing one, so it is pinned by count and by scheme rather than by "not
    empty": a seed that silently loses one vocabulary is the realistic failure,
    and ``> 0`` would not notice it.
    """
    rows = _rows()
    assert len(rows) >= 62, f"the seed shipped {len(rows)} rows, fewer than the 62 it carried"
    per_scheme = Counter(r["scheme"] for r in rows)
    assert per_scheme["unspsc"] >= 48, f"unspsc rows fell to {per_scheme['unspsc']}"
    assert per_scheme["cpv"] >= 14, f"cpv rows fell to {per_scheme['cpv']}"


def test_every_seeded_code_is_eight_digits_in_a_known_scheme():
    offenders = [
        f"{r['scheme']}:{r['code']} ({r['name']})"
        for r in _rows()
        if r["scheme"] not in _ANCESTOR_WIDTHS or not (len(r["code"]) == 8 and r["code"].isdigit())
    ]
    assert not offenders, "rows whose scheme is unknown or whose code is not 8 digits:\n" + "\n".join(offenders)


def test_no_seeded_code_is_declared_twice_in_its_scheme():
    """The loader upserts per row, so a duplicate is a silent overwrite."""
    seen = Counter((r["scheme"], r["code"]) for r in _rows())
    offenders = [f"{scheme}:{code} declared {n} times" for (scheme, code), n in sorted(seen.items()) if n > 1]
    assert not offenders, (
        "duplicate (scheme, code) pairs - the later row wins and the earlier one is lost:\n" + "\n".join(offenders)
    )


def test_every_declared_level_agrees_with_the_shape_of_its_code():
    offenders = []
    for row in _rows():
        expected = _level_from_shape(row["scheme"], row["code"])
        if row["level"] != str(expected):
            offenders.append(
                f"{row['scheme']}:{row['code']} ({row['name']}) declares level {row['level']}, shape says {expected}"
            )
    assert not offenders, f"{len(offenders)} rows declare a level their own code contradicts:\n" + "\n".join(offenders)


def test_every_declared_parent_is_a_row_of_this_file():
    known = {(r["scheme"], r["code"]) for r in _rows()}
    offenders = [
        f"{r['scheme']}:{r['code']} ({r['name']}) declares parent {r['parent_code']}, which is not in the file"
        for r in _rows()
        if r["parent_code"] and (r["scheme"], r["parent_code"]) not in known
    ]
    assert not offenders, f"{len(offenders)} rows point at a parent nothing resolves to:\n" + "\n".join(offenders)


def test_every_declared_parent_is_the_nearest_ancestor_the_file_declares():
    """A row may not skip an ancestor this same file carries.

    Absent ancestors are fine - the file is a curated subset. What is not fine
    is parking a row on the segment when its own class is three lines above it,
    which is what a hand-flattened tree looks like.
    """
    known = {(r["scheme"], r["code"]) for r in _rows()}
    offenders = []
    for row in _rows():
        scheme, code, declared = row["scheme"], row["code"], row["parent_code"]
        present = [a for a in _ancestors(scheme, code) if (scheme, a) in known]
        nearest = present[-1] if present else ""
        if declared != nearest:
            expected = nearest or "no parent (no ancestor of it is in the file)"
            offenders.append(
                f"{scheme}:{code} ({row['name']}) declares parent {declared or '(none)'}, nearest declared ancestor is {expected}"
            )
    assert not offenders, (
        f"{len(offenders)} rows declare a parent that is not their nearest declared ancestor:\n" + "\n".join(offenders)
    )
