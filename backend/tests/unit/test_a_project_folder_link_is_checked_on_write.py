# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The project's external folder link: http(s), file, smb or UNC only, bounded length."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.projects.models import Project
from app.modules.projects.schemas import ProjectCreate, ProjectResponse, ProjectUpdate


@pytest.mark.parametrize(
    "raw",
    [
        "https://example.sharepoint.com/sites/tower",
        "http://nas.local/projects/tower",
        "file:///Z:/Projects/Tower",
        "smb://nas/projects/tower",
        r"\\nas\projects\tower",
    ],
)
def test_an_accepted_link_is_stored_as_given(raw: str) -> None:
    assert ProjectUpdate(external_folder_url=raw).external_folder_url == raw
    assert ProjectCreate(name="Tower", currency="EUR", external_folder_url=raw).external_folder_url == raw


@pytest.mark.parametrize(
    "raw",
    ["javascript:alert(1)", "ftp://host/x", "data:text/html,x", "C:relative", r"\\nas", "/etc/passwd", "https://a b"],
)
def test_anything_else_is_refused(raw: str) -> None:
    with pytest.raises(ValidationError):
        ProjectUpdate(external_folder_url=raw)


def test_a_link_over_the_column_width_is_refused() -> None:
    with pytest.raises(ValidationError):
        ProjectUpdate(external_folder_url="https://example.com/" + "a" * 500)
    assert ProjectUpdate(external_folder_url="https://e.co/" + "a" * 487).external_folder_url


def test_a_blank_link_clears_it_and_omitting_leaves_it() -> None:
    assert ProjectUpdate(external_folder_url="  ").model_dump(exclude_unset=True) == {"external_folder_url": None}
    assert "external_folder_url" not in ProjectUpdate(name="Tower").model_dump(exclude_unset=True)


def test_the_link_is_a_nullable_column_and_part_of_the_response() -> None:
    col = Project.__table__.c.external_folder_url
    assert col.nullable is True
    assert col.type.length == 500
    assert "external_folder_url" in ProjectResponse.model_fields
