# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What a drawing page's title block, and the file it came in, say about the sheet.

The register used to read its revision with one pattern that had no word
boundary in front of the label and took the first match anywhere on the page.
An Italian drawing that mentions a sliding door ("porta scorrevole") anywhere
above its title block was registered at revision "ole", because "scorREVole"
carries the label. The same pattern read "Revisione: 02" as "e" and "Rev. n. 3"
as "n". The negatives below are the words that produced those values; the
positives are the title-block spellings a European drawing set actually uses.

Sheet numbers, titles and dates were read only from English labels, so an
Italian set registered every page without a number, which in turn meant no page
of it could ever join a revision stack.
"""

from __future__ import annotations

import pytest

from app.modules.documents.service import detect_discipline_from_sheet_number, detect_sheet_info
from app.modules.documents.sheet_fields import sheet_chain_key

# ── Revision ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "Pianta piano terra\nPorta scorrevole in vetro\nScala 1:100",
        "Porta girevole ingresso\nScala 1:50",
        "Solaio previsto in laterocemento",
        "CHECKED BY: AB\nREVIEWED BY: CD",
        "Sole Console parole tavole",
        "INDEX OF DRAWINGS",
        "Indice di affollamento 0,4 persone/m2",
        "INDICE\n1. Premessa",
        "Stand der Technik",
        "Stand: 12.03.2025",
    ],
)
def test_a_word_that_only_contains_a_revision_label_is_not_a_revision(text: str) -> None:
    """Prose and neighbouring labels never produce a revision."""
    assert detect_sheet_info(text)["revision"] is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Revisione: 02", "02"),
        ("REVISIONE B", "B"),
        ("Rev. n. 3", "3"),
        ("REV.1", "1"),
        ("Indice B", "B"),
        ("Indice rev. C", "C"),
        ("IND. 2", "2"),
        ("Revisión: P02", "P02"),
        ("Revisão 1A", "1A"),
        ("Révision C01", "C01"),
        ("Änderungsindex: c", None),
        ("Änderungsindex: C", "C"),
        ("Index B", "B"),
        ("Stand: A", "A"),
        ("REV A", "A"),
        ("REVISION NO. 4", "4"),
    ],
)
def test_title_block_revision_labels_in_every_market_read_the_bounded_value(text: str, expected: str | None) -> None:
    """Each label reads the value next to it and nothing longer."""
    assert detect_sheet_info(text)["revision"] == expected


def test_the_sliding_door_note_above_the_title_block_does_not_win() -> None:
    """The case the tester reported: the note used to be read as revision "ole"."""
    text = "Pianta piano terra\nPorta scorrevole in vetro\nScala 1:100\nRev. 02"
    assert detect_sheet_info(text)["revision"] == "02"


def test_a_revision_in_the_title_block_region_beats_one_elsewhere_on_the_page() -> None:
    """When the bottom-right region is known, its revision is the sheet's revision."""
    page = "Rev. 01 come da verbale\nPianta\nRev. 03"
    assert detect_sheet_info(page, title_block_text="TAVOLA 3\nRev. 03")["revision"] == "03"
    assert detect_sheet_info("Rev. 01\nPianta", title_block_text="Rev. 02")["revision"] == "02"


# ── Italian title block ───────────────────────────────────────────────────


def test_an_italian_title_block_reads_every_field() -> None:
    """Number, subject, date, scale and revision off one cartiglio."""
    text = (
        "COMUNE DI MILANO\n"
        "Progetto esecutivo\n"
        "TAVOLA 3\n"
        "Oggetto: Pianta piano terra\n"
        "Data 12/03/2025\n"
        "Scala 1:100\n"
        "Rev. 02\n"
    )
    info = detect_sheet_info(text)
    assert info["sheet_number"] == "3"
    assert info["sheet_title"] == "Pianta piano terra"
    assert info["revision_date"] == "2025-03-12"
    assert info["scale"] == "1:100"
    assert info["revision"] == "02"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("TAVOLA: ARC-01", "ARC-01"),
        ("Tav. n. 7", "7"),
        ("TAV. A.03", "A.03"),
        ("ELABORATO STR-04", "STR-04"),
        ("Blatt 5", "5"),
        ("Plan-Nr.: 123-A", "123-A"),
        ("Plano nº 12", "12"),
        ("Planche 4", "4"),
        ("TAV_01 Pianta", "TAV_01"),
        ("ARC_PT_01 Pianta", "ARC_PT_01"),
        ("SHEET NO: A-301", "A-301"),
        ("Some text A-201 more text", "A-201"),
        ("Drawing A101", "A101"),
    ],
)
def test_sheet_number_labels_and_codes(text: str, expected: str) -> None:
    """Labelled numbers in five languages, and the codes a file name carries."""
    assert detect_sheet_info(text)["sheet_number"] == expected


