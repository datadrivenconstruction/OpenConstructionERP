# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Shared plumbing for the GAEB DA XML 3.3 phases outside the tender chain.

The X81-X86 reader in :mod:`app.modules.boq.importers.gaeb_xml` turns a
Leistungsverzeichnis into positions. The two phases this module serves do
something else with the same OZ (Ordnungszahl) tree:

* **X31 Mengenermittlung** carries measured quantities per OZ and nothing
  else: no text, no prices (Fachdokumentation 3.3, chapter 7).
* **X89 Rechnung** carries an invoice: a header, the invoice shares and the
  billed quantity and amount per OZ (chapter 8).

Neither creates positions. Both have to find the position a given OZ names,
and both have to write a BoQ tree that a reader rebuilds into the same OZ.
That is what lives here, once, so the two phases cannot come to disagree
about what an OZ is.

The OZ helpers of the X8x importer are imported, not copied. The importer
pads a numeric part to the width the file's ``BoQBkdn`` mask declares, so
``1.10`` written under a two-digit mask comes back as ``01.10``; the matcher
here therefore compares numeric parts without their leading zeros as a last
resort, and never guesses when two positions answer to the same key.

Everything here is pure: no database, no request objects.
"""

from __future__ import annotations

import re
import uuid
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from app.modules.boq.importers._base import ImporterParseError
from app.modules.boq.importers.gaeb_xml import (
    _build_oz,
    _find_child,
    _local,
    _ozmask_separators,
    _text_of,
)

#: The schema release every writer here targets. ``GAEBInfo/VersDate`` is an
#: enumeration in the 3.3 schema and only accepts this value.
GAEB_VERSION = "3.3"
GAEB_VERS_DATE = "2021-05"
PROGRAM_NAME = "OpenConstructionERP"

#: ``tgRNoPart``: letters, digits and underscore, one to fourteen of them.
_RNOPART_RE = re.compile(r"^[A-Za-z0-9_]{1,14}$")

#: ``tgBoQBkdn`` allows seven entries; one is the Item level, so at most six
#: category levels sit above an item. A deeper OZ cannot be written.
MAX_OZ_DEPTH = 6

_Q3 = Decimal("0.001")
_C2 = Decimal("0.01")


def namespace_for(dp: str) -> str:
    """Return the GAEB DA XML 3.3 namespace URI for a phase number."""
    return f"http://www.gaeb.de/GAEB_DA_XML/DA{dp}/3.3"


def dec(value: Any) -> Decimal | None:
    """Coerce a number-like value to a finite ``Decimal``, or ``None``."""
    if value is None or value == "":
        return None
    try:
        d = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def q3(value: Decimal) -> Decimal:
    """Round to the three decimals ``tgDecimal_11_3`` and ``tgDecimal_13_3`` carry."""
    return value.quantize(_Q3, rounding=ROUND_HALF_UP)


def c2(value: Decimal) -> Decimal:
    """Round to the two decimals ``tgDecimal_13_2`` (money) carries."""
    return value.quantize(_C2, rounding=ROUND_HALF_UP)


def mint_id(prefix: str) -> str:
    """Mint an ``xs:ID`` handle. Never an OZ: an ID may not start with a digit."""
    return f"{prefix}{uuid.uuid4().hex[:16]}"


# ── Reading ──────────────────────────────────────────────────────────────


def parse_xml(content: bytes, *, label: str) -> ET.Element:
    """Parse an uploaded GAEB file through ``defusedxml``.

    The same entry point the X8x importer uses, so entity expansion, external
    entities and DTD tricks are refused here exactly as they are there. Every
    failure comes back as :class:`ImporterParseError` with a message that is
    safe to show to the person who uploaded the file.
    """
    from defusedxml.ElementTree import fromstring as _safe_fromstring

    if not content:
        raise ImporterParseError(f"{label} upload is empty")
    try:
        return _safe_fromstring(content)
    except ET.ParseError as exc:
        raise ImporterParseError(f"Failed to parse {label}: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - defusedxml raises its own classes
        raise ImporterParseError(f"{label} rejected by security parser: {exc}") from exc


def exchange_phase(root: ET.Element) -> str:
    """Return the two-digit phase a GAEB document declares, or ``""``.

    Read from the ``DA<nn>`` token of the root namespace first, then from a
    ``DP`` element that is a direct child of the phase container
    (``Award``, ``QtyDeterm`` or ``Invoice``). The container itself is the
    last hint: an X31 is the only phase whose root holds ``QtyDeterm`` and an
    X89 the only one whose root holds ``Invoice``.
    """
    ns = root.tag.split("}", 1)[0].lstrip("{") if "}" in root.tag else ""
    match = re.search(r"/DA(\d{2})/", ns + "/")
    if match:
        return match.group(1)
    for container_name in ("Award", "QtyDeterm", "Invoice"):
        container = _find_child(root, container_name)
        if container is None:
            continue
        dp = re.sub(r"\D", "", _text_of(container, "DP"))
        if len(dp) >= 2:
            return dp[-2:]
        if container_name == "QtyDeterm":
            return "31"
        if container_name == "Invoice":
            return "89"
    return ""


@dataclass(frozen=True, slots=True)
class FileItem:
    """One ``Item`` of a GAEB BoQ tree, with the OZ the tree gives it."""

    oz: str
    element: ET.Element


def iter_boq_items(boq: ET.Element) -> Iterator[FileItem]:
    """Walk a ``BoQ`` element and yield every ``Item`` with its full OZ.

    The OZ is assembled with the X8x importer's own ``_build_oz`` from the
    ``RNoPart`` chain and the ``BoQBkdn`` mask, so a file reads to the same
    OZ here as it would there. Tolerates the two shapes writers produce: the
    schema's ``BoQCtgy/BoQBody/Itemlist`` and the looser
    ``BoQCtgy/Itemlist`` some tools write. The mask is looked up inside this
    ``BoQ`` only, never in a sibling document part.
    """
    mask_lengths, _ = _ozmask_separators(boq)
    body = _find_child(boq, "BoQBody")
    if body is None:
        return

    def _items(container: ET.Element, chain: list[str]) -> Iterator[FileItem]:
        for child in container:
            tag = _local(child.tag)
            if tag == "BoQCtgy":
                part = (child.get("RNoPart") or "").strip()
                yield from _items(child, chain + ([part] if part else []))
            elif tag in ("BoQBody", "Itemlist"):
                yield from _items(child, chain)
            elif tag == "Item":
                part = (child.get("RNoPart") or "").strip()
                index = (child.get("RNoIndex") or "").strip()
                oz = _build_oz(chain + ([part] if part else []), index, mask_lengths)
                yield FileItem(oz=oz, element=child)

    yield from _items(body, [])


# ── Matching an OZ to a position ─────────────────────────────────────────


def normalize_oz(oz: str) -> str:
    """Canonical form of an OZ for the last-resort comparison.

    Numeric parts lose their leading zeros, letters are compared without
    case, and surrounding whitespace goes. ``01.0010`` and ``1.10`` are the
    same item under two masks; ``01.A`` and ``1.a`` too.
    """
    parts: list[str] = []
    for raw in (oz or "").strip().split("."):
        part = raw.strip()
        if part.isdigit():
            part = str(int(part))
        parts.append(part.lower())
    return ".".join(parts)


@dataclass(slots=True)
class OzMatch:
    """The outcome of looking one OZ up among a bill's positions."""

    status: str  # "matched" | "ambiguous" | "unmatched"
    position: Any = None
    candidates: list[Any] = field(default_factory=list)
    #: Which key found it: "ordinal", "gaeb_ordinal" or "normalized".
    via: str = ""


