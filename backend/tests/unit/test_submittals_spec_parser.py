"""Spec book parser: golden tests on small synthetic pages, no PDF needed."""

from __future__ import annotations

import weakref

from app.modules.submittals import spec_parser
from app.modules.submittals.spec_parser import parse_pages

MASTERFORMAT = """\
SECTION 03 30 00 - CAST-IN-PLACE CONCRETE
PART 1 - GENERAL
1.1 SUMMARY
A. This Section includes cast-in-place concrete.
1.4 SUBMITTALS
A. Submit the following:
B. Product Data: For each type of admixture and curing compound.
C. Design Mixtures: Mix designs for each concrete mixture.
D. Shop Drawings: Reinforcement placing drawings.
E. Samples: 12-inch square of each finish.
1.5 QUALITY ASSURANCE
A. Testing agency qualifications.
PART 2 - PRODUCTS
2.3 ACCEPTANCE
A. The Contractor shall submit a test report for each batch of cement.
END OF SECTION 03 30 00
SECTION 09 91 23 - INTERIOR PAINTING
PART 1 - GENERAL
1.3 ACTION SUBMITTALS
A. Product Data: For each type of product.
"""

DIN = """\
Leistungsbereich 013 - Beton- und Stahlbetonarbeiten
Einzureichende Unterlagen
- Produktdatenblätter für Zusatzmittel
- Prüfberichte der Betonprüfung
- Bemusterung der Sichtbetonflächen
Ausführung
Der Beton ist zu verdichten.
"""

TOC = """\
Table of contents
SECTION 03 30 00 - CAST-IN-PLACE CONCRETE ........ 12
SECTION 09 91 23 - INTERIOR PAINTING ............. 40
SECTION 26 05 00 - COMMON WORK RESULTS ........... 55
SECTION 31 20 00 - EARTH MOVING .................. 70
"""


def _by_kind(parser: spec_parser.SpecParser, section: str) -> dict[str, spec_parser.Proposal]:
    return {p.kind: p for p in parser.proposals if p.spec_section == section}


def test_masterformat_sections_and_submittals() -> None:
    parser = parse_pages([(1, MASTERFORMAT)])
    assert [s[0] for s in parser.sections] == ["03 30 00", "09 91 23"]
    concrete = _by_kind(parser, "03 30 00")
    assert {"product_data", "mix_design", "shop_drawing", "sample", "test_report"} <= set(concrete)
    assert concrete["mix_design"].submittal_type == "calculation"
    assert concrete["product_data"].confidence == 0.9
    assert concrete["test_report"].confidence == 0.6  # inferred from Part 2
    assert concrete["product_data"].source_page == 1
    assert _by_kind(parser, "09 91 23")["product_data"].title == "Product data - INTERIOR PAINTING"


def test_din_style_section_and_german_types() -> None:
    parser = parse_pages([(7, DIN)])
    assert parser.sections == [("LB 013", "Beton- und Stahlbetonarbeiten")]
    kinds = _by_kind(parser, "LB 013")
    assert set(kinds) == {"product_data", "test_report", "sample"}
    assert all(p.source_page == 7 for p in kinds.values())


def test_table_of_contents_is_skipped() -> None:
    parser = parse_pages([(2, TOC), (3, MASTERFORMAT)])
    assert [s[0] for s in parser.sections] == ["03 30 00", "09 91 23"]


def test_running_page_header_does_not_restart_the_section() -> None:
    page2 = "SECTION 03 30 00 - CAST-IN-PLACE CONCRETE Page 2\nE. Samples: finish panels.\n"
    parser = parse_pages([(1, MASTERFORMAT.split("1.5")[0]), (2, page2)])
    assert [s[0] for s in parser.sections] == ["03 30 00"]


def test_no_sections_in_plain_text() -> None:
    parser = parse_pages([(1, "Just a letter\nwith nothing in it")])
    assert parser.sections == [] and parser.proposals == []


def test_required_kinds_table() -> None:
    assert spec_parser.required_kinds("03 30 00") == ["mix_design"]
    assert spec_parser.required_kinds("09 91 23") == []


class _Page(str):
    """A str that can be weakly referenced, to see whether the parser keeps pages alive."""


def test_pages_are_not_retained() -> None:
    live: list[weakref.ref[_Page]] = []
    peak = 0

    def pages():  # type: ignore[no-untyped-def]
        nonlocal peak
        for n in range(1, 1001):
            page = _Page(f"SECTION 03 30 00 - CONCRETE\nPART 1\n1.4 SUBMITTALS\nA. Samples: panel {n}\n" + "x" * 2000)
            live.append(weakref.ref(page))
            yield n, page
            peak = max(peak, sum(1 for r in live if r() is not None))

    parser = parse_pages(pages())
    assert peak <= 2
    assert len(parser.proposals) == 1  # one sample proposal per section, not per page
