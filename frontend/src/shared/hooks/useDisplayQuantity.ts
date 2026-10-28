// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * useDisplayQuantity — the React seam for measurement-system-aware quantities.
 *
 * Reads the user's `measurementSystem` preference once (selector-scoped, so a
 * component only re-renders when that one preference changes) and returns a
 * small, memoised API bound to it. Every non-takeoff surface that renders or
 * exports a metric-canonical quantity should go through this hook instead of
 * touching the converter directly, so the metric/imperial decision lives in
 * exactly one place.
 *
 *   const q = useDisplayQuantity();
 *   const { value, unit } = q.convert(area, 'm²');   // -> ft² for imperial
 *   const label = q.unitFor('m');                    // -> 'ft' for imperial
 *   const stored = q.toMetric(typed, 'm²');          // editable-cell reverse
 */
import { useMemo } from 'react';

import { usePreferencesStore, type MeasurementSystem } from '@/stores/usePreferencesStore';
import {
  toDisplayQuantity,
  displayUnitFor,
  fromDisplayQuantity,
  conversionFactorFor,
  toDisplayRate,
  fromDisplayRate,
  type DisplayQuantity,
} from '@/shared/lib/unitConversion';

export interface DisplayQuantityApi {
  /** The active measurement system. */
  system: MeasurementSystem;
  /** Convert a metric-canonical value + unit into the display system. */
  convert: (value: number, metricUnit: string) => DisplayQuantity;
  /** The display unit label a metric unit resolves to (no value needed). */
  unitFor: (metricUnit: string) => string;
  /** Reverse a value a user typed in the display system back to metric storage. */
  toMetric: (value: number, metricUnit: string) => number;
  /**
   * Re-express a per-unit rate (money / metric unit) against the displayed
   * unit so a converted line reconciles (50/m -> 15.24/ft). The line total is
   * invariant; only the per-unit basis changes.
   */
  convertRate: (rate: number, metricUnit: string) => number;
  /** Reverse a rate typed against the displayed unit back to metric storage. */
  toMetricRate: (rate: number, metricUnit: string) => number;
  /** The scalar a metric unit scales by (1 for metric / unmapped units). */
  factorFor: (metricUnit: string) => number;
}

export function useDisplayQuantity(): DisplayQuantityApi {
  const system = usePreferencesStore((s) => s.measurementSystem);
  return useMemo(
    () => ({
      system,
      convert: (value: number, metricUnit: string) =>
        toDisplayQuantity(value, metricUnit, system),
      unitFor: (metricUnit: string) => displayUnitFor(metricUnit, system),
      toMetric: (value: number, metricUnit: string) =>
        fromDisplayQuantity(value, metricUnit, system),
      convertRate: (rate: number, metricUnit: string) =>
        toDisplayRate(rate, metricUnit, system),
      toMetricRate: (rate: number, metricUnit: string) =>
        fromDisplayRate(rate, metricUnit, system),
      factorFor: (metricUnit: string) => conversionFactorFor(metricUnit, system),
    }),
    [system],
  );
}
