# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The money of a filmed demo project adds up across the economics frame, the packages and the commitments.

The rule, per project: the works, supply and supply-and-install packages plus the contingency drawdown equal the
cost groups 300 and 400 of the DIN 276 cost frame; the design package equals the design fees already committed plus the
design appointment that is still to be released.

Regensburg, in EUR: cost frame KG 300 26.4 M + KG 400 7.0 M = 33.4 M. Packages: construction 26.95 M + supply and
install 4.6 M + supply 1.2 M = 32.75 M, plus the contingency drawdown 0.65 M = 33.4 M. Design package 3.0 M = LP 1 to 4
1.9 M (awarded, committed) + LP 5 to 8 1.1 M (the commitment CR-003 on the running site).

Ludwigsburg, in EUR: KG 300 13.2 M + KG 400 8.4 M = 21.6 M. Packages: construction 16.98 M + supply and install 3.2 M +
supply 1.1 M = 21.28 M, plus the contingency drawdown 0.32 M = 21.6 M. Design package 3.1 M = the design appointment
CR-003 before the gate. Lot 1 (CR-001, 6.2 M) is one trade lot of the construction package.

The cost frame itself is the demo template's and is not in the pack, so its groups are written down here.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_DEMO = _ROOT / "packs/eleven-areas-framework/src/openconstructionerp_eleven_areas_framework/demo"

# demo id -> (KG 300 + KG 400 of the template's cost frame, design package, contingency drawdown)
_FRAME = {
    "residential-regensburg": (Decimal("33400000"), Decimal("3000000"), Decimal("650000")),
    "school-ludwigsburg": (Decimal("21600000"), Decimal("3100000"), Decimal("320000")),
}


def _read(demo: str, module: str) -> dict:
    return json.loads((_DEMO / f"{demo}-{module}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("demo", sorted(_FRAME))
def test_packages_and_contingency_equal_the_cost_groups_300_and_400(demo: str) -> None:
    frame, design, contingency = _FRAME[demo]
    kinds = _read(demo, "procurement_concept")["kinds"]
    built = sum(Decimal(str(kinds[k]["value"])) for k in ("construction", "supply_and_install", "supply"))
    assert built + contingency == frame
    assert Decimal(str(kinds["design"]["value"])) == design


@pytest.mark.parametrize("demo", sorted(_FRAME))
def test_the_contingency_commitment_is_the_contingency_of_the_sheet(demo: str) -> None:
    _frame, _design, contingency = _FRAME[demo]
    story = _read(demo, "commitment_release")
    section = story["running_contingency"] if "running_contingency" in story else story["contingency"]
    assert Decimal(section["amount"]) == contingency


def test_regensburg_design_package_is_the_committed_fee_plus_the_open_appointment() -> None:
    story = _read("residential-regensburg", "commitment_release")
    open_appointment = Decimal(story["running_design"]["amount"])
    awarded_lp_1_to_4 = Decimal(story["design"]["amount"])
    assert awarded_lp_1_to_4 + open_appointment == _FRAME["residential-regensburg"][1]


def test_ludwigsburg_design_package_is_the_design_appointment() -> None:
    story = _read("school-ludwigsburg", "commitment_release")
    assert Decimal(story["design"]["amount"]) == _FRAME["school-ludwigsburg"][1]


@pytest.mark.parametrize("demo", sorted(_FRAME))
def test_the_awarded_design_package_was_awarded_in_the_past(demo: str) -> None:
    design = _read(demo, "procurement_concept")["kinds"]["design"]
    assert design["award_days_ago"] > 0
