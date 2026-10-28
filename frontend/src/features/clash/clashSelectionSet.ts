// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure derivation for "build a viewer selection set from a set of findings".
 *
 * A coordinator picks several clash / validation findings in the review table
 * and wants to see EVERY element those findings reference, framed together in
 * the 3D viewer. This module turns the chosen findings into:
 *
 *   - the de-duplicated union of all referenced element ids (each clash names
 *     two interfering elements, `a_element_id` / `b_element_id`),
 *   - a single world centroid to frame the camera on (the mean of the chosen
 *     findings' own centroids), and
 *   - the target model id, plus a `mixedModels` flag because the viewer
 *     deep-link addresses ONE model: a selection spanning several models can
 *     only isolate the elements that live in the model it opens.
 *
 * Everything here is a *pure function* over already-fetched `ClashResult`
 * rows - no fetch, no React, no side effects - so it is trivially
 * unit-testable and shared by the page, the bulk-actions bar and the tests.
 * The deep-link URL itself is built by `buildSelectionSetBimLink`
 * (`clashBimLink.ts`) so the `isolate` / `focus` contract lives in one place.
 */

import type { ClashResult } from './api';

/** The resolved selection set derived from a set of findings. */
export interface FindingsSelectionSet {
  /** De-duplicated union of every element id the findings reference, in
   *  first-seen order (a_element_id before b_element_id, finding by finding).
   *  Empty strings / nullish ids are dropped. */
  elementIds: string[];
  /** The model the viewer should open. This is the model that owns the most
   *  referenced elements across the chosen findings; ties break towards the
   *  first finding's `a_model_id` so the result is deterministic. Empty
   *  string when no finding carried a model id. */
  modelId: string;
  /** Camera focus target in the backend's canonical Z-up world frame - the
   *  mean of the chosen findings' centroids, ignoring any non-finite
   *  coordinate. `null` when no finding had a usable centroid. */
  focus: { x: number; y: number; z: number } | null;
  /** True when the chosen findings span more than one model. The viewer
   *  deep-link can only isolate elements in the single `modelId` it opens, so
   *  the UI should warn that elements in other models won't be shown. */
  mixedModels: boolean;
  /** How many distinct findings contributed to this set (after dropping rows
   *  with no usable element id). Drives the "View N elements" affordance. */
  findingCount: number;
}

/** Push an id onto the accumulator if it is a non-empty string not already
 *  present. Mutates `seen` / `out` in place for O(1) dedupe. */
function pushUnique(
  id: string | null | undefined,
  seen: Set<string>,
  out: string[],
): void {
  if (typeof id !== 'string') return;
  const trimmed = id.trim();
  if (trimmed.length === 0 || seen.has(trimmed)) return;
  seen.add(trimmed);
  out.push(trimmed);
}

/**
 * Derive a viewer selection set from a set of clash findings.
 *
 * - Unions both interfering element ids of every finding (de-duplicated,
 *   first-seen order).
 * - Picks the model that owns the most referenced elements as the deep-link
 *   target, and flags `mixedModels` when more than one model is referenced.
 * - Averages the findings' centroids (skipping non-finite coordinates) into a
 *   single focus point so the camera frames the whole group, not one clash.
 *
 * Never throws: an empty input, malformed coordinates or missing ids all
 * degrade to a well-formed, empty-ish result.
 */
export function deriveSelectionSetFromFindings(
  findings: readonly ClashResult[],
): FindingsSelectionSet {
  const seen = new Set<string>();
  const elementIds: string[] = [];
  // Count how many referenced elements each model owns so the deep-link opens
  // the model that shows the most of the selection.
  const modelWeight = new Map<string, number>();
  let firstModelId = '';
  let sumX = 0;
  let sumY = 0;
  let sumZ = 0;
  let focusSamples = 0;
  let findingCount = 0;

  for (const f of findings) {
    if (!f) continue;
    const before = elementIds.length;
    pushUnique(f.a_element_id, seen, elementIds);
    pushUnique(f.b_element_id, seen, elementIds);
    // Only count this finding (and its model / centroid) if it actually
    // contributed at least one new element id - a finding whose ids are all
    // blank or already seen adds nothing to isolate or frame.
    if (elementIds.length === before) continue;
    findingCount += 1;

    if (typeof f.a_model_id === 'string' && f.a_model_id) {
      if (!firstModelId) firstModelId = f.a_model_id;
      modelWeight.set(f.a_model_id, (modelWeight.get(f.a_model_id) ?? 0) + 1);
    }
    if (
      typeof f.b_model_id === 'string' &&
      f.b_model_id &&
      f.b_model_id !== f.a_model_id
    ) {
      if (!firstModelId) firstModelId = f.b_model_id;
      modelWeight.set(f.b_model_id, (modelWeight.get(f.b_model_id) ?? 0) + 1);
    }

    if (
      Number.isFinite(f.cx) &&
      Number.isFinite(f.cy) &&
      Number.isFinite(f.cz)
    ) {
      sumX += f.cx;
      sumY += f.cy;
      sumZ += f.cz;
      focusSamples += 1;
    }
  }

  // Pick the heaviest model (ties → the first finding's model for stability).
  let modelId = '';
  let bestWeight = -1;
  for (const [mid, weight] of modelWeight) {
    if (weight > bestWeight) {
      bestWeight = weight;
      modelId = mid;
    }
  }
  if (!modelId) modelId = firstModelId;

  const focus =
    focusSamples > 0
      ? {
          x: sumX / focusSamples,
          y: sumY / focusSamples,
          z: sumZ / focusSamples,
        }
      : null;

  return {
    elementIds,
    modelId,
    focus,
    mixedModels: modelWeight.size > 1,
    findingCount,
  };
}
