// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Simple / Advanced view mode store.
 *
 * Simple mode: clean interface with essential features only.
 * Advanced mode: full professional toolset with all options visible.
 *
 * Where the mode comes from, strongest first:
 *   1. The user's own choice, stored on the server (`/v1/users/me/view-mode/`)
 *      so it follows the login to every browser. Only `setMode` writes it, and
 *      `setMode` is what the Settings card and the Modules page notice call
 *      when the user picks a mode. The guided tour also calls it to switch to
 *      Advanced when a step needs a group Simple hides, so that switch is
 *      stored as a choice too.
 *   2. A choice this browser already remembers (`oe_view_mode`). Builds before
 *      the server copy existed kept the mode only here. That value is honoured
 *      but never promoted to the server: old onboarding wrote `simple` into it
 *      on its own, so it cannot be told apart from a choice.
 *   3. A default derived from the company profile (`useViewModeDefault`),
 *      applied through `applyDefault`, which writes nothing anywhere. A default
 *      that got written would turn into a "choice" on the next load, which is
 *      how a fresh profile used to be locked into Simple.
 *   4. `simple`, until any of the above answers.
 */

import { create } from 'zustand';
import { apiGet, apiPut } from '@/shared/lib/api';

export type ViewMode = 'simple' | 'advanced';

const STORAGE_KEY = 'oe_view_mode';
/** Which user the cached `oe_view_mode` belongs to, once the server copy
 *  exists. A cache without an owner is a legacy per-browser choice. */
const OWNER_KEY = 'oe_view_mode_owner';
const ENDPOINT = '/v1/users/me/view-mode/';

function readStored(): ViewMode | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === 'advanced' || v === 'simple' ? v : null;
  } catch {
    return null;
  }
}

function writeStored(mode: ViewMode, owner: string | null): void {
  try {
    localStorage.setItem(STORAGE_KEY, mode);
    if (owner) localStorage.setItem(OWNER_KEY, owner);
  } catch { /* ignore */ }
}

function clearStored(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
    localStorage.removeItem(OWNER_KEY);
  } catch { /* ignore */ }
}

function readOwner(): string | null {
  try {
    return localStorage.getItem(OWNER_KEY);
  } catch {
    return null;
  }
}

interface ViewModeState {
  mode: ViewMode;
  isAdvanced: boolean;
  /** True when `mode` is somebody's choice (server or this browser), false
   *  while it is a default. Only a default may be replaced by `applyDefault`. */
  chosen: boolean;
  /** The user picks a mode: remembered here and on the server. */
  setMode: (mode: ViewMode) => void;
  toggle: () => void;
  /** Show a derived default. Ignored once a choice exists; writes nothing. */
  applyDefault: (mode: ViewMode) => void;
  /** Show Advanced for this session only, e.g. when the guided tour points at
   *  a group Simple hides. Writes nothing and leaves `chosen` alone, so the
   *  user's saved choice is back on the next load. */
  revealAdvanced: () => void;
}

const initial = readStored();

/** The signed-in user the current choice belongs to, set by hydration. */
let currentUser: string | null = null;

export const useViewModeStore = create<ViewModeState>((set, get) => ({
  mode: initial ?? 'simple',
  isAdvanced: initial === 'advanced',
  chosen: initial !== null,

  setMode: (mode: ViewMode) => {
    writeStored(mode, currentUser);
    set({ mode, isAdvanced: mode === 'advanced', chosen: true });
    // Best-effort: an offline session keeps the local choice. Before sign-in
    // there is nobody to store it for, and the 401 would only land in the
    // bug-report buffer.
    if (currentUser) apiPut(ENDPOINT, { mode }).catch(() => undefined);
  },

  toggle: () => {
    const next = get().mode === 'simple' ? 'advanced' : 'simple';
    get().setMode(next);
  },

  applyDefault: (mode: ViewMode) => {
    if (get().chosen || get().mode === mode) return;
    set({ mode, isAdvanced: mode === 'advanced' });
  },

  revealAdvanced: () => {
    if (get().mode === 'advanced') return;
    set({ mode: 'advanced', isAdvanced: true });
  },
}));

let hydratedFor: string | null = null;

/**
 * Pull the user's stored choice once per signed-in user.
 *
 *   - Server has a choice: it wins and is cached here for the first paint.
 *   - Server has none: a cache another user left on this browser is dropped,
 *     so the default applies; a legacy cache without an owner is kept.
 *   - 401 / offline: whatever this browser had stays.
 */
export async function hydrateViewModeFromServer(userId: string | null): Promise<void> {
  if (!userId) {
    // Signed out: nothing to store choices for until the next sign-in.
    hydratedFor = null;
    currentUser = null;
    return;
  }
  if (hydratedFor === userId) return;
  hydratedFor = userId;
  currentUser = userId;
  try {
    const remote = await apiGet<{ mode: ViewMode | null }>(ENDPOINT);
    const mode = remote?.mode;
    if (mode === 'simple' || mode === 'advanced') {
      writeStored(mode, userId);
      useViewModeStore.setState({ mode, isAdvanced: mode === 'advanced', chosen: true });
      return;
    }
    const owner = readOwner();
    if (owner && owner !== userId) {
      clearStored();
      useViewModeStore.setState({ chosen: false });
    }
  } catch {
    // Keep the local state.
  }
}

/** Test hook: forget which user was hydrated. */
export function _resetViewModeHydration(): void {
  hydratedFor = null;
  currentUser = null;
}
