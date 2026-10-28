// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Frontend mirror of backend/app/modules/match_elements/ifc_labels.py.
// One i18n key per IFC class so localised UIs render "Стена" / "Wand"
// instead of the raw "IfcWallStandardCase" string. Order/coverage must
// stay in sync with the backend table — extending one without the
// other leaves users with mixed labels.

export interface IfcClassMeta {
  enLabel: string;
  i18nKey: string;
  trade:
    | 'architectural'
    | 'structural'
    | 'mep'
    | 'civil'
    | 'spatial'
    | 'subtractive'
    | 'annotation'
    | 'other';
  isSubtractive?: boolean;
}

export const IFC_LABELS: Record<string, IfcClassMeta> = {
  // Architectural
  IfcWall:                  { enLabel: 'Wall',                i18nKey: 'ifc.wall',                trade: 'architectural' },
  IfcWallStandardCase:      { enLabel: 'Wall',                i18nKey: 'ifc.wall',                trade: 'architectural' },
  IfcCurtainWall:           { enLabel: 'Curtain wall',        i18nKey: 'ifc.curtain_wall',        trade: 'architectural' },
  IfcDoor:                  { enLabel: 'Door',                i18nKey: 'ifc.door',                trade: 'architectural' },
  IfcWindow:                { enLabel: 'Window',              i18nKey: 'ifc.window',              trade: 'architectural' },
  IfcRoof:                  { enLabel: 'Roof',                i18nKey: 'ifc.roof',                trade: 'architectural' },
  IfcSlab:                  { enLabel: 'Slab',                i18nKey: 'ifc.slab',                trade: 'architectural' },
  IfcStair:                 { enLabel: 'Stair',               i18nKey: 'ifc.stair',               trade: 'architectural' },
  IfcStairFlight:           { enLabel: 'Stair flight',        i18nKey: 'ifc.stair_flight',        trade: 'architectural' },
  IfcRamp:                  { enLabel: 'Ramp',                i18nKey: 'ifc.ramp',                trade: 'architectural' },
  IfcRampFlight:            { enLabel: 'Ramp flight',         i18nKey: 'ifc.ramp_flight',         trade: 'architectural' },
  IfcRailing:               { enLabel: 'Railing',             i18nKey: 'ifc.railing',             trade: 'architectural' },
  IfcCovering:              { enLabel: 'Covering',            i18nKey: 'ifc.covering',            trade: 'architectural' },
  IfcShadingDevice:         { enLabel: 'Shading device',      i18nKey: 'ifc.shading_device',      trade: 'architectural' },
  IfcChimney:               { enLabel: 'Chimney',             i18nKey: 'ifc.chimney',             trade: 'architectural' },
  IfcFurniture:             { enLabel: 'Furniture',           i18nKey: 'ifc.furniture',           trade: 'architectural' },
  IfcFurnishingElement:     { enLabel: 'Furnishing',          i18nKey: 'ifc.furnishing',          trade: 'architectural' },
  IfcSystemFurnitureElement:{ enLabel: 'System furniture',    i18nKey: 'ifc.system_furniture',    trade: 'architectural' },

  // Structural
  IfcBeam:                  { enLabel: 'Beam',                i18nKey: 'ifc.beam',                trade: 'structural' },
  IfcBeamStandardCase:      { enLabel: 'Beam',                i18nKey: 'ifc.beam',                trade: 'structural' },
  IfcColumn:                { enLabel: 'Column',              i18nKey: 'ifc.column',              trade: 'structural' },
  IfcColumnStandardCase:    { enLabel: 'Column',              i18nKey: 'ifc.column',              trade: 'structural' },
  IfcFooting:               { enLabel: 'Footing',             i18nKey: 'ifc.footing',             trade: 'structural' },
  IfcPile:                  { enLabel: 'Pile',                i18nKey: 'ifc.pile',                trade: 'structural' },
  IfcMember:                { enLabel: 'Structural member',   i18nKey: 'ifc.member',              trade: 'structural' },
  IfcPlate:                 { enLabel: 'Structural plate',    i18nKey: 'ifc.plate',               trade: 'structural' },
  IfcReinforcingBar:        { enLabel: 'Rebar',               i18nKey: 'ifc.rebar',               trade: 'structural' },
  IfcReinforcingMesh:       { enLabel: 'Reinforcing mesh',    i18nKey: 'ifc.rebar_mesh',          trade: 'structural' },
  IfcTendon:                { enLabel: 'Tendon',              i18nKey: 'ifc.tendon',              trade: 'structural' },
  IfcTendonAnchor:          { enLabel: 'Tendon anchor',       i18nKey: 'ifc.tendon_anchor',       trade: 'structural' },
  IfcStructuralCurveMember: { enLabel: 'Curve member',        i18nKey: 'ifc.curve_member',        trade: 'structural' },
  IfcStructuralSurfaceMember:{ enLabel: 'Surface member',     i18nKey: 'ifc.surface_member',      trade: 'structural' },

  // MEP — HVAC
  IfcAirTerminal:           { enLabel: 'Air terminal',        i18nKey: 'ifc.air_terminal',        trade: 'mep' },
  IfcAirTerminalBox:        { enLabel: 'Air terminal box',    i18nKey: 'ifc.air_terminal_box',    trade: 'mep' },
  IfcDuctSegment:           { enLabel: 'Duct',                i18nKey: 'ifc.duct_segment',        trade: 'mep' },
  IfcDuctFitting:           { enLabel: 'Duct fitting',        i18nKey: 'ifc.duct_fitting',        trade: 'mep' },
  IfcDuctSilencer:          { enLabel: 'Duct silencer',       i18nKey: 'ifc.duct_silencer',       trade: 'mep' },
  IfcDamper:                { enLabel: 'Damper',              i18nKey: 'ifc.damper',              trade: 'mep' },
  IfcFan:                   { enLabel: 'Fan',                 i18nKey: 'ifc.fan',                 trade: 'mep' },
  IfcChiller:               { enLabel: 'Chiller',             i18nKey: 'ifc.chiller',             trade: 'mep' },
  IfcBoiler:                { enLabel: 'Boiler',              i18nKey: 'ifc.boiler',              trade: 'mep' },
  IfcCoolingTower:          { enLabel: 'Cooling tower',       i18nKey: 'ifc.cooling_tower',       trade: 'mep' },
  IfcAirToAirHeatRecovery:  { enLabel: 'Heat recovery',       i18nKey: 'ifc.heat_recovery',       trade: 'mep' },
  IfcCoil:                  { enLabel: 'Coil',                i18nKey: 'ifc.coil',                trade: 'mep' },
  IfcUnitaryEquipment:      { enLabel: 'Unitary equipment',   i18nKey: 'ifc.unitary_equipment',   trade: 'mep' },
  IfcSpaceHeater:           { enLabel: 'Space heater',        i18nKey: 'ifc.space_heater',        trade: 'mep' },
  // MEP — Plumbing
  IfcPipeSegment:           { enLabel: 'Pipe',                i18nKey: 'ifc.pipe_segment',        trade: 'mep' },
  IfcPipeFitting:           { enLabel: 'Pipe fitting',        i18nKey: 'ifc.pipe_fitting',        trade: 'mep' },
  IfcSanitaryTerminal:      { enLabel: 'Sanitary terminal',   i18nKey: 'ifc.sanitary_terminal',   trade: 'mep' },
  IfcValve:                 { enLabel: 'Valve',               i18nKey: 'ifc.valve',               trade: 'mep' },
  IfcPump:                  { enLabel: 'Pump',                i18nKey: 'ifc.pump',                trade: 'mep' },
  IfcTank:                  { enLabel: 'Tank',                i18nKey: 'ifc.tank',                trade: 'mep' },
  IfcWasteTerminal:         { enLabel: 'Waste terminal',      i18nKey: 'ifc.waste_terminal',      trade: 'mep' },
  IfcInterceptor:           { enLabel: 'Interceptor',         i18nKey: 'ifc.interceptor',         trade: 'mep' },
  IfcStackTerminal:         { enLabel: 'Stack terminal',      i18nKey: 'ifc.stack_terminal',      trade: 'mep' },
  // MEP — Electrical
  IfcCableSegment:          { enLabel: 'Cable',               i18nKey: 'ifc.cable_segment',       trade: 'mep' },
  IfcCableCarrierSegment:   { enLabel: 'Cable tray',          i18nKey: 'ifc.cable_carrier',       trade: 'mep' },
  IfcCableCarrierFitting:   { enLabel: 'Cable tray fitting',  i18nKey: 'ifc.cable_carrier_fitting', trade: 'mep' },
  IfcCableFitting:          { enLabel: 'Cable fitting',       i18nKey: 'ifc.cable_fitting',       trade: 'mep' },
  IfcLightFixture:          { enLabel: 'Light fixture',       i18nKey: 'ifc.light_fixture',       trade: 'mep' },
  IfcSwitchingDevice:       { enLabel: 'Switch',              i18nKey: 'ifc.switching_device',    trade: 'mep' },
  IfcOutlet:                { enLabel: 'Outlet',              i18nKey: 'ifc.outlet',              trade: 'mep' },
  IfcElectricDistributionBoard:{ enLabel: 'Distribution board', i18nKey: 'ifc.distribution_board', trade: 'mep' },
  IfcElectricAppliance:     { enLabel: 'Electric appliance',  i18nKey: 'ifc.electric_appliance',  trade: 'mep' },
  IfcElectricMotor:         { enLabel: 'Electric motor',      i18nKey: 'ifc.electric_motor',      trade: 'mep' },
  IfcTransformer:           { enLabel: 'Transformer',         i18nKey: 'ifc.transformer',         trade: 'mep' },
  IfcMotorConnection:       { enLabel: 'Motor connection',    i18nKey: 'ifc.motor_connection',    trade: 'mep' },
  IfcProtectiveDevice:      { enLabel: 'Protective device',   i18nKey: 'ifc.protective_device',   trade: 'mep' },
  // MEP — Fire / comms
  IfcFireSuppressionTerminal:{ enLabel: 'Fire suppression terminal', i18nKey: 'ifc.fire_terminal', trade: 'mep' },
  IfcAlarm:                 { enLabel: 'Alarm',               i18nKey: 'ifc.alarm',               trade: 'mep' },
  IfcSensor:                { enLabel: 'Sensor',              i18nKey: 'ifc.sensor',              trade: 'mep' },
  IfcCommunicationsAppliance:{ enLabel: 'Comms appliance',    i18nKey: 'ifc.comms_appliance',     trade: 'mep' },
  IfcFlowMeter:             { enLabel: 'Flow meter',          i18nKey: 'ifc.flow_meter',          trade: 'mep' },
  IfcFlowController:        { enLabel: 'Flow controller',     i18nKey: 'ifc.flow_controller',     trade: 'mep' },
  IfcDistributionElement:   { enLabel: 'Distribution element', i18nKey: 'ifc.distribution_element', trade: 'mep' },
  IfcDistributionFlowElement:{ enLabel: 'Distribution flow element', i18nKey: 'ifc.distribution_flow_element', trade: 'mep' },
  IfcDistributionControlElement:{ enLabel: 'Distribution control element', i18nKey: 'ifc.distribution_control_element', trade: 'mep' },
  IfcEnergyConversionDevice:{ enLabel: 'Energy conversion device', i18nKey: 'ifc.energy_conversion_device', trade: 'mep' },

  // Civil
  IfcRoad:                  { enLabel: 'Road',                i18nKey: 'ifc.road',                trade: 'civil' },
  IfcRailway:               { enLabel: 'Railway',             i18nKey: 'ifc.railway',             trade: 'civil' },
  IfcBridge:                { enLabel: 'Bridge',              i18nKey: 'ifc.bridge',              trade: 'civil' },
  IfcTunnel:                { enLabel: 'Tunnel',              i18nKey: 'ifc.tunnel',              trade: 'civil' },
  IfcPavement:              { enLabel: 'Pavement',            i18nKey: 'ifc.pavement',            trade: 'civil' },
  IfcKerb:                  { enLabel: 'Kerb',                i18nKey: 'ifc.kerb',                trade: 'civil' },
  IfcCourse:                { enLabel: 'Course',              i18nKey: 'ifc.course',              trade: 'civil' },
  IfcEarthworksFill:        { enLabel: 'Earthworks fill',     i18nKey: 'ifc.earthworks_fill',     trade: 'civil' },
  IfcEarthworksCut:         { enLabel: 'Earthworks cut',      i18nKey: 'ifc.earthworks_cut',      trade: 'civil' },
  IfcReinforcedSoil:        { enLabel: 'Reinforced soil',     i18nKey: 'ifc.reinforced_soil',     trade: 'civil' },
  IfcGeographicElement:     { enLabel: 'Geographic element',  i18nKey: 'ifc.geographic_element',  trade: 'civil' },
  IfcAlignment:             { enLabel: 'Alignment',           i18nKey: 'ifc.alignment',           trade: 'civil' },
  IfcRail:                  { enLabel: 'Rail',                i18nKey: 'ifc.rail',                trade: 'civil' },

  // Spatial
  IfcProject:               { enLabel: 'Project',             i18nKey: 'ifc.project',             trade: 'spatial' },
  IfcSite:                  { enLabel: 'Site',                i18nKey: 'ifc.site',                trade: 'spatial' },
  IfcBuilding:              { enLabel: 'Building',            i18nKey: 'ifc.building',            trade: 'spatial' },
  IfcBuildingStorey:        { enLabel: 'Storey',              i18nKey: 'ifc.storey',              trade: 'spatial' },
  IfcSpace:                 { enLabel: 'Space',               i18nKey: 'ifc.space',               trade: 'spatial' },
  IfcZone:                  { enLabel: 'Zone',                i18nKey: 'ifc.zone',                trade: 'spatial' },

  // Subtractive
  IfcOpeningElement:        { enLabel: 'Opening void',        i18nKey: 'ifc.opening_element',     trade: 'subtractive', isSubtractive: true },
  IfcOpeningStandardCase:   { enLabel: 'Opening void',        i18nKey: 'ifc.opening_element',     trade: 'subtractive', isSubtractive: true },
  IfcVoidingFeature:        { enLabel: 'Voiding feature',     i18nKey: 'ifc.voiding_feature',     trade: 'subtractive', isSubtractive: true },
  IfcVirtualElement:        { enLabel: 'Virtual separator',   i18nKey: 'ifc.virtual_element',     trade: 'subtractive', isSubtractive: true },
  IfcAnnotation:            { enLabel: 'Annotation',          i18nKey: 'ifc.annotation',          trade: 'annotation',  isSubtractive: true },
  IfcGrid:                  { enLabel: 'Grid',                i18nKey: 'ifc.grid',                trade: 'annotation',  isSubtractive: true },
  IfcGridAxis:              { enLabel: 'Grid axis',           i18nKey: 'ifc.grid_axis',           trade: 'annotation',  isSubtractive: true },

  // Suspect
  IfcBuildingElementProxy:  { enLabel: 'Generic element (proxy)', i18nKey: 'ifc.proxy',           trade: 'other' },
  IfcDiscreteAccessory:     { enLabel: 'Accessory',           i18nKey: 'ifc.accessory',           trade: 'other' },
  IfcMechanicalFastener:    { enLabel: 'Fastener',            i18nKey: 'ifc.fastener',            trade: 'other' },
  IfcFastener:              { enLabel: 'Fastener',            i18nKey: 'ifc.fastener',            trade: 'other' },
  IfcElementAssembly:       { enLabel: 'Element assembly',    i18nKey: 'ifc.element_assembly',    trade: 'other' },
  IfcBuiltElement:          { enLabel: 'Built element',       i18nKey: 'ifc.built_element',       trade: 'other' },
};

const UNKNOWN: IfcClassMeta = {
  enLabel: 'Element',
  i18nKey: 'ifc.unknown',
  trade: 'other',
};

export function lookupIfcClass(ifcClass: string | null | undefined): IfcClassMeta {
  if (!ifcClass) return UNKNOWN;
  const meta = IFC_LABELS[ifcClass];
  if (meta) return meta;
  return {
    enLabel: ifcClass.replace(/^Ifc/, '') || 'Element',
    i18nKey: 'ifc.unknown',
    trade: 'other',
  };
}

/** Resolve the human label for an IFC class via i18n with English fallback. */
export function ifcClassLabel(
  t: (k: string, opts?: Record<string, unknown>) => string,
  ifcClass: string | null | undefined,
): string {
  const meta = lookupIfcClass(ifcClass);
  return t(meta.i18nKey, { defaultValue: meta.enLabel });
}
