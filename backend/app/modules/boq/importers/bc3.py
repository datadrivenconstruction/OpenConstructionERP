# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""FIEBDC-3 / BC3 BOQ importer (Spain + Hispanophone LATAM).

FIEBDC (Formato de Intercambio Estándar para Bases de Datos de
Construcción) version 3 - the de-facto BOQ exchange format used across
Spain, Mexico, Argentina, Chile, Peru, Colombia and most of LATAM.
Mandated by AENOR for Spanish public tenders. Specification:
http://www.fiebdc.es/

Records are pipe-delimited (``|``), one logical record per ``~``-prefixed
header. The records the importer cares about:

* ``~V`` - Property record (file metadata, exporter version, currency).
* ``~K`` - Coefficient record (global tax / overhead factors). Captured
  in metadata, not applied to unit rates.
* ``~C`` - Concept record. The core BOQ position. Field indices matter
  here and are worth stating rather than drawing, because a file whose
  fields land one place over parses without an error and imports a date
  as a unit rate. Counting from zero after the ``~C`` header:
  ``0`` CODE, ``1`` UNIT, ``2`` SUMMARY, ``3`` PRICE, ``6`` TYPE, with
  the date subfields in between. ``TYPE`` is ``0`` for partidas (work
  items), ``1`` for capítulos (chapter / section), ``3`` for the obra
  root and other aggregates. A file that carries no type that far along
  falls back to the shape of the code, since a capítulo code
  conventionally ends in ``#``. Our own exporter writes this same
  layout, so an exported budget re-imports.
* ``~D`` - Decomposition record. Parent → children, each child a
  ``code\\factor\\yield`` triplet. Read for the parent set only, which is
  how a concept that other concepts decompose into is told apart from a
  partida; the yields are not taken as measured quantities, that is what
  ``~M`` is for, and assembly recipes belong to the assemblies module.
* ``~T`` - Extended text record (long description for a concept).
* ``~M`` - Measurement record. ``~M|PARENT\\CHILD|...|QTY|COMMENT|``.

Encoding: the fifth field of ``~V`` (JUEGO_CARACTERES) names the character
set, ``850`` or ``437`` for the MS-DOS code pages, ``ANSI`` for Windows-1252,
``UTF-8`` in the newer revisions, and empty for the default 850. See
:func:`_decode_bc3` for how the declaration and the bytes are weighed.

Line continuation: a logical record may wrap across multiple physical
lines. The convention is "anything not starting with ``~`` is a
continuation of the previous record". We rejoin before parsing.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from app.modules.boq.importers._base import (
    ImportedBOQ,
    ImportedPosition,
    ImporterParseError,
)
from app.modules.boq.importers._encoding import decode_text_bytes, safe_float, wide_bom_codec

logger = logging.getLogger(__name__)


# FIEBDC-3 record header prefixes (always at column 0).
_HDR_VERSION = "~V"
_HDR_COEFFICIENTS = "~K"
_HDR_CONCEPT = "~C"
_HDR_DECOMPOSITION = "~D"
_HDR_TEXT = "~T"
_HDR_MEASUREMENT = "~M"
_HDR_DATA_CONFIG = "~DC"

# Concept type → semantic role.
#  0  - partida (work item / position)
#  1  - capítulo (section / chapter)
#  3  - agrupador (aggregator - generally treated as a section)
_CONCEPT_TYPE_PARTIDA = "0"
_CONCEPT_TYPE_CAPITULO = "1"


# JUEGO_CARACTERES spellings → (canonical token, Python codec).
_CHARSET_TOKENS: dict[str, tuple[str, str]] = {
    "850": ("850", "cp850"),
    "CP850": ("850", "cp850"),
    "437": ("437", "cp437"),
    "CP437": ("437", "cp437"),
    "ANSI": ("ANSI", "cp1252"),
    "1252": ("ANSI", "cp1252"),
    "CP1252": ("ANSI", "cp1252"),
    "WINDOWS-1252": ("ANSI", "cp1252"),
    "WIN1252": ("ANSI", "cp1252"),
    "UTF-8": ("UTF-8", "utf-8"),
    "UTF8": ("UTF-8", "utf-8"),
    "ISO-8859-1": ("ISO-8859-1", "latin-1"),
    "8859-1": ("ISO-8859-1", "latin-1"),
}
_CODEC_BY_TOKEN: dict[str, str] = dict(_CHARSET_TOKENS.values())

