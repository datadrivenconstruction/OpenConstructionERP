# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Excel (.xlsx, .xls) and CSV BOQ importer.

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
import itertools
import json
import logging
import math
import re
import unicodedata
from collections.abc import Iterable, Iterator
from typing import Any, ClassVar, Literal

from app.core.file_signature import detect as detect_signature
from app.core.sheet_header import HEADER_SEARCH_ROWS, find_header_row
from app.modules.boq.importers._base import (
    ImportedBOQ,
    ImportedPosition,
    ImporterParseError,
)
from app.modules.boq.importers._encoding import (
    comma_groups_thousands,
    decode_text_bytes,
    dot_groups_thousands,
    fold_width,
    parse_numeric_cell,
    safe_float,
)
from app.modules.boq.importers._workbook import open_workbook
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
        # A bill that prices material and labour apart carries two rates and
        # two totals per line and no single rate at all. See
        # :func:`_combine_split_columns` for how they become the one rate.
        "material_rate": ("material rate", "material unit rate", "material unit price"),
        "labour_rate": ("labour rate", "labor rate", "labour unit rate", "labor unit rate", "labour unit price"),
        "material_total": ("material total", "material amount"),
        "labour_total": ("labour total", "labor total", "labour amount", "labor amount"),
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
        # The Spanish estimating programs head a presupuesto "Código | Ud |
        # Resumen | Medición | Precio | Importe", and a Mexican catálogo de
        # conceptos "Clave | Concepto | Unidad | Cantidad | P.U. | Importe".
        "description": ("descripción", "descripcion", "designación", "designacion", "resumen", "concepto"),
        "unit": ("unidad", "uds", "ud", "unidad de medida"),
        "quantity": ("cantidad", "cant", "cant.", "medición", "medicion"),
        "unit_rate": ("precio", "precio unitario", "precio unit.", "p. unitario", "p.u."),
        "total": ("importe", "importe total"),
        "classification": ("código", "codigo", "clave"),
    },
    "fr": {
        # A DPGF or DQE is headed "N° | Désignation | U | Qté | PU HT |
        # Montant HT".
        "ordinal": ("n°",),
        "description": ("désignation", "designation"),
        "unit": ("unité", "u"),
        "quantity": ("quantité", "qté", "qte"),
        "unit_rate": ("prix", "prix unitaire", "prix unitaire ht", "pu", "p.u.", "pu ht", "p.u. ht"),
        "total": ("montant", "prix total", "montant ht", "total ht"),
    },
    "it": {
        # A computo metrico estimativo is headed "Num. ord. | Tariffa |
        # Designazione dei lavori | U.M. | Quantità | Prezzo unitario |
        # Importo", the tariffa being the code of the regional price list.
        "ordinal": ("n.", "n. ord.", "num. ord.", "n.ord."),
        "description": ("descrizione", "designazione dei lavori", "descrizione dei lavori"),
        "unit": ("unità", "u", "u.m.", "unità di misura", "unita di misura"),
        "quantity": ("quantità", "quantita", "q.tà", "q.ta", "qta"),
        "unit_rate": ("prezzo", "prezzo unitario", "prezzo unit."),
        "total": ("importo", "totale", "importo totale"),
        "classification": ("tariffa", "codice", "codice tariffa", "articolo"),
    },
    "pl": {
        # A kosztorys is headed "Lp. | Podstawa | Opis robót | j.m. | Ilość |
        # Cena jedn. | Wartość"; the podstawa cites the KNR catalogue table.
        "ordinal": ("lp", "lp."),
        "description": ("opis", "opis robót", "opis robot", "nazwa"),
        "unit": ("jed", "j.m.", "jednostka miary"),
        "quantity": ("ilość", "ilosc"),
        # Polish carried no rate header at all until the table was split by
        # language, which made a Polish bill import with every rate at zero.
        "unit_rate": ("cena jednostkowa", "cena jedn.", "cena"),
        "total": ("wartość", "wartosc"),
        "classification": ("podstawa", "podstawa wyceny", "knr"),
    },
    "ru": {
        # A smeta is headed "№ п/п | Обоснование | Наименование работ и
        # затрат | Ед. изм. | Кол. | Цена | Всего"; the обоснование is the
        # GESN or FER rate code the line was priced from.
        "ordinal": ("№ п/п", "п/п", "№ пп"),
        "description": ("наименование", "наименование работ", "наименование работ и затрат"),
        "unit": ("ед", "ед.", "ед. изм.", "единица измерения"),
        "quantity": ("количество", "кол-во", "кол."),
        "unit_rate": ("цена",),
        "total": ("стоимость", "всего", "сметная стоимость"),
        "classification": ("обоснование", "шифр", "шифр расценки", "код"),
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
    # Turkish keşif özeti. The poz number is the code of the unit price the
    # line was priced from ("15.150.1005") and the sıra number is the running
    # number, so "poz" is read as the classification.
    "tr": {
        "ordinal": ("sıra", "sira", "sıra no", "sira no"),
        "description": (
            "tanım",
            "tanim",
            "iş kalemi",
            "is kalemi",
            "açıklama",
            "aciklama",
            "imalatın cinsi",
            "imalatin cinsi",
            "yapılan işin cinsi",
            "yapilan isin cinsi",
        ),
        "unit": ("birim", "birimi", "ölçü birimi", "olcu birimi"),
        "quantity": ("miktar", "miktarı", "miktari", "metraj"),
        "unit_rate": ("birim fiyat", "birim fiyatı", "birim fiyati"),
        "total": ("tutar", "tutarı", "tutari", "toplam", "toplam tutar"),
        # Bare "Poz." is the Romanian and Slovenian position number, so only
        # the spellings that say "poz number" are Turkish.
        "classification": ("poz no", "poz numarası", "poz numarasi"),
    },
    # Hungarian költségvetés. The item number ("Tételszám") is the norm or
    # catalogue code of the line, 21-003-5.1.1 and the like, not its running
    # number, so it is read as the classification and "Ssz." stays the
    # ordinal. Every priced line is quoted as material (anyag) plus fee (díj),
    # which a two-row header writes as "Egységár" over "Anyag | Díj".
    "hu": {
        "ordinal": ("sorszám", "sorszam", "ssz", "ssz.", "s.sz.", "sorsz."),
        "description": (
            "megnevezés",
            "megnevezes",
            "tétel szövege",
            "tetel szovege",
            # The same heading written as one word, the way several estimating
            # programs print it.
            "tételszöveg",
            "tetelszoveg",
            "tétel megnevezése",
            "tetel megnevezese",
            "leírás",
            "leiras",
        ),
        "unit": (
            "egység",
            "egyseg",
            "m.e.",
            # "Me." is how a narrow column abbreviates mennyiségi egység.
            "me.",
            "mennyiségi egység",
            "mennyisegi egyseg",
            "mértékegység",
            "mertekegyseg",
            "m.egys.",
        ),
        "quantity": ("mennyiség", "mennyiseg", "menny.", "menny"),
        "unit_rate": ("egységár", "egysegar", "egység ár", "egyseg ar"),
        "total": ("összesen", "osszesen", "összeg", "osszeg", "mindösszesen", "mindosszesen"),
        "classification": ("tételszám", "tetelszam", "tétel szám", "tetel szam", "normaszám", "normaszam"),
        # The split is headed three ways: "Anyag egységár", the same two words
        # the other way round ("Egységár anyag", which is also what a two-row
        # header grouped under "Anyag" composes to), and "Anyag egységre". A
        # bill headed the second or third way used to import every line at a
        # rate of zero without a word.
        "material_rate": (
            "anyag egységár",
            "anyag egysegar",
            "anyag egységára",
            "anyag egysegara",
            "egységár anyag",
            "egysegar anyag",
            "anyag egységre",
            "anyag egysegre",
        ),
        "labour_rate": (
            "díj egységár",
            "dij egysegar",
            "munkadíj egységár",
            "munkadij egysegar",
            "egységár díj",
            "egysegar dij",
            "díj egységre",
            "dij egysegre",
            "munkadíj egységre",
            "munkadij egysegre",
        ),
        "material_total": (
            "anyag összesen",
            "anyag osszesen",
            "nettó anyag összesen",
            "netto anyag osszesen",
            "anyag összege",
            "anyag osszege",
            "összesen anyag",
            "osszesen anyag",
        ),
        "labour_total": (
            "díj összesen",
            "dij osszesen",
            "munkadíj összesen",
            "munkadij osszesen",
            "nettó díj összesen",
            "netto dij osszesen",
            "díj összege",
            "dij osszege",
            "munkadíj összege",
            "munkadij osszege",
            "összesen díj",
            "osszesen dij",
        ),
    },
    "ro": {
        "ordinal": ("nr. crt.", "nr crt", "crt.", "poz."),
        "description": ("denumire", "denumire lucrare", "denumirea lucrării", "denumirea lucrarii", "descriere"),
        "unit": ("um", "u.m.", "unitate", "unitate de măsură", "unitate de masura"),
        "quantity": ("cantitate",),
        "unit_rate": ("preț unitar", "pret unitar"),
        "total": ("valoare", "valoare totală", "valoare totala"),
        # The norm code of the line ("CA01A1"), not the deviz chapter.
        "classification": ("simbol", "cod", "cod articol", "simbol articol"),
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
        "classification": ("άρθρο", "αρθρο", "κωδικός άρθρου", "κωδικος αρθρου", "κωδικός", "κωδικος"),
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
        "classification": ("шифр", "обґрунтування", "обгрунтування", "код"),
    },
    "ja": {
        "ordinal": ("番号", "項番"),
        "description": ("名称", "工種", "摘要", "工事内容", "説明", "内容"),
        "unit": ("単位",),
        "quantity": ("数量",),
        "unit_rate": ("単価",),
        "total": ("金額", "合計"),
        "classification": ("コード", "細目コード", "工種コード"),
    },
    "ko": {
        "ordinal": ("번호", "순번", "연번"),
        "description": ("품명", "공종", "내역", "설명", "공사명"),
        "unit": ("단위",),
        "quantity": ("수량",),
        "unit_rate": ("단가",),
        "total": ("금액", "합계"),
        "classification": ("코드", "공종코드", "품목코드"),
    },
    "zh": {
        "ordinal": ("序号", "编号"),
        "description": ("名称", "项目名称", "工作内容", "描述", "项目描述"),
        "unit": ("单位", "计量单位"),
        "quantity": ("数量", "工程量"),
        "unit_rate": ("单价", "综合单价"),
        "total": ("合价", "金额", "合计"),
        # The twelve-digit item code of a GB 50500 bill, and the quota number
        # a line priced from a 定额 cites.
        "classification": ("项目编码", "清单编码", "编码", "定额编号"),
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
        "classification": ("kode", "kode analisa", "kode ahsp", "kode pekerjaan"),
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

# Round, square and curly brackets, after NFKC has folded their full-width
# forms ("（元）" -> "(元)"), and the CJK lenticular and tortoise-shell brackets,
# which have no ASCII twin: "金额【元】", "单价〔元〕".
_BRACKETED = re.compile(r"\([^)]*\)|\[[^\]]*\]|\{[^}]*\}|【[^】]*】|〔[^〕]*〕|〖[^〗]*〗")


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

    Compatibility forms are folded first (NFKC), so a header typed with
    full-width brackets or letters ("金额（元）", "ＱＴＹ") reads like its
    ASCII twin. It used to keep "元" and match nothing, which refused the
    two-row header of a GB 50500 bill and imported every line at rate zero.

    Args:
        text: The raw cell text.

    Returns:
        The normalised label, possibly empty.
    """
    folded = unicodedata.normalize("NFKC", str(text)).lower()
    lowered = _BRACKETED.sub(" ", folded).translate(_TRANSLITERATE)
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


# ── Split rates, header language, two-row headers ──────────────────────────

# The split columns and the single column each one feeds. A Hungarian bill
# prices every line as material plus fee and has no single rate column at
# all, so reading only ``unit_rate`` imported every line at zero, and reading
# one half as the rate would halve the bill.
_SPLIT_COLUMNS: dict[str, str] = {
    "material_rate": "unit_rate",
    "labour_rate": "unit_rate",
    "material_total": "total",
    "labour_total": "total",
}

# Languages whose CSV exports come out of Excel in Windows-1250. That code
# page decodes as Windows-1252 without an error, so nothing fails: the
# Hungarian ő and ű quietly become õ and û. The header row says which market
# wrote the file, and its words are plain enough to read in either code page.
_CP1250_LANGUAGES: frozenset[str] = frozenset({"hu", "cs", "sk", "pl", "hr", "sl", "sr", "ro"})

# Every Windows code page Excel saves a CSV in, with the languages whose
# header row says a file came from it. Cyrillic, Greek, Hebrew, Arabic and
# Thai files decode as Windows-1252 without an error too, into letters
# nobody wrote; Turkish loses only its ı, ş and ğ, which is harder to see.
# The multi-byte East Asian pages come last: they are strict enough to fail
# on most Western bytes, but not on all of them.
_CODE_PAGE_LANGUAGES: tuple[tuple[str, frozenset[str]], ...] = (
    ("cp1250", _CP1250_LANGUAGES),
    ("cp1251", frozenset({"ru", "uk", "bg", "kk", "ky", "sr", "mn"})),
    ("cp1253", frozenset({"el"})),
    ("cp1254", frozenset({"tr"})),
    ("cp1257", frozenset({"et"})),
    ("cp1255", frozenset({"he"})),
    ("cp1256", frozenset({"ar", "fa", "ur"})),
    ("cp874", frozenset({"th"})),
    ("cp1258", frozenset({"vi"})),
    ("cp932", frozenset({"ja"})),
    ("gbk", frozenset({"zh"})),
    ("cp949", frozenset({"ko"})),
)

_LANGUAGE_HEADER_KEYS: dict[str, frozenset[str]] = {
    language: frozenset(_label_key(word) for words in headers.values() for word in words)
    for language, headers in _HEADERS_BY_LANGUAGE.items()
}


def header_language(header: tuple[Any, ...] | list[Any] | None) -> str | None:
    """The language whose table names the most cells of a header row.

    Args:
        header: The header row's cells.

    Returns:
        The language code, or ``None`` when no cell is a known header. A tie
        goes to the language listed first in :data:`_HEADERS_BY_LANGUAGE`.
    """
    keys = [_label_key(str(cell)) for cell in header or () if cell is not None and str(cell).strip()]
    best: str | None = None
    best_count = 0
    for language, known in _LANGUAGE_HEADER_KEYS.items():
        count = sum(1 for key in keys if key and key in known)
        if count > best_count:
            best, best_count = language, count
    return best


def _cell_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _compose_two_row_header(header: tuple[Any, ...], below: tuple[Any, ...]) -> tuple[str, ...] | None:
    """Read a header written over two rows, or ``None`` when it is one row.

    Split bills head their money columns twice: "Egységár" merged across the
    two columns under it, which say "Anyag" and "Díj". A merged cell holds its
    text in the first column only, so the parent label is carried right across
    the empty cells of its span, and each column under it is named "<sub>
    <parent>", which is what the alias table spells ("anyag egységár").

    The other way a block is headed twice names a column in each sub-cell and
    only groups them under the parent: GB 50500 heads its money block
    "金额（元）" over "综合单价 | 合价 | 其中：暂估价", and a Korean bill heads
    each cost block over "단가 | 금액". When no sub-cell of a block composes
    into a known column and the parent is itself a column name, each sub-cell
    that names a column on its own is read as that column. A block whose
    parent names nothing ("재료비", material) is left unread rather than
    guessed at.

    The composition is taken only when the row below holds no number and the
    composed header names more columns than the first row alone. A first data
    row that happens to be a text-only section heading composes into nothing
    the table knows and is left alone.
    """
    if not any(_cell_text(cell) for cell in below):
        return None
    if any(not math.isnan(safe_float(cell, default=math.nan)) for cell in below):
        return None
    width = max(len(header), len(below))
    composed: list[str] = []
    # Column indices of each parent's block, keyed by the parent's own column.
    blocks: dict[int, list[int]] = {}
    subs: dict[int, str] = {}
    parent = ""
    parent_index = -1
    for index in range(width):
        top = _cell_text(header[index]) if index < len(header) else ""
        sub = _cell_text(below[index]) if index < len(below) else ""
        if top:
            parent = top if sub else ""
            parent_index = index
        elif not sub:
            parent = ""
        if sub and parent:
            composed.append(f"{sub} {parent}")
            blocks.setdefault(parent_index, []).append(index)
            subs[index] = sub
        else:
            composed.append(top or sub)
    for parent_index, members in blocks.items():
        if any(_match_column(composed[index]) for index in members):
            continue
        if not _match_column(_cell_text(header[parent_index])):
            continue
        for index in members:
            if _match_column(subs[index]):
                composed[index] = subs[index]
    known_before = sum(1 for cell in header if _cell_text(cell) and _match_column(_cell_text(cell)))
    known_after = sum(1 for cell in composed if cell and _match_column(cell))
    return tuple(composed) if known_after > known_before else None


def _map_columns(header: tuple[Any, ...]) -> dict[int, str]:
    """Column index -> canonical column for every header cell the table knows."""
    column_map: dict[int, str] = {}
    for index, cell in enumerate(header):
        text = _cell_text(cell)
        canonical = _match_column(text) if text else None
        if canonical:
            column_map[index] = canonical
    return column_map


# Languages whose bills write a decimal comma and, often enough, a dot between
# thousands: "12.500 Ft" is twelve thousand five hundred forint. Read with a
# dot as the decimal point it imported as 12.5, a thousandth of the price, and
# nothing looked wrong. This was first fixed for Hungarian alone; every
# language below writes a decimal comma in CLDR, and a workbook headed in one
# of them had the same thousandth. A file that shows a decimal point of its
# own ("1,250.50", "12.5") is read the other way whatever its headers say, so
# a Mexican bill headed in Spanish keeps its point.
DECIMAL_COMMA_LANGUAGES: frozenset[str] = frozenset(
    {
        "bg", "cs", "da", "de", "el", "es", "et", "fi", "fr", "hr", "hu", "id", "it", "kk",
        "ky", "nl", "no", "pl", "pt", "ro", "ru", "sk", "sl", "sr", "sv", "tr", "uk", "uz", "vi",
    }
)  # fmt: skip

# The mirror image: languages that write a decimal point, where "12,500" is
# twelve thousand five hundred and a single comma used to be read as the
# decimal point, importing twelve and a half.
DECIMAL_POINT_LANGUAGES: frozenset[str] = frozenset({"en", "ja", "ko", "zh", "th", "he", "hi", "bn", "ur", "ar"})

# Kept under its old name for the readers that ask for it.
_DOT_THOUSANDS_LANGUAGES: frozenset[str] = DECIMAL_COMMA_LANGUAGES

# A number that can only be written with a decimal point ("1,250.50", "12.5")
# or only with a decimal comma ("1.250,50", "12,5").
_POINT_DECIMAL_SHAPE = re.compile(r"\d,\d{3}\.\d|\d\.\d{1,2}(?![\d.,])")
_COMMA_DECIMAL_SHAPE = re.compile(r"\d\.\d{3},\d|\d,\d{1,2}(?![\d.,])")

# The numeric columns whose typed text is read with dot thousands.
_NUMERIC_COLUMNS: tuple[str, ...] = ("quantity", "unit_rate", *_SPLIT_COLUMNS)


def _combine_split_columns(
    row: dict[str, Any], *, dot_thousands: bool = False, comma_thousands: bool = False
) -> dict[str, Any]:
    """Fold material and labour columns into ``unit_rate`` and ``total``.

    Only when the file has no single column of its own for the target: a
    bill that carries "Egységár" beside the split keeps its own figure. A
    blank half counts as zero (a fee-only line is a correct line), an unread
    half is handed on as text so the row reports it rather than importing at
    a guessed rate, and a row where both halves are blank stays unpriced, so
    a heading or a total line is still recognised as one.

    The two flags are the file's grouping, decided once for the whole file by
    :func:`_grouping_conventions`; see :func:`_fold_split_columns`.
    """
    for target in ("unit_rate", "total"):
        halves = [key for key, feeds in _SPLIT_COLUMNS.items() if feeds == target and key in row]
        if not halves or not _is_blank_value(row.get(target)):
            continue
        amount = 0.0
        filled = False
        for key in halves:
            value = row[key]
            if _is_blank_value(value):
                continue
            parsed, error = parse_numeric_cell(value, dot_thousands=dot_thousands, comma_thousands=comma_thousands)
            if error is not None or parsed is None:
                row[target] = value
                break
            amount += parsed
            filled = True
        else:
            if filled:
                row[target] = amount
    return row


def _fold_split_columns(rows: list[dict[str, Any]], language: str | None) -> list[dict[str, Any]]:
    """Fold every row's material and labour halves with the file's own grouping.

    The fold used to run row by row as each row was read, with the header
    language as the only guide, before the file's numbers had been seen. A
    file whose own cells veto that language's grouping (an English header over
    "2,50", a Hungarian one over "12.5") still had its halves read with it, so
    "1,250" + "2,50" became 1252.50 instead of 3.75. Deciding first, over every
    row of the file, is what :func:`_rows_to_positions` does for the single
    rate column, so the two now agree.
    """
    dot_thousands, comma_thousands = _grouping_conventions(rows, language)
    return [_combine_split_columns(row, dot_thousands=dot_thousands, comma_thousands=comma_thousands) for row in rows]


def header_report(headers: tuple[Any, ...] | list[Any], column_map: dict[int, str]) -> dict[str, Any]:
    """What the header row said, what it was read as, and what a bill still needs.

    ``recognised`` maps each header cell the table knows to the column it
    feeds, ``unrecognised`` lists the cells it does not, and ``missing`` names
    what the sheet lacks to be read as a bill at all: a description, and a
    quantity, unit or rate. The import dialog shows all three, so a file that
    imports nothing says which heading to rename instead of coming back empty.
    """
    recognised: dict[str, str] = {}
    unrecognised: list[str] = []
    for index, cell in enumerate(headers):
        text = _cell_text(cell)
        if not text:
            continue
        canonical = column_map.get(index)
        if canonical:
            recognised[text] = _SPLIT_COLUMNS.get(canonical, canonical)
        else:
            unrecognised.append(text)
    mapped = set(column_map.values())
    missing: list[str] = []
    if "description" not in mapped:
        missing.append("description")
    if not mapped & _ITEM_SHEET_COLUMNS:
        missing.append("quantity_or_rate")
    return {"recognised": recognised, "unrecognised": unrecognised, "missing": missing}


def _display_header(
    headers: tuple[Any, ...] | list[Any],
    header_number: int,
    column_map: dict[int, str],
    top_rows: Iterable[tuple[Any, ...]],
) -> tuple[tuple[Any, ...], int]:
    """The row that most looks like the header, and its row number.

    When fewer than two cells matched anywhere, the reader falls back to row
    one, which is often a title ("Költségvetés"). The widest row near the top
    is what the user wrote as headings, so that is the row the header report
    names and the row the import dialog offers to map column by column.
    """
    if len(set(column_map.values())) >= 2:
        return tuple(headers), header_number
    filled = [
        (sum(1 for cell in row if _cell_text(cell)), number, tuple(row)) for number, row in enumerate(top_rows, start=1)
    ]
    best = max(filled, key=lambda item: (item[0], -item[1]), default=None)
    if best is None or best[0] < 2:
        return tuple(headers), header_number
    return best[2], best[1]


# ── A column mapping chosen by the user ─────────────────────────────────────

#: What the import dialog lets a column be mapped to. An empty string leaves
#: the column out. The split columns are not offered: a column the reader took
#: as the material or the fee half keeps that reading until the user maps it
#: to something else.
COLUMN_MAPPING_TARGETS: frozenset[str] = frozenset(
    {"", "ordinal", "description", "unit", "quantity", "unit_rate", "total", "classification"}
)

#: The widest header a mapping may address. A real bill has a few dozen
#: columns; this only bounds what a request can make the reader look at.
_MAX_MAPPED_COLUMN = 1000


def parse_column_mapping(raw: str | None) -> dict[int, str] | None:
    """Read the ``column_mapping`` form field: column index -> target column.

    The indices are those of the header the preview reported
    (``metadata.original_columns``), and only the columns the user changed
    are sent: every other column keeps the reading the importer made of it.

    Raises:
        ValueError: when the field is not a JSON object of column indices to
            targets from :data:`COLUMN_MAPPING_TARGETS`, with a message that
            says which part is wrong.
    """
    if raw is None or not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("column_mapping is not valid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("column_mapping must be an object of column index to column name")
    mapping: dict[int, str] = {}
    for key, value in data.items():
        if not (isinstance(key, str) and key.isdigit() and int(key) < _MAX_MAPPED_COLUMN):
            raise ValueError(f"column_mapping key {key!r} is not a column index")
        if not isinstance(value, str) or value not in COLUMN_MAPPING_TARGETS:
            allowed = ", ".join(sorted(target for target in COLUMN_MAPPING_TARGETS if target))
            raise ValueError(
                f"column_mapping maps column {key} to {value!r}; use one of: {allowed}, or an empty string"
            )
        mapping[int(key)] = value
    targets = [value for value in mapping.values() if value]
    for target in set(targets):
        if targets.count(target) > 1:
            raise ValueError(f"column_mapping maps more than one column to {target}")
    return mapping or None


def _apply_column_mapping(column_map: dict[int, str], overrides: dict[int, str], width: int) -> dict[int, str]:
    """The importer's own reading of a header with the user's choices laid over it.

    Raises:
        ImporterParseError: when a choice addresses a column the header does
            not have, or leaves two columns feeding the same field.
    """
    mapped = dict(column_map)
    for index, target in overrides.items():
        if index >= width:
            raise ImporterParseError(
                f"The column mapping names column {index + 1}, and the header row has {width} columns."
            )
        if target:
            mapped[index] = target
        else:
            mapped.pop(index, None)
    for target in {target for target in overrides.values() if target}:
        columns = [index + 1 for index, canonical in mapped.items() if canonical == target]
        if len(columns) > 1:
            raise ImporterParseError(
                f"The column mapping leaves columns {', '.join(map(str, columns))} all feeding {target}. "
                "Map the others to something else or leave them out."
            )
    return mapped


def column_mapping_warning(reason: str, sheet: str | None = None) -> dict[str, Any]:
    """The note for a column mapping the import could not lay over the file.

    ``reason`` is ``profile`` (the workbook was read through a national
    profile, which has no generic columns), ``format`` (the file is not a
    spreadsheet) or ``different_header`` (a further sheet is headed
    differently from the one the mapping was chosen on, and was read with the
    importer's own mapping).
    """
    messages = {
        "profile": "The column mapping was not used: this workbook was read through its national profile.",
        "format": "The column mapping was not used: it applies to spreadsheets only.",
        "different_header": "The column mapping was not used on this sheet: its header differs from the first one.",
    }
    warning: dict[str, Any] = {
        "severity": "warning",
        "code": "column_mapping_not_applied",
        "reason": reason,
        "message": messages.get(reason, "The column mapping was not used."),
    }
    if sheet:
        warning["sheet"] = sheet
        warning["message"] = f"Sheet {sheet}: " + warning["message"]
    return warning


def header_problem_error(report: dict[str, Any], sheet: str | None = None) -> dict[str, Any]:
    """The import error for a header row that does not name a bill's columns."""
    unrecognised = ", ".join(report["unrecognised"][:12]) or "-"
    error: dict[str, Any] = {
        "severity": "error",
        "code": "header_not_recognised",
        "missing": list(report["missing"]),
        "unrecognised": list(report["unrecognised"]),
        "recognised": dict(report["recognised"]),
        "error": (
            "The header row does not name "
            + " and ".join(
                "a description column" if item == "description" else "a quantity, unit or rate column"
                for item in report["missing"]
            )
            + f". Headings not recognised: {unrecognised}."
        ),
    }
    if sheet:
        error["sheet"] = sheet
    return error


def _is_blank_value(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _report_mapping(column_map: dict[int, str]) -> dict[str, str]:
    """The mapping as the import dialog shows it: a split column under the column it feeds."""
    return {str(index): _SPLIT_COLUMNS.get(canonical, canonical) for index, canonical in column_map.items()}


def _detect_file_format(content_head: bytes) -> Literal["xlsx", "xls", "csv", "parquet", "unknown"]:
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
    if sig == "ole":  # XLS = Excel 97-2003, an OLE2 compound file
        return "xls"
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


_CSV_DELIMITERS: tuple[str, ...] = (";", "\t", ",", "|")


def _sniff_delimiter(text: str) -> str:
    """The delimiter that splits the most lines into the same number of fields.

    ``csv.Sniffer`` reads the whole sample, title lines included, and a
    semicolon file whose numbers carry decimal commas gives it two plausible
    answers. Counting fields line by line with the csv reader itself (so a
    quoted "125,5" stays one field) and taking the delimiter whose most common
    field count is shared by the most lines picks the one the table is laid
    out in, whatever sits above it. A tie goes to the earlier delimiter in
    :data:`_CSV_DELIMITERS`, semicolon first, which is what Excel writes in
    every locale that uses the decimal comma.
    """
    lines = [line for line in text[:16384].splitlines()[:60] if line.strip()]
    best, best_score = ",", 0
    for delimiter in _CSV_DELIMITERS:
        counts: dict[int, int] = {}
        for fields in csv.reader(lines, delimiter=delimiter):
            if len(fields) > 1:
                counts[len(fields)] = counts.get(len(fields), 0) + 1
        score = max(counts.values(), default=0)
        if score > best_score:
            best, best_score = delimiter, score
    return best


def _locate_header(
    rows_iter: Any,
) -> tuple[tuple[Any, ...] | None, int, Any]:
    """Find the header row and read a second header row under it if there is one.

    Returns ``(header, number of the last header row, rows under it)``.
    """
    raw_headers, header_number, rows = find_header_row(iter(rows_iter), _match_column)
    if not raw_headers:
        return raw_headers, header_number, rows
    below = next(rows, None)
    if below is None:
        return tuple(raw_headers), header_number, rows
    composed = _compose_two_row_header(tuple(raw_headers), tuple(below))
    if composed is not None:
        return composed, header_number + 1, rows
    return tuple(raw_headers), header_number, itertools.chain([below], rows)


def _decode_csv(content_bytes: bytes) -> tuple[str, str]:
    """Decode a CSV upload, reading Windows-1250 files as Windows-1250.

    :func:`decode_text_bytes` answers Windows-1252 for any single-byte file,
    and that answer is wrong for a Central European export without being an
    error. When the first answer is a single-byte code page and the header
    row reads in a language of :data:`_CP1250_LANGUAGES`, the bytes are
    decoded again as Windows-1250. Kept to this reader: BC3 and the other
    text formats share :data:`DEFAULT_ENCODINGS` and are Western by
    convention.
    """
    text, encoding = decode_text_bytes(content_bytes)
    if encoding not in ("cp1252", "latin-1"):
        return text, encoding
    for code_page, languages in _CODE_PAGE_LANGUAGES:
        try:
            candidate = content_bytes.decode(code_page)
        except UnicodeDecodeError:
            continue
        if candidate == text:
            continue
        delimiter = _sniff_delimiter(candidate)
        header, _, _ = find_header_row(csv.reader(io.StringIO(candidate), delimiter=delimiter), _match_column)
        if header_language(header) in languages:
            return candidate, code_page
    return text, encoding


def _parse_csv(
    content_bytes: bytes,
    overrides: dict[int, str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Decode + parse a CSV into canonical-key dicts and import metadata.

    ``overrides`` is the user's column mapping, see :func:`parse_column_mapping`.
    """
    text, encoding = _decode_csv(content_bytes)
    delimiter = _sniff_delimiter(text)

    def top_rows() -> Iterable[list[str]]:
        return itertools.islice(csv.reader(io.StringIO(text), delimiter=delimiter), HEADER_SEARCH_ROWS)

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    raw_headers, header_number, rows_iter = _locate_header(reader)
    if not raw_headers:
        raise ImporterParseError("CSV file is empty or has no header row")

    column_map = _map_columns(raw_headers)
    display, display_row = _display_header(raw_headers, header_number, column_map, top_rows())
    if overrides is not None:
        if display_row != header_number:
            found, rows_iter = _header_at(csv.reader(io.StringIO(text), delimiter=delimiter), display_row)
            raw_headers, header_number = found or raw_headers, display_row
        column_map = _apply_column_mapping(_map_columns(raw_headers), overrides, len(raw_headers))
        display = tuple(raw_headers)
        display_map = column_map
        report = header_report(raw_headers, column_map)
    else:
        display_map = column_map if display == tuple(raw_headers) else _map_columns(display)
        report = header_report(display, display_map)
    language = header_language(raw_headers)

    rows: list[dict[str, Any]] = []
    row_numbers: list[int] = []
    for line_number, raw_row in enumerate(rows_iter, start=header_number + 1):
        row: dict[str, Any] = {}
        for idx, val in enumerate(raw_row):
            canonical = column_map.get(idx)
            if canonical:
                row[canonical] = val.strip() if isinstance(val, str) else val
        if row:
            rows.append(row)
            row_numbers.append(line_number)
    rows = _fold_split_columns(rows, language)

    import_metadata = {
        "original_columns": [_cell_text(h) for h in display],
        "header_row": display_row if overrides is None else header_number,
        "column_mapping": _report_mapping(display_map),
        "column_mapping_applied": overrides is not None,
        "header_language": language,
        "header_report": report,
        "encoding": encoding,
        "delimiter": delimiter,
        "total_rows": len(rows),
        "row_numbers": row_numbers,
    }
    return rows, import_metadata


def _parse_rows_from_csv(content_bytes: bytes) -> list[dict[str, Any]]:
    """Decode + parse a CSV into a list of canonical-key dicts."""
    rows, _ = _parse_csv(content_bytes)
    return rows


# The columns that make a sheet a bill: it has to say what each line is and
# carry at least one of these. Split *totals* alone do not count. A summary
# sheet heads its money "Anyag összesen | Díj összesen" beside the chapter
# names and has no quantity, unit or rate, and letting those two columns make
# it an item sheet imported a workbook that opens on its summary as a handful
# of empty chapter headings while every line of the bill sat unread behind it.
_ITEM_SHEET_COLUMNS: frozenset[str] = frozenset({"quantity", "unit", "unit_rate", "material_rate", "labour_rate"})


def _sheet_columns(worksheet: Any) -> set[str]:
    """The canonical columns a worksheet's header row names."""
    header, _, _ = _locate_header(worksheet.iter_rows(max_row=HEADER_SEARCH_ROWS + 1, values_only=True))
    return set(_map_columns(header or ()).values())


def _is_item_sheet(columns: set[str]) -> bool:
    return "description" in columns and bool(columns & _ITEM_SHEET_COLUMNS)


def _sheet_is_hidden(worksheet: Any) -> bool:
    return str(getattr(worksheet, "sheet_state", "visible") or "visible") != "visible"


def _sheet_has_content(worksheet: Any) -> bool:
    for row in worksheet.iter_rows(max_row=HEADER_SEARCH_ROWS + 1, values_only=True):
        if any(_cell_text(cell) for cell in row):
            return True
    return False


def _pick_item_sheets(workbook: Any) -> tuple[list[Any], list[dict[str, Any]]]:
    """The worksheets the bill's lines are on, and why every other one was not read.

    A sheet is an item sheet when its header names a description and a
    quantity, unit or rate (see :data:`_ITEM_SHEET_COLUMNS`). Every visible item
    sheet is read, in workbook order: a bill priced by trade keeps each trade on
    a sheet of its own ("Építészet", "Épületgépészet", "Villamos") behind a cover
    and a summary ("Záradék", "Főösszesítő"), and reading only the first one
    lost every other trade without a word. A hidden sheet is left alone. When
    no sheet qualifies the active sheet is returned, so the error the user sees
    is the one it always was.

    Returns:
        ``(sheets, notes)``: the sheets to read, and one note per sheet that
        holds something and was not read, with its name and the reason.
    """
    sheets: list[Any] = []
    notes: list[dict[str, Any]] = []
    for name in workbook.sheetnames:
        worksheet = workbook[name]
        if _sheet_is_hidden(worksheet):
            if _sheet_has_content(worksheet):
                notes.append({"sheet": name, "reason": "hidden"})
            continue
        if _is_item_sheet(_sheet_columns(worksheet)):
            sheets.append(worksheet)
        elif _sheet_has_content(worksheet):
            notes.append({"sheet": name, "reason": "no_item_header"})
    if not sheets:
        return [workbook.active], []
    return sheets, notes


def _header_at(rows_iter: Iterable[tuple[Any, ...]], header_row: int) -> tuple[tuple[Any, ...] | None, Iterator[Any]]:
    """Row ``header_row`` (counted from 1) as the header, and the rows under it."""
    rows = iter(rows_iter)
    for number, row in enumerate(rows, start=1):
        if number == header_row:
            return tuple(row), rows
    return None, rows


def _read_sheet_rows(
    worksheet: Any,
    *,
    header_row: int | None = None,
    overrides: dict[int, str] | None = None,
) -> dict[str, Any] | None:
    """One item sheet's canonical rows, the sheet row of each, and its header.

    ``header_row`` reads that row as the header instead of looking for one, and
    ``overrides`` lays the user's column mapping over the importer's reading.
    """
    if header_row is None:
        raw_headers, header_number, rows_iter = _locate_header(worksheet.iter_rows(values_only=True))
    else:
        raw_headers, rows_iter = _header_at(worksheet.iter_rows(values_only=True), header_row)
        header_number = header_row
    if not raw_headers:
        return None
    column_map = _map_columns(raw_headers)
    if overrides is not None:
        column_map = _apply_column_mapping(column_map, overrides, len(raw_headers))
        display, display_row = tuple(raw_headers), header_number
        display_map = column_map
        report = header_report(raw_headers, column_map)
    else:
        display, display_row = _display_header(
            raw_headers,
            header_number,
            column_map,
            worksheet.iter_rows(max_row=HEADER_SEARCH_ROWS, values_only=True),
        )
        display_map = column_map if display == tuple(raw_headers) else _map_columns(display)
        report = header_report(display, display_map)
    # The material and labour halves are folded later, once every sheet of the
    # workbook has been read, see :func:`_parse_rows_from_excel`.
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
    return {
        "title": worksheet.title,
        "headers": tuple(raw_headers),
        "header_row": header_number,
        "display_headers": display,
        "display_header_row": display_row,
        "column_map": column_map,
        "display_column_map": display_map,
        "header_report": report,
        "rows": rows,
        "row_numbers": row_numbers,
    }


def _header_texts(headers: tuple[Any, ...]) -> tuple[str, ...]:
    return tuple(_cell_text(cell) for cell in headers)


def _sheet_fingerprint(rows: list[dict[str, Any]]) -> tuple[str, ...]:
    """What a sheet's lines say, for telling a copy of a sheet from a new one."""
    return tuple(str(row.get("description", "") or "").strip() for row in rows)


def _join_sheets(read: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[int], list[str]]:
    """Put several item sheets into one run of rows, a section per sheet.

    Each sheet opens with a section named after it, so the trade a line was
    priced under is still visible in the bill, and every row carries its sheet
    under ``_sheet`` for the messages about it. The sheets number their lines
    independently, so when any number occurs on two sheets every row is
    prefixed with its sheet's position (``2.1`` for line 1 of the second sheet)
    and the sheet's section carries that position; otherwise the numbers are
    the file's own and are kept as they are.
    """
    seen: set[str] = set()
    collide = False
    for sheet in read:
        ordinals = {str(row.get("ordinal", "") or "").strip() for row in sheet["rows"]} - {""}
        if ordinals & seen:
            collide = True
        seen |= ordinals
    rows: list[dict[str, Any]] = []
    numbers: list[int] = []
    sheets: list[str] = []
    for position, sheet in enumerate(read, start=1):
        section: dict[str, Any] = {"description": sheet["title"], "_sheet": sheet["title"]}
        if collide:
            section["ordinal"] = str(position)
        rows.append(section)
        numbers.append(sheet["header_row"])
        sheets.append(sheet["title"])
        for row, number in zip(sheet["rows"], sheet["row_numbers"], strict=True):
            ordinal = str(row.get("ordinal", "") or "").strip()
            joined = {**row, "_sheet": sheet["title"]}
            if collide and ordinal:
                joined["ordinal"] = f"{position}.{ordinal}"
            rows.append(joined)
            numbers.append(number)
            sheets.append(sheet["title"])
    return rows, numbers, sheets


def _parse_rows_from_excel(
    content_bytes: bytes,
    overrides: dict[int, str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read the item sheets of an .xlsx or .xls file into canonical-key dicts.

    Every item sheet is read, see :func:`_pick_item_sheets`. Returns
    ``(rows, import_metadata)``; metadata preserves the raw column ordering of
    the first item sheet so a later export can round-trip back to the user's
    original spreadsheet layout, ``row_numbers`` holds the sheet row each
    returned row came from and ``row_sheets`` its sheet, so a message about it
    names the row the user sees under a letterhead and past blank lines, on the
    sheet it is on. ``sheet_notes`` names every sheet that was not read and why.

    ``overrides`` is the user's column mapping, see :func:`parse_column_mapping`.
    It is laid over the first item sheet and every further one headed the same
    way; a sheet headed differently is read as before and named in
    ``mapping_notes``.
    """
    wb = open_workbook(content_bytes)
    if wb.active is None:
        raise ImporterParseError("Excel file has no worksheets")
    sheet_names = wb.sheetnames
    worksheets, notes = _pick_item_sheets(wb)

    read: list[dict[str, Any]] = []
    fingerprints: dict[tuple[str, ...], str] = {}
    mapped_header: tuple[str, ...] | None = None
    mapping_notes: list[dict[str, Any]] = []
    for worksheet in worksheets:
        sheet = _read_sheet_rows(worksheet)
        if sheet is None:
            continue
        if overrides is not None:
            texts = _header_texts(sheet["display_headers"])
            if mapped_header is None:
                mapped_header = texts
            if texts == mapped_header:
                # The two-row header the reader composed is found again only by
                # looking for it; a fallback row has to be named.
                row = None if sheet["display_header_row"] == sheet["header_row"] else sheet["display_header_row"]
                sheet = _read_sheet_rows(worksheet, header_row=row, overrides=overrides) or sheet
            else:
                mapping_notes.append({"sheet": sheet["title"], "reason": "different_header"})
        fingerprint = _sheet_fingerprint(sheet["rows"])
        if any(fingerprint) and fingerprint in fingerprints:
            # A copy of a sheet already read (a priced and an unpriced copy of
            # the same bill, "Költségvetés (2)") would import every line twice.
            notes.append({"sheet": sheet["title"], "reason": "duplicate", "of": fingerprints[fingerprint]})
            continue
        fingerprints.setdefault(fingerprint, sheet["title"])
        read.append(sheet)
    wb.close()

    if not read:
        raise ImporterParseError("Excel file is empty or has no header row")

    first = read[0]
    if len(read) == 1:
        rows, row_numbers = first["rows"], first["row_numbers"]
        row_sheets = [first["title"]] * len(rows)
    else:
        rows, row_numbers, row_sheets = _join_sheets(read)
    # One grouping for the whole workbook, in the language the positions are
    # read in: a trade sheet with no cell of its own to veto the grouping
    # follows the sheets that have one.
    language = header_language(first["headers"])
    rows = _fold_split_columns(rows, language)

    import_metadata = {
        "original_columns": [str(h) if h is not None else "" for h in first["display_headers"]],
        "header_row": first["display_header_row"],
        "column_mapping": _report_mapping(first["display_column_map"]),
        "column_mapping_applied": overrides is not None,
        "mapping_notes": mapping_notes,
        "header_language": language,
        "header_report": {**first["header_report"], "sheet": first["title"]},
        "sheet_names": sheet_names,
        "item_sheet": first["title"],
        "item_sheets": [sheet["title"] for sheet in read],
        "sheet_notes": notes,
        "total_rows": len(rows),
        "row_numbers": row_numbers,
        "row_sheets": row_sheets,
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
        "subtotal": ("összesen", "részösszeg", "nettó összesen", "összesen nettó"),
        "tax": ("áfa", "általános forgalmi adó"),
        "grand_total": (
            "mindösszesen",
            "végösszeg",
            "bruttó összesen",
            "összesen bruttó",
            "mindösszesen bruttó",
            "mindösszesen nettó",
        ),
        "recap": ("összesítő", "összesítés", "főösszesítő", "munkanem összesítő"),
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

# Languages that write the total word at the END of the line: Hungarian names
# the chapter first, "Irtás, föld- és sziklamunka összesen:". Kept to the
# languages that do it, because a trailing "sum" in English is a provisional
# sum, which is work, and matching it everywhere would drop that line.
_TRAILING_SUMMARY_LANGUAGES: tuple[str, ...] = ("hu",)

_TRAILING_SUMMARY_INDEX: dict[str, str] = {
    phrase: kind
    for phrase, kind in _build_summary_index(
        {language: _SUMMARY_WORDS_BY_LANGUAGE[language] for language in _TRAILING_SUMMARY_LANGUAGES}
    ).items()
    if kind != "recap"
}


def summary_label_kind(label: str) -> tuple[str, bool] | None:
    """Say whether a row label reads as a total, tax, grand-total or recap line.

    Args:
        label: The row's description cell.

    Returns:
        ``(kind, whole)`` where ``whole`` is True when the phrase is the entire
        label and False when it only starts it, or ends it in a language of
        :data:`_TRAILING_SUMMARY_LANGUAGES`; ``None`` when no phrase fits.
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
    for length in range(len(words) - 1, 0, -1):
        kind = _TRAILING_SUMMARY_INDEX.get(" ".join(words[-length:]))
        if kind is not None:
            return kind, False
    return None


def _amount_cell(value: Any, *, dot_thousands: bool = False, comma_thousands: bool = False) -> float:
    """A money cell read with the file's grouping; zero when it is blank or not a number."""
    parsed, _ = parse_numeric_cell(value, dot_thousands=dot_thousands, comma_thousands=comma_thousands)
    return parsed if parsed is not None else 0.0


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
    dot_thousands: bool = False,
    comma_thousands: bool = False,
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
        dot_thousands: The file's grouping, see :func:`_grouping_conventions`,
            for reading the amount a summary line reports.
        comma_thousands: Likewise, for a decimal-point market.

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

        amount = _amount_cell(row.get("total"), dot_thousands=dot_thousands, comma_thousands=comma_thousands)
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
                **({"sheet": row["_sheet"]} if row.get("_sheet") else {}),
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
        **({"sheet": report["sheet"]} if report.get("sheet") else {}),
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


def _split_metadata(
    row: dict[str, Any],
    language: str | None,
    *,
    dot_thousands: bool = False,
    comma_thousands: bool = False,
) -> dict[str, Any]:
    """The material and labour halves of a line, keyed for where they are read.

    Read with the file's grouping, the same reading the line's rate was folded
    with, so the halves add up to the rate stored beside them. They used to be
    read with no grouping at all: a Hungarian "12.500" folded into a rate of
    12 500 and was kept here as 12.5.
    """
    if not any(key in row for key in _SPLIT_COLUMNS):
        return {}

    def half(key: str) -> float:
        parsed, _ = parse_numeric_cell(row.get(key), dot_thousands=dot_thousands, comma_thousands=comma_thousands)
        return parsed if parsed is not None else 0.0

    halves = {key: half(key) for key in _SPLIT_COLUMNS}
    if language == "hu":
        return {
            "hu": {
                "profile": "flat",
                "material_unit_rate": halves["material_rate"],
                "fee_unit_rate": halves["labour_rate"],
                "material_total": halves["material_total"],
                "fee_total": halves["labour_total"],
            }
        }
    return {
        "rate_split": {
            "material_unit_rate": halves["material_rate"],
            "labour_unit_rate": halves["labour_rate"],
            "material_total": halves["material_total"],
            "labour_total": halves["labour_total"],
        }
    }


# Contingency lines, matched on :func:`normalise_label` at the start of the
# label. A bill writes its reserve as a line with a name and an amount and no
# unit, quantity or rate, "Tartalékkeret 5%", which is exactly the shape of a
# section heading, so it imported as an empty section and the reserve was
# lost from the total. Such a line is money the client budgets, so it comes in
# as a lump sum carrying its amount.
_CONTINGENCY_PHRASES: frozenset[str] = frozenset(
    normalise_label(phrase)
    for phrase in (
        # English
        "contingency",
        "contingencies",
        "contingency sum",
        "contingency allowance",
        # Hungarian
        "tartalékkeret",
        "tartalék",
        "előre nem látható költségek",
    )
)


def _contingency_amount(
    row: dict[str, Any], description: str, *, dot_thousands: bool = False, comma_thousands: bool = False
) -> float | None:
    """The amount of a contingency line written without a unit, quantity or rate.

    Returns ``None`` for any other row, and for a contingency line that is
    priced like work already or carries no amount. The amount is read with
    the file's grouping, like every other number of the line.
    """
    if str(row.get("unit", "") or "").strip():
        return None
    if not (_is_blank_cell(row.get("quantity")) and _is_blank_cell(row.get("unit_rate"))):
        return None
    words = normalise_label(description).split()
    if not any(" ".join(words[:length]) in _CONTINGENCY_PHRASES for length in range(1, len(words) + 1)):
        return None
    amount = _amount_cell(row.get("total"), dot_thousands=dot_thousands, comma_thousands=comma_thousands)
    return amount if amount > 0 else None


def _naming_the_sheet(
    kept_rows: list[tuple[int, dict[str, Any]]], result: ImportedBOQ
) -> Iterator[tuple[int, dict[str, Any]]]:
    """Yield the rows, then name the sheet on every issue each one raised.

    A row number alone is ambiguous in a workbook read across several sheets:
    row 12 exists on every one of them. The issues are tagged after the loop
    body has run, whichever way it left the row.
    """
    for row_idx, row in kept_rows:
        errors_before, warnings_before = len(result.errors), len(result.warnings)
        yield row_idx, row
        sheet = row.get("_sheet")
        if sheet:
            for issue in (*result.errors[errors_before:], *result.warnings[warnings_before:]):
                issue.setdefault("sheet", sheet)


def _grouping_conventions(rows: list[dict[str, Any]], header_language: str | None) -> tuple[bool, bool]:
    """``(dot_thousands, comma_thousands)`` for one file.

    The header's language proposes the convention, and the file's own
    numbers can veto it: one cell that can only be written with a decimal
    point switches dot grouping off, and one that can only be written with
    a decimal comma switches comma grouping off.
    """
    dot = header_language in DECIMAL_COMMA_LANGUAGES
    comma = header_language in DECIMAL_POINT_LANGUAGES
    if not (dot or comma):
        return False, False
    veto = _POINT_DECIMAL_SHAPE if dot else _COMMA_DECIMAL_SHAPE
    for row in rows:
        for column in _NUMERIC_COLUMNS:
            text = row.get(column)
            if isinstance(text, str) and veto.search(fold_width(text)):
                return False, False
    return dot, comma


def _comma_thousands_warnings(row: dict[str, Any], row_idx: int, ordinal: str) -> list[dict[str, Any]]:
    """One note per cell whose comma was read as a thousands separator."""
    notes: list[dict[str, Any]] = []
    for column in _NUMERIC_COLUMNS:
        text = row.get(column)
        if not comma_groups_thousands(text):
            continue
        read, _ = parse_numeric_cell(text, comma_thousands=True)
        plain, _ = parse_numeric_cell(text)
        if read is None or read == plain:
            continue
        notes.append(
            {
                "row": row_idx,
                "ordinal": ordinal,
                "severity": "info",
                "code": "comma_read_as_thousands",
                "column": column,
                "text": str(text).strip(),
                "value": read,
                "message": f"'{str(text).strip()}' was read as {read:g}: the comma separates thousands in this bill.",
            }
        )
    return notes


def _dot_thousands_warnings(row: dict[str, Any], row_idx: int, ordinal: str) -> list[dict[str, Any]]:
    """One note per cell whose dots were read as thousands separators.

    Only where that reading changed the number: "1.250.000" means the same
    either way and is not worth a line. The note carries the cell as typed
    and the number it became, so a reader who meant twelve and a half can see
    at once which cell to correct.
    """
    notes: list[dict[str, Any]] = []
    for column in _NUMERIC_COLUMNS:
        text = row.get(column)
        if not dot_groups_thousands(text):
            continue
        read, _ = parse_numeric_cell(text, dot_thousands=True)
        plain, _ = parse_numeric_cell(text)
        if read is None or read == plain:
            continue
        notes.append(
            {
                "row": row_idx,
                "ordinal": ordinal,
                "severity": "info",
                "code": "dot_read_as_thousands",
                "column": column,
                "text": str(text).strip(),
                "value": read,
                "message": f"'{str(text).strip()}' was read as {read:g}: the dot separates thousands in this bill.",
            }
        )
    return notes


def sheet_note_warning(note: dict[str, Any]) -> dict[str, Any]:
    """The import warning for a worksheet the reader did not read.

    Carries a code and the sheet's name so the import dialog words it in the
    reader's language; ``message`` is the English fallback.
    """
    reason = note["reason"]
    if reason == "hidden":
        because = "it is hidden"
    elif reason == "duplicate":
        because = f"it repeats the lines of sheet '{note.get('of', '')}'"
    else:
        because = "its header names no description with a quantity, unit or rate"
    warning = {
        "severity": "info",
        "code": "sheet_not_read",
        "sheet": note["sheet"],
        "reason": reason,
        "message": f"Sheet '{note['sheet']}' was not read: {because}.",
    }
    if note.get("of"):
        warning["of"] = note["of"]
    return warning


_IMPORT_MAX_QUANTITY = 1e9
_IMPORT_MAX_UNIT_RATE = 1e8


def _rows_to_positions(
    rows: list[dict[str, Any]],
    *,
    source: str = "excel_import",
    row_numbers: list[int] | None = None,
    header_language: str | None = None,
    sheet_notes: list[dict[str, Any]] | None = None,
    header: dict[str, Any] | None = None,
) -> ImportedBOQ:
    """Convert canonical rows into :class:`ImportedPosition` objects.

    Carries the sanity bounds + section-row + summary-row detection that
    the legacy inline parser used. Per-row errors are collected on the
    returned :class:`ImportedBOQ` rather than raised so the dispatcher
    can return them as a structured list.

    A line read from material and labour columns keeps the two halves in its
    metadata. A Hungarian bill keeps them under ``hu`` with the keys the
    workbook profile writes, which is where the Hungarian material and fee
    rule reads them; any other bill keeps them under ``rate_split``.

    A row read off one of several item sheets carries its sheet under
    ``_sheet``; every issue about it names that sheet, and ``sheet_notes``
    (the sheets the reader left out, see :func:`_pick_item_sheets`) become
    one warning each, so a workbook that was only partly read says so.

    ``header`` is the reader's :func:`header_report`. It is kept in the
    result's metadata, and when it names a column the bill cannot do without
    it becomes an error: rows read under a header that names no description
    or no quantity, unit or rate import as nothing, and used to do so with no
    error at all.
    """
    result = ImportedBOQ(source_format="csv-or-xlsx")
    if header is not None:
        result.metadata["header_report"] = header
        if header.get("missing"):
            result.errors.append(header_problem_error(header, header.get("sheet")))
    result.warnings.extend(sheet_note_warning(note) for note in sheet_notes or ())
    dot_thousands, comma_thousands = _grouping_conventions(rows, header_language)
    auto_ordinal = 1

    # Pre-compute a median unit rate across the file so we can warn on
    # any single position that's >10× above (likely a tampered export).
    rate_samples = sorted(
        v
        for v in (
            (
                parse_numeric_cell(r.get("unit_rate"), dot_thousands=dot_thousands, comma_thousands=comma_thousands)[0]
                or 0.0
            )
            for r in rows
        )
        if v > 0
    )
    median_rate = rate_samples[len(rate_samples) // 2] if rate_samples else 0.0

    kept_rows, summary_rows = partition_summary_rows(
        rows, row_numbers=row_numbers, dot_thousands=dot_thousands, comma_thousands=comma_thousands
    )
    result.skipped += len(summary_rows)
    result.warnings.extend(summary_row_warning(report) for report in summary_rows)
    if summary_rows:
        result.metadata["summary_rows"] = summary_rows

    # Numbers the file writes itself. A generated ordinal steps over them: a
    # bill that numbers its lines but not its chapter headings ("Ssz." blank
    # on the heading row) used to give the first heading "1" beside line 1,
    # and duplicate ordinals fail validation.
    explicit_ordinals = {fold_width(str(row.get("ordinal", ""))).strip() for _, row in kept_rows} - {""}

    for row_idx, row in _naming_the_sheet(kept_rows, result):
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

            # A number, a code or a unit typed full width ("１．２", "㎡") is
            # the same as its ASCII twin; see :func:`fold_width`.
            ordinal = fold_width(str(row.get("ordinal", ""))).strip()
            if not ordinal:
                while str(auto_ordinal) in explicit_ordinals:
                    auto_ordinal += 1
                ordinal = str(auto_ordinal)
            auto_ordinal += 1

            # Round-trip identity (GitHub #360): the dedicated "Position ID"
            # column an export stamped. Blank -> new row; a value belonging to
            # the target BOQ -> update in place (resolved downstream by the
            # diff against the BOQ's current ids).
            position_id = normalise_id(row.get("position_id"))

            unit_raw = fold_width(str(row.get("unit", ""))).strip()
            quantity_raw = row.get("quantity")
            unit_rate_raw = row.get("unit_rate")
            contingency = _contingency_amount(
                row, description, dot_thousands=dot_thousands, comma_thousands=comma_thousands
            )
            if contingency is not None:
                unit_raw, quantity_raw, unit_rate_raw = "lsum", 1.0, contingency
            quantity, q_err = parse_numeric_cell(
                quantity_raw, dot_thousands=dot_thousands, comma_thousands=comma_thousands
            )
            unit_rate, r_err = parse_numeric_cell(
                unit_rate_raw, dot_thousands=dot_thousands, comma_thousands=comma_thousands
            )
            if dot_thousands:
                result.warnings.extend(_dot_thousands_warnings(row, row_idx, ordinal))
            if comma_thousands:
                result.warnings.extend(_comma_thousands_warnings(row, row_idx, ordinal))
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
                            **({"import_sheet": row["_sheet"]} if row.get("_sheet") else {}),
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
            class_value = fold_width(str(row.get("classification", ""))).strip()
            classification = _infer_classification(class_value, description)
            if header_language == "hu" and "code" in classification:
                # The Hungarian rules read the item code from ``tetelrend``,
                # where the workbook profile writes it. A flat bill's code is
                # carried there too, so those rules judge the code the line
                # has rather than report it as having none.
                classification["tetelrend"] = classification["code"]

            metadata: dict[str, Any] = {"import_row_index": row_idx}
            if row.get("_sheet"):
                metadata["import_sheet"] = row["_sheet"]
            if contingency is not None:
                metadata["contingency"] = True
            split = _split_metadata(row, header_language, dot_thousands=dot_thousands, comma_thousands=comma_thousands)
            if split:
                metadata.update(split)

            result.positions.append(
                ImportedPosition(
                    description=description,
                    ordinal=ordinal,
                    unit=unit,
                    quantity=quantity,
                    unit_rate=unit_rate,
                    classification=classification,
                    source=source,
                    metadata=metadata,
                    position_id=position_id,
                )
            )

        except Exception as exc:  # noqa: BLE001 - caller surfaces row #
            result.errors.append({"row": row_idx, "ordinal": "", "error": str(exc)})
            logger.warning("Excel/CSV row %d error: %s", row_idx, exc)

    return result


class ExcelImporter:
    """Generic Excel (.xlsx, .xls) / CSV importer with NRM + MasterFormat heuristics."""

    format_id: ClassVar[str] = "excel"
    extensions: ClassVar[tuple[str, ...]] = (".xlsx", ".xls", ".csv")
    display_name: ClassVar[str] = "Excel / CSV BOQ"
    rule_packs: ClassVar[tuple[str, ...]] = ("boq_quality",)

    @classmethod
    def detect(cls, head_bytes: bytes, filename: str) -> bool:
        """Detect by magic bytes (xlsx zip, xls compound file, CSV text) + extension."""
        if not head_bytes:
            return False
        name = filename.lower()
        if not any(name.endswith(ext) for ext in cls.extensions):
            return False
        fmt = _detect_file_format(head_bytes[:4096])
        # Either workbook extension takes either workbook format. Excel opens
        # an .xlsx saved under .xls, and a password-protected .xlsx is a
        # compound file rather than a zip: claimed here, it is refused with
        # a message about the password instead of wandering off to the
        # model-assisted reader.
        if name.endswith((".xlsx", ".xls")):
            return fmt in ("xlsx", "xls")
        if name.endswith(".csv"):
            return fmt == "csv"
        return False

    @classmethod
    async def parse(
        cls,
        content: bytes,
        *,
        locale: str = "en",
        column_mapping: dict[int, str] | None = None,
    ) -> ImportedBOQ:
        """Parse an .xlsx, .xls or .csv BOQ into :class:`ImportedBOQ`.

        ``column_mapping`` is the user's choice of what each column holds, see
        :func:`parse_column_mapping`; the columns it does not name keep the
        importer's own reading.
        """
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
        if fmt in ("xlsx", "xls"):
            hungarian = parse_hungarian_workbook(content)
            if hungarian is not None and hungarian.positions:
                hungarian.source_format = fmt
                if column_mapping:
                    hungarian.warnings.append(column_mapping_warning("profile"))
                return hungarian

        import_meta: dict[str, Any] = {}
        try:
            if fmt in ("xlsx", "xls"):
                rows, import_meta = _parse_rows_from_excel(content, column_mapping)
                source_format = fmt
            elif fmt == "csv":
                rows, import_meta = _parse_csv(content, column_mapping)
                source_format = "csv"
            else:
                raise ImporterParseError(f"Unsupported spreadsheet format: detected {fmt!r}")
        except ImporterParseError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ImporterParseError(f"Could not parse spreadsheet: {exc}") from exc

        # A header that names no description or no quantity, unit or rate is
        # reported as a coded error with what it did and did not recognise,
        # which the import dialog words in the reader's language. Only a file
        # whose header is fine and holds no rows is refused outright.
        if not rows and not (import_meta.get("header_report") or {}).get("missing"):
            raise ImporterParseError("No data rows found. Check that the header row names the columns.")

        language = import_meta.get("header_language")
        result = _rows_to_positions(
            rows,
            row_numbers=import_meta.get("row_numbers"),
            header_language=language,
            sheet_notes=import_meta.get("sheet_notes"),
            header=import_meta.get("header_report"),
        )
        result.source_format = source_format
        for note in import_meta.get("mapping_notes", []):
            result.warnings.append(column_mapping_warning(note["reason"], note.get("sheet")))
        result.metadata = {
            **result.metadata,
            "original_columns": import_meta.get("original_columns", []),
            "column_mapping": import_meta.get("column_mapping", {}),
            "sheet_names": import_meta.get("sheet_names", []),
            "total_rows_seen": len(rows),
            "column_mapping_applied": bool(import_meta.get("column_mapping_applied")),
        }
        for key in ("header_language", "item_sheet", "item_sheets", "encoding", "delimiter", "header_row"):
            if import_meta.get(key):
                result.metadata[key] = import_meta[key]
        return result
