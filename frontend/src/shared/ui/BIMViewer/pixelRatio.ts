// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Device-pixel-ratio ceiling for the BIM renderer.
 *
 * Rendering at the raw devicePixelRatio on a 3x phone or a 4K panel multiplies
 * the per-frame fragment cost of a heavy model for little readability gain, so
 * the ratio is capped. A ceiling of 2.0 keeps retina / 2x displays fully sharp
 * (a no-op there) and only trims 3x / 4K. Kept as one named constant so the
 * ceiling is trivially tunable.
 */
export const MAX_PIXEL_RATIO = 2;

/**
 * The pixel ratio the renderer should use: the device ratio capped at
 * {@link MAX_PIXEL_RATIO}, with a safe fallback of 1 for a non-finite or
 * non-positive value (or a non-DOM/SSR context where there is no window).
 */
export function cappedDevicePixelRatio(
  devicePixelRatio: number = typeof window !== 'undefined' ? window.devicePixelRatio : 1,
): number {
  const safe =
    Number.isFinite(devicePixelRatio) && devicePixelRatio > 0 ? devicePixelRatio : 1;
  return Math.min(safe, MAX_PIXEL_RATIO);
}
