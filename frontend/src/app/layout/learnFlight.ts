// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The Learn section folds into one icon in the top bar and back out of it.
// A small ghost of the graduation cap flies between the two places so the
// reader sees where the section went, and the place it lands gives a short
// pulse. It is plain Web Animations on a fixed element: transforms and
// opacity only, nothing to install.
//
// With reduced motion there is no flight, only a short fade-in where the
// section now lives. Where the browser has no Web Animations (or the slot is
// not on screen, as with the sidebar folded away on a phone), nothing moves at
// all and the change simply happens.

/** Marks the two slots the flight runs between. */
export const LEARN_ANCHOR_ATTR = 'data-learn-anchor';
export type LearnAnchor = 'sidebar' | 'topbar';

const FLIGHT_MS = 520;
const PULSE_MS = 650;

export function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
  } catch {
    return false;
  }
}

const overlaps = (a: DOMRect, b: { left: number; top: number; right: number; bottom: number }) =>
  a.right > b.left && a.left < b.right && a.bottom > b.top && a.top < b.bottom;

/**
 * The slot's box, or null when the reader cannot see it: no size, outside
 * the window (the phone drawer is closed by sliding it off screen), or
 * scrolled out of a clipping ancestor such as the menu's own scroll area.
 */
export function anchorRect(anchor: LearnAnchor): DOMRect | null {
  const el = document.querySelector<HTMLElement>(`[${LEARN_ANCHOR_ATTR}="${anchor}"]`);
  if (!el) return null;
  const rect = el.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return null;
  if (!overlaps(rect, { left: 0, top: 0, right: window.innerWidth, bottom: window.innerHeight })) return null;
  for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
    const style = getComputedStyle(p);
    if (style.overflowX === 'visible' && style.overflowY === 'visible') continue;
    if (!overlaps(rect, p.getBoundingClientRect())) return null;
  }
  return rect;
}

const canAnimate = (el: Element) => typeof (el as HTMLElement).animate === 'function';

/** A short pulse, or with reduced motion a fade, on the slot that now shows Learn. */
function land(anchor: LearnAnchor, reduced: boolean) {
  const el = document.querySelector<HTMLElement>(`[${LEARN_ANCHOR_ATTR}="${anchor}"]`);
  if (!el || !canAnimate(el)) return;
  if (reduced) {
    el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 200, easing: 'ease-out' });
    return;
  }
  el.animate(
    [
      { transform: 'scale(1)', boxShadow: '0 0 0 0 rgba(37, 99, 235, 0.45)' },
      { transform: 'scale(1.18)', boxShadow: '0 0 0 6px rgba(37, 99, 235, 0.18)' },
      { transform: 'scale(1)', boxShadow: '0 0 0 10px rgba(37, 99, 235, 0)' },
    ],
    { duration: PULSE_MS, easing: 'ease-out' },
  );
}

/**
 * Fly a ghost of the cap from `from` to the `to` slot once it has rendered.
 * `from` is measured before the state change, because the element it belongs
 * to is about to leave the page.
 */
export function flyLearn(from: DOMRect | null, to: LearnAnchor, focusSelector?: string) {
  const reduced = prefersReducedMotion();
  // Two frames: one for React to commit the new slot, one for layout.
  const run = () => {
    // The button that was pressed has just unmounted; keyboard focus goes to
    // the control that brings the section the other way, not to the page.
    if (focusSelector) document.querySelector<HTMLElement>(focusSelector)?.focus({ preventScroll: true });
    const target = anchorRect(to);
    if (reduced || !from || !target) {
      land(to, reduced);
      return;
    }
    const ghost = document.createElement('div');
    ghost.setAttribute('data-testid', 'learn-flight-ghost');
    ghost.setAttribute('aria-hidden', 'true');
    const size = 28;
    Object.assign(ghost.style, {
      position: 'fixed',
      left: '0px',
      top: '0px',
      width: `${size}px`,
      height: `${size}px`,
      zIndex: '9999',
      pointerEvents: 'none',
      borderRadius: '8px',
      background: 'rgb(37, 99, 235)',
      boxShadow: '0 6px 18px rgba(37, 99, 235, 0.35)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
    } satisfies Partial<CSSStyleDeclaration>);
    // The lucide graduation cap, drawn inline so the ghost needs no React root.
    ghost.innerHTML =
      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.42 10.922a1 1 0 0 0-.019-1.838L12.83 5.18a2 2 0 0 0-1.66 0L2.6 9.08a1 1 0 0 0 0 1.832l8.57 3.908a2 2 0 0 0 1.66 0z"/><path d="M22 10v6"/><path d="M6 12.5V16a6 3 0 0 0 12 0v-3.5"/></svg>';
    if (!canAnimate(ghost)) {
      land(to, reduced);
      return;
    }
    document.body.appendChild(ghost);
    const x0 = from.left + from.width / 2 - size / 2;
    const y0 = from.top + from.height / 2 - size / 2;
    const x1 = target.left + target.width / 2 - size / 2;
    const y1 = target.top + target.height / 2 - size / 2;
    // A slight arc: the midpoint lifts above the straight line, but never
    // above the top of the window, where the top bar already sits.
    const xm = (x0 + x1) / 2;
    const ym = Math.max(4, Math.min(y0, y1) - 40);
    const anim = ghost.animate(
      [
        { transform: `translate(${x0}px, ${y0}px) scale(1)`, opacity: 0.95 },
        { transform: `translate(${xm}px, ${ym}px) scale(1.15)`, opacity: 1, offset: 0.5 },
        { transform: `translate(${x1}px, ${y1}px) scale(0.85)`, opacity: 0.2 },
      ],
      { duration: FLIGHT_MS, easing: 'cubic-bezier(0.22, 1, 0.36, 1)', fill: 'forwards' },
    );
    const done = () => {
      ghost.remove();
      land(to, false);
    };
    anim.onfinish = done;
    anim.oncancel = () => ghost.remove();
  };
  requestAnimationFrame(() => requestAnimationFrame(run));
}
