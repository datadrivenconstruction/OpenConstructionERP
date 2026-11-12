"""A region label that names one country settles the project country (VAT default follows)."""

import pytest

from app.modules.projects.service import country_from_region


@pytest.mark.parametrize(
    ("region", "expected"),
    [
        ("DE", "DE"),
        ("de", "DE"),
        ("Germany", "DE"),
        ("UK", "GB"),
        ("DACH", None),
        ("Middle East", None),
        ("", None),
        (None, None),
    ],
)
def test_country_from_region(region: str | None, expected: str | None) -> None:
    assert country_from_region(region) == expected
