/**
 * Simple / Advanced view mode store.
 *
 * Simple mode: clean interface with essential features only.
 * Advanced mode: full professional toolset with all options visible.
 *
 * Persists to localStorage so the user's choice is remembered.
 */

import { create } from 'zustand';

export type ViewMode = 'simple' | 'advanced';

const STORAGE_KEY = 'oe_view_mode';

function readMode(): ViewMode {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === 'simple' ? 'simple' : 'advanced';
  } catch {
    return 'advanced';
  }
}

interface ViewModeState {
  mode: ViewMode;
  isAdvanced: boolean;
  setMode: (mode: ViewMode) => void;
  toggle: () => void;
}

export const useViewModeStore = create<ViewModeState>((set, get) => ({
  mode: readMode(),
  isAdvanced: readMode() === 'advanced',

  setMode: (mode: ViewMode) => {
    try { localStorage.setItem(STORAGE_KEY, mode); } catch { /* ignore */ }
    set({ mode, isAdvanced: mode === 'advanced' });
  },

  toggle: () => {
    const next = get().mode === 'simple' ? 'advanced' : 'simple';
    get().setMode(next);
  },
}));