# The JUEGO_CARACTERES field is the fifth after ``~V``. Our own exporter and
# some others put it one or two fields later, so those are read when the
# fifth holds no charset.
_CHARSET_FIELD = 4
_CHARSET_FIELD_FALLBACKS = (5, 6, 7)

# The letters a Spanish budget is written in, which tell code page 850 from
# Windows-1252 when the header names neither: each decodes the other's
# accented vowels into box drawings and currency signs.
_SPANISH_LETTERS = frozenset("áéíóúñüÁÉÍÓÚÑÜ¿¡ºª")


def declared_bc3_charset(content: bytes) -> str | None:
    """The charset the file's ``~V`` record declares, as a canonical token.

    Returns ``"850"``, ``"437"``, ``"ANSI"``, ``"UTF-8"`` or ``"ISO-8859-1"``,
    ``""`` when there is a ``~V`` record that names none (the field is empty
    or holds something else), and ``None`` when there is no ``~V`` record.
    The record is ASCII up to its free-text fields, so the bytes are read as
    Latin-1, which cannot fail.
    """
    head = content[:8192]
    if head.startswith(b"\xef\xbb\xbf"):
        head = head[3:]
    text = head.decode("latin-1")
    for line in text.splitlines():
        stripped = line.lstrip()
        if not stripped.startswith(_HDR_VERSION):
            continue
        fields = [field.strip().upper() for field in stripped.split("|")[1:]]
        for index in (_CHARSET_FIELD, *_CHARSET_FIELD_FALLBACKS):
            if index < len(fields) and fields[index] in _CHARSET_TOKENS:
                return _CHARSET_TOKENS[fields[index]][0]
        return ""
    return None


def _spanish_score(text: str) -> int:
    return sum(1 for char in text if char in _SPANISH_LETTERS)


def _decode_bc3(content: bytes) -> tuple[str, str, str | None]:
    """Decode a BC3 upload. Returns ``(text, codec used, declared charset)``.

    In order:

    * A byte-order mark names the encoding outright.
    * Bytes that are valid UTF-8 and not plain ASCII are UTF-8 whatever the
      header says: text in a single-byte code page with accented letters is
      almost never valid UTF-8, and a converted file often keeps its old
      header.
    * A declared charset decodes the file.
    * With none declared, code page 850 (the standard's default) and
      Windows-1252 (what most Windows programs write without saying so) are
      both tried, and the one that reads more Spanish letters wins, ties to
      Windows-1252. Code page 437 is never guessed.
    * The shared probe of :func:`decode_text_bytes` is the last resort.
    """
    declared = declared_bc3_charset(content)
    if content.startswith(b"\xef\xbb\xbf") or wide_bom_codec(content) is not None:
        text, used = decode_text_bytes(content)
        return text, used, declared
    if not content.isascii():
        try:
            return content.decode("utf-8"), "utf-8", declared
        except UnicodeDecodeError:
            pass
    codec = _CODEC_BY_TOKEN.get(declared or "")
    if codec is not None:
        try:
            return content.decode(codec), codec, declared
        except UnicodeDecodeError:
            pass
    else:
        candidates: list[tuple[int, int, str, str]] = []
        for rank, guess in enumerate(("cp1252", "cp850")):
            try:
                decoded = content.decode(guess)
            except UnicodeDecodeError:
                continue
            candidates.append((_spanish_score(decoded), -rank, decoded, guess))
        if candidates:
            _, _, text, used = max(candidates)
            return text, used, declared
    text, used = decode_text_bytes(content)
    return text, used, declared


