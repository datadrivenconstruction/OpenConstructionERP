import { useRef, useEffect, useCallback } from 'react';

interface SwipeOptions {
  /** Minimum distance in px to count as a swipe (default: 50) */
  threshold?: number;
  /** Maximum time in ms for the swipe (default: 300) */
  maxTime?: number;
  onSwipeLeft?: () => void;
  onSwipeRight?: () => void;
  /** Whether the hook is active (default: true) */
  enabled?: boolean;
}

/**
 * Detects horizontal swipe gestures on a target element.
 * Returns a ref to attach to the swipeable element.
 */
export function useSwipeGesture<T extends HTMLElement = HTMLElement>({
  threshold = 50,
  maxTime = 300,
  onSwipeLeft,
  onSwipeRight,
  enabled = true,
}: SwipeOptions) {
  const ref = useRef<T>(null);
  const touchStart = useRef<{ x: number; y: number; time: number } | null>(null);

  const handleTouchStart = useCallback((e: TouchEvent) => {
    const touch = e.touches[0];
    if (!touch) return;
    touchStart.current = { x: touch.clientX, y: touch.clientY, time: Date.now() };
  }, []);

  const handleTouchEnd = useCallback(
    (e: TouchEvent) => {
      if (!touchStart.current) return;
      const touch = e.changedTouches[0];
      if (!touch) return;
      const dx = touch.clientX - touchStart.current.x;
      const dy = touch.clientY - touchStart.current.y;
      const dt = Date.now() - touchStart.current.time;
      touchStart.current = null;

      // Must be primarily horizontal and within time limit
      if (Math.abs(dx) < threshold || dt > maxTime || Math.abs(dy) > Math.abs(dx)) return;

      if (dx < 0 && onSwipeLeft) onSwipeLeft();
      if (dx > 0 && onSwipeRight) onSwipeRight();
    },
    [threshold, maxTime, onSwipeLeft, onSwipeRight],
  );

  useEffect(() => {
    if (!enabled) return;
    const el = ref.current;
    if (!el) return;
    el.addEventListener('touchstart', handleTouchStart, { passive: true });
    el.addEventListener('touchend', handleTouchEnd, { passive: true });
    return () => {
      el.removeEventListener('touchstart', handleTouchStart);
      el.removeEventListener('touchend', handleTouchEnd);
    };
  }, [enabled, handleTouchStart, handleTouchEnd]);

  return ref;
}

/**
 * Detects edge-swipe from the left (LTR) or right (RTL) side of the screen.
 * Attaches to the document body, no ref needed.
 *
 * - `onSwipeRight` — fires when the user swipes right starting from the LEFT edge (LTR open)
 * - `onSwipeLeft`  — fires when the user swipes left starting from the RIGHT edge (RTL open)
 */
export function useEdgeSwipe({
  edgeWidth = 20,
  threshold = 60,
  maxTime = 400,
  onSwipeRight,
  onSwipeLeft,
  enabled = true,
}: {
  edgeWidth?: number;
  threshold?: number;
  maxTime?: number;
  onSwipeRight?: () => void;
  onSwipeLeft?: () => void;
  enabled?: boolean;
}) {
  const touchStart = useRef<{ x: number; y: number; time: number } | null>(null);

  useEffect(() => {
    if (!enabled) return;

    function handleTouchStart(e: TouchEvent) {
      const touch = e.touches[0];
      if (!touch) return;
      const fromLeftEdge = touch.clientX <= edgeWidth;
      const fromRightEdge = touch.clientX >= window.innerWidth - edgeWidth;
      if (fromLeftEdge || fromRightEdge) {
        touchStart.current = { x: touch.clientX, y: touch.clientY, time: Date.now() };
      }
    }

    function handleTouchEnd(e: TouchEvent) {
      if (!touchStart.current) return;
      const touch = e.changedTouches[0];
      if (!touch) return;
      const dx = touch.clientX - touchStart.current.x;
      const dy = touch.clientY - touchStart.current.y;
      const dt = Date.now() - touchStart.current.time;
      touchStart.current = null;

      if (dt > maxTime || Math.abs(dy) >= Math.abs(dx)) return;

      if (dx >= threshold) {
        onSwipeRight?.();
      } else if (dx <= -threshold) {
        onSwipeLeft?.();
      }
    }

    document.addEventListener('touchstart', handleTouchStart, { passive: true });
    document.addEventListener('touchend', handleTouchEnd, { passive: true });
    return () => {
      document.removeEventListener('touchstart', handleTouchStart);
      document.removeEventListener('touchend', handleTouchEnd);
    };
  }, [enabled, edgeWidth, threshold, maxTime, onSwipeRight, onSwipeLeft]);
}
