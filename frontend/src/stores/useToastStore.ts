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

function scheduleDismiss(
  toastId: string,
  duration: number,
  set: (fn: (s: ToastStore) => Partial<ToastStore>) => void,
) {
  if (dismissTimers.has(toastId)) {
    clearTimeout(dismissTimers.get(toastId)!);
    dismissTimers.delete(toastId);
  }
  const timer = setTimeout(() => {
    set((state) => ({
      toasts: state.toasts.filter((t) => t.id !== toastId),
    }));
    dismissTimers.delete(toastId);
  }, duration);
  dismissTimers.set(toastId, timer);
}

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

    // Dedup: check current toasts for a match with the same type+title.
    // We read from the *previous* state inside the set callback so the
    // store never references itself during initialisation (avoids TS7022).
    let mergedInto: string | null = null;
    set((state) => {
      const existing = state.toasts.find(
        (t) => t.type === toast.type && t.title === toast.title,
      );
      if (existing) {
        mergedInto = existing.id;
        return {
          toasts: state.toasts.map((t) =>
            t.id === existing.id ? { ...t, count: (t.count ?? 1) + 1 } : t,
          ),
          history: [historyEntry, ...state.history].slice(0, MAX_HISTORY),
        };
      }
      return {
        toasts: [...state.toasts, { ...toast, id, count: 1 }],
        history: [historyEntry, ...state.history].slice(0, MAX_HISTORY),
      };
    });

    const effectiveId = mergedInto ?? id;
    scheduleDismiss(effectiveId, duration, set);
    return effectiveId;
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
