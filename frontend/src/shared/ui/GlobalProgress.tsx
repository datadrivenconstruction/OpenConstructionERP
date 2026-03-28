/**
 * GlobalProgress — thin animated bar at top of viewport for long operations.
 * Usage: useProgressStore.getState().start() / .done()
 */
import { useEffect, useRef } from 'react';
import { create } from 'zustand';

interface ProgressStore {
  isActive: boolean;
  progress: number;
  start: () => void;
  done: () => void;
  cancel: () => void;
}

let animationFrame: number | null = null;
let startTime = 0;
let safetyTimer: ReturnType<typeof setTimeout> | null = null;
let doneTimer: ReturnType<typeof setTimeout> | null = null;

const ANIMATION_DURATION_MS = 10_000; // time to reach 90%
const SAFETY_TIMEOUT_MS = 30_000; // auto-cancel after 30s

export const useProgressStore = create<ProgressStore>((set, get) => ({
  isActive: false,
  progress: 0,

  start: () => {
    // Clear any pending done/safety timers
    if (doneTimer) {
      clearTimeout(doneTimer);
      doneTimer = null;
    }
    if (safetyTimer) {
      clearTimeout(safetyTimer);
      safetyTimer = null;
    }
    if (animationFrame) {
      cancelAnimationFrame(animationFrame);
      animationFrame = null;
    }

    startTime = performance.now();
    set({ isActive: true, progress: 0 });

    const tick = () => {
      const elapsed = performance.now() - startTime;
      // Ease-out: fast at start, slowing as it approaches 90%
      const t = Math.min(elapsed / ANIMATION_DURATION_MS, 1);
      const progress = t * 90;
      set({ progress });

      if (t < 1 && get().isActive) {
        animationFrame = requestAnimationFrame(tick);
      }
    };
    animationFrame = requestAnimationFrame(tick);

    // Safety timeout: auto-cancel after 30s
    safetyTimer = setTimeout(() => {
      get().cancel();
    }, SAFETY_TIMEOUT_MS);
  },

  done: () => {
    if (animationFrame) {
      cancelAnimationFrame(animationFrame);
      animationFrame = null;
    }
    if (safetyTimer) {
      clearTimeout(safetyTimer);
      safetyTimer = null;
    }

    set({ progress: 100 });

    // Hide after 300ms
    doneTimer = setTimeout(() => {
      set({ isActive: false, progress: 0 });
      doneTimer = null;
    }, 300);
  },

  cancel: () => {
    if (animationFrame) {
      cancelAnimationFrame(animationFrame);
      animationFrame = null;
    }
    if (safetyTimer) {
      clearTimeout(safetyTimer);
      safetyTimer = null;
    }
    if (doneTimer) {
      clearTimeout(doneTimer);
      doneTimer = null;
    }
    set({ isActive: false, progress: 0 });
  },
}));

export function GlobalProgress() {
  const isActive = useProgressStore((s) => s.isActive);
  const progress = useProgressStore((s) => s.progress);
  const barRef = useRef<HTMLDivElement>(null);

  // Sync progress to the bar width via ref for smooth animation
  useEffect(() => {
    if (barRef.current) {
      barRef.current.style.width = `${progress}%`;
    }
  }, [progress]);

  if (!isActive && progress === 0) return null;

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        height: '3px',
        zIndex: 9999,
        pointerEvents: 'none',
      }}
    >
      <div
        ref={barRef}
        style={{
          height: '100%',
          width: '0%',
          backgroundColor: 'var(--color-oe-blue, #2563eb)',
          transition: progress === 100 ? 'width 200ms ease-out, opacity 200ms ease-out' : 'width 100ms linear',
          opacity: progress === 100 ? 0 : 1,
          borderRadius: '0 2px 2px 0',
          boxShadow: '0 0 8px var(--color-oe-blue, #2563eb)',
        }}
      />
    </div>
  );
}
