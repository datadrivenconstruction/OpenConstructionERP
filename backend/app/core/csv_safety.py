"""CSV / spreadsheet formula-injection neutralisation.

Spreadsheet applications (Excel, Google Sheets, LibreOffice Calc) interpret
any cell whose textual value begins with ``=``, ``+``, ``-``, ``@``, a tab
(``\\t``) or a carriage return (``\\r``) as a *formula*. A malicious user
who controls a string field that later flows into an export — a BOQ
position description, a takeoff annotation, a project name — can store a
value like::

    =cmd|'/c calc'!A0

When a colleague opens the exported ``.csv`` / ``.xlsx`` Excel will execute
the formula. Depending on the user's macro / DDE settings this ranges from
"phishing-quality misleading content" to outright RCE
(`CVE-2014-3524 <https://owasp.org/www-community/attacks/CSV_Injection>`_).

The OWASP-recommended fix is **output-side neutralisation**: when writing a
cell value, if the string starts with one of the dangerous characters,
prepend a single apostrophe (``'``). Excel hides that apostrophe in the
rendered cell but treats the remaining content as literal text.

We deliberately do *not* mutate the data at rest — sanitising on read /
write of the database would corrupt legitimate formula-prefixed text and
break round-trips for CSVs that the user explicitly wants to re-import. The
defence belongs at the export boundary.

Usage::

    from app.core.csv_safety import neutralise_formula

    writer.writerow([neutralise_formula(pos.description), ...])
    ws.cell(row=r, column=c, value=neutralise_formula(pos.description))

Numbers, ``Decimal``, ``None`` and other non-string types pass through
unchanged — they cannot be misinterpreted as formulae by the spreadsheet
software.
"""

from __future__ import annotations

from typing import Any, Final

__all__ = ["neutralise_formula"]


# Characters that trigger formula evaluation when they appear as the first
# character of a cell's string value. Tab and carriage return are included
# because Excel strips leading whitespace before parsing, so ``"\t=SUM(..)"``
# is also dangerous.
_DANGEROUS: Final[tuple[str, ...]] = ("=", "+", "-", "@", "\t", "\r")


def neutralise_formula(value: Any) -> Any:
    """Return *value* with a leading apostrophe added if it would be parsed
    as a spreadsheet formula.

    Only ``str`` values are modified, and only when the first character is
    one of :data:`_DANGEROUS`. Everything else (``None``, numbers, ``Decimal``,
    arbitrary objects) is returned unchanged so the caller can apply this
    helper unconditionally to every cell.

    Examples:
        >>> neutralise_formula("=SUM(A1:B1)")
        "'=SUM(A1:B1)"
        >>> neutralise_formula("Concrete C30/37")
        'Concrete C30/37'
        >>> neutralise_formula(None) is None
        True
        >>> neutralise_formula(42)
        42
    """
    if isinstance(value, str) and value and value[0] in _DANGEROUS:
        return "'" + value
    return value
