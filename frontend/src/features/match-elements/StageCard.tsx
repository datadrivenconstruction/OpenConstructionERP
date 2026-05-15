// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One step in the visible match pipeline timeline. Renders the stage
// number, title, plain-language subtitle, status pill, a compact output
// preview, and the Run / Re-run + Adjust controls. The whole point is
// that an estimator can look at this and understand exactly what the
// system did and why — no black box.

import { useTranslation } from 'react-i18next';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Circle,
  Loader2,
  Play,
  RefreshCw,
  Settings2,
  Sparkles,
  XCircle,
} from 'lucide-react';

import type { StageState, StageStatus } from './api';

interface Props {
  stage: StageState;
  index: number;
  isLast: boolean;
  running: boolean;
  /** True when ANY stage in the pipeline is running. Run/Re-run is
   *  gated on this so two stages can't race the same session. */
  busy: boolean;
  onRun: () => void;
  onAdjust: () => void;
}

function StatusPill({ status }: { status: StageStatus }) {
  const { t } = useTranslation();
  const map: Record<
    StageStatus,
    { cls: string; icon: React.ReactNode; label: string }
  > = {
    pending: {
      cls: 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300',
      icon: <Circle className="w-3 h-3" />,
      label: t('match_elements.pipeline.status_pending', 'Not run'),
    },
    running: {
      cls: 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300',
      icon: <Loader2 className="w-3 h-3 animate-spin" />,
      label: t('match_elements.pipeline.status_running', 'Running'),
    },
    done: {
      cls: 'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300',
      icon: <CheckCircle2 className="w-3 h-3" />,
      label: t('match_elements.pipeline.status_done', 'Done'),
    },
    error: {
      cls: 'bg-rose-100 dark:bg-rose-900/40 text-rose-700 dark:text-rose-300',
      icon: <XCircle className="w-3 h-3" />,
      label: t('match_elements.pipeline.status_error', 'Error'),
    },
    stale: {
      cls: 'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300',
      icon: <AlertTriangle className="w-3 h-3" />,
      label: t('match_elements.pipeline.status_stale', 'Needs re-run'),
    },
    skipped: {
      cls: 'bg-slate-100 dark:bg-slate-800 text-slate-500',
      icon: <ChevronRight className="w-3 h-3" />,
      label: t('match_elements.pipeline.status_skipped', 'Skipped'),
    },
  };
  const s = map[status];
  return (
    <span
      className={
        'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold ' +
        s.cls
      }
    >
      {s.icon}
      {s.label}
    </span>
  );
}

/** Render the small metrics the stage runner stashed on ``output`` as a
 *  human-readable strip. ``summary`` is always the headline; the rest
 *  are shown as chips so the user can verify counts at a glance. */
