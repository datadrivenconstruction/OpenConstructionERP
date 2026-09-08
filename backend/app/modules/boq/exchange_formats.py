# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The catalogue of bill-of-quantities exchange formats, by market.

A quantity surveyor does not think in file formats, they think in the
document their market uses. In Germany that is a Leistungsverzeichnis and
it travels as GAEB DA XML; in Spain it is a presupuesto and it travels as
a BC3; in Hungary it is a költségvetés and it travels as a workbook whose
columns are in Hungarian. Asking that person to choose between "GAEB",
"BC3" and "Excel" is asking them to translate their own job into ours.

This module is the list they should be shown instead: one row per market
document, carrying the countries it belongs to so the row can fly their
flag, and carrying enough truth about what we can do with it that the row
never promises more than the code delivers.

Nothing here declares a capability
----------------------------------

The temptation with a table like this is to write ``import_support =
"native"`` next to a format and move on. That value would be a mirror of
the importer registry, and mirrors drift silently: the day a reader is
added or removed, the table still says what it said, and no test fails
because nothing compares them. This repository has paid for that lesson
more than once, most expensively where a standards picker listed a
standard the backend could not store, and the mismatch surfaced as a
value falling back to a default without a word to the user.

So a catalogue row names a ``reader`` and a ``writer`` by ``format_id``
and stops there. Whether that reader exists is answered by looking in
``REGISTERED_IMPORTERS``; whether that writer exists is answered by
looking in ``REGISTERED_EXPORTERS``. Delete an importer and the rows that
named it drop to "assisted" on their own.

The same applies one level deeper for the workbook rows. A row saying we
read a Turkish költségvetés equivalent is only true if the spreadsheet
importer knows the Turkish words for quantity and unit price. It knows
which languages it covers, and publishes that as
``SUPPORTED_HEADER_LANGUAGES``, so a workbook row is native only when its
own ``header_language`` is in that set. Teach the importer a language and
the row changes by itself; that is the whole point.

The three levels of support
---------------------------

``native``
    We read (or write) the format's own container, or we read a workbook
    whose column headings are in a language the importer knows. What
    comes back is the file's own structure, not a guess.

``assisted``
    We have no reader for this shape, but the file is one the guided
    import can attempt: it walks the sheet, proposes a column mapping and
    a set of positions, and a human confirms every one of them before
    anything is written. Useful, and not the same thing as support, which
    is why it has its own word.

``none``
    We cannot take this file at all today. Rows in this state are still
    listed. A surveyor in Vienna is better served by being told plainly
    that we do not read ÖNORM A 2063 yet, and that GAEB DA XML is the way
    in until we do, than by not finding their format on the page and
    concluding the product is not for them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from app.modules.boq.exporters import REGISTERED_EXPORTERS, exporter_for
from app.modules.boq.importers import REGISTERED_IMPORTERS
from app.modules.boq.importers.excel import SUPPORTED_HEADER_LANGUAGES

SupportLevel = Literal["native", "assisted", "none"]

#: Extensions the guided import can be pointed at. Anything tabular or
#: textual: it reads the sheet and proposes a mapping for a human to
#: confirm. A container it cannot open at all (a signed archive, a
#: database dump) is not on this list, and rows carrying only such
#: extensions correctly report "none" rather than a false hope.
_ASSISTABLE_EXTENSIONS: frozenset[str] = frozenset({".xlsx", ".xls", ".xlsm", ".csv", ".txt", ".xml", ".json", ".pdf"})


