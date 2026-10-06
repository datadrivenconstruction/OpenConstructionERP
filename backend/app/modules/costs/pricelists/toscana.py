# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Regione Toscana price list, XML edition (one file per province).

Layout, read from the Firenze 2025 file::

    <Prezzario xmlns="https://prezzariollpp.regione.toscana.it/prezzario.xsd">
      <intestazione autore="Regione Toscana">
        <dettaglio anno="2025" area="Provincia di Firenze"/>
        <copyright tipo="CC BY 3.0"/>
      </intestazione>
      <Contenuto>
        <Articolo codice="TOS25_01.A03.001.001" cam="0">
          <livello1>..</livello1> .. <livello4>..</livello4>
          <um>m³</um> <prezzo>13.63017</prezzo>
          <Analisi>
            <vocedettaglio codice=".." tipo="TOS25_RU" udm="ora" quantita=".." prezzo=".." importo="..">
            <totaleparziale valore=".."/> <spesegenerali percentuale="16" valore=".."/>
            <onerisicurezza percentuale="4.5" valore=".."/> <utileimpresa percentuale="10" valore=".."/>
            <prezzo valore=".."/> <incidenzamanodopera percentuale="40.36" valore=".."/>
            <incidenzasicurezza percentuale="0.56"/>
          </Analisi>
        </Articolo>

Measured on that file: 23,132 articoli, 5,286 with an analysis; in every one
the analysis lines add up to ``totaleparziale`` and ``totaleparziale`` plus
general expenses plus profit is the price, to the cent. The analysis lines
become the item's components with one balancing line for general expenses and
profit, so the components add up to the official price exactly. The
``prezzo`` inside ``Analisi`` is an attribute and the article's own ``prezzo``
is text; the two are read by their parent, not by name.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import IO
from xml.etree.ElementTree import Element

from app.modules.costs.pricelists.base import (
    PriceListRow,
    PriceListSource,
    amount_or_flag,
    clean_text,
    first_line,
    normalise_unit,
    region_from_code,
    settle_components,
)
from app.modules.costs.pricelists.xml_stream import attr, child, child_text, children, iter_records

FORMAT_ID = "toscana_xml"

# Analysis line types by the suffix of their ``tipo`` (``TOS25_RU``).
_COMPONENT_TYPES = {"RU": "labor", "PR": "material", "PRCAM": "material", "AT": "equipment"}

# Chapter 17 of the Toscana list is the safety chapter (recinzioni, apprestamenti).
_SAFETY_CHAPTERS = frozenset({"17"})


def sniff(head: bytes, name: str) -> bool:
    text = head[:8192].decode("utf-8", errors="ignore")
    return "prezzariollpp.regione.toscana.it" in text or (
        "Prezzario" in text and "Articolo" in text and "livello1" in text
    )


def _component_type(tipo: str) -> str:
    suffix = tipo.rpartition("_")[2].upper()
    return _COMPONENT_TYPES.get(suffix, "other")


def _analysis(an: Element, rate: Decimal | None, row: PriceListRow) -> None:
    flags = row.flags
    components: list[dict[str, object]] = []
    total = Decimal(0)
    for voce in children(an, "vocedettaglio"):
        importo = amount_or_flag(attr(voce, "importo"), "analysis_amount", flags)
        quantity = amount_or_flag(attr(voce, "quantita"), "analysis_quantity", flags)
        unit_rate = amount_or_flag(attr(voce, "prezzo"), "analysis_rate", flags)
        if importo is None:
            return
        total += importo
        components.append(
            {
                "code": attr(voce, "codice"),
                "name": clean_text(child_text(voce, "descrizione")),
                "unit": normalise_unit(attr(voce, "udm")),
                "quantity": float(quantity) if quantity is not None else 1.0,
                "unit_rate": float(unit_rate) if unit_rate is not None else float(importo),
                "cost": float(importo),
                "type": _component_type(attr(voce, "tipo")),
            }
        )
    for name, pct_attr, target in (
        ("spesegenerali", "percentuale", "overhead_pct"),
        ("utileimpresa", "percentuale", "profit_pct"),
    ):
        el = child(an, name)
        if el is not None:
            setattr(row, target, amount_or_flag(attr(el, pct_attr), target, flags))
    labour = child(an, "incidenzamanodopera")
    if labour is not None:
        row.labour_share_pct = amount_or_flag(attr(labour, "percentuale"), "labour_share", flags)
        row.labour_amount = amount_or_flag(attr(labour, "valore"), "labour_amount", flags)
    safety = child(an, "onerisicurezza")
    if safety is not None:
        row.safety_amount = amount_or_flag(attr(safety, "valore"), "safety_amount", flags)
    safety_share = child(an, "incidenzasicurezza")
    if safety_share is not None:
        row.safety_share_pct = amount_or_flag(attr(safety_share, "percentuale"), "safety_share", flags)
    if rate is None:
        return
    settle_components(row, components, total)


def read(stream: IO[bytes], source: PriceListSource) -> Iterator[PriceListRow]:
    """Yield the priced articoli of a Toscana XML list, filling ``source`` from its header."""
    for el, _ancestors in iter_records(stream, frozenset({"intestazione", "Articolo"})):
        name = el.tag.rpartition("}")[2]
        if name == "intestazione":
            source.publisher = attr(el, "autore") or source.publisher
            detail = child(el, "dettaglio")
            if detail is not None:
                source.edition = attr(detail, "anno") or source.edition
                source.area = attr(detail, "area") or source.area
            rights = child(el, "copyright")
            if rights is not None and attr(rights, "tipo"):
                source.licence = attr(rights, "tipo")
                source.licence_stated_in = "file"
            source.region_code = source.region_code or "TOS"
            source.detected_from = source.detected_from or "file_header"
            source.title = source.title or "Prezzario dei Lavori Pubblici della Toscana"
            continue

        code = attr(el, "codice").strip()
        flags: list[str] = []
        texts = [child_text(el, f"livello{i}") for i in range(1, 5)]
        price_el = child(el, "prezzo")
        rate = amount_or_flag(price_el.text if price_el is not None else None, "rate", flags)
        source_unit = clean_text(child_text(el, "um"))
        parts = code.split("_", 1)[-1].split(".")
        chapter_codes = [".".join(parts[: i + 1]) for i in range(min(3, len(parts)))]
        chapters = [(c, first_line(t)) for c, t in zip(chapter_codes, texts[:3], strict=False) if t.strip()]
        description = " ".join(clean_text(t) for t in texts[1:] if t.strip())
        short = " - ".join(clean_text(t) for t in texts[2:] if t.strip())
        if region_from_code(code) and not source.region_code:
            source.region_code = region_from_code(code)[0]  # type: ignore[index]
        row = PriceListRow(
            code=code,
            description=description,
            short_description=short,
            unit=normalise_unit(source_unit),
            source_unit=source_unit,
            rate=rate,
            chapters=chapters,
            safety=bool(parts) and parts[0] in _SAFETY_CHAPTERS,
            flags=flags,
        )
        if attr(el, "cam") == "1":
            row.extra["cam"] = True
        analysis = child(el, "Analisi")
        if analysis is not None:
            _analysis(analysis, rate, row)
        else:
            overhead = child(el, "spesegenerali")
            profit = child(el, "utilidiimpresa")
            if overhead is not None:
                row.extra["overhead_amount"] = clean_text(overhead.text)
            if profit is not None:
                row.extra["profit_amount"] = clean_text(profit.text)
        yield row


__all__ = ["FORMAT_ID", "read", "sniff"]
