// ═══════════════════════════════════════════════════════════════════
// MAIN — bootstrap for /pro page
// ═══════════════════════════════════════════════════════════════════

import { initHeroWebGL } from './hero-webgl.js';
import { initSmoothScroll, gsap, ScrollTrigger } from './scroll.js';

// ——————— nav scroll state ———————
const nav = document.querySelector('.nav');
if (nav) {
  const onScroll = () => {
    if (window.scrollY > 10) nav.classList.add('is-scrolled');
    else nav.classList.remove('is-scrolled');
  };
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();
}

// ——————— hero WebGL ———————
const heroCanvas = document.getElementById('hero-canvas');
if (heroCanvas) {
  try {
    initHeroWebGL(heroCanvas);
  } catch (err) {
    console.warn('[hero-webgl] failed', err);
  }
}

// ——————— smooth scroll + GSAP ———————
initSmoothScroll();

// ——————— hero title word-by-word intro ———————
function heroIntro() {
  const title = document.querySelector('.hero-title');
  if (!title) return;

  const words = title.querySelectorAll('.word');
  gsap.set(words, { y: '110%', opacity: 0 });
  gsap.set('.hero-pill, .hero-sub, .hero-cta-row, .hero-cta-meta, .hero-install', { opacity: 0, y: 24 });

  const tl = gsap.timeline({ defaults: { ease: 'expo.out' } });
  tl.to('.hero-pill', { opacity: 1, y: 0, duration: 0.8 }, 0.1)
    .to(words, { y: '0%', opacity: 1, duration: 1.2, stagger: 0.08 }, 0.2)
    .to('.hero-sub', { opacity: 1, y: 0, duration: 1 }, 0.8)
    .to('.hero-cta-row', { opacity: 1, y: 0, duration: 0.8 }, 1.0)
    .to('.hero-install', { opacity: 1, y: 0, duration: 0.7 }, 1.15)
    .to('.hero-cta-meta', { opacity: 1, y: 0, duration: 0.8 }, 1.25);
}
heroIntro();

// ——————— install copy ———————
const installBlock = document.querySelector('.hero-install');
if (installBlock) {
  installBlock.addEventListener('click', async () => {
    const cmd = installBlock.dataset.cmd ?? 'docker compose up';
    try {
      await navigator.clipboard.writeText(cmd);
      installBlock.classList.add('is-copied');
      setTimeout(() => installBlock.classList.remove('is-copied'), 1400);
    } catch (e) { /* noop */ }
  });
}

// ——————— reveals on scroll ———————
document.querySelectorAll('.rv').forEach((el) => {
  gsap.fromTo(
    el,
    { opacity: 0, y: 40 },
    {
      opacity: 1,
      y: 0,
      duration: 0.9,
      ease: 'expo.out',
      scrollTrigger: {
        trigger: el,
        start: 'top 85%',
        toggleActions: 'play none none reverse',
      },
    },
  );
});

// ——————— stagger reveals ———————
document.querySelectorAll('[data-stagger]').forEach((el) => {
  const children = Array.from(el.children);
  gsap.fromTo(
    children,
    { opacity: 0, y: 32 },
    {
      opacity: 1,
      y: 0,
      duration: 0.8,
      ease: 'expo.out',
      stagger: 0.08,
      scrollTrigger: {
        trigger: el,
        start: 'top 80%',
        toggleActions: 'play none none reverse',
      },
    },
  );
});

// ——————— year in footer ———————
const year = document.querySelector('[data-year]');
if (year) year.textContent = String(new Date().getFullYear());
