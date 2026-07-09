/**
 * Pure day <-> pixel scaling helpers for GanttChart.tsx.
 *
 * Kept separate from the component so the arithmetic is unit-testable
 * without rendering SVG (mirrors roomRect/rectToPolygon in serialize.ts).
 */

/** Fixed pixel width per working day. The chart does not compress to fit
 *  its container - it scrolls horizontally instead (see GanttChart.tsx). */
export const PX_PER_DAY = 20;

/** Horizontal offset (px) of a day-offset from the chart's day-0 origin. */
export function dayToX(day: number): number {
  return Math.max(day, 0) * PX_PER_DAY;
}

/** Pixel width of a bar spanning `durationDays` working days. */
export function durationToWidth(durationDays: number): number {
  return Math.max(durationDays, 0) * PX_PER_DAY;
}
