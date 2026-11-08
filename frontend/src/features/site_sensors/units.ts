// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Sensor units: the store is SI, the display follows the project's unit system.
 * Labels go through i18n (`site_sensors.units.<key>`); this file only maps and converts.
 */

export type UnitSystem = 'metric' | 'imperial';

/** Unit keys the page shows; each has a `site_sensors.units.<key>` label. */
export type UnitKey =
  | 'degC'
  | 'degF'
  | 'degC_h'
  | 'degF_h'
  | 'h'
  | 'mpa'
  | 'psi'
  | 'mm_s'
  | 'in_s'
  | 'dba'
  | 'ugm3'
  | 'm'
  | 'ft'
  | 'm_s'
  | 'mph';

/** English fallbacks for `site_sensors.units.<key>`. */
export const UNIT_LABELS: Record<UnitKey, string> = {
  degC: '°C',
  degF: '°F',
  degC_h: '°C·h',
  degF_h: '°F·h',
  h: 'h',
  mpa: 'MPa',
  psi: 'psi',
  mm_s: 'mm/s',
  in_s: 'in/s',
  dba: 'dB(A)',
  ugm3: 'µg/m³',
  m: 'm',
  ft: 'ft',
  m_s: 'm/s',
  mph: 'mph',
};

const STORED: Record<string, UnitKey> = {
  degc: 'degC',
  '°c': 'degC',
  'db(a)': 'dba',
  dba: 'dba',
  'ug/m3': 'ugm3',
  'µg/m³': 'ugm3',
  'μg/m³': 'ugm3',
  'mm/s': 'mm_s',
  'm/s': 'm_s',
  m: 'm',
};

/** The unit key of a stored device unit string, or null for a unit the page does not know. */
export function unitKeyOf(stored: string | null | undefined): UnitKey | null {
  if (!stored) return null;
  return STORED[stored.trim().toLowerCase()] ?? null;
}

const IMPERIAL: Partial<Record<UnitKey, { to: UnitKey; convert: (v: number) => number }>> = {
  degC: { to: 'degF', convert: (v) => (v * 9) / 5 + 32 },
  // A degree-hour is a temperature difference times time: scale only, no offset.
  degC_h: { to: 'degF_h', convert: (v) => v * 1.8 },
  mpa: { to: 'psi', convert: (v) => v * 145.0377 },
  mm_s: { to: 'in_s', convert: (v) => v / 25.4 },
  m: { to: 'ft', convert: (v) => v / 0.3048 },
  m_s: { to: 'mph', convert: (v) => v * 2.236936 },
};

/** A stored SI value as the project shows it: same value and key for metric or unmapped units. */
export function toDisplay(value: number, key: UnitKey, system: UnitSystem): { value: number; unit: UnitKey } {
  const rule = system === 'imperial' ? IMPERIAL[key] : undefined;
  return rule ? { value: rule.convert(value), unit: rule.to } : { value, unit: key };
}

/** The display unit key for an SI key in a unit system. */
export function displayUnit(key: UnitKey, system: UnitSystem): UnitKey {
  return toDisplay(0, key, system).unit;
}

/** Decimals worth showing for a display unit. */
export function decimalsFor(unit: UnitKey): number {
  if (unit === 'psi' || unit === 'degC_h' || unit === 'degF_h') return 0;
  if (unit === 'in_s') return 3;
  return 1;
}
