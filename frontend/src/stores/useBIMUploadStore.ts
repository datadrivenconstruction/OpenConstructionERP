/**
 * Global BIM upload store — survives React component unmounts.
 *
 * The actual fetch runs as a store action (not inside a React component),
 * so navigating away from /bim does NOT cancel the upload.  The store
 * delegates to the same `uploadCADFile` / `uploadBIMData` functions used
 * by BIMPage — no new network layer.
 *
 * Multiple uploads can run in parallel; each gets a unique job ID.
 */

import { create } from 'zustand';
import {
  uploadCADFile,
  uploadBIMData,
  type BIMCadUploadResponse,
} from '@/features/bim/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type BIMUploadStatus =
  | 'uploading'
  | 'converting'
  | 'ready'
  | 'error'
  | 'converter_required';

export interface BIMUploadJob {
  id: string;
  fileName: string;
  fileSize: number;
  projectId: string;
  modelName: string;
  discipline: string;

  status: BIMUploadStatus;
  /** 0-100, indeterminate during upload phase. */
  progress: number;
  /** Human-readable current stage label. */
  stage: string;

  /** Populated on success. */
  modelId: string | null;
  elementCount: number;
  errorMessage: string | null;

  /** Converter id when status is 'converter_required'. */
  converterId: string | null;

  startedAt: number;
  completedAt: number | null;
}

export interface StartUploadParams {
  file: File;
  projectId: string;
  modelName: string;
  discipline: string;
  /** 'cad' for native CAD files (RVT/IFC/DWG/DGN), 'data' for CSV/XLSX. */
  uploadType: 'cad' | 'data';
  /** Optional geometry file for advanced (data) uploads. */
  geometryFile?: File | null;
  /** DDC conversion depth: 'standard' (fast, key props), 'medium' (~900 cols), 'complete' (~1000+ cols). */
  conversionDepth?: 'standard' | 'medium' | 'complete';
}

interface BIMUploadState {
  jobs: Map<string, BIMUploadJob>;

  startUpload: (params: StartUploadParams) => string;
  cancelUpload: (jobId: string) => void;
  dismissJob: (jobId: string) => void;
  clearCompleted: () => void;

  /** Retry a converter_required job after the converter was installed.
   *  Re-uses the saved File reference so the user never re-picks. */
  retryJob: (jobId: string) => void;

  hasActiveUploads: () => boolean;
  activeJobs: () => BIMUploadJob[];
  completedJobs: () => BIMUploadJob[];
}

/* ── Internal state kept outside React ─────────────────────────────────── */

/** AbortControllers for in-flight fetches, keyed by job ID. */
const abortControllers = new Map<string, AbortController>();

/** Original File objects for retry, keyed by job ID. */
const jobFiles = new Map<string, { file: File; geometryFile?: File | null }>();

/** Stage-progression timers, keyed by job ID. */
const stageTimers = new Map<string, ReturnType<typeof setInterval>>();

/* ── Store ─────────────────────────────────────────────────────────────── */

