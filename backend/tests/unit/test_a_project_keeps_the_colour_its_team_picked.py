# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The project colour: a validated ``#rrggbb`` stored on the project for the whole team."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.projects.models import Project
from app.modules.projects.schemas import ProjectCreate, ProjectResponse, ProjectUpdate


@pytest.mark.parametrize("raw", ["#1A2B3C", "#00aaff", "#ffffff"])
def test_a_hex_colour_is_accepted_and_lower_cased(raw: str) -> None:
    assert ProjectUpdate(color=raw).color == raw.lower()
    assert ProjectCreate(name="Tower", currency="EUR", color=raw).color == raw.lower()


@pytest.mark.parametrize("raw", ["red", "#fff", "#12345g", "1a2b3c", "#1a2b3c4d", "url(x)", ""])
def test_anything_but_a_six_digit_hex_is_refused(raw: str) -> None:
    with pytest.raises(ValidationError):
        ProjectUpdate(color=raw)


def test_an_explicit_null_clears_the_colour() -> None:
    patch = ProjectUpdate(color=None)
    assert patch.model_dump(exclude_unset=True) == {"color": None}


def test_omitting_the_colour_leaves_it_untouched() -> None:
    assert "color" not in ProjectUpdate(name="Tower").model_dump(exclude_unset=True)


def test_the_colour_is_a_nullable_column_and_part_of_the_response() -> None:
    col = Project.__table__.c.color
    assert col.nullable is True
    assert col.type.length == 7
    assert "color" in ProjectResponse.model_fields
