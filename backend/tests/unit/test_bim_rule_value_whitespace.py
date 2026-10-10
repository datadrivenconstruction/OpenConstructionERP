# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A quantity rule ignores whitespace around a value, as property search does.

Revit exports often carry a trailing space ("Fase 1 "). Property search trimmed
it and found the elements, the rule kept it and matched none of them.
"""

from __future__ import annotations

from app.modules.bim_hub.service import _glob_match


def test_a_trailing_space_in_the_model_value_still_matches() -> None:
    assert _glob_match("Fase 1 ", "fase 1")


def test_a_space_typed_around_the_rule_value_still_matches() -> None:
    assert _glob_match("Muro [30 cm]", "  Muro [30 cm] ")


def test_inner_whitespace_still_decides() -> None:
    assert not _glob_match("Fase  1", "Fase 1")
