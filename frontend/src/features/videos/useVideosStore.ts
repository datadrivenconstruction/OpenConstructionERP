// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// What the Videos page remembers for this browser: the role and market the
// reader chose for recommendations, and which videos they have started or
// marked as watched.
//
// "Started" is recorded when play is pressed. The player is a plain embed with
// no API handshake, so the page cannot see how far anybody got; "watched" is
// therefore the reader's own mark, never inferred. Storage can be missing or
// throw (private windows, blocked site data), so every access is guarded and
// the page works without it.

import { create } from 'zustand';
import type { ProfessionalRole } from '@/features/cases/types';
import { VALID_ROLES } from '@/features/cases/useCasesStore';

const ROLE_KEY = 'oe_videos_role';
const MARKET_KEY = 'oe_videos_market';
const PROGRESS_KEY = 'oe_videos_progress';

/** `auto` follows the active project and the interface language. */
export type MarketChoice = 'auto' | 'any' | string;

interface Progress {
  started: Record<string, number>;
  watched: Record<string, true>;
}

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* storage unavailable: the choice lasts for this visit only */
  }
}

function readRole(): ProfessionalRole | null {
  const raw = read(ROLE_KEY);
  return raw && (VALID_ROLES as readonly string[]).includes(raw) ? (raw as ProfessionalRole) : null;
}

function readMarket(): MarketChoice {
  const raw = read(MARKET_KEY);
  return raw && /^(any|[A-Z]{2})$/.test(raw) ? raw : 'auto';
}

function readProgress(): Progress {
  try {
    const parsed = JSON.parse(read(PROGRESS_KEY) ?? '{}') as Partial<Progress>;
    const started: Record<string, number> = {};
    const watched: Record<string, true> = {};
    for (const [id, at] of Object.entries(parsed.started ?? {})) if (typeof at === 'number') started[id] = at;
    for (const [id, on] of Object.entries(parsed.watched ?? {})) if (on === true) watched[id] = true;
    return { started, watched };
  } catch {
    return { started: {}, watched: {} };
  }
}

interface VideosState extends Progress {
  role: ProfessionalRole | null;
  market: MarketChoice;
  setRole: (role: ProfessionalRole | null) => void;
  setMarket: (market: MarketChoice) => void;
  markStarted: (id: string) => void;
  toggleWatched: (id: string) => void;
}

export const useVideosStore = create<VideosState>((set, get) => ({
  role: readRole(),
  market: readMarket(),
  ...readProgress(),
  setRole: (role) => {
    write(ROLE_KEY, role);
    set({ role });
  },
  setMarket: (market) => {
    write(MARKET_KEY, market === 'auto' ? null : market);
    set({ market });
  },
  markStarted: (id) => {
    const started = { ...get().started, [id]: Date.now() };
    write(PROGRESS_KEY, JSON.stringify({ started, watched: get().watched }));
    set({ started });
  },
  toggleWatched: (id) => {
    const watched = { ...get().watched };
    if (watched[id]) delete watched[id];
    else watched[id] = true;
    write(PROGRESS_KEY, JSON.stringify({ started: get().started, watched }));
    set({ watched });
  },
}));
