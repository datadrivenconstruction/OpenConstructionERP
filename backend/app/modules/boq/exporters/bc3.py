# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""FIEBDC-3 / BC3 BOQ exporter (Spain + Hispanophone LATAM).

The inverse of :mod:`app.modules.boq.importers.bc3`. Turns a priced
``BOQWithSections`` into a FIEBDC-3 (BC3) budget file that opens in the
Spanish/LATAM estimating tools and re-imports losslessly through our own
parser.

FIEBDC (Formato de Intercambio Estandar para Bases de Datos de
Construccion) version 3 is the de-facto BOQ exchange format across Spain,
Mexico, Argentina, Chile, Peru and Colombia, mandated by AENOR for
Spanish public tenders. Records are ``~``-headed and pipe-delimited.

The document we emit:

* ``~V`` - property/version record with the charset and the project
  currency.
* ``~C`` - one concept per node: an ``obra`` root (``TYPE=3``), a
  ``capitulo`` per BOQ section (``TYPE=1``) and a ``partida`` per BOQ
  position (``TYPE=0``). Field order is
  ``~C|CODE|UNIT|SUMMARY|PRICE||​|TYPE|`` - ``TYPE`` sits at field index 6
  (two reserved date fields follow ``PRICE``), matching both the FIEBDC-3
  spec and our importer's ``fields[6]`` read.
* ``~D`` - decomposition tree: the root decomposes into its chapters (and
  any ungrouped partidas), each chapter into its partidas. This is what a
  receiving tool uses to build the budget hierarchy.
* ``~T`` - extended (long) text for a concept, when present.
* ``~M`` - one measurement per priced partida
  (``~M|PARENT\\CHILD|POSITIONS|TOTAL_QTY|COMMENT|``) carrying the
  quantity.

Scope: this exports the priced partida budget (direct costs) with full
hierarchy, codes, units, quantities, unit rates and long texts. Overhead /
profit / VAT are applied by the receiving tool from its own coefficient
settings (FIEBDC ``~K``), matching how our importer treats those factors
as informational rather than baking them into the unit rates.

Encoding: FIEBDC files ship in CP1252 (Windows-1252) by convention, so we
emit CP1252 whenever the whole document fits it (the widest compatibility
with the Spanish desktop tools) and fall back to UTF-8 only when a
character cannot be represented, declaring the actual charset in ``~V``.
Both round-trip losslessly through our importer, whose probe order
(``utf-8-sig`` -> ``utf-8`` -> ``cp1252`` -> ``latin-1``) decodes each
correctly.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

_PROGRAM = "OpenConstructionERP"

# FIEBDC-3 concept type codes.
_TYPE_OBRA = "3"  # aggregator / budget root
_TYPE_CAPITULO = "1"  # chapter / section
_TYPE_PARTIDA = "0"  # work item

# Internal unit token -> FIEBDC/Spanish unit convention. The inverse of the
# importer's ``_normalise_unit`` map, so a BC3-imported BOQ round-trips, plus
# sensible Spanish defaults for units created elsewhere in the product.
_UNIT_TO_BC3: dict[str, str] = {
    "m": "m",
    "cm": "cm",
    "mm": "mm",
    "km": "km",
    "m2": "m2",
    "m²": "m2",
    "sqm": "m2",
    "m3": "m3",
    "m³": "m3",
    "cbm": "m3",
    "l": "l",
    "kg": "kg",
    "t": "t",
    "g": "g",
    "pcs": "ud",
    "piece": "ud",
    "ea": "ud",
    "stk": "ud",
    "lsum": "pa",
    "psch": "pa",
    "ls": "pa",
    "lump": "pa",
    "hour": "h",
    "h": "h",
    "d": "d",
    "day": "d",
    "ha": "ha",
    "month": "mes",
    "year": "año",
}

_CODE_ALLOWED = re.compile(r"[^A-Za-z0-9._-]")


