// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Two readings of how the forecast moved between snapshots.
//
// "Step by step" walks from one total to the other, the largest move first,
// each step with its cause and the reason recorded for it, so the question
// "why is it 120 000 more than last month?" is answered to the cent.
// "Side by side" puts the snapshots next to each other, one column each, the
// way a monthly cost report is laid out.
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';

import { Skeleton } from '@/shared/ui';
import { TabBar } from '@/shared/ui/TabBar';
import { fmtCurrency, fmtDate, fmtNumber } from '@/shared/lib/formatters';
import { getErrorMessage } from '@/shared/lib/api';
import { costControlApi, num, type ComparisonColumn, type SnapshotSummary } from './api';
import { causeLabel, evidenceKindLabel, snapshotStatusLabel, stageLabel } from './labels';

const LIVE = 'live';

function columnTitle(t: ReturnType<typeof useTranslation>['t'], c: ComparisonColumn): string {
  if (c.status === 'live') return t('cost_control.compare_today', { defaultValue: 'Today' });
  return c.label || stageLabel(t, c.stage);
}

function rowName(t: ReturnType<typeof useTranslation>['t'], kind: string, code: string, description: string): string {
  if (kind === 'unassigned') return t('cost_control.row_unassigned', { defaultValue: 'Not on any cost line' });
  if (kind === 'changes_without_contract')
    return t('cost_control.row_loose_changes', { defaultValue: 'Approved changes not on a contract' });
  return `${code} ${description}`.trim();
}

function signed(value: string, currency: string): string {
  return `${num(value) > 0 ? '+' : ''}${fmtCurrency(value, currency)}`;
}

