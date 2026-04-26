/**
 * useBIMMeasurementsStore — projected view-state of the MeasureManager's
 * measurement list, in a form the React UI can render.
 *
 * The actual THREE.js objects (lines, labels) live inside the
 * `MeasureManager` instance attached to the BIMViewer scene; their lifetime
 * is tied to the viewer mount.  This store is a thin mirror so the Tools
 * panel can render a list, persist user-supplied labels and visibility
 * toggles, and trigger removals/clears via the bridge handle on
 * ``window.__oeBim`` exposed by BIMViewer.
 *
 * The store does NOT persist to localStorage: measurements are tied to a
 * specific scene state (camera, geometry transforms) that we don't want
 * to surface across sessions or across model swaps.  Reset on model
 * change is the caller's job.
 */
import { create } from 'zustand';

export interface StoredMeasurement {
  /** Stable id mirrored from the underlying MeasureManager.Measurement.id. */
  id: string;
  /** Distance in metres (rounded to 2 dp at display time, raw here). */
  distance: number;
  /** User-supplied label (defaults to "Measurement N"). */
  label: string;
  /** Whether the user has hidden the on-canvas line + label. */
  visible: boolean;
  createdAt: number;
}

interface BIMMeasurementsState {
  measurements: StoredMeasurement[];
  /** Append a new measurement (typically from the MeasureManager onMeasurementAdded
   *  callback). */
  add: (m: { id: string; distance: number }) => void;
  /** Drop a single measurement. */
  remove: (id: string) => void;
  /** Reset everything — used when the user clicks "Clear all" or the
   *  active model changes. */
  clear: () => void;
  /** Update the user-visible label. */
  rename: (id: string, label: string) => void;
  /** Toggle the on-canvas visibility flag. */
  setVisible: (id: string, visible: boolean) => void;
}

export const useBIMMeasurementsStore = create<BIMMeasurementsState>((set) => ({
  measurements: [],

  add: ({ id, distance }) =>
    set((state) => {
      // Defensive: skip duplicates (shouldn't happen, but the random-id
      // generator could collide on a long session).
      if (state.measurements.some((m) => m.id === id)) return state;
      const ordinal = state.measurements.length + 1;
      return {
        measurements: [
          ...state.measurements,
          {
            id,
            distance,
            label: `Measurement ${ordinal}`,
            visible: true,
            createdAt: Date.now(),
          },
        ],
      };
    }),

  remove: (id) =>
    set((state) => ({
      measurements: state.measurements.filter((m) => m.id !== id),
    })),

  clear: () => set({ measurements: [] }),

  rename: (id, label) =>
    set((state) => ({
      measurements: state.measurements.map((m) =>
        m.id === id ? { ...m, label: label.trim().slice(0, 80) || m.label } : m,
      ),
    })),

  setVisible: (id, visible) =>
    set((state) => ({
      measurements: state.measurements.map((m) =>
        m.id === id ? { ...m, visible } : m,
      ),
    })),
}));
