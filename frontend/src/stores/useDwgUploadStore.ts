// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
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
import { stageFromServer, type ConversionStageId } from '@/shared/lib/conversionStages';
import { uuid } from '@/shared/lib/browser';
import { fetchDrawing, uploadDrawing } from '@/features/dwg-takeoff/api';
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
  /** Stable failure code (``metadata.error_code``) the UI translates. */
  errorCode?: string | null;
  /** Stage the server reports while converting, its start (ms) and time limit (s). */
  stageId?: ConversionStageId;
  serverStartedAt?: number | null;
  limitS?: number | null;
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

function parseIso(value: unknown): number | null {
  const ms = typeof value === 'string' ? Date.parse(value) : NaN;
  return Number.isFinite(ms) ? ms : null;
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

  function clearStageTimer(jobId: string) {
    const timer = stageTimers.get(jobId);
    if (timer) {
      clearInterval(timer);
      stageTimers.delete(jobId);
    }
  }

  /** Poll the backend for the drawing's conversion status until it
   *  flips out of `processing` / `uploaded`. The POST returns almost
   *  immediately for DWG files because the backend hands the
   *  conversion off to a fire-and-forget asyncio task — without this
   *  poll the store would mark the job `ready` while the DDC pipeline
   *  was still running for several minutes, which is exactly the
   *  "false loaded" bug that was reported: the project shows as loaded,
   *  nothing is rendered, and the real load only happens minutes
   *  later. Max 20 min — beyond that the zombie
   *  janitor below sweeps the job.
   *
   *  Polling cadence uses gentle exponential back-off: 3.5 s for the
   *  first 30 s (catches fast DXF parses snappily), then ramps to a
   *  ceiling of 15 s for long DDC conversions so we don't hammer the
   *  backend with hundreds of GETs over a 5-minute parse. */
  async function pollUntilReady(jobId: string, drawingId: string): Promise<void> {
    const FAST_POLL_MS = 3500;
    const MAX_POLL_MS = 15_000;
    const FAST_WINDOW_MS = 30_000;
    // The server stops a conversion at its own limit (30 minutes by default); wait a little longer than that.
    const TIMEOUT_MS = 35 * 60 * 1000;
    const startedAt = Date.now();

    while (Date.now() - startedAt < TIMEOUT_MS) {
      // Bail out if the user cancelled or the job was dismissed.
      const current = useDwgUploadStore.getState().jobs.get(jobId);
      if (!current) return;
      if (current.status === 'error') return;

      try {
        const drawing = await fetchDrawing(drawingId);
        const backendStatus = drawing.status ?? 'processing';
        if (backendStatus === 'ready' || backendStatus === 'empty') {
          patchJob(jobId, {
            status: 'ready',
            progress: 100,
            stage:
              backendStatus === 'empty'
                ? 'dwg_upload.stage_empty'
                : 'dwg_upload.stage_done',
            drawingId,
            completedAt: Date.now(),
          });
          return;
        }
        if (backendStatus === 'error') {
          patchJob(jobId, {
            status: 'error',
            progress: 0,
            stage: 'dwg_upload.stage_failed',
            errorMessage: drawing.error_message || null,
            errorCode: drawing.metadata?.error_code ?? 'convert_failed',
            completedAt: Date.now(),
          });
          return;
        }
        // Still processing — keep the simulated stage timer running so
        // the % keeps climbing toward 95, and refresh `stage` to make
        // it clear the backend is actively working (not stuck).
        patchJob(jobId, {
          drawingId,
          status: 'converting',
          stage: 'dwg_upload.stage_converting',
          stageId: stageFromServer(drawing.metadata?.conversion_stage as string | undefined),
          limitS: (drawing.metadata?.conversion_timeout_s as number | undefined) ?? null,
          serverStartedAt: parseIso(drawing.metadata?.conversion_started_at),
        });
      } catch {
        // Transient network blip — keep polling. The 20-min ceiling
        // means we still bail eventually if the backend is gone.
      }
      // Exponential back-off: tight cadence for the first 30s so a
      // fast DXF parse feels instant, then ramp linearly to MAX_POLL_MS
      // for long DDC conversions to keep server load proportional.
      const elapsed = Date.now() - startedAt;
      const wait =
        elapsed < FAST_WINDOW_MS
          ? FAST_POLL_MS
          : Math.min(
              MAX_POLL_MS,
              FAST_POLL_MS + Math.round((elapsed - FAST_WINDOW_MS) / 4),
            );
      await new Promise((r) => setTimeout(r, wait));
    }

    // Hit the 20-min ceiling without status flipping — surface as a
    // soft error so the user can decide whether to retry rather than
    // staring at a forever-spinner.
    patchJob(jobId, {
      status: 'error',
      progress: 0,
      stage: 'dwg_upload.stage_stalled',
      errorMessage: null,
      errorCode: 'ui_stalled',
      completedAt: Date.now(),
    });
  }

  async function executeUpload(jobId: string, params: StartDwgUploadParams) {
    try {
      const res: DwgDrawing = await uploadDrawing(
        params.projectId,
        params.file,
        params.modelName,
        params.discipline,
        (percent) => patchJob(jobId, { progress: percent }),
      );
      // POST returned with the drawing row. For .dwg the backend
      // dispatches the actual conversion in a background task and
      // immediately replies with `status="processing"` — so we do
      // NOT mark the job ready here. Instead we transition into the
      // `converting` stage and poll the backend until status flips.
      const backendStatus = res.status ?? 'processing';
      if (backendStatus === 'ready' || backendStatus === 'empty') {
        // Fast-path: DXF parsing already finished inline.
        clearStageTimer(jobId);
        patchJob(jobId, {
          status: 'ready',
          progress: 100,
          stage:
            backendStatus === 'empty'
              ? 'dwg_upload.stage_empty'
              : 'dwg_upload.stage_done',
          drawingId: res.id,
          completedAt: Date.now(),
        });
        return;
      }
      // Long-path (.dwg): swap stage to converting, expose drawingId
      // now so the takeoff page can render the honest progress card
      // bound to this specific drawing, then poll.
      patchJob(jobId, {
        drawingId: res.id,
        status: 'converting',
        stage: 'dwg_upload.stage_converting',
      });
      await pollUntilReady(jobId, res.id);
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
      clearStageTimer(jobId);
      abortControllers.delete(jobId);
    }
  }

  return {
    jobs: new Map(),

    startUpload: (params) => {
      const jobId = uuid();
      const job: DwgUploadJob = {
        id: jobId,
        fileName: params.file.name,
        fileSize: params.file.size,
        projectId: params.projectId,
        modelName: params.modelName,
        discipline: params.discipline,
        status: 'uploading',
        progress: 0,
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
        errorMessage: job.errorMessage,
        errorCode: 'ui_stalled',
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