@dataclass(frozen=True, slots=True)
class ExchangeFormat:
    """One market document, and how this product handles it."""

    #: Stable identifier. Where a container format is both read and
    #: written, this is the same token the importer and the exporter use,
    #: so the three registries join on it.
    format_id: str
    #: The document's own name, in its own market's words, untranslated.
    #: A German user looks for "Leistungsverzeichnis", not for "German
    #: bill of quantities", and a translated catalogue would hide the one
    #: string they are scanning for. The interface translates the
    #: surrounding sentence, never this.
    name: str
    #: ISO 3166-1 alpha-2 codes, uppercase. Drives the flags on the row
    #: and the "my market first" ordering. Empty for the formats that
    #: belong to no single market.
    countries: tuple[str, ...]
    #: Lowercased, leading dot. First entry is what an export of this
    #: format is named.
    extensions: tuple[str, ...]
    #: One sentence of English, shown as the fallback when the interface
    #: has no translation for this row yet.
    summary: str
    #: ``format_id`` of the importer that reads this, if any.
    reader: str | None = None
    #: ``format_id`` of the exporter that writes this, if any.
    writer: str | None = None
    #: Set for rows that are a spreadsheet in a particular market's
    #: language rather than a container of their own. Reading one depends
    #: on the spreadsheet importer knowing that language's column names.
    header_language: str | None = None
    #: The published standard behind the row, where there is one. Empty
    #: where the document is a market convention rather than a standard,
    #: which is the honest answer for most workbook rows.
    standard: str = ""
    #: Validation rule packs this document's market expects. Unioned with
    #: the project's own configuration by the import dispatcher.
    rule_packs: tuple[str, ...] = ()
    #: Markets where this is the everyday document rather than merely a
    #: format that circulates there. Subset of ``countries``; empty means
    #: "wherever it is the best we can read", which is the ordinary case.
    #:
    #: It exists because being listed for a market and being that market's
    #: paperwork are different claims, and the default has to answer the
    #: second one. BC3 files reach Mexico and a Mexican user should find
    #: BC3 on this page, but the document a Mexican unit-price contract is
    #: measured against is a catálogo de conceptos, and opening on BC3
    #: would tell them we had misunderstood their job. Without this field
    #: the default is decided by catalogue order, which puts every
    #: interchange container ahead of every workbook, and that ordering is
    #: right for Germany and wrong for most of Latin America.
    primary_for: tuple[str, ...] = ()


# ── The catalogue ──────────────────────────────────────────────────────
#
# Order is meaningful twice over. It is the order a caller that does not
# sort will show, and it decides which row a country defaults to: the
# first row that lists the country and can actually be read wins. So the
# container formats come first, because where a market has a real
# interchange file we would rather hand them that than a spreadsheet;
# then the market workbooks; then the formats that belong to everybody.

_CONTAINER_FORMATS: tuple[ExchangeFormat, ...] = (
    ExchangeFormat(
        format_id="gaeb_xml",
        name="GAEB DA XML 3.3",
        countries=("DE", "AT", "CH", "LU"),
        extensions=(".x83", ".x81", ".x82", ".x84", ".x86", ".xml"),
        summary="The DACH interchange for a bill of quantities, one file per tender phase.",
        reader="gaeb_xml",
        writer="gaeb_xml",
        standard="GAEB DA XML 3.3",
        rule_packs=("gaeb",),
    ),
    ExchangeFormat(
        format_id="bc3",
        name="FIEBDC-3 (BC3)",
        countries=("ES", "MX", "AR", "CL", "CO", "PE", "EC", "UY", "CR", "PA", "DO"),
        extensions=(".bc3",),
        summary="Spain's construction database interchange, and the common carrier across much of Latin America.",
        reader="bc3",
        writer="bc3",
        standard="FIEBDC-3",
        rule_packs=("bc3",),
        primary_for=("ES",),
    ),
    ExchangeFormat(
        format_id="oenorm_a2063",
        name="ÖNORM A 2063",
        countries=("AT",),
        extensions=(".onlv", ".xml"),
        summary="Austria's own bill of quantities interchange, used alongside GAEB on public work.",
        standard="ÖNORM A 2063",
        rule_packs=("onorm",),
    ),
    ExchangeFormat(
        format_id="arps",
        name="АРПС 1.10",
        countries=("RU", "KZ", "BY"),
        extensions=(".arp", ".xml"),
        summary="The open interchange for Russian estimates, carrying norm codes and the resource breakdown under each rate.",
        standard="АРПС 1.10",
        rule_packs=("gesn",),
    ),
    ExchangeFormat(
        format_id="gbt50500",
        name="GB/T 50500",
        countries=("CN",),
        extensions=(".xml", ".xlsx"),
        summary="China's bill of quantities valuation standard, which fixes what a priced item has to carry.",
        standard="GB/T 50500",
        rule_packs=("gbt50500",),
    ),
)

