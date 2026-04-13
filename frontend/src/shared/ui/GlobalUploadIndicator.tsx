/**
 * GlobalUploadIndicator — floating widget that shows BIM upload progress.
 *
 * Rendered in AppLayout (always mounted, outside the router outlet) so it
 * survives navigation between pages.  When no uploads exist it renders
 * nothing.  Active/completed uploads appear as a small fixed pill at the
 * bottom-right; clicking expands the full job list.
 *
 * Also installs a `beforeunload` handler when uploads are in flight so
 * the browser warns the user before they accidentally close the tab.
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Upload,
  Check,
  X,
  Loader2,
  ChevronUp,
  ChevronDown,
  AlertTriangle,
  ExternalLink,
  RotateCw,
} from 'lucide-react';
import {
  useBIMUploadStore,
  type BIMUploadJob,
} from '@/stores/useBIMUploadStore';

/* ── Helpers ───────────────────────────────────────────────────────────── */

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

function elapsed(startedAt: number): string {
  const sec = Math.round((Date.now() - startedAt) / 1000);
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  const rem = sec % 60;
  return `${min}m ${rem}s`;
}

function timeSince(ts: number, t: (key: string, opts?: Record<string, unknown>) => string): string {
  const sec = Math.round((Date.now() - ts) / 1000);
  if (sec < 60) return t('common.time_just_now', { defaultValue: 'just now' });
  const min = Math.floor(sec / 60);
  if (min < 60) return t('common.time_minutes_ago', { defaultValue: '{{count}}m ago', count: min });
  const hr = Math.floor(min / 60);
  return t('common.time_hours_ago', { defaultValue: '{{count}}h ago', count: hr });
}

/* ── Component ─────────────────────────────────────────────────────────── */

export function GlobalUploadIndicator() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const jobs = useBIMUploadStore((s) => s.jobs);
  const cancelUpload = useBIMUploadStore((s) => s.cancelUpload);
  const dismissJob = useBIMUploadStore((s) => s.dismissJob);
  const retryJob = useBIMUploadStore((s) => s.retryJob);
  const hasActiveUploads = useBIMUploadStore((s) => s.hasActiveUploads);

  const [expanded, setExpanded] = useState(false);
  /** Tick counter to refresh elapsed-time labels. */
  const [, setTick] = useState(0);

  const allJobs = useMemo(() => Array.from(jobs.values()), [jobs]);
  const active = useMemo(
    () => allJobs.filter((j) => j.status === 'uploading' || j.status === 'converting'),
    [allJobs],
  );
  const finished = useMemo(
    () => allJobs.filter((j) => j.status !== 'uploading' && j.status !== 'converting'),
    [allJobs],
  );

  // Refresh elapsed labels every second while there are active jobs
  useEffect(() => {
    if (active.length === 0) return;
    const iv = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(iv);
  }, [active.length]);

  // Auto-dismiss completed jobs after 5 minutes
  useEffect(() => {
    if (finished.length === 0) return;
    const timers: ReturnType<typeof setTimeout>[] = [];
    for (const job of finished) {
      if (job.completedAt) {
        const remaining = 5 * 60 * 1000 - (Date.now() - job.completedAt);
        if (remaining <= 0) {
          dismissJob(job.id);
        } else {
          timers.push(setTimeout(() => dismissJob(job.id), remaining));
        }
      }
    }
    return () => timers.forEach(clearTimeout);
  }, [finished, dismissJob]);

  // beforeunload handler: warn user when active uploads exist
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (hasActiveUploads()) {
        e.preventDefault();
        // Legacy browsers need returnValue
        e.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [hasActiveUploads]);

  const handleOpen = useCallback(
    (job: BIMUploadJob) => {
      if (job.modelId && job.projectId) {
        navigate(`/projects/${job.projectId}/bim?model=${job.modelId}`);
      }
    },
    [navigate],
  );

  // Don't render anything when there are no jobs
  if (allJobs.length === 0) return null;

  // Pick the "primary" active job for the minimized pill
  const primary = active[0] || finished[0];
  if (!primary) return null;

  // Minimized pill
  if (!expanded) {
    const isActive = primary.status === 'uploading' || primary.status === 'converting';
    return (
      <button
        onClick={() => setExpanded(true)}
        className="fixed bottom-20 right-4 z-[60] flex items-center gap-2.5 px-3.5 py-2.5 rounded-xl bg-surface-elevated border border-border-light shadow-lg hover:shadow-xl transition-all max-w-xs"
      >
        {isActive ? (
          <Loader2 size={14} className="text-oe-blue animate-spin shrink-0" />
        ) : primary.status === 'ready' ? (
          <Check size={14} className="text-emerald-500 shrink-0" />
        ) : primary.status === 'error' ? (
          <X size={14} className="text-red-500 shrink-0" />
        ) : (
          <AlertTriangle size={14} className="text-amber-500 shrink-0" />
        )}
        <div className="flex-1 min-w-0">
          <p className="text-xs font-medium text-content-primary truncate">
            {primary.fileName}
          </p>
          {isActive && (
            <div className="flex items-center gap-2 mt-1">
              <div className="flex-1 h-1 rounded-full bg-surface-tertiary overflow-hidden">
                <div
                  className="h-full rounded-full bg-oe-blue transition-all duration-300"
                  style={{ width: `${primary.progress}%` }}
                />
              </div>
              <span className="text-[10px] text-content-tertiary tabular-nums">
                {primary.progress}%
              </span>
            </div>
          )}
          {!isActive && primary.status === 'ready' && (
            <p className="text-[10px] text-emerald-600 mt-0.5">
              {t('bim.upload_indicator_ready', {
                defaultValue: '{{count}} elements',
                count: primary.elementCount,
              })}
            </p>
          )}
        </div>
        {active.length > 1 && (
          <span className="text-[10px] text-content-tertiary bg-surface-secondary px-1.5 py-0.5 rounded-full">
            +{active.length - 1}
          </span>
        )}
        <ChevronUp size={12} className="text-content-tertiary shrink-0" />
      </button>
    );
  }

  // Expanded panel
  return (
    <div className="fixed bottom-20 right-4 z-[60] w-80 rounded-xl bg-surface-elevated border border-border-light shadow-xl overflow-hidden animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-surface-secondary/50 border-b border-border-light">
        <div className="flex items-center gap-2">
          <Upload size={14} className="text-oe-blue" />
          <span className="text-xs font-semibold text-content-primary">
            {t('bim.upload_indicator_title', { defaultValue: 'BIM Uploads' })}
          </span>
        </div>
        <button
          onClick={() => setExpanded(false)}
          className="p-1 rounded hover:bg-surface-secondary text-content-tertiary"
          aria-label={t('common.collapse', { defaultValue: 'Collapse' })}
        >
          <ChevronDown size={14} />
        </button>
      </div>

      {/* Job list */}
      <div className="max-h-64 overflow-y-auto divide-y divide-border-light">
        {allJobs.map((job) => (
          <JobRow
            key={job.id}
            job={job}
            onCancel={() => cancelUpload(job.id)}
            onDismiss={() => dismissJob(job.id)}
            onRetry={() => retryJob(job.id)}
            onOpen={() => handleOpen(job)}
          />
        ))}
      </div>
    </div>
  );
}

