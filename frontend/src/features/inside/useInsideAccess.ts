// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Inside track - supporter access gate.
//
// There is no payment integration yet, so the perk (early-look access to the
// Inside track panel) is unlocked with a plain supporter access code instead
// of a paid account flag. After someone donates they are handed a code by
// hand; entering it here flips a localStorage flag that this hook reads on
// every load. This is intentionally simple - the panel never gates the app's
// code or data, only a small news-and-roadmap page, so a shared or leaked
// code costs us nothing beyond an extra reader.

import { create } from 'zustand';

const STORAGE_KEY = 'oe_inside_unlocked';

/**
 * Supporter access codes that unlock the Inside track panel. Issued by hand
 * to donors for now (see the "Fund development" support flow). Add or retire
 * a code by editing this list - it is the single place that needs to change.
 */
export const SUPPORTER_CODES: readonly string[] = ['BACKER2026'];

function readUnlocked(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === '1';
  } catch {
    return false;
  }
}

function persistUnlocked(value: boolean): void {
  try {
    if (value) localStorage.setItem(STORAGE_KEY, '1');
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* private mode / quota - non-fatal, just does not survive reload */
  }
}

/** Normalizes a code for comparison so stray spaces or letter case do not
 *  block a supporter who typed the code slightly differently. */
function normalizeCode(code: string): string {
  return code.trim().toUpperCase();
}

interface InsideAccessState {
  /** Whether the Inside track panel is currently unlocked on this device. */
  unlocked: boolean;
  /** Checks a typed code against the valid set. Unlocks and persists on a
   *  match; returns whether it matched so the caller can show an error. */
  tryUnlock: (code: string) => boolean;
  /** Re-locks the panel (sign out of Inside track). Mainly useful for
   *  testing the gate again on a device that is already unlocked. */
  lock: () => void;
}

export const useInsideAccess = create<InsideAccessState>((set) => ({
  unlocked: readUnlocked(),

  tryUnlock: (code) => {
    const matches = SUPPORTER_CODES.some((valid) => normalizeCode(valid) === normalizeCode(code));
    if (matches) {
      persistUnlocked(true);
      set({ unlocked: true });
    }
    return matches;
  },

  lock: () => {
    persistUnlocked(false);
    set({ unlocked: false });
  },
}));
