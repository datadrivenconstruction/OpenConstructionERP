// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Which of the round buttons floating in the bottom-right corner this person
 * hides, kept on this device. `true` means hidden; both show by default.
 * The assistant stays reachable with Alt+A and from the command palette.
 */
import { createLocalPref } from './localPref';

export const FLOATING_ITEMS = ['recent', 'assistant'] as const;
export type FloatingItem = (typeof FLOATING_ITEMS)[number];
export type FloatingPrefs = Record<FloatingItem, boolean>;

export const floatingPref = createLocalPref<FloatingPrefs>('oe_floating_buttons_v1', (raw) => {
  const src = (raw && typeof raw === 'object' ? raw : {}) as Partial<Record<FloatingItem, unknown>>;
  return { recent: src.recent === true, assistant: src.assistant === true };
});
