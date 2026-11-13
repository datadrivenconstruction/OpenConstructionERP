"""The boot repair fills an empty country from the region and leaves chosen ones alone."""

from types import SimpleNamespace

import pytest

from app.modules.projects import country_backfill


class _Result:
    def __init__(self, rows=None, rowcount=1):
        self._rows = rows or []
        self.rowcount = rowcount

    def all(self):
        return self._rows


class _Session:
    def __init__(self, rows):
        self.rows = rows
        self.updates = 0

    async def execute(self, stmt):
        if stmt.__class__.__name__ == "Select":
            return _Result(self.rows)
        self.updates += 1
        return _Result()


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        ([("a", "Germany"), ("b", "DE"), ("c", "DACH"), ("d", "Middle East")], 2),
        ([("a", "DACH")], 0),
        ([], 0),
    ],
)
async def test_backfill_updates_only_regions_that_name_one_country(rows, expected) -> None:
    session = _Session(rows)
    assert await country_backfill.backfill_country_from_region(session) == expected
    assert session.updates == expected


def test_repair_is_registered() -> None:
    from app.modules.projects.repairs import PROJECT_COUNTRY_FROM_REGION

    assert SimpleNamespace(**vars(PROJECT_COUNTRY_FROM_REGION)).repair_id == "project_country_from_region"
