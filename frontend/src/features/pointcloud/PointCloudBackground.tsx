/**
 * PointCloudBackground - a subtle, modern decorative point-cloud visual that
 * sits full-bleed behind the Point Cloud module content.
 *
 * Design constraints (matching the task brief):
 *  - Non-interactive: pointer-events:none, aria-hidden, sits at -z-10 behind
 *    the page cards.
 *  - Subtle: low opacity so text readability is never hurt.
 *  - Theme-aware: point colour adapts to the resolved light / dark theme.
 *  - Performant: a fixed, capped point budget rendered with a single
 *    THREE.Points draw call, driven by requestAnimationFrame; the loop stops
 *    when the tab is hidden (visibilitychange) and when the element scrolls
 *    out of view (IntersectionObserver).
 *  - Respects prefers-reduced-motion: renders a single static frame and never
 *    starts the animation loop.
 *
 * three.js is already a project dependency (see BIMViewer), so we reuse it
 * rather than hand-rolling a 2D canvas projection.
 */

import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { useThemeStore } from '@/stores/useThemeStore';

/** Points in the drifting cloud. Capped low so the background never competes
 *  with the real BIM / DWG viewers for the GPU. */
const POINT_COUNT = 2200;
/** Half-extent of the cube the points are scattered through. */
const SPREAD = 60;

/**
 * Feature-detect a usable WebGL2 context before we ever construct a
 * THREE.WebGLRenderer. three.js (r163+) requires WebGL2 and THROWS
 * synchronously when a context cannot be created - on headless Firefox /
 * WebKit (no GPU, no software fallback) that throw escapes the effect and
 * trips the page's React error boundary. Probing first lets this purely
 * decorative layer no-op silently instead, so the page degrades gracefully
 * while the chromium happy path is unchanged.
 */
function canUseWebGL2(): boolean {
  if (typeof document === 'undefined') return false;
  try {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl2');
    return gl != null;
  } catch {
    return false;
  }
}

export function PointCloudBackground() {
  const containerRef = useRef<HTMLDivElement>(null);
  const resolvedTheme = useThemeStore((s) => s.resolved);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const prefersReducedMotion =
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-color-scheme: dark)') !== null &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    let width = container.clientWidth || 1;
    let height = container.clientHeight || 1;

    // This is a decorative, aria-hidden layer. If WebGL2 is unavailable or the
    // renderer fails to start (common on headless Firefox / WebKit), skip it
    // silently - the page content still renders and never throws. The real
    // viewer surfaces its own WebGL notice; the background just stays blank.
    if (!canUseWebGL2()) return;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
    } catch {
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(width, height, false);
    renderer.setClearColor(0x000000, 0);
    container.appendChild(renderer.domElement);
    renderer.domElement.style.width = '100%';
    renderer.domElement.style.height = '100%';
    renderer.domElement.style.display = 'block';

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(60, width / height, 1, 1000);
    camera.position.z = 120;

    // Scatter points through a cube. A small per-point "twinkle" phase gives
    // the cloud a gentle living shimmer without per-frame allocation.
    const positions = new Float32Array(POINT_COUNT * 3);
    for (let i = 0; i < POINT_COUNT; i++) {
      positions[i * 3] = (Math.random() - 0.5) * 2 * SPREAD;
      positions[i * 3 + 1] = (Math.random() - 0.5) * 2 * SPREAD;
      positions[i * 3 + 2] = (Math.random() - 0.5) * 2 * SPREAD;
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));

    // Theme-aware colour: a calm blue that reads on light backgrounds, a
    // brighter sky-blue on dark. Opacity stays low so body copy never fights
    // the texture.
    const isDark = resolvedTheme === 'dark';
    const material = new THREE.PointsMaterial({
      color: isDark ? 0x5b9dff : 0x2563eb,
      size: 1.4,
      sizeAttenuation: true,
      transparent: true,
      opacity: isDark ? 0.5 : 0.42,
      depthWrite: false,
      blending: isDark ? THREE.AdditiveBlending : THREE.NormalBlending,
    });

    const points = new THREE.Points(geometry, material);
    scene.add(points);

    const renderFrame = () => renderer.render(scene, camera);

    const handleResize = () => {
      width = container.clientWidth || 1;
      height = container.clientHeight || 1;
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height, false);
      renderFrame();
    };

    const resizeObserver =
      typeof ResizeObserver !== 'undefined' ? new ResizeObserver(handleResize) : null;
    resizeObserver?.observe(container);
    window.addEventListener('resize', handleResize);

    // Reduced motion: draw one static frame at a pleasing angle and stop.
    if (prefersReducedMotion) {
      points.rotation.x = 0.25;
      points.rotation.y = 0.4;
      renderFrame();
    }

    let frameId = 0;
    let running = false;
    let visibleInViewport = true;

    const loop = () => {
      // Slow, continuous rotation - a drifting reality-capture cloud.
      points.rotation.y += 0.0009;
      points.rotation.x += 0.00035;
      renderFrame();
      frameId = window.requestAnimationFrame(loop);
    };

    const start = () => {
      if (running || prefersReducedMotion) return;
      if (document.hidden || !visibleInViewport) return;
      running = true;
      frameId = window.requestAnimationFrame(loop);
    };
    const stop = () => {
      running = false;
      if (frameId) window.cancelAnimationFrame(frameId);
      frameId = 0;
    };

    const handleVisibility = () => {
      if (document.hidden) stop();
      else start();
    };
    document.addEventListener('visibilitychange', handleVisibility);

    // Pause when the decorative layer scrolls off-screen so it never burns
    // cycles behind other content.
    const intersectionObserver =
      typeof IntersectionObserver !== 'undefined'
        ? new IntersectionObserver(
            (entries) => {
              visibleInViewport = entries[0]?.isIntersecting ?? true;
              if (visibleInViewport) start();
              else stop();
            },
            { threshold: 0 },
          )
        : null;
    intersectionObserver?.observe(container);

    start();

    return () => {
      stop();
      document.removeEventListener('visibilitychange', handleVisibility);
      window.removeEventListener('resize', handleResize);
      resizeObserver?.disconnect();
      intersectionObserver?.disconnect();
      geometry.dispose();
      material.dispose();
      // Release the GL context slot (not just dispose) so repeated mounts of
      // the background do not exhaust the browser's WebGL context cap.
      try {
        renderer.forceContextLoss();
      } catch {
        /* context already lost */
      }
      renderer.dispose();
      if (renderer.domElement.parentNode === container) {
        container.removeChild(renderer.domElement);
      }
    };
  }, [resolvedTheme]);

  return (
    <div
      ref={containerRef}
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 -z-10 overflow-hidden opacity-90 [mask-image:radial-gradient(ellipse_85%_75%_at_50%_40%,black,transparent)]"
    />
  );
}

export default PointCloudBackground;
