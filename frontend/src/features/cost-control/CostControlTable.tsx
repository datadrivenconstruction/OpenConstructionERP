// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The cost control table. Seven money columns, read left to right as the life
// of a cost: what was planned, what it was let for, what changes added, what it
// will cost, the difference, what is certified, what is paid. Cost lines are
// grouped under their control account with a subtotal, so a 300-line project
// still reads as a dozen groups.
//
// By contract the plan has no place: a budget belongs to a cost line, not to a
// contractor. That view drops the planned and difference columns, and a last
// row carries the part of the forecast no contract holds yet. The footer is
// always the project total the server added up, so it matches the figures at
// the top of the page whatever the search hides.
import { Fragment, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronRight } from 'lucide-react';

import { fmtCurrency, fmtPercent } from '@/shared/lib/formatters';
import { sumMoneyStrings } from '@/shared/lib/exactDecimal';
import { num, type CostControlAccount, type CostControlAxis, type CostControlRow } from './api';
import { sourceLabel, sourceTone } from './labels';

interface Group {
  key: string;
  title: string;
  rows: CostControlRow[];
}

const MONEY_COLUMNS = [
  'planned',
  'awarded',
  'changes',
  'forecast',
  'variance',
  'measured',
  'certified',
  'invoiced',
  'paid',
] as const;
type MoneyColumn = (typeof MONEY_COLUMNS)[number];
const PLAN_COLUMNS: ReadonlySet<MoneyColumn> = new Set<MoneyColumn>(['planned', 'variance']);

/** Exact decimal subtotal of one column; the server's figures are added as strings, never as floats. */
function sum(rows: CostControlRow[], col: MoneyColumn): string {
  return sumMoneyStrings(rows.map((r) => r[col]));
}

function varianceClass(value: number): string {
  if (value > 0.005) return 'text-semantic-error';
  if (value < -0.005) return 'text-semantic-success';
  return 'text-content-tertiary';
}

export interface CostControlTableProps {
  axis: CostControlAxis;
  rows: CostControlRow[];
  /** The project totals from the server; the footer shows these, not a sum of the visible rows. */
  totals: Record<string, string>;
  accounts: CostControlAccount[];
  currency: string;
  onOpenLine: (row: CostControlRow) => void;
  /** Opens the list of lines behind the "not on any cost line" row. */
  onOpenUnassigned?: () => void;
}

