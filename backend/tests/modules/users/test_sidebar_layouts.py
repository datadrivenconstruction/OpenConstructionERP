"""Rules for named sidebar layouts: name, uniqueness, cap, size."""

import pytest

from app.modules.users.sidebar_layouts import (
    MAX_LAYOUTS_PER_USER,
    MAX_NAME_LENGTH,
    SidebarLayoutError,
    read_layouts,
    validate_layouts,
)


def _layout(i: int, name: str | None = None) -> dict:
    return {"id": f"id{i}", "name": name or f"Layout {i}", "data": {"hiddenModules": ["/rfi"]}}


def test_valid_layout_is_trimmed_and_kept() -> None:
    out = validate_layouts([_layout(1, "  Site   week  ")])
    assert out[0]["name"] == "Site week"
    assert out[0]["data"] == {"hiddenModules": ["/rfi"]}


@pytest.mark.parametrize("name", ["", "   ", None, 5])
def test_empty_name_rejected(name: object) -> None:
    with pytest.raises(SidebarLayoutError) as err:
        validate_layouts([{"id": "a", "name": name, "data": {}}])
    assert err.value.code == "name_empty"


def test_name_length_boundary() -> None:
    validate_layouts([_layout(1, "x" * MAX_NAME_LENGTH)])
    with pytest.raises(SidebarLayoutError) as err:
        validate_layouts([_layout(1, "x" * (MAX_NAME_LENGTH + 1))])
    assert err.value.code == "name_too_long"


def test_name_unique_case_insensitive() -> None:
    with pytest.raises(SidebarLayoutError) as err:
        validate_layouts([_layout(1, "Estimating"), _layout(2, "estimating ")])
    assert err.value.code == "name_taken"


def test_cap_of_twenty() -> None:
    validate_layouts([_layout(i) for i in range(MAX_LAYOUTS_PER_USER)])
    with pytest.raises(SidebarLayoutError) as err:
        validate_layouts([_layout(i) for i in range(MAX_LAYOUTS_PER_USER + 1)])
    assert err.value.code == "too_many"


def test_oversized_data_rejected() -> None:
    big = {"id": "a", "name": "Big", "data": {"x": "y" * 70_000}}
    with pytest.raises(SidebarLayoutError) as err:
        validate_layouts([big])
    assert err.value.code == "too_large"


def test_read_layouts_drops_malformed() -> None:
    meta = {"sidebar_layouts": [_layout(1), {"id": 3}, "junk"]}
    assert [x["id"] for x in read_layouts(meta)] == ["id1"]
    assert read_layouts(None) == []
