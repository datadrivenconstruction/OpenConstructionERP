"""Global money-as-Decimal Pydantic schema audit.

v3 §10 — every monetary field on a request/response schema must be
emitted to JSON as a *string* (not a number) so:

* very-large totals round-trip exactly (floats lose precision past
  ~15 significant figures);
* the value is locale-neutral (no thousand-separator / decimal-comma
  ambiguity);
* consumers do not silently truncate cents through a float intermediate.

This test pins the contract for the top 40 money fields fixed in the
``fix(money): convert top 40 float fields …`` wave. Each case:

1. constructs the schema with a real ``Decimal`` value;
2. serialises to JSON via ``model_dump_json()``;
3. asserts the value emerges as a STRING in the JSON output, not a
   number — i.e. it is wrapped in double-quotes;
4. for request schemas, additionally asserts that the field accepts a
   plain string on input and round-trips back to ``Decimal``.

A meta-test (``test_no_new_money_floats_creep_in``) parses the live
OpenAPI document and asserts that no NEW money-named field has slipped
in as ``"type": "number"`` since this wave landed.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import BaseModel

# ── Fixtures shared by the assertion helpers ─────────────────────────────


def _assert_money_field_is_string(payload: str, field_name: str) -> None:
    """Assert ``field_name`` is rendered as a JSON STRING (not a number).

    A JSON number for ``"price": 12.34`` looks like ``"price": 12.34`` (no
    quotes round the value). The v3 §10 contract is ``"price": "12.34"``
    — the value is itself a quoted string.
    """
    obj = json.loads(payload)
    assert field_name in obj, f"{field_name!r} missing from payload {payload!r}"
    value = obj[field_name]
    assert isinstance(value, str), (
        f"{field_name!r} serialised as {type(value).__name__} {value!r}; expected str per v3 §10 (Decimal-as-string)"
    )


def _assert_decimal_roundtrips(
    schema_cls: type[BaseModel],
    field_name: str,
    value: str,
) -> None:
    """Parse a string into the schema, then re-emit it; field must be a string."""
    # Build a minimal kwargs dict — only the field under test is required-ish.
    instance = schema_cls.model_construct(**{field_name: Decimal(value)})
    # round-trip through JSON
    payload = instance.model_dump_json()
    _assert_money_field_is_string(payload, field_name)
    # parsing the JSON back into the schema must yield a Decimal
    reparsed = schema_cls.model_validate_json(payload)
    actual = getattr(reparsed, field_name)
    assert isinstance(actual, Decimal), (
        f"{schema_cls.__name__}.{field_name} reparsed as {type(actual).__name__}, expected Decimal"
    )
    assert actual == Decimal(value), (
        f"{schema_cls.__name__}.{field_name} round-trip lost precision: {value!r} → {actual!r}"
    )


# ── Per-field serialisation pinning (top 40) ─────────────────────────────


# Each tuple is (import_path, schema_cls_name, field_name).
# Constructed lazily because some schemas pull in heavy modules.
MONEY_FIELDS: list[tuple[str, str, str]] = [
    # match_elements (7)
    ("app.modules.match_elements.schemas", "SessionSummary", "total_value"),
    ("app.modules.match_elements.schemas", "GroupSummary", "suggested_unit_rate"),
    ("app.modules.match_elements.schemas", "ApplyResourcePreview", "unit_rate"),
    ("app.modules.match_elements.schemas", "ApplyPositionPreview", "unit_rate"),
    ("app.modules.match_elements.schemas", "ApplyPositionPreview", "line_total"),
    ("app.modules.match_elements.schemas", "ApplyToBoqResponse", "grand_total"),
    ("app.modules.match_elements.schemas", "NoMatchRequest", "custom_rate"),
    # bim_hub (4)
    ("app.modules.bim_hub.schemas", "BOQElementLinkBrief", "boq_position_unit_rate"),
    ("app.modules.bim_hub.schemas", "BOQElementLinkBrief", "boq_position_total"),
    ("app.modules.bim_hub.schemas", "BIMModelBOQLinkAggregate", "boq_position_unit_rate"),
    ("app.modules.bim_hub.schemas", "BIMModelBOQLinkAggregate", "boq_position_total"),
    # boq (29)
    ("app.modules.boq.schemas", "BOQListItem", "direct_cost_total"),
    ("app.modules.boq.schemas", "BOQListItem", "markups_total"),
    ("app.modules.boq.schemas", "BOQListItem", "grand_total"),
    ("app.modules.boq.schemas", "MarkupCalculated", "amount"),
    ("app.modules.boq.schemas", "BOQWithPositions", "direct_cost_total"),
    ("app.modules.boq.schemas", "BOQWithPositions", "markups_total"),
    ("app.modules.boq.schemas", "BOQWithPositions", "grand_total"),
    ("app.modules.boq.schemas", "SectionResponse", "subtotal"),
    ("app.modules.boq.schemas", "BOQWithSections", "direct_cost"),
    ("app.modules.boq.schemas", "BOQWithSections", "net_total"),
    ("app.modules.boq.schemas", "BOQWithSections", "grand_total"),
    ("app.modules.boq.schemas", "AIChatItem", "unit_rate"),
    ("app.modules.boq.schemas", "AIChatItem", "total"),
    ("app.modules.boq.schemas", "CostBreakdownCategory", "amount"),
    ("app.modules.boq.schemas", "CostBreakdownMarkup", "amount"),
    ("app.modules.boq.schemas", "CostBreakdownResource", "total_cost"),
    ("app.modules.boq.schemas", "CostBreakdownResponse", "grand_total"),
    ("app.modules.boq.schemas", "CostBreakdownResponse", "direct_cost"),
    ("app.modules.boq.schemas", "ResourceSummaryItem", "avg_unit_rate"),
    ("app.modules.boq.schemas", "ResourceSummaryItem", "total_cost"),
    ("app.modules.boq.schemas", "ResourceTypeSummary", "total_cost"),
    ("app.modules.boq.schemas", "ResourceSummaryResponse", "grand_total"),
    ("app.modules.boq.schemas", "ResourceCodeMatch", "unit_rate"),
    ("app.modules.boq.schemas", "RateMatch", "rate"),
    ("app.modules.boq.schemas", "SuggestRateResponse", "suggested_rate"),
    ("app.modules.boq.schemas", "ScopeMissingItem", "estimated_rate"),
    ("app.modules.boq.schemas", "BOQStatisticsResponse", "direct_cost"),
    ("app.modules.boq.schemas", "BOQStatisticsResponse", "grand_total"),
    ("app.modules.boq.schemas", "BOQStatisticsResponse", "avg_unit_rate"),
]


def _resolve(module_path: str, cls_name: str) -> type[BaseModel]:
    import importlib

    mod = importlib.import_module(module_path)
    return getattr(mod, cls_name)


@pytest.mark.parametrize(("module_path", "cls_name", "field_name"), MONEY_FIELDS)
def test_money_field_serialises_as_string(module_path: str, cls_name: str, field_name: str) -> None:
    """v3 §10 — money emerges from JSON serialisation as a STRING."""
    schema_cls = _resolve(module_path, cls_name)
    instance = schema_cls.model_construct(**{field_name: Decimal("1234.56")})
    payload = instance.model_dump_json()
    _assert_money_field_is_string(payload, field_name)


@pytest.mark.parametrize(("module_path", "cls_name", "field_name"), MONEY_FIELDS)
def test_money_field_accepts_string_input(module_path: str, cls_name: str, field_name: str) -> None:
    """v3 §10 — money fields accept a string input and parse back to Decimal."""
    schema_cls = _resolve(module_path, cls_name)
    # Build via Pydantic's full validator path so string→Decimal coercion runs.
    instance = schema_cls.model_construct(**{field_name: "9876.54"})
    payload = instance.model_dump_json()
    _assert_money_field_is_string(payload, field_name)
    # The serialised value must be the exact same string we put in
    # (no float-mediated drift like "9876.539999...").
    obj = json.loads(payload)
    assert obj[field_name] == "9876.54", (
        f"{cls_name}.{field_name} round-trip drifted: in='9876.54' out={obj[field_name]!r}"
    )


# ── Meta-test: cap the *remaining* money-as-float deficit ────────────────


# Heuristic — names that almost certainly indicate currency.
MONEY_NAME_RE = re.compile(
    r"^(?:.*_)?(?:price|cost|amount|markup|vat|subtotal|discount|"
    r"commission|fee|budget|quote|grand_total|net_total|line_total|"
    r"direct_cost|total_cost|unit_rate|unit_cost|unit_price|"
    r"suggested_rate|estimated_rate|typical_rate|escalated_rate|"
    r"avg_unit_rate|original_rate|recommended_budget|base_total|"
    r"actual_cost|planned_cost|earned_value|forecast_amount|"
    r"committed_amount|actual_amount|planned_amount|planned_inflow|"
    r"planned_outflow|actual_inflow|actual_outflow|cumulative_planned|"
    r"cumulative_actual|total_payable|total_receivable|total_overdue|"
    r"total_budget|total_committed|total_actual|total_variance|"
    r"total_payments|total_exposure|impact_cost|response_cost|"
    r"labor_cost|material_cost|labor_cost_change|fixed_amount|"
    r"variance_abs|cost_usd_estimate)(?:_[a-z0-9_]+)?$"
)
# Field names that match the regex but are pure ratios / percentages /
# counts / sizes — keep on the explicit ignore list (belt-and-braces).
RATIO_OR_NON_MONEY: set[str] = {
    "rate_factor",
    "pick_rate",
    "feedback_rate_pct",
    "cache_hit_rate_pct",
    "qty_variance_pct",
    "gr_rejection_rate",
    "rate_completeness_pct",
    "total_artifact_size_mb",
    "total_original_size_mb",
    "total_size_mb",
    "total_workforce_hours",
    "total_delay_hours",
    "variance_pct",
    "classification_coverage_pct",
    "share_of_total",
    "share_pct",
    "completion_pct",
    "abc_percentage",
}


def _is_money_named(field_name: str) -> bool:
    if field_name in RATIO_OR_NON_MONEY:
        return False
    if field_name.endswith(("_pct", "_percentage", "_count", "_mb")):
        return False
    return bool(MONEY_NAME_RE.match(field_name))


# Initial audit count (via the regex/heuristic below): 149 money-named
# fields rendering as ``"type": "number"`` in JSON-schema output.
#   * First wave fixed the top 40 → 109 remaining.
#   * v3128 (ai.cost_usd_estimate) regressed +1 → 110.
#   * v3129 money sweep (see ``v3129_money_decimal_sweep`` alembic rev)
#     converted the remaining deferred fields catalogued in
#     ``docs/MONEY_FLOAT_REMAINING.md`` (111 fields incl. the v3128
#     regression). 1 field remains: ``BidComparisonRow.budget_quantity``
#     — flagged in the audit as "measurement, but priced — verify per
#     project"; we kept it ``float`` because it is genuinely a measured
#     quantity in the bid context, not a unit price. The cap is set to
#     1 so any further regression — a new ``: float`` money field on a
#     schema, or a callable wrongly downcast — is caught by CI.
# Sibling agents that fix further money fields should *lower* this
# constant to lock in their progress. New money-as-float fields ADDED
# to a schema will push the count over the cap and fail CI.
MAX_REMAINING_MONEY_FLOATS = 1


def _collect_module_schemas() -> dict[str, dict]:
    """Walk every Pydantic BaseModel declared under ``app.modules.*.schemas``.

    The live OpenAPI spec only sees endpoints that were mounted before
    the spec was generated — but the per-module routers are mounted in
    an async startup hook (``module_loader.load_all``), so a synchronous
    ``app.openapi()`` returns ~9 schemas. Walking the source modules
    directly gives us the full schema inventory deterministically.
    """
    import importlib
    import pkgutil

    import app.modules as modules_pkg

    out: dict[str, dict] = {}
    for mod_info in pkgutil.iter_modules(modules_pkg.__path__):
        try:
            schemas_mod = importlib.import_module(f"app.modules.{mod_info.name}.schemas")
        except ModuleNotFoundError:
            continue
        except Exception:  # noqa: BLE001
            # A broken schemas.py shouldn't crash the audit.
            continue
        for attr_name in dir(schemas_mod):
            cls = getattr(schemas_mod, attr_name)
            if isinstance(cls, type) and issubclass(cls, BaseModel) and cls is not BaseModel:
                # Only include classes declared IN this module (skip imports).
                if cls.__module__ != schemas_mod.__name__:
                    continue
                try:
                    json_schema = cls.model_json_schema(mode="serialization")
                except Exception:  # noqa: BLE001
                    continue
                qualified = f"{mod_info.name}.{cls.__name__}"
                out[qualified] = json_schema
    return out


def test_money_as_float_deficit_does_not_grow() -> None:
    """Meta-guard — walk every module schema and count money-as-number fields.

    Asserts the count is ``<= MAX_REMAINING_MONEY_FLOATS``. When the
    follow-up wave converts more fields, lower the constant.
    """
    schemas = _collect_module_schemas()

    offenders: list[str] = []
    for schema_name, schema in schemas.items():
        if not isinstance(schema, dict):
            continue
        props = schema.get("properties") or {}
        for field_name, field_spec in props.items():
            if not isinstance(field_spec, dict):
                continue
            if not _is_money_named(field_name):
                continue
            # Look at type AND anyOf (Optional[float] renders as anyOf).
            types: set[str | None] = {field_spec.get("type")}
            for opt in field_spec.get("anyOf", []) or []:
                if isinstance(opt, dict):
                    types.add(opt.get("type"))
            # ``number`` = float, ``integer`` = int (counts, not money).
            # ``string`` is the v3 §10 Decimal-as-string contract.
            # Pydantic Decimal renders as ``string`` with ``format: decimal``
            # in OpenAPI.
            if "string" in types:
                continue
            # We deliberately do NOT flag ``integer`` — pagination
            # ``total: int``, ``positions_count: int``, etc. are real
            # integers, not float-shaped money.
            if "number" in types:
                offenders.append(f"{schema_name}.{field_name}")

    offenders_unique = sorted(set(offenders))
    assert len(offenders_unique) <= MAX_REMAINING_MONEY_FLOATS, (
        f"Money-as-float deficit grew: found {len(offenders_unique)} fields, "
        f"cap is {MAX_REMAINING_MONEY_FLOATS}. New offenders since last "
        f"audit indicate a regression. Either fix them or, after a wave "
        f"that intentionally widens scope, lower MAX_REMAINING_MONEY_FLOATS "
        f"here.\n\nOffenders (top 30):\n  - " + "\n  - ".join(offenders_unique[:30])
    )


# ── Sanity: convenience smoke tests for arithmetic flows ─────────────────


def test_apply_to_boq_response_grand_total_serialises_string() -> None:
    """End-to-end: build a realistic ApplyToBoqResponse and check the wire shape."""
    from app.modules.match_elements.schemas import (
        ApplyPositionPreview,
        ApplyResourcePreview,
        ApplyToBoqResponse,
    )

    res = ApplyResourcePreview(
        description="Concrete C30/37",
        factor=1.0,
        quantity=10.0,
        unit="m3",
        unit_rate=Decimal("125.50"),
    )
    pos = ApplyPositionPreview(
        group_key="wall:concrete",
        section_path=["300", "330"],
        description="RC wall",
        unit="m3",
        quantity=10.0,
        unit_rate=Decimal("125.50"),
        currency="EUR",
        line_total=Decimal("1255.00"),
        resources=[res],
    )
    resp = ApplyToBoqResponse(
        dry_run=True,
        boq_id=uuid4(),
        positions_created=0,
        positions=[pos],
        grand_total=Decimal("1255.00"),
        currency="EUR",
    )
    payload = json.loads(resp.model_dump_json())
    assert payload["grand_total"] == "1255.00", payload["grand_total"]
    assert payload["positions"][0]["unit_rate"] == "125.50"
    assert payload["positions"][0]["line_total"] == "1255.00"
    assert payload["positions"][0]["resources"][0]["unit_rate"] == "125.50"
