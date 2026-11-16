import { useLayoutEffect, useState } from 'react';

/**
 * Height that makes a full-screen workspace end exactly at the bottom of the
 * viewport, whatever sits above it (app header, demo banner and project bar,
 * desktop title bar). A fixed `100vh - 56px` only knew about the header, so on
 * the public demo the page grew taller than the window and scrolled as a whole.
 * Returns a callback ref, so a root that mounts after the first render is still
 * measured.
 */
export function useFillViewport<T extends HTMLElement>(fallback = 'calc(100dvh - 56px)') {
  const [el, setEl] = useState<T | null>(null);
  const [height, setHeight] = useState(fallback);

  useLayoutEffect(() => {
    if (!el) return undefined;
    const measure = () => {
      const top = el.getBoundingClientRect().top + window.scrollY;
      setHeight(`calc(100dvh - ${Math.max(0, Math.round(top))}px)`);
    };
    measure();
    window.addEventListener('resize', measure);
    const ro = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure);
    ro?.observe(document.body);
    return () => {
      window.removeEventListener('resize', measure);
      ro?.disconnect();
    };
  }, [el]);

  return [setEl, height] as const;
}