export const useBIMUploadStore = create<BIMUploadState>((set, get) => {
  /** Internal helper: update a single job. */
  function patchJob(jobId: string, patch: Partial<BIMUploadJob>) {
    set((state) => {
      const jobs = new Map(state.jobs);
      const existing = jobs.get(jobId);
      if (!existing) return state;
      jobs.set(jobId, { ...existing, ...patch });
      return { jobs };
    });
  }

  /** Internal helper: advance through simulated stages on a timer. */
  function startStageTimer(jobId: string) {
    const stages: Array<{ status: BIMUploadStatus; stage: string; progress: number }> = [
      { status: 'uploading', stage: 'Sending file...', progress: 10 },
      { status: 'converting', stage: 'Converting...', progress: 30 },
      { status: 'converting', stage: 'Parsing elements...', progress: 50 },
      { status: 'converting', stage: 'Indexing...', progress: 65 },
      { status: 'converting', stage: 'Linking geometry...', progress: 80 },
    ];
    let idx = 0;
    const timer = setInterval(() => {
      idx += 1;
      if (idx < stages.length) {
        const s = stages[idx]!;
        patchJob(jobId, { status: s.status, stage: s.stage, progress: s.progress });
      }
    }, 1500);
    stageTimers.set(jobId, timer);
  }

  function clearStageTimer(jobId: string) {
    const timer = stageTimers.get(jobId);
    if (timer) {
      clearInterval(timer);
      stageTimers.delete(jobId);
    }
  }

  /** Run the actual upload. This is a plain async function, not a hook. */
  async function executeUpload(jobId: string, params: StartUploadParams) {
    startStageTimer(jobId);

    try {
      const ac = abortControllers.get(jobId);

      if (params.uploadType === 'cad') {
        const res: BIMCadUploadResponse = await uploadCADFile(
          params.projectId,
          params.modelName,
          params.discipline,
          params.file,
          ac?.signal,
          params.conversionDepth,
        );

        clearStageTimer(jobId);
        const st = res.status || 'processing';
        const cnt = res.element_count || 0;

        if (st === 'ready' || (st !== 'converter_required' && st !== 'needs_converter' && st !== 'error')) {
          patchJob(jobId, {
            status: 'ready',
            progress: 100,
            stage: 'Done',
            modelId: res.model_id,
            elementCount: cnt,
            completedAt: Date.now(),
          });
        } else if (st === 'converter_required' || st === 'needs_converter') {
          patchJob(jobId, {
            status: 'converter_required',
            progress: 0,
            stage: 'Converter required',
            modelId: res.model_id,
            errorMessage:
              res.error_message || res.message || `${(res.format || '').toUpperCase()} converter not installed`,
            converterId: res.converter_id || null,
            completedAt: Date.now(),
          });
        } else if (st === 'error') {
          patchJob(jobId, {
            status: 'error',
            progress: 0,
            stage: 'Failed',
            modelId: res.model_id,
            errorMessage: res.error_message || 'Could not extract elements from this CAD file.',
            completedAt: Date.now(),
          });
        }
      } else {
        // Data upload (CSV/XLSX)
        const res = await uploadBIMData(
          params.projectId,
          params.modelName,
          params.discipline,
          params.file,
          params.geometryFile,
          ac?.signal,
        );

        clearStageTimer(jobId);
        patchJob(jobId, {
          status: 'ready',
          progress: 100,
          stage: 'Done',
          modelId: res.model_id,
          elementCount: res.element_count,
          completedAt: Date.now(),
        });
      }
    } catch (err) {
      clearStageTimer(jobId);
      // Don't report abort as an error
      if (err instanceof DOMException && err.name === 'AbortError') {
        return;
      }
      const msg = err instanceof Error ? err.message : String(err);
      patchJob(jobId, {
        status: 'error',
        progress: 0,
        stage: 'Failed',
        errorMessage: msg,
        completedAt: Date.now(),
      });
    } finally {
      abortControllers.delete(jobId);
      // Don't delete jobFiles — needed for retry
    }
  }

  return {
    jobs: new Map(),

    startUpload: (params) => {
      const jobId = crypto.randomUUID();
      const job: BIMUploadJob = {
        id: jobId,
        fileName: params.file.name,
        fileSize: params.file.size,
        projectId: params.projectId,
        modelName: params.modelName,
        discipline: params.discipline,
        status: 'uploading',
        progress: 5,
        stage: 'Sending file...',
        modelId: null,
        elementCount: 0,
        errorMessage: null,
        converterId: null,
        startedAt: Date.now(),
        completedAt: null,
      };

      const ac = new AbortController();
      abortControllers.set(jobId, ac);
      jobFiles.set(jobId, { file: params.file, geometryFile: params.geometryFile });

      set((state) => {
        const jobs = new Map(state.jobs);
        jobs.set(jobId, job);
        return { jobs };
      });

      // Fire and forget — the promise settles inside executeUpload
      void executeUpload(jobId, params);

      return jobId;
    },

    cancelUpload: (jobId) => {
      const ac = abortControllers.get(jobId);
      if (ac) ac.abort();
      abortControllers.delete(jobId);
      clearStageTimer(jobId);
      jobFiles.delete(jobId);

      set((state) => {
        const jobs = new Map(state.jobs);
        jobs.delete(jobId);
        return { jobs };
      });
    },

    dismissJob: (jobId) => {
      abortControllers.delete(jobId);
      jobFiles.delete(jobId);
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
          if (job.status === 'ready' || job.status === 'error' || job.status === 'converter_required') {
            jobs.delete(id);
            jobFiles.delete(id);
          }
        }
        return { jobs };
      });
    },

    retryJob: (jobId) => {
      const existing = get().jobs.get(jobId);
      const files = jobFiles.get(jobId);
      if (!existing || !files) return;

      // Reset job state
      patchJob(jobId, {
        status: 'uploading',
        progress: 5,
        stage: 'Sending file...',
        errorMessage: null,
        converterId: null,
        completedAt: null,
        startedAt: Date.now(),
      });

      const ac = new AbortController();
      abortControllers.set(jobId, ac);

      void executeUpload(jobId, {
        file: files.file,
        projectId: existing.projectId,
        modelName: existing.modelName,
        discipline: existing.discipline,
        uploadType: existing.fileName.match(/\.(csv|xlsx|xls)$/i) ? 'data' : 'cad',
        geometryFile: files.geometryFile,
      });
    },

    hasActiveUploads: () => {
      const jobs = get().jobs;
      for (const job of jobs.values()) {
        if (job.status === 'uploading' || job.status === 'converting') return true;
      }
      return false;
    },

    activeJobs: () => {
      const result: BIMUploadJob[] = [];
      for (const job of get().jobs.values()) {
        if (job.status === 'uploading' || job.status === 'converting') result.push(job);
      }
      return result;
    },

    completedJobs: () => {
      const result: BIMUploadJob[] = [];
      for (const job of get().jobs.values()) {
        if (job.status === 'ready' || job.status === 'error' || job.status === 'converter_required') {
          result.push(job);
        }
      }
      return result;
    },
  };
});
