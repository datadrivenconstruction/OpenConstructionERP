# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""An import without the DDC converter names its missing quantities.

The background CAD processor stores such a model as ``degraded`` and writes a
stable ``error_code``; the UI turns that code into translated text. These tests
pin the decision table and the code list the frontend mirrors.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.modules.bim_hub.quantity_warning import (
    CONVERTER_ABSENT,
    CONVERTER_FAILED,
    NO_QUANTITIES,
    NO_QUANTITIES_CONVERTER_ABSENT,
    NO_QUANTITIES_CONVERTER_FAILED,
    QUANTITY_WARNING_CODES,
    quantity_warning,
)

_FRONTEND_MIRROR = Path(__file__).resolve().parents[3] / "frontend" / "src" / "shared" / "lib" / "bimQuantityWarning.ts"


@pytest.mark.parametrize(
    ("converter_absent", "no_quantities", "code"),
    [
        (True, True, NO_QUANTITIES_CONVERTER_ABSENT),
        (True, False, CONVERTER_ABSENT),
        (False, True, NO_QUANTITIES),
    ],
)
def test_each_shortfall_has_its_own_code(converter_absent: bool, no_quantities: bool, code: str) -> None:
    warning = quantity_warning(converter_absent=converter_absent, no_quantities=no_quantities)
    assert warning is not None
    assert warning.code == code
    assert warning.message


def test_the_converter_cases_name_the_converter() -> None:
    for converter_absent, no_quantities in ((True, True), (True, False)):
        warning = quantity_warning(converter_absent=converter_absent, no_quantities=no_quantities)
        assert warning is not None
        assert "converter is not available" in warning.message


def test_a_full_import_carries_no_warning() -> None:
    assert quantity_warning(converter_absent=False, no_quantities=False) is None


def test_the_frontend_mirrors_every_code() -> None:
    if not _FRONTEND_MIRROR.exists():
        pytest.skip("frontend source not present in this checkout")
    text = _FRONTEND_MIRROR.read_text(encoding="utf-8")
    block = re.search(r"BIM_QUANTITY_WARNING_CODES = \[(.*?)\]", text, re.S)
    assert block is not None
    mirrored = set(re.findall(r"'([a-z_]+)'", block.group(1)))
    assert mirrored == set(QUANTITY_WARNING_CODES)


@pytest.mark.parametrize(
    ("no_quantities", "code"),
    [(True, NO_QUANTITIES_CONVERTER_FAILED), (False, CONVERTER_FAILED)],
)
def test_an_installed_converter_that_failed_is_not_called_absent(no_quantities: bool, code: str) -> None:
    # A timed-out or crashed conversion used to be reported as "converter not available".
    warning = quantity_warning(converter_absent=True, no_quantities=no_quantities, converter_failed=True)
    assert warning is not None
    assert warning.code == code
    assert "not available" not in warning.message
    assert "did not finish" in warning.message
