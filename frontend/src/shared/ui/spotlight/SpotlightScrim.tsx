// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// SpotlightScrim — the dim backdrop + rectangular cutout + accent ring that a
// spotlight coach-mark draws around the element it is pointing at. Lifted from
// the (previously duplicated) inline JSX in ProductTour and ModuleGuide so the
// halo is pixel-identical and theme-aware in one place. Accent hue is the only
// visible difference between the two surfaces: violet for the Tour, blue for
// the "How it works" guide.
//
// The scrim is purely decorative (aria-hidden, pointer-events: none). Any
// click-to-dismiss backdrop is the host's concern and sits underneath it.

import type { CSSProperties } from 'react';

import type { SpotlightRect } from './placeTooltip';

/** px spread on the box-shadow — large enough to dim the whole viewport. */
const SHADOW_SPREAD = 9999;

export type SpotlightAccent = 'violet' | 'blue';

interface RingStyle {
  border: string;
  boxShadow: string;
}

/** Accent-ring colours per hue, per theme. These are the exact values
 *  ProductTour (violet) and ModuleGuide (blue) have shipped with. */
const RING: Record<SpotlightAccent, { dark: RingStyle; light: RingStyle }> = {
  violet: {
    dark: {
      border: '2px solid rgba(196, 181, 253, 0.95)',
      boxShadow:
        '0 0 0 4px rgba(196, 181, 253, 0.25), 0 0 32px 6px rgba(167, 139, 250, 0.55)',
    },
    light: {
      border: '2px solid rgba(139, 92, 246, 0.85)',
      boxShadow:
        '0 0 0 4px rgba(139, 92, 246, 0.20), 0 0 18px 2px rgba(139, 92, 246, 0.35)',
    },
  },
  blue: {
    dark: {
      border: '2px solid rgba(125, 211, 252, 0.95)',
      boxShadow:
        '0 0 0 4px rgba(125, 211, 252, 0.25), 0 0 32px 6px rgba(56, 189, 248, 0.55)',
    },
    light: {
      border: '2px solid rgba(14, 165, 233, 0.85)',
      boxShadow:
        '0 0 0 4px rgba(14, 165, 233, 0.20), 0 0 18px 2px rgba(14, 165, 233, 0.35)',
    },
  },
};

export interface SpotlightScrimProps {
  /** The rectangle to leave undimmed (viewport coordinates). */
  rect: SpotlightRect;
  /** Accent hue of the ring — 'violet' (tour) or 'blue' (guide). */
  accent: SpotlightAccent;
  /** Current theme, so the inline rgba values (outside Tailwind's reach) can
   *  swap. Callers already track this with a MutationObserver. */
  isDark: boolean;
  /** Corner radius of the cutout + ring. Default 12. */
  radius?: number;
  /** Optional data-testid for the dimming cutout (existing test hook). */
  testId?: string;
}

/**
 * Draw the dimming cutout + accent ring over `rect`. Renders two fixed,
 * pointer-events-none divs; the dimming layer uses an enormous box-shadow to
 * paint the whole viewport while leaving `rect` a clear rectangular hole, and
 * the ring sits on top drawing a crisp, unmistakable boundary.
 */
export function SpotlightScrim({
  rect,
  accent,
  isDark,
  radius = 12,
  testId,
}: SpotlightScrimProps) {
  const scrimColor = isDark ? 'rgba(2, 6, 23, 0.80)' : 'rgba(15, 23, 42, 0.55)';
  const ring = isDark ? RING[accent].dark : RING[accent].light;

  const boxBase: CSSProperties = {
    position: 'fixed',
    top: rect.top,
    left: rect.left,
    width: rect.width,
    height: rect.height,
    borderRadius: radius,
    pointerEvents: 'none',
    transition:
      'top 200ms ease, left 200ms ease, width 200ms ease, height 200ms ease',
  };

  return (
    <>
      {/* Dimming layer — one huge box-shadow paints the whole viewport while
          the element itself stays a clear rectangular cutout. */}
      <div
        aria-hidden="true"
        data-testid={testId}
        style={{ ...boxBase, boxShadow: `0 0 0 ${SHADOW_SPREAD}px ${scrimColor}` }}
      />
      {/* Accent ring + glow around the cutout. Stronger in dark mode where the
          dimming alone is hard to see against already-dark surfaces. */}
      <div
        aria-hidden="true"
        style={{ ...boxBase, border: ring.border, boxShadow: ring.boxShadow }}
      />
    </>
  );
}
