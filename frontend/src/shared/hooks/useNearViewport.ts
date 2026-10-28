// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useEffect, useRef, useState, type RefObject } from 'react';

/**
 * Latches to `true` the first time the referenced element scrolls within
 * `rootMargin` of the viewport, and then stays true so gated content is never
 * torn back down once it has been revealed. Lets a long list defer expensive
 * per-item work (large inline SVG art, heavy images) until an item is actually
 * near the fold, without any layout shift when a same-sized placeholder is used
 * in the meantime.
 *
 * Falls back to eagerly visible when IntersectionObserver is unavailable (older
 * browsers, JSDOM-based test environments), so content is never left hidden
 * where the API cannot report visibility.
 *
 * @param rootMargin - how far outside the viewport still counts as "near", so
 *   the real content is ready by the time the item is scrolled to. Default
 *   `300px`.
 * @returns A ref to attach to the element to observe, and the `near` flag.
 */
export function useNearViewport<T extends HTMLElement = HTMLDivElement>(
  rootMargin = '300px',
): { ref: RefObject<T>; near: boolean } {
  const ref = useRef<T>(null);
  const [near, setNear] = useState(false);

  useEffect(() => {
    if (near) return;
    if (typeof IntersectionObserver === 'undefined') {
      setNear(true);
      return;
    }
    const node = ref.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setNear(true);
          observer.disconnect();
        }
      },
      { rootMargin },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [near, rootMargin]);

  return { ref, near };
}
