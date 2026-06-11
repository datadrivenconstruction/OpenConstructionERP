# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Canonical building geometry for the Retail Market Heilbronn showcase.

This module is intentionally dependency-free (no ORM, no app stack) so it can
be imported offline by the procedural 3D generator
(:mod:`app.scripts.gen_retail_heilbronn_assets`) without spinning up a database
engine. :mod:`app.core.demo_packs.retail_market_heilbronn` re-exports
:data:`CANONICAL_GEOMETRY` from here, so the LV quantities and the 3D model both
read the same numbers - a single source of truth. Changing a value here changes
both the bill of quantities and the BIM model; the geometry-vs-BOQ test keeps
them in lock-step.
"""

from __future__ import annotations

# Canonical building geometry - see the module docstring. Every value is exact
# and self-consistent (the cross-checks are documented in
# ``retail_market_heilbronn.py``).
CANONICAL_GEOMETRY: dict[str, float] = {
    # Footprint and work area (R-01, R-02)
    "footprint_length_m": 68.0,  # 11 bays x 6.18 m + end overhangs = 68.0 m
    "footprint_width_m": 40.0,
    "footprint_m2": 2720.0,  # 68.0 x 40.0
    "work_area_m2": 2774.0,  # footprint x 1.02 lap allowance (roof layers)
    "perimeter_m": 216.0,  # R-03: 2 x (68 + 40)
    # Structural grid (R-05)
    "grid_axes": 12,  # structural axes along the 68 m length
    "grid_spacing_m": 6.18,  # 11 bays x 6.18 m = 67.98 ~= 68 m
    "bearing_rows": 3,  # two outer rows + one internal row
    "columns": 36,  # 12 axes x 3 bearing rows
    "column_section_m": 0.40,  # 40/40 cm precast RC column
    "column_height_m": 6.4,
    "main_span_m": 23.8,  # sales hall main span
    "side_span_m": 16.2,  # warehouse / staff block side span
    # Foundations (R-06)
    "pocket_foundations": 36,  # one per column
    "pocket_foundation_l_m": 1.8,
    "pocket_foundation_w_m": 1.8,
    "pocket_foundation_d_m": 1.0,
    "frost_skirt_height_m": 0.8,  # perimeter frost skirt
    # Glulam binders (R-05)
    "binders_main": 12,  # 23.8 m binders
    "binders_side": 12,  # 16.2 m binders
    "binders_total": 24,
    "binder_width_m": 0.20,  # GL24h 20/120 cm
    "binder_height_m": 1.20,
    "edge_beams": 22,  # (12 axes - 1) x 2 rows
    # Slab and floor (R-01)
    "slab_thickness_m": 0.20,
    "slab_volume_m3": 544.0,  # 2,720 x 0.20
    # Roof (R-02)
    "rooflights": 8,  # 1.5 x 1.5 m NRWG smoke vents
    "rooflight_size_m": 1.5,
    "attika_height_m": 6.90,  # parapet height (standard run)
    "portal_height_m": 7.50,  # entrance portal parapet
    "clear_height_m": 5.00,  # clear height in the sales hall
    # Envelope (R-04 facade balance, all in m2)
    "facade_sandwich_m2": 1292.0,
    "facade_curtain_wall_m2": 120.0,  # 24.0 x 5.0 m PR glazing
    "facade_window_band_m2": 42.0,  # 28.0 x 1.5 m
    "facade_doors_m2": 13.2,  # 6 steel doors
    "facade_gates_m2": 23.6,  # dock leveller + grade-level gate
    "curtain_wall_length_m": 24.0,
    "curtain_wall_height_m": 5.0,
    # PV (R-13)
    "pv_modules": 660,  # 660 x 440 Wp = 290.4 kWp
    "pv_kwp": 290.0,
    # Outdoor
    "parking_stalls": 112,
    "marking_length_m": 952.0,  # 112 x 8.5 m
}
