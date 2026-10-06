# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Synthetic XPWE (Italian estimating XML) files for the importer tests.

Every file here is written by hand or generated. None is an export of a real
project and none carries a vendor's name: the small bill in ``xpwe/`` uses a
neutral processing instruction and a neutral ``CopyRight`` line, so the
importer is proven to recognise the document by its root element alone.

The small bill, ``computo_small.xpwe``, is laid out so each rule the importer
follows has a row that only that rule gets right:

* item 1 (49.11 m2): plain rows, an implicit multiplication ``2(3+4)``, a
  decimal comma, a deduction marked by a minus on ``Quantita`` and a note row
  with no factors;
* item 2 (12 m2): parts times one length;
* item 3 (1 pcs): a safety item with no measurement rows, so the declared
  quantity is the quantity;
* item 4 (24 m2): a row repeating item 2's quantity twice, and a printed
  partial subtotal whose ``Quantita`` (24) would double the item if summed;
* item 5 (10 m2): no category at all, so it lands at the top level.

The bill section (``PweVociComputo``) precedes the price list
(``PweElencoPrezzi``) on purpose: real exports differ in that order.
"""

from __future__ import annotations

from pathlib import Path

XPWE_DIR = Path(__file__).resolve().parent / "xpwe"
SMALL_COMPUTO = XPWE_DIR / "computo_small.xpwe"


def small_computo() -> bytes:
    return SMALL_COMPUTO.read_bytes()


def replaced(old: str, new: str, *, source: bytes | None = None) -> bytes:
    """The small bill with one exact fragment replaced; fails loudly if the fragment is absent."""
    text = (source or small_computo()).decode("utf-8")
    assert old in text, f"fragment not in fixture: {old!r}"
    return text.replace(old, new, 1).encode("utf-8")


def price_list_first() -> bytes:
    """The small bill with the price list moved before the measured bill."""
    text = small_computo().decode("utf-8")
    start = text.index("<PweElencoPrezzi>")
    end = text.index("</PweElencoPrezzi>") + len("</PweElencoPrezzi>")
    price_list = text[start:end]
    text = text[:start] + text[end:]
    anchor = text.index("<PweVociComputo>")
    return (text[:anchor] + price_list + text[anchor:]).encode("utf-8")


def cp1252_bill() -> bytes:
    """The small bill saved in a Windows code page, with no declaration saying so."""
    text = small_computo().decode("utf-8")
    text = text.replace("Pareti interne aula 1", "Pareti della città vecchia")
    text = text.replace("<UnMisura>m²</UnMisura>", "<UnMisura>mq</UnMisura>")
    return text.encode("cp1252")


def _header() -> str:
    return (
        "<PweDocumento><CopyRight>Synthetic test fixture</CopyRight><TipoDocumento>1</TipoDocumento>"
        "<TipoFormato>XMLPwe</TipoFormato><PweDatiGenerali>"
        "<PweDGCapitoliCategorie><PweDGSuperCapitoli>"
        '<DGSuperCapitoliItem ID="1"><DesSintetica>OPERE EDILI</DesSintetica><Codice>E</Codice></DGSuperCapitoliItem>'
        "</PweDGSuperCapitoli><PweDGCapitoli>"
        '<DGCapitoliItem ID="1"><DesSintetica>Murature</DesSintetica><Codice>E.01</Codice></DGCapitoliItem>'
        "</PweDGCapitoli></PweDGCapitoliCategorie>"
        "<PweDGConfigurazione><PweDGConfigNumeri><Divisa>Euro</Divisa><Quantita>10.2|0</Quantita>"
        "</PweDGConfigNumeri></PweDGConfigurazione></PweDatiGenerali><PweMisurazioni>"
    )


def _price_item(index: int, description: str, analysis_lines: int) -> str:
    analysis = "".join(
        f'<EPARItem ID="{n}"><IDEP>0</IDEP><Descrizione>Risorsa {n} della voce {index}</Descrizione>'
        f"<Misura>ora</Misura><Qt>0.{n:02d}</Qt><Prezzo>3{n}.17</Prezzo></EPARItem>"
        for n in range(1, analysis_lines + 1)
    )
    return (
        f'<EPItem ID="{index}"><TipoEP>0</TipoEP><Tariffa>EX26_01.A{index // 1000:02d}.{index % 1000:03d}.001</Tariffa>'
        f"<DesRidotta>Voce {index}</DesRidotta><DesEstesa>{description}</DesEstesa><UnMisura>mq</UnMisura>"
        f"<Prezzo1>{index % 97 + 1}.25</Prezzo1><IDSpCap>1</IDSpCap><IDCap>1</IDCap><IDSbCap>0</IDSbCap>"
        f"<Flags>0</Flags><IncMDO>35.5</IncMDO>"
        + (f"<PweEPAnalisi><PweEPAR>{analysis}</PweEPAR></PweEPAnalisi>" if analysis else "")
        + "</EPItem>"
    )


def price_list(items: int, *, analysis_lines: int = 2, description: str | None = None) -> bytes:
    """A price-list-only export of ``items`` items, the shape a regional list takes."""
    body = description or "Muratura in blocchi di laterizio, compresa la malta e ogni onere."
    parts = [_header(), "<PweElencoPrezzi>"]
    parts.extend(_price_item(i, body, analysis_lines) for i in range(1, items + 1))
    parts.append("</PweElencoPrezzi><PweVociComputo></PweVociComputo></PweMisurazioni></PweDocumento>")
    return "".join(parts).encode("utf-8")


def large_bill(target_bytes: int) -> bytes:
    """A price-list-heavy bill of about ``target_bytes``: long items with analyses, a few hundred measured."""
    description = ("Fornitura e posa in opera di muratura portante in blocchi di laterizio porizzato, " * 12).strip()
    one_item = len(_price_item(1, description, 6).encode("utf-8"))
    items = max(target_bytes // one_item, 1)
    parts = [_header(), "<PweElencoPrezzi>"]
    parts.extend(_price_item(i, description, 6) for i in range(1, items + 1))
    parts.append("</PweElencoPrezzi><PweVociComputo>")
    for n in range(1, 301):
        parts.append(
            f'<VCItem ID="{n}"><IDEP>{n % items + 1}</IDEP><Quantita>6.00</Quantita><IDSpCat>0</IDSpCat>'
            f'<PweVCMisure><RGItem ID="{n}"><IDVV>-2</IDVV><Descrizione>Parete {n}</Descrizione>'
            "<PartiUguali>2</PartiUguali><Lunghezza>3</Lunghezza><Larghezza></Larghezza><HPeso></HPeso>"
            "<Quantita>6.00</Quantita><Flags>0</Flags></RGItem></PweVCMisure></VCItem>"
        )
    parts.append("</PweVociComputo></PweMisurazioni></PweDocumento>")
    return "".join(parts).encode("utf-8")


def chained_bill(depth: int) -> bytes:
    """A bill of ``depth`` items, each but the last repeating the next one's quantity plus one.

    Item ``n`` has a "see item" row naming item ``n + 1`` and a row of 1; the
    last item measures 2 x 3. Item 1 therefore totals ``6 + depth - 1``, and
    reading it means following a chain ``depth`` items long.
    """
    parts = [_header(), "<PweElencoPrezzi>", _price_item(1, "Voce concatenata.", 0), "</PweElencoPrezzi>"]
    parts.append("<PweVociComputo>")
    for n in range(1, depth + 1):
        if n < depth:
            rows = (
                f'<RGItem ID="{2 * n}"><IDVV>{n + 1}</IDVV><Descrizione>Vedi voce {n + 1}</Descrizione>'
                "<PartiUguali></PartiUguali><Lunghezza></Lunghezza><Larghezza></Larghezza><HPeso></HPeso>"
                "<Quantita></Quantita><Flags>0</Flags></RGItem>"
                f'<RGItem ID="{2 * n + 1}"><IDVV>-2</IDVV><Descrizione>Aggiunta</Descrizione>'
                "<PartiUguali></PartiUguali><Lunghezza>1</Lunghezza><Larghezza></Larghezza><HPeso></HPeso>"
                "<Quantita>1.00</Quantita><Flags>0</Flags></RGItem>"
            )
        else:
            rows = (
                f'<RGItem ID="{2 * n}"><IDVV>-2</IDVV><Descrizione>Parete</Descrizione>'
                "<PartiUguali>2</PartiUguali><Lunghezza>3</Lunghezza><Larghezza></Larghezza><HPeso></HPeso>"
                "<Quantita>6.00</Quantita><Flags>0</Flags></RGItem>"
            )
        parts.append(
            f'<VCItem ID="{n}"><IDEP>1</IDEP><Quantita></Quantita><IDSpCat>0</IDSpCat>'
            f"<PweVCMisure>{rows}</PweVCMisure></VCItem>"
        )
    parts.append("</PweVociComputo></PweMisurazioni></PweDocumento>")
    return "".join(parts).encode("utf-8")


def deductions_bill(*, credit_quantity: str = "2.00") -> bytes:
    """The small bill with two deductions, the way a bill of lesser works writes them.

    Item 5 (10 m2 at 13.63) is measured as minus ten, so it takes 136.30 off.
    A new item 6 is ``credit_quantity`` of a price-list item priced at -50.00,
    a credit; at the default of two it takes 100.00 off. With a negative
    ``credit_quantity`` the two minuses cancel and item 6 adds money instead.

    The file's own total is the signed sum of its items: 2418.2693 with the
    defaults (669.3693 + 578.40 + 250.00 + 1156.80 - 136.30 - 100.00).
    """
    content = replaced(
        '<VCItem ID="5"><IDEP>1</IDEP><Quantita>10.00</Quantita>',
        '<VCItem ID="5"><IDEP>1</IDEP><Quantita>-10.00</Quantita>',
    )
    content = replaced(
        "<Lunghezza>10</Lunghezza><Larghezza></Larghezza><HPeso></HPeso><Quantita>10.00</Quantita>",
        "<Lunghezza>10</Lunghezza><Larghezza></Larghezza><HPeso></HPeso><Quantita>-10.00</Quantita>",
        source=content,
    )
    content = replaced(
        "</PweVociComputo>",
        f'<VCItem ID="6"><IDEP>4</IDEP><Quantita>{credit_quantity}</Quantita><IDSpCat>0</IDSpCat><IDCat>0</IDCat>'
        "<IDSbCat>0</IDSbCat><PweVCMisure></PweVCMisure></VCItem></PweVociComputo>",
        source=content,
    )
    return replaced(
        "</PweElencoPrezzi>",
        '<EPItem ID="4"><TipoEP>0</TipoEP><Tariffa>EX26_99.Z01.001.001</Tariffa><DesRidotta>Minori lavori</DesRidotta>'
        "<DesEstesa>Detrazione per minori lavori di finitura.</DesEstesa><UnMisura>cad</UnMisura>"
        "<Prezzo1>-50.00</Prezzo1><IDSpCap>1</IDSpCap><IDCap>0</IDCap><IDSbCap>0</IDSbCap><Flags>0</Flags></EPItem>"
        "</PweElencoPrezzi>",
        source=content,
    )


def measured_bill(items: int, *, categories: int = 25) -> bytes:
    """A bill of ``items`` measured items spread over ``categories`` categories, for persistence at scale.

    Each item has two measurement rows and its own price-list item, so the
    import creates ``items + categories`` positions.
    """
    head = _header().replace(
        "</PweDGCapitoli></PweDGCapitoliCategorie>",
        "</PweDGCapitoli><PweDGCategorie>"
        + "".join(
            f'<DGCategorieItem ID="{c}"><DesSintetica>Categoria {c}</DesSintetica><Codice>C{c:03d}</Codice>'
            "</DGCategorieItem>"
            for c in range(1, categories + 1)
        )
        + "</PweDGCategorie></PweDGCapitoliCategorie>",
    )
    parts = [head, "<PweElencoPrezzi>"]
    parts.extend(_price_item(i, f"Voce misurata numero {i}, compresa ogni fornitura.", 0) for i in range(1, items + 1))
    parts.append("</PweElencoPrezzi><PweVociComputo>")
    for n in range(1, items + 1):
        parts.append(
            f'<VCItem ID="{n}"><IDEP>{n}</IDEP><Quantita>10.50</Quantita><IDSpCat>0</IDSpCat>'
            f"<IDCat>{n % categories + 1}</IDCat><IDSbCat>0</IDSbCat><PweVCMisure>"
            f'<RGItem ID="{2 * n}"><IDVV>-2</IDVV><Descrizione>Parete {n}</Descrizione>'
            "<PartiUguali>2</PartiUguali><Lunghezza>3</Lunghezza><Larghezza></Larghezza><HPeso></HPeso>"
            "<Quantita>6.00</Quantita><Flags>0</Flags></RGItem>"
            f'<RGItem ID="{2 * n + 1}"><IDVV>-2</IDVV><Descrizione>Soletta {n}</Descrizione>'
            "<PartiUguali></PartiUguali><Lunghezza>3</Lunghezza><Larghezza></Larghezza><HPeso>1,5</HPeso>"
            "<Quantita>4.50</Quantita><Flags>0</Flags></RGItem></PweVCMisure></VCItem>"
        )
    parts.append("</PweVociComputo></PweMisurazioni></PweDocumento>")
    return "".join(parts).encode("utf-8")
