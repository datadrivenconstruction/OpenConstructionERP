# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Regione Lombardia price list, XML edition, in the two layouts one ZIP carries.

The 2026 archive holds the list twice. The current layout, about 125 MB::

    <report><voci>
      <voci>
        <riferimenti_voce><autore>LOM</autore><anno>2026</anno><edizione>1</edizione></riferimenti_voce>
        <dettaglio_voce codice_voce="LOM261.OC.EEA.Pa01.C0625.Sb010.0000.-" prezzo_voce="310.62"
            unita_misura_voce="1 cad" importo_senza_sgui_voce="245.55" rapporto_RU_voce="5.13"
            tipologia_risorsa="OPERA COMPIUTA">
          <declaratoria_voce>..</declaratoria_voce>
          <risorse><risorsaDTOList codifica_risorsa=".." udm_risorsa="1 cad" quantita_risorsa="1.00000"
              prezzo_risorsa="229.62" importo_risorsa="229.62" tipologia_risorsa="RISORSA MATERIALE">
            <declaratoria_risorsa>..</declaratoria_risorsa></risorsaDTOList></risorse>
          <cod_liv_1>OC</cod_liv_1><descr_liv_1>OPERA COMPIUTA</descr_liv_1> .. up to liv_11

and the previous layout, an office-database export (``dataroot``) with
``Codice``, ``Declaratoria``, ``U_M``, ``Prezzo`` and ``Rapporto_RU``.

Measured on the current file: 39,872 voci, 158 priced at 0.00 (resource
headings, skipped and counted), and in every voce with resources the
resources add up to ``importo_senza_sgui_voce`` to the cent; the difference
to the price is general expenses and profit, carried as one balancing
component. ``rapporto_RU_voce`` is a percentage here and a ratio (0.456) in
the previous layout; both are stored as a percentage.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import IO

from app.modules.costs.pricelists.base import (
    PriceListRow,
    PriceListSource,
    amount_or_flag,
    clean_text,
    normalise_unit,
    region_from_code,
    settle_components,
)
from app.modules.costs.pricelists.xml_stream import attr, child, child_text, children, iter_records

FORMAT_ID = "lombardia_xml"
LEGACY_FORMAT_ID = "lombardia_legacy_xml"

_RESOURCE_TYPES = {
    "RISORSA UMANA": "labor",
    "RISORSA MATERIALE": "material",
    "RISORSA STRUMENTALE PRODUTTIVA": "equipment",
    "RISORSA STRUMENTALE TECNOLOGICA": "equipment",
}


def sniff(head: bytes, name: str) -> bool:
    text = head[:16384].decode("utf-8", errors="ignore")
    return "<report" in text and "dettaglio_voce" in text and "codice_voce" in text


def sniff_legacy(head: bytes, name: str) -> bool:
    text = head[:16384].decode("utf-8", errors="ignore")
    return "<dataroot" in text and "<Codice>LOM" in text


def _chapters(detail) -> list[tuple[str, str]]:  # type: ignore[no-untyped-def]
    out: list[tuple[str, str]] = []
    path: list[str] = []
    for level in range(1, 12):
        code = clean_text(child_text(detail, f"cod_liv_{level}"))
        title = clean_text(child_text(detail, f"descr_liv_{level}"))
        if not code and not title:
            break
        path.append(code)
        out.append((".".join(path), title))
    # The deepest level is the voce itself; the list's chapters are above it.
    return out[:4]


