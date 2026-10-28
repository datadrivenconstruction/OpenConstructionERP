// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * `<RunDock>` — bottom run dock (collapsed 28 px status strip → expanded
 * timeline). Cloned conceptually from the EAC toolbar/dock idiom but kept to
 * a single resizable-free flex panel (Phase 1).
 *
 * Tabs: **Run** (live per-node timeline + progress) and **History**
 * (reverse-chronological run list rendered as-is from the API). No runs yet →
 * `EmptyState`. Screen-reader live region announces progress.
 */
import clsx from 'clsx';
import { ChevronDown, ChevronUp, Inbox } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { DateDisplay, EmptyState, StatusDot } from '@/shared/ui';
import { useTabKeyboardNav } from '@/shared/hooks/useTabKeyboardNav';

import { usePipelineStore } from '../usePipelineStore';
import type { PipelineRunSummary, RunStatus } from '../api';

type RunDockTab = 'run' | 'history';
const RUN_DOCK_TAB_IDS: readonly RunDockTab[] = ['run', 'history'];

/**
 * How many history rows to render at a time. The list endpoint returns runs
 * newest-first; rather than mounting hundreds of rows for a busy pipeline we
 * window the rendered slice client-side and reveal older runs on demand. This
 * keeps the DOM small without changing the API contract.
 */
const HISTORY_PAGE_SIZE = 20;

export interface RunDockProps {
  runs: PipelineRunSummary[];
  runsLoading?: boolean;
  expanded: boolean;
  onToggleExpanded: () => void;
  testId?: string;
}

function statusTone(
  status: RunStatus | null | undefined,
): 'success' | 'error' | 'warning' | 'neutral' {
  if (status === 'done' || status === 'success') return 'success';
  if (status === 'error' || status === 'failed') return 'error';
  // The owning JobRun reports `started`/`pending`; the per-node states
  // report `running`/`queued`. Treat all in-flight states as the same
  // "working" tone so the live dot is amber the whole time, not grey.
  if (
    status === 'running' ||
    status === 'started' ||
    status === 'queued' ||
    status === 'pending' ||
    status === 'paused'
  )
    return 'warning';
  return 'neutral';
}

