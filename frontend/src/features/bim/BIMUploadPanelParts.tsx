// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pieces shared by the two BIM upload surfaces (the Add Model side panel and
 * the landing dropzone): one row per upload job with a cancel control, and the
 * prompt shown when the picked file was already uploaded to the project.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { CheckCircle2, Copy, Loader2 } from 'lucide-react';
import { useBIMUploadStore, type BIMUploadJob } from '@/stores/useBIMUploadStore';
import { findUploadDuplicates, type BIMUploadDuplicate } from './api';

/** Navigation state that keeps the upload panel open across the page's own
 *  /bim -> /bim/<model> redirect. The app shell remounts a page on every
 *  pathname change, so plain component state would be lost. */
export function uploadPanelNavState(open: boolean): { bimUploadOpen: true } | null {
  return open ? { bimUploadOpen: true } : null;
}

export function isUploadPanelOpenInNavState(state: unknown): boolean {
  return (state as { bimUploadOpen?: unknown } | null)?.bimUploadOpen === true;
}

/** Jobs of one project that the upload surfaces list: running, then done. */
export function projectUploadJobs(jobs: Map<string, BIMUploadJob>, projectId: string | null | undefined): BIMUploadJob[] {
  const out: BIMUploadJob[] = [];
  for (const job of jobs.values()) {
    if (job.projectId !== projectId) continue;
    if (job.status === 'uploading' || job.status === 'converting' || job.status === 'ready') out.push(job);
  }
  return out;
}

function elapsedLabel(startedAt: number): string {
  const sec = Math.max(0, Math.round((Date.now() - startedAt) / 1000));
  if (sec < 60) return `${sec}s`;
  return `${Math.floor(sec / 60)}m ${sec % 60}s`;
}

export function BIMUploadJobRow({ job, variant = 'panel' }: { job: BIMUploadJob; variant?: 'panel' | 'landing' }) {
  const { t } = useTranslation();
  const cancelUpload = useBIMUploadStore((s) => s.cancelUpload);
  const done = job.status === 'ready';
  // Re-render once a second so the elapsed time keeps moving while the
  // server converts and nothing else changes on the job.
  const [, setTick] = useState(0);
  useEffect(() => {
    if (done) return;
    const iv = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(iv);
  }, [done]);
  const frame = done
    ? 'border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-950/20'
    : variant === 'landing'
      ? 'border-oe-blue/30 bg-white dark:bg-gray-900 shadow-sm'
      : 'border-oe-blue/30 bg-oe-blue/5';
  return (
    <div data-testid="bim-upload-job-row" className={`rounded-xl border ${variant === 'landing' ? 'p-3.5' : 'p-3'} ${frame}`}>
      <div className="flex items-center gap-2 mb-1.5">
        {done ? (
          <CheckCircle2 size={14} className="text-green-500 shrink-0" />
        ) : (
          <Loader2 size={14} className="text-oe-blue animate-spin shrink-0" />
        )}
        <span className="flex-1 min-w-0 text-xs font-medium text-content-primary truncate">{job.fileName}</span>
        {!done && (
          <button
            type="button"
            onClick={() => cancelUpload(job.id)}
            className="shrink-0 text-[10px] font-medium text-content-tertiary hover:text-red-500"
            title={
              job.serverConverting
                ? t('bim_upload.cancel_server_tip', {
                    defaultValue: 'Stop the conversion and remove this model from the project.',
                  })
                : undefined
            }
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </button>
        )}
      </div>
      {done ? (
        <p className="text-[10px] text-green-600 dark:text-green-400">
          {t('bim.upload_complete_count', { defaultValue: '{{count}} elements', count: job.elementCount })}
        </p>
      ) : (
        <>
          <div className="h-1.5 w-full rounded-full bg-surface-tertiary overflow-hidden">
            {job.serverConverting ? (
              <div className="h-full w-full rounded-full bg-oe-blue/60 animate-pulse" />
            ) : (
              <div
                className="h-full rounded-full bg-gradient-to-r from-oe-blue to-blue-400 transition-all duration-500 ease-out"
                style={{ width: `${job.progress}%` }}
              />
            )}
          </div>
          <p className="text-[10px] text-content-tertiary mt-1">
            {t(job.stage, { defaultValue: 'Processing...' })} · {elapsedLabel(job.startedAt)}
          </p>
        </>
      )}
    </div>
  );
}

/** A start that waits for the user to settle a same-file collision. */
export interface PendingDuplicateUpload {
  fileName: string;
  duplicates: BIMUploadDuplicate[];
  start: (parentModelId: string | null) => void;
}

/** Models in the project uploaded from this same file. A failed lookup never
 *  blocks the upload, it only skips the warning. */
export async function lookUpUploadDuplicates(projectId: string, file: File): Promise<BIMUploadDuplicate[]> {
  try {
    return await findUploadDuplicates(projectId, file.name, file.size);
  } catch {
    return [];
  }
}

export function BIMUploadDuplicatePrompt({
  pending,
  onDone,
}: {
  pending: PendingDuplicateUpload;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const latest = pending.duplicates[0]!;
  return (
    <div
      role="alertdialog"
      aria-live="polite"
      data-testid="bim-upload-duplicate-prompt"
      className="rounded-xl border border-amber-300/70 dark:border-amber-700/50 bg-amber-50 dark:bg-amber-950/20 p-3 space-y-2"
    >
      <div className="flex items-start gap-2">
        <Copy size={14} className="text-amber-600 shrink-0 mt-0.5" />
        <p className="text-xs text-content-primary">
          {t('bim_upload.duplicate_found', {
            defaultValue: '"{{file}}" was already uploaded to this project as "{{model}}".',
            file: pending.fileName,
            model: latest.name,
          })}
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          data-testid="bim-upload-duplicate-version"
          onClick={() => {
            pending.start(latest.model_id);
            onDone();
          }}
          className="px-2.5 py-1 rounded-lg text-[11px] font-semibold bg-oe-blue text-white hover:bg-oe-blue-dark"
        >
          {t('bim_upload.duplicate_as_version', {
            defaultValue: 'Upload as new version of "{{model}}"',
            model: latest.name,
          })}
        </button>
        <button
          type="button"
          data-testid="bim-upload-duplicate-separate"
          onClick={() => {
            pending.start(null);
            onDone();
          }}
          className="px-2.5 py-1 rounded-lg text-[11px] font-medium border border-border-light text-content-secondary hover:bg-surface-secondary"
        >
          {t('bim_upload.duplicate_as_separate', { defaultValue: 'Upload as a separate model' })}
        </button>
        <button
          type="button"
          onClick={onDone}
          className="px-2.5 py-1 rounded-lg text-[11px] font-medium text-content-tertiary hover:text-content-primary"
        >
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </button>
      </div>
    </div>
  );
}