def _to_dec(value: Any) -> Decimal | None:
    """Best-effort Decimal coercion; ``None`` when not finite / parseable."""
    if value is None or value == "":
        return None
    try:
        d = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def _num(value: Any) -> str:
    """Format a numeric value for a BC3 field.

    Emits a plain, non-exponential decimal with a ``.`` separator and no
    thousands grouping, trailing zeros trimmed. Non-finite / unparseable
    inputs collapse to ``"0"``. FIEBDC data records use ``.`` as the decimal
    mark; our importer's ``safe_float`` accepts either convention.
    """
    d = _to_dec(value)
    if d is None:
        return "0"
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def _clean_text(text: Any) -> str:
    """Sanitise a free-text field for a BC3 record.

    FIEBDC reserves ``|`` (field), ``\\`` (subfield), ``~`` (record header)
    and ``#`` (grouping marker); a raw one inside a value would corrupt the
    record structure. Newlines are collapsed to spaces so a value never
    leaks into the next physical line (which the importer would treat as a
    continuation of the record).
    """
    s = str(text or "")
    s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    s = s.replace("|", "/").replace("\\", "/").replace("~", "-").replace("#", " ")
    # Collapse the runs of whitespace the substitutions may have produced.
    return re.sub(r"\s+", " ", s).strip()


def _clean_code(code: Any) -> str:
    """Coerce a concept code into FIEBDC-safe characters (``[A-Za-z0-9._-]``)."""
    c = _CODE_ALLOWED.sub("", str(code or "").strip())
    return c[:60]


def _bc3_unit(internal_unit: str, original_unit: str) -> str:
    """Map an internal unit token back to a FIEBDC/Spanish unit code.

    Prefers ``original_unit`` (the raw BC3 unit stashed at import time) so a
    round-tripped file keeps its exact unit; otherwise maps the internal
    token, falling back to the token itself for user-custom units.
    """
    if original_unit and original_unit.strip():
        return original_unit.strip()
    key = (internal_unit or "").strip().lower()
    if not key:
        return ""
    return _UNIT_TO_BC3.get(key, key)


def _encode_bc3(text: str) -> tuple[bytes, str]:
    """Encode the assembled document, preferring CP1252, else UTF-8.

    ``text`` carries a ``{{CHARSET}}`` placeholder in the ``~V`` record; we
    substitute the real charset label for whichever codec succeeds. Returns
    ``(bytes, http_charset)`` where ``http_charset`` names the codec for the
    HTTP ``Content-Type`` header.
    """
    try:
        data = text.replace("{{CHARSET}}", "ANSI").encode("cp1252")
        return data, "windows-1252"
    except UnicodeEncodeError:
        data = text.replace("{{CHARSET}}", "UTF-8").encode("utf-8")
        return data, "utf-8"


