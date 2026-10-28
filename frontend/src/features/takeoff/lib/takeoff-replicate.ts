// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Replicate takeoff measurements onto other pages.
 *
 * A common takeoff shortcut: a "typical floor" detail (a slab outline, a run
 * of columns, a count of fixtures) is measured once and repeats on many
 * identical sheets. Rather than redrawing it, the estimator copies the drawn
 * measurement(s) onto the other pages. This is the pure core of that action -
 * it clones the source measurements onto each target page and hands the fresh
 * rows back; the caller appends them to state and persists them the same way a
 * freshly drawn measurement is.
 *
 * Kept dependency-free (only the shared Measurement type) so it unit-tests
 * without React or pdf.js.
 */

import type { Measurement } from './takeoff-types';

/**
 * Clone `sources` onto every page in `targetPages`, returning fresh
 * measurements.
 *
 * Each clone keeps the source's geometry, group, annotation, colour, appearance
 * overrides and quantity adjustments, but is given a NEW id (via `makeId`) and
 * the target page, and has its server identity, BOQ link and AI-suggestion
 * flags cleared - so a copy is an independent, unsynced, unlinked measurement
 * rather than a second row aliasing the source's server object / BOQ position
 * (the same identity-reset rule the in-page "duplicate" action uses).
 *
 * A target page equal to a source's OWN page is skipped, so "copy to pages"
 * never stacks a measurement on top of itself. Points are deep-copied so the
 * clone never aliases the source geometry. Pure + side-effect-free.
 *
 * @param makeId called per clone to mint a unique id; receives the source
 *   measurement, the target page, and a running index across all clones.
 */
export function replicateMeasurementsToPages(
  sources: readonly Measurement[],
  targetPages: readonly number[],
  makeId: (source: Measurement, page: number, index: number) => string,
): Measurement[] {
  const out: Measurement[] = [];
  // De-duplicate + order target pages so callers can pass a raw selection.
  const pages = Array.from(new Set(targetPages)).sort((a, b) => a - b);
  let index = 0;
  for (const page of pages) {
    if (!Number.isFinite(page) || page < 1) continue;
    for (const src of sources) {
      if (src.page === page) continue; // never clone onto its own page
      out.push({
        ...src,
        id: makeId(src, page, index++),
        page,
        points: src.points.map((p) => ({ x: p.x, y: p.y })),
        serverId: undefined,
        suggested: undefined,
        confidence: undefined,
        linkedPositionId: undefined,
        linkedPositionOrdinal: undefined,
        linkedBoqId: undefined,
        linkedPositionLabel: undefined,
      });
    }
  }
  return out;
}
