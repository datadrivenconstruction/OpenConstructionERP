/**
 * BIMProcessingProgress — multi-stage stepper shown during BIM file upload
 * and conversion.
 *
 * The backend `/upload-cad/` endpoint is synchronous: by the time the
 * request returns, the model's status is already final (ready / error /
 * needs_converter). That means the frontend has no intermediate milestones
 * to poll — we only know "still waiting for the server" vs "done".
 *
 * To give the user meaningful feedback we advance through the six known
 * stages on a loose time schedule that reflects a typical small-to-medium
 * IFC/RVT conversion. The current stage is *estimated*, not authoritative —
 * if the real work finishes early we jump straight to "ready". If the
 * server reports `needs_converter` or `error` we stop on the stage where
 * the problem happened and surface the error message.
 *
 * Stages (see CLAUDE.md section "Целевой Workflow"):
 *  1. Uploading       — file transferred to server
 *  2. Converting      — DDC cad2data / IFC parser running
 *  3. Parsing         — backend reading the intermediate file into rows
 *  4. Indexing        — elements written to DB, stable_id index built
 *  5. Linking geometry — COLLADA mesh nodes matched to element stable_ids
 *  6. Ready           — viewport opens
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  Upload as UploadIcon,
  Cpu,
  FileText,
  Database,
  Link2,
  CheckCircle2,
  XCircle,
  Loader2,
  AlertTriangle,
} from 'lucide-react';

export type BIMProcessingStage =
  | 'uploading'
  | 'converting'
  | 'parsing'
  | 'indexing'
  | 'linking'
  | 'ready'
  | 'error'
  | 'needs_converter';

export interface BIMProcessingProgressProps {
  /** Current stage (driven by the parent). */
  stage: BIMProcessingStage;
  /** Optional file name displayed in the card header. */
  fileName?: string;
  /** Optional file size label (e.g. "23.4 MB"). */
  fileSize?: string;
  /** Element count — shown once the model is ready. */
  elementCount?: number;
  /** Error message — shown in error / needs_converter states. */
  errorMessage?: string;
  /** Called when the user dismisses the card. */
  onClose?: () => void;
}

interface StageDef {
  id: Exclude<BIMProcessingStage, 'error' | 'needs_converter'>;
  icon: React.ElementType;
  labelKey: string;
  defaultLabel: string;
  hintKey: string;
  defaultHint: string;
}

const STAGES: StageDef[] = [
  {
    id: 'uploading',
    icon: UploadIcon,
    labelKey: 'bim.progress_uploading',
    defaultLabel: 'Uploading',
    hintKey: 'bim.progress_uploading_hint',
    defaultHint: 'Sending file to the server…',
  },
  {
    id: 'converting',
    icon: Cpu,
    labelKey: 'bim.progress_converting',
    defaultLabel: 'Converting',
    hintKey: 'bim.progress_converting_hint',
    defaultHint: 'Running CAD converter (DDC cad2data for RVT, IFC parser for IFC)…',
  },
  {
    id: 'parsing',
    icon: FileText,
    labelKey: 'bim.progress_parsing',
    defaultLabel: 'Parsing',
    hintKey: 'bim.progress_parsing_hint',
    defaultHint: 'Reading converted rows into BIM elements…',
  },
  {
    id: 'indexing',
    icon: Database,
    labelKey: 'bim.progress_indexing',
    defaultLabel: 'Indexing',
    hintKey: 'bim.progress_indexing_hint',
    defaultHint: 'Writing elements to the database and building the stable-id index…',
  },
  {
    id: 'linking',
    icon: Link2,
    labelKey: 'bim.progress_linking',
    defaultLabel: 'Linking geometry',
    hintKey: 'bim.progress_linking_hint',
    defaultHint: 'Matching COLLADA mesh nodes to element stable ids…',
  },
  {
    id: 'ready',
    icon: CheckCircle2,
    labelKey: 'bim.progress_ready',
    defaultLabel: 'Ready',
    hintKey: 'bim.progress_ready_hint',
    defaultHint: 'Model ready to view.',
  },
];

function stageIndex(stage: BIMProcessingStage): number {
  const idx = STAGES.findIndex((s) => s.id === stage);
  return idx >= 0 ? idx : 0;
}

