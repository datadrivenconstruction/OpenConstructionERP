// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Input and readout helpers for the wall-area panel of a linear takeoff
 * measurement (wall height + openings).
 *
 * Storage is metric-canonical (D-TKC-016): a wall height and every opening
 * dimension are stored in metres whatever the reader's measurement system.
 * These helpers are the seam between that storage and what the estimator
 * types and reads: metres for a metric reader, decimal feet for an imperial
 * one, so `ft x ft` reads back as `ft²` exactly like the rest of the viewer.
 * The quantity math itself stays in `takeoff-quantity.ts`.
 *
 * Pure and React-free so the panel logic unit-tests on its own.
 */

import type { MeasurementSystem } from '@/stores/usePreferencesStore';
import type { Measurement, WallOpening } from './takeoff-types';
import { convertQuantity } from './takeoff-display-units';
import {
  effectiveQuantity,
  effectiveUnit,
  normalizeOpening,
  wallGrossArea,
  wallOpeningsArea,
} from './takeoff-quantity';

/** Exact international foot. */
export const METRES_PER_FOOT = 0.3048;

/**
 * Parse a length the estimator typed into canonical metres.
 *
 * Accepts a decimal comma ("2,80") as well as a point. A metric reader types
 * metres, an imperial reader decimal feet. Empty, non-numeric, negative or
 * zero input returns null, which the caller reads as "clear the field".
 */
export function parseLengthInput(text: string, system: MeasurementSystem): number | null {
  const cleaned = text.trim().replace(/\s+/g, '').replace(',', '.');
  if (!cleaned) return null;
  const n = Number(cleaned);
  if (!Number.isFinite(n) || n <= 0) return null;
  return system === 'imperial' ? n * METRES_PER_FOOT : n;
}

/**
 * Render a stored length (metres) back into the input box, in the reader's
 * system. Rounded to 3 decimals so a 2.8 m height does not reappear as
 * 2.7999999 after a metres -> feet -> metres round trip. Empty for no value.
 */
export function lengthToInput(metres: number | undefined | null, system: MeasurementSystem): string {
  if (metres == null || !Number.isFinite(metres) || metres <= 0) return '';
  const v = system === 'imperial' ? metres / METRES_PER_FOOT : metres;
  return String(Math.round(v * 1000) / 1000);
}

/** Parse an opening count: a whole number >= 1, or null when invalid. */
export function parseCountInput(text: string): number | null {
  const n = Number(text.trim());
  if (!Number.isFinite(n)) return null;
  const whole = Math.floor(n);
  return whole >= 1 ? whole : null;
}

/** Append an opening, normalized. */
export function addOpening(
  openings: readonly WallOpening[] | undefined,
  opening: Partial<WallOpening>,
): WallOpening[] {
  return [...(openings ?? []), normalizeOpening(opening)];
}

/** Replace fields of the opening at `index`; out-of-range is a no-op copy. */
export function updateOpening(
  openings: readonly WallOpening[] | undefined,
  index: number,
  patch: Partial<WallOpening>,
): WallOpening[] {
  return (openings ?? []).map((o, i) => (i === index ? normalizeOpening({ ...o, ...patch }) : o));
}

/** Remove the opening at `index`. */
export function removeOpening(openings: readonly WallOpening[] | undefined, index: number): WallOpening[] {
  return (openings ?? []).filter((_, i) => i !== index);
}

/**
 * Store-ready openings list: undefined when empty, so a wall with no openings
 * carries no key at all (and clearing the last one clears the stored list).
 */
export function openingsForStore(openings: readonly WallOpening[]): WallOpening[] | undefined {
  return openings.length > 0 ? [...openings] : undefined;
}

/** Numbers behind the "length x height = area" readout, in the reader's system. */
export interface WallBreakdown {
  length: number;
  lengthUnit: string;
  height: number;
  gross: number;
  openings: number;
  /** The reported figure, wastage and multiplier included. */
  reported: number;
  areaUnit: string;
}

/**
 * Convert a wall's stored figures into the reader's system for the panel
 * readout. Area values go through the area conversion (m² -> ft²), never by
 * squaring a converted length, so the readout matches the ledger exactly.
 */
export function wallBreakdown(m: Measurement, system: MeasurementSystem): WallBreakdown {
  const lengthUnit = m.unit || 'm';
  // The area unit a wall of this length unit reports in; asked as if a height
  // were set so the readout also has a unit while the height is still blank.
  const areaUnit = effectiveUnit({ type: 'distance', unit: lengthUnit, wallHeight: 1 });
  const length = convertQuantity(Number.isFinite(m.value) ? m.value : 0, lengthUnit, system);
  const height = convertQuantity(m.wallHeight ?? 0, lengthUnit, system);
  const gross = convertQuantity(wallGrossArea(m), areaUnit, system);
  const openings = convertQuantity(wallOpeningsArea(m), areaUnit, system);
  const reported = convertQuantity(Math.abs(effectiveQuantity(m)), areaUnit, system);
  return {
    length: length.value,
    lengthUnit: length.unit,
    height: height.value,
    gross: gross.value,
    openings: openings.value,
    reported: reported.value,
    areaUnit: gross.unit,
  };
}
