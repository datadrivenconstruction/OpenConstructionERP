// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Adaptive render-resolution controller for touch site mode.
 *
 * Walking a large model on a phone or a low-spec laptop can drop the frame
 * rate below usable. This controller watches the smoothed frame time and
 * trims the renderer pixel ratio down (fewer fragments -> faster) when frames
 * are slow, then eases it back up when there is headroom - so the picture is
 * as sharp as the device can sustain without ever stuttering.
 *
 * It is a PURE state machine: feed it frame durations via {@link sample} and
 * read back a target scale. The side effect (renderer.setPixelRatio) lives in
 * SceneManager. Hysteresis (a gap between the down- and up-shift thresholds), a
 * warm-up window and a cooldown between changes keep the scale from
 * oscillating. No DOM, no three.js, fully unit testable.
 */

export interface AdaptiveResolutionOptions {
  /** Lowest pixel ratio it will drop to. Default 0.5. */
  minScale?: number;
  /** Highest pixel ratio it will climb back to (the manual ceiling). Default 1. */
  maxScale?: number;
  /** Below this smoothed FPS, shrink the scale. Default 40. */
  targetFps?: number;
  /** Above this smoothed FPS (with headroom), grow the scale. Default 58. */
  recoverFps?: number;
  /** EMA smoothing factor 0..1 (higher = reacts faster). Default 0.1. */
  emaAlpha?: number;
  /** Scale change applied per adjustment. Default 0.15. */
  step?: number;
  /** Minimum rendered frames between two adjustments. Default 40. */
  cooldownFrames?: number;
  /** Rendered frames ignored at the start (buffers warming up). Default 24. */
  warmupFrames?: number;
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

export class AdaptiveResolution {
  private readonly minScale: number;
  private readonly maxScale: number;
  private readonly targetMs: number; // frame time above which we shrink
  private readonly recoverMs: number; // frame time below which we grow
  private readonly emaAlpha: number;
  private readonly step: number;
  private readonly cooldownFrames: number;
  private readonly warmupFrames: number;

  private _scale: number;
  private _emaMs = 0;
  private _framesSeen = 0;
  private _framesSinceChange = 0;

  constructor(opts: AdaptiveResolutionOptions = {}) {
    this.minScale = opts.minScale ?? 0.5;
    this.maxScale = Math.max(this.minScale, opts.maxScale ?? 1);
    const targetFps = opts.targetFps ?? 40;
    const recoverFps = opts.recoverFps ?? 58;
    this.targetMs = 1000 / targetFps;
    this.recoverMs = 1000 / recoverFps;
    this.emaAlpha = clamp(opts.emaAlpha ?? 0.1, 0.01, 1);
    this.step = opts.step ?? 0.15;
    this.cooldownFrames = Math.max(1, opts.cooldownFrames ?? 40);
    this.warmupFrames = Math.max(0, opts.warmupFrames ?? 24);
    this._scale = this.maxScale;
  }

  /** Current target pixel ratio. */
  get scale(): number {
    return this._scale;
  }

  /** Smoothed frame time in ms (0 before the first sample). */
  get smoothedFrameMs(): number {
    return this._emaMs;
  }

  /** Reset to the ceiling scale and clear the frame-time history. */
  reset(): void {
    this._scale = this.maxScale;
    this._emaMs = 0;
    this._framesSeen = 0;
    this._framesSinceChange = 0;
  }

  /**
   * Feed one rendered frame's duration (ms) and get the target pixel ratio.
   * Non-finite or non-positive inputs are ignored (the scale is unchanged).
   */
  sample(frameMs: number): number {
    if (!Number.isFinite(frameMs) || frameMs <= 0) return this._scale;

    this._framesSeen += 1;
    this._emaMs =
      this._framesSeen === 1 ? frameMs : this._emaMs + this.emaAlpha * (frameMs - this._emaMs);

    // Let the average settle before acting.
    if (this._framesSeen <= this.warmupFrames) return this._scale;

    this._framesSinceChange += 1;
    if (this._framesSinceChange < this.cooldownFrames) return this._scale;

    if (this._emaMs > this.targetMs && this._scale > this.minScale) {
      this._scale = clamp(this._scale - this.step, this.minScale, this.maxScale);
      this._framesSinceChange = 0;
    } else if (this._emaMs < this.recoverMs && this._scale < this.maxScale) {
      this._scale = clamp(this._scale + this.step, this.minScale, this.maxScale);
      this._framesSinceChange = 0;
    }
    return this._scale;
  }
}
