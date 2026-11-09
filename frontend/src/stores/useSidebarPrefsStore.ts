// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Personal preferences for the left navigation menu, kept on this device:
 *  - label mode: item names wrap onto several lines, or stay on one line cut
 *    off at the panel edge (the full name is then in the tooltip);
 *  - width of the expanded panel, 200-360 px in steps of 8.
 *
 * The width is applied through `--oe-sidebar-width` (see Sidebar.tsx), which
 * also drives the content offset, so the page reflows in lockstep. The icon-only
 * mode keeps its own fixed width and ignores this preference.
 */

import { create } from 'zustand';

const STORAGE_KEY = 'oe_sidebar_prefs';
const COLLAPSE_KEY = 'oe_sidebar_iconified';

export type SidebarLabelMode = 'wrap' | 'single';

export const SIDEBAR_MIN_WIDTH = 200;
export const SIDEBAR_MAX_WIDTH = 360;
export const SIDEBAR_WIDTH_STEP = 8;
export const SIDEBAR_DEFAULT_WIDTH = 248;

/** Clamp to the allowed range and snap to the step; non-numbers give the default. */
export function normalizeSidebarWidth(value: unknown): number {
  const n = typeof value === 'number' ? value : Number.NaN;
  if (!Number.isFinite(n)) return SIDEBAR_DEFAULT_WIDTH;
  const snapped = Math.round(n / SIDEBAR_WIDTH_STEP) * SIDEBAR_WIDTH_STEP;
  return Math.min(SIDEBAR_MAX_WIDTH, Math.max(SIDEBAR_MIN_WIDTH, snapped));
}

function normalizeLabelMode(value: unknown): SidebarLabelMode {
  return value === 'single' ? 'single' : 'wrap';
}

function read(): { width: number; labelMode: SidebarLabelMode } {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as { width?: unknown; labelMode?: unknown };
      return { width: normalizeSidebarWidth(parsed.width), labelMode: normalizeLabelMode(parsed.labelMode) };
    }
  } catch {
    /* storage unavailable or corrupt: fall back to defaults */
  }
  return { width: SIDEBAR_DEFAULT_WIDTH, labelMode: 'wrap' };
}

function persist(width: number, labelMode: SidebarLabelMode): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ width, labelMode }));
  } catch {
    /* storage unavailable */
  }
}

interface SidebarPrefsState {
  width: number;
  labelMode: SidebarLabelMode;
  setWidth: (value: number) => void;
  resetWidth: () => void;
  setLabelMode: (mode: SidebarLabelMode) => void;
}

const initial = read();

export const useSidebarPrefsStore = create<SidebarPrefsState>((set, get) => ({
  width: initial.width,
  labelMode: initial.labelMode,
  setWidth: (value) => {
    const width = normalizeSidebarWidth(value);
    persist(width, get().labelMode);
    set({ width });
  },
  resetWidth: () => get().setWidth(SIDEBAR_DEFAULT_WIDTH),
  setLabelMode: (mode) => {
    const labelMode = normalizeLabelMode(mode);
    persist(get().width, labelMode);
    set({ labelMode });
  },
}));

// Apply the saved width before the first paint so the layout does not jump
// when the sidebar mounts. Icon-only mode is left to Sidebar.tsx.
if (typeof document !== 'undefined' && initial.width !== SIDEBAR_DEFAULT_WIDTH) {
  let iconified = false;
  try {
    iconified = localStorage.getItem(COLLAPSE_KEY) === '1';
  } catch {
    /* storage unavailable */
  }
  if (!iconified) {
    document.documentElement.style.setProperty('--oe-sidebar-width', `${initial.width}px`);
  }
}
