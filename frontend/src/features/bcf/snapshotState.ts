// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Which of the three "no picture" states a BCF viewpoint thumbnail is in.
 *
 * A crossed-out image is a failure affordance. Drawing it for a viewpoint that
 * simply never carried a PNG makes a register of perfectly healthy issues read
 * as a grid of broken pictures, and that is how it gets reported. The BCF
 * schema makes the snapshot optional, the demo seeder writes a null snapshot
 * key on purpose, and an issue raised from a clash result never had a picture
 * and never will - so "no image" is the ordinary case, not the failure. The
 * three states are:
 *
 *   'failed'        the PNG exists and would not load. The only real failure,
 *                   and the only one that earns the crossed-out glyph.
 *   'no_snapshot'   there IS a viewpoint - a camera the reader can fly the
 *                   model to - it just carries no image. A crosshair says what
 *                   is there rather than what is not.
 *   'no_viewpoint'  the issue was raised outside a viewer. Nothing is wrong and
 *                   nothing is missing, so neither glyph belongs.
 *
 * `null` means the thumbnail has a picture to draw.
 *
 * This lives beside the `Viewpoint` type rather than inside either screen
 * because two screens render the same thumbnail from the same data: the
 * project issue register (`features/bcf/BcfIssuesPanel`) and the Model Review
 * dock (`features/bim/ReviewIssuesDock`). They were written apart and drifted:
 * the dock went on drawing all of the nothings as one broken picture, and told
 * a reader whose snapshot had failed to load that no snapshot was ever taken.
 * A shared decision is what keeps the two surfaces saying the same thing.
 */

import type { Viewpoint } from './api';

/** The placeholder a thumbnail draws when it has no picture to show. */
export type SnapshotPlaceholder = 'failed' | 'no_snapshot' | 'no_viewpoint';

/**
 * Pick the placeholder for a thumbnail, or `null` when a picture is available.
 *
 * @param viewpoint The viewpoint being drawn, or `null` when the issue carries
 *   none at all.
 * @param failed Whether the snapshot fetch has already been tried and lost.
 *   Only meaningful when the viewpoint declares a snapshot: a viewpoint with no
 *   PNG is never fetched, so it can never fail.
 */
export function snapshotPlaceholder(
  viewpoint: Pick<Viewpoint, 'has_snapshot'> | null | undefined,
  failed: boolean,
): SnapshotPlaceholder | null {
  if (failed) return 'failed';
  if (!viewpoint) return 'no_viewpoint';
  if (!viewpoint.has_snapshot) return 'no_snapshot';
  return null;
}
