// ═══════════════════════════════════════════════════════════════════
// SCROLL — Lenis smooth scroll + GSAP ScrollTrigger integration
// ═══════════════════════════════════════════════════════════════════

import Lenis from 'https://cdn.jsdelivr.net/npm/lenis@1.1.14/+esm';
import gsap from 'https://cdn.jsdelivr.net/npm/gsap@3.12.5/+esm';
import { ScrollTrigger } from 'https://cdn.jsdelivr.net/npm/gsap@3.12.5/ScrollTrigger/+esm';

gsap.registerPlugin(ScrollTrigger);

export function initSmoothScroll() {
  const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (prefersReduced) return { lenis: null };

  const lenis = new Lenis({
    duration: 1.1,
    easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
    smoothWheel: true,
    smoothTouch: false,
    touchMultiplier: 2,
  });

  lenis.on('scroll', ScrollTrigger.update);

  gsap.ticker.add((time) => {
    lenis.raf(time * 1000);
  });
  gsap.ticker.lagSmoothing(0);

  return { lenis, gsap, ScrollTrigger };
}

export { gsap, ScrollTrigger };
