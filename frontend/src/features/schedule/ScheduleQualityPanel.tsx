// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
//
// Claims-grade schedule quality panel (T1.2). A read-only forensic view of a
// base schedule driven by POST /v1/schedule-advanced/{scheduleId}/schedule-quality:
//   - headline stats (project finish work-day, # activities, # critical)
//   - the Longest Path (the driving chain, ordered activity ids + length)
//   - the ranked float-path decomposition (index, activities, length, relative float)
//   - the scheduling QA log (code / severity / message, severity-coloured)
//   - per-activity explain strings (why-critical / float reasoning)
//
// Activity ids arrive as raw UUIDs on the wire; an optional ``activitiesById``
// name map (the caller already holds the Gantt rows) lets us render readable
// labels instead. Nothing here is written back to the schedule.

import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  ShieldCheck,
  Route,
  ListChecks,
  AlertTriangle,
  AlertCircle,
  Info,
  Loader2,
} from 'lucide-react';

import { Button, Card, Badge, EmptyState, RecoveryCard, SkeletonTable } from '@/shared/ui';
import {
  scheduleQuality,
  type ScheduleQuality,
  type QAFinding,
} from '@/features/schedule-advanced/api';

interface ScheduleQualityPanelProps {
  scheduleId: string;
  /** Optional id -> display name map so paths/findings show names, not UUIDs. */
  activitiesById?: Record<string, string>;
}

/** Severity buckets. Backend emits a numeric severity (higher = worse). */
type SeverityTone = 'error' | 'warning' | 'info';

function severityTone(sev: number): SeverityTone {
  if (sev >= 3) return 'error';
  if (sev === 2) return 'warning';
  return 'info';
}

const SEVERITY_BADGE: Record<SeverityTone, 'error' | 'warning' | 'neutral'> = {
  error: 'error',
  warning: 'warning',
  info: 'neutral',
};

