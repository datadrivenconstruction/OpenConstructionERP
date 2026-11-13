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
