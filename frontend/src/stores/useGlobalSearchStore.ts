/**
 * Zustand store for the global semantic search modal (Cmd+K).
 *
 * Tiny — just open/close state plus the last query so reopening the
 * modal restores the previous results without a re-fetch.
 */

import { create } from 'zustand';

interface GlobalSearchState {
  open: boolean;
  query: string;
  selectedTypes: string[];

  openModal: (initialQuery?: string) => void;
  closeModal: () => void;
  toggleModal: () => void;
  setQuery: (q: string) => void;
  setSelectedTypes: (types: string[]) => void;
  toggleType: (type: string) => void;
  clearTypes: () => void;
}

export const useGlobalSearchStore = create<GlobalSearchState>((set) => ({
  open: false,
  query: '',
  selectedTypes: [],

  openModal: (initialQuery) =>
    set((s) => ({ open: true, query: initialQuery ?? s.query })),
  closeModal: () => set({ open: false }),
  toggleModal: () => set((s) => ({ open: !s.open })),
  setQuery: (q) => set({ query: q }),
  setSelectedTypes: (types) => set({ selectedTypes: types }),
  toggleType: (type) =>
    set((s) => ({
      selectedTypes: s.selectedTypes.includes(type)
        ? s.selectedTypes.filter((t) => t !== type)
        : [...s.selectedTypes, type],
    })),
  clearTypes: () => set({ selectedTypes: [] }),
}));
