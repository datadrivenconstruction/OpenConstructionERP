# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Excel (.xlsx) and CSV BOQ importer.

Generic spreadsheet ingester with three classification heuristics on top
of the column-alias mapper:

* **NRM** - UK New Rules of Measurement. Detects element codes like
  ``2.6.1`` and section headers like ``Element 2 - Substructure``.
* **MasterFormat** - US CSI MasterFormat. Detects 6-digit codes like
  ``03 30 00`` and division headers like
  ``Division 03 - Cast-in-Place Concrete``.
* **Generic** - anything else goes into ``classification["code"]``.

Epic I3 (refactor) keeps the parser pure (no DB I/O, no FastAPI types);
all the per-row error reporting, dry-run handling and inline validation
the route used to do inline now live in the dispatcher route. Epics
I9 / I10 wire in the NRM and MasterFormat division detectors as
:func:`_infer_classification`.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import unicodedata
from typing import Any, ClassVar, Literal

from app.core.file_signature import detect as detect_signature
from app.core.sheet_header import find_header_row
from app.modules.boq.importers._base import (
    ImportedBOQ,
    ImportedPosition,
    ImporterParseError,
)
from app.modules.boq.importers._encoding import (
    decode_text_bytes,
    parse_numeric_cell,
    safe_float,
)
from app.modules.boq.importers.hungary_workbook import parse_hungarian_workbook
from app.modules.boq.roundtrip import ID_COLUMN_ALIASES, normalise_id
from app.modules.boq.units import is_lump_sum_unit

logger = logging.getLogger(__name__)


