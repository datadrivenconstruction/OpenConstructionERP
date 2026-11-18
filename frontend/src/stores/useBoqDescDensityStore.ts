// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * BOQ Langtext display store ("Langtext anzeigen").
 *
 * How much of the Langtext (long text) the BOQ grid shows under each Kurztext,
 * for positions and section headers alike:
 *
 *   - compact     : off. Kurztext only, one line; the row's chevron or the
 *                   section's Langtext chip opens a single text.
 *   - comfortable : the first two lines of the Langtext under the Kurztext.
 *   - tall        : the full Langtext; the row grows to fit it.
 *
 * The Langtext lives in `metadata.gaeb_long_text`; the text editor writes it.
 * Remembered per signed-in user (in this browser) so the choice survives
 * reloads and does not leak to a colleague on a shared PC. The storage key
 * moved with the change of meaning, so everyone starts at "first two lines".
 */

import { create } from 'zustand';
import { useAuthStore } from './useAuthStore';

export type BoqDescDensity = 'compact' | 'comfortable' | 'tall';

const STORAGE_KEY = 'oe_boq_langtext_mode';
const ORDER: BoqDescDensity[] = ['compact', 'comfortable', 'tall'];
const DEFAULT: BoqDescDensity = 'comfortable';

function storageKey(): string {
  const userId = useAuthStore.getState().userId;
  return userId ? `${STORAGE_KEY}:${userId}` : STORAGE_KEY;
}

function read(): BoqDescDensity {
  try {
    const v = localStorage.getItem(storageKey());
    return v === 'compact' || v === 'comfortable' || v === 'tall' ? v : DEFAULT;
  } catch {
    return DEFAULT;
  }
}

function persist(value: BoqDescDensity): void {
  try {
    localStorage.setItem(storageKey(), value);
  } catch {
    /* ignore — a private-mode browser just loses the preference */
  }
}

interface BoqDescDensityState {
  density: BoqDescDensity;
  setDensity: (value: BoqDescDensity) => void;
  /** Advance off -> first lines -> full -> off. */
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

// Another user signing in on this browser gets their own choice back.
useAuthStore.subscribe((state, prev) => {
  if (state.userId !== prev.userId) useBoqDescDensityStore.setState({ density: read() });
});