def _position_meta(position: Any) -> dict[str, Any]:
    meta = getattr(position, "metadata_", None)
    if not isinstance(meta, dict):
        meta = getattr(position, "metadata", None)
    return meta if isinstance(meta, dict) else {}


class PositionIndex:
    """Look positions up by the OZ a GAEB file names.

    Three keys, tried in order, each only accepted when exactly one position
    answers to it:

    1. the position's own ``ordinal``, exactly;
    2. the OZ a GAEB import recorded in ``metadata.gaeb_ordinal``;
    3. the normalized form of either, see :func:`normalize_oz`.

    Two positions sharing a key at the first level that has any hit is
    reported as ambiguous; the index never picks one, because a quantity or
    an amount landing on the wrong line is worse than one that lands nowhere.
    Section rows are passed in by the caller as ``is_section`` and never
    match: GAEB measures and bills items only.
    """

    def __init__(self, positions: Iterable[Any], *, is_section: Callable[[Any], bool]) -> None:
        self._exact: dict[str, list[Any]] = {}
        self._gaeb: dict[str, list[Any]] = {}
        self._norm: dict[str, list[Any]] = {}
        for pos in positions:
            if is_section(pos):
                continue
            ordinal = str(getattr(pos, "ordinal", "") or "").strip()
            gaeb_ordinal = str(_position_meta(pos).get("gaeb_ordinal") or "").strip()
            if ordinal:
                self._exact.setdefault(ordinal, []).append(pos)
            if gaeb_ordinal:
                self._gaeb.setdefault(gaeb_ordinal, []).append(pos)
            norm_keys = {normalize_oz(k) for k in (ordinal, gaeb_ordinal) if k}
            for key in norm_keys:
                self._norm.setdefault(key, []).append(pos)

    def match(self, oz: str) -> OzMatch:
        key = (oz or "").strip()
        if not key:
            return OzMatch(status="unmatched")
        for via, table, lookup in (
            ("ordinal", self._exact, key),
            ("gaeb_ordinal", self._gaeb, key),
            ("normalized", self._norm, normalize_oz(key)),
        ):
            hits = _unique(table.get(lookup, []))
            if len(hits) == 1:
                return OzMatch(status="matched", position=hits[0], via=via)
            if len(hits) > 1:
                return OzMatch(status="ambiguous", candidates=hits, via=via)
        return OzMatch(status="unmatched")