_WORKBOOK_FORMATS: tuple[ExchangeFormat, ...] = (
    ExchangeFormat(
        format_id="de_leistungsverzeichnis",
        name="Leistungsverzeichnis",
        countries=("DE", "AT", "CH", "LU"),
        extensions=(".xlsx", ".csv"),
        summary="The German priced schedule as a workbook, for the exchanges that never became a GAEB file.",
        reader="excel",
        writer="excel",
        header_language="de",
    ),
    ExchangeFormat(
        format_id="gb_boq_nrm",
        name="Bill of quantities (NRM)",
        countries=("GB", "IE", "NG", "KE", "GH", "HK", "SG", "MY"),
        extensions=(".xlsx", ".csv"),
        summary="The measured bill as it is exchanged across the NRM markets, priced or unpriced.",
        reader="excel",
        writer="excel",
        header_language="en",
        standard="RICS NRM",
        rule_packs=("nrm",),
    ),
    ExchangeFormat(
        format_id="us_schedule_of_values",
        name="Schedule of values",
        countries=("US", "CA"),
        extensions=(".xlsx", ".csv"),
        summary="The North American priced breakdown, divided by MasterFormat or by UniFormat element.",
        reader="excel",
        writer="excel",
        header_language="en",
        standard="CSI MasterFormat",
        rule_packs=("masterformat",),
    ),
    ExchangeFormat(
        format_id="fr_dpgf",
        name="DPGF",
        countries=("FR", "BE", "LU", "MA", "DZ", "TN", "CI", "SN"),
        extensions=(".xlsx", ".csv"),
        summary="The Décomposition du Prix Global et Forfaitaire, the priced breakdown behind a French lump sum.",
        reader="excel",
        writer="excel",
        header_language="fr",
        rule_packs=("dpgf",),
    ),
    ExchangeFormat(
        format_id="es_presupuesto",
        name="Presupuesto",
        countries=("ES", "CL", "CO", "PE", "AR", "UY", "EC"),
        extensions=(".xlsx", ".csv"),
        summary="The Spanish-language priced estimate as a workbook, where a BC3 was never issued.",
        reader="excel",
        writer="excel",
        header_language="es",
        primary_for=("CL", "CO", "PE", "AR", "UY", "EC"),
    ),
    ExchangeFormat(
        format_id="mx_catalogo_conceptos",
        name="Catálogo de conceptos",
        countries=("MX",),
        extensions=(".xlsx", ".csv"),
        summary="Mexico's schedule of priced concepts, the document a unit-price contract is measured against.",
        reader="excel",
        writer="excel",
        header_language="es",
        primary_for=("MX",),
    ),
    ExchangeFormat(
        format_id="br_orcamento",
        name="Orçamento",
        countries=("BR", "PT", "AO", "MZ"),
        extensions=(".xlsx", ".csv"),
        summary="The Portuguese-language priced estimate, commonly built on a public reference cost base.",
        reader="excel",
        writer="excel",
        header_language="pt",
        rule_packs=("sinapi",),
    ),
    ExchangeFormat(
        format_id="it_computo_metrico",
        name="Computo metrico estimativo",
        countries=("IT", "SM", "CH"),
        extensions=(".xlsx", ".csv"),
        summary="Italy's measured and priced schedule, the estimate that accompanies a tender.",
        reader="excel",
        writer="excel",
        header_language="it",
    ),
    ExchangeFormat(
        format_id="pl_kosztorys",
        name="Kosztorys",
        countries=("PL",),
        extensions=(".xlsx", ".csv"),
        summary="The Polish estimate workbook, priced per item against a norm catalogue.",
        reader="excel",
        writer="excel",
        header_language="pl",
    ),
    ExchangeFormat(
        format_id="cz_rozpocet",
        name="Rozpočet",
        countries=("CZ", "SK"),
        extensions=(".xlsx", ".csv"),
        summary="The Czech and Slovak priced estimate workbook.",
        reader="excel",
        writer="excel",
        header_language="cs",
    ),
    ExchangeFormat(
        format_id="hu_koltsegvetes",
        name="Költségvetés",
        countries=("HU",),
        extensions=(".xlsx", ".xls"),
        summary="The Hungarian estimate workbook, read through its own column profile rather than the generic one.",
        reader="excel",
        writer="excel",
        header_language="hu",
    ),
    ExchangeFormat(
        format_id="ru_smeta",
        name="Смета",
        countries=("RU", "BY", "KZ", "UZ", "KG", "AM", "AZ", "MD", "TJ"),
        extensions=(".xlsx", ".csv"),
        summary="The Russian-language estimate workbook, priced against a state norm base.",
        reader="excel",
        writer="excel",
        header_language="ru",
        rule_packs=("gesn",),
    ),
    ExchangeFormat(
        format_id="ua_koshtorys",
        name="Кошторис",
        countries=("UA",),
        extensions=(".xlsx", ".csv"),
        summary="The Ukrainian estimate workbook, priced against the national norm base.",
        reader="excel",
        writer="excel",
        header_language="uk",
    ),
    ExchangeFormat(
        format_id="tr_birim_fiyat",
        name="Birim fiyat cetveli",
        countries=("TR", "CY"),
        extensions=(".xlsx", ".csv"),
        summary="Turkey's unit price schedule, priced against the published public works rates.",
        reader="excel",
        writer="excel",
        header_language="tr",
        rule_packs=("birimfiyat",),
    ),
    ExchangeFormat(
        format_id="nl_begroting",
        name="Begroting",
        countries=("NL", "BE"),
        extensions=(".xlsx", ".csv"),
        summary="The Dutch priced estimate workbook.",
        reader="excel",
        writer="excel",
        header_language="nl",
    ),
    ExchangeFormat(
        format_id="se_mangdforteckning",
        name="Mängdförteckning",
        countries=("SE",),
        extensions=(".xlsx", ".csv"),
        summary="Sweden's measured schedule of quantities.",
        reader="excel",
        writer="excel",
        header_language="sv",
    ),
    ExchangeFormat(
        format_id="no_mengdebeskrivelse",
        name="Mengdebeskrivelse",
        countries=("NO",),
        extensions=(".xlsx", ".csv"),
        summary="Norway's measured description of quantities.",
        reader="excel",
        writer="excel",
        header_language="no",
    ),
    ExchangeFormat(
        format_id="dk_tilbudsliste",
        name="Tilbudsliste",
        countries=("DK",),
        extensions=(".xlsx", ".csv"),
        summary="Denmark's tender schedule, the list a bidder prices.",
        reader="excel",
        writer="excel",
        header_language="da",
    ),
    ExchangeFormat(
        format_id="fi_maaraluettelo",
        name="Määräluettelo",
        countries=("FI",),
        extensions=(".xlsx", ".csv"),
        summary="Finland's schedule of measured quantities.",
        reader="excel",
        writer="excel",
        header_language="fi",
    ),
    ExchangeFormat(
        format_id="ro_deviz",
        name="Deviz",
        countries=("RO", "MD"),
        extensions=(".xlsx", ".csv"),
        summary="The Romanian priced estimate workbook.",
        reader="excel",
        writer="excel",
        header_language="ro",
    ),
    ExchangeFormat(
        format_id="bg_smetna_dokumentaciya",
        name="Количествено-стойностна сметка",
        countries=("BG",),
        extensions=(".xlsx", ".csv"),
        summary="Bulgaria's quantity and value schedule.",
        reader="excel",
        writer="excel",
        header_language="bg",
    ),
    ExchangeFormat(
        format_id="gr_proypologismos",
        name="Προϋπολογισμός",
        countries=("GR", "CY"),
        extensions=(".xlsx", ".csv"),
        summary="The Greek priced estimate workbook.",
        reader="excel",
        writer="excel",
        header_language="el",
    ),
    ExchangeFormat(
        format_id="in_schedule_of_rates",
        name="Schedule of rates",
        countries=("IN", "BD", "LK", "NP"),
        extensions=(".xlsx", ".csv"),
        summary="The South Asian priced schedule, measured against a published public works rate book.",
        reader="excel",
        writer="excel",
        header_language="en",
        rule_packs=("cpwd",),
    ),
    ExchangeFormat(
        format_id="au_boq",
        name="Bill of quantities (ANZ)",
        countries=("AU", "NZ"),
        extensions=(".xlsx", ".csv"),
        summary="The Australian and New Zealand measured bill.",
        reader="excel",
        writer="excel",
        header_language="en",
    ),
    ExchangeFormat(
        format_id="za_boq",
        name="Bill of quantities (SA)",
        countries=("ZA", "NA", "BW"),
        extensions=(".xlsx", ".csv"),
        summary="The Southern African measured bill, priced under the standard system of measuring building work.",
        reader="excel",
        writer="excel",
        header_language="en",
    ),
    ExchangeFormat(
        format_id="gulf_boq",
        name="Bill of quantities (Gulf)",
        countries=("SA", "AE", "QA", "KW", "BH", "OM"),
        extensions=(".xlsx", ".csv"),
        summary="The Gulf measured bill, priced under the international principles of measurement.",
        reader="excel",
        writer="excel",
        header_language="en",
    ),
    ExchangeFormat(
        format_id="jp_sekisan",
        name="積算内訳書",
        countries=("JP",),
        extensions=(".xlsx", ".csv"),
        summary="Japan's itemised cost breakdown.",
        reader="excel",
        writer="excel",
        header_language="ja",
        rule_packs=("sekisan",),
    ),
    ExchangeFormat(
        format_id="kr_naeyeokseo",
        name="내역서",
        countries=("KR",),
        extensions=(".xlsx", ".csv"),
        summary="Korea's itemised statement of quantities and prices.",
        reader="excel",
        writer="excel",
        header_language="ko",
    ),
    ExchangeFormat(
        format_id="cn_gongchengliang_qingdan",
        name="工程量清单",
        countries=("CN",),
        extensions=(".xlsx", ".csv"),
        summary="China's bill of quantities as a workbook, the everyday carrier beside the standard.",
        reader="excel",
        writer="excel",
        header_language="zh",
        rule_packs=("gbt50500",),
    ),
    ExchangeFormat(
        format_id="id_rab",
        name="Rencana anggaran biaya",
        countries=("ID",),
        extensions=(".xlsx", ".csv"),
        summary="Indonesia's cost budget plan.",
        reader="excel",
        writer="excel",
        header_language="id",
    ),
    ExchangeFormat(
        format_id="vn_du_toan",
        name="Dự toán",
        countries=("VN",),
        extensions=(".xlsx", ".csv"),
        summary="Vietnam's priced estimate workbook.",
        reader="excel",
        writer="excel",
        header_language="vi",
    ),
    ExchangeFormat(
        format_id="il_kitvei_kamuyot",
        name="כתב כמויות",
        countries=("IL",),
        extensions=(".xlsx", ".csv"),
        summary="Israel's bill of quantities workbook.",
        reader="excel",
        writer="excel",
        header_language="he",
    ),
)