export function CostControlTable({
  axis,
  rows,
  totals,
  accounts,
  currency,
  onOpenLine,
  onOpenUnassigned,
}: CostControlTableProps) {
  const { t } = useTranslation();
  const columns = axis === 'cost_line' ? MONEY_COLUMNS : MONEY_COLUMNS.filter((c) => !PLAN_COLUMNS.has(c));

  const special = (row: CostControlRow): string => {
    switch (row.kind) {
      case 'unassigned':
        return t('cost_control.row_unassigned', { defaultValue: 'Not on any cost line' });
      case 'changes_without_contract':
        return t('cost_control.row_changes_without_contract', {
          defaultValue: 'Approved changes not on a contract ({{n}})',
          n: Number(row.description || 0),
        });
      case 'other':
        return t('cost_control.row_other', { defaultValue: 'Purchase orders and other commitments' });
      case 'remaining':
        return t('cost_control.row_remaining', { defaultValue: 'Not on a contract yet' });
      case 'allowance':
        return t('cost_control.row_allowance', {
          defaultValue: 'Allowance on the account, not broken down yet',
        });
      default:
        return row.description;
    }
  };

  const groups = useMemo<Group[]>(() => {
    if (axis !== 'cost_line') {
      return [{ key: 'all', title: '', rows }];
    }
    const byId = new Map(accounts.map((a) => [a.id, a]));
    const map = new Map<string, Group>();
    const order: string[] = [];
    const push = (key: string, title: string, row: CostControlRow) => {
      if (!map.has(key)) {
        map.set(key, { key, title, rows: [] });
        order.push(key);
      }
      map.get(key)!.rows.push(row);
    };
    for (const row of rows) {
      if (row.kind !== 'cost_line' && row.kind !== 'allowance') {
        push('__special', t('cost_control.group_other', { defaultValue: 'Not yet on a cost line' }), row);
        continue;
      }
      const acct = row.account_id ? byId.get(row.account_id) : undefined;
      if (acct) push(acct.id, `${acct.code} ${acct.title || acct.name}`.trim(), row);
      else
        push(
          '__none',
          t('cost_control.group_no_account_suspense', {
            defaultValue: 'No account (suspense): cost lines not yet on the cost structure',
          }),
          row,
        );
    }
    // Accounts in code order, the two catch-all groups last.
    const rank = (key: string) => (key === '__special' ? 2 : key === '__none' ? 1 : 0);
    return order
      .map((k) => map.get(k)!)
      .sort((a, b) => rank(a.key) - rank(b.key) || a.title.localeCompare(b.title, undefined, { numeric: true }));
  }, [axis, rows, accounts, t]);

  const headers: Record<MoneyColumn, string> = {
    planned: t('cost_control.col_planned', { defaultValue: 'Planned' }),
    awarded: t('cost_control.col_awarded', { defaultValue: 'Awarded' }),
    changes: t('cost_control.col_changes', { defaultValue: 'Changes' }),
    forecast: t('cost_control.col_forecast', { defaultValue: 'Forecast' }),
    variance: t('cost_control.col_variance', { defaultValue: 'Difference' }),
    measured: t('cost_control.col_measured', { defaultValue: 'Measured' }),
    certified: t('cost_control.col_certified', { defaultValue: 'Certified' }),
    invoiced: t('cost_control.col_invoiced', { defaultValue: 'Invoiced' }),
    paid: t('cost_control.col_paid', { defaultValue: 'Paid' }),
  };

  const showGroupHeaders = groups.length > 1 || (groups[0] && groups[0].title !== '');

  const cell = (row: CostControlRow, col: MoneyColumn) => {
    switch (col) {
      case 'changes':
        return (
          <td key={col} className="px-3 py-2.5 text-right tabular-nums text-content-secondary">
            {num(row.changes) === 0 ? '-' : fmtCurrency(row.changes, currency)}
          </td>
        );
      case 'forecast':
        return (
          <td key={col} className="px-3 py-2.5 text-right">
            <div className="flex flex-col items-end gap-0.5">
              <span className="font-semibold tabular-nums text-content-primary">
                {fmtCurrency(row.forecast, currency)}
              </span>
              {row.kind !== 'remaining' && (
                <span className={`rounded px-1.5 py-px text-2xs font-medium ${sourceTone(row.forecast_source)}`}>
                  {sourceLabel(t, row.forecast_source)}
                </span>
              )}
            </div>
          </td>
        );
      case 'variance': {
        const variance = num(row.variance);
        return (
          <td key={col} className={`px-3 py-2.5 text-right tabular-nums font-medium ${varianceClass(variance)}`}>
            {num(row.planned) === 0 ? '-' : fmtCurrency(variance, currency)}
            {row.variance_pct && num(row.planned) !== 0 && (
              <div className="text-2xs font-normal">
                {variance > 0 ? '+' : ''}
                {fmtPercent(row.variance_pct)}
              </div>
            )}
          </td>
        );
      }
      default:
        return (
          <td key={col} className="px-3 py-2.5 text-right tabular-nums text-content-secondary">
            {fmtCurrency(row[col], currency)}
          </td>
        );
    }
  };

  return (
    <div className="overflow-x-auto rounded-xl border border-border-light">
      <table
        className={`w-full text-sm ${axis === 'cost_line' ? 'min-w-[1080px]' : 'min-w-[880px]'}`}
        data-testid="cost-control-table"
      >
        <thead>
          <tr className="border-b border-border-light bg-surface-secondary/60 text-left text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
            <th className="py-2.5 pl-4 pr-2">
              {axis === 'cost_line'
                ? t('cost_control.col_cost_line', { defaultValue: 'Cost line' })
                : t('cost_control.col_contract', { defaultValue: 'Contract' })}
            </th>
            {columns.map((col) => (
              <th key={col} className="px-3 py-2.5 text-right">
                {headers[col]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => (
            <Fragment key={group.key}>
              {showGroupHeaders && group.title && (
                <tr className="border-b border-border-light bg-surface-secondary/30">
                  <td className="py-2 pl-4 pr-2 text-xs font-semibold text-content-primary">{group.title}</td>
                  {columns.map((col) => {
                    const value = sum(group.rows, col);
                    return (
                      <td
                        key={col}
                        className={`px-3 py-2 text-right text-xs font-semibold tabular-nums ${
                          col === 'variance' ? varianceClass(num(value)) : 'text-content-primary'
                        }`}
                      >
                        {fmtCurrency(value, currency)}
                      </td>
                    );
                  })}
                </tr>
              )}
              {group.rows.map((row) => {
                const open =
                  row.kind === 'cost_line'
                    ? () => onOpenLine(row)
                    : row.kind === 'unassigned' && onOpenUnassigned
                      ? onOpenUnassigned
                      : undefined;
                const clickable = open !== undefined;
                const label = special(row);
                return (
                  <tr
                    key={row.key}
                    className={`border-b border-border-light last:border-0 ${
                      clickable
                        ? 'cursor-pointer hover:bg-surface-secondary/50 focus-visible:bg-surface-secondary/50 focus-visible:outline-none'
                        : ''
                    }`}
                    onClick={open}
                    onKeyDown={
                      open
                        ? (e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault();
                              open();
                            }
                          }
                        : undefined
                    }
                    tabIndex={clickable ? 0 : undefined}
                    role={clickable ? 'button' : undefined}
                    aria-label={clickable ? `${row.code} ${label}`.trim() : undefined}
                    data-testid={`cost-control-row-${row.key}`}
                  >
                    <td className="py-2.5 pl-4 pr-2">
                      <div className="flex items-center gap-2">
                        {row.code && (
                          <span className="shrink-0 font-mono text-xs text-content-tertiary">{row.code}</span>
                        )}
                        <div className="min-w-0">
                          <div className="truncate text-content-primary">{label}</div>
                          {row.kind === 'remaining' && (
                            <div className="text-2xs text-content-tertiary">
                              {t('cost_control.row_remaining_hint', {
                                defaultValue: 'Work not yet awarded and your own forecasts',
                              })}
                            </div>
                          )}
                        </div>
                        {clickable && <ChevronRight size={14} className="ml-auto shrink-0 text-content-quaternary" />}
                      </div>
                    </td>
                    {columns.map((col) => cell(row, col))}
                  </tr>
                );
              })}
            </Fragment>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-border bg-surface-secondary/60 font-bold">
            <td className="py-3 pl-4 pr-2 text-content-primary">
              {t('cost_control.total', { defaultValue: 'Project total' })}
            </td>
            {columns.map((col) => {
              const value = num(totals[col]);
              return (
                <td
                  key={col}
                  className={`px-3 py-3 text-right tabular-nums ${
                    col === 'variance' ? varianceClass(value) : 'text-content-primary'
                  }`}
                >
                  {fmtCurrency(totals[col] ?? 0, currency)}
                </td>
              );
            })}
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
