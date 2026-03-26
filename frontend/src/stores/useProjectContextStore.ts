/**
 * Global project context store.
 *
 * Remembers the active project and BOQ across all pages so modules
 * (Schedule, Cost Model, Tendering, etc.) know what they're working on.
 *
 * Persists to localStorage so context survives page reloads.
 */

import { create } from 'zustand';

const STORAGE_KEY = 'oe_active_project';
const PINNED_KEY = 'oe_pinned_projects';

interface ProjectContext {
  id: string;
  name: string;
  boqId: string | null;
}

function readContext(): ProjectContext | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed.id === 'string') return parsed;
    return null;
  } catch {
    return null;
  }
}

function readPinned(): string[] {
  try {
    const raw = localStorage.getItem(PINNED_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function persist(ctx: ProjectContext | null) {
  try {
    if (ctx) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(ctx));
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  } catch { /* ignore */ }
}

function persistPinned(ids: string[]) {
  try {
    localStorage.setItem(PINNED_KEY, JSON.stringify(ids));
  } catch { /* ignore */ }
}

interface ProjectContextState {
  activeProjectId: string | null;
  activeProjectName: string;
  activeBOQId: string | null;
  pinnedProjectIds: string[];

  setActiveProject: (id: string, name: string) => void;
  setActiveBOQ: (boqId: string | null) => void;
  clearProject: () => void;

  togglePinned: (projectId: string) => void;
  isPinned: (projectId: string) => boolean;
}

const initial = readContext();
const initialPinned = readPinned();

export const useProjectContextStore = create<ProjectContextState>((set, get) => ({
  activeProjectId: initial?.id ?? null,
  activeProjectName: initial?.name ?? '',
  activeBOQId: initial?.boqId ?? null,
  pinnedProjectIds: initialPinned,

  setActiveProject: (id: string, name: string) => {
    const ctx: ProjectContext = { id, name, boqId: get().activeBOQId };
    persist(ctx);
    set({ activeProjectId: id, activeProjectName: name });
  },

  setActiveBOQ: (boqId: string | null) => {
    const state = get();
    if (state.activeProjectId) {
      persist({ id: state.activeProjectId, name: state.activeProjectName, boqId });
    }
    set({ activeBOQId: boqId });
  },

  clearProject: () => {
    persist(null);
    set({ activeProjectId: null, activeProjectName: '', activeBOQId: null });
  },

  togglePinned: (projectId: string) => {
    const current = get().pinnedProjectIds;
    const next = current.includes(projectId)
      ? current.filter((id) => id !== projectId)
      : [...current, projectId];
    persistPinned(next);
    set({ pinnedProjectIds: next });
  },

  isPinned: (projectId: string) => {
    return get().pinnedProjectIds.includes(projectId);
  },
}));
