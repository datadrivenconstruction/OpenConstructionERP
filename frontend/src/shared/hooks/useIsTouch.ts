// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * `useIsTouch` - true when the primary pointer is coarse (finger/stylus),
 * i.e. a phone or tablet. This is a touch-CAPABILITY probe, not a width
 * check: a large tablet is touch but not "mobile width", and a narrow
 * desktop window is mobile width but not touch. Site-mode chrome (the walk
 * joystick) keys off this, not off viewport size.
 *
 * Follows the same `useSyncExternalStore` + `matchMedia` shape as
 * `useIsMobileViewport`, so it re-renders if the capability changes (e.g. a
 * 2-in-1 toggling tablet mode) and stays deterministic before hydration.
 */
import { useSyncExternalStore } from 'react';

const QUERY = '(pointer: coarse)';

function getMediaQuery(): MediaQueryList | null {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return null;
  return window.matchMedia(QUERY);
}

export function useIsTouch(): boolean {
  const subscribe = (callback: () => void): (() => void) => {
    const mq = getMediaQuery();
    if (!mq) return () => {};
    mq.addEventListener('change', callback);
    return () => mq.removeEventListener('change', callback);
  };
  const getSnapshot = (): boolean => getMediaQuery()?.matches ?? false;
  const getServerSnapshot = (): boolean => false;
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
