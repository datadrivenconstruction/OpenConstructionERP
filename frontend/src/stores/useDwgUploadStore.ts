/**
 * Global DWG upload store — survives React component unmounts.
 *
 * Mirrors `useBIMUploadStore`: actions run outside React so navigating
 * away from /dwg-takeoff does not cancel an in-flight upload. Jobs carry
 * progress + stage + error state for a global upload dock.
 *
 * Each uploaded drawing yields one job; abort is supported via per-job
 * AbortController. On success, the job ends in `ready` with `drawingId`
 * populated so the caller can navigate or refresh the drawing list.
 */

import { create } from 'zustand';
import { uploadDrawing } from '@/features/dwg-takeoff/api';
import type { DwgDrawing } from '@/features/dwg-takeoff/api';

export type DwgUploadStatus = 'uploading' | 'converting' | 'ready' | 'error';

export interface DwgUploadJob {
  id: string;
  fileName: string;
  fileSize: number;
  projectId: string;
  modelName: string;
  discipline: string;
  status: DwgUploadStatus;
  progress: number;
  stage: string;
  drawingId: string | null;
  errorMessage: string | null;
  startedAt: number;
  completedAt: number | null;
}

export interface StartDwgUploadParams {
  file: File;
  projectId: string;
  modelName: string;
  discipline: string;
}

interface DwgUploadState {
  jobs: Map<string, DwgUploadJob>;
  startUpload: (params: StartDwgUploadParams) => string;
  cancelUpload: (jobId: string) => void;
  dismissJob: (jobId: string) => void;
  clearCompleted: () => void;
  hasActiveUploads: () => boolean;
  activeJobs: () => DwgUploadJob[];
  completedJobs: () => DwgUploadJob[];
}

const abortControllers = new Map<string, AbortController>();
const stageTimers = new Map<string, ReturnType<typeof setInterval>>();

