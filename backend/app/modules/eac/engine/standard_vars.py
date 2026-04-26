# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Standard FR-1.7 element variables auto-resolved by the validator.

These names are the ``${variable_name}`` references that the executor
will hand-pull from each canonical-format element row at run time. They
do NOT need an :class:`EacParameterAlias` entry — the validator skips
the alias-existence check when the name appears in :data:`STANDARD_VARIABLES`.

A real attempt to use an unknown name (not standard, not a local var,
not a global var, not an alias) raises ``unknown_variable``.
"""

from __future__ import annotations

# Standard geometric / quantity properties produced by the canonical CAD
# converter for every element. Names are case-sensitive.
STANDARD_VARIABLES: frozenset[str] = frozenset(
    {
        "Volume",
        "Area",
        "Length",
        "Width",
        "Height",
        "Thickness",
        "Weight",
        "Mass",
        "Perimeter",
        "Count",
        "Diameter",
        "Radius",
        "Depth",
    }
)


def is_standard_variable(name: str) -> bool:
    """Return ``True`` iff ``name`` is a built-in element variable."""
    return name in STANDARD_VARIABLES


__all__ = ["STANDARD_VARIABLES", "is_standard_variable"]
