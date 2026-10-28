# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure base-resolution helper (methodology, sections 5-6).

Covers:

* The Uzbekistan base mapping (labor / machinery / materials / equipment) with
  sample per-resource-type totals, asserted exactly.
* A many-to-one mapping where several resource types feed one base token, and a
  base token whose resource type is absent from the totals (contributes 0).
* The fallback path: an empty mapping and an empty resource-totals map both
  return ``{fallback_token: fallback_amount}`` when a fallback is given, and the
  fallback stays inert when not.
* Decimal exactness: int / numeric-str inputs coerce to Decimal, and floats are
  rejected to keep the arithmetic exact.
* Validation: a bad mapping shape (bare string instead of a sequence), a
  non-mapping argument, and a non-string resource type all raise
  :class:`BaseResolutionError`, which subclasses ``ValueError``.

This module imports the helper from the app package and therefore runs under the
backend's Python 3.12 test environment (CI). The same logic is also validated
standalone on local Python 3.11 by loading ``bases.py`` directly via
``importlib`` (the full backend cannot import on 3.11 because of PEP 695 syntax
elsewhere in the tree).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.methodology.bases import BaseResolutionError, resolve_bases

# The canonical Uzbekistan base mapping: each cascade leaf base token mapped to
# the resource type(s) that feed it.
UZ_BASE_MAPPING = {
    "labor": ["labor"],
    "machinery": ["equipment_machinery"],
    "materials": ["material"],
    "equipment": ["installed_equipment"],
}


# ── 1. Uzbekistan mapping ─────────────────────────────────────────────────


def test_uz_mapping_resolves_each_base() -> None:
    resource_totals = {
        "labor": Decimal("100000"),
        "equipment_machinery": Decimal("50000"),
        "material": Decimal("200000"),
        "installed_equipment": Decimal("150000"),
    }
    result = resolve_bases(UZ_BASE_MAPPING, resource_totals)

    assert result == {
        "labor": Decimal("100000"),
        "machinery": Decimal("50000"),
        "materials": Decimal("200000"),
        "equipment": Decimal("150000"),
    }
    # The result feeds compute_cascade directly: SMR = labor + machinery +
    # materials = 350000, equipment = 150000.
    assert result["labor"] + result["machinery"] + result["materials"] == Decimal("350000")


def test_uz_mapping_missing_resource_type_contributes_zero() -> None:
    """A resource type listed in the mapping but absent from totals -> 0."""
    resource_totals = {
        "labor": Decimal("100000"),
        "material": Decimal("200000"),
        # equipment_machinery and installed_equipment intentionally absent.
    }
    result = resolve_bases(UZ_BASE_MAPPING, resource_totals)

    assert result == {
        "labor": Decimal("100000"),
        "machinery": Decimal("0"),
        "materials": Decimal("200000"),
        "equipment": Decimal("0"),
    }


def test_many_resource_types_sum_into_one_base() -> None:
    """Several resource types can feed a single base token (summed)."""
    base_mapping = {
        "materials": ["material", "consumables", "small_tools"],
        "labor": ["labor"],
    }
    resource_totals = {
        "material": Decimal("200000"),
        "consumables": Decimal("1500.50"),
        "small_tools": Decimal("499.50"),
        "labor": Decimal("80000"),
    }
    result = resolve_bases(base_mapping, resource_totals)

    assert result["materials"] == Decimal("202000.00")
    assert result["labor"] == Decimal("80000")


def test_extra_resource_types_are_ignored() -> None:
    """Resource totals not referenced by any base token do not appear."""
    resource_totals = {
        "labor": Decimal("100000"),
        "equipment_machinery": Decimal("50000"),
        "material": Decimal("200000"),
        "installed_equipment": Decimal("150000"),
        "overhead_pool": Decimal("9999"),  # not mapped to any base
    }
    result = resolve_bases(UZ_BASE_MAPPING, resource_totals)

    assert "overhead_pool" not in result
    assert set(result) == {"labor", "machinery", "materials", "equipment"}


# ── 2. Fallback path ───────────────────────────────────────────────────────


def test_empty_mapping_uses_fallback() -> None:
    result = resolve_bases(
        {},
        {"labor": Decimal("100")},
        fallback_token="direct",
        fallback_amount=Decimal("1234.56"),
    )
    assert result == {"direct": Decimal("1234.56")}


def test_no_resources_uses_fallback() -> None:
    """A scope with no resources falls back even when a mapping is present."""
    result = resolve_bases(
        UZ_BASE_MAPPING,
        {},
        fallback_token="direct",
        fallback_amount=Decimal("0"),
    )
    assert result == {"direct": Decimal("0")}