export function BIMProcessingProgress({
  stage,
  fileName,
  fileSize,
  elementCount,
  errorMessage,
  onClose,
}: BIMProcessingProgressProps) {
  const { t } = useTranslation();
  const isError = stage === 'error' || stage === 'needs_converter';
  const isDone = stage === 'ready';
  const currentIdx = isError ? -1 : stageIndex(stage);

  // Visual progress with realistic phase-aware pacing:
  //   uploading   (idx 0): 0-30%  — fast, proportional to upload
  //   converting  (idx 1): 30-60% — slower, steady increments
  //   parsing     (idx 2): 60-75% — medium
  //   indexing    (idx 3): 75-90% — medium
  //   linking     (idx 4): 90-98% — quick
  //   ready       (idx 5): 100%
  const PHASE_TARGETS = [30, 60, 75, 90, 98, 100];
  const PHASE_SPEEDS  = [0.08, 0.04, 0.06, 0.06, 0.10, 0]; // multiplier for exponential approach

  const [visualPct, setVisualPct] = useState(2);
  const [elapsedSec, setElapsedSec] = useState(0);
  const startTime = useRef(Date.now());

  // Track elapsed seconds for estimated-time display
  useEffect(() => {
    if (isDone || isError) return;
    const iv = setInterval(() => {
      setElapsedSec(Math.floor((Date.now() - startTime.current) / 1000));
    }, 1000);
    return () => clearInterval(iv);
  }, [isDone, isError]);

  useEffect(() => {
    if (isError) return;
    if (isDone) {
      setVisualPct(100);
      return;
    }
    const target = PHASE_TARGETS[currentIdx] ?? 30;
    const speed = PHASE_SPEEDS[currentIdx] ?? 0.05;
    const iv = setInterval(() => {
      setVisualPct((prev) => {
        if (prev >= target) return prev;
        // Exponential approach — slows down near the phase boundary,
        // giving a natural "working" feel instead of a stuck bar.
        const remaining = target - prev;
        const increment = Math.max(0.1, remaining * speed);
        return Math.min(target, prev + increment);
      });
    }, 100);
    return () => clearInterval(iv);
  }, [currentIdx, isDone, isError]);

  // Formatted elapsed time string
  const elapsedLabel = useMemo(() => {
    if (isDone || isError) return '';
    if (elapsedSec < 5) return '';
    const m = Math.floor(elapsedSec / 60);
    const s = elapsedSec % 60;
    return m > 0 ? `${m}m ${s}s` : `${s}s`;
  }, [elapsedSec, isDone, isError]);

  const headerCopy = useMemo(() => {
    if (stage === 'needs_converter') {
      return {
        title: t('bim.progress_needs_converter_title', {
          defaultValue: 'Converter required',
        }),
        subtitle:
          errorMessage ||
          t('bim.progress_needs_converter_hint', {
            defaultValue: 'This format needs an external converter. Convert to IFC first.',
          }),
      };
    }
    if (stage === 'error') {
      return {
        title: t('bim.progress_error_title', { defaultValue: 'Processing failed' }),
        subtitle:
          errorMessage ||
          t('bim.progress_error_hint', {
            defaultValue: 'Something went wrong while processing the model.',
          }),
      };
    }
    if (stage === 'ready') {
      return {
        title: t('bim.progress_ready_title', { defaultValue: 'Model ready' }),
        subtitle:
          elementCount !== undefined
            ? t('bim.progress_ready_count', {
                defaultValue: '{{count}} elements extracted.',
                count: elementCount,
              })
            : t('bim.progress_ready_hint', { defaultValue: 'Model ready to view.' }),
      };
    }
    return {
      title: t('bim.progress_title', { defaultValue: 'Preparing model' }),
      subtitle: t('bim.progress_subtitle', {
        defaultValue: 'This can take a minute for large CAD files.',
      }),
    };
  }, [stage, errorMessage, elementCount, t]);

  return (
    <div
      role="status"
      aria-label={headerCopy.title}
      className="w-[440px] max-w-full rounded-2xl border border-border-light bg-surface-primary shadow-2xl overflow-hidden pointer-events-auto"
    >
      {/* Header */}
      <div className="flex items-start gap-3 px-5 pt-5 pb-4 border-b border-border-light">
        <div
          className={clsx(
            'flex h-10 w-10 shrink-0 items-center justify-center rounded-xl',
            isError
              ? 'bg-red-50 dark:bg-red-950/20 text-red-500'
              : isDone
                ? 'bg-emerald-50 dark:bg-emerald-950/20 text-emerald-500'
                : 'bg-oe-blue/10 text-oe-blue',
          )}
        >
          {isError ? (
            stage === 'needs_converter' ? (
              <AlertTriangle size={20} />
            ) : (
              <XCircle size={20} />
            )
          ) : isDone ? (
            <CheckCircle2 size={20} />
          ) : (
            <Loader2 size={20} className="animate-spin" />
          )}
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-bold text-content-primary">{headerCopy.title}</h3>
          <p className="text-[11px] text-content-tertiary mt-0.5 leading-relaxed">
            {headerCopy.subtitle}
          </p>
          {fileName && (
            <p className="text-[10px] text-content-quaternary mt-1 truncate">
              {fileName}
              {fileSize ? ` · ${fileSize}` : ''}
            </p>
          )}
        </div>
        {(isDone || isError) && onClose && (
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="shrink-0 text-[11px] text-content-tertiary hover:text-content-primary hover:underline"
          >
            {t('common.close', { defaultValue: 'Close' })}
          </button>
        )}
      </div>

      {/* Progress bar */}
      {!isError && (
        <div className="px-5 pt-4">
          <div className="flex items-center justify-between text-[10px] text-content-tertiary mb-1.5">
            <span>
              {isDone
                ? t('bim.progress_done_label', { defaultValue: 'Done' })
                : t(STAGES[currentIdx]?.labelKey ?? 'bim.progress_running', {
                    defaultValue: STAGES[currentIdx]?.defaultLabel ?? 'Processing',
                  })}
            </span>
            <span className="flex items-center gap-2 tabular-nums">
              {elapsedLabel && !isDone && (
                <span className="text-content-quaternary">{elapsedLabel}</span>
              )}
              {Math.round(visualPct)}%
            </span>
          </div>
          <div
            className="h-1.5 w-full rounded-full bg-surface-tertiary overflow-hidden"
            role="progressbar"
            aria-valuenow={Math.round(visualPct)}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <div
              className={clsx(
                'h-full rounded-full',
                isDone
                  ? 'bg-emerald-400 transition-all duration-500 ease-out'
                  : 'bg-gradient-to-r from-oe-blue to-blue-400 transition-[width] duration-700 ease-out',
              )}
              style={{ width: `${visualPct}%` }}
            />
          </div>
        </div>
      )}

      {/* Stepper */}
      <ul className="px-5 pt-4 pb-5 space-y-2.5">
        {STAGES.filter((s) => s.id !== 'ready').map((s, idx) => {
          let stateCls = 'text-content-quaternary';
          let iconCls = 'bg-surface-tertiary text-content-quaternary';
          let showSpinner = false;
          let showCheck = false;

          if (isError) {
            // On error, mark everything up to the error stage as done and
            // everything after as skipped. Since we don't know exactly where
            // the server failed, highlight the "Converting" stage as the
            // most likely culprit.
            const errorAt = stage === 'needs_converter' ? 1 : 1; // converting
            if (idx < errorAt) {
              stateCls = 'text-content-secondary';
              iconCls = 'bg-emerald-50 dark:bg-emerald-950/20 text-emerald-500';
              showCheck = true;
            } else if (idx === errorAt) {
              stateCls = 'text-red-600 dark:text-red-400 font-medium';
              iconCls = 'bg-red-50 dark:bg-red-950/20 text-red-500';
            }
          } else if (isDone) {
            stateCls = 'text-content-secondary';
            iconCls = 'bg-emerald-50 dark:bg-emerald-950/20 text-emerald-500';
            showCheck = true;
          } else if (idx < currentIdx) {
            stateCls = 'text-content-secondary';
            iconCls = 'bg-emerald-50 dark:bg-emerald-950/20 text-emerald-500';
            showCheck = true;
          } else if (idx === currentIdx) {
            stateCls = 'text-content-primary font-medium';
            iconCls = 'bg-oe-blue/10 text-oe-blue';
            showSpinner = true;
          }

          const Icon = s.icon;
          return (
            <li key={s.id} className="flex items-start gap-3">
              <div
                className={clsx(
                  'flex h-7 w-7 shrink-0 items-center justify-center rounded-lg',
                  iconCls,
                )}
              >
                {showCheck ? (
                  <CheckCircle2 size={14} />
                ) : showSpinner ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Icon size={14} />
                )}
              </div>
              <div className="flex-1 min-w-0 pt-0.5">
                <p className={clsx('text-[12px] leading-tight', stateCls)}>
                  {t(s.labelKey, { defaultValue: s.defaultLabel })}
                </p>
                <p className="text-[10px] text-content-quaternary leading-snug mt-0.5">
                  {t(s.hintKey, { defaultValue: s.defaultHint })}
                </p>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
