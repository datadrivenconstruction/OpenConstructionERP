// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Trainer UI state that is not server state: the task dock (open, collapsed
// to the rail, width, mobile sheet expanded), the task it shows, the task
// selected on the course map, unsent draft answers, and the unlocks already
// celebrated in this session.
//
// Only the dock width survives a reload (localStorage, guarded: storage can be
// missing or throw). Drafts stay in memory on purpose: answers that count are
// saved on the server through the answers PUT, and a draft from an earlier
// visit could disagree with what the server holds. Hints are not here either:
// the server records which hints were revealed (decision 15).

import { create } from 'zustand';

export const DOCK_WIDTH_STORAGE_KEY = 'oe_trainer_dock_width_v1';
export const DOCK_WIDTH_DEFAULT = 380;
export const DOCK_WIDTH_MIN = 320;
export const DOCK_WIDTH_MAX = 560;

/** Clamp to [min, max] and round; anything not a finite number gives the default. */
export function clampDockWidth(width: unknown): number {
  if (typeof width !== 'number' || !Number.isFinite(width)) return DOCK_WIDTH_DEFAULT;
  return Math.round(Math.min(DOCK_WIDTH_MAX, Math.max(DOCK_WIDTH_MIN, width)));
}

function readDockWidth(): number {
  try {
    const raw = localStorage.getItem(DOCK_WIDTH_STORAGE_KEY);
    return raw === null ? DOCK_WIDTH_DEFAULT : clampDockWidth(Number(raw));
  } catch {
    return DOCK_WIDTH_DEFAULT;
  }
}

function writeDockWidth(width: number): void {
  try {
    if (width === DOCK_WIDTH_DEFAULT) localStorage.removeItem(DOCK_WIDTH_STORAGE_KEY);
    else localStorage.setItem(DOCK_WIDTH_STORAGE_KEY, String(width));
  } catch {
    /* storage unavailable: the width lasts for this visit only */
  }
}

/** Draft answers of one task, by answer name (a field key or a choice check id). */
export type TaskDrafts = Record<string, string>;

interface TrainerUiState {
  /** The task the dock shows; null hides the dock. */
  dockTaskId: string | null;
  /** The dock is open (push or sheet); false shows it as the rail. */
  dockOpen: boolean;
  dockWidth: number;
  /** Mobile sheet: expanded (85vh) or the 64px peek. */
  sheetExpanded: boolean;
  /** The station selected on the course map, which drives the detail panel. */
  selectedTaskId: string | null;
  drafts: Record<string, TaskDrafts>;
  /** Unlocks shown this session, so a failed `seen` POST does not re-show them. */
  celebrated: string[];

  /** Show `taskId` in the dock and open it. Also selects it on the map. */
  openTask: (taskId: string) => void;
  /** Collapse the dock to the rail; the task stays. */
  collapseDock: () => void;
  /** Expand the rail back to the dock. No-op without a task. */
  expandDock: () => void;
  /** Remove the dock entirely (no current task). */
  closeDock: () => void;
  setDockWidth: (width: number) => void;
  resetDockWidth: () => void;
  setSheetExpanded: (expanded: boolean) => void;
  selectTask: (taskId: string | null) => void;
  setDraft: (taskId: string, name: string, value: string) => void;
  clearDraft: (taskId: string, name: string) => void;
  clearDrafts: (taskId: string) => void;
  markCelebrated: (lockId: string) => void;
  /** Forget everything but the stored width (sign-out, user switch). */
  reset: () => void;
}

const SESSION_DEFAULTS = {
  dockTaskId: null,
  dockOpen: false,
  sheetExpanded: false,
  selectedTaskId: null,
  drafts: {},
  celebrated: [],
} satisfies Partial<TrainerUiState>;

export const useTrainerUiStore = create<TrainerUiState>((set, get) => ({
  ...SESSION_DEFAULTS,
  dockWidth: readDockWidth(),

  openTask: (taskId) => set({ dockTaskId: taskId, dockOpen: true, selectedTaskId: taskId }),
  collapseDock: () => set({ dockOpen: false, sheetExpanded: false }),
  expandDock: () => {
    if (get().dockTaskId !== null) set({ dockOpen: true });
  },
  closeDock: () => set({ dockTaskId: null, dockOpen: false, sheetExpanded: false }),
  setDockWidth: (width) => {
    const next = clampDockWidth(width);
    writeDockWidth(next);
    set({ dockWidth: next });
  },
  resetDockWidth: () => {
    writeDockWidth(DOCK_WIDTH_DEFAULT);
    set({ dockWidth: DOCK_WIDTH_DEFAULT });
  },
  setSheetExpanded: (expanded) => set({ sheetExpanded: expanded }),
  selectTask: (taskId) => set({ selectedTaskId: taskId }),
  setDraft: (taskId, name, value) =>
    set((s) => ({ drafts: { ...s.drafts, [taskId]: { ...s.drafts[taskId], [name]: value } } })),
  clearDraft: (taskId, name) =>
    set((s) => {
      const task = s.drafts[taskId];
      if (!task || !(name in task)) return s;
      const { [name]: _dropped, ...rest } = task;
      return { drafts: { ...s.drafts, [taskId]: rest } };
    }),
  clearDrafts: (taskId) =>
    set((s) => {
      if (!(taskId in s.drafts)) return s;
      const { [taskId]: _dropped, ...rest } = s.drafts;
      return { drafts: rest };
    }),
  markCelebrated: (lockId) =>
    set((s) => (s.celebrated.includes(lockId) ? s : { celebrated: [...s.celebrated, lockId] })),
  reset: () => set({ ...SESSION_DEFAULTS, drafts: {}, celebrated: [] }),
}));
