// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Every phase of the cost on one tree: budget, estimate, best tender, award,
// changes, commitment, pending changes, measured, certified, invoiced, paid
// and forecast. Read across, a row is the story of one part of the building;
// read down, a column is one phase of the whole project. The percent view puts
// each phase against the plan, and progress and invoicing against the
// commitment.
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';

import { Skeleton } from '@/shared/ui';
import { TabBar } from '@/shared/ui/TabBar';
import { fmtCurrency, fmtNumber } from '@/shared/lib/formatters';
import { getErrorMessage } from '@/shared/lib/api';
import { costControlApi, num, type PhaseRow } from './api';
import { layerLabel } from './labels';

export interface PhaseComparisonProps {
  projectId: string;
  currency: string;
}

export function PhaseComparison({ projectId, currency }: PhaseComparisonProps) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<'amount' | 'pct'>('amount');
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const phases = useQuery({
    queryKey: ['cost-control', 'phases', projectId],
    queryFn: () => costControlApi.phases(projectId),
  });
  const data = phases.data;

  const visible = useMemo(() => {
    if (!data) return [];
    const parentOf = new Map(data.rows.map((r) => [r.key, r.parent_key]));
    const hidden = (row: PhaseRow): boolean => {
      let parent = row.parent_key;
      while (parent) {
        if (collapsed.has(parent)) return true;
        parent = parentOf.get(parent) ?? null;
      }
      return false;
    };
    return data.rows.filter((r) => !hidden(r));
  }, [data, collapsed]);

  if (phases.isLoading) return <Skeleton className="h-64 w-full" />;
  if (phases.error || !data) return <p className="text-sm text-semantic-error">{getErrorMessage(phases.error)}</p>;

  const hasChildren = new Set(data.rows.map((r) => r.parent_key).filter(Boolean) as string[]);
  const toggle = (key: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const name = (row: PhaseRow): string => {
    if (row.kind === 'unassigned') return t('cost_control.row_unassigned', { defaultValue: 'Not on any cost line' });
    if (row.kind === 'allowance')
      return t('cost_control.row_allowance', { defaultValue: 'Allowance on the account, not broken down yet' });
    return `${row.code} ${row.description}`.trim();
  };
  const cell = (row: PhaseRow, layer: (typeof data.layers)[number]) => {
    if (mode === 'pct') {
      const p = row.pct[layer];
      return p === null ? '-' : `${fmtNumber(p, 1)}%`;
    }
    return num(row.values[layer]) === 0 ? '-' : fmtCurrency(row.values[layer], currency);
  };
  const pctCell = (value: string | null) => (value === null ? '-' : `${fmtNumber(value, 1)}%`);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <TabBar
          variant="segmented"
          size="sm"
          ariaLabel={t('cost_control.phases_mode', { defaultValue: 'Show as' })}
          activeId={mode}
          onChange={(next) => setMode(next)}
          tabs={[
            { id: 'amount', label: t('cost_control.phases_amounts', { defaultValue: 'Amounts' }) },
            { id: 'pct', label: t('cost_control.phases_pct', { defaultValue: '% of plan' }) },
          ]}
        />
        <p className="text-xs text-content-tertiary">
          {mode === 'pct'
            ? t('cost_control.phases_pct_hint', {
                defaultValue: 'Each phase against the plan (budget, or the estimate where no budget is set).',
              })
            : t('cost_control.phases_hint', {
                defaultValue: 'Accounts carry the sum of everything below them. Click an account to fold it.',
              })}
        </p>
      </div>
      {data.rows.length === 0 ? (
        <p className="text-sm text-content-tertiary">
          {t('cost_control.phases_empty', { defaultValue: 'No cost lines yet, so there is nothing to compare.' })}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border-light">
          <table className="w-full min-w-[1100px] text-xs">
            <thead className="bg-surface-secondary/60">
              <tr className="text-2xs uppercase tracking-wide text-content-tertiary">
                <th className="sticky start-0 bg-surface-secondary px-3 py-2 text-start font-semibold">
                  {t('cost_control.col_code', { defaultValue: 'Code' })}
                </th>
                {data.layers.map((layer) => (
                  <th key={layer} className="px-2 py-2 text-end font-semibold">
                    {layerLabel(t, layer)}
                  </th>
                ))}
                <th className="px-2 py-2 text-end font-semibold">
                  {t('cost_control.phases_progress', { defaultValue: 'Measured % of committed' })}
                </th>
                <th className="px-2 py-2 text-end font-semibold">
                  {t('cost_control.phases_invoiced', { defaultValue: 'Invoiced % of committed' })}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-light">
              {visible.map((row) => {
                const account = row.kind === 'account';
                const foldable = hasChildren.has(row.key);
                return (
                  <tr key={row.key} className={account ? 'font-semibold text-content-primary' : 'text-content-secondary'}>
                    <td className="sticky start-0 max-w-[20rem] truncate bg-surface-primary px-3 py-1.5" title={name(row)}>
                      <span style={{ paddingInlineStart: `${(row.level - 1) * 14}px` }} className="inline-block">
                        {foldable ? (
                          <button
                            type="button"
                            className="hover:underline"
                            onClick={() => toggle(row.key)}
                            aria-expanded={!collapsed.has(row.key)}
                          >
                            {collapsed.has(row.key) ? '▸ ' : '▾ '}
                            {name(row)}
                          </button>
                        ) : (
                          name(row)
                        )}
                      </span>
                    </td>
                    {data.layers.map((layer) => (
                      <td key={layer} className="px-2 py-1.5 text-end tabular-nums">
                        {cell(row, layer)}
                      </td>
                    ))}
                    <td className="px-2 py-1.5 text-end tabular-nums">{pctCell(row.progress_pct)}</td>
                    <td className="px-2 py-1.5 text-end tabular-nums">{pctCell(row.invoiced_pct)}</td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr className="border-t border-border bg-surface-secondary/60 font-semibold text-content-primary">
                <td className="sticky start-0 bg-surface-secondary px-3 py-2">
                  {t('cost_control.total', { defaultValue: 'Total' })}
                </td>
                {data.layers.map((layer) => (
                  <td key={layer} className="px-2 py-2 text-end tabular-nums">
                    {cell(data.totals, layer)}
                  </td>
                ))}
                <td className="px-2 py-2 text-end tabular-nums">{pctCell(data.totals.progress_pct)}</td>
                <td className="px-2 py-2 text-end tabular-nums">{pctCell(data.totals.invoiced_pct)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </div>
  );
}