def read(stream: IO[bytes], source: PriceListSource) -> Iterator[PriceListRow]:
    """Yield every priced voce of the current Lombardia layout."""
    source.region_code = source.region_code or "LOM"
    source.title = source.title or "Prezzario Regione Lombardia"
    for el, _ancestors in iter_records(stream, frozenset({"voci"})):
        detail = child(el, "dettaglio_voce")
        if detail is None:
            continue
        refs = child(el, "riferimenti_voce")
        if refs is not None and not source.edition:
            source.edition = clean_text(child_text(refs, "anno")) or None
            source.detected_from = "file_header"
            edition_no = clean_text(child_text(refs, "edizione"))
            if edition_no:
                source.title = f"Prezzario Regione Lombardia, edizione {edition_no}"
        flags: list[str] = []
        code = attr(detail, "codice_voce").strip()
        rate = amount_or_flag(attr(detail, "prezzo_voce"), "rate", flags)
        net = amount_or_flag(attr(detail, "importo_senza_sgui_voce"), "net_amount", flags)
        source_unit = clean_text(attr(detail, "unita_misura_voce"))
        text = clean_text(child_text(detail, "declaratoria_voce"))
        row = PriceListRow(
            code=code,
            description=text,
            short_description=text[:160],
            unit=normalise_unit(source_unit),
            source_unit=source_unit,
            rate=rate,
            chapters=_chapters(detail),
            labour_share_pct=amount_or_flag(attr(detail, "rapporto_RU_voce"), "labour_share", flags),
            flags=flags,
        )
        row.extra["resource_type"] = attr(detail, "tipologia_risorsa")
        resources = child(detail, "risorse")
        if resources is not None and rate is not None and net is not None:
            components: list[dict[str, object]] = []
            total = Decimal(0)
            for res in children(resources, "risorsaDTOList"):
                amount = amount_or_flag(attr(res, "importo_risorsa"), "resource_amount", flags)
                if amount is None:
                    components = []
                    break
                total += amount
                quantity = amount_or_flag(attr(res, "quantita_risorsa"), "resource_quantity", flags)
                unit_rate = amount_or_flag(attr(res, "prezzo_risorsa"), "resource_rate", flags)
                components.append(
                    {
                        "code": attr(res, "codifica_risorsa"),
                        "name": clean_text(child_text(res, "declaratoria_risorsa")),
                        "unit": normalise_unit(attr(res, "udm_risorsa")),
                        "quantity": float(quantity) if quantity is not None else 1.0,
                        "unit_rate": float(unit_rate) if unit_rate is not None else float(amount),
                        "cost": float(amount),
                        "type": _RESOURCE_TYPES.get(attr(res, "tipologia_risorsa"), "other"),
                    }
                )
            settle_components(row, components, total)
        yield row


def read_legacy(stream: IO[bytes], source: PriceListSource) -> Iterator[PriceListRow]:
    """Yield every priced voce of the previous Lombardia layout (office export)."""
    source.region_code = source.region_code or "LOM"
    source.title = source.title or "Prezzario Regione Lombardia"
    # Headings are the rows without a price; a voce's chapters are the headings
    # whose codes prefix its own. There are a few hundred, held as a dict.
    headings: dict[str, str] = {}
    for el, _ancestors in iter_records(stream, depth=1):
        code = clean_text(child_text(el, "Codice"))
        if not source.edition:
            found = region_from_code(code)
            if found:
                source.edition = found[1]
                source.detected_from = "code_prefix"
        text = clean_text(child_text(el, "Declaratoria"))
        price_text = child_text(el, "Prezzo")
        if not code:
            continue
        if not price_text.strip():
            headings[code] = text
            continue
        flags: list[str] = []
        ratio = amount_or_flag(child_text(el, "Rapporto_RU"), "labour_share", flags)
        segments = code.split(".")
        chapters = [
            (".".join(segments[:i]), headings[".".join(segments[:i])])
            for i in range(2, len(segments))
            if ".".join(segments[:i]) in headings
        ]
        source_unit = clean_text(child_text(el, "U_M"))
        yield PriceListRow(
            code=code,
            description=text,
            short_description=text[:160],
            unit=normalise_unit(source_unit),
            source_unit=source_unit,
            rate=amount_or_flag(price_text, "rate", flags),
            chapters=chapters,
            labour_share_pct=(ratio * 100).quantize(Decimal("0.01")) if ratio is not None else None,
            flags=flags,
        )


__all__ = ["FORMAT_ID", "LEGACY_FORMAT_ID", "read", "read_legacy", "sniff", "sniff_legacy"]
