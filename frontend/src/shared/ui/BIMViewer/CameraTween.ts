// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * CameraTween — pure rAF-driven interpolator between two camera states.
 *
 * Used by SceneManager.flyTo() and the View Cube to smoothly animate
 * the camera between viewpoints. Has zero dependency on three.js or
 * any rendering layer — callers receive plain CameraState updates per
 * frame and are responsible for applying them to their camera + controls.
 *
 * WHY: A pure helper means we can unit-test the easing curve and the
 * cancellation contract without spinning up a WebGL renderer. The
 * SceneManager imports this and bridges into THREE.* objects.
 */

export interface CameraState {
  position: [number, number, number];
  target: [number, number, number];
  up?: [number, number, number];
}

/** Cubic ease-in-out — passes through (0,0), (0.5,0.5), (1,1). */
export function easeInOutCubic(t: number): number {
  if (t <= 0) return 0;
  if (t >= 1) return 1;
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

function lerpVec3(
  a: [number, number, number],
  b: [number, number, number],
  t: number,
): [number, number, number] {
  return [lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t)];
}

/**
 * Animate between two camera states over `durationMs` milliseconds.
 *
 * Returns a `cancel()` function that aborts the tween on the next rAF
 * tick. Aborted tweens do NOT call `onComplete` — callers chain a new
 * tween freely without worrying about a stale completion racing in.
 */
export class CameraTween {
  private rafHandle: number | null = null;
  private cancelled = false;

  /** Convenience flag for callers — true while the tween is running. */
  get isActive(): boolean {
    return this.rafHandle !== null && !this.cancelled;
  }

  start(
    from: CameraState,
    to: CameraState,
    durationMs: number,
    onUpdate: (state: CameraState) => void,
    onComplete?: () => void,
  ): () => void {
    // Guard against pathological durations — clamp to 1 ms so we
    // always at least call onComplete on the next frame.
    const duration = Math.max(1, durationMs);
    const startTime =
      typeof performance !== 'undefined' && performance.now
        ? performance.now()
        : Date.now();

    this.cancelled = false;

    const fromUp = from.up ?? [0, 1, 0];
    const toUp = to.up ?? [0, 1, 0];

    const step = (now: number) => {
      if (this.cancelled) {
        this.rafHandle = null;
        return;
      }
      const elapsed = now - startTime;
      const rawT = Math.min(1, Math.max(0, elapsed / duration));
      const t = easeInOutCubic(rawT);

      const next: CameraState = {
        position: lerpVec3(from.position, to.position, t),
        target: lerpVec3(from.target, to.target, t),
        up: lerpVec3(fromUp, toUp, t),
      };
      onUpdate(next);

      if (rawT >= 1) {
        // Snap to the exact target on the final frame so floating-point
        // drift never leaves the camera a hair off the destination.
        onUpdate({ position: to.position, target: to.target, up: toUp });
        this.rafHandle = null;
        onComplete?.();
        return;
      }
      this.rafHandle = requestAnimationFrame(step);
    };

    this.rafHandle = requestAnimationFrame(step);

    return () => this.cancel();
  }

  /**
   * Abort the current tween. Safe to call multiple times. Once cancelled,
   * the in-flight rAF callback will exit on its next tick without calling
   * onComplete.
   */
  cancel(): void {
    this.cancelled = true;
    if (this.rafHandle !== null) {
      cancelAnimationFrame(this.rafHandle);
      this.rafHandle = null;
    }
  }
}