export function RunDock({
  runs,
  runsLoading = false,
  expanded,
  onToggleExpanded,
  testId,
}: RunDockProps) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<RunDockTab>('run');
  const onTabKeyDown = useTabKeyboardNav<RunDockTab>({
    ids: RUN_DOCK_TAB_IDS,
    activeId: tab,
    onChange: setTab,
    orientation: 'horizontal',
  });
  const run = usePipelineStore((s) => s.run);
  const nodes = usePipelineStore((s) => s.nodes);

  const tone = statusTone(run.status);

  // Client-side windowing of the (newest-first) run history. Collapse back to
  // the first page whenever the underlying list shrinks below what we were
  // showing (e.g. switched pipeline) so we never render a stale slice.
  const [historyVisible, setHistoryVisible] = useState(HISTORY_PAGE_SIZE);
  useEffect(() => {
    if (historyVisible > runs.length && runs.length > HISTORY_PAGE_SIZE) {
      setHistoryVisible(HISTORY_PAGE_SIZE);
    }
  }, [runs.length, historyVisible]);
  const visibleRuns = useMemo(
    () => runs.slice(0, historyVisible),
    [runs, historyVisible],
  );
  const hasMoreRuns = runs.length > visibleRuns.length;

  return (
    <div
      data-testid={testId ?? 'pipeline-run-dock'}
      data-expanded={expanded ? 'true' : 'false'}
      className="flex shrink-0 flex-col border-t border-border bg-surface-primary"
      style={{ height: expanded ? 280 : 32 }}
    >
      {/* Status strip — always visible */}
      <div className="flex h-8 shrink-0 items-center gap-3 px-3 text-xs">
        <button
          type="button"
          onClick={onToggleExpanded}
          aria-expanded={expanded}
          aria-label={
            expanded
              ? t('pipeline.dock.collapse', { defaultValue: 'Collapse run dock' })
              : t('pipeline.dock.expand', { defaultValue: 'Expand run dock' })
          }
          className="flex items-center gap-1.5 rounded px-1 py-0.5 font-medium text-content-secondary hover:bg-surface-secondary"
        >
          {expanded ? (
            <ChevronDown size={14} aria-hidden="true" />
          ) : (
            <ChevronUp size={14} aria-hidden="true" />
          )}
          {t('pipeline.dock.run', { defaultValue: 'Run' })}
        </button>
        <span aria-hidden="true" className="h-4 w-px bg-border" />
        <span
          className="flex items-center gap-1.5 text-content-secondary"
          aria-live="polite"
          data-testid="pipeline-run-status"
        >
          <StatusDot variant={tone} pulse={tone === 'warning'} />
          {run.status
            ? t(`pipeline.runstatus.${run.status}`, {
                defaultValue: String(run.status),
              })
            : t('pipeline.dock.idle', { defaultValue: 'Idle' })}
          {run.status && run.status !== 'done' && run.status !== 'success' && (
            <span className="tabular-nums text-content-tertiary">
              {t('pipeline.dock.progress', {
                defaultValue: '{{pct}}%',
                pct: Math.round(run.progress),
              })}
            </span>
          )}
        </span>
        {(run.status === 'queued' || run.status === 'pending') &&
          run.progress === 0 && (
            <span className="truncate text-content-tertiary">
              {t('pipeline.dock.queued_hint', {
                defaultValue: 'Waiting for a worker to pick up the run…',
              })}
            </span>
          )}
        {run.error && (
          <span className="truncate text-semantic-error">{run.error}</span>
        )}
      </div>

      {expanded && (
        <div className="flex min-h-0 flex-1 flex-col">
          <div
            role="tablist"
            aria-label={t('pipeline.dock.tabs_aria', {
              defaultValue: 'Run dock sections',
            })}
            onKeyDown={onTabKeyDown}
            className="flex shrink-0 gap-1 border-b border-border px-3 py-1.5"
          >
            {RUN_DOCK_TAB_IDS.map((k) => (
              <button
                key={k}
                type="button"
                role="tab"
                id={`pipeline-rundock-tab-${k}`}
                aria-selected={tab === k}
                aria-controls={`pipeline-rundock-panel-${k}`}
                tabIndex={tab === k ? 0 : -1}
                onClick={() => setTab(k)}
                className={clsx(
                  'rounded px-2 py-1 text-xs font-medium',
                  tab === k
                    ? 'bg-oe-blue/10 text-oe-blue'
                    : 'text-content-tertiary hover:text-content-secondary',
                )}
              >
                {k === 'run'
                  ? t('pipeline.dock.tab_run', { defaultValue: 'Run' })
                  : t('pipeline.dock.tab_history', {
                      defaultValue: 'History',
                    })}
              </button>
            ))}
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2">
            {tab === 'run' ? (
              nodes.length === 0 ? (
                <p className="py-6 text-center text-xs text-content-tertiary">
                  {t('pipeline.dock.no_steps', {
                    defaultValue:
                      'Add steps and press Run to watch data flow through your pipeline.',
                  })}
                </p>
              ) : (
                <ol className="space-y-1.5" data-testid="pipeline-run-timeline">
                  {nodes.map((n, i) => {
                    const ns = run.nodeStates[n.id];
                    const nt = statusTone(ns?.status);
                    return (
                      <li
                        key={n.id}
                        className="flex items-center gap-2 text-xs"
                      >
                        <StatusDot variant={nt} />
                        <span className="text-content-tertiary tabular-nums">
                          {i + 1}.
                        </span>
                        <span className="truncate text-content-primary">
                          {n.title}
                        </span>
                        <span className="ms-auto text-content-tertiary">
                          {ns?.status
                            ? t(`pipeline.runstatus.${ns.status}`, {
                                defaultValue: String(ns.status),
                              })
                            : t('pipeline.runstatus.pending', {
                                defaultValue: 'Pending',
                              })}
                        </span>
                        {typeof ns?.took_ms === 'number' && (
                          <span className="tabular-nums text-content-tertiary">
                            {t('pipeline.node.took_ms', {
                              defaultValue: '{{ms}} ms',
                              ms: ns.took_ms,
                            })}
                          </span>
                        )}
                      </li>
                    );
                  })}
                </ol>
              )
            ) : runsLoading ? (
              <p className="py-6 text-center text-xs text-content-tertiary">
                {t('pipeline.dock.loading_history', {
                  defaultValue: 'Loading run history…',
                })}
              </p>
            ) : runs.length === 0 ? (
              <EmptyState
                icon={<Inbox size={22} aria-hidden="true" />}
                title={t('pipeline.dock.no_runs_title', {
                  defaultValue: 'No runs yet',
                })}
                description={t('pipeline.dock.no_runs_desc', {
                  defaultValue:
                    'Press Run to see data flow through your pipeline.',
                })}
              />
            ) : (
              <>
                <ul className="space-y-1" data-testid="pipeline-run-history">
                  {visibleRuns.map((r) => {
                    const rt = statusTone(r.status);
                    const triggerType =
                      r.trigger && typeof r.trigger === 'object'
                        ? r.trigger.type
                        : undefined;
                    return (
                      <li
                        key={r.id}
                        className="flex items-center gap-2 rounded px-2 py-1.5 text-xs hover:bg-surface-secondary"
                      >
                        <StatusDot variant={rt} />
                        <span className="text-content-primary">
                          {triggerType
                            ? t(`pipeline.trigger.${triggerType}`, {
                                defaultValue: triggerType,
                              })
                            : t('pipeline.dock.manual', {
                                defaultValue: 'Manual',
                              })}
                        </span>
                        <span className="text-content-tertiary">
                          {r.status
                            ? t(`pipeline.runstatus.${r.status}`, {
                                defaultValue: String(r.status),
                              })
                            : ''}
                        </span>
                        {r.started_at && (
                          <span className="ms-auto text-content-tertiary">
                            <DateDisplay
                              value={r.started_at}
                              format="relative"
                            />
                          </span>
                        )}
                      </li>
                    );
                  })}
                </ul>
                {hasMoreRuns && (
                  <div className="pt-2 text-center">
                    <button
                      type="button"
                      data-testid="pipeline-run-history-more"
                      onClick={() =>
                        setHistoryVisible((v) => v + HISTORY_PAGE_SIZE)
                      }
                      className="rounded-md border border-border bg-surface-primary px-3 py-1 text-xs font-medium text-content-secondary hover:bg-surface-secondary focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/30"
                    >
                      {t('pipeline.dock.show_more', {
                        defaultValue: 'Show older runs ({{count}} more)',
                        count: runs.length - visibleRuns.length,
                      })}
                    </button>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default RunDock;
