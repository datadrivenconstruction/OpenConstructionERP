// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Waiting for a BOQ import the server runs as a background job.
 *
 * ``POST /import/auto/?background=true`` answers 202 with a job id at once;
 * the same file posted again while that job runs gets the job back, so a
 * retry never imports a bill twice. Posted again after it was imported, it is
 * answered 409 ``import_already_done`` (see ``alreadyImported``). This polls the job until it ends and hands back the
 * response the synchronous import would have given, so the editor's existing
 * result toast reads it unchanged. A file no native reader claims is still
 * answered synchronously (200 with the result), which ``resultOrJob`` passes
 * straight through.
 */

import { importFailureText } from './importFailureText';

/** Minimal shape of the i18next `t` used here (repo convention). */
type Translate = (key: string, opts?: Record<string, unknown>) => string;

export type ImportPhase = 'reading' | 'writing' | 'validating';

export interface ImportJobView {
  job_id: string;
  status: 'pending' | 'started' | 'success' | 'failed' | 'cancelled';
  progress_percent: number;
  phase?: ImportPhase | string | null;
  result?: unknown;
  /** The server's English fallback for why the file was refused; null for an internal failure. */
  error?: string | null;
  /** Why the file was refused, worded from ``boq.import_error.<code>``. */
  error_code?: string | null;
  error_params?: Record<string, unknown> | null;
}

export interface ImportProgress {
  percent: number;
  phase: ImportPhase | null;
}

/** Raised when the job ended without importing; ``message`` is ready to show. */
export class ImportJobFailedError extends Error {}

const FINISHED = new Set(['success', 'failed', 'cancelled']);

export function isImportJob(body: unknown): body is ImportJobView {
  return typeof body === 'object' && body !== null && typeof (body as { job_id?: unknown }).job_id === 'string';
}

/** The phase the server reported, when it is one the editor has words for. */
export function importPhase(view: ImportJobView): ImportPhase | null {
  const phase = view.phase;
  return phase === 'reading' || phase === 'writing' || phase === 'validating' ? phase : null;
}

/** The line the editor shows while the job runs. */
export function importProgressText(progress: ImportProgress, t: Translate): string {
  const percent = Math.max(0, Math.min(100, Math.round(progress.percent)));
  switch (progress.phase) {
    case 'reading':
      return t('boq.import_job_reading', { defaultValue: 'Reading the file… {{percent}}%', percent });
    case 'writing':
      return t('boq.import_job_writing', { defaultValue: 'Writing the positions… {{percent}}%', percent });
    case 'validating':
      return t('boq.import_job_validating', { defaultValue: 'Checking the bill… {{percent}}%', percent });
    default:
      return t('boq.import_job_queued', { defaultValue: 'Waiting to start… {{percent}}%', percent });
  }
}

interface WaitOptions {
  boqId: string;
  jobId: string;
  headers: Record<string, string>;
  t: Translate;
  onProgress?: (progress: ImportProgress) => void;
  /** Stops waiting (the import itself goes on on the server). */
  signal?: AbortSignal;
  intervalMs?: number;
  fetchImpl?: typeof fetch;
  sleep?: (ms: number) => Promise<void>;
}

const defaultSleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/**
 * Poll the job until it ends; resolve with its result, or reject with
 * {@link ImportJobFailedError} carrying a message the reader can act on.
 * A poll that fails on the network is retried: the import goes on on the
 * server whether or not the editor hears about it.
 */
export async function waitForImportJob<T = unknown>({
  boqId,
  jobId,
  headers,
  t,
  onProgress,
  signal,
  intervalMs = 2000,
  fetchImpl = fetch,
  sleep = defaultSleep,
}: WaitOptions): Promise<T> {
  const url = `/api/v1/boq/boqs/${boqId}/import/jobs/${jobId}/`;
  let networkFailures = 0;
  for (;;) {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    let view: ImportJobView | null = null;
    try {
      const res = await fetchImpl(url, { headers, signal });
      if (res.status === 404) {
        throw new ImportJobFailedError(
          t('boq.import_job_lost', { defaultValue: 'The import could not be found any more. Reload the bill to see what was imported.' }),
        );
      }
      if (!res.ok) throw new Error(`poll answered ${res.status}`);
      view = (await res.json()) as ImportJobView;
      networkFailures = 0;
    } catch (err) {
      if (err instanceof ImportJobFailedError) throw err;
      if (err instanceof DOMException && err.name === 'AbortError') throw err;
      networkFailures += 1;
      // About a minute of failed polls at the default interval.
      if (networkFailures >= 30) {
        throw new ImportJobFailedError(
          t('boq.import_job_unreachable', {
            defaultValue: 'Lost contact with the server. The import may still finish; reload the bill in a minute.',
          }),
        );
      }
    }
    if (view) {
      onProgress?.({ percent: view.status === 'success' ? 100 : view.progress_percent, phase: importPhase(view) });
      if (FINISHED.has(view.status)) {
        if (view.status === 'success') return view.result as T;
        const stopped = t('boq.import_job_failed', {
          defaultValue: 'The import stopped before it finished. Nothing was imported; try again.',
        });
        throw new ImportJobFailedError(
          view.error || view.error_code
            ? importFailureText({ code: view.error_code, params: view.error_params, message: view.error }, t, stopped)
            : stopped,
        );
      }
    }
    await sleep(intervalMs);
  }
}
