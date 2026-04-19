/**
 * DwgUploadIndicator — floating DWG upload dock.
 *
 * Sibling to {@link GlobalUploadIndicator} but reads from
 * {@link useDwgUploadStore}. Mounted once in AppLayout so DWG uploads
 * survive navigation away from /dwg-takeoff and keep progress visible.
 *
 * Positioned at the bottom-right corner, above the BIM indicator, so the
 * two never overlap when both stores have jobs in flight.
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
  ExternalLink,
} from 'lucide-react';
import { useDwgUploadStore, type DwgUploadJob } from '@/stores/useDwgUploadStore';

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

export function DwgUploadIndicator() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const jobs = useDwgUploadStore((s) => s.jobs);
  const cancelUpload = useDwgUploadStore((s) => s.cancelUpload);
  const dismissJob = useDwgUploadStore((s) => s.dismissJob);

  const [expanded, setExpanded] = useState(false);
  const [, setTick] = useState(0);

  const allJobs = useMemo(() => Array.from(jobs.values()), [jobs]);
  const active = useMemo(
    () => allJobs.filter((j) => j.status === 'uploading' || j.status === 'converting'),
    [allJobs],
  );
  const finished = useMemo(
    () => allJobs.filter((j) => j.status === 'ready' || j.status === 'error'),
    [allJobs],
  );

  // Refresh elapsed labels while there are active jobs.
  useEffect(() => {
    if (active.length === 0) return;
    const iv = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(iv);
  }, [active.length]);

  // Auto-dismiss completed jobs. Successful ones fade after 8s, failures
  // linger for 5 min so the user can read the error.
  useEffect(() => {
    if (finished.length === 0) return;
    const timers: ReturnType<typeof setTimeout>[] = [];
    for (const job of finished) {
      if (!job.completedAt) continue;
      const lifetime = job.status === 'ready' ? 8_000 : 5 * 60 * 1000;
      const remaining = lifetime - (Date.now() - job.completedAt);
      if (remaining <= 0) dismissJob(job.id);
      else timers.push(setTimeout(() => dismissJob(job.id), remaining));
    }
    return () => timers.forEach(clearTimeout);
  }, [finished, dismissJob]);

  // Warn before unload only while actually transferring bytes.
  useEffect(() => {
    const isTransferring = active.some((j) => j.status === 'uploading');
    if (!isTransferring) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [active]);

  const handleOpen = useCallback(
    (job: DwgUploadJob) => {
      if (job.drawingId && job.projectId) {
        navigate(`/dwg-takeoff?project_id=${job.projectId}&drawing_id=${job.drawingId}`);
      } else if (job.projectId) {
        navigate(`/dwg-takeoff?project_id=${job.projectId}`);
      }
    },
    [navigate],
  );

  if (allJobs.length === 0) return null;

  const primary = active[0] || finished[0];
  if (!primary) return null;

  // Minimised pill — sits above the BIM indicator so they never overlap.
  if (!expanded) {
    const isActive = primary.status === 'uploading' || primary.status === 'converting';
    return (
      <button
        type="button"
        data-testid="dwg-upload-dock"
        onClick={() => setExpanded(true)}
        className="fixed bottom-36 right-4 z-[60] flex items-center gap-2.5 px-3.5 py-2.5 rounded-xl bg-surface-elevated border border-border-light shadow-lg hover:shadow-xl transition-all max-w-xs"
      >
        {isActive ? (
          <Loader2 size={14} className="text-oe-blue animate-spin shrink-0" />
        ) : primary.status === 'ready' ? (
          <Check size={14} className="text-emerald-500 shrink-0" />
        ) : (
          <X size={14} className="text-red-500 shrink-0" />
        )}
        <div className="flex-1 min-w-0 text-left">
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
    <div
      className="fixed bottom-36 right-4 z-[60] w-80 rounded-xl bg-surface-elevated border border-border-light shadow-xl overflow-hidden animate-fade-in"
      data-testid="dwg-upload-dock-expanded"
    >
      <div className="flex items-center justify-between px-4 py-2.5 bg-surface-secondary/50 border-b border-border-light">
        <div className="flex items-center gap-2">
          <Upload size={14} className="text-oe-blue" />
          <span className="text-xs font-semibold text-content-primary">
            {t('dwg_upload.title', { defaultValue: 'DWG Uploads' })}
          </span>
        </div>
        <button
          type="button"
          onClick={() => setExpanded(false)}
          className="p-1 rounded hover:bg-surface-secondary text-content-tertiary"
          aria-label={t('common.collapse', { defaultValue: 'Collapse' })}
        >
          <ChevronDown size={14} />
        </button>
      </div>

      <div className="max-h-64 overflow-y-auto divide-y divide-border-light">
        {allJobs.map((job) => (
          <DwgJobRow
            key={job.id}
            job={job}
            onCancel={() => cancelUpload(job.id)}
            onDismiss={() => dismissJob(job.id)}
            onOpen={() => handleOpen(job)}
          />
        ))}
      </div>
    </div>
  );
}

function DwgJobRow({
  job,
  onCancel,
  onDismiss,
  onOpen,
}: {
  job: DwgUploadJob;
  onCancel: () => void;
  onDismiss: () => void;
  onOpen: () => void;
}) {
  const { t } = useTranslation();
  const isActive = job.status === 'uploading' || job.status === 'converting';
  const isDone = job.status === 'ready';
  const isError = job.status === 'error';

  return (
    <div className="px-4 py-3 flex items-start gap-3">
      <div className="mt-0.5 shrink-0">
        {isActive && <Loader2 size={16} className="text-oe-blue animate-spin" />}
        {isDone && <Check size={16} className="text-emerald-500" />}
        {isError && <X size={16} className="text-red-500" />}
      </div>

      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium text-content-primary truncate">{job.fileName}</p>
        <p className="text-[10px] text-content-quaternary">{formatFileSize(job.fileSize)}</p>

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
              {t(job.stage, { defaultValue: 'Processing...' })} — {elapsed(job.startedAt)}
            </p>
          </div>
        )}

        {isError && (
          <p className="text-[10px] text-red-500 mt-0.5 line-clamp-2">
            {job.errorMessage || t('dwg_upload.failed', { defaultValue: 'Upload failed' })}
          </p>
        )}

        <div className="mt-1.5 flex items-center gap-2">
          {isActive && (
            <button
              type="button"
              onClick={onCancel}
              className="text-[10px] text-content-tertiary hover:text-red-500 font-medium"
            >
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </button>
          )}
          {isDone && job.drawingId && (
            <button
              type="button"
              onClick={onOpen}
              className="inline-flex items-center gap-1 text-[10px] text-oe-blue hover:underline font-medium"
            >
              <ExternalLink size={10} />
              {t('dwg_upload.open', { defaultValue: 'Open' })}
            </button>
          )}
          {!isActive && (
            <button
              type="button"
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
