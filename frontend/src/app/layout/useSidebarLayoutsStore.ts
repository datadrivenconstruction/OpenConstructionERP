// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The signed-in user's named sidebar layouts. They live on the server
 * (`/v1/users/me/sidebar-layouts/`), like the hidden-rows list, so a layout
 * follows the user to another browser. Every change is checked here first
 * and again by the server; a refused or failed write rolls the list back.
 */

import { create } from 'zustand';
import { apiGet, apiPut } from '@/shared/lib/api';
import {
  addLayout,
  overwriteLayout,
  removeLayout,
  renameLayout,
  sanitizeLayouts,
  validateLayoutName,
  type LayoutNameError,
  type SidebarLayout,
  type SidebarLayoutData,
} from './sidebarLayouts';

const ENDPOINT = '/v1/users/me/sidebar-layouts/';

interface LayoutsPayload {
  layouts: SidebarLayout[];
}

export type LayoutResult = { ok: true; id: string } | { ok: false; error: LayoutNameError | 'save_failed' };

interface SidebarLayoutsState {
  layouts: SidebarLayout[];
  loaded: boolean;
  load: () => Promise<void>;
  save: (name: string, data: SidebarLayoutData) => Promise<LayoutResult>;
  rename: (id: string, name: string) => Promise<LayoutResult>;
  update: (id: string, data: SidebarLayoutData) => Promise<LayoutResult>;
  remove: (id: string) => Promise<LayoutResult>;
  /** Forget everything, e.g. on sign-out or account switch. */
  clear: () => void;
}

export const useSidebarLayoutsStore = create<SidebarLayoutsState>((set, get) => {
  async function commit(next: SidebarLayout[], id: string): Promise<LayoutResult> {
    const previous = get().layouts;
    set({ layouts: next });
    try {
      const saved = await apiPut<LayoutsPayload, LayoutsPayload>(ENDPOINT, { layouts: next });
      set({ layouts: sanitizeLayouts(saved.layouts) });
      return { ok: true, id };
    } catch {
      set({ layouts: previous });
      return { ok: false, error: 'save_failed' };
    }
  }

  return {
    layouts: [],
    loaded: false,
    load: async () => {
      try {
        const data = await apiGet<LayoutsPayload>(ENDPOINT);
        set({ layouts: sanitizeLayouts(data.layouts), loaded: true });
      } catch {
        set({ loaded: true });
      }
    },
    save: async (name, data) => {
      const error = validateLayoutName(name, get().layouts);
      if (error) return { ok: false, error };
      const next = addLayout(get().layouts, name, data);
      return commit(next, next[next.length - 1].id);
    },
    rename: async (id, name) => {
      const error = validateLayoutName(name, get().layouts, id);
      if (error) return { ok: false, error };
      return commit(renameLayout(get().layouts, id, name), id);
    },
    update: async (id, data) => commit(overwriteLayout(get().layouts, id, data), id),
    remove: async (id) => commit(removeLayout(get().layouts, id), id),
    clear: () => set({ layouts: [], loaded: false }),
  };
});
