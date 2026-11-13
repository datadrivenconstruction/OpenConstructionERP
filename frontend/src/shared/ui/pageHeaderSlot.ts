// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { create } from 'zustand';

/**
 * The element at the end of the mounted `PageHeader` action row. App-shell
 * widgets that belong beside the page actions ("Learn this step") portal into
 * it, so they sit in the same h-8 row instead of reserving a row of their own.
 */
interface PageHeaderSlotState {
  el: HTMLElement | null;
  setEl: (el: HTMLElement | null) => void;
}

export const usePageHeaderSlot = create<PageHeaderSlotState>((set) => ({
  el: null,
  setEl: (el) => set({ el }),
}));

/**
 * How many expanded info cards (`DismissibleInfo`) the page shows. An Explainer
 * the reader never toggled starts collapsed while one is open, so the two long
 * reads are never stacked at the top of a page (founder 13.11).
 */
interface InfoPresenceState {
  open: number;
  add: () => void;
  remove: () => void;
}

export const useInfoCardPresence = create<InfoPresenceState>((set) => ({
  open: 0,
  add: () => set((s) => ({ open: s.open + 1 })),
  remove: () => set((s) => ({ open: Math.max(0, s.open - 1) })),
}));