export function ScheduleQualityPanel({
  scheduleId,
  activitiesById,
}: ScheduleQualityPanelProps) {
  const { t } = useTranslation();

  const q = useQuery<ScheduleQuality>({
    queryKey: ['schedule', 'quality', scheduleId],
    queryFn: () => scheduleQuality(scheduleId),
    enabled: !!scheduleId,
    // Forensic snapshot; cheap to keep around but recompute on demand.
    staleTime: 30_000,
  });

  const nameFor = useMemo(
    () => (id: string) => activitiesById?.[id] ?? id,
    [activitiesById],
  );

  if (q.isLoading) {
    return (
      <Card padding="md" data-testid="schedule-quality-loading">
        <div className="mb-3 flex items-center gap-2 text-sm text-content-secondary">
          <Loader2 size={14} className="animate-spin" />
          {t('schedule.quality.running', {
            defaultValue: 'Analysing the schedule network...',
          })}
        </div>
        <SkeletonTable rows={5} columns={4} />
      </Card>
    );
  }

  if (q.isError) {
    return (
      <Card padding="md">
        <RecoveryCard error={q.error} onRetry={() => q.refetch()} />
      </Card>
    );
  }

  const data = q.data;
  if (!data) return null;

  if (data.num_activities === 0) {
    return (
      <Card padding="md">
        <EmptyState
          icon={<ShieldCheck size={24} strokeWidth={1.5} />}
          title={t('schedule.quality.empty', {
            defaultValue: 'Nothing to analyse yet',
          })}
          description={t('schedule.quality.empty_desc', {
            defaultValue:
              'Add activities and dependencies to this schedule, then run the analysis to see the Longest Path, float paths and a scheduling quality log.',
          })}
        />
      </Card>
    );
  }

  // Sort the QA log worst-first so the most serious findings lead.
  const qaSorted = [...data.qa_log].sort((a, b) => b.severity - a.severity);
  const qaCounts = qaSorted.reduce(
    (acc, f) => {
      acc[severityTone(f.severity)] += 1;
      return acc;
    },
    { error: 0, warning: 0, info: 0 } as Record<SeverityTone, number>,
  );

  return (
    <div className="space-y-4" data-testid="schedule-quality-panel">
      {/* ── Headline stats ─────────────────────────────────────────── */}
      <Card padding="md">
        <div className="mb-3 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <ShieldCheck size={16} className="text-content-secondary" />
            <h3 className="text-sm font-semibold text-content-primary">
              {t('schedule.quality.title', { defaultValue: 'Schedule quality' })}
            </h3>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => q.refetch()}
            loading={q.isFetching}
          >
            {t('schedule.quality.recompute', { defaultValue: 'Recompute' })}
          </Button>
        </div>
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat
            label={t('schedule.quality.project_finish', {
              defaultValue: 'Project finish (work-day)',
            })}
            value={String(data.project_finish_workday)}
          />
          <Stat
            label={t('schedule.quality.activities', { defaultValue: 'Activities' })}
            value={String(data.num_activities)}
          />
          <Stat
            label={t('schedule.quality.critical', { defaultValue: 'Critical' })}
            value={String(data.num_critical)}
            tone={data.num_critical > 0 ? 'warning' : 'neutral'}
          />
          <Stat
            label={t('schedule.quality.longest_path_len', {
              defaultValue: 'Longest Path (days)',
            })}
            value={String(data.longest_path_length_days)}
          />
        </dl>
      </Card>

      {/* ── Longest Path ───────────────────────────────────────────── */}
      <Card padding="md">
        <div className="mb-3 flex items-center gap-2">
          <Route size={16} className="text-content-secondary" />
          <h3 className="text-sm font-semibold text-content-primary">
            {t('schedule.quality.longest_path', { defaultValue: 'Longest Path' })}
          </h3>
          <Badge variant="blue">
            {t('schedule.quality.length_days', {
              defaultValue: '{{count}} days',
              count: data.longest_path_length_days,
            })}
          </Badge>
        </div>
        {data.longest_path.length === 0 ? (
          <p className="text-sm text-content-tertiary">
            {t('schedule.quality.longest_path_none', {
              defaultValue: 'No driving path could be derived from the current logic.',
            })}
          </p>
        ) : (
          <ol className="flex flex-wrap items-center gap-1.5" data-testid="quality-longest-path">
            {data.longest_path.map((id, i) => (
              <li key={`${id}-${i}`} className="flex items-center gap-1.5">
                <span
                  className="rounded-md border border-oe-blue/30 bg-oe-blue-subtle/40 px-2 py-1 text-xs font-medium text-content-primary"
                  title={id}
                >
                  {nameFor(id)}
                </span>
                {i < data.longest_path.length - 1 && (
                  <span className="text-content-tertiary" aria-hidden>
                    &rarr;
                  </span>
                )}
              </li>
            ))}
          </ol>
        )}
      </Card>

      {/* ── Ranked float paths ─────────────────────────────────────── */}
      <Card padding="none">
        <div className="flex items-center gap-2 border-b border-border-light px-4 py-3">
          <Route size={16} className="text-content-secondary" />
          <h3 className="text-sm font-semibold text-content-primary">
            {t('schedule.quality.float_paths', { defaultValue: 'Float paths' })}
          </h3>
          <span className="text-xs text-content-tertiary">
            {t('schedule.quality.float_paths_hint', {
              defaultValue: 'Ranked by total float - path 1 is the driving path.',
            })}
          </span>
        </div>
        {data.float_paths.length === 0 ? (
          <div className="px-4 py-6 text-sm text-content-tertiary">
            {t('schedule.quality.float_paths_none', {
              defaultValue: 'No float paths to show.',
            })}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface-secondary text-2xs uppercase tracking-wide text-content-tertiary">
                <tr>
                  <th className="px-4 py-2 text-left">{t('schedule.quality.path', { defaultValue: 'Path' })}</th>
                  <th className="px-4 py-2 text-left">{t('schedule.quality.activities_col', { defaultValue: 'Activities' })}</th>
                  <th className="px-4 py-2 text-right">{t('schedule.quality.length', { defaultValue: 'Length (d)' })}</th>
                  <th className="px-4 py-2 text-right">{t('schedule.quality.relative_float', { defaultValue: 'Relative float (d)' })}</th>
                </tr>
              </thead>
              <tbody>
                {data.float_paths.map((p) => (
                  <tr key={p.index} className="border-t border-border-light align-top">
                    <td className="px-4 py-2">
                      <span className="flex items-center gap-2">
                        <span className="font-mono tabular-nums text-content-secondary">
                          {p.index + 1}
                        </span>
                        {p.relative_float === 0 && (
                          <Badge variant="warning">
                            {t('schedule.quality.driving', { defaultValue: 'Driving' })}
                          </Badge>
                        )}
                      </span>
                    </td>
                    <td className="px-4 py-2">
                      <span className="flex flex-wrap gap-1">
                        {p.activity_ids.map((id, i) => (
                          <span
                            key={`${id}-${i}`}
                            className="rounded bg-surface-secondary px-1.5 py-0.5 text-2xs text-content-secondary"
                            title={id}
                          >
                            {nameFor(id)}
                          </span>
                        ))}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-right font-mono tabular-nums">{p.length_days}</td>
                    <td className="px-4 py-2 text-right font-mono tabular-nums">{p.relative_float}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* ── Scheduling QA log ──────────────────────────────────────── */}
      <Card padding="none">
        <div className="flex flex-wrap items-center gap-2 border-b border-border-light px-4 py-3">
          <ListChecks size={16} className="text-content-secondary" />
          <h3 className="text-sm font-semibold text-content-primary">
            {t('schedule.quality.qa_log', { defaultValue: 'Scheduling QA log' })}
          </h3>
          <div className="ml-auto flex items-center gap-2 text-2xs">
            {qaCounts.error > 0 && (
              <Badge variant="error" dot>
                {t('schedule.quality.errors', { defaultValue: '{{count}} errors', count: qaCounts.error })}
              </Badge>
            )}
            {qaCounts.warning > 0 && (
              <Badge variant="warning" dot>
                {t('schedule.quality.warnings', { defaultValue: '{{count}} warnings', count: qaCounts.warning })}
              </Badge>
            )}
            {qaCounts.info > 0 && (
              <Badge variant="neutral" dot>
                {t('schedule.quality.infos', { defaultValue: '{{count}} info', count: qaCounts.info })}
              </Badge>
            )}
          </div>
        </div>
        {qaSorted.length === 0 ? (
          <div className="flex items-center gap-2 px-4 py-6 text-sm text-semantic-success">
            <ShieldCheck size={16} />
            {t('schedule.quality.qa_clean', {
              defaultValue: 'No scheduling-quality issues found. The logic is clean.',
            })}
          </div>
        ) : (
          <ul className="divide-y divide-border-light" data-testid="quality-qa-log">
            {qaSorted.map((f, i) => (
              <QARow key={`${f.code}-${f.activity_id}-${i}`} finding={f} nameFor={nameFor} />
            ))}
          </ul>
        )}
      </Card>

      {/* ── Per-activity explanations ──────────────────────────────── */}
      {data.explanations.length > 0 && (
        <Card padding="none">
          <div className="border-b border-border-light px-4 py-3">
            <h3 className="text-sm font-semibold text-content-primary">
              {t('schedule.quality.explanations', {
                defaultValue: 'Activity explanations',
              })}
            </h3>
          </div>
          <ul className="divide-y divide-border-light">
            {data.explanations.map((e) => (
              <li key={e.activity_id} className="px-4 py-3">
                <p className="text-sm font-medium text-content-primary" title={e.activity_id}>
                  {nameFor(e.activity_id)}
                </p>
                {e.why_critical && (
                  <p className="mt-1 text-xs text-content-secondary">{e.why_critical}</p>
                )}
                {e.float_explanation && (
                  <p className="mt-0.5 text-xs text-content-tertiary">{e.float_explanation}</p>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

/* ── helpers ─────────────────────────────────────────────────────────── */

function Stat({
  label,
  value,
  tone = 'neutral',
}: {
  label: string;
  value: string;
  tone?: 'neutral' | 'warning';
}) {
  return (
    <div className="rounded-lg border border-border-light bg-surface-secondary/40 px-3 py-2">
      <dt className="text-2xs uppercase tracking-wide text-content-tertiary">{label}</dt>
      <dd
        className={
          'mt-0.5 text-xl font-bold tabular-nums ' +
          (tone === 'warning' ? 'text-semantic-warning' : 'text-content-primary')
        }
      >
        {value}
      </dd>
    </div>
  );
}

function QARow({
  finding,
  nameFor,
}: {
  finding: QAFinding;
  nameFor: (id: string) => string;
}) {
  const { t } = useTranslation();
  const tone = severityTone(finding.severity);
  const Icon = tone === 'error' ? AlertCircle : tone === 'warning' ? AlertTriangle : Info;
  const iconCls =
    tone === 'error'
      ? 'text-semantic-error'
      : tone === 'warning'
        ? 'text-semantic-warning'
        : 'text-content-tertiary';
  return (
    <li className="flex items-start gap-3 px-4 py-2.5">
      <Icon size={15} className={'mt-0.5 shrink-0 ' + iconCls} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={SEVERITY_BADGE[tone]}>{finding.code}</Badge>
          <span className="truncate text-xs text-content-tertiary" title={finding.activity_id}>
            {nameFor(finding.activity_id)}
          </span>
        </div>
        <p className="mt-0.5 text-sm text-content-secondary">
          {finding.message ||
            t('schedule.quality.no_message', { defaultValue: 'No detail provided.' })}
        </p>
      </div>
    </li>
  );
}

export default ScheduleQualityPanel;