# ── Column alias map, tagged by language ───────────────────────────────────
#
# Canonical column → accepted header strings (lowercased), grouped by the
# language whose market writes them. Editing this map is the supported
# extension point for new locale variants (Polish ``Ilosc``, Italian
# ``Quantità`` etc. land here).
#
# It is a table keyed by language rather than a flat set of strings because a
# caller has to be able to ask which languages a header row can be read in,
# and deriving that back out of a flat set means guessing which market owns
# ``prezzo``. ``_COLUMN_ALIASES`` below is the union, computed rather than
# maintained, so the matcher keeps behaving exactly as it did.
#
# Every accented header carries its unaccented twin: exports strip diacritics
# often enough that a table holding only ``descrição`` reads nothing out of a
# file whose header says ``DESCRICAO``.
#
# Strings no single language owns live under ``"en"``: the abbreviations an
# export writes whatever its locale (``pos``, ``nr``, ``qty``) and the
# classification standards (``nrm``, ``csi``, ``masterformat``). The German
# ones stay German - ``kg`` is a DIN 276 Kostengruppe, not a kilogramme.
_HEADERS_BY_LANGUAGE: dict[str, dict[str, tuple[str, ...]]] = {
    "en": {
        "ordinal": (
            "pos",
            "pos.",
            "position",
            "ordinal",
            "nr",
            "nr.",
            "no",
            "no.",
            "ord",
            "item",
            "item no",
            "ref",
            "#",
            # South Asian and Commonwealth bills: "Sl. No.", "S. No.", "Sr. No.".
            "sl. no.",
            "s. no.",
            "sr. no.",
        ),
        "description": (
            "description",
            "desc",
            "text",
            "item description",
            "description of item",
            "description of work",
        ),
        "unit": ("unit", "uom", "unit of measure"),
        "quantity": ("quantity", "qty", "qty."),
        "unit_rate": ("unit rate", "rate", "unitrate", "unit price", "unit cost", "price"),
        "total": ("total", "amount", "subtotal", "sum", "total price"),
        # Note: ``"code"`` lives here in the ``classification`` group, not in
        # ``ordinal``. Spreadsheets that name their classification column
        # "Code" (NRM / MasterFormat exports) need that header to map to
        # ``classification`` so the I9 / I10 heuristics can infer ``nrm`` /
        # ``masterformat``.
        "classification": (
            "classification",
            "nrm",
            "code",
            "csi",
            "masterformat",
            "element",
            "division",
            "category",
            "trade",
            "cost code",
            "cost group",
            "class",
        ),
    },
    "de": {
        "ordinal": ("oz", "pos.-nr.", "lv-pos."),
        "description": ("beschreibung", "leistung", "bezeichnung", "kurztext"),
        "unit": ("einheit", "me"),
        "quantity": ("menge",),
        "unit_rate": ("einheitspreis", "ep", "preis"),
        "total": ("gesamt", "gesamtpreis", "gp"),
        "classification": ("din 276", "din276", "kg"),
    },
    "es": {
        "description": ("descripción", "descripcion", "designación", "designacion"),
        "unit": ("unidad", "uds", "ud"),
        "quantity": ("cantidad", "cant", "cant."),
        "unit_rate": ("precio",),
        "total": ("importe",),
    },
    "fr": {
        "description": ("désignation", "designation"),
        "unit": ("unité",),
        "quantity": ("quantité",),
        "unit_rate": ("prix",),
        "total": ("montant", "prix total", "montant ht", "total ht"),
    },
    "it": {
        "description": ("descrizione",),
        "unit": ("unità", "u"),
        "quantity": ("quantità", "quantita"),
        "unit_rate": ("prezzo",),
        "total": ("importo", "totale", "importo totale"),
    },
    "pl": {
        "description": ("opis",),
        "unit": ("jed",),
        "quantity": ("ilość", "ilosc"),
        # Polish carried no rate header at all until the table was split by
        # language, which made a Polish bill import with every rate at zero.
        "unit_rate": ("cena jednostkowa", "cena jedn.", "cena"),
    },
    "ru": {
        "description": ("наименование",),
        "unit": ("ед", "ед."),
        "quantity": ("количество", "кол-во"),
        "unit_rate": ("цена",),
        "total": ("стоимость",),
    },
    "pt": {
        "ordinal": ("nº", "n°", "n.º", "ordem"),
        "description": (
            "descrição",
            "descricao",
            "discriminação",
            "discriminacao",
            "especificação",
            "especificacao",
            "serviço",
            "servico",
        ),
        "unit": ("unidade", "und", "unid", "unid.", "un"),
        "quantity": ("quantidade", "qtd", "qtde", "quant", "quant."),
        "unit_rate": (
            "preço unitário",
            "preco unitario",
            "preço unit.",
            "preco unit.",
            "valor unitário",
            "valor unitario",
            "custo unitário",
            "custo unitario",
        ),
        "total": ("valor total", "preço total", "preco total"),
        # Brazilian estimators label the classification column after the
        # reference they priced from, so these must not fall to ``ordinal``.
        "classification": ("sinapi", "código sinapi", "codigo sinapi", "nbr", "nbr 12721"),
    },
    "nl": {
        "ordinal": ("post", "postnr", "postnr.", "volgnr", "volgnr."),
        "description": ("omschrijving", "beschrijving"),
        "unit": ("eenheid", "eenh", "eenh."),
        "quantity": ("hoeveelheid", "aantal", "hvh"),
        "unit_rate": ("eenheidsprijs", "prijs per eenheid", "prijs"),
        "total": ("totaal", "totaalbedrag", "bedrag"),
    },
    "cs": {
        "ordinal": ("poř.", "por.", "poř. č.", "por. c.", "p.č.", "p.c.", "pol."),
        "description": ("popis", "název", "nazev", "popis položky", "popis polozky"),
        "unit": ("mj", "m.j.", "měrná jednotka", "merna jednotka", "jednotka"),
        "quantity": ("množství", "mnozstvi", "výměra", "vymera"),
        "unit_rate": ("jednotková cena", "jednotkova cena", "j. cena", "cena"),
        "total": ("celkem", "cena celkem", "celková cena", "celkova cena"),
    },
    "sk": {
        "ordinal": ("por.", "por. č.", "p. č.", "p. c."),
        "description": ("popis", "názov", "nazov", "popis položky", "popis polozky"),
        "unit": ("mj", "m.j.", "merná jednotka", "merna jednotka", "jednotka"),
        "quantity": ("množstvo", "mnozstvo", "výmera", "vymera"),
        "unit_rate": ("jednotková cena", "jednotkova cena", "cena"),
        "total": ("spolu", "celkom", "cena spolu"),
    },
    "tr": {
        "ordinal": ("sıra", "sira", "sıra no", "sira no", "poz", "poz no"),
        "description": (
            "tanım",
            "tanim",
            "iş kalemi",
            "is kalemi",
            "açıklama",
            "aciklama",
            "imalatın cinsi",
            "imalatin cinsi",
        ),
        "unit": ("birim", "ölçü birimi", "olcu birimi"),
        "quantity": ("miktar", "metraj"),
        "unit_rate": ("birim fiyat", "birim fiyatı", "birim fiyati"),
        "total": ("tutar", "toplam", "toplam tutar"),
    },
    "hu": {
        "ordinal": ("sorszám", "sorszam", "tételszám", "tetelszam", "ssz", "ssz."),
        "description": ("megnevezés", "megnevezes", "tétel szövege", "tetel szovege", "leírás", "leiras"),
        "unit": ("egység", "egyseg", "m.e.", "mennyiségi egység", "mennyisegi egyseg"),
        "quantity": ("mennyiség", "mennyiseg"),
        "unit_rate": ("egységár", "egysegar", "egység ár", "egyseg ar"),
        "total": ("összesen", "osszesen", "összeg", "osszeg", "mindösszesen", "mindosszesen"),
    },
    "ro": {
        "ordinal": ("nr. crt.", "nr crt", "crt.", "poz."),
        "description": ("denumire", "denumire lucrare", "denumirea lucrării", "denumirea lucrarii", "descriere"),
        "unit": ("um", "u.m.", "unitate", "unitate de măsură", "unitate de masura"),
        "quantity": ("cantitate",),
        "unit_rate": ("preț unitar", "pret unitar"),
        "total": ("valoare", "valoare totală", "valoare totala"),
    },
    "bg": {
        "ordinal": ("№", "поз", "поз."),
        "description": ("описание", "вид работа", "видове работи"),
        "unit": ("мярка", "ед. мярка", "единица мярка", "мерна единица"),
        "quantity": ("количество",),
        "unit_rate": ("ед. цена", "единична цена"),
        "total": ("стойност", "обща стойност", "общо"),
    },
    "el": {
        "ordinal": ("α/α", "αα"),
        "description": ("περιγραφή", "περιγραφη", "είδος εργασίας", "ειδος εργασιας", "ονομασία", "ονομασια"),
        "unit": ("μονάδα", "μοναδα", "μονάδα μέτρησης", "μοναδα μετρησης", "μ.μ."),
        "quantity": ("ποσότητα", "ποσοτητα"),
        "unit_rate": ("τιμή μονάδας", "τιμη μοναδας", "τιμή", "τιμη"),
        "total": ("σύνολο", "συνολο", "δαπάνη", "δαπανη"),
    },
    "sv": {
        "ordinal": ("post", "postnr"),
        "description": ("beskrivning", "benämning", "benamning"),
        "unit": ("enhet", "enh", "enh."),
        "quantity": ("mängd", "mangd", "antal"),
        "unit_rate": ("à-pris", "a-pris", "enhetspris"),
        "total": ("summa", "belopp", "totalt"),
    },
    "no": {
        "ordinal": ("post", "postnr", "postnr."),
        "description": ("beskrivelse", "betegnelse"),
        "unit": ("enhet", "enh", "enh."),
        "quantity": ("mengde", "antall"),
        "unit_rate": ("enhetspris", "pris"),
        "total": ("sum", "beløp", "belop", "totalt"),
    },
    "da": {
        "ordinal": ("post", "postnr", "løbenr", "lobenr"),
        "description": ("beskrivelse", "betegnelse", "ydelse"),
        "unit": ("enhed", "enh", "enh."),
        "quantity": ("mængde", "maengde", "antal"),
        "unit_rate": ("enhedspris", "pris"),
        "total": ("sum", "beløb", "belob", "i alt"),
    },
    "fi": {
        "ordinal": ("nro", "nro.", "n:o"),
        "description": ("kuvaus", "selite", "nimike", "työn kuvaus", "tyon kuvaus"),
        "unit": ("yksikkö", "yksikko", "yks", "yks."),
        "quantity": ("määrä", "maara"),
        "unit_rate": ("yksikköhinta", "yksikkohinta", "yks.hinta", "hinta"),
        "total": ("yhteensä", "yhteensa", "summa", "kokonaishinta"),
    },
    "uk": {
        "ordinal": ("№ з/п", "поз", "поз."),
        "description": ("найменування", "опис", "найменування робіт"),
        "unit": ("од", "од.", "од. вим.", "одиниця виміру", "одиниця"),
        "quantity": ("кількість", "к-ть"),
        "unit_rate": ("ціна", "ціна за одиницю", "вартість одиниці"),
        "total": ("сума", "вартість", "загальна вартість"),
    },
    "ja": {
        "ordinal": ("番号", "項番"),
        "description": ("名称", "工種", "摘要", "工事内容", "説明", "内容"),
        "unit": ("単位",),
        "quantity": ("数量",),
        "unit_rate": ("単価",),
        "total": ("金額", "合計"),
    },
    "ko": {
        "ordinal": ("번호", "순번", "연번"),
        "description": ("품명", "공종", "내역", "설명", "공사명"),
        "unit": ("단위",),
        "quantity": ("수량",),
        "unit_rate": ("단가",),
        "total": ("금액", "합계"),
    },
    "zh": {
        "ordinal": ("序号", "编号"),
        "description": ("名称", "项目名称", "工作内容", "描述", "项目描述"),
        "unit": ("单位", "计量单位"),
        "quantity": ("数量", "工程量"),
        "unit_rate": ("单价", "综合单价"),
        "total": ("合价", "金额", "合计"),
    },
    "ar": {
        "ordinal": ("رقم", "الرقم", "التسلسل", "رقم البند"),
        "description": ("الوصف", "وصف", "البيان", "وصف الأعمال", "البند"),
        "unit": ("الوحدة", "وحدة", "وحدة القياس"),
        "quantity": ("الكمية", "كمية"),
        "unit_rate": ("سعر الوحدة", "السعر", "سعر"),
        "total": ("الإجمالي", "الاجمالي", "المجموع"),
    },
    "he": {
        "ordinal": ("מס'", "מספר", "סעיף"),
        "description": ("תיאור", "תאור", "פירוט"),
        "unit": ("יחידה", "יח'", "יחידת מידה"),
        "quantity": ("כמות",),
        "unit_rate": ("מחיר יחידה", "מחיר"),
        "total": ('סה"כ', "סהכ", "סך הכל", "סכום"),
    },
    "id": {
        "ordinal": ("nomor", "urut", "no. urut"),
        "description": ("uraian", "uraian pekerjaan", "deskripsi", "jenis pekerjaan"),
        "unit": ("satuan", "sat", "sat."),
        # ``jumlah`` is deliberately absent. Indonesian bills head both the
        # quantity column and the money column with it, so accepting it makes
        # one of the two read as the other; ``volume`` and ``jumlah harga``
        # are the spellings that say which is meant.
        "quantity": ("volume", "vol.", "kuantitas", "banyaknya"),
        "unit_rate": ("harga satuan", "harga"),
        "total": ("jumlah harga", "total harga", "jumlah biaya"),
    },
    "vi": {
        "ordinal": ("stt", "số tt", "so tt"),
        "description": (
            "nội dung công việc",
            "noi dung cong viec",
            "tên công việc",
            "ten cong viec",
            "mô tả",
            "mo ta",
            "diễn giải",
            "dien giai",
        ),
        "unit": ("đơn vị", "don vi", "đơn vị tính", "don vi tinh", "đvt", "dvt"),
        "quantity": ("khối lượng", "khoi luong", "số lượng", "so luong"),
        "unit_rate": ("đơn giá", "don gia"),
        "total": ("thành tiền", "thanh tien", "tổng cộng", "tong cong"),
    },
    # Croatian troškovnik. "Jed. mj." is the unit (jedinica mjere), and the
    # money columns usually carry the currency in brackets, "Jed. cijena
    # (EUR)", which the matcher strips before it looks the header up.
    "hr": {
        "ordinal": ("r.br.", "r. br.", "rbr", "rb", "red. br.", "redni broj", "br.", "br. stavke"),
        "description": ("opis", "opis stavke", "opis radova", "opis rada", "naziv", "naziv stavke"),
        "unit": ("jed. mj.", "jed.mj.", "j. mj.", "jm", "jedinica mjere", "mjerna jedinica"),
        "quantity": ("količina", "kolicina", "kol."),
        "unit_rate": ("jed. cijena", "jedinična cijena", "jedinicna cijena", "cijena"),
        "total": ("ukupno", "iznos", "ukupna cijena", "ukupni iznos"),
    },
    # Serbian writes both scripts, so each Latin spelling has its Cyrillic twin.
    "sr": {
        "ordinal": ("r.br.", "rb", "redni broj", "р.бр.", "рб", "редни број"),
        "description": ("opis", "opis pozicije", "naziv", "опис", "опис позиције", "назив"),
        "unit": ("jed. mere", "jedinica mere", "j.m.", "јед. мере", "јединица мере", "ј.м."),
        "quantity": ("količina", "kolicina", "количина"),
        "unit_rate": ("jed. cena", "jedinična cena", "jedinicna cena", "cena", "јед. цена", "јединична цена"),
        "total": ("ukupno", "iznos", "укупно", "износ"),
    },
    "sl": {
        "ordinal": ("zap. št.", "zap. st.", "zap.št.", "poz."),
        "description": ("opis", "opis postavke", "naziv"),
        "unit": ("enota", "enota mere", "em", "e.m."),
        "quantity": ("količina", "kolicina"),
        "unit_rate": ("cena na enoto", "cena/enoto", "enotna cena", "cena enote", "cena"),
        "total": ("skupaj", "vrednost", "znesek"),
    },
    "et": {
        "ordinal": ("jrk", "jrk nr", "jrk. nr"),
        "description": ("kirjeldus", "nimetus", "töö kirjeldus"),
        "unit": ("ühik", "uhik", "mõõtühik", "mootuhik"),
        "quantity": ("kogus", "maht"),
        "unit_rate": ("ühikuhind", "uhikuhind", "ühiku hind", "hind"),
        "total": ("kokku", "maksumus"),
    },
    "th": {
        "ordinal": ("ลำดับ", "ลำดับที่"),
        "description": ("รายการ", "รายละเอียด"),
        "unit": ("หน่วย",),
        "quantity": ("จำนวน", "ปริมาณ"),
        "unit_rate": ("ราคาต่อหน่วย", "ราคา/หน่วย"),
        "total": ("รวมเงิน", "จำนวนเงิน"),
    },
    "hi": {
        "ordinal": ("क्रम सं.", "क्रमांक", "क्र.सं."),
        "description": ("विवरण", "कार्य का विवरण"),
        "unit": ("इकाई",),
        "quantity": ("मात्रा",),
        "unit_rate": ("दर",),
        "total": ("राशि", "कुल राशि"),
    },
    "bn": {
        "ordinal": ("ক্রমিক নং", "ক্রম"),
        "description": ("বিবরণ", "কাজের বিবরণ"),
        "unit": ("একক",),
        "quantity": ("পরিমাণ",),
        "unit_rate": ("দর", "একক দর"),
        "total": ("মোট", "মোট টাকা"),
    },
    # Urdu "شرح" means rate but Persian "شرح" means description, so Urdu
    # carries only the loanword for rate and the shared spelling is Persian's.
    "ur": {
        "ordinal": ("نمبر شمار",),
        "description": ("تفصیل",),
        "unit": ("اکائی", "یونٹ"),
        "quantity": ("مقدار",),
        "unit_rate": ("ریٹ", "فی یونٹ ریٹ"),
        # Bare "رقم" is Arabic for the item number, so Urdu keeps only the
        # spelling that says "total amount".
        "total": ("کل رقم",),
    },
    "fa": {
        "ordinal": ("ردیف",),
        "description": ("شرح", "شرح عملیات", "شرح کار"),
        "unit": ("واحد",),
        # Persian and Urdu share the spelling and the meaning here.
        "quantity": ("مقدار",),
        "unit_rate": ("بهای واحد", "فی"),
        "total": ("بهای کل", "مبلغ"),
    },
    "fil": {
        "ordinal": ("blg.",),
        "description": ("paglalarawan",),
        "unit": ("yunit",),
        "quantity": ("dami",),
        "unit_rate": ("presyo bawat yunit", "halaga bawat yunit"),
        "total": ("kabuuan", "kabuuang halaga"),
    },
    "kk": {
        "ordinal": ("р/с", "№ р/с"),
        "description": ("атауы", "жұмыстардың атауы"),
        "unit": ("өлшем бірлігі", "өлш. бір."),
        "quantity": ("саны", "көлемі"),
        "unit_rate": ("бірлік бағасы", "бағасы"),
        "total": ("сомасы", "құны"),
    },
    "ky": {
        "description": ("аталышы", "иштердин аталышы"),
        "unit": ("өлчөө бирдиги",),
        # Kazakh and Kyrgyz share the spelling and the meaning here.
        "quantity": ("саны",),
        "unit_rate": ("баасы", "бирдик баасы"),
        "total": ("суммасы",),
    },
    "uz": {
        "ordinal": ("t/r",),
        "description": ("nomi", "ishlar nomi"),
        "unit": ("o'lchov birligi", "o‘lchov birligi", "olchov birligi"),
        "quantity": ("miqdori", "soni"),
        "unit_rate": ("narxi", "birlik narxi"),
        "total": ("qiymati", "jami"),
    },
    "mn": {
        "ordinal": ("д/д",),
        "description": ("ажлын нэр", "нэр"),
        "unit": ("хэмжих нэгж", "нэгж"),
        "quantity": ("тоо хэмжээ",),
        "unit_rate": ("нэгж үнэ",),
        "total": ("нийт үнэ", "дүн"),
    },
}


