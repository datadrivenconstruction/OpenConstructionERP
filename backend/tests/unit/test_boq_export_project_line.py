# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The project line printed under the title of an exported BOQ sheet.

An exported workbook used to be titled with the bill's own name and nothing
else, so a recipient outside the company could not tell which job it belonged
to, under which classification standard, or in which region. The browser's own
exporter tried to print exactly those three and printed the product name
instead, because it read them from a value it did not hold; the export is the
server's now, and the server has to actually print them.

Run:
    pytest backend/tests/unit/test_boq_export_project_line.py -q
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.modules.boq.router import _export_details, _project_line


@dataclass
class _Project:
    """Only the three attributes the line reads."""

    name: str | None = "Riverside HQ"
    classification_standard: str | None = "din276"
    region: str | None = "DACH"


class TestProjectLine:
    """What lands under the title of the sheet."""

    def test_names_the_job_the_standard_and_the_region(self) -> None:
        assert _project_line(_Project()) == "Project: Riverside HQ  |  Standard: din276  |  Region: DACH"

    def test_a_project_that_could_not_be_read_prints_no_line(self) -> None:
        # Not an empty string: the caller must be able to tell "nothing to say"
        # from "say nothing", because an empty subtitle would still take a row.
        assert _project_line(None) is None

    def test_a_project_answering_none_of_the_three_prints_no_line(self) -> None:
        assert _project_line(_Project(name="", classification_standard="", region="")) is None

    def test_nulls_are_the_same_as_blanks(self) -> None:
        assert _project_line(_Project(name=None, classification_standard=None, region=None)) is None

    def test_a_missing_part_is_dropped_rather_than_printed_empty(self) -> None:
        line = _project_line(_Project(classification_standard=""))
        assert line == "Project: Riverside HQ  |  Region: DACH"

    def test_only_the_job_is_enough_for_a_line(self) -> None:
        line = _project_line(_Project(classification_standard=None, region=None))
        assert line == "Project: Riverside HQ"

    def test_surrounding_space_is_not_printed(self) -> None:
        line = _project_line(_Project(name="  Riverside HQ  ", classification_standard=" ", region="DACH"))
        assert line == "Project: Riverside HQ  |  Region: DACH"

    def test_an_object_missing_the_attributes_entirely_prints_no_line(self) -> None:
        # A row read through a different model, or a stub in a caller's test,
        # must not raise inside an export that is otherwise finished.
        assert _project_line(object()) is None


class TestExportDetails:
    """The detail lines of the document block: the project, the money, the day."""

    _AT = datetime(2026, 10, 4, 23, 30, tzinfo=timezone(timedelta(hours=-5)))

    def test_project_then_currency_and_date(self) -> None:
        lines = _export_details("Project: Riverside HQ", "eur", self._AT)
        # 23:30 at UTC-5 is already the 5th in UTC, which is the date printed.
        assert lines == ["Project: Riverside HQ", "Currency: EUR  |  Exported: 2026-10-05"]

    def test_no_project_still_states_currency_and_date(self) -> None:
        assert _export_details(None, "USD", self._AT) == ["Currency: USD  |  Exported: 2026-10-05"]

    def test_no_currency_is_left_out_rather_than_printed_empty(self) -> None:
        assert _export_details("Project: X", "  ", self._AT) == ["Project: X", "Exported: 2026-10-05"]
        assert _export_details("Project: X", "", self._AT)[-1] == "Exported: 2026-10-05"
