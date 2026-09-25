// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The light half of "Videos for this step": which catalogue route a screen
// belongs to, and whether the reader has hidden the hint. The app shell loads
// this on every screen, so it imports the route counts and nothing else; the
// catalogue and the panel load only on a screen that has videos.

import { create } from 'zustand';
import { VIDEO_COUNT_BY_ROUTE } from './academyIndex.generated';

const ROUTES = Object.keys(VIDEO_COUNT_BY_ROUTE).sort((a, b) => b.length - a.length);
// `/projects/<id>/boq` is the project-scoped form of `/boq`; `/projects/new`
// is a route of its own.
const PROJECT_SCOPE = /^\/projects\/(?!new(?:\/|$))[^/]+(?=\/)/;

/** The catalogue route a pathname belongs to, longest match first, or null. */
export function videoRouteFor(pathname: string): string | null {
  const path = pathname.replace(PROJECT_SCOPE, '').replace(/\/+$/, '') || '/';
  return ROUTES.find((r) => path === r || path.startsWith(`${r}/`)) ?? null;
}

export function videoCountForRoute(route: string): number {
  return VIDEO_COUNT_BY_ROUTE[route] ?? 0;
}

const KEY = 'oe_videos_hints';

interface HintState {
  /** Hidden on every screen. */
  off: boolean;
  /** Routes the hint is hidden on. */
  hidden: string[];
}

function readHints(): HintState {
  try {
    const parsed = JSON.parse(localStorage.getItem(KEY) ?? '{}') as Partial<HintState>;
    return {
      off: parsed.off === true,
      hidden: Array.isArray(parsed.hidden) ? parsed.hidden.filter((r): r is string => typeof r === 'string') : [],
    };
  } catch {
    return { off: false, hidden: [] };
  }
}

function writeHints(state: HintState): void {
  try {
    if (!state.off && state.hidden.length === 0) localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    /* storage unavailable: the choice lasts for this visit only */
  }
}

interface VideoHintsState extends HintState {
  hideOn: (route: string) => void;
  unhideOn: (route: string) => void;
  setOff: (off: boolean) => void;
  showAgain: () => void;
  isHidden: (route: string) => boolean;
}

export const useVideoHintsStore = create<VideoHintsState>((set, get) => ({
  ...readHints(),
  hideOn: (route) => {
    const next = { off: get().off, hidden: [...new Set([...get().hidden, route])] };
    writeHints(next);
    set(next);
  },
  unhideOn: (route) => {
    const next = { off: get().off, hidden: get().hidden.filter((r) => r !== route) };
    writeHints(next);
    set(next);
  },
  setOff: (off) => {
    const next = { off, hidden: get().hidden };
    writeHints(next);
    set(next);
  },
  showAgain: () => {
    const next = { off: false, hidden: [] };
    writeHints(next);
    set(next);
  },
  isHidden: (route) => get().off || get().hidden.includes(route),
}));