def _split_logical_records(text: str) -> list[str]:
    """Split a BC3 text buffer into logical (``~``-headed) records.

    BC3 records may span multiple physical lines. The de-facto rule:
    a line that does not start with ``~`` is a continuation of the
    previous record. We join continuations with a single space so the
    pipe-split below still works.
    """
    records: list[str] = []
    current: list[str] = []
    for raw_line in text.splitlines():
        # Strip trailing CR (Windows line endings) and surrounding whitespace.
        line = raw_line.rstrip("\r").rstrip()
        if not line:
            continue
        if line.startswith("~"):
            if current:
                records.append(" ".join(current))
            current = [line]
        else:
            # Continuation line.
            if current:
                current.append(line)
            else:
                # Stray line before any header - ignore.
                continue
    if current:
        records.append(" ".join(current))
    return records


def _split_fields(record: str) -> list[str]:
    """Split one logical record into pipe-separated fields.

    Trailing trailing ``|`` is conventional in BC3 (every field is
    terminated, not separated). We tolerate either style by stripping
    trailing empty fields.
    """
    # Drop the header token (``~V``, ``~C`` etc.).
    if record.startswith("~"):
        # Header is the leading run of ASCII letters after ``~``.
        idx = 1
        while idx < len(record) and record[idx].isalpha():
            idx += 1
        body = record[idx:]
        # If a ``|`` immediately follows the header we drop it.
        if body.startswith("|"):
            body = body[1:]
    else:
        body = record
    fields = body.split("|")
    # Strip trailing empty fields (trailing ``|`` style).
    while fields and fields[-1].strip() == "":
        fields.pop()
    return [f.strip() for f in fields]


def _record_header(record: str) -> str:
    """Return the ``~X`` header token of a record."""
    if not record.startswith("~"):
        return ""
    idx = 1
    while idx < len(record) and record[idx].isalpha():
        idx += 1
    return record[:idx]


def _normalise_unit(unit: str) -> str:
    """Map common Spanish BC3 unit abbreviations to internal tokens.

    BC3 uses Spanish unit codes by convention: ``m``, ``m2``, ``m3``,
    ``ml`` (metro lineal → ``m``), ``kg``, ``t`` (tonelada),
    ``ud``/``u`` (unidad → ``pcs``), ``pa`` (partida alzada → ``lsum``).
    """
    key = unit.strip().lower()
    if not key:
        return ""
    mapping = {
        "ml": "m",
        "ud": "pcs",
        "uds": "pcs",
        "u": "pcs",
        "pa": "lsum",
        "ha": "ha",
        "h": "hour",
        "hr": "hour",
        "kg": "kg",
        "t": "t",
        "l": "l",
    }
    return mapping.get(key, key)


def _looks_like_section_code(code: str) -> bool:
    """BC3 capítulo codes typically end with ``#`` or are short alphanumeric
    (e.g. ``01#``, ``01.02#``). Used as a fallback when ``~C`` records do
    not carry an explicit type field.
    """
    return code.endswith("#") or code.endswith(".")


