// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Broker Performance (v3124) — sortable leaderboard table.
 *
 * Columns: broker name, leads assigned, reservations, sales, conv-rate,
 * GMV attributed, commission earned. Sales directors use this to spot
 * the top 20% who deserve a Q-end bonus and the bottom 20% who need
 * coaching or contract renegotiation.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { ArrowDown, ArrowUp } from 'lucide-react';
import {
  getBrokerPerformance,
  type BrokerLeaderboardRow,
  type BrokerPerformanceResponse,
} from '../api';
import {
  DashboardEmpty,
  DashboardSkeleton,
  fmtCompactNumber,
  num,
} from './_shared';
import { fmtPercent } from '@/shared/lib/formatters';
import { compareNames } from '@/shared/lib/collator';

interface BrokerPerformanceWidgetProps {
  since?: string;
  until?: string;
}

type SortKey =
  | 'broker_name'
  | 'leads_assigned'
  | 'reservations_closed'
  | 'sales_closed'
  | 'conversion_rate_pct'
  | 'gmv'
  | 'commission_earned';

function maxAmount(rows: { amount: number | string }[]): number {
  return rows.reduce((m, r) => Math.max(m, num(r.amount)), 0);
}

export function BrokerPerformanceWidget({
  since,
  until,
}: BrokerPerformanceWidgetProps) {
  const { t } = useTranslation();
  const [sortKey, setSortKey] = useState<SortKey>('gmv');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');

  const { data, isLoading, error } = useQuery<BrokerPerformanceResponse>({
    queryKey: ['propdev-analytics-broker-performance', since, until],
    queryFn: () => getBrokerPerformance({ since, until }),
    staleTime: 60_000,
  });

  const sortedRows = useMemo(() => {
    if (!data) return [];
    const arr = [...data.rows];
    arr.sort((a, b) => {
      const dir = sortDir === 'asc' ? 1 : -1;
      if (sortKey === 'broker_name') {
        return compareNames(a.broker_name, b.broker_name) * dir;
      }
      if (sortKey === 'gmv') {
        return (maxAmount(a.gmv) - maxAmount(b.gmv)) * dir;
      }
      if (sortKey === 'commission_earned') {
        return (
          (maxAmount(a.commission_earned) - maxAmount(b.commission_earned)) *
          dir
        );
      }
      const aVal = num(a[sortKey] as number | string);
      const bVal = num(b[sortKey] as number | string);
      return (aVal - bVal) * dir;
    });
    return arr;
  }, [data, sortKey, sortDir]);

  if (isLoading) return <DashboardSkeleton variant="bars" rows={5} />;
  if (error) {
    return (
      <DashboardEmpty
        title={t('propdev.dashboards.bp.error', {
          defaultValue: 'Could not load broker performance',
        })}
        description={(error as Error)?.message ?? ''}
      />
    );
  }
  if (!data || data.total_brokers === 0) {
    return (
      <DashboardEmpty
        title={t('propdev.dashboards.bp.empty_title', {
          defaultValue: 'No active brokers',
        })}
        description={t('propdev.dashboards.bp.empty_desc', {
          defaultValue:
            'Once brokers are activated and start carrying leads, the leaderboard fills in.',
        })}
      />
    );
  }

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir(key === 'broker_name' ? 'asc' : 'desc');
    }
  };

  return (
    <section
      role="region"
      aria-label={t('propdev.dashboards.bp.aria_label', {
        defaultValue: 'Broker performance leaderboard',
      })}
      className="space-y-3"
    >
      <header>
        <h3 className="text-sm font-semibold text-content-primary">
          {t('propdev.dashboards.bp.title', {
            defaultValue: 'Broker performance',
          })}
        </h3>
        <p className="text-xs text-content-tertiary">
          {t('propdev.dashboards.bp.subtitle', {
            defaultValue:
              'Leads, reservations, sales, GMV and commission per broker.',
          })}
        </p>
      </header>

      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse text-xs">
          <thead>
            <tr className="border-b border-divider text-content-tertiary">
              <SortHeader
                label={t('propdev.dashboards.bp.col_broker', {
                  defaultValue: 'Broker',
                })}
                active={sortKey === 'broker_name'}
                dir={sortDir}
                onClick={() => toggleSort('broker_name')}
                align="left"
              />
              <SortHeader
                label={t('propdev.dashboards.bp.col_leads', {
                  defaultValue: 'Leads',
                })}
                active={sortKey === 'leads_assigned'}
                dir={sortDir}
                onClick={() => toggleSort('leads_assigned')}
              />
              <SortHeader
                label={t('propdev.dashboards.bp.col_res', {
                  defaultValue: 'Res.',
                })}
                active={sortKey === 'reservations_closed'}
                dir={sortDir}
                onClick={() => toggleSort('reservations_closed')}
              />
              <SortHeader
                label={t('propdev.dashboards.bp.col_sales', {
                  defaultValue: 'Sales',
                })}
                active={sortKey === 'sales_closed'}
                dir={sortDir}
                onClick={() => toggleSort('sales_closed')}
              />
              <SortHeader
                label={t('propdev.dashboards.bp.col_conv', {
                  defaultValue: 'Conv %',
                })}
                active={sortKey === 'conversion_rate_pct'}
                dir={sortDir}
                onClick={() => toggleSort('conversion_rate_pct')}
              />
              <SortHeader
                label={t('propdev.dashboards.bp.col_gmv', {
                  defaultValue: 'GMV',
                })}
                active={sortKey === 'gmv'}
                dir={sortDir}
                onClick={() => toggleSort('gmv')}
              />
              <SortHeader
                label={t('propdev.dashboards.bp.col_commission', {
                  defaultValue: 'Commission',
                })}
                active={sortKey === 'commission_earned'}
                dir={sortDir}
                onClick={() => toggleSort('commission_earned')}
              />
            </tr>
          </thead>
          <tbody>
            {sortedRows.map((r: BrokerLeaderboardRow) => (
              <tr key={r.broker_id} className="border-b border-divider/50">
                <td className="px-2 py-1.5 font-medium text-content-primary">
                  {r.broker_name || '—'}
                </td>
                <td className="px-2 py-1.5 text-right text-content-secondary">
                  {r.leads_assigned}
                </td>
                <td className="px-2 py-1.5 text-right text-content-secondary">
                  {r.reservations_closed}
                </td>
                <td className="px-2 py-1.5 text-right text-content-secondary">
                  {r.sales_closed}
                </td>
                <td className="px-2 py-1.5 text-right text-content-secondary">
                  {fmtPercent(num(r.conversion_rate_pct))}
                </td>
                <td className="px-2 py-1.5 text-right">
                  <CurrencyStack rows={r.gmv} />
                </td>
                <td className="px-2 py-1.5 text-right">
                  <CurrencyStack rows={r.commission_earned} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function SortHeader({
  label,
  active,
  dir,
  onClick,
  align = 'right',
}: {
  label: string;
  active: boolean;
  dir: 'asc' | 'desc';
  onClick: () => void;
  align?: 'left' | 'right';
}) {
  const Icon = dir === 'asc' ? ArrowUp : ArrowDown;
  return (
    <th
      scope="col"
      className={`px-2 py-1.5 font-medium ${align === 'right' ? 'text-right' : 'text-left'}`}
    >
      <button
        type="button"
        onClick={onClick}
        aria-sort={active ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}
        className={
          `inline-flex items-center gap-1 ${
            align === 'right' ? 'flex-row-reverse' : ''
          } ` +
          (active
            ? 'text-content-primary'
            : 'text-content-tertiary hover:text-content-primary')
        }
      >
        {active && <Icon size={10} aria-hidden="true" />}
        <span>{label}</span>
      </button>
    </th>
  );
}

function CurrencyStack({
  rows,
}: {
  rows: { currency: string; amount: number | string }[];
}) {
  if (rows.length === 0) return <span className="text-content-tertiary">—</span>;
  return (
    <div className="flex flex-wrap justify-end gap-1">
      {rows.map((r) => (
        <span
          key={r.currency}
          className="rounded bg-surface-secondary px-1.5 py-0.5 text-2xs"
        >
          <span className="font-medium">{r.currency}</span>{' '}
          {fmtCompactNumber(num(r.amount))}
        </span>
      ))}
    </div>
  );
}
