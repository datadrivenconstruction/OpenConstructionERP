// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Attribute a measurement's scale ratio to where it came from.
 *
 * A wrong scale is the one takeoff error that multiplies through every
 * quantity on a sheet. The server stores a ``scale_source`` per measurement so
 * a sheet found to be mis-scaled can be narrowed to the rows that actually
 * inherited the bad ratio, instead of sending the whole document back to be
 * re-checked by hand. Only the drawing surface knows which of the client-side
 * sources applies, so the client has to state it; the server never guesses.
 *
 * The rule this module exists to enforce is that we state a source only when
 * we know one. A provenance field that is sometimes a guess is worse than no
 * field at all, because it is precisely the field a re-scale would trust when
 * deciding which rows to recompute, and a laundered guess would quietly
 * exclude the rows that needed it most.
 */

import type { ScaleSource } from '../api';

/** The union's members at runtime, so the guard below cannot drift from it. */
const SCALE_SOURCES: readonly ScaleSource[] = [
  'page_text',
  'recovered_text',
  'vision_read',
  'manual_calibration',
  'preset',
  'inherited',
];

/**
 * Narrow a scale source that arrived over the wire.
 *
 * The response field is typed as a plain string on purpose: it is data from
 * the network, and claiming it is already one of the six would be an assertion
 * this side cannot make. Callers that want the closed set run it through here,
 * so a value this build does not recognise degrades to "unknown" the way a
 * missing one does, instead of reaching a label lookup that assumes it exists.
 *
 * It lives here rather than next to the type in ``api.ts`` for a practical
 * reason: the api module is mocked wholesale in the persistence tests, and a
 * runtime helper exported from there would be undefined under every such mock.
 * The type import above is erased, so this file still pulls no runtime graph.
 */
export function isScaleSource(value: string | null | undefined): value is ScaleSource {
  return typeof value === 'string' && (SCALE_SOURCES as readonly string[]).includes(value);
}

/**
 * The factory ratio a page sits on before anyone calibrates it.
 *
 * Mirrors ``defaultScaleConfig()`` in the viewer's page-scale model. Kept as a
 * local constant so this module stays free of a cross-layer import; the test
 * pins the two together so they cannot drift apart unnoticed.
 */
export const FACTORY_DEFAULT_PIXELS_PER_UNIT = 100;

/** What the client knows about the page a measurement is being drawn on. */
export interface ScaleAttributionInput {
  /** The ratio being stamped on the measurement, or ``null`` when the page
   *  carries no usable scale. */
  pixelsPerUnit: number | null;
  /** True when the page has its own calibration rather than riding the
   *  document-level default. */
  pageHasOwnCalibration: boolean;
  /** True when that per-page calibration was INFERRED from legacy rows rather
   *  than stated by the user. See {@link inferredCalibrationPages}. */
  calibrationIsInferred: boolean;
}

/**
 * Decide the source to send with a newly created measurement.
 *
 * Returns ``null`` for "we cannot attribute this", which the server stores as
 * NULL and every surface renders as "Unknown". That is a deliberate outcome,
 * not a gap: see the module docstring.
 */
export function attributeScaleSource(
  input: ScaleAttributionInput,
): ScaleSource | null {
  const { pixelsPerUnit, pageHasOwnCalibration, calibrationIsInferred } = input;
  // No usable ratio means nothing was inherited from anywhere. Naming a source
  // for a number we do not have would be confident fiction.
  if (
    typeof pixelsPerUnit !== 'number' ||
    !Number.isFinite(pixelsPerUnit) ||
    pixelsPerUnit <= 0
  ) {
    return null;
  }
  if (pageHasOwnCalibration) {
    // A calibration we only inferred is not one we can attribute to a person.
    return calibrationIsInferred ? null : 'manual_calibration';
  }
  // The page rides the document-level scale: the ratio was chosen once for the
  // set rather than measured on this sheet.
  return 'preset';
}

/** The row shape this module needs; structurally satisfied by the API type. */
export interface ScaleProvenanceRow {
  page: number;
  scale_pixels_per_unit: number | null;
  metadata?: Record<string, unknown> | null;
}

/**
 * Pages whose per-page calibration was inferred rather than stated.
 *
 * The viewer restores per-page calibration from stored measurements. Rows
 * written before the calibration flag existed carry no flag, so the restore
 * falls back to a heuristic: a ratio other than the factory default must have
 * been a real calibration. That heuristic is good enough to restore a usable
 * scale, but it is not good enough to put a person's name on it.
 *
 * A page counts as known, not inferred, as soon as ANY row on it carries the
 * explicit flag, because one row stating the fact settles it for the page.
 */
export function inferredCalibrationPages(
  rows: readonly ScaleProvenanceRow[],
): Set<number> {
  const stated = new Set<number>();
  const guessed = new Set<number>();
  for (const r of rows) {
    const ppu = r.scale_pixels_per_unit;
    if (typeof ppu !== 'number' || !Number.isFinite(ppu) || ppu <= 0) continue;
    const flag = r.metadata?.scale_calibrated;
    if (flag === true) {
      stated.add(r.page);
    } else if (flag !== false && ppu !== FACTORY_DEFAULT_PIXELS_PER_UNIT) {
      // No flag at all and off the factory ratio: the restore will treat this
      // page as calibrated, but only because it guessed.
      guessed.add(r.page);
    }
  }
  for (const page of stated) guessed.delete(page);
  return guessed;
}
