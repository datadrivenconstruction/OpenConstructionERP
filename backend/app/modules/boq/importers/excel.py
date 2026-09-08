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
from typing import Any, ClassVar, Literal

from app.core.file_signature import detect as detect_signature
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
        ),
        "description": ("description", "desc", "text"),
        "unit": ("unit",),
        "quantity": ("quantity", "qty"),
        "unit_rate": ("unit rate", "rate", "unitrate"),
        "total": ("total", "amount", "subtotal"),
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
        ),
    },
    "de": {
        "description": ("beschreibung", "leistung"),
        "unit": ("einheit", "me"),
        "quantity": ("menge",),
        "unit_rate": ("einheitspreis", "ep", "preis"),
        "total": ("gesamt", "gesamtpreis"),
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
    },
    "it": {
        "description": ("descrizione",),
        "unit": ("unità", "u"),
        "quantity": ("quantità", "quantita"),
        "unit_rate": ("prezzo",),
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


def _match_column(header: str) -> str | None:
    """Match a header string to a canonical column name using the alias map."""
    normalised = header.strip().lower()
    for canonical, aliases in _COLUMN_ALIASES.items():
        if normalised in aliases:
            return canonical
    return None


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
    user's original spreadsheet layout.
    """
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(content_bytes), read_only=True, data_only=True)
    ws = wb.active
    if ws is None:
        raise ImporterParseError("Excel file has no worksheets")

    sheet_names = wb.sheetnames

    rows_iter = ws.iter_rows(values_only=True)
    raw_headers = next(rows_iter, None)
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
    for raw_row in rows_iter:
        row: dict[str, Any] = {}
        for idx, val in enumerate(raw_row):
            canonical = column_map.get(idx)
            if canonical and val is not None:
                row[canonical] = val
        if row:
            rows.append(row)
    wb.close()

    import_metadata = {
        "original_columns": original_columns,
        "column_mapping": {str(k): v for k, v in column_map.items()},
        "sheet_names": sheet_names,
        "total_rows": len(rows),
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


_IMPORT_MAX_QUANTITY = 1e9
_IMPORT_MAX_UNIT_RATE = 1e8


def _rows_to_positions(
    rows: list[dict[str, Any]],
    *,
    source: str = "excel_import",
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

    for row_idx, row in enumerate(rows, start=2):
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

            # Soft warnings.
            if median_rate > 0 and unit_rate > median_rate * 10:
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
            raise ImporterParseError("No data rows found. Check that the first row contains column headers.")

        result = _rows_to_positions(rows)
        result.source_format = source_format
        result.metadata = {
            "original_columns": import_meta.get("original_columns", []),
            "column_mapping": import_meta.get("column_mapping", {}),
            "sheet_names": import_meta.get("sheet_names", []),
            "total_rows_seen": len(rows),
        }
        return result