def build_bc3(
    boq_data: Any,
    *,
    project_name: str,
    project_currency: str,
    program_version: str = "",
    trace: list[dict[str, Any]] | None = None,
) -> tuple[bytes, str]:
    """Build a FIEBDC-3 (BC3) budget document from a ``BOQWithSections``.

    Pure function (no I/O) so it is unit-testable and round-trip-checkable
    against :class:`~app.modules.boq.importers.bc3.BC3Importer` without
    booting the app. ``boq_data`` only needs ``name``, ``sections`` (each
    with ``ordinal``, ``description``, ``positions``) and ``positions``
    (ungrouped) - a duck-typed ``BOQWithSections``.

    ``trace``, when given, receives one record per chapter and partida
    stating the code, unit, summary and quantity actually written, for the
    exchange fidelity report (``exchange_fidelity.analyze_bc3_export``).

    Returns ``(file_bytes, http_charset)``.
    """
    currency = (project_currency or "").strip().upper()
    currency = currency if len(currency) == 3 and currency.isalpha() else ""
    today = date.today().strftime("%d%m%Y")

    seen: set[str] = set()

    def _uniq(base: Any, fallback: str) -> str:
        """Return a unique, FIEBDC-safe code (concept codes are the file's keys)."""
        code = _clean_code(base) or _clean_code(fallback) or "C"
        cand, i = code, 2
        while cand in seen:
            cand = f"{code}_{i}"
            i += 1
        seen.add(cand)
        return cand

    concepts: list[str] = []
    decomps: list[str] = []
    texts: list[str] = []
    measures: list[str] = []
    root_children: list[str] = []  # "code\\factor\\yield" triplets

    # Reserve the root code first so a chapter/partida sharing the BOQ name
    # gets disambiguated instead of colliding with the root.
    root_code = _uniq(getattr(boq_data, "name", ""), "OBRA")

    def _emit_partida(pos: Any, parent_code: str, child_sink: list[str]) -> None:
        meta = getattr(pos, "metadata", None)
        meta = meta if isinstance(meta, dict) else {}
        classif = getattr(pos, "classification", None)
        classif = classif if isinstance(classif, dict) else {}

        base_code = (
            str(classif.get("bc3_code") or "")
            or str(getattr(pos, "reference_code", "") or "")
            or str(getattr(pos, "ordinal", "") or "")
        )
        code = _uniq(base_code, "P")

        description = str(getattr(pos, "description", "") or "")
        unit = _bc3_unit(
            str(getattr(pos, "unit", "") or ""),
            str(meta.get("bc3_unit_original") or ""),
        )
        rate = _num(getattr(pos, "unit_rate", 0))
        qty_dec = _to_dec(getattr(pos, "quantity", 0)) or Decimal(0)
        qty = _num(qty_dec) if qty_dec > 0 else "0"

        concepts.append(f"~C|{code}|{_clean_text(unit)}|{_clean_text(description)}|{rate}|||{_TYPE_PARTIDA}|")

        extended = str(meta.get("bc3_extended_text") or "")
        if not extended and "\n" in description:
            extended = description
        if extended.strip():
            texts.append(f"~T|{code}|{_clean_text(extended)}|")

        if qty_dec > 0:
            measures.append(f"~M|{parent_code}\\{code}|1|{qty}||")
        if trace is not None:
            trace.append(
                {
                    "type": "item",
                    "id": str(getattr(pos, "id", "") or ""),
                    "code": code,
                    "unit": _clean_text(unit),
                    "summary": _clean_text(description),
                    "rate": rate,
                    "qty": qty,
                    "extended": _clean_text(extended) if extended.strip() else None,
                }
            )

        # A partida appears once in its parent; carry the measured quantity as
        # the decomposition yield so a receiving tool rolls up the same total.
        child_sink.append(f"{code}\\1\\{qty}")

    # Sections -> chapters (capitulos).
    for section in getattr(boq_data, "sections", None) or []:
        chap_code = _uniq(getattr(section, "ordinal", ""), "CAP")
        chap_desc = str(getattr(section, "description", "") or "")
        concepts.append(f"~C|{chap_code}||{_clean_text(chap_desc)}|0|||{_TYPE_CAPITULO}|")
        if trace is not None:
            trace.append(
                {
                    "type": "section",
                    "id": str(getattr(section, "id", "") or ""),
                    "code": chap_code,
                    "summary": _clean_text(chap_desc),
                }
            )
        root_children.append(f"{chap_code}\\1\\1")

        chap_children: list[str] = []
        for pos in getattr(section, "positions", None) or []:
            _emit_partida(pos, chap_code, chap_children)
        if chap_children:
            decomps.append(f"~D|{chap_code}|" + "\\".join(chap_children) + "|")

    # Ungrouped positions -> partidas directly under the root.
    for pos in getattr(boq_data, "positions", None) or []:
        _emit_partida(pos, root_code, root_children)

    # Root concept (obra) first, then its decomposition into chapters +
    # ungrouped partidas. The importer skips the ``TYPE=3`` root because it is
    # a decomposition parent - so we only emit it when it actually has
    # children. An empty budget is just a ``~V`` header; emitting a childless
    # root would have no ``~D`` and would then re-import as a phantom partida.
    if root_children:
        root_summary = _clean_text(getattr(boq_data, "name", "") or project_name or "Budget")
        concepts.insert(0, f"~C|{root_code}||{root_summary}|0|||{_TYPE_OBRA}|")
        decomps.insert(0, f"~D|{root_code}|" + "\\".join(root_children) + "|")

    # ~V property record. The currency sits in its own field so the importer's
    # 3-letter currency sniff picks it up regardless of exact position.
    prog = f"{_PROGRAM}\\{_clean_code(program_version)}" if program_version else _PROGRAM
    filename = _clean_text(project_name)[:40] or _PROGRAM
    header = (
        f"~V|{filename}|FIEBDC-3/2020|{prog}|{today}|"
        f"{_clean_text(project_name) or _PROGRAM}|{{{{CHARSET}}}}|2||{currency}|"
    )

    body = [header, *concepts, *decomps, *texts, *measures]
    text = "\r\n".join(body) + "\r\n"
    return _encode_bc3(text)
