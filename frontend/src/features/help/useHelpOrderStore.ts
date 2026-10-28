// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How-it-works hub - section order store.
//
// A thin zustand store over localStorage that lets a user choose how the manual
// sections read top to bottom: the intuitive project Lifecycle (the default),
// plain Alphabetical, or a Custom order they arrange themselves with the up/down
// arrows on each section. Only the chosen mode and the custom order are kept
// here; the actual grouping stays in `groupByCategory`. Same lightweight,
// no-backend, localStorage pattern as `useCasesStore`.

import { create } from 'zustand';
import { HOW_IT_WORKS_CATEGORIES } from './types';
import type { CategoryId } from './types';

const MODE_KEY = 'oe_howto_sort_mode';
const ORDER_KEY = 'oe_howto_order';

/** How the hub orders its sections. `lifecycle` is the canonical, intuitive
 *  project-lifecycle sequence (the default first-run experience). */
export type HelpSortMode = 'lifecycle' | 'alphabetical' | 'custom';

const VALID_MODES: readonly HelpSortMode[] = ['lifecycle', 'alphabetical', 'custom'];

/** The canonical lifecycle order, and the default custom order on first run. */
export const CANONICAL_CATEGORY_ORDER: CategoryId[] = HOW_IT_WORKS_CATEGORIES.map((c) => c.id);
const VALID_CATEGORIES = new Set<string>(CANONICAL_CATEGORY_ORDER);

/**
 * Reconcile a stored order with the current category list: keep the saved
 * positions of ids that still exist (deduped), then append any categories the
 * saved order does not mention (in canonical order). This keeps a user's custom
 * order stable while staying complete as categories are added or removed.
 */
function reconcileOrder(saved: readonly string[]): CategoryId[] {
  const seen = new Set<string>();
  const out: CategoryId[] = [];
  for (const id of saved) {
    if (VALID_CATEGORIES.has(id) && !seen.has(id)) {
      out.push(id as CategoryId);
      seen.add(id);
    }
  }
  for (const id of CANONICAL_CATEGORY_ORDER) {
    if (!seen.has(id)) out.push(id);
  }
  return out;
}

function readMode(): HelpSortMode {
  try {
    const raw = localStorage.getItem(MODE_KEY);
    return raw && (VALID_MODES as string[]).includes(raw) ? (raw as HelpSortMode) : 'lifecycle';
  } catch {
    return 'lifecycle';
  }
}

function persistMode(mode: HelpSortMode) {
  try {
    localStorage.setItem(MODE_KEY, mode);
  } catch {
    /* localStorage unavailable (private mode / quota) - non-fatal. */
  }
}

function readOrder(): CategoryId[] {
  try {
    const raw = localStorage.getItem(ORDER_KEY);
    if (!raw) return [...CANONICAL_CATEGORY_ORDER];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [...CANONICAL_CATEGORY_ORDER];
    return reconcileOrder(parsed.filter((id): id is string => typeof id === 'string'));
  } catch {
    return [...CANONICAL_CATEGORY_ORDER];
  }
}

function persistOrder(order: CategoryId[]) {
  try {
    localStorage.setItem(ORDER_KEY, JSON.stringify(order));
  } catch {
    /* non-fatal */
  }
}

interface HelpOrderState {
  /** The chosen sort mode. Persists across visits. */
  mode: HelpSortMode;
  /** The user's custom section order (all categories, canonical on first run).
   *  Only applied when `mode === 'custom'`. */
  customOrder: CategoryId[];
  /** Switch the sort mode. */
  setMode: (mode: HelpSortMode) => void;
  /** Move a section one slot up (dir -1) or down (dir 1) in the custom order.
   *  A no-op at the ends. */
  moveCategory: (id: CategoryId, dir: -1 | 1) => void;
}

export const useHelpOrderStore = create<HelpOrderState>((set, get) => ({
  mode: readMode(),
  customOrder: readOrder(),

  setMode: (mode) => {
    persistMode(mode);
    set({ mode });
  },

  moveCategory: (id, dir) => {
    const order = get().customOrder;
    const from = order.indexOf(id);
    const to = from + dir;
    if (from === -1 || to < 0 || to >= order.length) return;
    const next = [...order];
    const moved = next[from];
    const displaced = next[to];
    if (moved === undefined || displaced === undefined) return;
    next[from] = displaced;
    next[to] = moved;
    persistOrder(next);
    set({ customOrder: next });
  },
}));