def _unique(items: list[Any]) -> list[Any]:
    seen: set[int] = set()
    out: list[Any] = []
    for item in items:
        if id(item) in seen:
            continue
        seen.add(id(item))
        out.append(item)
    return out


# ── Writing an OZ tree ───────────────────────────────────────────────────


@dataclass(slots=True)
class OzLayout:
    """How a set of OZ is written as a GAEB BoQ tree.

    ``depth`` counts the item level, so an OZ ``01.02.0010`` has depth 3:
    two ``BoQCtgy`` levels and the item. ``lengths`` and ``numeric`` describe
    the ``BoQBkdn`` mask per level. ``accepted`` maps every writable OZ to
    its segments; ``rejected`` lists the OZ that cannot be written, each
    with the reason, so a caller can report them instead of dropping them.
    """

    depth: int
    lengths: list[int]
    numeric: list[bool]
    accepted: dict[str, list[str]]
    rejected: list[dict[str, str]]


def oz_segments(oz: str) -> list[str] | None:
    """Split an OZ into ``RNoPart`` segments, or ``None`` if it cannot be one.

    A segment must satisfy ``tgRNoPart``. The dot is the separator, so an OZ
    carrying any other punctuation (``01-002``, ``A/3``) has no faithful
    GAEB spelling: rewriting it would make a re-import name a different item.
    """
    text = (oz or "").strip()
    if not text:
        return None
    segments = text.split(".")
    if any(not _RNOPART_RE.match(seg) for seg in segments):
        return None
    return segments


def plan_oz_layout(ordinals: Iterable[str]) -> OzLayout:
    """Decide the tree for a set of OZ and which of them fit it.

    GAEB fixes one depth per file: every item sits at the level the mask
    names, and a ``BoQBody`` holds either categories or one item list, never
    both. The depth the most OZ share wins (ties go to the deeper one, the
    more structured bill). An OZ of another depth, an OZ a GAEB segment
    cannot spell, an empty one, or one that occurs twice is rejected with a
    reason rather than rewritten.
    """
    ordered: list[str] = []
    seen: Counter[str] = Counter()
    for raw in ordinals:
        text = (raw or "").strip()
        seen[text] += 1
        ordered.append(text)

    rejected: list[dict[str, str]] = []
    candidates: dict[str, list[str]] = {}
    for text in ordered:
        if text in candidates or any(r["ordinal"] == text for r in rejected):
            continue
        if not text:
            rejected.append({"ordinal": text, "reason": "empty_ordinal"})
            continue
        if seen[text] > 1:
            rejected.append({"ordinal": text, "reason": "duplicate_ordinal"})
            continue
        segments = oz_segments(text)
        if segments is None:
            rejected.append({"ordinal": text, "reason": "ordinal_not_representable"})
            continue
        if len(segments) > MAX_OZ_DEPTH:
            rejected.append({"ordinal": text, "reason": "ordinal_too_deep"})
            continue
        candidates[text] = segments

    if not candidates:
        return OzLayout(depth=0, lengths=[], numeric=[], accepted={}, rejected=rejected)

    depth_counts = Counter(len(segs) for segs in candidates.values())
    depth = max(depth_counts, key=lambda d: (depth_counts[d], d))
    accepted: dict[str, list[str]] = {}
    for text, segments in candidates.items():
        if len(segments) != depth:
            rejected.append({"ordinal": text, "reason": "ordinal_depth_mismatch"})
            continue
        accepted[text] = segments

    lengths = [max(len(segs[level]) for segs in accepted.values()) for level in range(depth)]
    numeric = [all(segs[level].isdigit() for segs in accepted.values()) for level in range(depth)]
    return OzLayout(depth=depth, lengths=lengths, numeric=numeric, accepted=accepted, rejected=rejected)


