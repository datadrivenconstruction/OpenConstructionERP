// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Selection, the command stack (up to 200 per session) and the working
 * feature set of the plan canvas. Unsaved commands survive a reload through
 * sessionStorage; Save sends the net operations and clears the stack.
 */

import { create } from 'zustand';
import type { EditOp, FeatureMap, PlanCommand, PlanFeature } from './types';
import { fromData, netOps, pushCommand, type CommandData } from './engine/commands';

const STORAGE_PREFIX = 'oe.plan.edits.';

export interface PlanEditState {
  scope: string | null;
  /** Features as the server last sent them. */
  server: FeatureMap;
  /** `server` with the settled commands applied: what the undo stack reverts to. */
  base: FeatureMap;
  working: FeatureMap;
  undo: CommandData[];
  redo: CommandData[];
  /** Commands that fell off the undo stack but are not saved yet. */
  settled: CommandData[];
  selection: ReadonlySet<string>;
  savedAt: string | null;
  saving: boolean;
  /** Bind the store to a canvas (project + screen); restores unsaved commands of that scope. */
  bind(scope: string): void;
  /** New server state (after load or save); unsaved commands are replayed on top. */
  setBase(features: Iterable<PlanFeature>): void;
  push(cmd: PlanCommand & { data?: CommandData }): void;
  undoOne(): void;
  redoOne(): void;
  setSelection(ids: Iterable<string>): void;
  ops(): EditOp[];
  markSaved(at: string): void;
  setSaving(saving: boolean): void;
  discard(): void;
}

function readStored(scope: string): { undo: CommandData[]; redo: CommandData[] } {
  try {
    const raw = typeof sessionStorage !== 'undefined' ? sessionStorage.getItem(STORAGE_PREFIX + scope) : null;
    if (!raw) return { undo: [], redo: [] };
    const parsed = JSON.parse(raw) as { undo?: CommandData[]; redo?: CommandData[] };
    return { undo: parsed.undo ?? [], redo: parsed.redo ?? [] };
  } catch {
    return { undo: [], redo: [] };
  }
}

function store(scope: string | null, undo: CommandData[], redo: CommandData[]): void {
  if (!scope || typeof sessionStorage === 'undefined') return;
  try {
    if (undo.length === 0 && redo.length === 0) sessionStorage.removeItem(STORAGE_PREFIX + scope);
    else sessionStorage.setItem(STORAGE_PREFIX + scope, JSON.stringify({ undo, redo }));
  } catch {
    /* quota: the stack still lives in memory */
  }
}

function replay(base: FeatureMap, undo: readonly CommandData[]): FeatureMap {
  let out = base;
  for (const d of undo) out = fromData(d).apply(out);
  return out;
}

function asData(cmd: PlanCommand & { data?: CommandData }): CommandData | null {
  return cmd.data ?? null;
}

export const usePlanEditStore = create<PlanEditState>((set, get) => ({
  scope: null,
  server: new Map(),
  base: new Map(),
  working: new Map(),
  undo: [],
  redo: [],
  settled: [],
  selection: new Set(),
  savedAt: null,
  saving: false,

  bind(scope) {
    if (get().scope === scope) return;
    const { undo, redo } = readStored(scope);
    set({ scope, undo, redo, settled: [], selection: new Set(), server: new Map(), base: new Map(), working: new Map(), savedAt: null });
  },

  setBase(features) {
    const server = new Map<string, PlanFeature>();
    for (const f of features) server.set(f.id, f);
    const base = replay(server, get().settled);
    set({ server, base, working: replay(base, get().undo) });
  },

  push(cmd) {
    const data = asData(cmd);
    if (!data) {
      // A command without data cannot be stored or replayed; apply it to the view only.
      set({ working: cmd.apply(get().working) });
      return;
    }
    const s = get();
    const stack = pushCommand({ undo: s.undo, redo: s.redo }, data);
    // A stack that dropped its oldest command must rebase so revert stays consistent.
    const dropped = s.undo.length + 1 - stack.undo.length;
    let base = s.base;
    const settled = dropped > 0 ? [...s.settled, ...s.undo.slice(0, dropped)] : s.settled;
    if (dropped > 0) for (const d of s.undo.slice(0, dropped)) base = fromData(d).apply(base);
    set({ ...stack, settled, base, working: cmd.apply(s.working) });
    store(s.scope, stack.undo, stack.redo);
  },

  undoOne() {
    const s = get();
    const last = s.undo[s.undo.length - 1];
    if (!last) return;
    const undo = s.undo.slice(0, -1);
    const redo = [...s.redo, last];
    set({ undo, redo, working: fromData(last).revert(s.working) });
    store(s.scope, undo, redo);
  },

  redoOne() {
    const s = get();
    const next = s.redo[s.redo.length - 1];
    if (!next) return;
    const redo = s.redo.slice(0, -1);
    const undo = [...s.undo, next];
    set({ undo, redo, working: fromData(next).apply(s.working) });
    store(s.scope, undo, redo);
  },

  setSelection(ids) {
    set({ selection: new Set(ids) });
  },

  ops() {
    return netOps([...get().settled, ...get().undo]);
  },

  markSaved(at) {
    const s = get();
    set({ undo: [], redo: [], settled: [], savedAt: at, server: s.working, base: s.working });
    store(s.scope, [], []);
  },

  setSaving(saving) {
    set({ saving });
  },

  discard() {
    const s = get();
    set({ undo: [], redo: [], settled: [], base: s.server, working: s.server });
    store(s.scope, [], []);
  },
}));

/** Unsaved changes exist. */
export function useDirty(): boolean {
  return usePlanEditStore((s) => s.undo.length > 0 || s.settled.length > 0);
}