/* ── Job Row ───────────────────────────────────────────────────────────── */

function JobRow({
  job,
  onCancel,
  onDismiss,
  onRetry,
  onOpen,
}: {
  job: BIMUploadJob;
  onCancel: () => void;
  onDismiss: () => void;
  onRetry: () => void;
  onOpen: () => void;
}) {
  const { t } = useTranslation();
  const isActive = job.status === 'uploading' || job.status === 'converting';
  const isDone = job.status === 'ready';
  const isError = job.status === 'error';
  const isConverterRequired = job.status === 'converter_required';

  return (
    <div className="px-4 py-3 flex items-start gap-3">
      {/* Status icon */}
      <div className="mt-0.5 shrink-0">
        {isActive && <Loader2 size={16} className="text-oe-blue animate-spin" />}
        {isDone && <Check size={16} className="text-emerald-500" />}
        {isError && <X size={16} className="text-red-500" />}
        {isConverterRequired && <AlertTriangle size={16} className="text-amber-500" />}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium text-content-primary truncate">
          {job.fileName}
        </p>
        <p className="text-[10px] text-content-quaternary">
          {formatFileSize(job.fileSize)}
        </p>

        {/* Active: progress bar + elapsed */}
        {isActive && (
          <div className="mt-1.5">
            <div className="flex items-center gap-2">
              <div className="flex-1 h-1.5 bg-surface-tertiary rounded-full overflow-hidden">
                <div
                  className="h-full bg-oe-blue rounded-full transition-all duration-500"
                  style={{ width: `${job.progress}%` }}
                />
              </div>
              <span className="text-[10px] text-oe-blue font-semibold tabular-nums w-8 text-right">
                {job.progress}%
              </span>
            </div>
            <p className="text-[10px] text-content-quaternary mt-0.5">
              {job.stage} — {elapsed(job.startedAt)}
            </p>
          </div>
        )}

        {/* Completed: element count + open button */}
        {isDone && (
          <div className="mt-1 flex items-center gap-2">
            <span className="text-[10px] text-emerald-600">
              {t('bim.upload_indicator_ready', {
                defaultValue: '{{count}} elements',
                count: job.elementCount,
              })}
            </span>
            {job.completedAt && (
              <span className="text-[10px] text-content-quaternary">
                {timeSince(job.completedAt, t)}
              </span>
            )}
          </div>
        )}

        {/* Error */}
        {isError && (
          <p className="text-[10px] text-red-500 mt-0.5 line-clamp-2">
            {job.errorMessage || t('bim.upload_indicator_error', { defaultValue: 'Upload failed' })}
          </p>
        )}

        {/* Converter required */}
        {isConverterRequired && (
          <p className="text-[10px] text-amber-600 mt-0.5 line-clamp-2">
            {job.errorMessage ||
              t('bim.upload_indicator_converter', {
                defaultValue: 'Converter not installed',
              })}
          </p>
        )}

        {/* Action buttons */}
        <div className="mt-1.5 flex items-center gap-2">
          {isActive && (
            <button
              onClick={onCancel}
              className="text-[10px] text-content-tertiary hover:text-red-500 font-medium"
            >
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </button>
          )}
          {isDone && job.modelId && (
            <button
              onClick={onOpen}
              className="inline-flex items-center gap-1 text-[10px] text-oe-blue hover:underline font-medium"
            >
              <ExternalLink size={10} />
              {t('bim.upload_indicator_open', { defaultValue: 'Open' })}
            </button>
          )}
          {(isError || isConverterRequired) && (
            <button
              onClick={onRetry}
              className="inline-flex items-center gap-1 text-[10px] text-oe-blue hover:underline font-medium"
            >
              <RotateCw size={10} />
              {t('bim.upload_indicator_retry', { defaultValue: 'Retry' })}
            </button>
          )}
          {!isActive && (
            <button
              onClick={onDismiss}
              className="text-[10px] text-content-quaternary hover:text-content-secondary"
            >
              {t('common.dismiss', { defaultValue: 'Dismiss' })}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