def append_bkdn(parent: ET.Element, layout: OzLayout) -> None:
    """Append the ``BoQBkdn`` mask (category levels, then the item level)."""
    for level in range(layout.depth):
        bkdn = ET.SubElement(parent, "BoQBkdn")
        ET.SubElement(bkdn, "Type").text = "Item" if level == layout.depth - 1 else "BoQLevel"
        ET.SubElement(bkdn, "Length").text = str(max(1, min(14, layout.lengths[level])))
        ET.SubElement(bkdn, "Num").text = "Yes" if layout.numeric[level] else "No"


@dataclass(slots=True)
class _Node:
    children: dict[str, _Node] = field(default_factory=dict)
    items: list[tuple[str, str, Any]] = field(default_factory=list)  # (leaf, ordinal, payload)


def write_oz_body(
    body: ET.Element,
    layout: OzLayout,
    payloads: list[tuple[str, Any]],
    *,
    emit_item: Callable[[ET.Element, str, str, Any], None],
    open_category: Callable[[ET.Element, list[str], list[Any]], None] | None = None,
    close_category: Callable[[ET.Element, list[str], list[Any]], None] | None = None,
) -> None:
    """Write ``payloads`` (``(ordinal, payload)``, in bill order) as a BoQ tree.

    Only ordinals in ``layout.accepted`` are written. Categories are created
    from the OZ segments themselves, so the ``RNoPart`` chain of every item
    rebuilds the ordinal it came from. ``emit_item(itemlist, leaf, ordinal,
    payload)`` writes one ``Item``; the category hooks let a phase add what
    its ``BoQCtgy`` requires before (``LblTx``) and after (``Totals``) the
    nested body. Both hooks receive the payloads under that category.
    """
    root = _Node()
    for ordinal, payload in payloads:
        segments = layout.accepted.get(ordinal)
        if segments is None:
            continue
        node = root
        for seg in segments[:-1]:
            node = node.children.setdefault(seg, _Node())
        node.items.append((segments[-1], ordinal, payload))

    def _payloads_under(node: _Node) -> list[Any]:
        found = [p for _, _, p in node.items]
        for child in node.children.values():
            found.extend(_payloads_under(child))
        return found

    def _write(container: ET.Element, node: _Node, path: list[str]) -> None:
        if node.children:
            for seg, child in node.children.items():
                ctgy = ET.SubElement(container, "BoQCtgy", ID=mint_id("oeCtgy"), RNoPart=seg)
                under = _payloads_under(child)
                if open_category is not None:
                    open_category(ctgy, path + [seg], under)
                child_body = ET.SubElement(ctgy, "BoQBody")
                _write(child_body, child, path + [seg])
                if close_category is not None:
                    close_category(ctgy, path + [seg], under)
        elif node.items:
            itemlist = ET.SubElement(container, "Itemlist")
            for leaf, ordinal, payload in node.items:
                emit_item(itemlist, leaf, ordinal, payload)

    _write(body, root, [])


def append_gaeb_info(root: ET.Element, today: date | None = None) -> None:
    """Append the ``GAEBInfo`` block every 3.3 document opens with."""
    info = ET.SubElement(root, "GAEBInfo")
    ET.SubElement(info, "Version").text = GAEB_VERSION
    ET.SubElement(info, "VersDate").text = GAEB_VERS_DATE
    ET.SubElement(info, "Date").text = (today or date.today()).isoformat()
    ET.SubElement(info, "ProgSystem").text = PROGRAM_NAME
    ET.SubElement(info, "ProgName").text = PROGRAM_NAME


def ml_text(parent: ET.Element, tag: str, text: str) -> ET.Element:
    """Append a ``tgMLText`` element: one ``<p><span>`` per line of ``text``."""
    el = ET.SubElement(parent, tag)
    lines = (text or "").split("\n") or [""]
    for line in lines:
        p = ET.SubElement(el, "p")
        ET.SubElement(p, "span").text = line
    return el


def serialize(root: ET.Element) -> str:
    """Serialize with an XML declaration, as the X8x writer does."""
    body = ET.tostring(root, encoding="unicode", xml_declaration=False)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body


__all__ = [
    "GAEB_VERSION",
    "GAEB_VERS_DATE",
    "MAX_OZ_DEPTH",
    "FileItem",
    "OzLayout",
    "OzMatch",
    "PositionIndex",
    "append_bkdn",
    "append_gaeb_info",
    "c2",
    "dec",
    "exchange_phase",
    "iter_boq_items",
    "mint_id",
    "ml_text",
    "namespace_for",
    "normalize_oz",
    "oz_segments",
    "parse_xml",
    "plan_oz_layout",
    "q3",
    "serialize",
    "write_oz_body",
]