export const useDwgUploadStore = create<DwgUploadState>((set, get) => {
  function patchJob(jobId: string, patch: Partial<DwgUploadJob>) {
    set((state) => {
      const jobs = new Map(state.jobs);
      const existing = jobs.get(jobId);
      if (!existing) return state;
      jobs.set(jobId, { ...existing, ...patch });
      return { jobs };
    });
  }

  function startStageTimer(jobId: string) {
    const phases = [
      { status: 'uploading' as const, stage: 'dwg_upload.stage_uploading', target: 30, step: 2.0, interval: 200 },
      { status: 'converting' as const, stage: 'dwg_upload.stage_converting', target: 70, step: 0.9, interval: 300 },
      { status: 'converting' as const, stage: 'dwg_upload.stage_extracting', target: 90, step: 0.7, interval: 250 },
      { status: 'converting' as const, stage: 'dwg_upload.stage_finalizing', target: 95, step: 1.5, interval: 200 },
    ];

    let phaseIdx = 0;
    let currentPct = 5;

    const tick = () => {
      // Phases exhausted → self-terminate. Prior code only returned
      // early, leaving setInterval firing every 300ms forever — the
      // zombie timer Artem reported as "конвертация постоянно".
      if (phaseIdx >= phases.length) {
        clearStageTimer(jobId);
        return;
      }
      const phase = phases[phaseIdx]!;
      const remaining = phase.target - currentPct;
      const increment = Math.max(0.2, Math.min(phase.step, remaining * 0.15));
      currentPct = Math.min(phase.target, currentPct + increment);
      patchJob(jobId, { status: phase.status, stage: phase.stage, progress: Math.round(currentPct) });
      if (currentPct >= phase.target - 0.2) phaseIdx += 1;
    };

    tick();
    const timer = setInterval(tick, 300);
    stageTimers.set(jobId, timer);
  }

  function clearStageTimer(jobId: string) {
    const timer = stageTimers.get(jobId);
    if (timer) {
      clearInterval(timer);
      stageTimers.delete(jobId);
    }
  }

  async function executeUpload(jobId: string, params: StartDwgUploadParams) {
    startStageTimer(jobId);
    try {
      const res: DwgDrawing = await uploadDrawing(
        params.projectId,
        params.file,
        params.modelName,
        params.discipline,
      );
      clearStageTimer(jobId);
      patchJob(jobId, {
        status: 'ready',
        progress: 100,
        stage: 'dwg_upload.stage_done',
        drawingId: res.id,
        completedAt: Date.now(),
      });
    } catch (err) {
      clearStageTimer(jobId);
      if (err instanceof DOMException && err.name === 'AbortError') return;
      const msg = err instanceof Error ? err.message : String(err);
      patchJob(jobId, {
        status: 'error',
        progress: 0,
        stage: 'dwg_upload.stage_failed',
        errorMessage: msg,
        completedAt: Date.now(),
      });
    } finally {
      abortControllers.delete(jobId);
    }
  }

  return {
    jobs: new Map(),

    startUpload: (params) => {
      const jobId = crypto.randomUUID();
      const job: DwgUploadJob = {
        id: jobId,
        fileName: params.file.name,
        fileSize: params.file.size,
        projectId: params.projectId,
        modelName: params.modelName,
        discipline: params.discipline,
        status: 'uploading',
        progress: 5,
        stage: 'dwg_upload.stage_sending',
        drawingId: null,
        errorMessage: null,
        startedAt: Date.now(),
        completedAt: null,
      };

      abortControllers.set(jobId, new AbortController());

      set((state) => {
        const jobs = new Map(state.jobs);
        jobs.set(jobId, job);
        return { jobs };
      });

      void executeUpload(jobId, params);
      return jobId;
    },

    cancelUpload: (jobId) => {
      abortControllers.get(jobId)?.abort();
      abortControllers.delete(jobId);
      clearStageTimer(jobId);
      set((state) => {
        const jobs = new Map(state.jobs);
        jobs.delete(jobId);
        return { jobs };
      });
    },

    dismissJob: (jobId) => {
      abortControllers.delete(jobId);
      clearStageTimer(jobId);
      set((state) => {
        const jobs = new Map(state.jobs);
        jobs.delete(jobId);
        return { jobs };
      });
    },

    clearCompleted: () => {
      set((state) => {
        const jobs = new Map(state.jobs);
        for (const [id, job] of jobs) {
          if (job.status === 'ready' || job.status === 'error') jobs.delete(id);
        }
        return { jobs };
      });
    },

    hasActiveUploads: () => {
      for (const job of get().jobs.values()) {
        if (job.status === 'uploading' || job.status === 'converting') return true;
      }
      return false;
    },

    activeJobs: () => {
      const out: DwgUploadJob[] = [];
      for (const job of get().jobs.values()) {
        if (job.status === 'uploading' || job.status === 'converting') out.push(job);
      }
      return out;
    },

    completedJobs: () => {
      const out: DwgUploadJob[] = [];
      for (const job of get().jobs.values()) {
        if (job.status === 'ready' || job.status === 'error') out.push(job);
      }
      return out;
    },
  };
});


// ── Zombie-job janitor ─────────────────────────────────────────────────────
//
// Same pattern as useBIMUploadStore. A DWG upload that dies mid-flight
// (network drop, browser crash, Vite HMR revival) can leave a job pinned
// in `uploading` / `converting` state forever — the indicator spins with
// no way to clear it. Every 2 minutes, flip anything older than 45 min
// to `error` so the UI drops it. Reported as "конвертация проходит
// постоянно" alongside the BIM-side zombie.

if (typeof window !== 'undefined') {
  const MAX_ACTIVE_MS = 45 * 60 * 1000;
  const PATROL_MS = 2 * 60 * 1000;

  const sweep = () => {
    const state = useDwgUploadStore.getState();
    const now = Date.now();
    let dirty = false;
    const nextJobs = new Map(state.jobs);
    for (const [id, job] of nextJobs) {
      const active = job.status === 'uploading' || job.status === 'converting';
      if (!active) continue;
      if (now - job.startedAt < MAX_ACTIVE_MS) continue;
      nextJobs.set(id, {
        ...job,
        status: 'error',
        progress: 0,
        stage: 'dwg_upload.stage_stalled',
        errorMessage:
          job.errorMessage ??
          'Upload abandoned after 45 min — reload to retry if the file is still needed.',
        completedAt: now,
      });
      dirty = true;
    }
    if (dirty) {
      useDwgUploadStore.setState({ jobs: nextJobs });
    }
  };

  sweep();
  setInterval(sweep, PATROL_MS);
}
