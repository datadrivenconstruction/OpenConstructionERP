// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Survey display and input conventions. Every value is a setting: the project
 * default comes from its country (`core/country_data/survey_plan.json`), a user
 * may override the display. Nothing here names a country.
 */

export type AngleUnit = 'dms' | 'deg' | 'gon';
/** `azimuth`: whole-circle from the zero direction; `quadrant`: N 45°30' E. */
export type DirectionFormat = 'azimuth' | 'quadrant';
export type AzimuthZero = 'north' | 'south';
/**
 * `EN` Easting then Northing; `NE` Northing then Easting; `XY` geodetic X (north)
 * then Y (east); `YX` Y (east) then X (north).
 */
export type AxisConvention = 'EN' | 'NE' | 'XY' | 'YX';
export type LinearUnit = 'm' | 'ft' | 'ftUS';
export type AreaUnit = 'm2' | 'ha' | 'acre' | 'ft2';
export type DistancePrecision = 'mm' | 'cm' | '0.01ft' | '0.001ft';
/** `metric` 0+000.000, `imperial` 0+00.00 (100 ft stations), `km` km 1.234. */
export type ChainageFormat = 'metric' | 'imperial' | 'km';
/** Whether a typed distance is a grid or a ground distance. */
export type DistanceInput = 'grid' | 'ground';

export interface PlanConventions {
  angleUnit: AngleUnit;
  directionFormat: DirectionFormat;
  azimuthZero: AzimuthZero;
  axis: AxisConvention;
  linearUnit: LinearUnit;
  areaUnit: AreaUnit;
  precision: DistancePrecision;
  chainage: ChainageFormat;
  distanceInput: DistanceInput;
  /** Seconds decimals in DMS, decimals in deg/gon are derived from it. */
  angleDecimals: 0 | 1 | 2;
}

/** Neutral defaults when neither the project nor its country says otherwise. */
export const DEFAULT_CONVENTIONS: PlanConventions = {
  angleUnit: 'dms',
  directionFormat: 'azimuth',
  azimuthZero: 'north',
  axis: 'EN',
  linearUnit: 'm',
  areaUnit: 'm2',
  precision: 'mm',
  chainage: 'metric',
  distanceInput: 'grid',
  angleDecimals: 1,
};

export const CONVENTION_OPTIONS = {
  angleUnit: ['dms', 'deg', 'gon'],
  directionFormat: ['azimuth', 'quadrant'],
  azimuthZero: ['north', 'south'],
  axis: ['EN', 'NE', 'XY', 'YX'],
  linearUnit: ['m', 'ft', 'ftUS'],
  areaUnit: ['m2', 'ha', 'acre', 'ft2'],
  precision: ['mm', 'cm', '0.01ft', '0.001ft'],
  chainage: ['metric', 'imperial', 'km'],
  distanceInput: ['grid', 'ground'],
} as const satisfies { [K in keyof Omit<PlanConventions, 'angleDecimals'>]: readonly PlanConventions[K][] };

/** Merge a partial (server or user) onto the defaults, dropping unknown values. */
export function resolveConventions(...layers: (Partial<Record<keyof PlanConventions, unknown>> | null | undefined)[]): PlanConventions {
  const out: PlanConventions = { ...DEFAULT_CONVENTIONS };
  for (const layer of layers) {
    if (!layer) continue;
    for (const [key, allowed] of Object.entries(CONVENTION_OPTIONS) as [keyof typeof CONVENTION_OPTIONS, readonly string[]][]) {
      const v = layer[key];
      if (typeof v === 'string' && allowed.includes(v)) (out as unknown as Record<string, unknown>)[key] = v;
    }
    const d = layer.angleDecimals;
    if (d === 0 || d === 1 || d === 2) out.angleDecimals = d;
  }
  return out;
}
