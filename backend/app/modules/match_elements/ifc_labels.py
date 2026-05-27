# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Canonical IFC class metadata for human-readable group display.

Source of truth for:

    * the human label rendered next to a group in the match-elements UI
      ("Wall · Concrete C30/37 · 200mm · Level 1" instead of the raw
      ``IfcWallStandardCase`` pipe-string), and
    * the trade taxonomy used to default-group the workspace by
      Architectural / Structural / MEP / Civil / Spatial, and
    * the subtractive-element flag that drives auto-exclusion of voids,
      annotations and analytical placeholders from the priced scope.

The table is keyed by canonical IFC class name (CamelCase, IFC 4.3
spelling) and falls back to a deterministic ``Ifc → ""`` strip when an
unknown class is queried — so a brand-new IFC entity ships without a
crash, just an underlabelled chip.

The frontend mirrors this table as i18n keys ``ifc.<snake>``; the
``i18n_key`` field tells the frontend which key to look up. Translations
that don't ship for a locale fall through to the ``en_label`` here.
"""

from __future__ import annotations

from typing import Literal, NamedTuple

Trade = Literal[
    "architectural",
    "structural",
    "mep",
    "civil",
    "spatial",
    "subtractive",
    "annotation",
    "other",
]


class IfcClassMeta(NamedTuple):
    """‌⁠‍Metadata one IFC class carries through the matcher pipeline."""

    en_label: str
    i18n_key: str
    trade: Trade
    # Suggested DIN 276 cost group (3-digit). A hint, not authoritative —
    # actual classification stays many-to-many per the CWICR catalogue.
    din276_hint: str | None = None
    # When True, the class is a void/annotation/analytical placeholder
    # the cost workflow skips by default (auto-excluded on session
    # create). Estimators can opt back in via the settings rail.
    is_subtractive: bool = False
    # Suggested MasterFormat (CSI 50-division, US) prefix. A 4-digit or
    # 6-digit prefix narrows the candidate pool for US projects. Only
    # populated where the IFC → MasterFormat cross-walk is 1:1 enough to
    # be safe; ambiguous classes leave it unset (the matcher then falls
    # back to vector ranking only). Examples: IfcWall=04 21 00,
    # IfcSlab=03 30 53, IfcDuctSegment=23 31 13.
    masterformat_hint: str | None = None
    # Suggested NRM (RICS New Rules of Measurement, UK) prefix. Same
    # philosophy as masterformat_hint — only set on safe cross-walks.
    # Examples: IfcWall="2.5", IfcSlab="2.4", IfcDuctSegment="5.4".
    nrm_hint: str | None = None


# ── Architectural envelope + interior ────────────────────────────────────


def _arch(label: str, key: str, din: str | None, mf: str | None = None, nrm: str | None = None) -> IfcClassMeta:
    """‌⁠‍Architectural-trade IfcClassMeta with full standards crosswalk."""
    return IfcClassMeta(label, key, "architectural", din, False, mf, nrm)


_ARCH: dict[str, IfcClassMeta] = {
    # Walls — structural concrete vs CMU vs partitions all map to the
    # same head; the matcher uses material_class to disambiguate.
    "IfcWall": _arch("Wall", "ifc.wall", "330", "04 21 00", "2.5"),
    "IfcWallStandardCase": _arch("Wall", "ifc.wall", "330", "04 21 00", "2.5"),
    "IfcCurtainWall": _arch("Curtain wall", "ifc.curtain_wall", "334", "08 44 00", "2.6"),
    "IfcDoor": _arch("Door", "ifc.door", "334", "08 11 00", "2.6"),
    "IfcWindow": _arch("Window", "ifc.window", "334", "08 50 00", "2.6"),
    "IfcRoof": _arch("Roof", "ifc.roof", "360", "07 00 00", "2.7"),
    "IfcSlab": _arch("Slab", "ifc.slab", "350", "03 30 00", "2.4"),
    "IfcStair": _arch("Stair", "ifc.stair", "351", "05 51 00", "2.5"),
    "IfcStairFlight": _arch("Stair flight", "ifc.stair_flight", "351", "05 51 00", "2.5"),
    "IfcRamp": _arch("Ramp", "ifc.ramp", "351", "05 51 00", "2.5"),
    "IfcRampFlight": _arch("Ramp flight", "ifc.ramp_flight", "351", "05 51 00", "2.5"),
    "IfcRailing": _arch("Railing", "ifc.railing", "351", "05 52 00", "2.5"),
    "IfcCovering": _arch("Covering", "ifc.covering", "352", "09 00 00", "3.1"),
    "IfcShadingDevice": _arch("Shading device", "ifc.shading_device", "338", "10 71 00", "2.6"),
    "IfcChimney": _arch("Chimney", "ifc.chimney", "330", "04 51 00", "2.5"),
    "IfcFurniture": _arch("Furniture", "ifc.furniture", "611", "12 00 00", "4"),
    "IfcFurnishingElement": _arch("Furnishing", "ifc.furnishing", "611", "12 00 00", "4"),
    "IfcSystemFurnitureElement": _arch("System furniture", "ifc.system_furniture", "611", "12 60 00", "4"),
}


# ── Structural ───────────────────────────────────────────────────────────


def _struct(label: str, key: str, din: str | None, mf: str | None = None, nrm: str | None = None) -> IfcClassMeta:
    """Structural-trade IfcClassMeta with full standards crosswalk."""
    return IfcClassMeta(label, key, "structural", din, False, mf, nrm)


_STRUCT: dict[str, IfcClassMeta] = {
    "IfcBeam": _struct("Beam", "ifc.beam", "320", "03 41 00", "2.5.1"),
    "IfcBeamStandardCase": _struct("Beam", "ifc.beam", "320", "03 41 00", "2.5.1"),
    "IfcColumn": _struct("Column", "ifc.column", "320", "03 30 00", "2.5.1"),
    "IfcColumnStandardCase": _struct("Column", "ifc.column", "320", "03 30 00", "2.5.1"),
    "IfcFooting": _struct("Footing", "ifc.footing", "322", "03 30 00", "2.1"),
    "IfcPile": _struct("Pile", "ifc.pile", "322", "31 62 00", "2.1"),
    "IfcMember": _struct("Structural member", "ifc.member", "320", "05 12 00", "2.5"),
    "IfcPlate": _struct("Structural plate", "ifc.plate", "320", "05 12 00", "2.5"),
    "IfcReinforcingBar": _struct("Rebar", "ifc.rebar", "320", "03 21 00", "2.5"),
    "IfcReinforcingMesh": _struct("Reinforcing mesh", "ifc.rebar_mesh", "320", "03 22 00", "2.5"),
    "IfcTendon": _struct("Tendon", "ifc.tendon", "320", "03 23 00", "2.5"),
    "IfcTendonAnchor": _struct("Tendon anchor", "ifc.tendon_anchor", "320", "03 23 00", "2.5"),
    "IfcStructuralCurveMember": _struct("Curve member", "ifc.curve_member", "320", "05 12 00", "2.5"),
    "IfcStructuralSurfaceMember": _struct("Surface member", "ifc.surface_member", "320", "05 12 00", "2.5"),
}


# ── MEP / Building services ──────────────────────────────────────────────


_MEP: dict[str, IfcClassMeta] = {
    # HVAC
    "IfcAirTerminal": IfcClassMeta("Air terminal", "ifc.air_terminal", "mep", "430"),
    "IfcAirTerminalBox": IfcClassMeta("Air terminal box", "ifc.air_terminal_box", "mep", "430"),
    "IfcDuctSegment": IfcClassMeta("Duct", "ifc.duct_segment", "mep", "430"),
    "IfcDuctFitting": IfcClassMeta("Duct fitting", "ifc.duct_fitting", "mep", "430"),
    "IfcDuctSilencer": IfcClassMeta("Duct silencer", "ifc.duct_silencer", "mep", "430"),
    "IfcDamper": IfcClassMeta("Damper", "ifc.damper", "mep", "430"),
    "IfcFan": IfcClassMeta("Fan", "ifc.fan", "mep", "430"),
    "IfcChiller": IfcClassMeta("Chiller", "ifc.chiller", "mep", "430"),
    "IfcBoiler": IfcClassMeta("Boiler", "ifc.boiler", "mep", "420"),
    "IfcCoolingTower": IfcClassMeta("Cooling tower", "ifc.cooling_tower", "mep", "430"),
    "IfcAirToAirHeatRecovery": IfcClassMeta("Heat recovery", "ifc.heat_recovery", "mep", "430"),
    "IfcCoil": IfcClassMeta("Coil", "ifc.coil", "mep", "430"),
    "IfcUnitaryEquipment": IfcClassMeta("Unitary equipment", "ifc.unitary_equipment", "mep", "430"),
    "IfcSpaceHeater": IfcClassMeta("Space heater", "ifc.space_heater", "mep", "420"),
    # Plumbing
    "IfcPipeSegment": IfcClassMeta("Pipe", "ifc.pipe_segment", "mep", "410"),
    "IfcPipeFitting": IfcClassMeta("Pipe fitting", "ifc.pipe_fitting", "mep", "410"),
    "IfcSanitaryTerminal": IfcClassMeta("Sanitary terminal", "ifc.sanitary_terminal", "mep", "410"),
    "IfcValve": IfcClassMeta("Valve", "ifc.valve", "mep", "410"),
    "IfcPump": IfcClassMeta("Pump", "ifc.pump", "mep", "410"),
    "IfcTank": IfcClassMeta("Tank", "ifc.tank", "mep", "410"),
    "IfcWasteTerminal": IfcClassMeta("Waste terminal", "ifc.waste_terminal", "mep", "410"),
    "IfcInterceptor": IfcClassMeta("Interceptor", "ifc.interceptor", "mep", "410"),
    "IfcStackTerminal": IfcClassMeta("Stack terminal", "ifc.stack_terminal", "mep", "410"),
    # Electrical
    "IfcCableSegment": IfcClassMeta("Cable", "ifc.cable_segment", "mep", "445"),
    "IfcCableCarrierSegment": IfcClassMeta("Cable tray", "ifc.cable_carrier", "mep", "445"),
    "IfcCableCarrierFitting": IfcClassMeta("Cable tray fitting", "ifc.cable_carrier_fitting", "mep", "445"),
    "IfcCableFitting": IfcClassMeta("Cable fitting", "ifc.cable_fitting", "mep", "445"),
    "IfcLightFixture": IfcClassMeta("Light fixture", "ifc.light_fixture", "mep", "445"),
    "IfcSwitchingDevice": IfcClassMeta("Switch", "ifc.switching_device", "mep", "445"),
    "IfcOutlet": IfcClassMeta("Outlet", "ifc.outlet", "mep", "445"),
    "IfcElectricDistributionBoard": IfcClassMeta("Distribution board", "ifc.distribution_board", "mep", "445"),
    "IfcElectricAppliance": IfcClassMeta("Electric appliance", "ifc.electric_appliance", "mep", "445"),
    "IfcElectricMotor": IfcClassMeta("Electric motor", "ifc.electric_motor", "mep", "445"),
    "IfcTransformer": IfcClassMeta("Transformer", "ifc.transformer", "mep", "445"),
    "IfcMotorConnection": IfcClassMeta("Motor connection", "ifc.motor_connection", "mep", "445"),
    "IfcProtectiveDevice": IfcClassMeta("Protective device", "ifc.protective_device", "mep", "445"),
    # Fire / Comms
    "IfcFireSuppressionTerminal": IfcClassMeta("Fire suppression terminal", "ifc.fire_terminal", "mep", "474"),
    "IfcAlarm": IfcClassMeta("Alarm", "ifc.alarm", "mep", "474"),
    "IfcSensor": IfcClassMeta("Sensor", "ifc.sensor", "mep", "474"),
    "IfcCommunicationsAppliance": IfcClassMeta("Comms appliance", "ifc.comms_appliance", "mep", "445"),
    "IfcFlowMeter": IfcClassMeta("Flow meter", "ifc.flow_meter", "mep", "410"),
    "IfcFlowController": IfcClassMeta("Flow controller", "ifc.flow_controller", "mep", "410"),
    "IfcDistributionElement": IfcClassMeta("Distribution element", "ifc.distribution_element", "mep", "400"),
    "IfcDistributionFlowElement": IfcClassMeta(
        "Distribution flow element", "ifc.distribution_flow_element", "mep", "400"
    ),
    "IfcDistributionControlElement": IfcClassMeta(
        "Distribution control element", "ifc.distribution_control_element", "mep", "400"
    ),
    "IfcEnergyConversionDevice": IfcClassMeta("Energy conversion device", "ifc.energy_conversion_device", "mep", "420"),
}


# ── Civil / infra (IFC 4.3+) ─────────────────────────────────────────────


_CIVIL: dict[str, IfcClassMeta] = {
    "IfcRoad": IfcClassMeta("Road", "ifc.road", "civil", "560"),
    "IfcRailway": IfcClassMeta("Railway", "ifc.railway", "civil", "560"),
    "IfcBridge": IfcClassMeta("Bridge", "ifc.bridge", "civil", "560"),
    "IfcTunnel": IfcClassMeta("Tunnel", "ifc.tunnel", "civil", "560"),
    "IfcPavement": IfcClassMeta("Pavement", "ifc.pavement", "civil", "560"),
    "IfcKerb": IfcClassMeta("Kerb", "ifc.kerb", "civil", "560"),
    "IfcCourse": IfcClassMeta("Course", "ifc.course", "civil", "560"),
    "IfcEarthworksFill": IfcClassMeta("Earthworks fill", "ifc.earthworks_fill", "civil", "510"),
    "IfcEarthworksCut": IfcClassMeta("Earthworks cut", "ifc.earthworks_cut", "civil", "510"),
    "IfcReinforcedSoil": IfcClassMeta("Reinforced soil", "ifc.reinforced_soil", "civil", "510"),
    "IfcGeographicElement": IfcClassMeta("Geographic element", "ifc.geographic_element", "civil", "510"),
    "IfcAlignment": IfcClassMeta("Alignment", "ifc.alignment", "civil", "560"),
    "IfcRail": IfcClassMeta("Rail", "ifc.rail", "civil", "560"),
}


# ── Spatial / logical (NOT priced — used for grouping) ───────────────────


_SPATIAL: dict[str, IfcClassMeta] = {
    "IfcProject": IfcClassMeta("Project", "ifc.project", "spatial"),
    "IfcSite": IfcClassMeta("Site", "ifc.site", "spatial"),
    "IfcBuilding": IfcClassMeta("Building", "ifc.building", "spatial"),
    "IfcBuildingStorey": IfcClassMeta("Storey", "ifc.storey", "spatial"),
    "IfcSpace": IfcClassMeta("Space", "ifc.space", "spatial"),
    "IfcZone": IfcClassMeta("Zone", "ifc.zone", "spatial"),
}


# ── Subtractive / annotations / proxies (auto-excluded by default) ───────


_SUBTRACTIVE: dict[str, IfcClassMeta] = {
    "IfcOpeningElement": IfcClassMeta("Opening void", "ifc.opening_element", "subtractive", is_subtractive=True),
    "IfcOpeningStandardCase": IfcClassMeta("Opening void", "ifc.opening_element", "subtractive", is_subtractive=True),
    "IfcVoidingFeature": IfcClassMeta("Voiding feature", "ifc.voiding_feature", "subtractive", is_subtractive=True),
    "IfcVirtualElement": IfcClassMeta("Virtual separator", "ifc.virtual_element", "subtractive", is_subtractive=True),
    "IfcAnnotation": IfcClassMeta("Annotation", "ifc.annotation", "annotation", is_subtractive=True),
    "IfcGrid": IfcClassMeta("Grid", "ifc.grid", "annotation", is_subtractive=True),
    "IfcGridAxis": IfcClassMeta("Grid axis", "ifc.grid_axis", "annotation", is_subtractive=True),
}


# ── Always-suspect (proxy / fastener — needs reclassification) ───────────


_SUSPECT: dict[str, IfcClassMeta] = {
    "IfcBuildingElementProxy": IfcClassMeta("Generic element (proxy)", "ifc.proxy", "other"),
    "IfcDiscreteAccessory": IfcClassMeta("Accessory", "ifc.accessory", "other"),
    "IfcMechanicalFastener": IfcClassMeta("Fastener", "ifc.fastener", "other"),
    "IfcFastener": IfcClassMeta("Fastener", "ifc.fastener", "other"),
    "IfcElementAssembly": IfcClassMeta("Element assembly", "ifc.element_assembly", "other"),
    "IfcBuiltElement": IfcClassMeta("Built element", "ifc.built_element", "other"),
}


_TABLE: dict[str, IfcClassMeta] = {
    **_ARCH,
    **_STRUCT,
    **_MEP,
    **_CIVIL,
    **_SPATIAL,
    **_SUBTRACTIVE,
    **_SUSPECT,
}


# Default exclusion set materialised on every fresh session. Estimators
# never price a void or a grid axis, but they sometimes want to inspect
# them — the settings rail offers a "show non-billable" toggle that
# clears this list temporarily.
DEFAULT_EXCLUDED_CATEGORIES: tuple[str, ...] = tuple(cls for cls, meta in _TABLE.items() if meta.is_subtractive)


def lookup(ifc_class: str | None) -> IfcClassMeta:
    """Best-effort metadata lookup for an IFC class name.

    Unknown classes are returned with a deterministic ``Ifc → ""``
    stripped fallback label so the UI never shows a literal IFC string.
    """
    if not ifc_class:
        return IfcClassMeta("Element", "ifc.unknown", "other")
    meta = _TABLE.get(ifc_class)
    if meta is not None:
        return meta
    # Fallback — strip "Ifc" prefix, leave the rest.
    fallback = ifc_class
    if fallback.startswith("Ifc"):
        fallback = fallback[3:]
    return IfcClassMeta(fallback or "Element", "ifc.unknown", "other")


def is_subtractive(ifc_class: str | None) -> bool:
    """True for IFC classes that should be excluded from priced scope by default."""
    return lookup(ifc_class).is_subtractive


def trade_for(ifc_class: str | None) -> Trade:
    """Return the trade bucket for an IFC class."""
    return lookup(ifc_class).trade