# The four columns a bill row cannot be read without. A language that names
# fewer than these cannot carry a bill on its own, however many other headers
# it declares, so it has no business being listed as supported.
_MANDATORY_COLUMNS: tuple[str, ...] = ("description", "unit", "quantity", "unit_rate")

# Canonical column order for the flattened map. ``position_id`` is prepended
# by the builder and comes first: an exported "Position ID" header maps there,
# never to ``ordinal``. A blank cell -> new row; a value belonging to the
# target BOQ -> update in place (GitHub #360).
_CANONICAL_COLUMNS: tuple[str, ...] = (
    "ordinal",
    "description",
    "unit",
    "quantity",
    "unit_rate",
    "total",
    "classification",
)


def _languages_missing_mandatory_columns(
    table: dict[str, dict[str, tuple[str, ...]]],
) -> dict[str, tuple[str, ...]]:
    """Report which mandatory columns each language fails to name.

    Args:
        table: A language-tagged header table shaped like
            :data:`_HEADERS_BY_LANGUAGE`.

    Returns:
        Language code -> the mandatory columns it leaves empty or omits.
        Empty when every language is complete.
    """
    holes: dict[str, tuple[str, ...]] = {}
    for language, headers in table.items():
        missing = tuple(column for column in _MANDATORY_COLUMNS if not headers.get(column))
        if missing:
            holes[language] = missing
    return holes