_UNIVERSAL_FORMATS: tuple[ExchangeFormat, ...] = (
    ExchangeFormat(
        format_id="excel",
        name="Spreadsheet workbook",
        countries=(),
        extensions=(".xlsx", ".csv"),
        summary="Any workbook with a row per item. Belongs to no market, which is why it is last and never a country's default.",
        reader="excel",
        writer="excel",
    ),
    ExchangeFormat(
        format_id="csv",
        name="Delimited text (CSV)",
        countries=(),
        extensions=(".csv",),
        summary="A plain text table, for the systems that will take nothing else.",
        reader="excel",
        writer="csv",
    ),
    ExchangeFormat(
        format_id="pdf",
        name="PDF bill of quantities",
        countries=(),
        extensions=(".pdf",),
        summary="A typeset bill for issue and signature. Written, not read: a PDF upload goes to the guided import.",
        writer="pdf",
    ),
)

EXCHANGE_FORMATS: tuple[ExchangeFormat, ...] = _CONTAINER_FORMATS + _WORKBOOK_FORMATS + _UNIVERSAL_FORMATS


# ── Computed capability ────────────────────────────────────────────────


def _reader_ids() -> frozenset[str]:
    return frozenset(importer.format_id for importer in REGISTERED_IMPORTERS)


def _writer_ids() -> frozenset[str]:
    return frozenset(exporter.format_id for exporter in REGISTERED_EXPORTERS)


