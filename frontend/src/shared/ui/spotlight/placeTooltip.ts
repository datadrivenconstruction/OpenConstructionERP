// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// placeTooltip — pure geometry helpers shared by the spotlight coach-marks:
// ProductTour's violet walkthrough and ModuleGuide's blue "How it works"
// explainer. Lifted from ProductTour so both surfaces anchor their card with
// identical, well-tested placement, plus an RTL branch that mirrors the
// horizontal candidate order for right-to-left locales.
//
// No React, no DOM ownership — just measurement + arithmetic, so it can be
// unit-tested and reused headlessly.

/** A measured, padded highlight rectangle in viewport coordinates. */
export interface SpotlightRect {
  top: number;
  left: number;
  width: number;
  height: number;
}

/** Absolute viewport coordinates for the tooltip / card top-left corner. */
export interface TooltipCoords {
  top: number;
  left: number;
}

/** Side of the target the tooltip prefers to sit on. */
export type TooltipPosition = 'top' | 'right' | 'bottom' | 'left';

/* Geometry constants — the values ProductTour has shipped with. */
export const TOOLTIP_W = 340; // px — fixed tooltip width
export const TOOLTIP_H = 200; // px — estimated tooltip height (pre-positioning)
export const TOOLTIP_OFFSET = 16; // px gap between spotlight and tooltip
export const SPOTLIGHT_PADDING = 8; // px halo around the highlighted element
export const VIEWPORT_MARGIN = 12; // px keep-away from viewport edges

/** Flip a horizontal position to its mirror; vertical positions pass through. */
function mirror(pos: TooltipPosition): TooltipPosition {
  if (pos === 'left') return 'right';
  if (pos === 'right') return 'left';
  return pos;
}

/**
 * Choose the best on-screen coordinates for a fixed-width tooltip next to a
 * spotlight rectangle. Tries the preferred side first, then a sensible
 * fallback order, and returns the first candidate that fits fully inside the
 * viewport; when none fit cleanly it clamps the preferred candidate to the
 * viewport margins.
 *
 * `rtl` mirrors the horizontal candidates (and the preferred side) so a
 * right-to-left layout gets left/right placement that reads correctly.
 */
export function placeTooltip(
  spotlight: SpotlightRect,
  preferred: TooltipPosition = 'bottom',
  rtl = false,
): TooltipCoords {
  const vw = window.innerWidth;
  const vh = window.innerHeight;

  const primary = rtl ? mirror(preferred) : preferred;

  // Candidate positions ordered by preference; first that fully fits wins.
  // In RTL the horizontal fallbacks swap so we lean to the mirrored side.
  const order: TooltipPosition[] = rtl
    ? [primary, 'bottom', 'left', 'top', 'right']
    : [primary, 'bottom', 'right', 'top', 'left'];

  const tryPlace = (pos: TooltipPosition): TooltipCoords => {
    switch (pos) {
      case 'right':
        return {
          top: spotlight.top + spotlight.height / 2 - TOOLTIP_H / 2,
          left: spotlight.left + spotlight.width + TOOLTIP_OFFSET,
        };
      case 'left':
        return {
          top: spotlight.top + spotlight.height / 2 - TOOLTIP_H / 2,
          left: spotlight.left - TOOLTIP_W - TOOLTIP_OFFSET,
        };
      case 'top':
        return {
          top: spotlight.top - TOOLTIP_H - TOOLTIP_OFFSET,
          left: spotlight.left + spotlight.width / 2 - TOOLTIP_W / 2,
        };
      case 'bottom':
      default:
        return {
          top: spotlight.top + spotlight.height + TOOLTIP_OFFSET,
          left: spotlight.left + spotlight.width / 2 - TOOLTIP_W / 2,
        };
    }
  };

  const fits = ({ top, left }: TooltipCoords) =>
    top >= VIEWPORT_MARGIN &&
    left >= VIEWPORT_MARGIN &&
    top + TOOLTIP_H <= vh - VIEWPORT_MARGIN &&
    left + TOOLTIP_W <= vw - VIEWPORT_MARGIN;

  for (const pos of order) {
    const candidate = tryPlace(pos);
    if (fits(candidate)) return candidate;
  }
  // Nothing fit cleanly — fall back to the primary side and clamp.
  const fallback = tryPlace(primary);
  return {
    top: Math.max(VIEWPORT_MARGIN, Math.min(fallback.top, vh - TOOLTIP_H - VIEWPORT_MARGIN)),
    left: Math.max(VIEWPORT_MARGIN, Math.min(fallback.left, vw - TOOLTIP_W - VIEWPORT_MARGIN)),
  };
}

/** Centre of the viewport — used when there is no target to anchor to. */
export function centerOfViewport(): TooltipCoords {
  return {
    top: Math.max(VIEWPORT_MARGIN, (window.innerHeight - TOOLTIP_H) / 2),
    left: Math.max(VIEWPORT_MARGIN, (window.innerWidth - TOOLTIP_W) / 2),
  };
}

/**
 * Measure a selector's bounding box in viewport coordinates, padded by
 * SPOTLIGHT_PADDING. Returns null when the element is absent or has zero size
 * (not yet laid out / display:none) so callers degrade to a centred modal
 * instead of drawing a halo at the wrong spot.
 */
export function measureSpotlight(selector: string): SpotlightRect | null {
  if (typeof document === 'undefined') return null;
  const el = document.querySelector(selector);
  if (!el) return null;
  const rect = el.getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return null;
  return {
    top: rect.top - SPOTLIGHT_PADDING,
    left: rect.left - SPOTLIGHT_PADDING,
    width: rect.width + SPOTLIGHT_PADDING * 2,
    height: rect.height + SPOTLIGHT_PADDING * 2,
  };
}