function OutputPreview({ output }: { output: Record<string, unknown> }) {
  const summary =
    typeof output.summary === 'string' ? output.summary : null;
  const chips: { k: string; v: string }[] = [];
  for (const [k, v] of Object.entries(output)) {
    if (k === 'summary' || k === 'samples' || k === 'models') continue;
    if (v == null) continue;
    if (typeof v === 'object') {
      // Flatten one level (status breakdowns etc.).
      for (const [kk, vv] of Object.entries(v as Record<string, unknown>)) {
        if (vv == null || typeof vv === 'object') continue;
        chips.push({ k: kk, v: String(vv) });
      }
      continue;
    }
    chips.push({ k, v: String(v) });
  }
  if (!summary && chips.length === 0) return null;
  return (
    <div className="mt-1.5 space-y-1.5">
      {summary && (
        <p className="text-xs text-content-secondary">{summary}</p>
      )}
      {chips.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {chips.slice(0, 8).map((c) => (
            <span
              key={c.k}
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] bg-surface-secondary border border-border text-content-tertiary"
            >
              <span className="font-semibold text-content-secondary">
                {c.k}
              </span>
              {c.v}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export function StageCard({
  stage,
  index,
  isLast,
  running,
  busy,
  onRun,
  onAdjust,
}: Props) {
  const { t } = useTranslation();
  const isRunning = running || stage.status === 'running';
  const done = stage.status === 'done';
  const numberCls = done
    ? 'bg-emerald-500 text-white'
    : stage.status === 'error'
      ? 'bg-rose-500 text-white'
      : stage.status === 'stale'
        ? 'bg-amber-500 text-white'
        : isRunning
          ? 'bg-blue-500 text-white'
          : 'bg-slate-200 dark:bg-slate-700 text-content-secondary';

  return (
    <div className="flex gap-3">
      {/* Timeline rail */}
      <div className="flex flex-col items-center">
        <div
          className={
            'w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold shrink-0 transition-colors ' +
            numberCls
          }
        >
          {index + 1}
        </div>
        {!isLast && (
          <div className="w-px flex-1 my-1 bg-border" aria-hidden />
        )}
      </div>

      {/* Card */}
      <div className="flex-1 pb-3 min-w-0">
        <div
          className={
            'rounded-xl border bg-surface-primary p-3 shadow-sm transition-colors ' +
            (stage.status === 'stale'
              ? 'border-amber-300/60 dark:border-amber-800/40'
              : stage.status === 'error'
                ? 'border-rose-300/60 dark:border-rose-800/40'
                : 'border-border')
          }
        >
          <div className="flex items-start justify-between gap-2 flex-wrap">
            <div className="min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <h4 className="text-sm font-bold text-content-primary">
                  {stage.title}
                </h4>
                {stage.uses_llm && (
                  <span
                    className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-indigo-50 dark:bg-indigo-950/30 text-indigo-700 dark:text-indigo-300 border border-indigo-200/60 dark:border-indigo-800/40"
                    title={t(
                      'match_elements.pipeline.llm_tunable',
                      'LLM-augmented — prompt is editable',
                    )}
                  >
                    <Sparkles className="w-2.5 h-2.5" />
                    {t('match_elements.pipeline.llm_badge', 'LLM')}
                  </span>
                )}
                <StatusPill status={stage.status} />
                {stage.took_ms != null && stage.status === 'done' && (
                  <span className="text-[10px] text-content-tertiary">
                    {stage.took_ms < 1000
                      ? `${stage.took_ms} ms`
                      : `${(stage.took_ms / 1000).toFixed(1)} s`}
                  </span>
                )}
              </div>
              <p className="text-xs text-content-secondary mt-0.5">
                {stage.subtitle}
              </p>
            </div>

            <div className="flex items-center gap-1.5 shrink-0">
              <button
                onClick={onAdjust}
                className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-medium border border-border text-content-secondary hover:bg-surface-secondary"
              >
                <Settings2 className="w-3 h-3" />
                {t('match_elements.pipeline.adjust', 'Adjust')}
              </button>
              <button
                onClick={onRun}
                disabled={busy}
                title={
                  busy && !isRunning
                    ? t(
                        'match_elements.pipeline.busy_hint',
                        'A stage is running — wait for it to finish before starting another.',
                      )
                    : undefined
                }
                className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-semibold bg-oe-blue text-white hover:opacity-90 disabled:opacity-50"
              >
                {isRunning ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : done || stage.status === 'stale' ? (
                  <RefreshCw className="w-3 h-3" />
                ) : (
                  <Play className="w-3 h-3" />
                )}
                {done || stage.status === 'stale'
                  ? t('match_elements.pipeline.rerun', 'Re-run')
                  : t('match_elements.pipeline.run', 'Run')}
              </button>
            </div>
          </div>

          {/* Explainer — always visible so the step is self-documenting */}
          <p className="text-[11px] text-content-tertiary leading-relaxed mt-2">
            {stage.explainer}
          </p>

          {/* Output preview */}
          {stage.status === 'done' && (
            <OutputPreview output={stage.output} />
          )}

          {/* Error */}
          {stage.status === 'error' && stage.error && (
            <div className="mt-2 text-xs text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-950/20 border border-rose-200/60 dark:border-rose-800/40 rounded-lg px-2.5 py-1.5 break-words">
              {stage.error}
            </div>
          )}

          {stage.status === 'stale' && (
            <div className="mt-2 text-[11px] text-amber-700 dark:text-amber-300">
              {t(
                'match_elements.pipeline.stale_hint',
                'An earlier stage changed — re-run this step to refresh its output.',
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
