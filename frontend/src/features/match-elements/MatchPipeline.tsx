// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
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

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ChevronDown,
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

export function MatchPipeline({ sessionId }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [expanded, setExpanded] = useState(true);
  const [adjust, setAdjust] = useState<StageState | null>(null);
  const [runningStage, setRunningStage] = useState<StageName | null>(null);
  const [runAll, setRunAll] = useState(false);

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

  const runOne = useMutation({
    mutationFn: (name: StageName) =>
      matchElementsApi.runStage(sessionId, name),
    onMutate: (name) => setRunningStage(name),
    onSettled: () => {
      setRunningStage(null);
      qc.invalidateQueries({ queryKey: ['match-stages', sessionId] });
      qc.invalidateQueries({ queryKey: ['match-groups', sessionId] });
      qc.invalidateQueries({ queryKey: ['match-session', sessionId] });
    },
  });

  // Sequential full run convert → rollup. Stops on the first error so
  // the user can inspect + fix that stage rather than cascading garbage.
  const runEntirePipeline = async () => {
    setRunAll(true);
    try {
      for (const name of ORDER) {
        setRunningStage(name);
        const res = await matchElementsApi.runStage(sessionId, name);
        qc.invalidateQueries({ queryKey: ['match-stages', sessionId] });
        if (res.status === 'error') break;
      }
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
    <section className="mt-2 rounded-xl border border-border bg-surface-primary shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 px-3 py-2.5 border-b border-border">
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
                'Seven steps from CAD file to priced BoQ — every step is visible and tunable',
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
                    'A stage is running — wait for it to finish before starting another.',
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
