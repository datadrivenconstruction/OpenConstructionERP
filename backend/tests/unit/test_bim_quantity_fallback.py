# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the BIM ingest quantity fallback (issue #347).

Pure functions, no database: recover canonical quantities from differently
named columns, and as a last resort from the bounding box.
"""

from app.modules.bim_hub.quantity_fallback import (
    derive_quantities_from_bbox,
    derive_quantities_from_columns,
)


class TestDeriveQuantitiesFromColumns:
    def test_ifc_qto_dotted_column(self) -> None:
        # Qto_<set>.<Quantity> is the DDC IFC export form the fixed list misses.
        out = derive_quantities_from_columns({"Qto_WallBaseQuantities.NetVolume": "9.0"})
        assert out == {"volume": 9.0}

    def test_unit_suffixed_header(self) -> None:
        out = derive_quantities_from_columns({"Volume (m3)": 12.5})
        assert out == {"volume": 12.5}

    def test_prefers_net_over_gross(self) -> None:
        # Both normalise to "area"; the net value is the one to bill.
        out = derive_quantities_from_columns({"GrossArea": 40.0, "NetArea": 37.5})
        assert out["area"] == 37.5

    def test_prefers_net_regardless_of_order(self) -> None:
        out = derive_quantities_from_columns({"NetArea": 37.5, "GrossArea": 40.0})
        assert out["area"] == 37.5

    def test_bare_unit_column(self) -> None:
        out = derive_quantities_from_columns({"m3": 3.0})
        assert out == {"volume": 3.0}

    def test_mass_maps_to_weight(self) -> None:
        out = derive_quantities_from_columns({"Mass (kg)": 120.0})
        assert out == {"weight": 120.0}

    def test_ignores_identifier_and_text_columns(self) -> None:
        # "Number" normalises to the count synonym, which is deliberately not a
        # fallback dimension; identifiers and text must never become quantities.
        out = derive_quantities_from_columns({"Mark": "W-12", "Number": "5", "Comments": "load-bearing"})
        assert out == {}

    def test_ignores_zero_and_negative(self) -> None:
        out = derive_quantities_from_columns({"Volume": 0.0, "Area": -2.0})
        assert out == {}

    def test_none_values_skipped(self) -> None:
        out = derive_quantities_from_columns({"Volume": None, "Length (m)": 5.0})
        assert out == {"length": 5.0}


class TestDeriveQuantitiesFromBbox:
    def test_linear_member_gets_length(self) -> None:
        bbox = {"min_x": 0, "min_y": 0, "min_z": 0, "max_x": 5.0, "max_y": 0.2, "max_z": 0.3}
        out = derive_quantities_from_bbox(bbox, "Structural Framing")
        assert out == {"length": 5.0}

    def test_planar_element_gets_area_and_volume(self) -> None:
        bbox = {"min_x": 0, "min_y": 0, "min_z": 0, "max_x": 4.0, "max_y": 0.24, "max_z": 3.0}
        out = derive_quantities_from_bbox(bbox, "Basic Wall")
        assert out["area"] == 12.0  # two largest extents: 4.0 * 3.0
        assert round(out["volume"], 4) == 2.88  # 4.0 * 3.0 * 0.24

    def test_solid_unknown_gets_volume(self) -> None:
        bbox = {"min_x": 0, "min_y": 0, "min_z": 0, "max_x": 2.0, "max_y": 2.0, "max_z": 2.0}
        out = derive_quantities_from_bbox(bbox, "Furniture")
        assert out == {"volume": 8.0}

    def test_none_bbox_returns_empty(self) -> None:
        assert derive_quantities_from_bbox(None, "Basic Wall") == {}

    def test_degenerate_zero_box_returns_empty(self) -> None:
        bbox = {"min_x": 1, "min_y": 1, "min_z": 1, "max_x": 1, "max_y": 1, "max_z": 1}
        assert derive_quantities_from_bbox(bbox, "Basic Wall") == {}

    def test_incomplete_bbox_returns_empty(self) -> None:
        bbox = {"min_x": 0, "min_y": 0, "min_z": 0, "max_x": 4.0, "max_y": 3.0}
        assert derive_quantities_from_bbox(bbox, "Basic Wall") == {}
