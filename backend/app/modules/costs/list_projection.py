"""Compact database inputs for the existing ``lite=true`` list response.

Keep the Python Decimal build-up calculation authoritative. It needs component
prices and variant-slot presence, but not the large variant catalogues or the
component descriptions that the response discards. Project those inputs in SQL
without loading a partially populated CostItem into the session identity map.
"""

from sqlalchemy import JSON, literal_column

from app.modules.costs.models import CostItem

LITE_METADATA_KEYS = (
    "variant_stats",
    "labor_cost",
    "material_cost",
    "equipment_cost",
    "other_cost",
    "labor_hours",
    "workers_per_unit",
    "scope_of_work",
)


def _variant_marker(expression: str) -> str:
    # has_variant_slot only reads whether this is an array with >= 2 entries.
    # Nested CASE avoids calling jsonb_array_length on malformed legacy values.
    return f"""CASE WHEN jsonb_typeof({expression}) = 'array' THEN
        CASE WHEN jsonb_array_length({expression}) >= 2
        THEN '[null,null]'::jsonb ELSE '[]'::jsonb END
        ELSE '[]'::jsonb END"""


def _project_jsonb(expression: str, column: str):
    # JSONB is the modern schema. Legacy JSON may carry values JSONB rejects
    # (e.g. escaped NUL in a discarded description), so keep the existing full
    # read/trim path for that column. pg_typeof does not inspect the JSON value.
    return literal_column(
        f"CASE WHEN pg_typeof(oe_costs_item.{column}) = 'jsonb'::regtype "
        f"THEN ({expression})::json ELSE oe_costs_item.{column}::json END",
        type_=JSON,
    )


def lite_columns() -> list:
    """Select scalar fields plus compact JSON; response serialization is shared."""
    components = _project_jsonb(
        f"""CASE WHEN jsonb_typeof(oe_costs_item.components::jsonb) = 'array' THEN
        (SELECT COALESCE(jsonb_agg(CASE WHEN jsonb_typeof(c.value) = 'object'
            THEN jsonb_build_object(
                'cost', c.value->'cost',
                'quantity', c.value->'quantity',
                'unit_rate', c.value->'unit_rate',
                'available_variant_stats', c.value->'available_variant_stats',
                'available_variants', {_variant_marker("c.value->'available_variants'")}
            ) ELSE c.value END ORDER BY c.ordinality), '[]'::jsonb)
         FROM jsonb_array_elements(oe_costs_item.components::jsonb) WITH ORDINALITY AS c(value, ordinality))
        ELSE oe_costs_item.components::jsonb END""",
        "components",
    ).label("components")
    keys = ", ".join(f"'{key}'" for key in (*LITE_METADATA_KEYS, "variants"))
    metadata = _project_jsonb(
        f"""CASE WHEN jsonb_typeof(oe_costs_item.metadata::jsonb) = 'object' THEN
        (SELECT COALESCE(jsonb_object_agg(m.key, CASE WHEN m.key = 'variants'
            THEN {_variant_marker("m.value")} ELSE m.value END), '{{}}'::jsonb)
         FROM jsonb_each(oe_costs_item.metadata::jsonb) AS m(key, value)
         WHERE m.key IN ({keys})) ELSE oe_costs_item.metadata::jsonb END""",
        "metadata",
    ).label("metadata_")
    return [
        getattr(CostItem, prop.key).label(prop.key)
        for prop in CostItem.__mapper__.column_attrs
        if prop.key not in {"components", "metadata_"}
    ] + [components, metadata]
