// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Smart Views — applied-view session store.
//
// Tracks WHICH SmartView is currently applied (if any) and CACHES the
// evaluator output so a re-mount of the BIMViewer (e.g. tab change,
// route hop within the same session) doesn't lose the visual state.
// Persistence target is sessionStorage so a fresh browser window starts
// clean — Smart Views are deliberate, not sticky-by-default.

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { SmartViewEvaluateResponse } from './types';

interface SmartViewState {
  /** ID of the currently-applied SmartView, or ``null`` when nothing
   *  is applied. */
  appliedViewId: string | null;
  /** The most recent evaluate-response. Cached so re-mounting the
   *  viewer can re-paint the scene without an extra network round-trip. */
  lastEvalResult: SmartViewEvaluateResponse | null;

  /** Mark a view as applied + remember its evaluator output. */
  setApplied: (viewId: string, evalResult: SmartViewEvaluateResponse) => void;
  /** Forget the applied view — viewer will revert to default look. */
  clear: () => void;
}

export const useSmartViewState = create<SmartViewState>()(
  persist(
    (set) => ({
      appliedViewId: null,
      lastEvalResult: null,

      setApplied: (viewId, evalResult) =>
        set({ appliedViewId: viewId, lastEvalResult: evalResult }),

      clear: () => set({ appliedViewId: null, lastEvalResult: null }),
    }),
    {
      name: 'oe-smart-view-state-v1',
      storage: createJSONStorage(() => sessionStorage),
    },
  ),
);