def _build_column_aliases(
    table: dict[str, dict[str, tuple[str, ...]]],
) -> dict[str, frozenset[str]]:
    """Flatten the language-tagged table into the canonical alias map.

    Args:
        table: A language-tagged header table shaped like
            :data:`_HEADERS_BY_LANGUAGE`.

    Returns:
        Canonical column -> every accepted header string for it, across all
        languages, with ``position_id`` seeded from
        :data:`~app.modules.boq.roundtrip.ID_COLUMN_ALIASES`.
    """
    merged: dict[str, set[str]] = {}
    for headers in table.values():
        for canonical, words in headers.items():
            merged.setdefault(canonical, set()).update(words)
    aliases: dict[str, frozenset[str]] = {"position_id": ID_COLUMN_ALIASES}
    for canonical in _CANONICAL_COLUMNS:
        aliases[canonical] = frozenset(merged.pop(canonical, set()))
    for canonical in sorted(merged):
        aliases[canonical] = frozenset(merged[canonical])
    return aliases


_COLUMN_ALIASES: dict[str, frozenset[str]] = _build_column_aliases(_HEADERS_BY_LANGUAGE)

SUPPORTED_HEADER_LANGUAGES: frozenset[str] = frozenset(_HEADERS_BY_LANGUAGE)
"""Languages whose spreadsheet header row this importer reads natively.

Computed from :data:`_HEADERS_BY_LANGUAGE`, never written out by hand, so a
caller deciding whether a national profile can claim native spreadsheet
import reads what the table actually holds rather than what a second list
once said it held. Membership means the language names at least
:data:`_MANDATORY_COLUMNS`.

Note that this covers the header row only. A market whose bills are not
tables with a header row at all (the Hungarian workbooks, whose item code is
composed down a heading tree across nine columns) needs a profile of its own
regardless of what this set says.
"""


# ── Label normalisation ─────────────────────────────────────────────────────
#
# A header is written a dozen ways for the same column: "Jed. mj.", "JED MJ",
# "Jed.mj.", "Jed. cijena (EUR)", "KOLIČINA", "Kolicina". The table above
# holds one or two spellings per column, so the matcher reduces both sides to
# a key that ignores case, diacritics, punctuation, spacing and a bracketed or
# trailing currency before it compares them.

# Letters NFKD leaves alone because Unicode does not treat them as a base
# letter plus an accent. Without these, "Količina" and "Kolicina" meet but
# "Đ" (Croatian), "Ł" (Polish), "Ø"/"Æ" (Danish, Norwegian) and "ı"
# (Turkish) never reach their unaccented twins.
_TRANSLITERATE: dict[int, str] = str.maketrans(
    {"đ": "d", "ł": "l", "ø": "o", "æ": "ae", "œ": "oe", "ß": "ss", "ı": "i", "þ": "th", "ð": "d"}
)

# Combining marks are dropped only above this code point's scripts (Latin,
# Greek, Cyrillic, Armenian). Thai tone marks, Devanagari and Bengali vowel
# signs and Arabic hamza are combining marks too, but there they change the
# word, so dropping them would make two different headers one.
_STRIP_MARKS_BELOW = 0x0590

_BRACKETED = re.compile(r"\([^)]*\)|\[[^\]]*\]|\{[^}]*\}")


def _currency_codes() -> frozenset[str]:
    """Lowercased ISO 4217 codes the platform knows, for stripping from headers."""
    from app.core.currency_registry import CURRENCIES

    return frozenset(code.lower() for code in CURRENCIES)


_CURRENCY_CODES: frozenset[str] = _currency_codes()


def normalise_label(text: str) -> str:
    """Reduce a header or row label to its comparison form.

    Lowercases, drops bracketed parts ("Jed. cijena (EUR)"), strips accents
    from Latin, Greek and Cyrillic letters, turns every run of punctuation
    and spacing into one space and drops a trailing currency code or sign
    ("Iznos EUR", "Ukupno €"). The words stay separated by single spaces.

    Args:
        text: The raw cell text.

    Returns:
        The normalised label, possibly empty.
    """
    lowered = _BRACKETED.sub(" ", str(text).lower()).translate(_TRANSLITERATE)
    kept: list[str] = []
    base = 0
    for char in unicodedata.normalize("NFKD", lowered):
        if unicodedata.combining(char):
            if base < _STRIP_MARKS_BELOW:
                continue
            kept.append(char)
            continue
        base = ord(char)
        kept.append(char if char.isalnum() else " ")
    words = unicodedata.normalize("NFC", "".join(kept)).split()
    if len(words) > 1 and words[-1] in _CURRENCY_CODES:
        words.pop()
    return " ".join(words)


def _label_key(text: str) -> str:
    """The normalised label with the spaces removed too ("r br" == "rbr")."""
    return normalise_label(text).replace(" ", "")


def _build_normalised_index(aliases: dict[str, frozenset[str]]) -> dict[str, str]:
    """Key every alias by :func:`_label_key`, the first canonical column winning.

    The collision test in ``tests/unit/test_boq_spreadsheet_header_languages``
    holds that no two canonical columns share a key, so "first wins" never
    decides anything in practice; it only keeps ``position_id`` ahead of
    ``ordinal`` if that test is ever broken.
    """
    index: dict[str, str] = {}
    for canonical, words in aliases.items():
        for word in words:
            key = _label_key(word)
            if key:
                index.setdefault(key, canonical)
    return index


_NORMALISED_COLUMN_INDEX: dict[str, str] = _build_normalised_index(_COLUMN_ALIASES)


def _match_column(header: str) -> str | None:
    """Match a header string to a canonical column name using the alias map.

    The exact lowercased spelling is tried first, so a symbol-only header such
    as ``#`` (which normalises to nothing) still matches, then the normalised
    key, which is what reads "Jed. mj." and "KOLICINA (m3)".
    """
    lowered = header.strip().lower()
    for canonical, aliases in _COLUMN_ALIASES.items():
        if lowered in aliases:
            return canonical
    key = _label_key(header)
    return _NORMALISED_COLUMN_INDEX.get(key) if key else None