def import_support(fmt: ExchangeFormat, *, readers: frozenset[str] | None = None) -> SupportLevel:
    """How well we read ``fmt`` right now.

    Reads the importer registry rather than a stored answer, so removing
    an importer downgrades every row that named it without anybody having
    to remember this file exists.
    """
    known = _reader_ids() if readers is None else readers
    if fmt.reader in known:
        # A workbook row is only as good as the importer's vocabulary. If
        # it does not know the market's words for quantity and unit rate,
        # the file still opens, but the columns land by guesswork, and
        # that is the guided path, not the native one.
        if fmt.header_language is not None and fmt.header_language not in SUPPORTED_HEADER_LANGUAGES:
            return "assisted"
        return "native"
    if any(ext in _ASSISTABLE_EXTENSIONS for ext in fmt.extensions):
        return "assisted"
    return "none"


def export_support(fmt: ExchangeFormat, *, writers: frozenset[str] | None = None) -> SupportLevel:
    """How well we write ``fmt`` right now."""
    known = _writer_ids() if writers is None else writers
    return "native" if fmt.writer in known else "none"


def format_by_id(format_id: str) -> ExchangeFormat | None:
    """Look up one catalogue row."""
    for fmt in EXCHANGE_FORMATS:
        if fmt.format_id == format_id:
            return fmt
    return None