class BC3Importer:
    """FIEBDC-3 (BC3) native importer."""

    format_id: ClassVar[str] = "bc3"
    extensions: ClassVar[tuple[str, ...]] = (".bc3",)
    display_name: ClassVar[str] = "FIEBDC-3 (BC3)"
    rule_packs: ClassVar[tuple[str, ...]] = ("bc3", "masterformat", "boq_quality")

    @classmethod
    def detect(cls, head_bytes: bytes, filename: str) -> bool:
        """Detect by ``.bc3`` extension or a ``~V`` header in the first KB.

        FIEBDC-3 files always start with the ``~V`` Version/Property
        record - that's the cheapest content sniff. We sample 2 KB to
        survive UTF-8 BOMs / leading whitespace.
        """
        if not head_bytes:
            return False
        name = filename.lower()
        if any(name.endswith(ext) for ext in cls.extensions):
            return True
        # Content sniff for .txt uploads carrying a BC3 payload.
        try:
            head_text, _ = decode_text_bytes(head_bytes[:2048])
        except UnicodeDecodeError:
            return False
        # The very first record in a valid BC3 file is ``~V``. Some
        # exporters precede it with a UTF-8 BOM (handled by
        # ``decode_text_bytes("utf-8-sig")``).
        stripped = head_text.lstrip()
        return stripped.startswith("~V") or "\n~V" in head_text[:2048]

    @classmethod
    async def parse(cls, content: bytes, *, locale: str = "en") -> ImportedBOQ:
        """Parse a BC3 buffer into :class:`ImportedBOQ`."""
        if not content:
            raise ImporterParseError("BC3 upload is empty", code="bc3_empty_file")

        try:
            text, encoding_used, declared_charset = _decode_bc3(content)
        except UnicodeDecodeError as exc:
            raise ImporterParseError(
                f"BC3 file uses an unsupported encoding: {exc}", code="bc3_encoding_unknown"
            ) from exc

        records = _split_logical_records(text)
        if not records:
            raise ImporterParseError("BC3 file contains no recognisable records", code="bc3_no_records")

        # First pass: collect concept records into a map keyed by code so
        # ~T (extended text) and ~M (measurements) records can backfill
        # description + quantity later.
        concepts: dict[str, dict[str, Any]] = {}
        extended_texts: dict[str, str] = {}
        # parent → list[(child_code, qty)] from ~D records, so we can
        # determine which concepts are leaf partidas (vs capítulos that
        # decompose into other concepts) and pull a measurement quantity.
        decompositions: dict[str, list[tuple[str, float]]] = {}
        currency = ""

        for rec in records:
            hdr = _record_header(rec)
            fields = _split_fields(rec)

            if hdr == _HDR_VERSION:
                # ``~V|PROPERTY|VERSION_FMT|VERSION_PROG|FECHA|COMENT|TIPO|CHARSET|``
                # Modern exporters stash the project currency in a sub-field;
                # we sniff the trailing fields for a 3-letter ISO code.
                for f in fields:
                    f_up = f.strip().upper()
                    if (
                        len(f_up) == 3
                        and f_up.isalpha()
                        and f_up
                        in (
                            "EUR",
                            "USD",
                            "MXN",
                            "ARS",
                            "CLP",
                            "PEN",
                            "COP",
                            "BRL",
                        )
                    ):
                        currency = f_up
                        break

            elif hdr == _HDR_CONCEPT:
                # ``~C|CODE|UNIT|SUMMARY|PRICE|DATE|DATE|TYPE|`` - see the module
                # docstring for why the indices are spelled out. PRICE is 3 and
                # TYPE is 6; a file that puts either one field over still parses,
                # and the damage is silent.
                if not fields:
                    continue
                code = fields[0]
                if not code:
                    continue
                unit = fields[1] if len(fields) > 1 else ""
                summary = fields[2] if len(fields) > 2 else ""
                price = fields[3] if len(fields) > 3 else ""
                # date is fields[4] - we don't use it.
                concept_type = fields[6] if len(fields) > 6 else ""
                concepts[code] = {
                    "code": code,
                    "unit": unit,
                    "summary": summary,
                    "price": price,
                    "type": concept_type,
                }

            elif hdr == _HDR_TEXT:
                # ``~T|CODE|EXTENDED_TEXT|``
                if len(fields) >= 2:
                    extended_texts[fields[0]] = fields[1]

            elif hdr == _HDR_DECOMPOSITION:
                # ``~D|PARENT|CHILD\FACTOR\QTY\...|``
                # Children are slash-separated triplets in one field.
                if len(fields) < 2:
                    continue
                parent = fields[0]
                # The legacy format puts every child triplet in one
                # pipe-delimited subfield separated by ``\``.
                children_blob = "|".join(fields[1:])
                parts = [p for p in children_blob.split("\\") if p]
                # Iterate triplets: code, factor, qty.
                triplets = [parts[i : i + 3] for i in range(0, len(parts), 3)]
                decompositions.setdefault(parent, [])
                for trip in triplets:
                    if len(trip) >= 3:
                        decompositions[parent].append((trip[0], safe_float(trip[2], default=0.0)))

            elif hdr == _HDR_MEASUREMENT:
                # ``~M|PARENT\CHILD|POSITIONS|TOTAL_QTY|COMMENT|``
                # ``PARENT\CHILD`` lives in the first field, backslash-split.
                # ``POSITIONS`` (count of measurement entries) is field[1],
                # ``TOTAL_QTY`` is field[2]. We prefer field[2] when present
                # to avoid misreading the POSITIONS counter as the qty.
                if not fields:
                    continue
                parent_child = fields[0].split("\\")
                if len(parent_child) < 2:
                    continue
                child = parent_child[1].strip()
                if not child:
                    continue
                # FIEBDC-3 spec: TOTAL_QTY is field[2]. Some exporters
                # (especially partial / pre-computed measurements) skip
                # the POSITIONS counter and ship only the qty; we then
                # fall back to the first positive numeric field.
                qty = 0.0
                if len(fields) >= 3:
                    parsed = safe_float(fields[2], default=float("nan"))
                    if parsed == parsed and parsed > 0:
                        qty = parsed
                if qty == 0.0:
                    for f in fields[1:]:
                        parsed = safe_float(f, default=float("nan"))
                        if parsed == parsed and parsed > 0:
                            qty = parsed
                            break
                # Attach to the concept (overrides any previous measurement
                # - last writer wins, matching FIEBDC reference behaviour).
                if child in concepts:
                    concepts[child]["measured_qty"] = qty

        # Identify leaf partidas: a concept is a partida if (a) its type
        # field is ``0`` or empty AND it is not itself a decomposition
        # parent, OR (b) its type field is explicitly ``0``.
        result = ImportedBOQ(source_format="bc3", currency=currency)
        decomp_parents = set(decompositions.keys())
        auto_ord = 0

        for code, concept in concepts.items():
            ctype = concept.get("type", "")
            is_section = ctype == _CONCEPT_TYPE_CAPITULO or (not ctype and _looks_like_section_code(code))
            if is_section:
                # Emit section row so the editor preserves the BC3
                # chapter hierarchy.
                auto_ord += 1
                description = concept.get("summary", "") or extended_texts.get(code, "")
                if not description:
                    result.skipped += 1
                    continue
                result.positions.append(
                    ImportedPosition(
                        description=description,
                        ordinal=code,
                        unit="section",
                        quantity=0.0,
                        unit_rate=0.0,
                        classification={"bc3_code": code},
                        source="bc3_import",
                        metadata={
                            "bc3_code": code,
                            "bc3_type": "capitulo",
                            "bc3_currency": currency,
                        },
                        is_section=True,
                    )
                )
                continue

            # Partida (work item).
            # Skip concepts that are pure aux-resources (decomposed into
            # by something but not themselves a partida).
            if code in decomp_parents and ctype not in (
                "",
                _CONCEPT_TYPE_PARTIDA,
            ):
                result.skipped += 1
                continue

            auto_ord += 1
            description = (concept.get("summary", "") or extended_texts.get(code, "") or "").strip()
            if not description:
                result.skipped += 1
                continue

            unit_raw = concept.get("unit", "") or ""
            unit = _normalise_unit(unit_raw) or "pcs"
            unit_rate = safe_float(concept.get("price"), default=0.0)
            quantity = safe_float(concept.get("measured_qty", 0), default=0.0)

            # Sanity caps.
            if not (0 <= quantity <= 1e9):
                result.errors.append({"ordinal": code, "error": f"Quantity out of range: {quantity}"})
                continue
            if not (0 <= unit_rate <= 1e8):
                result.errors.append({"ordinal": code, "error": f"Unit rate out of range: {unit_rate}"})
                continue

            metadata: dict[str, Any] = {
                "bc3_code": code,
                "bc3_unit_original": unit_raw,
                "bc3_currency": currency,
                "bc3_encoding": encoding_used,
            }
            ext_text = extended_texts.get(code)
            if ext_text and ext_text != description:
                metadata["bc3_extended_text"] = ext_text

            result.positions.append(
                ImportedPosition(
                    description=description,
                    ordinal=code,
                    unit=unit,
                    quantity=quantity,
                    unit_rate=unit_rate,
                    classification={"bc3_code": code},
                    source="bc3_import",
                    metadata=metadata,
                )
            )

        result.metadata = {
            "bc3_encoding": encoding_used,
            "bc3_declared_charset": declared_charset,
            "bc3_concepts": len(concepts),
            "bc3_extended_texts": len(extended_texts),
            "bc3_decompositions": len(decompositions),
        }
        return result
