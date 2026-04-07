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
  addToast: (toast: Omit<Toast, 'id'>, options?: { duration?: number }) => string;
  removeToast: (id: string) => void;
  clearHistory: () => void;
  markAllRead: () => void;
}

let nextId = 0;

export const useToastStore = create<ToastStore>((set) => ({
  toasts: [],
  history: [],

  addToast: (toast, options) => {
    const id = `toast-${Date.now()}-${++nextId}`;
    const historyEntry: HistoryEntry = {
      id,
      type: toast.type,
      title: toast.title,
      message: toast.message,
      timestamp: Date.now(),
      read: false,
    };

    set((state) => ({
      toasts: [...state.toasts, { ...toast, id }],
      history: [historyEntry, ...state.history].slice(0, MAX_HISTORY),
    }));

    const duration = options?.duration ?? 4000;
    setTimeout(() => {
      set((state) => ({
        toasts: state.toasts.filter((t) => t.id !== id),
      }));
    }, duration);

    return id;
  },

  removeToast: (id) =>
    set((state) => ({
      toasts: state.toasts.filter((t) => t.id !== id),
    })),

  clearHistory: () => set({ history: [] }),

  markAllRead: () =>
    set((state) => ({
      history: state.history.map((h) => ({ ...h, read: true })),
    })),
}));
