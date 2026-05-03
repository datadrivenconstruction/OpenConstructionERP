/**
 * useBIMViewerStore — per-viewer UI state that needs to survive re-renders.
 *
 * Currently tracks per-category opacity (RFC 19 §4.2) and whether the Tools
 * tab is active on the right panel. The store is intentionally tiny; model
 * data itself lives in React Query + ElementManager.
 */
import { create } from 'zustand';

export type BIMRightPanelTab =
  | 'properties'
  | 'layers'
  | 'tools'
  | 'groups'
  | 'match';

const ASSET_CARD_KEY = 'oe_bim_asset_card_enabled';

function readAssetCardEnabled(): boolean {
  try {
    const raw = localStorage.getItem(ASSET_CARD_KEY);
    if (raw === null) return true;
    return raw === '1';
  } catch {
    return true;
  }
}

function writeAssetCardEnabled(enabled: boolean): void {
  try {
    localStorage.setItem(ASSET_CARD_KEY, enabled ? '1' : '0');
  } catch {
    /* ignore quota errors */
  }
}

interface BIMViewerState {
  /** Per-category opacity (0..1). 1 means fully opaque (default). */
  categoryOpacity: Record<string, number>;
  /** Categories the user explicitly hid from the Layers tab. */
  hiddenCategories: Record<string, boolean>;
  /** Active right-panel tab. */
  rightPanelTab: BIMRightPanelTab;
  /** Whether the right-panel (with the 4 tabs) is currently open. */
  rightPanelOpen: boolean;
  /** Whether the measure tool is enabled. */
  measureActive: boolean;
  /** Whether the floating "Model / Filtered / Selection summary" panel
   *  is visible. Toggled from the top toolbar or the panel's own X. */
  summaryPanelOpen: boolean;
  /** Whether the bounding-box dimension card is shown when an element
   *  is selected. Toggled from the top toolbar. */
  dimensionsVisible: boolean;
  /** Whether the floating Asset-info card is shown when an element is
   *  selected. Persisted to localStorage so the preference survives
   *  page reloads. */
  assetCardEnabled: boolean;

  setCategoryOpacity: (category: string, opacity: number) => void;
  setCategoryHidden: (category: string, hidden: boolean) => void;
  resetCategoryOverrides: () => void;
  setRightPanelTab: (tab: BIMRightPanelTab) => void;
  setRightPanelOpen: (open: boolean) => void;
  setMeasureActive: (active: boolean) => void;
  setSummaryPanelOpen: (open: boolean) => void;
  setDimensionsVisible: (visible: boolean) => void;
  setAssetCardEnabled: (enabled: boolean) => void;
}

export const useBIMViewerStore = create<BIMViewerState>((set) => ({
  categoryOpacity: {},
  hiddenCategories: {},
  rightPanelTab: 'properties',
  rightPanelOpen: false,
  measureActive: false,
  summaryPanelOpen: true,
  dimensionsVisible: true,
  assetCardEnabled: readAssetCardEnabled(),

  setCategoryOpacity: (category, opacity) =>
    set((state) => ({
      categoryOpacity: {
        ...state.categoryOpacity,
        [category]: Math.max(0, Math.min(1, opacity)),
      },
    })),

  setCategoryHidden: (category, hidden) =>
    set((state) => ({
      hiddenCategories: { ...state.hiddenCategories, [category]: hidden },
    })),

  resetCategoryOverrides: () => set({ categoryOpacity: {}, hiddenCategories: {} }),

  setRightPanelTab: (tab) => set({ rightPanelTab: tab, rightPanelOpen: true }),
  setRightPanelOpen: (open) => set({ rightPanelOpen: open }),
  setMeasureActive: (active) => set({ measureActive: active }),
  setSummaryPanelOpen: (open) => set({ summaryPanelOpen: open }),
  setDimensionsVisible: (visible) => set({ dimensionsVisible: visible }),
  setAssetCardEnabled: (enabled) => {
    writeAssetCardEnabled(enabled);
    set({ assetCardEnabled: enabled });
  },
}));