def _detect_file_format(content_head: bytes) -> Literal["xlsx", "csv", "parquet", "unknown"]:
    """Identify an upload by its magic bytes (BUG-UPLOAD01 from the legacy code).

    A ``.exe`` renamed to ``.xlsx`` would otherwise be handed to
    ``openpyxl`` - best case a parse exception, worst case the bytes
    land in our buffers + logs before we error.
    """
    if not content_head:
        return "unknown"
    sig = detect_signature(content_head)
    if sig == "zip":  # XLSX = OOXML zip
        return "xlsx"
    if content_head[:4] == b"PAR1":
        return "parquet"
    if b"\x00" in content_head:
        return "unknown"
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            decoded = content_head.decode(encoding)
        except UnicodeDecodeError:
            continue
        if any(sep in decoded for sep in (",", ";", "\t", "|", "\n")):
            return "csv"
    return "unknown"


# ── Classification heuristics (Epics I9 + I10) ─────────────────────────────


# NRM codes: ``N.N.N`` or ``N.N`` (e.g. ``2.6.1``, ``2.6``). NRM 1 / NRM 2
# tops out at four levels but two/three are the common case in tender
# documents.
_NRM_CODE_RE = re.compile(r"^(\d{1,2}\.){1,3}\d{1,2}$")

# NRM element header text e.g. ``"Element 2 - Substructure"``,
# ``"Group element 2.6 - External walls"``.
_NRM_HEADER_RE = re.compile(r"^(group\s+)?element\s+(\d{1,2}(?:\.\d{1,2})*)\b", re.IGNORECASE)

# MasterFormat: ``XX XX XX`` or ``XX.XX.XX`` or ``XX-XX-XX`` (2-2-2 digits).
# Sub-codes ``XX XX XX.XX`` are allowed.
_MASTERFORMAT_CODE_RE = re.compile(r"^(\d{2})[\s.\-](\d{2})[\s.\-](\d{2})(?:\.(\d{2}))?$")

# MasterFormat division header text e.g. ``"Division 03 - Concrete work"``,
# ``"03 30 00 Cast-in-Place Concrete"``.
_MASTERFORMAT_HEADER_RE = re.compile(r"^division\s+(\d{2})\b", re.IGNORECASE)


def _infer_classification(
    code_text: str,
    description: str,
) -> dict[str, Any]:
    """Heuristic classification from a raw code cell + description.

    Tries NRM and MasterFormat patterns; anything else falls through to
    ``{"code": code_text}`` (the historic generic behaviour).
    """
    code = code_text.strip()
    desc = (description or "").strip()
    classification: dict[str, Any] = {}

    # NRM element header in the description ("Element 2 - Substructure").
    m = _NRM_HEADER_RE.match(desc)
    if m:
        classification["nrm"] = m.group(2)
    # NRM code pattern in the code cell ("2.6.1").
    if code and _NRM_CODE_RE.match(code):
        classification["nrm"] = code

    # MasterFormat 6-digit code in the code cell ("03 30 00").
    m = _MASTERFORMAT_CODE_RE.match(code) if code else None
    if m:
        # Normalise to spaced form "XX XX XX[.XX]".
        parts = [m.group(1), m.group(2), m.group(3)]
        mf = " ".join(parts)
        if m.group(4):
            mf = f"{mf}.{m.group(4)}"
        classification["masterformat"] = mf

    # MasterFormat division header in the description ("Division 03 -").
    m = _MASTERFORMAT_HEADER_RE.match(desc)
    if m:
        # Pad to canonical 6-digit form for downstream rules.
        div = m.group(1)
        # If the description contains a fuller code further along, keep it,
        # else stub the level-2 + level-3 to ``00``.
        if "masterformat" not in classification:
            classification["masterformat"] = f"{div} 00 00"

    # Fallback: stash the raw code so the editor can show it. Skip if we
    # already mapped it to a structured field above.
    if code and "nrm" not in classification and "masterformat" not in classification:
        classification["code"] = code

    return classification


# ── Row parsing helpers ─────────────────────────────────────────────────────


def _parse_rows_from_csv(content_bytes: bytes) -> list[dict[str, Any]]:
    """Decode + parse a CSV into a list of canonical-key dicts."""
    text, _ = decode_text_bytes(content_bytes)
    # Detect delimiter from the first 4 KB.
    sniffer = csv.Sniffer()
    try:
        dialect = sniffer.sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel  # type: ignore[assignment]

    reader = csv.reader(io.StringIO(text), dialect)
    raw_headers = next(reader, None)
    if not raw_headers:
        raise ImporterParseError("CSV file is empty or has no header row")

    column_map: dict[int, str] = {}
    raw_header_strings: list[str] = []
    for idx, hdr in enumerate(raw_headers):
        raw_header_strings.append(str(hdr or ""))
        canonical = _match_column(str(hdr or ""))
        if canonical:
            column_map[idx] = canonical

    rows: list[dict[str, Any]] = []
    for raw_row in reader:
        row: dict[str, Any] = {}
        for idx, val in enumerate(raw_row):
            canonical = column_map.get(idx)
            if canonical:
                row[canonical] = val.strip() if isinstance(val, str) else val
        if row:
            rows.append(row)
    return rows


