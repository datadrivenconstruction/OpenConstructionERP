// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Screen state of the phone clock panel​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠: who is clocking, and what the last tap did. */

import { create } from 'zustand';
import type { ClockKind } from './clockApi';

export interface ClockResult {
  kind: ClockKind;
  /** True when the server (or, offline, nobody yet) judged the tap inside a fence. */
  inside: boolean | null;
  distanceM: number | null;
  geofenceName: string | null;
  /** Saved on this device, not yet on the server. */
  queued: boolean;
  /** The device gave no position (denied, timed out, unsupported). */
  positionMissing: boolean;
  at: string;
  /** Crew taps only: members that were not clocked, with the server's reason code. */
  skipped?: { resource_id: string; code: string }[];
}

interface ClockState {
  resourceId: string;
  /** What this device last did per worker; wins over the server until a refetch disagrees. */
  lastKind: Record<string, ClockKind>;
  result: ClockResult | null;
  setResourceId: (id: string) => void;
  setLastKind: (resourceId: string, kind: ClockKind) => void;
  setResult: (r: ClockResult | null) => void;
  reset: () => void;
}

export const useClockStore = create<ClockState>((set) => ({
  resourceId: '',
  lastKind: {},
  result: null,
  setResourceId: (resourceId) => set({ resourceId, result: null }),
  setLastKind: (resourceId, kind) => set((s) => ({ lastKind: { ...s.lastKind, [resourceId]: kind } })),
  setResult: (result) => set({ result }),
  reset: () => set({ resourceId: '', lastKind: {}, result: null }),
}));