@pytest.mark.parametrize(
    "text",
    [
        "Strada Provinciale 12",
        "UNI EN 1992",
        "NTC 2018",
        "D.M. 17/01/2018",
        "D.Lgs. 81/2008",
        "Via Roma 12",
        "ELENCO TAVOLE",
        "Tavole allegate al progetto",
    ],
)
def test_references_that_merely_carry_digits_are_not_sheet_numbers(text: str) -> None:
    """Norm and address references on an Italian sheet are not its number."""
    assert detect_sheet_info(text)["sheet_number"] is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("vedi Tav. ARC-05 per i dettagli\nPianta\nTAVOLA: ARC-03", "ARC-03"),
        ("siehe Plan-Nr. 12\nGrundriss\nPlan-Nr.: 7", "7"),
        ("ver plano 5\nPlanta baja\nPlano nº 2", "2"),
        ("See A-501 for details\nDrawing A-101", "A-101"),
        ("cfr. Tav. 4", None),
    ],
)
def test_a_drawing_the_sheet_points_at_is_not_its_number(text: str, expected: str | None) -> None:
    """A cross-reference in a note never becomes the sheet's own number."""
    assert detect_sheet_info(text)["sheet_number"] == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Titolo: Prospetti", "Prospetti"),
        ("Contenuto: Sezioni", "Sezioni"),
        ("Planinhalt: Grundriss EG", "Grundriss EG"),
        ("Titel: Schnitt A-A", "Schnitt A-A"),
        ("Titre : Plan du rez-de-chaussée", "Plan du rez-de-chaussée"),
        ("Título: Planta baja", "Planta baja"),
        ("Oggetto\nPianta copertura", "Pianta copertura"),
        ("SUBTITLE: nothing", None),
        ("a titolo di esempio", None),
    ],
)
def test_title_labels(text: str, expected: str | None) -> None:
    """Title labels in each market's wording, and a label alone on its line."""
    assert detect_sheet_info(text)["sheet_title"] == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Data: 12/03/2025", "2025-03-12"),
        ("Datum: 12.03.2025", "2025-03-12"),
        ("Fecha: 5-3-2025", "2025-03-05"),
        ("DATE: 2025-01-15", "2025-01-15"),
        ("DATE: 25/12/2025", "2025-12-25"),
        ("DATE: 12/25/2025", "2025-12-25"),
        ("DATE: 03/04/2025", None),
        ("Data: 31/02/2025", None),
        ("Data emissione: 01/10/25", "2025-10-01"),
    ],
)
def test_dates_are_stored_iso_and_an_ambiguous_one_is_left_unset(text: str, expected: str | None) -> None:
    """Day-first labels read day first; an English label that could be either is not guessed."""
    assert detect_sheet_info(text)["revision_date"] == expected


# ── File name fallback ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("filename", "number", "revision"),
    [
        ("TAV_01_Pianta piano terra_rev02.pdf", "TAV_01", "02"),
        ("ARC_PT_01_R03.pdf", "ARC_PT_01", "03"),
        ("A-101 Rev B.pdf", "A-101", "B"),
        ("S-200-REV-C.pdf", "S-200", "C"),
        ("C:\\progetti\\STR_02_rev1.pdf", "STR_02", "1"),
        ("Pianta piano terra.pdf", None, None),
    ],
)
def test_the_file_name_fills_in_what_the_page_does_not_say(
    filename: str, number: str | None, revision: str | None
) -> None:
    """A page with no title block text takes number and revision from its file name."""
    info = detect_sheet_info("", filename=filename)
    assert info["sheet_number"] == number
    assert info["revision"] == revision


