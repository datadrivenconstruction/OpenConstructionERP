// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Five-star rendering of a subcontractor's `rating_score`.
 *
 * Score domain: 0..100. That is the domain the rating engine clamps to, the
 * one ScorecardTile draws its dials on, and the one the "low rating" pill on
 * a purchase order compares against.
 *
 * The stars and the number are two renderings of the same value, so they have
 * to agree about the scale or the row contradicts itself. They did not: the
 * number printed bare, and a bare number beside five stars reads as a score
 * out of five. A register carrying 4.20 therefore drew five empty stars next
 * to the digit 4, which a reader had every reason to take as four out of
 * five. The number now carries its denominator, so neither half can be read
 * on the wrong scale.
 *
 * The denominator goes through `fmtFixed` rather than being pasted in as a
 * literal so that both halves of the fraction are written in the reader's
 * numbering system, and it sits inline rather than behind a translation key
 * because it is digits and a solidus, the same notation the supplier
 * catalogue already prints beside its own stars.
 */

import clsx from 'clsx';
import { Star } from 'lucide-react';

import { fmtFixed } from '@/shared/lib/formatters';

/** Top of the `rating_score` domain. */
export const RATING_SCALE_MAX = 100;

/** How many stars a row draws. */
export const RATING_STAR_COUNT = 5;

/** Stars to fill for a score on the 0..`RATING_SCALE_MAX` scale. */
export function starsForScore(score: number): number {
  if (!Number.isFinite(score)) return 0;
  const clamped = Math.min(Math.max(score, 0), RATING_SCALE_MAX);
  return Math.round((clamped / RATING_SCALE_MAX) * RATING_STAR_COUNT);
}

function toNum(n: number | string | null | undefined): number {
  if (n === null || n === undefined) return 0;
  return typeof n === 'number' ? n : Number(n) || 0;
}

export function RatingStars({ score }: { score: number | string | null | undefined }) {
  const num = toNum(score);
  const stars = starsForScore(num);
  return (
    <span className="inline-flex items-center gap-0.5">
      {Array.from({ length: RATING_STAR_COUNT }, (_, idx) => idx + 1).map((i) => (
        <Star
          key={i}
          size={12}
          className={clsx(
            i <= stars ? 'fill-oe-blue text-oe-blue' : 'text-content-tertiary',
          )}
        />
      ))}
      <span className="ml-1.5 text-xs text-content-secondary tabular-nums">
        {fmtFixed(num, 0)}/{fmtFixed(RATING_SCALE_MAX, 0)}
      </span>
    </span>
  );
}
