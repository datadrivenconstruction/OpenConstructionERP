// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/**
 * What a markup line is charged on. Mirrors
 * `backend/app/modules/boq/markup_base.py`, which is the authority; change one
 * and change the other.
 *
 * - `direct_cost`: the sum of the positions.
 * - `cumulative`: the sum of the positions plus every active line above.
 * - `subtotal`: identical to `cumulative`, kept for stored and imported rows.
 * - `same_as_previous`: exactly the base the nearest active line above was
 *   charged on, so Wagnis and Gewinn can both sit on the Selbstkosten. With
 *   no line above, or a fixed amount above (which has no base), it falls back
 *   to the sum of the positions.
 */
export type MarkupApplyTo = 'direct_cost' | 'cumulative' | 'subtotal' | 'same_as_previous';

export function resolveMarkupBase(
  applyTo: string | null | undefined,
  directCost: number,
  running: number,
  previousBase: number | null,
): number {
  if (applyTo === 'same_as_previous') return previousBase ?? directCost;
  if (applyTo === 'cumulative' || applyTo === 'subtotal') return running;
  return directCost;
}

/** A fixed amount has no base; every other type is charged on one. */
export function markupHasBase(markupType: string | null | undefined): boolean {
  return markupType !== 'fixed';
}
