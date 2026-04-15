/**
 * BIM category and type constants for Revit and IFC formats.
 *
 * Used by the BIM Rules page for format-aware parameter-based filtering:
 * - User selects Revit or IFC format
 * - Dropdowns populate with format-specific categories/types
 * - Filter parameters change based on format selection
 */

/* ── Revit Categories ──────────────────────────────────────────────────── */

export const REVIT_CATEGORIES = [
  'Walls',
  'Floors',
  'Roofs',
  'Ceilings',
  'Doors',
  'Windows',
  'Columns',
  'Structural Columns',
  'Beams',
  'Structural Framing',
  'Foundations',
  'Structural Foundations',
  'Stairs',
  'Railings',
  'Ramps',
  'Curtain Panels',
  'Curtain Wall Mullions',
  'Curtain Systems',
  'Generic Models',
  'Specialty Equipment',
  'Plumbing Fixtures',
  'Mechanical Equipment',
  'Electrical Equipment',
  'Electrical Fixtures',
  'Lighting Fixtures',
  'Communication Devices',
  'Fire Alarm Devices',
  'Ducts',
  'Duct Fittings',
  'Duct Accessories',
  'Pipes',
  'Pipe Fittings',
  'Pipe Accessories',
  'Cable Trays',
  'Cable Tray Fittings',
  'Conduits',
  'Conduit Fittings',
  'Sprinklers',
  'Flex Ducts',
  'Flex Pipes',
  'Furniture',
  'Furniture Systems',
  'Casework',
  'Mass',
  'Parking',
  'Planting',
  'Site',
  'Topography',
  'Rooms',
  'Spaces',
  'Areas',
] as const;

export type RevitCategory = (typeof REVIT_CATEGORIES)[number];

/** Revit filter parameters: Category, Type Name, Family */
export const REVIT_FILTER_PARAMS = ['Category', 'Type Name', 'Family'] as const;

/** Common Revit property names for the "parameter to check" column. */
export const REVIT_PROPERTY_NAMES = [
  'Width',
  'Height',
  'Length',
  'Thickness',
  'Area',
  'Volume',
  'Perimeter',
  'Mark',
  'Type Mark',
  'Comments',
  'Description',
  'Structural Material',
  'Material',
  'Fire Rating',
  'Phase Created',
  'Phase Demolished',
  'Level',
  'Base Level',
  'Top Level',
  'Base Offset',
  'Top Offset',
  'Unconnected Height',
  'Assembly Code',
  'Assembly Description',
  'Keynote',
  'Model',
  'Manufacturer',
  'URL',
  'Cost',
  'Head Height',
  'Sill Height',
  'Rough Width',
  'Rough Height',
  'Function',
  'Structural Usage',
  'Insulation Thickness',
  'Coarse Scale Fill Pattern',
  'Absorption Coefficient',
  'Thermal Resistance (R)',
  'Thermal Mass',
  'Heat Transfer Coefficient (U)',
  'Slope',
  'Span Direction',
] as const;

/* ── IFC Types ─────────────────────────────────────────────────────────── */

export const IFC_TYPES = [
  'IfcWall',
  'IfcWallStandardCase',
  'IfcSlab',
  'IfcDoor',
  'IfcWindow',
  'IfcColumn',
  'IfcBeam',
  'IfcStair',
  'IfcStairFlight',
  'IfcRailing',
  'IfcRoof',
  'IfcCovering',
  'IfcCurtainWall',
  'IfcPlate',
  'IfcMember',
  'IfcFooting',
  'IfcPile',
  'IfcRamp',
  'IfcRampFlight',
  'IfcSpace',
  'IfcBuildingElementProxy',
  'IfcOpeningElement',
  'IfcFurnishingElement',
  'IfcDistributionElement',
  'IfcFlowTerminal',
  'IfcFlowSegment',
  'IfcFlowFitting',
  'IfcFlowController',
  'IfcEnergyConversionDevice',
  'IfcFlowMovingDevice',
  'IfcFlowStorageDevice',
  'IfcFlowTreatmentDevice',
  'IfcSanitaryTerminal',
  'IfcLightFixture',
  'IfcElectricAppliance',
  'IfcCableCarrierSegment',
  'IfcCableSegment',
  'IfcDuctSegment',
  'IfcDuctFitting',
  'IfcPipeSegment',
  'IfcPipeFitting',
  'IfcFastener',
  'IfcMechanicalFastener',
  'IfcReinforcingBar',
  'IfcReinforcingMesh',
  'IfcTendon',
  'IfcBuildingStorey',
  'IfcSite',
  'IfcBuilding',
  'IfcProxy',
] as const;

export type IFCType = (typeof IFC_TYPES)[number];

/** IFC filter parameters: Name, Category (entity class), ObjectType */
export const IFC_FILTER_PARAMS = ['Name', 'Category', 'ObjectType'] as const;

/** Common IFC property names for the "parameter to check" column. */
export const IFC_PROPERTY_NAMES = [
  'IsExternal',
  'LoadBearing',
  'FireRating',
  'ThermalTransmittance',
  'AcousticRating',
  'Combustible',
  'SurfaceSpreadOfFlame',
  'Compartmentation',
  'Reference',
  'Status',
  'GrossArea',
  'NetArea',
  'GrossVolume',
  'NetVolume',
  'GrossSideArea',
  'NetSideArea',
  'Width',
  'Height',
  'Length',
  'Depth',
  'NominalLength',
  'NominalWidth',
  'NominalHeight',
  'Perimeter',
  'Span',
  'Slope',
  'Roll',
  'Material',
  'Finish',
  'Color',
  'Pset_WallCommon',
  'Pset_SlabCommon',
  'Pset_DoorCommon',
  'Pset_WindowCommon',
  'Pset_ColumnCommon',
  'Pset_BeamCommon',
  'Pset_CoveringCommon',
  'Pset_RoofCommon',
  'Pset_StairCommon',
  'Pset_RailingCommon',
] as const;

/* ── Format discriminator ──────────────────────────────────────────────── */

export type BIMFormat = 'revit' | 'ifc';

/** Given a format, return the list of categories / entity types. */
export function getCategoriesForFormat(format: BIMFormat): readonly string[] {
  return format === 'revit' ? REVIT_CATEGORIES : IFC_TYPES;
}

/** Given a format, return the filter parameter names. */
export function getFilterParamsForFormat(format: BIMFormat): readonly string[] {
  return format === 'revit' ? REVIT_FILTER_PARAMS : IFC_FILTER_PARAMS;
}

/** Given a format, return common property names for the check column. */
export function getPropertyNamesForFormat(format: BIMFormat): readonly string[] {
  return format === 'revit' ? REVIT_PROPERTY_NAMES : IFC_PROPERTY_NAMES;
}

/* ── Constraint types for requirements rules ──────────────────────────── */

export const CONSTRAINT_TYPES = [
  'equals',
  'not_equals',
  'min',
  'max',
  'range',
  'contains',
  'not_contains',
  'regex',
  'exists',
  'not_exists',
] as const;

export type ConstraintType = (typeof CONSTRAINT_TYPES)[number];

/** Human-friendly labels for constraint types. */
export const CONSTRAINT_TYPE_LABELS: Record<ConstraintType, string> = {
  equals: '= equals',
  not_equals: '!= not equal',
  min: '>= minimum',
  max: '<= maximum',
  range: '[min..max]',
  contains: 'contains',
  not_contains: 'not contains',
  regex: 'regex',
  exists: 'exists (any value)',
  not_exists: 'must not exist',
};
