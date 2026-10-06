# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""XPWE (Italian estimating XML) importer.

XPWE is the XML exchange file Italian estimating programs write next to their
native project file. It carries both halves of an Italian estimate: the price
list the estimate is priced from (elenco prezzi) and the measured bill itself
(computo metrico), with every measurement row of the libretto delle misure.
No public specification or schema exists. The element names below were checked
against a file-type signature built from ten real exports and against two
independent open-source readers, and the parser is written to the shape those
three agree on. Where they disagree, the choice is stated at the point it is
made.

Layout, with ``ID`` as the only attribute anywhere in the file::

    PweDocumento
      PweDatiGenerali
        PweDGProgetto/PweDGDatiGenerali     Oggetto, Comune, Provincia, Committente
        PweDGCapitoliCategorie
          PweDGSuperCapitoli/DGSuperCapitoliItem ...   price-list chapter tree
          PweDGSuperCategorie/DGSuperCategorieItem ... bill (computo) tree
        PweDGModuli/PweDGAnalisi            SpeseGenerali, UtiliImpresa
        PweDGConfigurazione/PweDGConfigNumeri  Divisa, decimals per field
        PweDGWBS/DGWBSItem                  optional work breakdown
      PweMisurazioni
        PweElencoPrezzi/EPItem              Tariffa, DesEstesa, UnMisura, Prezzo1,
                                            IDSpCap/IDCap/IDSbCap, IncMDO ...
        PweVociComputo/VCItem               IDEP, Quantita, IDSpCat/IDCat/IDSbCat,
                                            PweVCMisure/RGItem (measurement rows)

Everything is joined by integer id: ``VCItem/IDEP`` names its price-list item,
and the three ``ID*Cat`` fields name the bill's super-category, category and
sub-category. The two halves come in either order, so the reader collects both
before it joins them.

The parse is a streaming one. A full element tree of a regional price list
exported to XPWE (tens of megabytes, every item with its analysis) costs
several times the file size, which the 3 GB server cannot spare next to the
database. Each record is read when its closing tag arrives and then detached,
so what stays in memory is the extracted values, not the tree.

Quantities are computed from the measurement rows, each row being
PartiUguali x Lunghezza x Larghezza x HPeso with an empty factor counting as 1.
``RGItem/Quantita`` is never summed: one reader takes it as the row value, the
other as the item total repeated on every row, and summing the second reading
multiplies the bill. Its leading minus sign is read, because both readers agree
that is how a deduction row is marked. The total is then checked against the
item's own declared ``Quantita`` and a difference is reported, not hidden.