def _parse_rows_from_excel(
    content_bytes: bytes,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read an .xlsx file's first worksheet into canonical-key dicts.

    Returns ``(rows, import_metadata)``; metadata preserves the raw
    column ordering so a later export can round-trip back to the
    user's original spreadsheet layout, and ``row_numbers`` holds the
    sheet row each returned row came from, so a message about it names the
    row the user sees under a letterhead and past blank lines.
    """
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(content_bytes), read_only=True, data_only=True)
    ws = wb.active
    if ws is None:
        raise ImporterParseError("Excel file has no worksheets")

    sheet_names = wb.sheetnames

    raw_headers, header_number, rows_iter = find_header_row(ws.iter_rows(values_only=True), _match_column)
    if not raw_headers:
        raise ImporterParseError("Excel file is empty or has no header row")

    original_columns = [str(h) if h is not None else "" for h in raw_headers]
    column_map: dict[int, str] = {}
    for idx, hdr in enumerate(raw_headers):
        if hdr is not None:
            canonical = _match_column(str(hdr))
            if canonical:
                column_map[idx] = canonical

    rows: list[dict[str, Any]] = []
    row_numbers: list[int] = []
    for sheet_row, raw_row in enumerate(rows_iter, start=header_number + 1):
        row: dict[str, Any] = {}
        for idx, val in enumerate(raw_row):
            canonical = column_map.get(idx)
            if canonical and val is not None:
                row[canonical] = val
        if row:
            rows.append(row)
            row_numbers.append(sheet_row)
    wb.close()

    import_metadata = {
        "original_columns": original_columns,
        "column_mapping": {str(k): v for k, v in column_map.items()},
        "sheet_names": sheet_names,
        "total_rows": len(rows),
        "row_numbers": row_numbers,
    }
    return rows, import_metadata


_TOTAL_ROW_DESCRIPTIONS = {
    "grand total",
    "total",
    "summe",
    "gesamt",
    "gesamtsumme",
    "subtotal",
    "zwischensumme",
    # Export artifacts of our own workbook - never re-imported as positions
    # on a round-trip (GitHub #360).
    "direct cost",
    "cost summary",
    "net total",
    "gross total",
}


# ── Total, tax and recap rows, tagged by language ──────────────────────────
#
# A national bill closes every section with a total line ("UKUPNO I. ...",
# "Summe Titel 01"), ends with a tax line and a grand total ("PDV 25 %",
# "SVEUKUPNO") and often repeats the section totals on a recap page
# ("REKAPITULACIJA"). None of them is work, and a total line has no unit,
# quantity or rate, so without this table each one imported as an empty
# section, and the recap page repeated the section ordinals.
#
# The phrases are matched on :func:`normalise_label`, so they are written
# plainly here and accents, punctuation and a trailing currency do not matter.
# ``recap`` phrases must be the whole label; the others may also start a
# longer one ("ukupno" reads "UKUPNO II. ZEMLJANI RADOVI") and then only count
# on a line that carries an amount, so a section heading that happens to start
# with "Total" stays a section.
_SUMMARY_KINDS: tuple[str, ...] = ("subtotal", "tax", "grand_total", "recap")

_SUMMARY_WORDS_BY_LANGUAGE: dict[str, dict[str, tuple[str, ...]]] = {
    "en": {
        "subtotal": (
            "total",
            "subtotal",
            "sub total",
            "page total",
            "carried forward",
            "brought forward",
            "carried to collection",
            "total carried to collection",
            "total carried to summary",
            "net total",
            "total excluding vat",
            "total excl vat",
        ),
        "tax": ("vat", "tax", "sales tax", "gst", "hst", "pst", "qst"),
        "grand_total": ("grand total", "total including vat", "total incl vat", "gross total", "contract sum"),
        "recap": ("summary", "collection", "recapitulation", "general summary", "cost summary"),
    },
    "de": {
        "subtotal": ("summe", "zwischensumme", "gesamt", "übertrag", "nettosumme", "summe netto"),
        "tax": ("mwst", "ust", "umsatzsteuer", "mehrwertsteuer"),
        "grand_total": ("gesamtsumme", "gesamtbetrag", "bruttosumme", "summe brutto", "angebotssumme", "endsumme"),
        "recap": ("zusammenstellung", "zusammenfassung"),
    },
    "hr": {
        "subtotal": ("ukupno", "svega", "ukupno bez pdv"),
        "tax": ("pdv",),
        "grand_total": ("sveukupno", "sveukupno s pdv", "ukupno s pdv"),
        "recap": ("rekapitulacija", "rekapitulacija radova", "zbirna rekapitulacija"),
    },
    "sr": {
        "subtotal": ("ukupno", "svega", "укупно", "свега"),
        "tax": ("pdv", "пдв"),
        "grand_total": ("sveukupno", "свеукупно"),
        "recap": ("rekapitulacija", "рекапитулација"),
    },
    "sl": {
        "subtotal": ("skupaj", "vmesni seštevek"),
        "tax": ("ddv",),
        "grand_total": ("skupaj z ddv", "skupna vrednost"),
        "recap": ("rekapitulacija",),
    },
    "pl": {
        "subtotal": ("razem", "suma", "razem netto", "wartość netto"),
        "grand_total": ("ogółem", "razem brutto", "wartość brutto"),
        "recap": ("zestawienie", "podsumowanie"),
    },
    "cs": {
        "subtotal": ("celkem", "mezisoučet", "součet"),
        "tax": ("dph",),
        "grand_total": ("celkem s dph", "celková cena"),
        "recap": ("rekapitulace", "rekapitulace stavby"),
    },
    "sk": {
        "subtotal": ("spolu", "celkom", "medzisúčet"),
        "grand_total": ("spolu s dph", "celkom s dph"),
        "recap": ("rekapitulácia",),
    },
    "hu": {
        "subtotal": ("összesen", "részösszeg"),
        "tax": ("áfa",),
        "grand_total": ("mindösszesen", "végösszeg"),
        "recap": ("összesítő", "összesítés"),
    },
    "ro": {
        "subtotal": ("total capitol", "subtotal"),
        "tax": ("tva",),
        "grand_total": ("total general",),
        "recap": ("centralizator", "recapitulatie"),
    },
    "bg": {
        "subtotal": ("общо", "междинна сума"),
        "tax": ("ддс",),
        "grand_total": ("общо с ддс", "всичко"),
        "recap": ("рекапитулация", "обобщение"),
    },
    "el": {
        "subtotal": ("σύνολο", "μερικό σύνολο", "άθροισμα"),
        "tax": ("φπα",),
        "grand_total": ("γενικό σύνολο",),
        "recap": ("ανακεφαλαίωση",),
    },
    "ru": {
        "subtotal": ("итого", "итого по разделу", "всего по разделу"),
        "tax": ("ндс",),
        "grand_total": ("всего", "всего по смете", "итого по смете", "всего с ндс"),
    },
    "uk": {
        "subtotal": ("разом", "всього по розділу", "підсумок"),
        "tax": ("пдв",),
        "grand_total": ("всього", "разом з пдв"),
    },
    "it": {
        "subtotal": ("totale", "subtotale", "totale parziale"),
        "tax": ("iva",),
        "grand_total": ("totale generale", "importo complessivo"),
        "recap": ("riepilogo", "riassunto"),
    },
    "es": {
        "subtotal": ("suma y sigue",),
        "tax": ("igic",),
        "grand_total": ("total general", "total presupuesto"),
        "recap": ("resumen", "resumen de presupuesto"),
    },
    "pt": {
        "subtotal": ("total parcial",),
        "grand_total": ("total geral",),
        "recap": ("resumo",),
    },
    "fr": {
        "subtotal": ("sous total", "total ht"),
        "tax": ("tva",),
        "grand_total": ("total ttc", "montant ttc", "total général"),
        "recap": ("récapitulatif", "récapitulation"),
    },
    "nl": {
        "subtotal": ("totaal", "subtotaal", "totaal excl btw"),
        "tax": ("btw",),
        "grand_total": ("totaal incl btw", "eindtotaal"),
        "recap": ("samenvatting", "recapitulatie"),
    },
    "sv": {
        "subtotal": ("summa", "delsumma", "totalt"),
        "tax": ("moms",),
        "grand_total": ("summa inkl moms", "totalsumma"),
        "recap": ("sammanställning",),
    },
    "no": {
        "subtotal": ("sum", "delsum"),
        "tax": ("mva",),
        "grand_total": ("sum inkl mva", "totalsum"),
        "recap": ("sammendrag", "sammenstilling"),
    },
    "da": {
        "subtotal": ("i alt",),
        "grand_total": ("i alt inkl moms",),
        "recap": ("sammenfatning",),
    },
    "fi": {
        "subtotal": ("yhteensä", "välisumma"),
        "tax": ("alv",),
        "grand_total": ("kokonaissumma", "yhteensä sis alv"),
        "recap": ("yhteenveto",),
    },
    "et": {
        "subtotal": ("kokku", "vahesumma"),
        "tax": ("käibemaks",),
        "grand_total": ("kokku koos käibemaksuga",),
        "recap": ("koond", "kokkuvõte"),
    },
    "tr": {
        "subtotal": ("toplam", "ara toplam"),
        "tax": ("kdv",),
        "grand_total": ("genel toplam",),
        "recap": ("icmal", "özet"),
    },
    "ja": {"subtotal": ("小計", "合計"), "tax": ("消費税",), "grand_total": ("総合計", "総計"), "recap": ("集計",)},
    "zh": {"subtotal": ("小计", "合计"), "tax": ("税金", "增值税"), "grand_total": ("总计",), "recap": ("汇总",)},
    "ko": {"subtotal": ("소계", "합계"), "tax": ("부가세", "부가가치세"), "grand_total": ("총계",), "recap": ("집계",)},
    "ar": {
        "subtotal": ("المجموع", "المجموع الفرعي"),
        "tax": ("ضريبة القيمة المضافة",),
        "grand_total": ("الإجمالي", "المجموع الكلي"),
        "recap": ("ملخص",),
    },
    "he": {
        "subtotal": ('סה"כ', "סיכום ביניים"),
        "tax": ('מע"מ',),
        "grand_total": ('סה"כ כולל מע"מ',),
        "recap": ("ריכוז",),
    },
    "id": {
        "subtotal": ("jumlah", "sub total"),
        "tax": ("ppn",),
        "grand_total": ("jumlah total", "total keseluruhan"),
        "recap": ("rekapitulasi",),
    },
    "vi": {"subtotal": ("cộng",), "tax": ("thuế gtgt",), "grand_total": ("tổng cộng",), "recap": ("tổng hợp",)},
    "th": {"subtotal": ("รวม",), "tax": ("ภาษีมูลค่าเพิ่ม",), "grand_total": ("รวมทั้งสิ้น",)},
    "hi": {"subtotal": ("कुल", "योग"), "tax": ("जीएसटी",), "grand_total": ("कुल योग",)},
    "fa": {"subtotal": ("جمع",), "tax": ("مالیات بر ارزش افزوده",), "grand_total": ("جمع کل",)},
}


def _build_summary_index(table: dict[str, dict[str, tuple[str, ...]]]) -> dict[str, str]:
    """Normalised phrase -> summary kind, across every language."""
    index: dict[str, str] = {}
    for words_by_kind in table.values():
        for kind, phrases in words_by_kind.items():
            for phrase in phrases:
                key = normalise_label(phrase)
                if key:
                    index.setdefault(key, kind)
    return index


_SUMMARY_INDEX: dict[str, str] = _build_summary_index(_SUMMARY_WORDS_BY_LANGUAGE)


def summary_label_kind(label: str) -> tuple[str, bool] | None:
    """Say whether a row label reads as a total, tax, grand-total or recap line.

    Args:
        label: The row's description cell.

    Returns:
        ``(kind, whole)`` where ``whole`` is True when the phrase is the entire
        label and False when it only starts it; ``None`` when no phrase fits.
        A ``recap`` phrase counts only as the whole label.
    """
    normalised = normalise_label(label)
    if not normalised:
        return None
    kind = _SUMMARY_INDEX.get(normalised)
    if kind is not None:
        return kind, True
    words = normalised.split()
    for length in range(len(words) - 1, 0, -1):
        kind = _SUMMARY_INDEX.get(" ".join(words[:length]))
        if kind is not None and kind != "recap":
            return kind, False
    return None


def _is_blank_cell(value: Any) -> bool:
    """A cell that carries nothing: empty, whitespace or a zero."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip() or safe_float(value, default=1.0) == 0.0
    return value in (0, 0.0)


def partition_summary_rows(
    rows: list[dict[str, Any]],
    *,
    first_row_number: int = 2,
    row_numbers: list[int] | None = None,
) -> tuple[list[tuple[int, dict[str, Any]]], list[dict[str, Any]]]:
    """Separate a bill's total, tax and recap lines from its sections and work.

    Only a row with no unit, no quantity and no rate can be one of these; a
    priced row is work whatever its label says. Such a row is a summary line
    when its label is a summary phrase in any language of
    :data:`_SUMMARY_WORDS_BY_LANGUAGE` (a phrase that only starts the label
    also needs an amount in the total column), when it carries an amount
    under a recap heading, or when it carries an amount and repeats the
    ordinal of a section already read, which is what a recap page without a
    heading looks like. Every other unpriced row stays a section heading.

    Args:
        rows: Canonical row dicts as the sheet parsers return them.
        first_row_number: The sheet row number of ``rows[0]``, when
            ``row_numbers`` is not given.
        row_numbers: The sheet row of each row, as the Excel reader returns
            them in its metadata.

    Returns:
        ``(kept, summary)``: the rows to import, each with its row number, and
        one report per summary line with its row, ordinal, label, kind and
        amount.
    """
    kept: list[tuple[int, dict[str, Any]]] = []
    summary: list[dict[str, Any]] = []
    section_ordinals: set[str] = set()
    in_recap = False
    numbers = row_numbers if row_numbers is not None and len(row_numbers) == len(rows) else None
    for index, row in enumerate(rows):
        number = numbers[index] if numbers is not None else first_row_number + index
        description = str(row.get("description", "") or "").strip()
        unpriced = (
            not str(row.get("unit", "") or "").strip()
            and _is_blank_cell(row.get("quantity"))
            and _is_blank_cell(row.get("unit_rate"))
        )
        if not description or not unpriced:
            if not unpriced:
                in_recap = False
            kept.append((number, row))
            continue

        amount = safe_float(row.get("total"), default=0.0)
        ordinal = str(row.get("ordinal", "") or "").strip()
        ordinal_key = _label_key(ordinal)
        kind: str | None = None
        matched = summary_label_kind(description)
        if matched is not None and (matched[1] or amount):
            kind = matched[0]
        elif amount and (in_recap or (ordinal_key and ordinal_key in section_ordinals)):
            kind = "recap"

        if kind is None:
            in_recap = False
            if ordinal_key:
                section_ordinals.add(ordinal_key)
            kept.append((number, row))
            continue
        if kind == "recap":
            in_recap = True
        summary.append(
            {
                "row": number,
                "ordinal": ordinal,
                "description": description[:200],
                "kind": kind,
                "amount": amount,
            }
        )
    return kept, summary


_SUMMARY_KIND_WORDS: dict[str, str] = {
    "subtotal": "subtotal",
    "tax": "tax",
    "grand_total": "grand total",
    "recap": "recap",
}


def summary_row_warning(report: dict[str, Any]) -> dict[str, Any]:
    """The import warning that tells the user a summary line was left out."""
    return {
        "row": report["row"],
        "ordinal": report["ordinal"],
        "severity": "info",
        "code": "summary_row_skipped",
        "kind": report["kind"],
        "amount": report["amount"],
        # The row number travels in ``row``; the import dialog prints it in
        # front of the message, so the message does not repeat it.
        "label": report["description"][:80],
        "message": (
            f"'{report['description'][:80]}' reads as a "
            f"{_SUMMARY_KIND_WORDS[report['kind']]} line and was not imported as a position."
        ),
    }


_IMPORT_MAX_QUANTITY = 1e9
_IMPORT_MAX_UNIT_RATE = 1e8


def _rows_to_positions(
    rows: list[dict[str, Any]],
    *,
    source: str = "excel_import",
    row_numbers: list[int] | None = None,
) -> ImportedBOQ:
    """Convert canonical rows into :class:`ImportedPosition` objects.

    Carries the sanity bounds + section-row + summary-row detection that
    the legacy inline parser used. Per-row errors are collected on the
    returned :class:`ImportedBOQ` rather than raised so the dispatcher
    can return them as a structured list.
    """
    result = ImportedBOQ(source_format="csv-or-xlsx")
    auto_ordinal = 1

    # Pre-compute a median unit rate across the file so we can warn on
    # any single position that's >10× above (likely a tampered export).
    rate_samples = sorted(v for v in (safe_float(r.get("unit_rate"), default=0.0) for r in rows) if v > 0)
    median_rate = rate_samples[len(rate_samples) // 2] if rate_samples else 0.0

    kept_rows, summary_rows = partition_summary_rows(rows, row_numbers=row_numbers)
    result.skipped += len(summary_rows)
    result.warnings.extend(summary_row_warning(report) for report in summary_rows)
    if summary_rows:
        result.metadata["summary_rows"] = summary_rows

    for row_idx, row in kept_rows:
        try:
            description = str(row.get("description", "")).strip()
            if not description:
                result.skipped += 1
                continue

            desc_lower = description.lower()
            if desc_lower in _TOTAL_ROW_DESCRIPTIONS:
                result.skipped += 1
                continue
            if desc_lower.startswith("subtotal:") or desc_lower.startswith("zwischensumme:"):
                result.skipped += 1
                continue

            ordinal = str(row.get("ordinal", "")).strip()
            if not ordinal:
                ordinal = str(auto_ordinal)
            auto_ordinal += 1

            # Round-trip identity (GitHub #360): the dedicated "Position ID"
            # column an export stamped. Blank -> new row; a value belonging to
            # the target BOQ -> update in place (resolved downstream by the
            # diff against the BOQ's current ids).
            position_id = normalise_id(row.get("position_id"))

            unit_raw = str(row.get("unit", "")).strip()
            quantity_raw = row.get("quantity")
            unit_rate_raw = row.get("unit_rate")
            quantity, q_err = parse_numeric_cell(quantity_raw)
            unit_rate, r_err = parse_numeric_cell(unit_rate_raw)
            if q_err is not None:
                result.errors.append(
                    {
                        "row": row_idx,
                        "ordinal": ordinal,
                        "error": f"Invalid quantity at row {row_idx}: {q_err}",
                    }
                )
                continue
            if r_err is not None:
                result.errors.append(
                    {
                        "row": row_idx,
                        "ordinal": ordinal,
                        "error": f"Invalid unit_rate at row {row_idx}: {r_err}",
                    }
                )
                continue
            assert quantity is not None
            assert unit_rate is not None

            # Section detection: a row with a description but no unit /
            # quantity / rate is a section header from our own exporter.
            is_section_row = (
                not unit_raw and (quantity_raw in (None, "", 0, 0.0)) and (unit_rate_raw in (None, "", 0, 0.0))
            )
            if is_section_row:
                result.positions.append(
                    ImportedPosition(
                        description=description,
                        ordinal=ordinal,
                        unit="section",
                        quantity=0.0,
                        unit_rate=0.0,
                        classification={},
                        source=source,
                        metadata={
                            "import_row_index": row_idx,
                            "section_header": True,
                        },
                        is_section=True,
                        position_id=position_id,
                    )
                )
                continue

            unit = unit_raw or "pcs"

            # Range guards - reject obvious tamper / typo errors.
            if not (0 <= quantity <= _IMPORT_MAX_QUANTITY):
                result.errors.append(
                    {
                        "row": row_idx,
                        "ordinal": ordinal,
                        "error": f"Quantity out of range: {quantity}",
                    }
                )
                continue
            if not (0 <= unit_rate <= _IMPORT_MAX_UNIT_RATE):
                result.errors.append(
                    {
                        "row": row_idx,
                        "ordinal": ordinal,
                        "error": f"Unit rate out of range: {unit_rate}",
                    }
                )
                continue

            # Soft warnings. A lump sum prices a whole piece of work, so its
            # rate says nothing next to the per-metre rates around it.
            if median_rate > 0 and unit_rate > median_rate * 10 and not is_lump_sum_unit(unit):
                result.warnings.append(
                    {
                        "row": row_idx,
                        "ordinal": ordinal,
                        "severity": "warning",
                        "message": (
                            f"Unit rate {unit_rate:.2f} is >10× the file median "
                            f"({median_rate:.2f}) - possible typo or tampered export."
                        ),
                    }
                )
            if quantity == 0:
                result.warnings.append(
                    {
                        "row": row_idx,
                        "ordinal": ordinal,
                        "severity": "info",
                        "message": "Quantity is zero - position imported but contributes no cost.",
                    }
                )
            if unit_rate == 0:
                result.warnings.append(
                    {
                        "row": row_idx,
                        "ordinal": ordinal,
                        "severity": "info",
                        "message": "Unit rate is zero - position imported without a rate.",
                    }
                )

            # Heuristic classification (Epics I9 + I10).
            class_value = str(row.get("classification", "")).strip()
            classification = _infer_classification(class_value, description)

            result.positions.append(
                ImportedPosition(
                    description=description,
                    ordinal=ordinal,
                    unit=unit,
                    quantity=quantity,
                    unit_rate=unit_rate,
                    classification=classification,
                    source=source,
                    metadata={"import_row_index": row_idx},
                    position_id=position_id,
                )
            )

        except Exception as exc:  # noqa: BLE001 - caller surfaces row #
            result.errors.append({"row": row_idx, "ordinal": "", "error": str(exc)})
            logger.warning("Excel/CSV row %d error: %s", row_idx, exc)

    return result


class ExcelImporter:
    """Generic Excel (.xlsx) / CSV importer with NRM + MasterFormat heuristics."""

    format_id: ClassVar[str] = "excel"
    extensions: ClassVar[tuple[str, ...]] = (".xlsx", ".csv")
    display_name: ClassVar[str] = "Excel / CSV BOQ"
    rule_packs: ClassVar[tuple[str, ...]] = ("boq_quality",)

    @classmethod
    def detect(cls, head_bytes: bytes, filename: str) -> bool:
        """Detect by magic bytes (xlsx zip header / CSV text) + extension."""
        if not head_bytes:
            return False
        name = filename.lower()
        if not any(name.endswith(ext) for ext in cls.extensions):
            return False
        fmt = _detect_file_format(head_bytes[:4096])
        if name.endswith(".xlsx"):
            return fmt == "xlsx"
        if name.endswith(".csv"):
            return fmt == "csv"
        return False

    @classmethod
    async def parse(cls, content: bytes, *, locale: str = "en") -> ImportedBOQ:
        """Parse an .xlsx or .csv BOQ into :class:`ImportedBOQ`."""
        if not content:
            raise ImporterParseError("Spreadsheet upload is empty")

        fmt = _detect_file_format(content[:4096])

        # Hungarian bills are not tables with a header row, so the alias mapper
        # below reads nothing out of them: the building shape spreads its item
        # code across nine columns on seventeen sheets, and both shapes carry
        # two unit prices per line rather than one. The profile answers only for
        # a workbook it recognises and hands everything else straight back, and
        # it has to be asked here rather than in ``detect`` because an xlsx is a
        # zip whose first four kilobytes say nothing about its contents.
        if fmt == "xlsx":
            hungarian = parse_hungarian_workbook(content)
            if hungarian is not None and hungarian.positions:
                return hungarian

        import_meta: dict[str, Any] = {}
        try:
            if fmt == "xlsx":
                rows, import_meta = _parse_rows_from_excel(content)
                source_format = "xlsx"
            elif fmt == "csv":
                rows = _parse_rows_from_csv(content)
                source_format = "csv"
            else:
                raise ImporterParseError(f"Unsupported spreadsheet format: detected {fmt!r}")
        except ImporterParseError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ImporterParseError(f"Could not parse spreadsheet: {exc}") from exc

        if not rows:
            raise ImporterParseError("No data rows found. Check that the header row names the columns.")

        result = _rows_to_positions(rows, row_numbers=import_meta.get("row_numbers"))
        result.source_format = source_format
        result.metadata = {
            **result.metadata,
            "original_columns": import_meta.get("original_columns", []),
            "column_mapping": import_meta.get("column_mapping", {}),
            "sheet_names": import_meta.get("sheet_names", []),
            "total_rows_seen": len(rows),
        }
        return result
