"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the region → currency table and its warning path.

Audit fix #1 (2026-05-21): ``_resolve_currency`` previously fell through
silently to ``EUR`` on unknown/malformed regions.

Currency-correctness fix (2026-05-31): the silent ``EUR`` fallback for a
genuinely-unknown region was itself a bug — labelling a Kenyan/Thai/Korean
rate as EUR corrupts every downstream cross-currency conversion. The helper
now returns ``""`` (unset, honestly "unknown") instead of a wrong "EUR".

Loadable-region fix (2026-08-03): the table was derived from the v3 snapshot
registry, while the set of bases the importer accepts comes from
``base_registry.github_workitems_files()``. Twelve of the thirty-eight
loadable regions were missing from the table, so importing any of them
resolved to ``""`` and wrote a whole catalogue of rates with no currency on
them. One such import left 55 718 rows that way. The table is now built from
the same registry the loader reads, and the invariant below is the gate: a
base that can be loaded can be priced.

These tests lock in:

    1. Malformed regions log a warning, append the message to the
       caller-supplied ``warnings`` list, and resolve to "" (unset).
    2. Unknown but well-formed regions log a warning AND resolve to "".
    3. Every base the importer will load resolves to the currency its own
       registry entry declares.
    4. The well-known regions (PT_LISBON, DE_BERLIN, ...) still resolve
       correctly and emit NO warning.
    5. Duplicate warnings are de-duplicated within a single request.
    6. Every available v3 catalogue region resolves to its declared
       currency — never a wrong fallback.
    7. The read path and the write path share one table, not two copies of
       the same construction.
"""

from __future__ import annotations

import logging

import pytest

from app.modules.costs import base_registry
from app.modules.costs.cwicr_v3_catalogue import CWICR_V3_CATALOGUES
from app.modules.costs.router import (
    _REGION_CURRENCY,
    _is_valid_region_format,
    _resolve_currency,
)
from app.modules.costs.schemas import _REGION_CURRENCY_FALLBACK


def test_resolve_currency_well_known_region_no_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Happy path: a known region resolves to its currency and emits no
    warning. The caller-supplied ``warnings`` list stays empty."""
    warnings: list[str] = []
    with caplog.at_level(logging.WARNING, logger="app.modules.costs.router"):
        assert _resolve_currency(None, "DE_BERLIN", warnings=warnings) == "EUR"
        assert _resolve_currency(None, "GB_LONDON", warnings=warnings) == "GBP"
        assert _resolve_currency(None, "BR_SAOPAULO", warnings=warnings) == "BRL"
    assert warnings == []
    assert not any(r.levelno == logging.WARNING for r in caplog.records)


#: The bases the importer will accept, read once so the guard below and the
#: parametrised test cannot disagree about what they cover.
_LOADABLE_REGIONS: list[str] = sorted(base_registry.github_workitems_files())


def test_the_loadable_region_list_is_not_empty() -> None:
    """The parametrised test below covers nothing if this list comes back empty.

    ``github_workitems_files()`` builds from the in-memory registry and touches
    no filesystem, so it cannot come back short on a machine that lacks the
    parquet files. This asserts that anyway, because a parametrisation over an
    empty sequence collects zero tests and reports success, which is the one
    failure mode a green run cannot distinguish from a pass. 30 is the global
    market family alone; the national bases sit on top.
    """
    assert len(_LOADABLE_REGIONS) >= 30


