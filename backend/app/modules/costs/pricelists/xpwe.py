# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""XPWE (Italian estimating XML) as a price list.

An XPWE export carries the price list an estimate is priced from
(``PweElencoPrezzi``), and an estimating program can export a regional list on
its own in the same file. Each ``EPItem`` becomes one row:

* ``Tariffa`` the code, ``DesEstesa`` the description, ``DesRidotta`` (or
  ``DesBreve``) the short one, ``UnMisura`` the unit, ``Prezzo1`` the rate;
* ``IDSpCap`` / ``IDCap`` / ``IDSbCap`` the chapter path, as the chapter's
  ``Codice`` and ``DesSintetica``;
* ``IncMDO`` and ``IncSIC`` the labour and safety shares in percent, and
  ``IncMAT`` / ``IncATTR`` the material and equipment shares beside them;
* the ``0x8000000`` flag a safety-cost item;
* the analysis lines (``PweEPAnalisi``) the components.

The file is read by :func:`app.modules.boq.importers.xpwe.stream_price_list`,
the same streaming parse the bill import uses, so the format has one parser.
It is read twice, from disk, never whole into memory: a first pass indexes
every item's code and the chapter tree, the second yields the rows, so an
analysis line naming an item further on in the file is resolved without
holding anything back.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import IO, Any

from app.modules.boq.importers.xpwe import (
    ROOT_TAG,
    XpweDocument,
    XpwePriceItem,
    index_price_list,
    plain_decimal,
    stream_price_list,
)
from app.modules.costs.pricelists.base import (
    PriceListRow,
    PriceListSource,
    clean_text,
    normalise_unit,
    region_from_code,
    settle_components,
)

FORMAT_ID = "xpwe"


def sniff(head: bytes, name: str) -> bool:
    """An XPWE document, by its root element; the file name does not decide it."""
    return b"<" + ROOT_TAG.encode("ascii") in head[:4096]


def read_member(opener: Callable[[], IO[bytes]], source: PriceListSource) -> Iterator[PriceListRow]:
    """Yield one row per price-list item, opening the file once to index it and once to read it.

    The first pass keeps only each item's code by its id, the header and the
    chapter tree; the second yields the rows, each analysis line naming the
    item it refers to wherever that item sits in the file.

    Raises:
        ImporterParseError: The upload is not an XPWE document, or is malformed.
    """
    with opener() as probe:
        seekable = probe.seekable()
        if not seekable:
            # A ZIP member reads forward only, and the encoding probe rewinds:
            # it is copied to disk once, in chunks, and both passes read that.
            spool = tempfile.TemporaryFile(prefix="oe-xpwe-")  # noqa: SIM115
            shutil.copyfileobj(probe, spool, 1 << 20)
            spool.seek(0)
    if not seekable:
        with spool:
            yield from read(spool, source)
        return
    doc = XpweDocument()
    with opener() as stream:
        codes = index_price_list(stream, doc)
    if doc.header.get("Oggetto") and not source.title:
        source.title = doc.header["Oggetto"]
    with opener() as stream:
        for item in stream_price_list(stream, doc):
            yield _row(item, doc, codes, source)


def read(stream: IO[bytes], source: PriceListSource) -> Iterator[PriceListRow]:
    """:func:`read_member` over one open, seekable stream, rewound between the passes."""
    start = stream.tell()

    def _rewound() -> _Borrowed:
        stream.seek(start)
        return _Borrowed(stream)

    yield from read_member(_rewound, source)


class _Borrowed:
    """The caller's stream, lent to a ``with`` block that must not close it."""

    def __init__(self, stream: IO[bytes]) -> None:
        self.stream = stream

    def __enter__(self) -> IO[bytes]:
        return self.stream

    def __exit__(self, *_exc: object) -> None:
        return None


def _row(item: XpwePriceItem, doc: XpweDocument, codes: dict[str, str], source: PriceListSource) -> PriceListRow:
    flags: list[str] = []
    try:
        rate = plain_decimal(item.price_text)
    except ValueError:
        rate = None
        flags.append("broken_number:rate")
    if not source.region_code:
        found = region_from_code(item.code)
        if found:
            source.region_code, year = found
            source.edition = source.edition or year
            source.detected_from = "code_prefix"
    components: list[dict[str, Any]] = []
    total = Decimal(0)
    for line in item.analysis:
        quantity = line["quantity"] if line["quantity"] is not None else Decimal(1)
        unit_rate = line["unit_rate"] if line["unit_rate"] is not None else Decimal(0)
        cost = quantity * unit_rate
        total += cost
        components.append(
            {
                "code": codes.get(line["ref_id"], ""),
                "name": clean_text(line["name"]),
                "unit": normalise_unit(line["unit"]),
                "quantity": float(quantity),
                "unit_rate": float(unit_rate),
                "cost": float(cost),
                "type": "other",
            }
        )
    extra: dict[str, Any] = {}
    for key in ("material", "equipment"):
        if key in item.share_pcts:
            extra[f"{key}_share_pct"] = format(item.share_pcts[key].normalize(), "f")
    row = PriceListRow(
        code=item.code,
        description=clean_text(item.description) or clean_text(item.short_description),
        short_description=clean_text(item.short_description),
        unit=normalise_unit(item.unit),
        source_unit=item.unit,
        rate=rate,
        chapters=[(group.code, group.title) for group in doc.chapter_path(item)],
        labour_share_pct=item.share_pcts.get("labour"),
        safety_share_pct=item.share_pcts.get("safety"),
        safety=item.is_safety,
        flags=flags,
        extra=extra,
    )
    # The analysis lines add up to the bare cost; the list price carries
    # general expenses and profit on top (5.34 of a 13.63 voce), and the
    # editor prices a line from its components.
    settle_components(row, components, total)
    return row


__all__ = ["FORMAT_ID", "read", "sniff"]