def formats_for_country(country: str) -> tuple[ExchangeFormat, ...]:
    """Every row that belongs to ``country``, catalogue order preserved."""
    code = (country or "").strip().upper()
    if not code:
        return ()
    return tuple(fmt for fmt in EXCHANGE_FORMATS if code in fmt.countries)


def default_format_for_country(country: str) -> str | None:
    """The row a user in ``country`` should land on.

    Their market's own document, and among their market's documents the
    one we can actually read. A surveyor in Vienna is offered GAEB rather
    than ÖNORM A 2063 not because GAEB is the better answer for Austria
    but because it is the answer that works today; the ÖNORM row is still
    on the page, saying so.

    Returns ``None`` for a country the catalogue does not cover, and the
    caller falls back to the spreadsheet row, which belongs to everybody.
    """
    rows = formats_for_country(country)
    if not rows:
        return None
    code = country.strip().upper()
    readers = _reader_ids()

    # A row that claims this market as its own wins, provided we can read
    # it. Claiming a market we cannot read for would be the one way this
    # field could make the answer worse than catalogue order.
    for fmt in rows:
        if code in fmt.primary_for and import_support(fmt, readers=readers) == "native":
            return fmt.format_id
    for fmt in rows:
        if import_support(fmt, readers=readers) == "native":
            return fmt.format_id
    return rows[0].format_id


