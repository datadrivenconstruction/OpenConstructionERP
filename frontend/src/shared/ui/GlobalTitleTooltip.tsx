// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

const DELAY_MS = 450;
const GAP = 6;

interface Tip {
  text: string;
  x: number;
  y: number;
  below: boolean;
}

/**
 * Renders every native `title` attribute as the platform tooltip instead of the
 * browser's own yellow box. The title is parked in `data-oe-title` while the
 * pointer or focus is on the element, and an icon-only control with no other
 * accessible name keeps the text as its `aria-label`.
 */
export function GlobalTitleTooltip() {
  const [tip, setTip] = useState<Tip | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const current = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const restore = () => {
      window.clearTimeout(timer.current);
      const el = current.current;
      if (el && el.dataset.oeTitle !== undefined) {
        el.setAttribute('title', el.dataset.oeTitle);
        delete el.dataset.oeTitle;
      }
      current.current = null;
      setTip(null);
    };

    const enter = (event: Event) => {
      const target = event.target as Element | null;
      const el = target?.closest?.('[title]') as HTMLElement | null;
      if (!el || el === current.current || el instanceof SVGElement) return;
      if (el.closest('[data-oe-native-title]')) return;
      const text = el.getAttribute('title')?.trim();
      if (!text) return;
      restore();
      current.current = el;
      el.dataset.oeTitle = el.getAttribute('title') ?? '';
      el.removeAttribute('title');
      if (!el.getAttribute('aria-label') && !el.textContent?.trim()) el.setAttribute('aria-label', text);
      timer.current = window.setTimeout(() => {
        if (current.current !== el || !el.isConnected) return;
        const r = el.getBoundingClientRect();
        const below = r.top < 40;
        setTip({ text, x: r.left + r.width / 2, y: below ? r.bottom + GAP : r.top - GAP, below });
      }, DELAY_MS);
    };

    const leave = (event: Event) => {
      const el = current.current;
      if (!el) return;
      const to = (event as MouseEvent).relatedTarget as Node | null;
      if (to && el.contains(to)) return;
      restore();
    };

    document.addEventListener('mouseover', enter, true);
    document.addEventListener('focusin', enter, true);
    document.addEventListener('mouseout', leave, true);
    document.addEventListener('focusout', leave, true);
    document.addEventListener('pointerdown', restore, true);
    window.addEventListener('scroll', restore, true);
    return () => {
      restore();
      document.removeEventListener('mouseover', enter, true);
      document.removeEventListener('focusin', enter, true);
      document.removeEventListener('mouseout', leave, true);
      document.removeEventListener('focusout', leave, true);
      document.removeEventListener('pointerdown', restore, true);
      window.removeEventListener('scroll', restore, true);
    };
  }, []);

  if (!tip) return null;
  return createPortal(
    <div
      role="tooltip"
      className="pointer-events-none fixed z-tooltip max-w-xs rounded-md bg-content-primary px-2 py-1 text-xs font-medium text-surface-primary shadow-md animate-fade-in"
      style={{
        left: Math.min(Math.max(tip.x, 8), window.innerWidth - 8),
        top: tip.y,
        transform: `translate(-50%, ${tip.below ? '0' : '-100%'})`,
      }}
    >
      {tip.text}
    </div>,
    document.body,
  );
}
