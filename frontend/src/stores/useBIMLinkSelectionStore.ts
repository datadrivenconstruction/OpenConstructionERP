/**
 * useBIMLinkSelectionStore — cross-highlight signal bus between the BOQ
 * editor and the BIM viewer.
 *
 * The BOQ editor publishes the currently-selected position and its linked
 * CAD element IDs; the BIM viewer subscribes to `highlightedBIMElementIds`
 * and recolours any matching meshes in orange.
 *
 * Conversely, when the user clicks a mesh in the viewer, it calls
 * `setBIMSelection` with the element ID(s). The BOQ editor subscribes to
 * `selectedBIMElementIds` and scrolls to the first linked row.
 *
 * The store is intentionally tiny — it's a signalling layer, not a cache.
 * Nothing is persisted.
 */
import { create } from 'zustand';

interface BIMLinkSelectionState {
  /** The BOQ position currently selected in the editor, if any. Used by
   *  the BIM viewer to highlight every linked BIM element. */
  selectedBOQPositionId: string | null;
  /** Element IDs to highlight in the viewer. Derived from the selected
   *  position's `cad_element_ids`, OR set directly by the BIM viewer on
   *  element click so the BOQ editor knows which row to scroll to. */
  highlightedBIMElementIds: string[];
  /** Element IDs coming FROM the BIM viewer (a user clicked a mesh) —
   *  the BOQ editor consumes this to scroll to the first linked row. */
  selectedBIMElementIds: string[];

  /** BOQ editor → viewer. Pass empty string array to keep the selection
   *  but clear the highlight (e.g. position has no linked elements). */
  setBOQSelection: (positionId: string | null, cadElementIds: string[]) => void;
  /** Viewer → BOQ editor. Called when the user clicks a mesh. */
  setBIMSelection: (elementIds: string[]) => void;
  /** Reset everything. Call on unmount / when switching BOQs or models. */
  clear: () => void;
}

export const useBIMLinkSelectionStore = create<BIMLinkSelectionState>((set) => ({
  selectedBOQPositionId: null,
  highlightedBIMElementIds: [],
  selectedBIMElementIds: [],

  setBOQSelection: (positionId, cadElementIds) =>
    set({
      selectedBOQPositionId: positionId,
      highlightedBIMElementIds: cadElementIds,
    }),

  setBIMSelection: (elementIds) =>
    set({
      selectedBIMElementIds: elementIds,
      highlightedBIMElementIds: elementIds,
    }),

  clear: () =>
    set({
      selectedBOQPositionId: null,
      highlightedBIMElementIds: [],
      selectedBIMElementIds: [],
    }),
}));