@pytest.mark.parametrize(
    ("filename", "number", "revision", "title"),
    [
        ("ARC PT 01 R03 Pianta.pdf", "ARC PT 01", "03", "Pianta"),
        ("STR FN 02 rev02 Fondazioni.pdf", "STR FN 02", "02", "Fondazioni"),
        ("IMP EL 12 Schema quadro generale.pdf", "IMP EL 12", None, "Schema quadro generale"),
        ("TAV 07 Prospetto nord.pdf", "TAV 07", None, "Prospetto nord"),
        ("A 101 Grundriss EG.pdf", "A 101", None, "Grundriss EG"),
        ("GR OG 03 Grundriss 1. Obergeschoss.pdf", "GR OG 03", None, "Grundriss 1. Obergeschoss"),
        ("ELT UG 004 Beleuchtung R1.pdf", "ELT UG 004", "1", "Beleuchtung"),
        ("TWP 05 Schnitt A-A.pdf", "TWP 05", None, "Schnitt A-A"),
    ],
)
def test_a_space_separated_code_at_the_start_of_the_name_is_the_number(
    filename: str, number: str, revision: str | None, title: str
) -> None:
    """Offices name files "ARC PT 01 R03 Pianta.pdf": upper-case letter groups, then the digits."""
    info = detect_sheet_info("", filename=filename)
    assert (info["sheet_number"], info["revision"], info["sheet_title"]) == (number, revision, title)


@pytest.mark.parametrize(
    "filename",
    [
        # Ordinary title words, capitalised or not, are not a code.
        "Pianta piano terra 1.pdf",
        "PIANTA PIANO TERRA 1.pdf",
        "Via Roma 12 Pianta.pdf",
        "Haus 2 Ansicht Nord.pdf",
        "Plan 3 Schnitt.pdf",
        "Grundriss EG 1 50.pdf",
        # An address or a cited standard in capitals has the code's shape and is neither.
        "VIA ROMA 12 Pianta.pdf",
        "UNI EN 1090 Relazione.pdf",
        "DIN EN 1992 Bemessung.pdf",
        "EN 1991 Lastannahmen.pdf",
        "NTC 2018 Relazione strutturale.pdf",
        # Digits running into letters are not the end of a code.
        "ARC PT 01A Pianta.pdf",
    ],
)
def test_words_that_merely_look_like_a_spaced_code_are_not_a_number(filename: str) -> None:
    """Only upper-case groups of up to four letters count, and never a street or a standard."""
    assert detect_sheet_info("", filename=filename)["sheet_number"] is None


def test_a_spaced_code_stacks_with_its_underscored_spelling() -> None:
    """ "ARC PT 01" from one file name and "ARC_PT_01" from another are one drawing."""
    spaced = detect_sheet_info("", filename="ARC PT 01 R03 Pianta.pdf")["sheet_number"]
    underscored = detect_sheet_info("", filename="ARC_PT_01_R04.pdf")["sheet_number"]
    assert sheet_chain_key(spaced) == sheet_chain_key(underscored)


def test_the_page_wins_over_the_file_name() -> None:
    """The file name is a fallback, never an override."""
    info = detect_sheet_info("TAVOLA: ARC-07\nRev. 05", filename="ARC_PT_01_R03.pdf")
    assert info["sheet_number"] == "ARC-07"
    assert info["revision"] == "05"


# ── Discipline ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("number", "expected"),
    [
        ("ARC_PT_01", "Architectural"),
        ("STR-04", "Structural"),
        ("IMP-02", "MEP"),
        ("MEC_01", "Mechanical"),
        ("ELE.03", "Electrical"),
        ("A-101", "Architectural"),
        ("TAV_01", None),
        ("3", None),
    ],
)
def test_discipline_reads_italian_codes_as_well_as_the_first_letter(number: str, expected: str | None) -> None:
    """A three-letter Italian code names its discipline; an unknown word does not fall back to its first letter."""
    assert detect_discipline_from_sheet_number(number) == expected
