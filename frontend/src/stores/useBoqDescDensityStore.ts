/**
 * BOQ description-density store.
 *
 * Controls how tall a position's description cell renders in the BOQ grid, so
 * an estimator can turn a one-line Kurztext into a full multi-line Langtext
 * view (like a German LV) without leaving the grid:
 *
 *   - compact     : single line, truncated with an ellipsis (the classic view).
 *   - comfortable : a few wrapped lines, newlines honoured, scroll for the rest.
 *   - tall        : a generous block for long specification text.
 *
 * The full text always lives in the single `description` field (stored as TEXT
 * on the backend, newlines preserved), and the large-text popup editor handles
 * writing arbitrarily long Langtext. This store only drives how much of it the
 * grid shows at rest. Persisted to localStorage so the choice survives reloads.
 */

import { create } from 'zustand';

export type BoqDescDensity = 'compact' | 'comfortable' | 'tall';

const STORAGE_KEY = 'oe_boq_desc_density';
const ORDER: BoqDescDensity[] = ['compact', 'comfortable', 'tall'];

function read(): BoqDescDensity {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === 'comfortable' || v === 'tall' ? v : 'compact';
  } catch {
    return 'compact';
  }
}

function persist(value: BoqDescDensity): void {
  try {
    localStorage.setItem(STORAGE_KEY, value);
  } catch {
    /* ignore — a private-mode browser just loses the preference */
  }
}

interface BoqDescDensityState {
  density: BoqDescDensity;
  setDensity: (value: BoqDescDensity) => void;
  /** Advance compact -> comfortable -> tall -> compact (toolbar button). */
  cycleDensity: () => void;
}

export const useBoqDescDensityStore = create<BoqDescDensityState>((set, get) => ({
  density: read(),
  setDensity: (value) => {
    persist(value);
    set({ density: value });
  },
  cycleDensity: () => {
    const next = ORDER[(ORDER.indexOf(get().density) + 1) % ORDER.length]!;
    persist(next);
    set({ density: next });
  },
}));

/** Pixel height a position row uses for each density (compact matches the
 *  grid's historical 32px position row). Exported so the grid's getRowHeight
 *  and any layout math stay in sync with the store. */
export const BOQ_DESC_ROW_HEIGHT: Record<BoqDescDensity, number> = {
  compact: 32,
  comfortable: 64,
  tall: 132,
};
