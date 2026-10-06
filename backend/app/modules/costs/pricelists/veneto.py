# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Regione Veneto price list, XML edition.

Layout, read from the 2026 file::

    <prezzario cod="2026" desc="Prezzario 2026" ver="1.1">
      <settore cod="VEN26-01" desc="OPERE EDILI">
        <capitolo cod="VEN26-01.02" desc="SCAVI">
          <paragrafo cod="VEN26-01.02.01" manodopera="0">
            <sint>SCAVO DI PULIZIA ..</sint> <estesa>Scavo di pulizia generale ..</estesa>
            <prezzi>
              <prezzo cod="VEN26-01.02.01.00" umi="m²" val="3.47" man="35.44">SCAVO ..</prezzo>

``man`` is the labour share in percent. The file names no licence and no
publisher; the region is read off the code prefix.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator
from typing import IO

from app.modules.costs.pricelists.base import (
    PriceListRow,
    PriceListSource,
    amount_or_flag,
    clean_text,
    normalise_unit,
    region_from_code,
)
from app.modules.costs.pricelists.xml_stream import attr, child, child_text, children, iter_records, local_name

FORMAT_ID = "veneto_xml"


def sniff(head: bytes, name: str) -> bool:
    text = head[:8192].decode("utf-8", errors="ignore")
    return "<prezzario" in text and "<settore" in text and "<capitolo" in text


def _same_text(a: str, b: str) -> bool:
    """Equal once quotes and case are folded: the list writes ’ in one place and ' in the other."""

    def fold(s: str) -> str:
        s = unicodedata.normalize("NFKC", s).replace("’", "'").replace("`", "'")
        return re.sub(r"\s+", " ", s).strip().lower()

    return fold(a) == fold(b)


def read(stream: IO[bytes], source: PriceListSource) -> Iterator[PriceListRow]:
    """Yield every priced voce of a Veneto XML list, filling ``source`` as it goes."""
    source.title = source.title or "Prezzario regionale dei lavori pubblici del Veneto"
    for el, ancestors in iter_records(stream, frozenset({"paragrafo"})):
        root = ancestors[0] if ancestors else None
        if root is not None and local_name(root.tag) == "prezzario" and not source.edition:
            source.edition = attr(root, "cod") or None
        chapters = [
            (attr(a, "cod"), clean_text(attr(a, "desc")))
            for a in ancestors
            if local_name(a.tag) in {"settore", "capitolo"}
        ]
        para_code = attr(el, "cod")
        sint = clean_text(child_text(el, "sint"))
        estesa = clean_text(child_text(el, "estesa"))
        chapters.append((para_code, sint))
        prezzi = child(el, "prezzi")
        for price in children(prezzi, "prezzo") if prezzi is not None else []:
            code = attr(price, "cod").strip()
            flags: list[str] = []
            item_text = clean_text(price.text)
            description = estesa or sint
            if item_text and not _same_text(item_text, sint):
                description = f"{description} - {item_text}" if description else item_text
            source_unit = clean_text(attr(price, "umi"))
            if not source.region_code:
                found = region_from_code(code)
                if found:
                    source.region_code, year = found
                    source.edition = source.edition or year
                    source.detected_from = "code_prefix"
            row = PriceListRow(
                code=code,
                description=description,
                short_description=item_text or sint,
                unit=normalise_unit(source_unit),
                source_unit=source_unit,
                rate=amount_or_flag(attr(price, "val"), "rate", flags),
                chapters=list(chapters),
                labour_share_pct=amount_or_flag(attr(price, "man"), "labour_share", flags),
                flags=flags,
            )
            previous = attr(price, "ex").strip()
            if previous:
                row.extra["previous_code"] = previous
            yield row


__all__ = ["FORMAT_ID", "read", "sniff"]
