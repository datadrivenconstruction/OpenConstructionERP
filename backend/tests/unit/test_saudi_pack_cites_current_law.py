# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The Saudi partner pack cites the building code in force and no unsourced labour rule.

SBC 2024 replaced SBC 2018 and is mandatory since 2025-06-30, so a pack that
told a contractor to confirm "which SBC 2018 Parts apply" pointed at a code the
municipalities no longer check against. And two Nitaqat requirements the pack
stated as fact (at least Yellow above nine employees, Green-Medium for public
tenders) had no source; a rule pack may describe them as open, never enforce
them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_PACK = Path(__file__).resolve().parents[3] / "packs" / "saudi-vision2030"
_SRC = _PACK / "src" / "openconstructionerp_saudi_vision2030"
_SBC_PARTS = ("201_energy", "301_loads", "304_concrete", "401_electrical", "501_mechanical", "801_fire")


def _shipped_text_files() -> list[Path]:
    return [
        path
        for path in _PACK.rglob("*")
        if path.is_file()
        and path.suffix in {".py", ".json", ".yaml", ".toml", ".md"}
        and "__pycache__" not in path.parts
    ]


def test_every_sbc_part_is_the_2024_edition() -> None:
    for part in _SBC_PARTS:
        doc = json.loads((_SRC / "rule_packs" / f"sbc_{part}.json").read_text(encoding="utf-8"))
        assert doc["standard"].startswith("Saudi Building Code 2024"), part
        assert doc["publication_year"] == 2024, part
        assert doc["mandatory_from"] == "2025-06-30", part
        # The lineage was stated for the 2018 edition and is kept under a name
        # that says so, not presented as the 2024 edition's.
        assert "derives_from" not in doc, part


def test_sbc_2018_is_named_only_as_the_superseded_edition() -> None:
    allowed = re.compile(r"(supersedes|replaced SBC 2018|derives_from_note|SBC 2018 edition|2018 lineage)")
    offenders = []
    for path in _shipped_text_files():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"SBC 2018|Saudi Building Code 2018", line) and not allowed.search(line):
                offenders.append(f"{path.relative_to(_PACK)}:{number}")
    assert offenders == [], f"SBC 2018 still cited as current: {offenders}"


def test_no_nitaqat_rule_claims_an_unsourced_band_requirement() -> None:
    doc = json.loads((_SRC / "rule_packs" / "saudization_nitaqat.json").read_text(encoding="utf-8"))
    review = doc["needs_expert_review"]
    assert "nitaqat.public_tender_requires_green_medium" in review
    # A rule under review may not carry an ERROR severity: that would enforce
    # it the day it is built.
    assert not set(doc["severity_overrides"]) & set(review)
    assert "at least a Yellow band;" not in doc["description"]
    onboarding = (_SRC / "onboarding.yaml").read_text(encoding="utf-8")
    assert "required for government tenders" not in onboarding
