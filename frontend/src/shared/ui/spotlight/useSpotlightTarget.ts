// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// useSpotlightTarget — resolve a CSS selector to a live, viewport-anchored
// spotlight rectangle plus the coordinates a coach-mark card should sit at.
//
// It consolidates the target-tracking logic that ProductTour and ModuleGuide
// each grew independently:
//   * scroll the target to the centre of the viewport on first resolve,
//   * defer the first measure (timeout + rAF) so a smooth scroll settles,
//   * bounded reveal-retry — dispatch `oe:tour-reveal` for a target hidden
//     inside a collapsed sidebar group, then re-query a few times,
//   * recompute on resize / scroll / ResizeObserver so the halo stays pinned,
//   * degrade to a centred card (rect === null) when the target never shows.
//
// The hook is headless: it owns no DOM, only geometry + status, so the blue
// guide and the violet tour can both drive their own chrome from one source
// of measurements.

import { useEffect, useRef, useState } from 'react';

import {
  centerOfViewport,
  measureSpotlight,
  placeTooltip,
  type SpotlightRect,
  type TooltipCoords,
  type TooltipPosition,
} from './placeTooltip';

/** Window event a Sidebar listens for to expand a collapsed group so a
 *  spotlight target inside it can mount and be measured. Matches the event
 *  ProductTour has always dispatched. */
export const SPOTLIGHT_REVEAL_EVENT = 'oe:tour-reveal';

/** Resolution state of the target selector. */
export type SpotlightStatus = 'none' | 'pending' | 'found' | 'missing';

export interface UseSpotlightTargetOptions {
  /** Preferred side for the card relative to the target. */
  preferredPosition?: TooltipPosition;
  /** Sidebar group id to reveal when the target is unmounted (collapsed). */
  revealGroupId?: string;
  /** Whether tracking is live. When false the hook idles and reports 'none'. */
  active?: boolean;
  /** Mirror horizontal placement for right-to-left locales. */
  rtl?: boolean;
}

export interface SpotlightTarget {
  /** Measured, padded highlight rect, or null when there is no target. */
  rect: SpotlightRect | null;
  /** Where the coach-mark card should be placed. Centre when rect is null. */
  tooltipCoords: TooltipCoords;
  /** Resolution state — 'none' (no selector), 'pending', 'found', 'missing'. */
  status: SpotlightStatus;
}

const SCROLL_INTO_VIEW_OPTS: ScrollIntoViewOptions = {
  behavior: 'smooth',
  block: 'center',
  inline: 'center',
};

/** How many times to re-query a not-yet-mounted target before degrading. */
const MAX_ATTEMPTS = 5;
/** ms between reveal-retry attempts. */
const RETRY_INTERVAL = 80;
/** ms to wait before the first measure so a smooth scroll can progress. */
const FIRST_MEASURE_DELAY = 170;

/**
 * Track a spotlight target by selector.
 *
 * @param selector CSS selector for the element to highlight. `null` /
 *   `undefined` (or `active === false`) yields `status: 'none'` and a centred
 *   card — this is the zero-regression fallback for guides that set no
 *   spotlight.
 */
export function useSpotlightTarget(
  selector: string | null | undefined,
  options: UseSpotlightTargetOptions = {},
): SpotlightTarget {
  const { preferredPosition, revealGroupId, active = true, rtl = false } = options;

  const [rect, setRect] = useState<SpotlightRect | null>(null);
  const [tooltipCoords, setTooltipCoords] = useState<TooltipCoords>(() =>
    typeof window === 'undefined' ? { top: 0, left: 0 } : centerOfViewport(),
  );
  const [status, setStatus] = useState<SpotlightStatus>('none');

  // Pending timers / animation frames, cleared on re-run so a stale retry
  // never re-positions onto a newer target.
  const timersRef = useRef<number[]>([]);
  const framesRef = useRef<number[]>([]);
  // Missing-target selectors we've already warned about, so scroll/resize
  // recomputes don't spam the console.
  const warnedRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    const clearPending = () => {
      for (const id of timersRef.current) window.clearTimeout(id);
      timersRef.current = [];
      for (const id of framesRef.current) window.cancelAnimationFrame(id);
      framesRef.current = [];
    };

    // No selector / inactive → centred fallback. This is the path the ~73
    // guides that set no spotlight take, and it must never draw a halo.
    if (!active || !selector) {
      clearPending();
      setRect(null);
      setStatus('none');
      if (typeof window !== 'undefined') setTooltipCoords(centerOfViewport());
      return;
    }

    setStatus('pending');

    const scrollIntoView = () => {
      const el = document.querySelector(selector);
      if (!el) return;
      try {
        el.scrollIntoView(SCROLL_INTO_VIEW_OPTS);
      } catch {
        /* older browsers — ignore */
      }
    };

    const apply = (r: SpotlightRect) => {
      setRect(r);
      setTooltipCoords(placeTooltip(r, preferredPosition, rtl));
      setStatus('found');
    };
    const degrade = () => {
      setRect(null);
      setTooltipCoords(centerOfViewport());
      setStatus('missing');
    };

    // First resolve: scroll the target to centre (or ask its sidebar group to
    // expand), then measure once layout settles.
    const el = document.querySelector(selector);
    if (el) {
      scrollIntoView();
    } else if (revealGroupId) {
      window.dispatchEvent(
        new CustomEvent(SPOTLIGHT_REVEAL_EVENT, { detail: { groupId: revealGroupId } }),
      );
    } else if (!warnedRef.current.has(selector)) {
      warnedRef.current.add(selector);
      // eslint-disable-next-line no-console
      console.warn(`[useSpotlightTarget] target not found: ${selector}`);
    }

    const attempt = (n: number) => {
      const measured = measureSpotlight(selector);
      if (measured) {
        // The row may have just mounted / scrolled — re-centre, then measure
        // on the next frame so we read the settled rect, not the pre-scroll one.
        if (n > 0) {
          scrollIntoView();
          const frame = window.requestAnimationFrame(() => {
            apply(measureSpotlight(selector) ?? measured);
          });
          framesRef.current.push(frame);
          return;
        }
        apply(measured);
        return;
      }
      if (n + 1 >= MAX_ATTEMPTS) {
        degrade();
        return;
      }
      const retry = window.setTimeout(() => attempt(n + 1), RETRY_INTERVAL);
      timersRef.current.push(retry);
    };

    // Defer the first measure so the smooth scroll can progress, then a rAF so
    // we measure after the browser applies layout for that frame.
    const firstTimer = window.setTimeout(() => {
      const frame = window.requestAnimationFrame(() => attempt(0));
      framesRef.current.push(frame);
    }, FIRST_MEASURE_DELAY);
    timersRef.current.push(firstTimer);

    // Keep the halo pinned through scroll / resize / layout shifts. These only
    // re-measure (never re-scroll) so they don't fight the user's scrolling.
    const recompute = () => {
      const measured = measureSpotlight(selector);
      if (measured) {
        setRect(measured);
        setTooltipCoords(placeTooltip(measured, preferredPosition, rtl));
        setStatus('found');
      }
    };
    window.addEventListener('resize', recompute);
    window.addEventListener('scroll', recompute, true);
    let ro: ResizeObserver | null = null;
    if (typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(recompute);
      ro.observe(document.body);
    }

    return () => {
      clearPending();
      window.removeEventListener('resize', recompute);
      window.removeEventListener('scroll', recompute, true);
      if (ro) ro.disconnect();
    };
  }, [selector, preferredPosition, revealGroupId, active, rtl]);

  return { rect, tooltipCoords, status };
}
