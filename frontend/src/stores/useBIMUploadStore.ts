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
  generateBIMPDFSheets,
  fetchBIMModel,
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

  /** When true, the store will fire a background PDF-sheet generation
   *  request once the model record reaches status="ready" on the
   *  backend.  The request is deliberately delayed: triggering it
   *  immediately makes the PDF DDC subprocess compete with the model
   *  conversion DDC, which can stall the upload entirely. */
  generatePdfSheets: boolean;

  /** Lifecycle of the optional PDF-sheet generation:
   *    - 'idle'        — no PDF requested, or model not ready yet
   *    - 'generating'  — backend has accepted the PDF job and is exporting
   *    - 'done'        — PDF generation finished successfully
   *    - 'failed'      — backend rejected or DDC failed; ``pdfError`` is set
   */
  pdfStatus: 'idle' | 'generating' | 'done' | 'failed';
  pdfError: string | null;

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
  /** When true, also fire a background request to extract all sheets
   *  from the uploaded CAD file as a single PDF (CAD uploads only). */
  generatePdfSheets?: boolean;
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

/** Secondary interval handles for the phase-tick timers. */
const activeIntervalTimers = new Map<string, ReturnType<typeof setInterval>>();

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

  /** Internal helper: advance through simulated stages on a timer.
   *
   *  Progress phases:
   *    0-30%  : Upload phase (fast, ~3s)
   *   30-60%  : Conversion phase (slower, steady increments, ~8s)
   *   60-90%  : Element extraction (medium speed, ~6s)
   *   90-95%  : Finalization (quick, ~2s)
   *
   *  The bar advances smoothly with small increments that slow down
   *  near each phase boundary — mimicking real I/O behaviour. */
  function startStageTimer(jobId: string) {
    const phases: Array<{
      status: BIMUploadStatus;
      stage: string;
      targetPct: number;
      /** ms between ticks */
      interval: number;
      /** pct added per tick (capped at targetPct) */
      step: number;
    }> = [
      { status: 'uploading',  stage: 'bim_upload.stage_uploading',    targetPct: 30, interval: 200, step: 1.8 },
      { status: 'converting', stage: 'bim_upload.stage_converting',   targetPct: 50, interval: 400, step: 0.8 },
      { status: 'converting', stage: 'bim_upload.stage_extracting',   targetPct: 75, interval: 300, step: 1.0 },
      { status: 'converting', stage: 'bim_upload.stage_indexing',     targetPct: 88, interval: 250, step: 1.2 },
      { status: 'converting', stage: 'bim_upload.stage_finalizing',   targetPct: 95, interval: 200, step: 1.5 },
    ];

    let phaseIdx = 0;
    let currentPct = 5;

    const tick = () => {
      if (phaseIdx >= phases.length) return;
      const phase = phases[phaseIdx]!;

      // Slow down exponentially as we approach the phase boundary
      const remaining = phase.targetPct - currentPct;
      const increment = Math.max(0.15, Math.min(phase.step, remaining * 0.12));
      currentPct = Math.min(phase.targetPct, currentPct + increment);

      patchJob(jobId, {
        status: phase.status,
        stage: phase.stage,
        progress: Math.round(currentPct),
      });

      if (currentPct >= phase.targetPct - 0.2) {
        phaseIdx += 1;
      }
    };

    // Use a dynamic interval: each phase can have its own tick rate
    let activeInterval: ReturnType<typeof setInterval> | null = null;
    let lastPhaseIdx = -1;

    const masterTimer = setInterval(() => {
      if (phaseIdx >= phases.length) return;
      if (phaseIdx !== lastPhaseIdx) {
        lastPhaseIdx = phaseIdx;
        if (activeInterval) clearInterval(activeInterval);
        activeInterval = setInterval(tick, phases[phaseIdx]!.interval);
      }
    }, 100);

    // Start the first phase immediately
    tick();
    activeInterval = setInterval(tick, phases[0]!.interval);

    // Store both timer handles so clearStageTimer can kill them.
    stageTimers.set(jobId, masterTimer);
    activeIntervalTimers.set(jobId, activeInterval!);
  }

  function clearStageTimer(jobId: string) {
    const timer = stageTimers.get(jobId);
    if (timer) {
      clearInterval(timer);
      stageTimers.delete(jobId);
    }
    const activeTimer = activeIntervalTimers.get(jobId);
    if (activeTimer) {
      clearInterval(activeTimer);
      activeIntervalTimers.delete(jobId);
    }
  }

  /** Poll the model record until it's ready, then trigger background PDF
   *  export.  Used by ``executeUpload`` when ``params.generatePdfSheets``
   *  is true; lives at module scope so the polling loop survives page
   *  navigation (the upload store itself is global).  Bail out silently if
   *  the job is removed or the model fails — the heavy lifting is on the
   *  backend, this side is only orchestration. */
  async function waitForReadyThenGeneratePdf(jobId: string, modelId: string) {
    const POLL_INTERVAL_MS = 4000;
    const POLL_MAX_ATTEMPTS = 600; // ~40 minutes upper bound

    for (let attempt = 0; attempt < POLL_MAX_ATTEMPTS; attempt++) {
      // Bail if the user dismissed/cancelled the job
      if (!get().jobs.has(jobId)) return;

      await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));

      let model: Awaited<ReturnType<typeof fetchBIMModel>>;
      try {
        model = await fetchBIMModel(modelId);
      } catch {
        // Transient network blip — keep polling
        continue;
      }

      if (model.status === 'ready') {
        patchJob(jobId, { pdfStatus: 'generating', pdfError: null });
        try {
          await generateBIMPDFSheets(modelId);
        } catch (e) {
          patchJob(jobId, {
            pdfStatus: 'failed',
            pdfError: e instanceof Error ? e.message : String(e),
          });
          return;
        }
        // The PDF endpoint just schedules a backend BackgroundTask; there
        // is no completion signal we can poll without scraping Documents.
        // Mark the indicator as done after a heuristic delay long enough
        // for typical sheet exports — the resulting PDF will appear in
        // the project's Documents list when DDC finishes.
        setTimeout(() => {
          if (get().jobs.has(jobId)) {
            patchJob(jobId, { pdfStatus: 'done' });
          }
        }, 90 * 1000);
        return;
      }

      if (model.status === 'error' || model.status === 'needs_converter') {
        // Don't try to generate PDF for a model that itself failed.
        return;
      }
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

        const isSuccessStatus =
          st === 'ready' ||
          (st !== 'converter_required' &&
            st !== 'needs_converter' &&
            st !== 'error');

        if (isSuccessStatus) {
          patchJob(jobId, {
            status: 'ready',
            progress: 100,
            stage: 'bim_upload.stage_done',
            modelId: res.model_id,
            elementCount: cnt,
            completedAt: Date.now(),
          });

          // PDF generation is intentionally deferred until the model record
          // reaches status="ready" on the backend.  Triggering it earlier
          // makes the PDF DDC subprocess race the model conversion DDC, and
          // both crawl — the user reported the upload "freezing forever".
          // We poll model status here in the store so the call survives
          // page navigation; once the model is ready we fire-and-forget the
          // PDF endpoint and surface its lifecycle via job.pdfStatus.
          if (params.generatePdfSheets && res.model_id) {
            const modelIdForPdf = res.model_id;
            void waitForReadyThenGeneratePdf(jobId, modelIdForPdf);
          }
        } else if (st === 'converter_required' || st === 'needs_converter') {
          patchJob(jobId, {
            status: 'converter_required',
            progress: 0,
            stage: 'bim_upload.stage_converter_required',
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
            stage: 'bim_upload.stage_failed',
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
          stage: 'bim_upload.stage_done',
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
        stage: 'bim_upload.stage_failed',
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
        stage: 'bim_upload.stage_sending',
        modelId: null,
        elementCount: 0,
        errorMessage: null,
        converterId: null,
        generatePdfSheets: params.generatePdfSheets ?? false,
        pdfStatus: 'idle',
        pdfError: null,
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
        stage: 'bim_upload.stage_sending',
        errorMessage: null,
        converterId: null,
        pdfStatus: 'idle',
        pdfError: null,
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
        generatePdfSheets: existing.generatePdfSheets,
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
