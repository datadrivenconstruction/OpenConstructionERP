/**
 * Ortho / angle-lock math for rubber-banding Shift-held draws.
 *
 * When the user holds Shift while placing the next point of a distance /
 * line / polyline, we snap the cursor to the nearest ray emanating from
 * the last committed point at 0°, 45°, 90°, 135° (and their mirrors).
 * This gives AutoCAD-style "ortho" behaviour without a toggle.
 */

/** World-space 2D point — kept minimal so the helper has no dependency
 *  on the viewport / annotation types. */
export interface Pt {
  x: number;
  y: number;
}

/** Angles we snap to, expressed in degrees. Eight evenly spaced rays
 *  (every 45°) cover both axis-aligned and diagonal directions. */
export const ANGLE_LOCK_STEP_DEG = 45;

/**
 * Snap a free cursor point to the nearest 0°/45°/90°/135° ray from
 * ``anchor``. Preserves the raw distance from anchor to cursor — only
 * the direction changes. When ``anchor`` and ``cursor`` coincide we
 * return ``anchor`` unchanged (no ray to snap to).
 */
export function snapToOrthoAngle(anchor: Pt, cursor: Pt): Pt {
  const dx = cursor.x - anchor.x;
  const dy = cursor.y - anchor.y;
  const dist = Math.hypot(dx, dy);
  if (dist === 0) return { x: anchor.x, y: anchor.y };

  // Normalize to radians, quantize to the nearest 45° step, reproject.
  const rawAngle = Math.atan2(dy, dx);
  const step = (ANGLE_LOCK_STEP_DEG * Math.PI) / 180;
  const snapped = Math.round(rawAngle / step) * step;

  return {
    x: anchor.x + dist * Math.cos(snapped),
    y: anchor.y + dist * Math.sin(snapped),
  };
}

/**
 * Helper for tests & UI hints — returns the snapped angle in degrees in
 * the range [-180, 180]. Exposed so the ghost ray overlay can render a
 * human-readable hint next to the cursor.
 */
export function snapAngleDegrees(anchor: Pt, cursor: Pt): number {
  const dx = cursor.x - anchor.x;
  const dy = cursor.y - anchor.y;
  const rawAngle = Math.atan2(dy, dx);
  const step = (ANGLE_LOCK_STEP_DEG * Math.PI) / 180;
  const snapped = Math.round(rawAngle / step) * step;
  return (snapped * 180) / Math.PI;
}
