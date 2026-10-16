# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The warning a CAD import carries when it could not extract quantities.

When the DDC cad2data converter is missing, an IFC upload still imports its
elements through the text parser, but quantities can only come from explicit
IfcElementQuantity blocks in the file. Such a model is stored as ``degraded``,
not ``ready``, with a stable ``error_code`` in its metadata. The API lifts that
code to ``BIMModelResponse.error_code`` and the UI renders its own translated
text from it; ``message`` is the English fallback kept in ``error_message`` for
API readers and logs.
"""

from __future__ import annotations

from typing import NamedTuple

# Stable codes, mirrored by ``frontend/src/shared/lib/bimQuantityWarning.ts``.
NO_QUANTITIES_CONVERTER_ABSENT = "no_quantities_converter_absent"
CONVERTER_ABSENT = "converter_absent"
NO_QUANTITIES = "no_quantities"

QUANTITY_WARNING_CODES: frozenset[str] = frozenset({NO_QUANTITIES_CONVERTER_ABSENT, CONVERTER_ABSENT, NO_QUANTITIES})


class QuantityWarning(NamedTuple):
    """A machine-readable code plus its English fallback text."""

    code: str
    message: str


def quantity_warning(*, converter_absent: bool, no_quantities: bool) -> QuantityWarning | None:
    """Return the warning for an import, or ``None`` when quantities came through.

    Args:
        converter_absent: The DDC converter was not available, so the file was
            read by the fallback parser with placeholder geometry.
        no_quantities: Not one imported element carries a non-zero quantity.
    """
    if converter_absent and no_quantities:
        return QuantityWarning(
            NO_QUANTITIES_CONVERTER_ABSENT,
            "Geometry imported, but no quantities could be extracted: the DDC "
            "cad2data converter is not available on this server, and the file "
            "does not carry explicit IFC BaseQuantities. Elements were imported "
            "for geometry/linking only. Install the DDC converter (Settings → "
            "BIM Converters) and click Retry to recover area/volume/length "
            "quantities.",
        )
    if converter_absent:
        return QuantityWarning(
            CONVERTER_ABSENT,
            "Imported with placeholder geometry: the DDC cad2data converter is "
            "not available on this server, so quantities were read from the "
            "file's embedded IFC BaseQuantities only and may be incomplete. "
            "Install the DDC converter (Settings → BIM Converters) and click "
            "Retry for full geometry-derived quantities.",
        )
    if no_quantities:
        return QuantityWarning(
            NO_QUANTITIES,
            "Geometry imported, but no quantities (area/volume/length) could be "
            "extracted from this file. Elements were imported for "
            "geometry/linking only.",
        )
    return None