def describe_formats() -> list[dict[str, Any]]:
    """The catalogue as the interface needs it, capability resolved once.

    The registries are read a single time here rather than once per row.
    They are cheap to read, but the two calls also have to agree with
    each other across the whole response: a caller comparing two rows in
    the same payload should not be able to catch us mid-registration.
    """
    readers = _reader_ids()
    writers = _writer_ids()
    described: list[dict[str, Any]] = []
    for fmt in EXCHANGE_FORMATS:
        exporter = exporter_for(fmt.writer) if fmt.writer else None
        described.append(
            {
                "format_id": fmt.format_id,
                "name": fmt.name,
                "countries": list(fmt.countries),
                "extensions": list(fmt.extensions),
                "summary": fmt.summary,
                "standard": fmt.standard,
                "rule_packs": list(fmt.rule_packs),
                "header_language": fmt.header_language,
                "import_support": import_support(fmt, readers=readers),
                "export_support": export_support(fmt, writers=writers),
                # Where to actually fetch this format, and what the file
                # should be called. Sent rather than left to the client so
                # the route table has one home. A client that built these
                # itself would be the third copy of the same five paths,
                # and the copy nobody edits when a route moves.
                "export_route": exporter.route if exporter else None,
                "export_extension": exporter.extension if exporter else None,
                "export_media_type": exporter.media_type if exporter else None,
            }
        )
    return described


# ── API shape ──────────────────────────────────────────────────────────
#
# These live here rather than in ``schemas.py`` because they are the
# catalogue's own shape and have no other caller. Keeping them next to
# the table means adding a column to one is a single-file change, which
# is the difference between a field being added everywhere it belongs and
# a field being added in two of the three places it belongs.


class ExchangeFormatInfo(BaseModel):
    """One catalogue row, capability already resolved."""

    format_id: str
    name: str
    countries: list[str]
    extensions: list[str]
    summary: str
    standard: str
    rule_packs: list[str]
    header_language: str | None
    import_support: SupportLevel
    export_support: SupportLevel
    #: Path under ``/boqs/{boq_id}/`` that serves an export of this
    #: format, or ``None`` when we cannot write it.
    export_route: str | None = None
    export_extension: str | None = None
    export_media_type: str | None = None


class ExchangeCatalogue(BaseModel):
    """The whole catalogue, plus where a given reader should start."""

    formats: list[ExchangeFormatInfo]
    #: Echo of the country that was asked about, normalised, or ``None``
    #: when the caller asked about no country in particular.
    country: str | None = None
    #: The row that country should land on. ``None`` when the catalogue
    #: does not cover the country; the caller then falls back to the
    #: spreadsheet row rather than to nothing.
    default_format_id: str | None = None
    #: Languages the spreadsheet importer knows column headings in.
    #: Published so a client can explain why a workbook row is guided
    #: rather than native without having to guess at the reason.
    header_languages: list[str] = []


def build_catalogue(country: str | None = None) -> ExchangeCatalogue:
    """Assemble the catalogue response for one reader."""
    code = (country or "").strip().upper() or None
    return ExchangeCatalogue(
        formats=[ExchangeFormatInfo(**row) for row in describe_formats()],
        country=code,
        default_format_id=default_format_for_country(code) if code else None,
        header_languages=sorted(SUPPORTED_HEADER_LANGUAGES),
    )


__all__ = [
    "EXCHANGE_FORMATS",
    "ExchangeCatalogue",
    "ExchangeFormat",
    "ExchangeFormatInfo",
    "SupportLevel",
    "build_catalogue",
    "default_format_for_country",
    "describe_formats",
    "export_support",
    "format_by_id",
    "formats_for_country",
    "import_support",
]