def test_fallback_amount_defaults_to_zero() -> None:
    result = resolve_bases({}, {}, fallback_token="direct")
    assert result == {"direct": Decimal("0")}


def test_no_fallback_token_empty_mapping_returns_empty() -> None:
    """Without a fallback token an empty mapping yields an empty dict."""
    assert resolve_bases({}, {"labor": Decimal("100")}) == {}


def test_no_fallback_with_resources_resolves_normally() -> None:
    """A non-empty mapping + non-empty totals ignores the fallback entirely."""
    result = resolve_bases(
        UZ_BASE_MAPPING,
        {"labor": Decimal("100000")},
        fallback_token="direct",
    )
    assert "direct" not in result
    assert result["labor"] == Decimal("100000")
    assert result["machinery"] == Decimal("0")


def test_fallback_amount_float_rejected() -> None:
    with pytest.raises(BaseResolutionError, match="must be a Decimal"):
        resolve_bases({}, {}, fallback_token="direct", fallback_amount=1.5)  # type: ignore[arg-type]


# ── 3. Decimal exactness ───────────────────────────────────────────────────


def test_int_and_str_totals_coerce_to_decimal_exactly() -> None:
    result = resolve_bases(
        {"labor": ["labor"], "materials": ["material"]},
        {"labor": 100000, "material": "0.10"},  # type: ignore[dict-item]
    )
    assert result["labor"] == Decimal("100000")
    assert isinstance(result["labor"], Decimal)
    # 0.10 must stay exact - a float would have introduced 0.1000000000000000055.
    assert result["materials"] == Decimal("0.10")


def test_decimal_sum_is_exact() -> None:
    """0.1 + 0.2 is exact under Decimal (a float sum would be 0.30000000000000004)."""
    result = resolve_bases(
        {"materials": ["a", "b"]},
        {"a": Decimal("0.1"), "b": Decimal("0.2")},
    )
    assert result["materials"] == Decimal("0.3")


def test_float_total_rejected() -> None:
    with pytest.raises(BaseResolutionError, match="must be a Decimal"):
        resolve_bases(
            {"labor": ["labor"]},
            {"labor": 100000.0},  # type: ignore[dict-item]
        )


def test_bool_total_rejected() -> None:
    """bool is an int subclass but is rejected explicitly."""
    with pytest.raises(BaseResolutionError, match="must be a Decimal, got bool"):
        resolve_bases(
            {"labor": ["labor"]},
            {"labor": True},  # type: ignore[dict-item]
        )


def test_non_numeric_str_total_rejected() -> None:
    with pytest.raises(BaseResolutionError, match="not a valid number"):
        resolve_bases(
            {"labor": ["labor"]},
            {"labor": "abc"},  # type: ignore[dict-item]
        )


# ── 4. Validation ──────────────────────────────────────────────────────────


def test_bare_string_mapping_value_rejected() -> None:
    """A bare string value is rejected (it would iterate per character)."""
    with pytest.raises(BaseResolutionError, match="must be a sequence of resource"):
        resolve_bases(
            {"labor": "labor"},  # type: ignore[dict-item]
            {"labor": Decimal("100")},
        )


def test_non_sequence_mapping_value_rejected() -> None:
    with pytest.raises(BaseResolutionError, match="must be a sequence of resource"):
        resolve_bases(
            {"labor": 123},  # type: ignore[dict-item]
            {"labor": Decimal("100")},
        )


def test_non_mapping_base_mapping_rejected() -> None:
    with pytest.raises(BaseResolutionError, match="base_mapping must be a mapping"):
        resolve_bases(
            [("labor", ["labor"])],  # type: ignore[arg-type]
            {"labor": Decimal("100")},
        )


def test_non_mapping_resource_totals_rejected() -> None:
    with pytest.raises(BaseResolutionError, match="resource_totals must be a mapping"):
        resolve_bases(
            {"labor": ["labor"]},
            [("labor", Decimal("100"))],  # type: ignore[arg-type]
        )


def test_non_string_resource_type_in_mapping_rejected() -> None:
    with pytest.raises(BaseResolutionError, match="non-string"):
        resolve_bases(
            {"labor": ["labor", 99]},  # type: ignore[list-item]
            {"labor": Decimal("100")},
        )


def test_base_resolution_error_is_value_error() -> None:
    """BaseResolutionError subclasses ValueError so broad handlers catch it."""
    assert issubclass(BaseResolutionError, ValueError)
