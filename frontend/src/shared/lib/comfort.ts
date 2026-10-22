/**
 * Personal comfort options (motion, contrast): kept on this device and set as
 * `data-motion` / `data-contrast` on <html>, like the appearance axes. They are
 * accessibility preferences, so they are never part of a workspace default.
 */
export const MOTIONS = ['full', 'reduced'] as const;
export const CONTRASTS = ['standard', 'high'] as const;

export type Motion = (typeof MOTIONS)[number];
export type Contrast = (typeof CONTRASTS)[number];

export interface Comfort {
  motion: Motion;
  contrast: Contrast;
}

export const DEFAULT_COMFORT: Comfort = { motion: 'full', contrast: 'standard' };
export const COMFORT_KEY = 'oe_comfort_v1';

export function readComfort(): Comfort {
  try {
    const raw = JSON.parse(localStorage.getItem(COMFORT_KEY) ?? 'null') as Partial<Record<keyof Comfort, unknown>> | null;
    return {
      motion: MOTIONS.includes(raw?.motion as Motion) ? (raw!.motion as Motion) : DEFAULT_COMFORT.motion,
      contrast: CONTRASTS.includes(raw?.contrast as Contrast) ? (raw!.contrast as Contrast) : DEFAULT_COMFORT.contrast,
    };
  } catch {
    return { ...DEFAULT_COMFORT };
  }
}

export function applyComfort(c: Comfort, root: HTMLElement = document.documentElement): void {
  root.dataset.motion = c.motion;
  root.dataset.contrast = c.contrast;
}

export function writeComfort(c: Comfort): void {
  try {
    if (c.motion === DEFAULT_COMFORT.motion && c.contrast === DEFAULT_COMFORT.contrast) {
      localStorage.removeItem(COMFORT_KEY);
    } else {
      localStorage.setItem(COMFORT_KEY, JSON.stringify(c));
    }
  } catch {
    /* storage blocked: the choice still applies for this session */
  }
  applyComfort(c);
}
