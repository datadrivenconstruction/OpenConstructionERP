# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The Smart View property catalog shows Revit's own property names.

Property keys are stored lowercased ("phase created"); the header text the
converter wrote is kept on the model as ``column_labels``. Property search used
it, the Smart View builder still printed the lowercased key.
"""

from __future__ import annotations

from app.modules.bim_hub.smart_views import build_property_catalog


def _labels_by_field(**kwargs: object) -> dict[str, str]:
    elements = [{"properties": {"phase created": "Nuova costruzione", "fire_rating": "EI60"}}]
    return {e.field: e.label for e in build_property_catalog(elements, "rvt", **kwargs)}


def test_the_converter_header_is_the_label() -> None:
    labels = _labels_by_field(labels={"phase created": "Phase Created"})
    assert labels["properties.phase created"] == "Phase Created"


def test_a_key_without_a_header_keeps_the_readable_fallback() -> None:
    labels = _labels_by_field(labels={"phase created": "Phase Created"})
    assert labels["properties.fire_rating"] == "fire rating"
    assert _labels_by_field()["properties.phase created"] == "phase created"
