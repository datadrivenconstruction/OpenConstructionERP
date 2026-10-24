// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { create } from 'zustand';
import {
  DEFAULT_MENU_LAYOUT,
  menuLayoutReducer,
  resolveMenuLayout,
  type MenuLayout,
  type MenuLayoutAction,
} from './menuLayout';
import { dismissSuggestion, readUsage, recordVisit, writeUsage, type MenuUsage } from './menuUsage';

const LAYOUT_KEY = 'oe.menu_layout.v1';

function readOverrides(): unknown {
  try {
    const raw = localStorage.getItem(LAYOUT_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function writeOverrides(layout: MenuLayout): void {
  try {
    localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout));
  } catch {
    /* storage unavailable */
  }
}

interface MenuLayoutState {
  /** Company template, once an admin can push one; null today. */
  template: unknown;
  layout: MenuLayout;
  usage: MenuUsage;
  dispatch: (action: MenuLayoutAction) => void;
  setTemplate: (template: unknown) => void;
  recordVisit: (route: string) => void;
  dismiss: (key: string) => void;
}

export const useMenuLayoutStore = create<MenuLayoutState>((set, get) => ({
  template: null,
  layout: resolveMenuLayout(null, readOverrides()),
  usage: readUsage(Date.now()),
  dispatch: (action) => {
    const layout = menuLayoutReducer(get().layout, action);
    if (layout === get().layout) return;
    if (action.type === 'reset') {
      const fresh = { ...resolveMenuLayout(get().template, null), activeMode: layout.activeMode, rail: layout.rail };
      writeOverrides({ ...DEFAULT_MENU_LAYOUT, activeMode: fresh.activeMode, rail: fresh.rail });
      set({ layout: fresh });
      return;
    }
    writeOverrides(layout);
    set({ layout });
  },
  setTemplate: (template) => set({ template, layout: resolveMenuLayout(template, readOverrides()) }),
  recordVisit: (route) => {
    const usage = recordVisit(get().usage, route, Date.now());
    writeUsage(usage);
    set({ usage });
  },
  dismiss: (key) => {
    const usage = dismissSuggestion(get().usage, key, Date.now());
    writeUsage(usage);
    set({ usage });
  },
}));
