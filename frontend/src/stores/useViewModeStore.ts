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
    // Default is 'simple' for the Indonesia/ACAP launch (a first-time user
    // with no persisted choice sees the decluttered sidebar). An explicit
    // 'advanced' choice — stored the moment a user flips the toggle — is
    // still honored and persists across sessions, so this only changes the
    // out-of-the-box default, not the toggle's reversibility.
    return v === 'advanced' ? 'advanced' : 'simple';
  } catch {
    return 'simple';
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
