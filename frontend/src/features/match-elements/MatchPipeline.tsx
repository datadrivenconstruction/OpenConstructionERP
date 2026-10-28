// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The visible 7-stage match pipeline. This is the headline UX of
// /match-elements: instead of a single opaque "Run match" button, the
// estimator sees every step — Convert → Load → Schema → Filter → Group
// → Match → Rollup — with status, output preview, and a per-stage
// "Adjust" panel where prompts, LLM provider and knobs are tunable.
//
// Mounted above the classic toolset on the page; collapsing it returns
// the user to the legacy single-shot flow without losing anything.

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ChevronDown,
  ChevronsRight,
  ChevronUp,
  Loader2,
  PlayCircle,
  Workflow,
} from 'lucide-react';

import {
  matchElementsApi,
  type StageListResponse,
  type StageName,
  type StageState,
} from './api';
import { StageCard } from './StageCard';
import { StageAdjustSheet } from './StageAdjustSheet';

interface Props {
  sessionId: string;
}

const ORDER: StageName[] = [
  'convert',
  'load',
  'schema',
  'filter',
  'group',
  'match',
  'rollup',
];

/**
 * Read-only advertisement of the full 7-stage journey, shown on
 * `/match-elements` BEFORE a session exists (the setup wizard hasn't
 * created one yet). It reuses the exact same `ORDER` + i18n labels as
 * the live pipeline so the depth of the process is self-evident the
 * moment the user lands — without mounting a second interactive
 * stepper (the live `MatchPipeline` still owns the single interactive
 * rail once a session is created).
 */
export function PipelinePreview() {
  const { t } = useTranslation();
  return (
    <section className="mt-2 rounded-xl border border-indigo-200/70 dark:border-indigo-800/50 bg-surface-primary shadow-sm">
      <div className="flex items-center gap-2 px-3 py-2.5 border-b border-border bg-gradient-to-r from-indigo-50/70 via-white to-white dark:from-indigo-950/20 dark:via-surface-primary dark:to-surface-primary">
        <span className="w-7 h-7 rounded-lg bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-200 inline-flex items-center justify-center">
          <Workflow className="w-4 h-4" />
        </span>
        <div className="min-w-0">
          <h3 className="text-sm font-bold text-content-primary truncate">
            {t('match_elements.pipeline.title', 'Match pipeline')}
          </h3>
          <p className="text-[11px] text-content-tertiary">
            {t(
              'match_elements.pipeline.subtitle',
              'Seven steps from CAD file to priced BoQ - every step is visible and tunable',
            )}
          </p>
        </div>
      </div>
      <ol className="flex items-center gap-1.5 flex-wrap px-3 py-2 border-b border-border">
        {ORDER.map((name, i) => (
          <li
            key={name}
            className="inline-flex items-center gap-1 text-[10px] font-semibold"
          >
            <span className="px-1.5 py-0.5 rounded border bg-surface-secondary border-border text-content-tertiary">
              {i + 1}. {t(`match_elements.pipeline.step_${name}`, { defaultValue: name })}
            </span>
            {i < ORDER.length - 1 && (
              <ChevronsRight className="w-2.5 h-2.5 opacity-50 text-content-tertiary" />
            )}
          </li>
        ))}
      </ol>
      <p className="px-3 py-2 text-[11px] text-content-tertiary">
        {t('match_elements.pipeline.preview_hint', {
          defaultValue:
            'Pick a project and finish the quick setup below - these seven stages then run here, each visible and tunable.',
        })}
      </p>
    </section>
  );
}