function Ladder({
  projectId,
  frozen,
  currency,
}: {
  projectId: string;
  frozen: SnapshotSummary[];
  currency: string;
}) {
  const { t } = useTranslation();
  const latest = frozen[frozen.length - 1];
  const [start, setStart] = useState<string>(latest?.id ?? '');
  const [end, setEnd] = useState<string>(LIVE);
  const startIndex = frozen.findIndex((s) => s.id === start);
  const ends = frozen.slice(startIndex + 1);
  const ladder = useQuery({
    queryKey: ['cost-control', 'ladder', projectId, start, end],
    queryFn: () => costControlApi.ladder(projectId, start, end),
    enabled: !!start,
  });
  const data = ladder.data;
  const biggest = useMemo(
    () => Math.max(1, ...(data?.steps ?? []).map((s) => Math.abs(num(s.delta))), Math.abs(num(data?.other))),
    [data],
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <label className="flex items-center gap-2">
          <span className="text-content-secondary">{t('cost_control.compare_from', { defaultValue: 'From' })}</span>
          <select
            className="h-8 rounded-lg border border-border bg-surface-primary px-2"
            value={start}
            onChange={(e) => {
              setStart(e.target.value);
              setEnd(LIVE);
            }}
          >
            {frozen.map((s) => (
              <option key={s.id} value={s.id}>
                {fmtDate(s.taken_on)} · {s.label || stageLabel(t, s.stage)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2">
          <span className="text-content-secondary">{t('cost_control.compare_to', { defaultValue: 'to' })}</span>
          <select
            className="h-8 rounded-lg border border-border bg-surface-primary px-2"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
          >
            {ends.map((s) => (
              <option key={s.id} value={s.id}>
                {fmtDate(s.taken_on)} · {s.label || stageLabel(t, s.stage)}
              </option>
            ))}
            <option value={LIVE}>{t('cost_control.compare_today', { defaultValue: 'Today' })}</option>
          </select>
        </label>
      </div>
      {ladder.isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : ladder.error || !data ? (
        <p className="text-sm text-semantic-error">{getErrorMessage(ladder.error)}</p>
      ) : (
        <ol className="divide-y divide-border-light text-sm">
          <li className="flex items-center justify-between py-2 font-medium text-content-primary">
            <span>
              {t('cost_control.ladder_start', {
                defaultValue: 'Forecast on {{date}}',
                date: fmtDate(data.start_column.taken_on),
              })}
            </span>
            <span className="tabular-nums">{fmtCurrency(data.start, currency)}</span>
          </li>
          {data.steps.length === 0 && (
            <li className="py-2 text-content-tertiary">
              {t('cost_control.ladder_none', { defaultValue: 'No line moved between the two.' })}
            </li>
          )}
          {data.steps.map((s) => {
            const up = num(s.delta) > 0;
            return (
              <li key={s.key} className="py-2">
                <div className="flex items-center gap-3">
                  <span className="min-w-0 flex-1 truncate text-content-primary">
                    {rowName(t, s.kind, s.code, s.description)}
                  </span>
                  <span className="shrink-0 rounded bg-surface-secondary px-1.5 py-px text-2xs text-content-tertiary">
                    {causeLabel(t, s.cause)}
                  </span>
                  <span className="hidden w-28 shrink-0 sm:block" aria-hidden>
                    <span
                      className={`block h-2 rounded ${up ? 'bg-rose-400' : 'bg-emerald-400'}`}
                      style={{ width: `${Math.max(4, (Math.abs(num(s.delta)) / biggest) * 100)}%` }}
                    />
                  </span>
                  <span
                    className={`w-32 shrink-0 text-end tabular-nums ${up ? 'text-semantic-error' : 'text-semantic-success'}`}
                  >
                    {signed(s.delta, currency)}
                  </span>
                </div>
                {(s.comment || s.evidence.length > 0) && (
                  <div className="mt-0.5 text-xs text-content-secondary">
                    {s.comment}
                    {s.evidence.length > 0 && (
                      <span className="text-content-tertiary">
                        {s.comment ? ' · ' : ''}
                        {s.evidence.map((e) => `${evidenceKindLabel(t, e.kind)}: ${e.ref}`).join(' · ')}
                      </span>
                    )}
                  </div>
                )}
              </li>
            );
          })}
          {data.other_count > 0 && (
            <li className="flex items-center justify-between py-2 text-content-secondary">
              <span>
                {t('cost_control.ladder_other', { defaultValue: 'Smaller moves on other lines: {{n}}', n: data.other_count })}
              </span>
              <span className="tabular-nums">{signed(data.other, currency)}</span>
            </li>
          )}
          <li className="flex items-center justify-between py-2 font-medium text-content-primary">
            <span>
              {data.end_column.status === 'live'
                ? t('cost_control.ladder_end_today', { defaultValue: 'Forecast today' })
                : t('cost_control.ladder_end', {
                    defaultValue: 'Forecast on {{date}}',
                    date: fmtDate(data.end_column.taken_on),
                  })}
            </span>
            <span className="tabular-nums">{fmtCurrency(data.end, currency)}</span>
          </li>
        </ol>
      )}
    </div>
  );
}

function Matrix({ projectId, currency }: { projectId: string; currency: string }) {
  const { t } = useTranslation();
  const [all, setAll] = useState(false);
  const matrix = useQuery({
    queryKey: ['cost-control', 'compare', projectId],
    queryFn: () => costControlApi.compare(projectId),
  });
  const data = matrix.data;
  const rows = useMemo(
    () => (data?.rows ?? []).filter((r) => all || Math.abs(num(r.delta)) >= 0.005),
    [data, all],
  );
  if (matrix.isLoading) return <Skeleton className="h-40 w-full" />;
  if (matrix.error || !data) return <p className="text-sm text-semantic-error">{getErrorMessage(matrix.error)}</p>;
  return (
    <div className="space-y-2">
      <label className="flex items-center gap-2 text-xs text-content-secondary">
        <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />
        {t('cost_control.compare_all_lines', { defaultValue: 'Show lines that did not move too' })}
      </label>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="border-b border-border-light text-2xs uppercase tracking-wide text-content-tertiary">
              <th className="py-1.5 text-start font-semibold">{t('cost_control.col_code', { defaultValue: 'Code' })}</th>
              {data.columns.map((c, i) => (
                <th key={c.id ?? `live-${i}`} className="py-1.5 ps-3 text-end font-semibold">
                  <span className="block normal-case">{columnTitle(t, c)}</span>
                  <span className="block font-normal normal-case">
                    {fmtDate(c.taken_on)} · {snapshotStatusLabel(t, c.status)}
                  </span>
                </th>
              ))}
              <th className="py-1.5 ps-3 text-end font-semibold">
                {t('cost_control.compare_change', { defaultValue: 'Change' })}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-light">
            {rows.map((r) => (
              <tr key={r.key}>
                <td className="max-w-[16rem] truncate py-1.5 text-content-primary" title={r.description}>
                  {rowName(t, r.kind, r.code, r.description)}
                </td>
                {r.values.map((v, i) => (
                  <td key={i} className="py-1.5 ps-3 text-end tabular-nums text-content-secondary">
                    {v === null ? '-' : fmtCurrency(v, currency)}
                  </td>
                ))}
                <td
                  className={`py-1.5 ps-3 text-end tabular-nums ${
                    num(r.delta) > 0.005
                      ? 'text-semantic-error'
                      : num(r.delta) < -0.005
                        ? 'text-semantic-success'
                        : 'text-content-tertiary'
                  }`}
                >
                  {signed(r.delta, currency)}
                  {r.delta_pct && <span className="ms-1 text-2xs">({fmtNumber(r.delta_pct, 1)}%)</span>}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={data.columns.length + 2} className="py-3 text-content-tertiary">
                  {t('cost_control.compare_none', { defaultValue: 'No line moved across these snapshots.' })}
                </td>
              </tr>
            )}
          </tbody>
          <tfoot>
            <tr className="border-t border-border font-semibold text-content-primary">
              <td className="py-1.5">{t('cost_control.total', { defaultValue: 'Total' })}</td>
              {data.columns.map((c, i) => (
                <td key={c.id ?? `live-${i}`} className="py-1.5 ps-3 text-end tabular-nums">
                  {fmtCurrency(c.total, currency)}
                </td>
              ))}
              <td />
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}

export interface SnapshotCompareProps {
  projectId: string;
  snapshots: SnapshotSummary[];
  currency: string;
}

export function SnapshotCompare({ projectId, snapshots, currency }: SnapshotCompareProps) {
  const { t } = useTranslation();
  const [view, setView] = useState<'ladder' | 'matrix'>('ladder');
  const frozen = useMemo(() => snapshots.filter((s) => s.status === 'frozen'), [snapshots]);
  if (frozen.length === 0) {
    return (
      <p className="text-sm text-content-tertiary">
        {t('cost_control.compare_empty', {
          defaultValue: 'Freeze a first snapshot, then every later one is compared with it here, line by line.',
        })}
      </p>
    );
  }
  return (
    <div className="space-y-3">
      <TabBar
        variant="segmented"
        size="sm"
        ariaLabel={t('cost_control.compare_view', { defaultValue: 'Comparison view' })}
        activeId={view}
        onChange={(next) => setView(next)}
        tabs={[
          { id: 'ladder', label: t('cost_control.compare_ladder', { defaultValue: 'Step by step' }) },
          { id: 'matrix', label: t('cost_control.compare_matrix', { defaultValue: 'Side by side' }) },
        ]}
      />
      {view === 'ladder' ? (
        <Ladder projectId={projectId} frozen={frozen} currency={currency} />
      ) : (
        <Matrix projectId={projectId} currency={currency} />
      )}
    </div>
  );
}
