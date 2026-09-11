// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { create } from 'zustand';

export interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface Toast {
  id: string;
  type: 'success' | 'error' | 'warning' | 'info';
  title: string;
  message?: string;
  action?: ToastAction;
  count?: number;
}

export interface HistoryEntry {
  id: string;
  type: Toast['type'];
  title: string;
  message?: string;
  timestamp: number;
  read: boolean;
}

const MAX_HISTORY = 23;

interface ToastStore {
  toasts: Toast[];
  history: HistoryEntry[];
  addToast: (toast: Omit<Toast, 'id' | 'count'>, options?: { duration?: number }) => string;
  removeToast: (id: string) => void;
  clearHistory: () => void;
  markAllRead: () => void;
}

let nextId = 0;
const dismissTimers = new Map<string, ReturnType<typeof setTimeout>>();

export const useToastStore = create<ToastStore>((set) => ({
  toasts: [],
  history: [],

  addToast: (toast, options) => {
    const id = `toast-${Date.now()}-${++nextId}`;
    const duration = options?.duration ?? 4000;
    const historyEntry: HistoryEntry = {
      id,
      type: toast.type,
      title: toast.title,
      message: toast.message,
      timestamp: Date.now(),
      read: false,
    };

    // Group: if a toast with the same type+title is already visible, bump its
    // count instead of adding a duplicate. The auto-dismiss timer resets so
    // the grouped toast stays on screen long enough for the user to notice.
    const existing = useToastStore.getState().toasts.find(
      (t) => t.type === toast.type && t.title === toast.title,
    );

    if (existing) {
      // Clear existing timer and schedule a new one
      if (dismissTimers.has(existing.id)) {
        clearTimeout(dismissTimers.get(existing.id)!);
        dismissTimers.delete(existing.id);
      }
      set((state) => ({
        toasts: state.toasts.map((t) =>
          t.id === existing.id ? { ...t, count: (t.count ?? 1) + 1 } : t,
        ),
        history: [historyEntry, ...state.history].slice(0, MAX_HISTORY),
      }));
      const timer = setTimeout(() => {
        set((state) => ({
          toasts: state.toasts.filter((t) => t.id !== existing.id),
        }));
        dismissTimers.delete(existing.id);
      }, duration);
      dismissTimers.set(existing.id, timer);
      return existing.id;
    }

    set((state) => ({
      toasts: [...state.toasts, { ...toast, id, count: 1 }],
      history: [historyEntry, ...state.history].slice(0, MAX_HISTORY),
    }));

    const timer = setTimeout(() => {
      set((state) => ({
        toasts: state.toasts.filter((t) => t.id !== id),
      }));
      dismissTimers.delete(id);
    }, duration);
    dismissTimers.set(id, timer);

    return id;
  },

  removeToast: (id) => {
    if (dismissTimers.has(id)) {
      clearTimeout(dismissTimers.get(id)!);
      dismissTimers.delete(id);
    }
    set((state) => ({
      toasts: state.toasts.filter((t) => t.id !== id),
    }));
  },

  clearHistory: () => set({ history: [] }),

  markAllRead: () =>
    set((state) => ({
      history: state.history.map((h) => ({ ...h, read: true })),
    })),
}));