The native project file is a proprietary compressed container with no
published layout. It is claimed here only so it can be refused with a message
that says what to do (export XPWE from the estimating program) instead of
falling through to the model-assisted import.
"""

from __future__ import annotations

import asyncio
import codecs
import io
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import IO, Any, ClassVar

from app.modules.boq.importers._base import (
    ImportedBOQ,
    ImportedPosition,
    ImporterParseError,
    xml_error_position,
)
from app.modules.boq.importers._encoding import decode_text_bytes

logger = logging.getLogger(__name__)

ROOT_TAG = "PweDocumento"

# ``EPItem/Flags`` bit that marks a safety-cost item (oneri della sicurezza),
# which an Italian tender keeps out of the discount.
SAFETY_FLAG = 0x8000000
# ``RGItem/Flags`` bit of a partial-subtotal row: a printed running total, not a
# measurement, so it contributes nothing.
SUBTOTAL_FLAG = 2

# The longest description a position stores (``PositionCreate.description``).
_MAX_DESCRIPTION = 5000
# A measurement expression longer than this is not a hand-written factor.
_MAX_EXPRESSION = 200
# One kind of warning is listed at most this many times; the rest are counted.
_MAX_WARNINGS_PER_CODE = 200
# No factor, row or item quantity of a real bill comes near this. Past it a
# value is a typing slip or a hostile file, and rounding it to the declared
# decimals would run out of digits.
_MAX_MAGNITUDE = Decimal("1e10")
# A line amount is kept to the places a stored position total keeps.
_AMOUNT_QUANTUM = Decimal("0.0001")

# Group tags -> (tree, level). Level 0 is the super group, 2 the sub group.
_GROUP_TAGS: dict[str, tuple[str, int]] = {
    "DGSuperCapitoliItem": ("chapter", 0),
    "DGCapitoliItem": ("chapter", 1),
    "DGSubCapitoliItem": ("chapter", 2),
    "DGSuperCategorieItem": ("category", 0),
    "DGCategorieItem": ("category", 1),
    "DGSubCategorieItem": ("category", 2),
}

# Project header fields, by the key the import metadata carries them under.
_HEADER_KEYS: dict[str, str] = {
    "Oggetto": "title",
    "Committente": "client",
    "Impresa": "contractor",
    "Comune": "municipality",
    "Provincia": "province",
    "PercPrezzi": "price_adjustment_pct",
}

# Italian unit spellings an estimate uses, folded onto the canonical units.
# Anything not listed passes through ``normalise_unit`` at persistence.
_UNIT_ALIASES: dict[str, str] = {
    "mq": "m2",
    "m²": "m2",
    "m2": "m2",
    "mc": "m3",
    "m³": "m3",
    "m3": "m3",
    "ml": "m",
    "m": "m",
    "cad": "pcs",
    "cad.": "pcs",
    "n": "pcs",
    "n.": "pcs",
    "nr": "pcs",
    "nr.": "pcs",
    "pz": "pcs",
    "ora": "hr",
    "ore": "hr",
    "h": "hr",
    "a corpo": "lsum",
    "corpo": "lsum",
    "a.c.": "lsum",
    "kg": "kg",
    "t": "t",
    "gg": "day",
    "giorno": "day",
    "giorni": "day",
    "l": "l",
}

_PLAIN_NUMBER = re.compile(r"^[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)$")
_DOT_GROUPED_COMMA_DECIMAL = re.compile(r"^[+-]?\d{1,3}(?:\.\d{3})+,\d+$")
_COMMA_GROUPED_DOT_DECIMAL = re.compile(r"^[+-]?\d{1,3}(?:,\d{3})+\.\d+$")
_NUMBER_TOKEN = re.compile(r"\d[\d.,]*\d|\d")
_EXPRESSION_CHARS = re.compile(r"^[\d\s.,+\-*/()xX×]+$")
_DECLARED_ENCODING = re.compile(rb"<\?xml[^>]*encoding\s*=\s*[\"']([A-Za-z0-9._-]+)[\"']")


class XpweNativeFileError(ImporterParseError):
    """The upload is not XML: a native project file rather than its XPWE export."""


class _UnreadableFactor(ValueError):
    """A measurement factor that is neither a number nor an expression we can evaluate."""


# ── Extracted records ────────────────────────────────────────────────────────


@dataclass(slots=True)
class XpweGroup:
    """One node of a chapter, category or WBS tree."""

    kind: str
    level: int
    id: str
    index: int
    code: str
    title: str


@dataclass(slots=True)
class XpwePriceItem:
    """One price-list item (``EPItem``)."""

    id: str
    code: str
    description: str
    short_description: str
    unit: str
    price_text: str
    chapter_ids: tuple[str, str, str]
    flags: int
    kind: str = ""
    article: str = ""
    date: str = ""
    # The same shares two ways: fractions as strings for a bill line's
    # metadata, percentages as the file states them for a price list.
    shares: dict[str, str] = field(default_factory=dict)
    share_pcts: dict[str, Decimal] = field(default_factory=dict)
    analysis: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_safety(self) -> bool:
        return bool(self.flags & SAFETY_FLAG)


@dataclass(slots=True)
class XpweMeasureRow:
    """One measurement row (``RGItem``) of a bill item."""

    id: str
    ref: str
    description: str
    factors: tuple[str, str, str, str]
    quantity_text: str
    flags: int


@dataclass(slots=True)
class XpweWorkItem:
    """One measured bill item (``VCItem``)."""

    id: str
    price_id: str
    quantity_text: str
    date: str
    category_ids: tuple[str, str, str]
    wbs_code: str
    rows: list[XpweMeasureRow]
    order: int


@dataclass(slots=True)
class XpweDocument:
    """Everything the reader extracted, before it is shaped into a bill or a price list."""

    encoding: str = "utf-8"
    header: dict[str, str] = field(default_factory=dict)
    currency: str = ""
    decimals: dict[str, int] = field(default_factory=dict)
    overheads: dict[str, str] = field(default_factory=dict)
    groups: dict[tuple[str, int, str], XpweGroup] = field(default_factory=dict)
    wbs: dict[str, dict[str, str]] = field(default_factory=dict)
    price_items: dict[str, XpwePriceItem] = field(default_factory=dict)
    work_items: list[XpweWorkItem] = field(default_factory=list)
    # Set once the chapter and category tree has been read in full.
    chapters_complete: bool = False

    def chapter_path(self, item: XpwePriceItem) -> list[XpweGroup]:
        """The price-list chapters an item sits in, top level first."""
        return _path_of(self, "chapter", item.chapter_ids)


# ── Low-level readers ────────────────────────────────────────────────────────


def _local(tag: Any) -> str:
    text = str(tag)
    return text.rsplit("}", 1)[-1]


def _child_text(elem: Any, name: str) -> str:
    child = elem.find(name)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def _int(text: str, default: int = 0) -> int:
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return default


def _id(text: str) -> str:
    """An id reference, with ``0``, negative and blank all meaning "none"."""
    value = _int(text, 0)
    return str(value) if value > 0 else ""


def plain_decimal(text: str | None) -> Decimal | None:
    """Read a plain number written with a decimal comma or a decimal point.

    Returns ``None`` for an empty value and raises ``ValueError`` for anything
    that is not a plain number. A value carrying both separators is read the
    way it is grouped ("1.234,56" and "1,234.56" are both 1234.56).
    """
    if text is None:
        return None
    value = str(text).strip().replace(" ", "").replace(" ", "")
    if not value:
        return None
    try:
        if _PLAIN_NUMBER.match(value):
            return Decimal(value.replace(",", "."))
        if _DOT_GROUPED_COMMA_DECIMAL.match(value):
            return Decimal(value.replace(".", "").replace(",", "."))
        if _COMMA_GROUPED_DOT_DECIMAL.match(value):
            return Decimal(value.replace(",", ""))
    except InvalidOperation as exc:
        raise ValueError(f"not a number: {text!r}") from exc
    raise ValueError(f"not a number: {text!r}")


def _decimal_or_none(text: str | None) -> Decimal | None:
    try:
        return plain_decimal(text)
    except ValueError:
        return None


def _normalise_expression(text: str) -> str:
    """Turn a hand-written factor such as ``2(3+4)`` or ``3,5x2`` into one the evaluator reads.

    Decimal commas become points, ``x`` and ``×`` between operands become
    ``*``, and the implicit multiplication of a number or a closing bracket
    against an opening bracket is written out.
    """
    expr = text.strip()
    if len(expr) > _MAX_EXPRESSION or not _EXPRESSION_CHARS.match(expr):
        raise _UnreadableFactor(text)
    expr = re.sub(r"(?<=[\d)])\s*[xX×]\s*(?=[\d(.])", "*", expr)
    if re.search(r"[xX×]", expr):
        raise _UnreadableFactor(text)

    def _token(match: re.Match[str]) -> str:
        try:
            number = plain_decimal(match.group(0))
        except ValueError as exc:
            raise _UnreadableFactor(text) from exc
        return format(number, "f") if number is not None else match.group(0)

    expr = _NUMBER_TOKEN.sub(_token, expr)
    expr = re.sub(r"(?<=[\d.)])\s*\(", "*(", expr)
    expr = re.sub(r"\)\s*(?=[\d.(])", ")*", expr)
    if re.search(r"\*\s*\*", expr):
        # A power: an estimator never writes one, and ``10**999999`` is a
        # number no rounding can hold.
        raise _UnreadableFactor(text)
    return expr


def _evaluate_factor(text: str) -> tuple[Decimal, str, bool]:
    """Value of one factor, the expression it is written as, and whether it is a plain number."""
    try:
        number = plain_decimal(text)
    except ValueError:
        number = None
    else:
        if number is not None:
            return number, format(number, "f"), True
    from app.modules.measurement.formula import MeasurementError, safe_eval

    expr = _normalise_expression(text)
    try:
        return safe_eval(expr), expr, False
    except MeasurementError as exc:
        raise _UnreadableFactor(text) from exc


def _is_utf8(content: bytes) -> bool:
    """Whether ``content`` decodes as UTF-8, checked in chunks so no second copy is built."""
    decoder = codecs.getincrementaldecoder("utf-8")()
    step = 1 << 20
    try:
        for start in range(0, len(content), step):
            decoder.decode(content[start : start + step], final=False)
        decoder.decode(b"", final=True)
    except UnicodeDecodeError:
        return False
    return True


def _xml_bytes(content: bytes) -> tuple[bytes, str]:
    """The bytes to hand the XML parser, and the encoding they were read in.

    An export carries no XML declaration, which makes the parser assume UTF-8.
    A file actually written in a Windows code page then fails on its first
    accented letter, so a body that is not valid UTF-8 is decoded through the
    shared probe order and handed over re-encoded.
    """
    head = content[:4096]
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return content, "utf-16"
    body = head[3:] if head.startswith(b"\xef\xbb\xbf") else head
    if not body.lstrip(b" \t\r\n").startswith(b"<"):
        raise XpweNativeFileError(
            "The file is not XML. Export it as XPWE from the estimating program.", code="xpwe_not_xml"
        )
    declared = _DECLARED_ENCODING.search(head[:256])
    if declared:
        return content, declared.group(1).decode("ascii").lower()
    if _is_utf8(content):
        return content, "utf-8"
    text, encoding = decode_text_bytes(content)
    return text.encode("utf-8"), encoding


class _Utf8Reader:
    """A binary stream in a legacy code page, handed on as UTF-8 a chunk at a time.

    The parser asks for 16 KB at a time; each read decodes only what it needs,
    so a list in cp1252 is never decoded whole.
    """

    _CHUNK = 1 << 16

    def __init__(self, raw: IO[bytes], encoding: str) -> None:
        self._raw = raw
        self._decoder = codecs.getincrementaldecoder(encoding)()
        self._buffer = b""
        self._done = False

    def read(self, size: int = -1) -> bytes:
        while not self._done and (size < 0 or len(self._buffer) < size):
            chunk = self._raw.read(self._CHUNK)
            if not chunk:
                self._buffer += self._decoder.decode(b"", final=True).encode("utf-8")
                self._done = True
            else:
                self._buffer += self._decoder.decode(chunk).encode("utf-8")
        if size < 0 or size >= len(self._buffer):
            out, self._buffer = self._buffer, b""
        else:
            out, self._buffer = self._buffer[:size], self._buffer[size:]
        return out


def _stream_decodes(stream: IO[bytes], encoding: str) -> bool:
    """Whether the rest of ``stream`` decodes in ``encoding``; read in chunks, rewound after."""
    start = stream.tell()
    decoder = codecs.getincrementaldecoder(encoding)()
    try:
        while chunk := stream.read(1 << 20):
            decoder.decode(chunk, final=False)
        decoder.decode(b"", final=True)
    except UnicodeDecodeError:
        return False
    finally:
        stream.seek(start)
    return True


def open_xml_stream(stream: IO[bytes]) -> tuple[IO[bytes], str]:
    """:func:`_xml_bytes` for a seekable stream: what to hand the parser, and the encoding, without reading the file whole.

    A declared encoding, a UTF-16 mark or a UTF-8 body is parsed straight from
    the stream. A body in a Windows code page goes through a reader that
    transcodes it to UTF-8 as the parser asks for it, in the shared probe
    order (cp1252, then latin-1, which reads anything).

    Raises:
        ImporterParseError: The stream is empty.
        XpweNativeFileError: The stream is not XML.
    """
    start = stream.tell()
    head = stream.read(4096)
    stream.seek(start)
    if not head:
        raise ImporterParseError("The XPWE file is empty.", code="xpwe_empty_file")
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return stream, "utf-16"
    body = head[3:] if head.startswith(b"\xef\xbb\xbf") else head
    if not body.lstrip(b" \t\r\n").startswith(b"<"):
        raise XpweNativeFileError(
            "The file is not XML. Export it as XPWE from the estimating program.", code="xpwe_not_xml"
        )
    declared = _DECLARED_ENCODING.search(head[:256])
    if declared:
        return stream, declared.group(1).decode("ascii").lower()
    if _stream_decodes(stream, "utf-8"):
        return stream, "utf-8"
    encoding = "cp1252" if _stream_decodes(stream, "cp1252") else "latin-1"
    return _Utf8Reader(stream, encoding), encoding  # type: ignore[return-value]


# ── The streaming reader ─────────────────────────────────────────────────────


def _read_group(elem: Any, kind: str, level: int, index: int) -> XpweGroup | None:
    group_id = _id(elem.get("ID", ""))
    if not group_id:
        return None
    title = _child_text(elem, "DesSintetica") or _child_text(elem, "DesEstesa")
    code = _child_text(elem, "Codice")
    return XpweGroup(kind=kind, level=level, id=group_id, index=index, code=code, title=title or code or group_id)


def _read_price_item(elem: Any, *, with_analysis: bool) -> XpwePriceItem | None:
    item_id = _id(elem.get("ID", ""))
    if not item_id:
        return None
    shares: dict[str, str] = {}
    share_pcts: dict[str, Decimal] = {}
    for tag, key in (("IncMDO", "labour"), ("IncSIC", "safety"), ("IncMAT", "material"), ("IncATTR", "equipment")):
        pct = _decimal_or_none(_child_text(elem, tag))
        if pct is not None and Decimal(0) <= pct <= Decimal(100):
            share_pcts[key] = pct
            shares[key] = format((pct / Decimal(100)).normalize(), "f")
    analysis: list[dict[str, Any]] = []
    if with_analysis:
        for line in elem.iter("EPARItem"):
            quantity = _decimal_or_none(_child_text(line, "Qt"))
            price = _decimal_or_none(_child_text(line, "Prezzo"))
            analysis.append(
                {
                    "ref_id": _id(_child_text(line, "IDEP")),
                    "name": _child_text(line, "Descrizione"),
                    "unit": _child_text(line, "Misura"),
                    "quantity": quantity,
                    "unit_rate": price,
                }
            )
    return XpwePriceItem(
        id=item_id,
        code=_child_text(elem, "Tariffa"),
        article=_child_text(elem, "Articolo"),
        description=_child_text(elem, "DesEstesa"),
        short_description=_child_text(elem, "DesRidotta") or _child_text(elem, "DesBreve"),
        unit=_child_text(elem, "UnMisura"),
        price_text=_child_text(elem, "Prezzo1"),
        chapter_ids=(
            _id(_child_text(elem, "IDSpCap")),
            _id(_child_text(elem, "IDCap")),
            _id(_child_text(elem, "IDSbCap")),
        ),
        flags=_int(_child_text(elem, "Flags")),
        kind=_child_text(elem, "TipoEP"),
        date=_child_text(elem, "Data"),
        shares=shares,
        share_pcts=share_pcts,
        analysis=analysis,
    )


def _read_work_item(elem: Any, order: int) -> XpweWorkItem | None:
    item_id = _id(elem.get("ID", ""))
    if not item_id:
        return None
    rows: list[XpweMeasureRow] = []
    for row in elem.iter("RGItem"):
        rows.append(
            XpweMeasureRow(
                id=str(row.get("ID", "")),
                ref=_child_text(row, "IDVV"),
                description=_child_text(row, "Descrizione"),
                factors=(
                    _child_text(row, "PartiUguali"),
                    _child_text(row, "Lunghezza"),
                    _child_text(row, "Larghezza"),
                    _child_text(row, "HPeso"),
                ),
                quantity_text=_child_text(row, "Quantita"),
                flags=_int(_child_text(row, "Flags")),
            )
        )
    return XpweWorkItem(
        id=item_id,
        price_id=_id(_child_text(elem, "IDEP")),
        quantity_text=_child_text(elem, "Quantita"),
        date=_child_text(elem, "DataMis"),
        category_ids=(
            _id(_child_text(elem, "IDSpCat")),
            _id(_child_text(elem, "IDCat")),
            _id(_child_text(elem, "IDSbCat")),
        ),
        wbs_code=_child_text(elem, "CodiceWBS"),
        rows=rows,
        order=order,
    )


def _read_config(elem: Any, doc: XpweDocument) -> None:
    """Currency and the decimals each field is rounded to ("9.3|0" means three)."""
    currency = _child_text(elem, "Divisa")
    if currency and not doc.currency:
        folded = currency.strip().lower()
        if folded in ("euro", "eur", "€"):
            doc.currency = "EUR"
        elif re.fullmatch(r"[a-z]{3}", folded):
            doc.currency = folded.upper()
    for name in ("PartiUguali", "Lunghezza", "Larghezza", "HPeso", "Quantita", "Prezzi", "PrezziTotale"):
        match = re.search(r"\.(\d+)", _child_text(elem, name))
        if match and name not in doc.decimals:
            doc.decimals[name] = min(int(match.group(1)), 9)


def read_xpwe(content: bytes, *, price_list_only: bool = False) -> XpweDocument:
    """Stream an XPWE file into an :class:`XpweDocument`.

    Args:
        content: The raw upload.
        price_list_only: Skip the measured bill and keep each price item's
            analysis lines, for an import into a cost database.

    Raises:
        XpweNativeFileError: The upload is not XML.
        ImporterParseError: Malformed XML, a DTD or entity declaration, or an
            XML document whose root is not ``PweDocumento``.
    """
    doc = XpweDocument()
    for price_item in _walk(content, doc, price_list_only=price_list_only):
        doc.price_items[price_item.id] = price_item
    return doc


def index_price_list(content: bytes | IO[bytes], doc: XpweDocument) -> dict[str, str]:
    """Every price item's code by its ``ID``, and ``doc`` filled, keeping nothing else.

    The first of two passes over a list too large to hold: with the codes and
    the chapter tree known up front, the second pass (:func:`stream_price_list`
    on the same ``doc``) names the item each analysis line refers to and holds
    no item back, wherever in the file it sits.
    """
    return {item.id: item.code for item in _walk(content, doc, price_list_only=True)}


def stream_price_list(content: bytes | IO[bytes], doc: XpweDocument) -> Iterator[XpwePriceItem]:
    """Yield an export's price items, with their analysis lines, without keeping them.

    ``doc`` collects everything else as it is read: the header, the chapter
    tree and the configuration; ``doc.price_items`` stays empty. An item read
    before the chapter tree is held back until the tree is complete, so
    :meth:`XpweDocument.chapter_path` answers for every item yielded. An export
    writes its general data first, so in practice nothing is held and memory
    stays at one record however long the list is.

    ``content`` may be a seekable binary stream, read as the parse goes
    (:func:`open_xml_stream`), so a large list never sits in memory whole.

    Raises:
        XpweNativeFileError: The upload is not XML.
        ImporterParseError: As :func:`read_xpwe`.
    """
    held: list[XpwePriceItem] = []
    for price_item in _walk(content, doc, price_list_only=True):
        if doc.chapters_complete:
            yield from held
            held.clear()
            yield price_item
        else:
            held.append(price_item)
    yield from held


def _walk(content: bytes | IO[bytes], doc: XpweDocument, *, price_list_only: bool) -> Iterator[XpwePriceItem]:
    """The streaming parse: fill ``doc`` and yield each price item as it ends."""
    from xml.etree.ElementTree import ParseError

    from defusedxml import DefusedXmlException
    from defusedxml.ElementTree import iterparse

    source: IO[bytes]
    if isinstance(content, bytes | bytearray):
        if not content:
            raise ImporterParseError("The XPWE file is empty.", code="xpwe_empty_file")
        data, doc.encoding = _xml_bytes(bytes(content))
        source = io.BytesIO(data)
    else:
        source, doc.encoding = open_xml_stream(content)
    stack: list[Any] = []
    group_counts: dict[tuple[str, int], int] = {}
    work_order = 0
    try:
        for event, elem in iterparse(source, events=("start", "end"), forbid_dtd=True):
            if event == "start":
                if not stack and _local(elem.tag) != ROOT_TAG:
                    raise ImporterParseError(
                        f"The file is XML but not an XPWE document: its root element is <{_local(elem.tag)}>.",
                        code="xpwe_wrong_root",
                        params={"root": _local(elem.tag)},
                    )
                stack.append(elem)
                continue
            stack.pop()
            tag = _local(elem.tag)
            handled = True
            if tag in _GROUP_TAGS:
                kind, level = _GROUP_TAGS[tag]
                index = group_counts.get((kind, level), 0)
                group_counts[(kind, level)] = index + 1
                group = _read_group(elem, kind, level, index)
                if group is not None:
                    doc.groups[(kind, level, group.id)] = group
            elif tag == "EPItem":
                price_item = _read_price_item(elem, with_analysis=price_list_only)
                if price_item is not None:
                    yield price_item
            elif tag == "VCItem":
                if not price_list_only:
                    work_order += 1
                    work_item = _read_work_item(elem, work_order)
                    if work_item is not None:
                        doc.work_items.append(work_item)
            elif tag == "DGWBSItem":
                node_id = _id(elem.get("ID", ""))
                if node_id:
                    doc.wbs[node_id] = {
                        "cu": _child_text(elem, "CU"),
                        "parent": _child_text(elem, "CUParent"),
                        "title": _child_text(elem, "TITOLO"),
                        "code": _child_text(elem, "CODICE"),
                        "index": str(len(doc.wbs)),
                    }
            elif tag == "PweDGDatiGenerali":
                for name in _HEADER_KEYS:
                    value = _child_text(elem, name)
                    if value:
                        doc.header[name] = value
            elif tag in ("PweDGConfigNumeri", "PweDGConfigurazione"):
                _read_config(elem, doc)
            elif tag == "PweDGCapitoliCategorie":
                doc.chapters_complete = True
                handled = False
            elif tag == "PweDGAnalisi":
                for name in ("SpeseGenerali", "UtiliImpresa", "OneriAccessoriSc"):
                    value = _child_text(elem, name)
                    if value:
                        doc.overheads[name] = value
            else:
                handled = False
            if handled and stack:
                # Detach the finished record so the tree never grows past one
                # record at a time.
                elem.clear()
                stack[-1].remove(elem)
    except ImporterParseError:
        raise
    except DefusedXmlException as exc:
        raise ImporterParseError(
            "The file declares a DTD or entities, which an XPWE export never does. It was not read.",
            code="xpwe_dtd_refused",
        ) from exc
    except ParseError as exc:
        raise ImporterParseError(
            f"The XPWE file is not well-formed XML: {exc}", code="xpwe_not_well_formed", params=xml_error_position(exc)
        ) from exc
    doc.chapters_complete = True
    if not doc.currency:
        doc.currency = "EUR"


# ── Shaping the bill ─────────────────────────────────────────────────────────


def _path_of(doc: XpweDocument, kind: str, ids: tuple[str, str, str]) -> list[XpweGroup]:
    path: list[XpweGroup] = []
    for level, group_id in enumerate(ids):
        if not group_id:
            continue
        group = doc.groups.get((kind, level, group_id))
        if group is not None:
            path.append(group)
    return path


def _wbs_path(doc: XpweDocument, code: str) -> list[XpweGroup]:
    """The WBS nodes from the root down to the one ``code`` names."""
    if not code:
        return []
    by_key: dict[str, tuple[str, dict[str, str]]] = {}
    for node_id, node in doc.wbs.items():
        for key in (node.get("code"), node.get("cu")):
            if key:
                by_key.setdefault(key, (node_id, node))
    found = by_key.get(code)
    chain: list[XpweGroup] = []
    seen: set[str] = set()
    while found is not None and found[0] not in seen:
        node_id, node = found
        seen.add(node_id)
        chain.append(
            XpweGroup(
                kind="wbs",
                level=0,
                id=node_id,
                index=_int(node.get("index", "0")),
                code=node.get("code", ""),
                title=node.get("title") or node.get("code") or node_id,
            )
        )
        parent = node.get("parent") or ""
        found = by_key.get(parent) if parent and parent != node.get("cu") else None
    chain.reverse()
    for depth, group in enumerate(chain):
        group.level = depth
    return chain


def _choose_grouping(doc: XpweDocument) -> tuple[str, dict[int, list[XpweGroup]]]:
    """Which tree the bill is laid out by, and each item's path through it, by the item's place in the file.

    The bill's own category tree first. An export that uses none falls back to
    its work breakdown, then to the chapters of the price items, and otherwise
    stays flat.
    """
    paths = {item.order: _path_of(doc, "category", item.category_ids) for item in doc.work_items}
    if any(paths.values()):
        return "categories", paths
    if doc.wbs:
        paths = {item.order: _wbs_path(doc, item.wbs_code) for item in doc.work_items}
        if any(paths.values()):
            return "wbs", paths
    paths = {}
    for item in doc.work_items:
        price_item = doc.price_items.get(item.price_id)
        paths[item.order] = doc.chapter_path(price_item) if price_item else []
    if any(paths.values()):
        return "chapters", paths
    return "none", {item.order: [] for item in doc.work_items}


def normalise_unit(raw: str) -> str:
    """Canonical unit for an Italian unit spelling; the raw text when it has none."""
    folded = (raw or "").strip()
    if not folded:
        return "pcs"
    return _UNIT_ALIASES.get(folded.lower(), folded)


@dataclass(slots=True)
class _Notes:
    """Warnings collected while shaping, capped per code."""

    warnings: list[dict[str, Any]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def add(self, code: str, message: str, **params: Any) -> None:
        seen = self.counts.get(code, 0)
        self.counts[code] = seen + 1
        if seen < _MAX_WARNINGS_PER_CODE:
            self.warnings.append({"severity": "warning", "code": code, "message": message, **params})

    def finish(self) -> list[dict[str, Any]]:
        for code, count in self.counts.items():
            if count > _MAX_WARNINGS_PER_CODE:
                hidden = count - _MAX_WARNINGS_PER_CODE
                self.warnings.append(
                    {
                        "severity": "warning",
                        "code": "xpwe_more_warnings",
                        "of": code,
                        "count": hidden,
                        "message": f"{hidden} more warnings of the kind {code} were not listed.",
                    }
                )
        return self.warnings


def _fmt(value: Decimal) -> str:
    return format(value.normalize(), "f") if value == value.to_integral_value() else format(value, "f")


class _Measurer:
    """Totals each bill item from its measurement rows, resolving "see item" rows on demand.

    Items are keyed by their place in the file (``XpweWorkItem.order``): two
    items may share an ``ID``, and a "see item" row naming that ID follows the
    first of them.
    """

    def __init__(self, doc: XpweDocument, notes: _Notes) -> None:
        self.doc = doc
        self.notes = notes
        self.items = {item.order: item for item in doc.work_items}
        self.by_id: dict[str, int] = {}
        for item in doc.work_items:
            self.by_id.setdefault(item.id, item.order)
        self.totals: dict[int, Decimal] = {}
        self.lines: dict[int, list[dict[str, Any]]] = {}
        self.ordinals: dict[int, str] = {}
        self._active: set[int] = set()
        self.see_rows = 0
        self.rows = 0
        self.decimals = doc.decimals.get("Quantita")
        self.quantum = Decimal(1).scaleb(-self.decimals) if self.decimals is not None else None

    def total(self, key: int) -> Decimal | None:
        """The quantity of the item at ``key``, or None when there is none or it repeats itself.

        A "see item" chain is followed with an explicit stack rather than by
        recursion, so a chain thousands of items long reads like a short one.
        """
        if key in self.totals:
            return self.totals[key]
        if key not in self.items or key in self._active:
            return None
        stack = [key]
        self._active.add(key)
        try:
            self._follow(stack)
        finally:
            # An item that failed part way leaves the rest of its chain free
            # to be measured on its own, not taken for a cycle.
            self._active.difference_update(stack)
        return self.totals.get(key)

    def _follow(self, stack: list[int]) -> None:
        while stack:
            current = stack[-1]
            waiting = next(
                (
                    ref
                    for ref in self._see_refs(self.items[current])
                    if ref not in self.totals and ref not in self._active
                ),
                None,
            )
            if waiting is not None:
                # One at a time, so the stack is exactly the chain being
                # followed and a reference back into it is a cycle.
                self._active.add(waiting)
                stack.append(waiting)
                continue
            total, lines = self._measure(self.items[current])
            stack.pop()
            self._active.discard(current)
            self.totals[current] = total
            self.lines[current] = lines

    def _see_refs(self, item: XpweWorkItem) -> Iterator[int]:
        for row in item.rows:
            if row.flags & SUBTOTAL_FLAG:
                continue
            see = self._see_id(row)
            if see and see in self.by_id:
                yield self.by_id[see]

    @staticmethod
    def _see_id(row: XpweMeasureRow) -> str:
        return _id(row.ref) if row.ref.strip() not in ("", "-2") else ""

    def _label(self, item: XpweWorkItem) -> str:
        return self.ordinals.get(item.order, item.id)

    def _ref_label(self, see: str) -> str:
        key = self.by_id.get(see)
        return self.ordinals.get(key, see) if key is not None else see

    def _measure(self, item: XpweWorkItem) -> tuple[Decimal, list[dict[str, Any]]]:
        if not item.rows:
            declared = _decimal_or_none(item.quantity_text)
            return (declared if declared is not None else Decimal(0)), []
        total = Decimal(0)
        lines: list[dict[str, Any]] = []
        for row in item.rows:
            self.rows += 1
            try:
                value, line = self._row(item, row)
            except ArithmeticError:
                # Whatever the arithmetic tripped on, it costs this row and
                # not the bill.
                value, line = self._out_of_range(item, row)
            total += value
            lines.append(line)
        if self.quantum is not None:
            total = total.quantize(self.quantum, rounding=ROUND_HALF_UP)
        return total, lines

    def _out_of_range(self, item: XpweWorkItem, row: XpweMeasureRow) -> tuple[Decimal, dict[str, Any]]:
        self.notes.add(
            "xpwe_measurement_out_of_range",
            f"Item {self._label(item)}: a measurement row is beyond any real quantity and counts as zero.",
            ordinal=self._label(item),
        )
        return Decimal(0), {**self._note_line(row), "error": "measurement out of range"}

    def _note_line(self, row: XpweMeasureRow, **extra: Any) -> dict[str, Any]:
        return {
            "description": row.description,
            "formula": "0",
            "variables": {},
            "factor": "1",
            "sign": "+",
            "ref": row.id,
            **extra,
        }

    def _row(self, item: XpweWorkItem, row: XpweMeasureRow) -> tuple[Decimal, dict[str, Any]]:
        if row.flags & SUBTOTAL_FLAG:
            return Decimal(0), self._note_line(row, xpwe_subtotal=True)
        parsed: list[tuple[int, Decimal, str, bool]] = []
        for position, raw in enumerate(row.factors):
            if not raw:
                continue
            try:
                value, expr, plain = _evaluate_factor(raw)
            except _UnreadableFactor:
                self.notes.add(
                    "xpwe_expression_unreadable",
                    f"Item {self._label(item)}: the measurement {raw!r} could not be read and counts as zero.",
                    ordinal=self._label(item),
                    text=raw,
                )
                return Decimal(0), {
                    **self._note_line(row),
                    "formula": raw,
                    "error": f"unreadable measurement: {raw}",
                }
            if abs(value) > _MAX_MAGNITUDE:
                return self._out_of_range(item, row)
            parsed.append((position, value, expr, plain))

        see = self._see_id(row)
        product = Decimal(1)
        for _position, value, _expr, _plain in parsed:
            product *= value
        if see:
            self.see_rows += 1
            key = self.by_id.get(see)
            # Every reference is measured before the item making it (see
            # :meth:`total`); one still missing here is unknown or a cycle.
            referenced = self.totals.get(key) if key is not None else None
            if referenced is None:
                self.notes.add(
                    "xpwe_see_item_unresolved",
                    f"Item {self._label(item)}: a row refers to item {see}, which could not be read; it counts as zero.",
                    ordinal=self._label(item),
                    ref=see,
                )
                return Decimal(0), self._note_line(row, xpwe_see_item=see)
            value = referenced * product
            if abs(value) > _MAX_MAGNITUDE:
                return self._out_of_range(item, row)
            self.notes.add(
                "xpwe_see_item_flattened",
                f"Item {self._label(item)}: a row repeating the quantity of item "
                f"{self._ref_label(see)} was stored as its value, {_fmt(referenced)}.",
                ordinal=self._label(item),
                ref=self._ref_label(see),
                value=float(referenced),
            )
            exprs = [_fmt(referenced)] + [expr for _p, _v, expr, _pl in parsed]
            return self._signed(row, value, exprs, structured=None, see=see)
        if not parsed:
            return Decimal(0), self._note_line(row)
        if abs(product) > _MAX_MAGNITUDE:
            return self._out_of_range(item, row)
        structured = parsed if all(plain for _p, _v, _e, plain in parsed) else None
        exprs = [expr for _p, _v, expr, _pl in parsed]
        return self._signed(row, product, exprs, structured=structured, see="")

    def _signed(
        self,
        row: XpweMeasureRow,
        value: Decimal,
        exprs: list[str],
        *,
        structured: list[tuple[int, Decimal, str, bool]] | None,
        see: str,
    ) -> tuple[Decimal, dict[str, Any]]:
        negative = value < 0 or row.quantity_text.strip().startswith("-")
        magnitude = abs(value)
        line: dict[str, Any] = {
            "description": row.description,
            "sign": "-" if negative else "+",
            "ref": row.id,
        }
        if structured is not None:
            # The columns an estimator reads: parts, then up to three dimensions.
            variables: dict[str, str] = {}
            factor = "1"
            for position, number, _expr, _plain in structured:
                if position == 0:
                    factor = _fmt(abs(number))
                else:
                    variables[("L", "B", "H")[position - 1]] = _fmt(abs(number))
            line["factor"] = factor
            line["variables"] = variables
            line["formula"] = " * ".join(name for name in ("L", "B", "H") if name in variables) or "1"
        else:
            expression = " * ".join(f"({expr})" if re.search(r"[+\-/]", expr.lstrip("-")) else expr for expr in exprs)
            line["factor"] = "1"
            line["variables"] = {}
            line["formula"] = f"abs({expression})" if value < 0 else expression
        if see:
            line["xpwe_see_item"] = see
        if self.quantum is not None:
            # The estimating program rounds every row to the declared decimals
            # and totals the rounded rows. The row keeps what was typed and the
            # sheet carries the same rounding (``row_decimals``), so it adds up
            # to the imported quantity and its dimensions stay editable.
            magnitude = magnitude.quantize(self.quantum, rounding=ROUND_HALF_UP)
        return (-magnitude if negative else magnitude), line


def _mismatch_tolerance(quantum: Decimal | None, declared: Decimal) -> Decimal:
    """How far a measured total may sit from the declared one and still be the same number.

    Half a unit of the finer of the two roundings: the decimals the file
    declares for quantities, and the decimals the declared value is written
    with. Rows are rounded one by one before they are added, so the measured
    total is a whole number of those units and a real difference is at least
    one unit. A file that declares no rounding gets no tolerance: without it a
    declared "12" would excuse anything up to half a unit.
    """
    if quantum is None:
        return Decimal(0)
    exponent = declared.as_tuple().exponent
    written = Decimal(1).scaleb(exponent) if isinstance(exponent, int) and exponent < 0 else Decimal(1)
    return min(quantum, written) / 2


@dataclass(slots=True)
class _Node:
    group: XpweGroup | None
    ordinal: str = ""
    children: dict[tuple[str, int, str], _Node] = field(default_factory=dict)
    items: list[XpweWorkItem] = field(default_factory=list)


def _build_tree(doc: XpweDocument, paths: dict[int, list[XpweGroup]]) -> _Node:
    root = _Node(group=None)
    for item in doc.work_items:
        node = root
        for group in paths.get(item.order, []):
            key = (group.kind, group.level, group.id)
            child = node.children.get(key)
            if child is None:
                child = _Node(group=group)
                node.children[key] = child
            node = child
        node.items.append(item)
    return root


def _number_tree(node: _Node, prefix: str, ordinals: dict[int, str]) -> None:
    """Give every section and item a dotted ordinal.

    Inside a section its own items come first, then its sub-sections: the order
    the bill editor keeps a section in (a position added to a section lands
    after its items and before its first sub-section), so a bill imported in
    document order reads the same as one built row by row. Items filed under no
    section at all come after the top-level sections, where the editor appends
    them.
    """
    counter = 0

    def number_items() -> None:
        nonlocal counter
        for item in node.items:
            counter += 1
            ordinals[item.order] = f"{prefix}{counter}"

    if node.group is not None:
        number_items()
    children = sorted(node.children.values(), key=lambda n: (n.group.level, n.group.index) if n.group else (0, 0))
    node.children = {(c.group.kind, c.group.level, c.group.id): c for c in children if c.group}
    for child in children:
        counter += 1
        child.ordinal = f"{prefix}{counter}"
        _number_tree(child, f"{child.ordinal}.", ordinals)
    if node.group is None:
        number_items()


def _truncate(text: str, notes: _Notes, ordinal: str) -> tuple[str, str | None]:
    if len(text) <= _MAX_DESCRIPTION:
        return text, None
    notes.add(
        "xpwe_description_truncated",
        f"Item {ordinal}: the description is longer than {_MAX_DESCRIPTION} characters; "
        "the full text is kept with the position.",
        ordinal=ordinal,
    )
    return text[: _MAX_DESCRIPTION - 1].rstrip() + "…", text


def build_imported_boq(doc: XpweDocument) -> ImportedBOQ:
    """Shape an extracted document into sections and positions, top-down."""
    notes = _Notes()
    # Emitted section by section with every item naming its section, see ``emit_items``.
    result = ImportedBOQ(source_format="xpwe", currency=doc.currency, document_order=True)
    grouping, paths = _choose_grouping(doc)
    root = _build_tree(doc, paths)
    ordinals: dict[int, str] = {}
    _number_tree(root, "", ordinals)
    measurer = _Measurer(doc, notes)
    measurer.ordinals = ordinals

    if doc.encoding not in ("utf-8", "utf-16"):
        notes.add(
            "xpwe_encoding_fallback",
            f"The file is not UTF-8 and was read as {doc.encoding}.",
            encoding=doc.encoding,
        )
    first_of: dict[str, str] = {}
    for work_item in doc.work_items:
        ordinal = ordinals[work_item.order]
        first = first_of.setdefault(work_item.id, ordinal)
        if first != ordinal:
            notes.add(
                "xpwe_duplicate_item_id",
                f"Item {ordinal}: item {first} has the same ID ({work_item.id}). Both were imported; "
                f"rows repeating item {work_item.id} follow item {first}.",
                ordinal=ordinal,
                ref=work_item.id,
                first=first,
            )

    sections = 0
    items = 0
    deductions = 0
    deducted = Decimal(0)

    def emit(node: _Node, parent_ordinal: str) -> None:
        # The same order as :func:`_number_tree`, so the rows arrive in ordinal order.
        if node.group is None:
            emit_sections(node)
            emit_items(node, parent_ordinal)
        else:
            emit_items(node, parent_ordinal)
            emit_sections(node)

    def emit_items(node: _Node, parent_ordinal: str) -> None:
        nonlocal items
        for work_item in node.items:
            ordinal = ordinals[work_item.order]
            try:
                position = emit_item(work_item, ordinal, parent_ordinal)
            except ArithmeticError:
                logger.debug("XPWE item %s could not be shaped", ordinal, exc_info=True)
                result.errors.append(
                    {
                        "ordinal": ordinal,
                        "code": "xpwe_item_failed",
                        "error": f"Item {ordinal}: its numbers could not be worked out. It was not imported.",
                    }
                )
                continue
            if position is not None:
                items += 1
                result.positions.append(position)

    def emit_item(work_item: XpweWorkItem, ordinal: str, parent_ordinal: str) -> ImportedPosition | None:
        """One bill item as a position, or None with an error recorded.

        An item whose amount is negative, a deduction measured below zero or a
        credit priced below zero, cannot be a position: a position's quantity
        and rate are never negative. It is imported with its quantity and no
        price, its signed figures kept in ``metadata``, and its amount is taken
        off by one deductions line on the bill (see ``deductions``), so the
        bill totals what the file does.
        """
        nonlocal deductions, deducted
        price_item = doc.price_items.get(work_item.price_id)
        if price_item is None:
            result.errors.append(
                {
                    "ordinal": ordinal,
                    "code": "xpwe_price_item_missing",
                    "ref": work_item.price_id,
                    "error": (
                        f"Item {ordinal} refers to price-list item {work_item.price_id or '-'}, "
                        "which the file does not contain. It was not imported."
                    ),
                }
            )
            return None
        total = measurer.total(work_item.order)
        if total is None:
            total = Decimal(0)
        lines = measurer.lines.get(work_item.order, [])
        declared = _decimal_or_none(work_item.quantity_text)
        if lines and declared is not None:
            tolerance = _mismatch_tolerance(measurer.quantum, declared)
            if abs(total - declared) <= tolerance:
                total = declared
            else:
                notes.add(
                    "xpwe_quantity_mismatch",
                    f"Item {ordinal}: the measurement rows add up to {_fmt(total)}, "
                    f"the file states {_fmt(declared)}. The measured quantity was imported.",
                    ordinal=ordinal,
                    computed=float(total),
                    declared=float(declared),
                    kept="measured",
                )
        if abs(total) > _MAX_MAGNITUDE:
            result.errors.append(
                {
                    "ordinal": ordinal,
                    "code": "xpwe_quantity_out_of_range",
                    "error": f"Item {ordinal}: its quantity is beyond any real one. It was not imported.",
                }
            )
            return None
        try:
            rate = plain_decimal(price_item.price_text) or Decimal(0)
        except ValueError:
            notes.add(
                "xpwe_price_unreadable",
                f"Item {ordinal}: the price {price_item.price_text!r} could not be read; it was imported at zero.",
                ordinal=ordinal,
                text=price_item.price_text,
            )
            rate = Decimal(0)
        if abs(rate) > Decimal("1e8"):
            result.errors.append(
                {
                    "ordinal": ordinal,
                    "code": "xpwe_price_out_of_range",
                    "text": format(rate, "f"),
                    "error": f"Unit rate out of range: {rate}",
                }
            )
            return None

        amount = (total * rate).quantize(_AMOUNT_QUANTUM, rounding=ROUND_HALF_UP)
        deduction = amount < 0
        if total < 0 and rate < 0:
            notes.add(
                "xpwe_signs_cancel",
                f"Item {ordinal}: both its quantity and its unit rate are negative, so it adds "
                f"{_fmt(amount)}. It was imported with both made positive.",
                ordinal=ordinal,
            )
        if total < 0:
            # The sheet keeps every row as typed and turns its signs round, so
            # it still adds up to the quantity the position carries.
            lines = [{**line, "sign": "+" if line["sign"] == "-" else "-", "xpwe_sign": line["sign"]} for line in lines]

        text = price_item.description or price_item.short_description or price_item.code
        description, full_text = _truncate(text, notes, ordinal)
        classification: dict[str, Any] = {}
        if price_item.code:
            # An XPWE bill is priced from an Italian list, so the code is
            # also the voce the Italian rules read, whatever the project's
            # country says.
            classification["code"] = price_item.code
            classification["voci"] = price_item.code
        if price_item.is_safety:
            classification["cost_type"] = "sicurezza"
        unit = normalise_unit(price_item.unit)
        metadata: dict[str, Any] = {
            "import_section": parent_ordinal,
            "import_row_index": work_item.order,
            "xpwe_order": work_item.order,
            "xpwe_vc_id": work_item.id,
            "xpwe_ep_id": price_item.id,
            "xpwe_unit_raw": price_item.unit,
            "xpwe_unit_rate": format(rate, "f"),
        }
        if declared is not None:
            metadata["xpwe_declared_quantity"] = format(declared, "f")
        if work_item.date:
            metadata["xpwe_date"] = work_item.date
        if price_item.short_description and price_item.short_description != description:
            metadata["short_description"] = price_item.short_description
        if full_text is not None:
            metadata["description_full"] = full_text
        if price_item.shares:
            metadata["cost_shares"] = dict(price_item.shares)
        if price_item.is_safety:
            metadata["safety_item"] = True
        if deduction:
            deductions += 1
            deducted += amount
            metadata["deduction"] = True
            metadata["deduction_amount"] = format(amount, "f")
            metadata["deduction_quantity"] = format(total, "f")
            metadata["deduction_unit_rate"] = format(rate, "f")
        if lines:
            metadata["measurement"] = {"unit": unit, "lines": lines, "source": "xpwe"}
            if measurer.decimals is not None:
                # The rounding the file applies to every row, so the sheet
                # totals what was imported (``MeasurementSheet.row_decimals``).
                metadata["measurement"]["row_decimals"] = measurer.decimals
        return ImportedPosition(
            description=description,
            ordinal=ordinal,
            unit=unit,
            quantity=float(abs(total)),
            unit_rate=0.0 if deduction else float(abs(rate)),
            classification=classification,
            source="xpwe_import",
            metadata=metadata,
        )

    def emit_sections(node: _Node) -> None:
        nonlocal sections
        for child in node.children.values():
            group = child.group
            assert group is not None
            sections += 1
            result.positions.append(
                ImportedPosition(
                    description=group.title,
                    ordinal=child.ordinal,
                    unit="section",
                    quantity=0.0,
                    unit_rate=0.0,
                    classification={},
                    source="xpwe_import",
                    metadata={
                        "section_header": True,
                        "xpwe_group": {"kind": group.kind, "level": group.level, "id": group.id, "code": group.code},
                    },
                    is_section=True,
                )
            )
            emit(child, child.ordinal)

    emit(root, "")
    if deductions:
        notes.add(
            "xpwe_deductions_moved",
            f"{deductions} items with a negative amount were imported without a price, and their "
            f"{_fmt(-deducted)} is taken off by one deductions line on the bill.",
            count=deductions,
            amount=float(deducted.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        )
    result.warnings = notes.finish()
    result.metadata = {
        "xpwe_encoding": doc.encoding,
        "xpwe_grouping": grouping,
        "xpwe_sections": sections,
        "xpwe_items": items,
        "xpwe_measurement_rows": measurer.rows,
        "xpwe_see_item_rows": measurer.see_rows,
        "xpwe_price_list_items": len(doc.price_items),
        "measurement_rows": measurer.rows,
        **{f"xpwe_{_HEADER_KEYS[key]}": value for key, value in doc.header.items() if key in _HEADER_KEYS},
    }
    if doc.overheads:
        result.metadata["xpwe_overheads"] = dict(doc.overheads)
    if deductions:
        # Read when the bill is stored, which adds the deductions line.
        result.metadata["deductions"] = {"count": deductions, "amount": format(deducted, "f")}
    if not doc.work_items:
        result.warnings.append(
            {
                "severity": "warning",
                "code": "xpwe_no_bill_items",
                "count": len(doc.price_items),
                "message": (
                    f"The file holds a price list of {len(doc.price_items)} items and no measured bill. "
                    "Import it into a cost database instead."
                ),
            }
        )
    return result


def native_file_message(locale: str) -> str:
    """The translated refusal for a native project file."""
    from app.core.validation.messages import translate

    return translate("errors.xpwe_native_file_refused", locale=locale)


class XpweImporter:
    """XPWE (Italian estimating XML) native importer."""

    format_id: ClassVar[str] = "xpwe"
    extensions: ClassVar[tuple[str, ...]] = (".xpwe",)
    display_name: ClassVar[str] = "XPWE (Italian estimating XML)"
    rule_packs: ClassVar[tuple[str, ...]] = ("boq_quality",)

    # Claimed only so they can be refused with a message that says what to do.
    # The native project file is a proprietary container; ``.pwe`` is the older
    # exchange name and is read when it turns out to be the same XML.
    refused_extensions: ClassVar[tuple[str, ...]] = (".dcf", ".pwe")

    @classmethod
    def detect(cls, head_bytes: bytes, filename: str) -> bool:
        """Claim ``.xpwe``, the native and legacy names, and any ``.xml`` whose root is ``PweDocumento``."""
        if not head_bytes:
            return False
        name = (filename or "").lower()
        if name.endswith(cls.extensions) or name.endswith(cls.refused_extensions):
            return True
        if not name.endswith(".xml"):
            return False
        return b"<" + ROOT_TAG.encode("ascii") in head_bytes[:4096]

    @classmethod
    async def parse(cls, content: bytes, *, locale: str = "en") -> ImportedBOQ:
        """Parse an XPWE buffer into :class:`ImportedBOQ`.

        Reading and shaping are pure CPU work (about a second per megabyte on
        a busy machine), so they run in a worker thread: on the event loop they
        would stall every other request of a single-worker server.
        """
        try:
            return await asyncio.to_thread(_parse_sync, content)
        except XpweNativeFileError as exc:
            raise ImporterParseError(native_file_message(locale), code="xpwe_not_xml") from exc


def _parse_sync(content: bytes) -> ImportedBOQ:
    return build_imported_boq(read_xpwe(content))


__all__ = [
    "ROOT_TAG",
    "SAFETY_FLAG",
    "XpweDocument",
    "XpweGroup",
    "XpweImporter",
    "XpweNativeFileError",
    "XpwePriceItem",
    "build_imported_boq",
    "index_price_list",
    "native_file_message",
    "normalise_unit",
    "open_xml_stream",
    "plain_decimal",
    "read_xpwe",
    "stream_price_list",
]
