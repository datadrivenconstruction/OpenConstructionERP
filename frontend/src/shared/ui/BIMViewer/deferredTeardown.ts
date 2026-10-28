// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * DeferredTeardown - a one-shot, cancelable teardown timer that lets the BIM
 * viewers survive React's development double-mount (and any other
 * unmount-then-immediately-remount) without disposing a healthy WebGL scene.
 *
 * React 18 StrictMode mounts an effect, runs its cleanup, then mounts it
 * again, synchronously, within the same task. A viewer whose cleanup disposes
 * the WebGL context on the spot therefore force-loses the context and rebuilds
 * on the very next line. To the user that reads as a black canvas / "WebGL
 * unavailable", and it desyncs any "already loaded this model" bookkeeping so
 * the second, empty scene renders nothing.
 *
 * The fix is to DEFER the teardown by one task instead of running it inline:
 *   - the effect cleanup calls schedule(dispose); the dispose runs next task;
 *   - a remount that happens first calls cancel(); the dispose never runs and
 *     the caller reuses its live scene.
 * A genuine unmount has no matching remount, so the timer fires and the scene
 * is disposed for real, exactly one task later - imperceptible, and safe on a
 * canvas React has already detached.
 *
 * The scheduler and canceller are injectable so the behaviour can be
 * unit-tested deterministically, without real timers or a DOM.
 */
export type TeardownScheduler = (run: () => void) => number;
export type TeardownCanceller = (handle: number) => void;

export class DeferredTeardown {
  private handle: number | null = null;

  constructor(
    private readonly scheduleFn: TeardownScheduler = (run) =>
      setTimeout(run, 0) as unknown as number,
    private readonly cancelFn: TeardownCanceller = (h) => clearTimeout(h),
  ) {}

  /** True while a teardown has been scheduled but has not yet run. */
  get pending(): boolean {
    return this.handle !== null;
  }

  /**
   * Schedule ``run`` to execute on the next task. Any teardown already pending
   * is cancelled first, so only the most recently scheduled one survives.
   */
  schedule(run: () => void): void {
    this.cancel();
    this.handle = this.scheduleFn(() => {
      this.handle = null;
      run();
    });
  }

  /**
   * Cancel a pending teardown, if any. Returns true when a teardown was
   * actually cancelled (a remount beat the timer, so the caller should reuse
   * its existing scene), false when nothing was pending.
   */
  cancel(): boolean {
    if (this.handle === null) return false;
    this.cancelFn(this.handle);
    this.handle = null;
    return true;
  }
}
