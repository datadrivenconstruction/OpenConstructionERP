# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The sample ABS file the rebar schedule page offers for download.

A first-time user downloads it, or loads it with one click, to see what an ABS
import does before they have a file of their own. A sample that the module's
own rules mark red would teach the opposite of what it is there for, so every
rule of the ``bvbs_abs`` set is run over the shipped bytes here.
"""

from pathlib import Path

from app.core.validation.engine import ValidationContext
from app.modules.rebar_schedule.abs_format import parse_file
from app.modules.rebar_schedule.validators import RULES

SAMPLE = Path(__file__).resolve().parents[4] / "frontend" / "public" / "templates" / "rebar-schedule-sample.abs"


def test_the_sample_is_ascii_with_crlf_record_terminators() -> None:
    data = SAMPLE.read_bytes()
    assert data.isascii()
    lines = data.split(b"\r\n")
    assert lines[-1] == b""
    assert all(b"\n" not in line for line in lines)


async def test_the_sample_passes_every_rule() -> None:
    parsed = parse_file(SAMPLE.read_bytes())
    assert len(parsed.records) == 5
    context = ValidationContext(
        data={"records": parsed.records, "encoding": parsed.encoding},
        metadata={"locale": "en"},
    )
    failures = []
    for rule_class in RULES:
        failures += [item for item in await rule_class().validate(context) if not item.passed]
    assert failures == []