@pytest.mark.parametrize("region", _LOADABLE_REGIONS)
def test_every_loadable_base_region_resolves_to_its_declared_currency(
    region: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A base the importer will load must resolve to the currency it declares.

    This is the invariant the 55 718 blank rows were missing. The importer takes
    the bases it accepts from ``github_workitems_files()`` and resolves the
    currency through ``_REGION_CURRENCY``; while those were two independently
    built tables, a region present in the first and absent from the second was
    an import that silently wrote no currency at all. Parametrised so a region
    that falls out of the table fails by its own name.

    The expected value is read from the region's own ``BaseVariant``, not from a
    list written down here, because a second list is the thing that drifted.
    """
    variant = base_registry.variant_by_region(region)
    assert variant is not None, f"{region} is loadable but has no registry variant"
    assert variant.currency, f"{region} declares no currency in the registry"

    warnings: list[str] = []
    with caplog.at_level(logging.WARNING, logger="app.modules.costs.router"):
        assert _resolve_currency(None, region, warnings=warnings) == variant.currency
    assert warnings == []


def test_pt_saopaulo_resolves_alongside_the_v3_key() -> None:
    """Both São Paulo keys are real and both must resolve to BRL.

    ``PT_SAOPAULO`` was once excluded from the table as a mislabel, on the
    reasoning that São Paulo is Brazil and the canonical key is
    ``BR_SAOPAULO``. That is true of the v3 snapshot regions and false of the
    global family, where ``PT_SAOPAULO`` is the region id of the Brazil /
    Portugal card — ``github_workitems_files()`` will load it and
    ``variant_by_region`` declares BRL for it. A region the loader accepts is
    not a typo, and treating it as one is what left its rows unpriced.
    """
    assert "PT_SAOPAULO" in base_registry.github_workitems_files()
    assert base_registry.variant_by_region("PT_SAOPAULO").currency == "BRL"
    assert _REGION_CURRENCY["PT_SAOPAULO"] == "BRL"
    assert _REGION_CURRENCY["BR_SAOPAULO"] == "BRL"


def test_read_and_write_paths_share_one_region_currency_table() -> None:
    """One table, bound twice — not two tables kept in step by a comment.

    The router's copy backs the importer and the match paths; the schema's copy
    backs the ``CostItemResponse`` validator and the Cost Explorer. They were
    built by two identical functions in two modules, with a comment in each
    asking the next editor to keep them the same. Identity is the only version
    of that promise a test can hold, and without it a region added to one is a
    region the other still calls unknown, so the same row is priced on the list
    screen and blank on the detail screen.
    """
    assert _REGION_CURRENCY is _REGION_CURRENCY_FALLBACK


def test_resolve_currency_malformed_region_logs_warning_and_appends(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Garbage like ``"!@#$"`` or ``"berlin"`` (lowercase) doesn't match
    ``XX_CITY`` — flag it as non-canonical, log a warning, and append the
    message to the caller's warnings list so the FE can show a toast."""
    warnings: list[str] = []
    with caplog.at_level(logging.WARNING, logger="app.modules.costs.router"):
        result = _resolve_currency(None, "!@#$", warnings=warnings)
    assert result == ""  # unset, not a wrong "EUR"
    assert len(warnings) == 1
    assert "non-canonical" in warnings[0]
    assert any(r.levelno == logging.WARNING and "non-canonical" in r.getMessage() for r in caplog.records)


def test_resolve_currency_unknown_but_valid_format_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A well-formed but unregistered region (``DK_COPENHAGEN``) is the
    most likely real-world miss — log a warning identifying the missing
    entry so ops can extend the registry, and resolve to "" (never a
    wrong "EUR")."""
    warnings: list[str] = []
    with caplog.at_level(logging.WARNING, logger="app.modules.costs.router"):
        result = _resolve_currency(None, "DK_COPENHAGEN", warnings=warnings)
    assert result == ""
    assert len(warnings) == 1
    assert "Unknown region" in warnings[0]
    assert "DK_COPENHAGEN" in warnings[0]


def test_resolve_currency_duplicate_warnings_collapsed() -> None:
    """When the same bad region appears on many rows, the warnings list
    must not blow up — the helper de-duplicates so the FE shows one toast
    per distinct issue."""
    warnings: list[str] = []
    for _ in range(10):
        _resolve_currency(None, "ZZ_MARS", warnings=warnings)
    assert len(warnings) == 1


def test_resolve_currency_explicit_currency_short_circuits(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A row that carries a non-empty currency bypasses the region lookup
    entirely — even if the region is malformed. No warning emitted."""
    warnings: list[str] = []
    with caplog.at_level(logging.WARNING, logger="app.modules.costs.router"):
        result = _resolve_currency("CHF", "not-a-region", warnings=warnings)
    assert result == "CHF"
    assert warnings == []


@pytest.mark.parametrize(
    ("region", "expected_currency"),
    [(cat.region, cat.currency) for cat in CWICR_V3_CATALOGUES if cat.available and cat.currency],
)
def test_every_available_v3_region_resolves_to_declared_currency(
    region: str,
    expected_currency: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Every shipped v3 catalogue region must resolve to its OWN declared ISO
    currency — never the wrong fallback. This is the regression guard for the
    ~18 regions (KES/GHS/KRW/THB/VND/…) the hand-kept map used to mislabel as
    EUR. ``_REGION_CURRENCY`` is now derived from ``CWICR_V3_CATALOGUES`` so
    the two can never drift."""
    warnings: list[str] = []
    with caplog.at_level(logging.WARNING, logger="app.modules.costs.router"):
        assert _resolve_currency(None, region, warnings=warnings) == expected_currency
    assert warnings == []


def test_is_valid_region_format() -> None:
    """Sanity check for the regex guard used by ``_resolve_currency``."""
    # Valid shapes (2-3 letter country + underscore + uppercase city).
    assert _is_valid_region_format("DE_BERLIN")
    assert _is_valid_region_format("USA_NEWYORK")
    assert _is_valid_region_format("RU_ST_PETERSBURG") is False  # extra _
    # Wait — actually RU_STPETERSBURG is valid (no second underscore).
    assert _is_valid_region_format("RU_STPETERSBURG")
    # Invalid shapes.
    assert not _is_valid_region_format("")
    assert not _is_valid_region_format("berlin")
    assert not _is_valid_region_format("DE-BERLIN")
    assert not _is_valid_region_format("!@#$")
    assert not _is_valid_region_format("DE_")