export function MatchPipeline({ sessionId }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [expanded, setExpanded] = useState(true);
  // The pipeline is the headline experience of /match-elements. When it
  // mounts (a session is active) bring it into view so the deep 7-stage
  // flow — not the legacy toolset below it — is what the user lands on.
  const rootRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    rootRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    // Run once per session — re-scrolling on every refetch would be
    // hostile while the user is editing a downstream stage.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);
  const [adjust, setAdjust] = useState<StageState | null>(null);
  const [runningStage, setRunningStage] = useState<StageName | null>(null);
  const [runAll, setRunAll] = useState(false);
  // Surfaces a transport failure (network / 5xx) or a "run all stopped
  // at stage X" notice. A per-stage *stage* error already paints on its
  // card from the refetch; this covers the cases that otherwise fail
  // silently (a thrown fetch leaves every card's status untouched).
  const [pipelineError, setPipelineError] = useState<string | null>(null);

  const stagesQ = useQuery<StageListResponse>({
    queryKey: ['match-stages', sessionId],
    queryFn: () => matchElementsApi.listStages(sessionId),
    refetchInterval: (q) => {
      const data = q.state.data as StageListResponse | undefined;
      const anyRunning = data?.stages.some((s) => s.status === 'running');
      return anyRunning || runAll ? 1200 : false;
    },
  });

  const stages = useMemo(() => {
    const byName = new Map(
      (stagesQ.data?.stages ?? []).map((s) => [s.stage_name, s]),
    );
    return ORDER.map((n) => byName.get(n)).filter(Boolean) as StageState[];
  }, [stagesQ.data]);

  const titleOf = (name: StageName) =>
    stages.find((s) => s.stage_name === name)?.title ?? name;

  const runOne = useMutation({
    mutationFn: (name: StageName) =>
      matchElementsApi.runStage(sessionId, name),
    onMutate: (name) => {
      setPipelineError(null);
      setRunningStage(name);
    },
    onError: (err: Error) => {
      // Transport failure — the stage card status never changed, so
      // without this the click would look like it did nothing.
      setPipelineError(
        err?.message ??
          t('match_elements.pipeline.run_failed', 'Stage run failed'),
      );
    },
    onSettled: () => {
      setRunningStage(null);
      qc.invalidateQueries({ queryKey: ['match-stages', sessionId] });
      qc.invalidateQueries({ queryKey: ['match-groups', sessionId] });
      qc.invalidateQueries({ queryKey: ['match-session', sessionId] });
    },
  });

  // Sequential full run convert → rollup. Stops on the first error so
  // the user can inspect + fix that stage rather than cascading garbage.
  //
  // IMPORTANT: every stage is *unconditionally* re-executed here. An
  // earlier shortcut skipped any stage already marked `done`, which
  // looked fine — until you realise the backend marks downstream stages
  // `stale` whenever the user adjusts an upstream input (see
  // pipeline.run_stage: it walks STAGE_NAMES[idx+1:] and downgrades
  // done→stale). Treating a stale stage as "already done" makes
  // "Run all" silently feed pre-edit outputs into the rest of the
  // pipeline. We only ever break the loop on a transport throw or a
  // backend-reported error.
  const runEntirePipeline = async () => {
    setRunAll(true);
    setPipelineError(null);
    try {
      for (const name of ORDER) {
        setRunningStage(name);
        const res = await matchElementsApi.runStage(sessionId, name);
        qc.invalidateQueries({ queryKey: ['match-stages', sessionId] });
        if (res.status === 'error') {
          setPipelineError(
            t('match_elements.pipeline.run_all_stopped', {
              defaultValue: 'Stopped at “{{stage}}” - fix that step, then run again.',
              stage: titleOf(name),
            }),
          );
          break;
        }
      }
    } catch (err) {
      setPipelineError(
        err instanceof Error
          ? err.message
          : t('match_elements.pipeline.run_failed', 'Stage run failed'),
      );
    } finally {
      setRunningStage(null);
      setRunAll(false);
      qc.invalidateQueries({ queryKey: ['match-stages', sessionId] });
      qc.invalidateQueries({ queryKey: ['match-groups', sessionId] });
      qc.invalidateQueries({ queryKey: ['match-session', sessionId] });
    }
  };

  const doneCount = stages.filter((s) => s.status === 'done').length;
  // One stage at a time — concurrent runs would race the same session
  // rows in the DB (load/group both call rebuild_groups). Every run
  // trigger is gated on this.
  const anyRunning = stages.some((s) => s.status === 'running');
  const busy = runAll || runningStage != null || anyRunning;

  return (
    <section
      ref={rootRef}
      className="mt-2 rounded-xl border border-indigo-200/70 dark:border-indigo-800/50 bg-surface-primary shadow-sm scroll-mt-20"
    >
      {/* Header — this is the headline deep wizard of /match-elements,
          not a collapsible afterthought. The 7-step preview strip below
          makes the full Convert → … → Rollup journey self-evident even
          before the user expands a single stage. */}
      <div className="flex items-center justify-between gap-3 px-3 py-2.5 border-b border-border bg-gradient-to-r from-indigo-50/70 via-white to-white dark:from-indigo-950/20 dark:via-surface-primary dark:to-surface-primary">
        <div className="flex items-center gap-2 min-w-0">
          <span className="w-7 h-7 rounded-lg bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-200 inline-flex items-center justify-center">
            <Workflow className="w-4 h-4" />
          </span>
          <div className="min-w-0">
            <h3 className="text-sm font-bold text-content-primary truncate">
              {t('match_elements.pipeline.title', 'Match pipeline')}
            </h3>
            <p className="text-[11px] text-content-tertiary">
              {t(
                'match_elements.pipeline.subtitle',
                'Seven steps from CAD file to priced BoQ - every step is visible and tunable',
              )}
              {stages.length > 0 && (
                <span className="ml-1.5 font-semibold text-content-secondary">
                  {doneCount}/{stages.length}{' '}
                  {t('match_elements.pipeline.done_suffix', 'done')}
                </span>
              )}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={runEntirePipeline}
            disabled={busy}
            title={
              busy
                ? t(
                    'match_elements.pipeline.busy_hint',
                    'A stage is running - wait for it to finish before starting another.',
                  )
                : undefined
            }
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-semibold bg-oe-blue text-white hover:opacity-90 disabled:opacity-50"
          >
            {runAll ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <PlayCircle className="w-3.5 h-3.5" />
            )}
            {runAll
              ? t('match_elements.pipeline.running_all', 'Running all…')
              : t('match_elements.pipeline.run_all', 'Run all stages')}
          </button>
          <button
            onClick={() => setExpanded((v) => !v)}
            className="p-1.5 rounded-lg hover:bg-surface-secondary text-content-tertiary"
            aria-label={expanded ? 'Collapse' : 'Expand'}
          >
            {expanded ? (
              <ChevronUp className="w-4 h-4" />
            ) : (
              <ChevronDown className="w-4 h-4" />
            )}
          </button>
        </div>
      </div>

      {/* 7-step preview strip — always visible (even collapsed) so the
          full depth of the journey is advertised at a glance. This is
          the explanatory affordance the old "Open the pipeline" entry
          card carried; folding it into the pipeline header keeps it on
          ONE rail instead of as a separate competing card. */}
      <ol className="flex items-center gap-1.5 flex-wrap px-3 py-2 border-b border-border">
        {ORDER.map((name, i) => {
          const st = stages.find((s) => s.stage_name === name);
          const status = st?.status ?? 'pending';
          return (
            <li
              key={name}
              className="inline-flex items-center gap-1 text-[10px] font-semibold"
            >
              <span
                className={`px-1.5 py-0.5 rounded border ${
                  status === 'done'
                    ? 'bg-emerald-50 dark:bg-emerald-950/30 border-emerald-300/70 dark:border-emerald-700/50 text-emerald-800 dark:text-emerald-200'
                    : status === 'running'
                      ? 'bg-blue-50 dark:bg-blue-950/30 border-blue-300/70 dark:border-blue-700/50 text-blue-800 dark:text-blue-200'
                      : status === 'error'
                        ? 'bg-rose-50 dark:bg-rose-950/30 border-rose-300/70 dark:border-rose-700/50 text-rose-800 dark:text-rose-200'
                        : 'bg-surface-secondary border-border text-content-tertiary'
                }`}
              >
                {i + 1}.{' '}
                {st?.title ??
                  t(`match_elements.pipeline.step_${name}`, { defaultValue: name })}
              </span>
              {i < ORDER.length - 1 && (
                <ChevronsRight className="w-2.5 h-2.5 opacity-50 text-content-tertiary" />
              )}
            </li>
          );
        })}
      </ol>

      {/* Body */}
      {expanded && (
        <div className="px-3 py-3">
          {stagesQ.isLoading ? (
            <div className="flex items-center gap-2 text-xs text-content-tertiary py-6 justify-center">
              <Loader2 className="w-4 h-4 animate-spin" />
              {t('match_elements.pipeline.loading', 'Loading pipeline…')}
            </div>
          ) : stagesQ.isError ? (
            <div className="text-xs text-rose-600 dark:text-rose-400 py-4 text-center">
              {(stagesQ.error as Error)?.message ??
                t(
                  'match_elements.pipeline.load_failed',
                  'Could not load the pipeline.',
                )}
            </div>
          ) : (
            <div>
              {pipelineError && (
                <div
                  role="alert"
                  className="mb-3 flex items-start justify-between gap-2 text-xs text-rose-700 dark:text-rose-300 bg-rose-50 dark:bg-rose-950/20 border border-rose-200/60 dark:border-rose-800/40 rounded-lg px-3 py-2"
                >
                  <span className="break-words">{pipelineError}</span>
                  <button
                    type="button"
                    onClick={() => setPipelineError(null)}
                    className="shrink-0 underline hover:no-underline"
                  >
                    {t('common.dismiss', 'Dismiss')}
                  </button>
                </div>
              )}
              {stages.map((s, i) => (
                <StageCard
                  key={s.stage_name}
                  stage={s}
                  index={i}
                  isLast={i === stages.length - 1}
                  running={runningStage === s.stage_name || s.status === 'running'}
                  busy={busy}
                  onRun={() => runOne.mutate(s.stage_name)}
                  onAdjust={() => setAdjust(s)}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {adjust && (
        <StageAdjustSheet
          // Key by stage so switching the Adjust target gives a fresh
          // instance — otherwise the per-stage knob state (seeded once
          // via useState initialisers) leaks across stages.
          key={adjust.stage_name}
          sessionId={sessionId}
          stage={adjust}
          busy={busy}
          onClose={() => setAdjust(null)}
          onRan={() => setAdjust(null)}
        />
      )}
    </section>
  );
}
