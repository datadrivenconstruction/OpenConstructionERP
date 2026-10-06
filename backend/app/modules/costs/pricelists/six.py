# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""SIX, the open XML exchange format for Italian price lists (schema ``six.xsd``).

Written from the published schema (version 2.0.10107.1); no regional list in
this format was available to test against, so the reader is exercised by a
synthetic file built to the schema. The parts read::

    <Documento xmlns="six.xsd">
      <intestazione autore=".." />
      <prezzario prezzarioId="..">
        <unitaDiMisura unitaDiMisuraId="1" simbolo="m²"/>
        <listaQuotazione listaQuotazioneId="Q1" lqtId="2025"/>
        <przDescrizione lingua="it" breve="Prezzario .. 2025"/>
        <prodotto prodottoId=".." prdId="A.01.001.a" unitaDiMisuraId="1" onereSicurezza="..">
          <incidenzaManodopera>35.5</incidenzaManodopera>
          <prdDescrizione lingua="it" breve=".." estesa=".."/>
          <prdQuotazione listaQuotazioneId="Q1" valore="12.50"/>

The schema qualifies attributes with its namespace, so every attribute is read
with and without it. A list can carry several price levels
(``listaQuotazione``); the reader takes the one whose id names the latest year,
else the first, and says which in the source profile. A product without a
quotation is a heading; its text is carried onto the products under it.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import IO
from xml.etree.ElementTree import Element

from app.modules.costs.pricelists.base import (
    PriceListRow,
    PriceListSource,
    amount_or_flag,
    clean_text,
    normalise_unit,
    region_from_code,
)
from app.modules.costs.pricelists.xml_stream import attr, child_text, children, iter_records, local_name

FORMAT_ID = "six_xml"

_LANGUAGE = "it"


def sniff(head: bytes, name: str) -> bool:
    text = head[:16384].decode("utf-8", errors="ignore")
    return "six.xsd" in text or ("<Documento" in text and "prodotto" in text)


def _description(el: Element) -> tuple[str, str]:
    """``(short, long)`` in Italian, else in the first language given."""
    descriptions = children(el, "prdDescrizione")
    chosen = next(
        (d for d in descriptions if attr(d, "lingua") == _LANGUAGE), descriptions[0] if descriptions else None
    )
    if chosen is None:
        return "", ""
    return clean_text(attr(chosen, "breve")), clean_text(attr(chosen, "estesa"))


def _year(value: str) -> int:
    found = re.findall(r"20\d{2}", value)
    return int(found[-1]) if found else 0


def read(stream: IO[bytes], source: PriceListSource) -> Iterator[PriceListRow]:
    """Yield every quoted product of a SIX price list."""
    units: dict[str, str] = {}
    quotations: list[tuple[str, str]] = []
    chosen_quotation: str | None = None
    headings: list[tuple[str, str]] = []  # (code, text), the open heading path
    tags = frozenset({"intestazione", "unitaDiMisura", "listaQuotazione", "przDescrizione", "prodotto"})
    for el, _ancestors in iter_records(stream, tags):
        name = local_name(el.tag)
        if name == "intestazione":
            source.publisher = attr(el, "autore") or source.publisher
            continue
        if name == "unitaDiMisura":
            units[attr(el, "unitaDiMisuraId")] = attr(el, "simbolo") or attr(el, "udmId")
            continue
        if name == "listaQuotazione":
            quotations.append((attr(el, "listaQuotazioneId"), attr(el, "lqtId")))
            continue
        if name == "przDescrizione":
            if attr(el, "lingua") in ("", _LANGUAGE) or not source.title:
                source.title = clean_text(attr(el, "breve")) or source.title
                year = _year(source.title)
                if year and not source.edition:
                    source.edition = str(year)
            continue

        if chosen_quotation is None and quotations:
            best = max(quotations, key=lambda q: _year(q[1]))
            chosen_quotation = best[0] if _year(best[1]) else quotations[0][0]
            source.profile = f"quotation:{chosen_quotation}"
        code = (attr(el, "prdId") or attr(el, "prodottoId")).strip()
        short, long_text = _description(el)
        quotes = children(el, "prdQuotazione")
        quote = next(
            (q for q in quotes if chosen_quotation is None or attr(q, "listaQuotazioneId") == chosen_quotation),
            None,
        )
        while headings and not code.startswith(headings[-1][0]):
            headings.pop()
        if quote is None or not attr(quote, "valore").strip():
            headings.append((code, long_text or short))
            continue
        if not source.region_code:
            found = region_from_code(code)
            if found:
                source.region_code, year = found
                source.edition = source.edition or year
                source.detected_from = "code_prefix"
        flags: list[str] = []
        parent_text = headings[-1][1] if headings else ""
        own = long_text or short
        description = f"{parent_text} - {own}" if parent_text and own and own not in parent_text else own or parent_text
        source_unit = units.get(attr(el, "unitaDiMisuraId"), "")
        labour_text = child_text(el, "incidenzaManodopera")
        row = PriceListRow(
            code=code,
            description=description,
            short_description=short or own,
            unit=normalise_unit(source_unit),
            source_unit=source_unit,
            rate=amount_or_flag(attr(quote, "valore"), "rate", flags),
            chapters=[(c, t[:160]) for c, t in headings[:3]],
            labour_share_pct=amount_or_flag(labour_text, "labour_share", flags) if labour_text.strip() else None,
            safety_amount=amount_or_flag(attr(el, "onereSicurezza"), "safety_amount", flags)
            if attr(el, "onereSicurezza")
            else None,
            flags=flags,
        )
        yield row


__all__ = ["FORMAT_ID", "read", "sniff"]
