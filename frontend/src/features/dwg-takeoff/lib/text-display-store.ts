// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * LocalStorage persistence for the viewer's text display setting.
 *
 * Stored under one global key rather than per drawing, matching
 * ``dwg:snap_modes``: how big a user wants annotation to be is a property of
 * the user's eyes and screen, not of the file they happen to have open. The
 * per-drawing keys (``dwg:scale:{id}``, ``dwg-cal:…``) carry things the drawing
 * itself determines, which this is not.
 *
 * Reads are defensive in the same way as ``loadCalibration``: anything that is
 * not a well-formed state falls back to the default instead of poisoning the
 * viewer. Unlike calibration there is no ``null`` outcome, because "no
 * preference" has a correct answer - draw the text the way the drawing asks.
 */

/** Text display preference. ``scale`` multiplies the drawn glyph height. */
export interface TextDisplayState {
  /** False hides every text entity on the canvas. */
  visible: boolean;
  /** Multiplier on the rendered text height. ``1`` = the drawing's own size. */
  scale: number;
}

/** Key. Exported so tests and devtools don't sprinkle the literal around. */
export const TEXT_DISPLAY_KEY = 'dwg:text_display';

/** Text shown, at the size the drawing asks for. */
export const DEFAULT_TEXT_DISPLAY: TextDisplayState = { visible: true, scale: 1 };

/** Range of the size control. Half size still reads as a label at a glance;
 *  2.5x is where a single word starts to cover the geometry under it. */
export const MIN_TEXT_SCALE = 0.5;
export const MAX_TEXT_SCALE = 2.5;
/** One press of the smaller / larger button. */
export const TEXT_SCALE_STEP = 0.25;

/** Snap a multiplier into the supported range. Non-numbers become ``1``, so a
 *  corrupt stored value never renders text at zero or at infinity. */
export function clampTextScale(value: number): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return DEFAULT_TEXT_DISPLAY.scale;
  return Math.max(MIN_TEXT_SCALE, Math.min(MAX_TEXT_SCALE, value));
}

/** Next value of the size control, one step in either direction, clamped.
 *  Rounded to 2 decimals so repeated steps don't accumulate float dust into
 *  the percentage the user reads. */
export function stepTextScale(value: number, direction: 1 | -1): number {
  const next = clampTextScale(value) + direction * TEXT_SCALE_STEP;
  return clampTextScale(Math.round(next * 100) / 100);
}

/** Load the stored preference, or the default when there is none, when the
 *  entry is malformed, or when ``localStorage`` is unavailable (SSR / private
 *  browsing). Never throws. */
export function loadTextDisplay(): TextDisplayState {
  try {
    if (typeof localStorage === 'undefined') return { ...DEFAULT_TEXT_DISPLAY };
    const raw = localStorage.getItem(TEXT_DISPLAY_KEY);
    if (!raw) return { ...DEFAULT_TEXT_DISPLAY };
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return { ...DEFAULT_TEXT_DISPLAY };
    const obj = parsed as Record<string, unknown>;
    return {
      visible: typeof obj.visible === 'boolean' ? obj.visible : DEFAULT_TEXT_DISPLAY.visible,
      scale: clampTextScale(obj.scale as number),
    };
  } catch {
    return { ...DEFAULT_TEXT_DISPLAY };
  }
}

/** Persist the preference. Swallows storage errors (quota, private browsing)
 *  so a failed save degrades to in-memory only rather than crashing the UI. */
export function saveTextDisplay(state: TextDisplayState): void {
  try {
    if (typeof localStorage === 'undefined') return;
    localStorage.setItem(
      TEXT_DISPLAY_KEY,
      JSON.stringify({ visible: state.visible, scale: clampTextScale(state.scale) }),
    );
  } catch {
    // Ignore — localStorage is best-effort.
  }
}
