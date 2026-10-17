// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Which processes surface is open. Global UI state, so a module banner can
 * open the panel and the panel can reopen the first-run wizard.
 */

import { create } from 'zustand';

interface ProcessesUiState {
  panelOpen: boolean;
  wizardOpen: boolean;
  /** Row to expand and scroll to when the panel opens from a module page. */
  focusId: string | null;
  openPanel: (focusId?: string | null) => void;
  closePanel: () => void;
  openWizard: () => void;
  closeWizard: () => void;
  /**
   * Services the wizard (or a retry) asked to start and the header still
   * follows, so it can say when they are ready or which one failed.
   */
  startWatch: string[];
  watchStarts: (ids: string[]) => void;
  settleStart: (id: string) => void;
}

export const useProcessesUi = create<ProcessesUiState>((set) => ({
  panelOpen: false,
  wizardOpen: false,
  focusId: null,
  openPanel: (focusId = null) => set({ panelOpen: true, wizardOpen: false, focusId }),
  closePanel: () => set({ panelOpen: false, focusId: null }),
  openWizard: () => set({ wizardOpen: true, panelOpen: false }),
  closeWizard: () => set({ wizardOpen: false }),
  startWatch: [],
  watchStarts: (ids) => set((s) => ({ startWatch: [...new Set([...s.startWatch, ...ids])] })),
  settleStart: (id) => set((s) => ({ startWatch: s.startWatch.filter((x) => x !== id) })),
}));
