/**
 * Global upload/processing queue store.
 *
 * Persists across page navigation — upload or CAD conversion continues
 * in background even when user navigates to other modules.
 */

import { create } from 'zustand';

export type TaskStatus = 'queued' | 'processing' | 'completed' | 'error';
export type TaskType = 'cad_convert' | 'file_upload' | 'import';

export interface QueueTask {
  id: string;
  type: TaskType;
  filename: string;
  status: TaskStatus;
  progress: number;       // 0-100
  message?: string;
  error?: string;
  resultSessionId?: string;  // for CAD conversions
  resultUrl?: string;        // for navigating to result
  startedAt: number;
  completedAt?: number;
}

interface UploadQueueState {
  tasks: QueueTask[];
  addTask: (task: Omit<QueueTask, 'startedAt'>) => void;
  updateTask: (id: string, updates: Partial<QueueTask>) => void;
  removeTask: (id: string) => void;
  clearCompleted: () => void;
  activeCount: () => number;
}

export const useUploadQueueStore = create<UploadQueueState>((set, get) => ({
  tasks: [],

  addTask: (task) =>
    set((state) => ({
      tasks: [{ ...task, startedAt: Date.now() }, ...state.tasks],
    })),

  updateTask: (id, updates) =>
    set((state) => ({
      tasks: state.tasks.map((t) => (t.id === id ? { ...t, ...updates } : t)),
    })),

  removeTask: (id) =>
    set((state) => ({
      tasks: state.tasks.filter((t) => t.id !== id),
    })),

  clearCompleted: () =>
    set((state) => ({
      tasks: state.tasks.filter((t) => t.status !== 'completed' && t.status !== 'error'),
    })),

  activeCount: () => get().tasks.filter((t) => t.status === 'processing' || t.status === 'queued').length,
}));
