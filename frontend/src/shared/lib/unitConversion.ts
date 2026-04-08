/**
 * Unit conversion utility for metric ↔ imperial.
 *
 * Used by QuantityDisplay to auto-convert values when the user
 * preference differs from the source measurement system.
 */

export interface ConversionResult {
  value: number;
  unit: string;
  displayUnit: string;
}

interface ConversionEntry {
  factor: number;
  unit: string;
  display: string;
}

const METRIC_TO_IMPERIAL: Record<string, ConversionEntry> = {
  m: { factor: 3.2808399, unit: 'ft', display: 'ft' },
  m2: { factor: 10.7639, unit: 'ft2', display: 'sq ft' },
  m3: { factor: 35.3147, unit: 'ft3', display: 'cu ft' },
  kg: { factor: 2.20462, unit: 'lb', display: 'lb' },
  km: { factor: 0.621371, unit: 'mi', display: 'mi' },
  cm: { factor: 0.393701, unit: 'in', display: 'in' },
  mm: { factor: 0.0393701, unit: 'in', display: 'in' },
  t: { factor: 1.10231, unit: 'ton', display: 'ton' },
  lm: { factor: 3.28084, unit: 'lft', display: 'l.ft' },
};

const IMPERIAL_TO_METRIC: Record<string, ConversionEntry> = {
  ft: { factor: 0.3048, unit: 'm', display: 'm' },
  ft2: { factor: 0.092903, unit: 'm2', display: 'm\u00B2' },
  ft3: { factor: 0.0283168, unit: 'm3', display: 'm\u00B3' },
  lb: { factor: 0.453592, unit: 'kg', display: 'kg' },
  mi: { factor: 1.60934, unit: 'km', display: 'km' },
  in: { factor: 25.4, unit: 'mm', display: 'mm' },
  ton: { factor: 0.907185, unit: 't', display: 't' },
  lft: { factor: 0.3048, unit: 'lm', display: 'l.m' },
  'sq ft': { factor: 0.092903, unit: 'm2', display: 'm\u00B2' },
  'cu ft': { factor: 0.0283168, unit: 'm3', display: 'm\u00B3' },
};

/** Display-friendly labels for common metric units. */
const METRIC_DISPLAY: Record<string, string> = {
  m: 'm',
  m2: 'm\u00B2',
  m3: 'm\u00B3',
  kg: 'kg',
  km: 'km',
  cm: 'cm',
  mm: 'mm',
  t: 't',
  lm: 'l.m',
};

/** Display-friendly labels for common imperial units. */
const IMPERIAL_DISPLAY: Record<string, string> = {
  ft: 'ft',
  ft2: 'sq ft',
  ft3: 'cu ft',
  lb: 'lb',
  mi: 'mi',
  in: 'in',
  ton: 'ton',
  lft: 'l.ft',
};

/**
 * Returns the human-friendly display string for a unit code.
 * Falls back to the raw unit code when no mapping is available.
 */
export function getDisplayUnit(unit: string): string {
  return METRIC_DISPLAY[unit] ?? IMPERIAL_DISPLAY[unit] ?? unit;
}

/**
 * Detect whether a unit belongs to the metric system.
 * Returns `true` for metric units, `false` for imperial, `null` for unknowns.
 */
export function isMetricUnit(unit: string): boolean | null {
  if (unit in METRIC_TO_IMPERIAL || unit in METRIC_DISPLAY) return true;
  if (unit in IMPERIAL_TO_METRIC || unit in IMPERIAL_DISPLAY) return false;
  return null;
}

/**
 * Convert a value from its source unit to the target measurement system.
 *
 * If the unit is already in the target system, or no conversion exists,
 * the value is returned unchanged with a display-friendly unit label.
 */
export function convertUnit(
  value: number,
  fromUnit: string,
  toSystem: 'metric' | 'imperial',
): ConversionResult {
  const unitLower = fromUnit.toLowerCase().trim();
  const unitKey = fromUnit.trim();

  // Target is imperial — convert from metric
  if (toSystem === 'imperial') {
    const entry = METRIC_TO_IMPERIAL[unitKey] ?? METRIC_TO_IMPERIAL[unitLower];
    if (entry) {
      return {
        value: value * entry.factor,
        unit: entry.unit,
        displayUnit: entry.display,
      };
    }
  }

  // Target is metric — convert from imperial
  if (toSystem === 'metric') {
    const entry = IMPERIAL_TO_METRIC[unitKey] ?? IMPERIAL_TO_METRIC[unitLower];
    if (entry) {
      return {
        value: value * entry.factor,
        unit: entry.unit,
        displayUnit: entry.display,
      };
    }
  }

  // No conversion available — return as-is with display label
  return {
    value,
    unit: fromUnit,
    displayUnit: getDisplayUnit(fromUnit),
  };
}
